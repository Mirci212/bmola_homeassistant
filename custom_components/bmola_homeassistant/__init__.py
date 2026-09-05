"""Bmola / SanNcco Air Purifier Home Assistant Integration."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Callable

import websockets

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

DOMAIN = "bmola_homeassistant"
WS_URL = "wss://app.iotstars.cn/con/websocket"
PLATFORMS: list[Platform] = [
    Platform.FAN,
    Platform.SENSOR,
    Platform.SWITCH,
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Bmola integration from a config entry."""
    device_id = str(entry.data.get("device_id", "")).strip()
    user_name = str(entry.data.get("user_name", "")).strip()
    password = str(entry.data.get("password", "")).strip()

    hub = BmolaHub(hass, entry, device_id, user_name, password)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = hub

    # Start WebSocket connection loop
    hub.start()

    # Forward entry setups to platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Listen for options/config changes
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a Bmola config entry."""
    hub: BmolaHub = hass.data[DOMAIN].get(entry.entry_id)
    if hub:
        await hub.stop()

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)

    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the config entry when options are updated."""
    await hass.config_entries.async_reload(entry.entry_id)


class BmolaHub:
    """Hub class for WebSocket/STOMP communication with Bmola cloud."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        device_id: str,
        user_name: str,
        password: str = "",
    ) -> None:
        """Initialize the Bmola hub."""
        self.hass = hass
        self.entry = entry
        self.device_id = str(device_id)
        self.user_name = str(user_name)
        self.password = str(password)
        self.product_uid = "SanNcco Air Purifier"

        self.ws: websockets.WebSocketClientProtocol | None = None
        self.connected = False
        self.sub_counter = 1
        self.callbacks: list[Callable[[], None]] = []
        self.states: dict[int, Any] = {}

        self._running = False
        self._task: asyncio.Task | None = None
        self._connected_event = asyncio.Event()

    def register_callback(self, callback: Callable[[], None]) -> Callable[[], None]:
        """Register a callback for state changes and return unregister function."""
        self.callbacks.append(callback)

        def remove_callback() -> None:
            if callback in self.callbacks:
                self.callbacks.remove(callback)

        return remove_callback

    def _notify_callbacks(self) -> None:
        """Notify all registered listeners of state changes."""
        for cb in self.callbacks:
            try:
                cb()
            except Exception as err:
                _LOGGER.error("Fehler beim Ausführen des Callbacks: %s", err)

    def start(self) -> None:
        """Start the background connection loop."""
        self._running = True
        if hasattr(self.entry, "async_create_background_task"):
            self._task = self.entry.async_create_background_task(
                self.hass, self.connect_loop(), "bmola_connect_loop"
            )
        else:
            self._task = self.hass.async_create_task(self.connect_loop())

    async def stop(self) -> None:
        """Stop connection loop and close WebSocket."""
        self._running = False
        self.connected = False
        self._connected_event.clear()

        if self.ws:
            try:
                await self.ws.close()
            except Exception:
                pass
            self.ws = None

        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        self._notify_callbacks()

    async def send_stomp(self, frame_str: str) -> None:
        """Send a STOMP frame terminated with NULL byte."""
        if self.ws:
            try:
                await self.ws.send(frame_str + "\x00")
            except Exception as err:
                _LOGGER.error("Fehler beim Senden des STOMP Frames: %s", err)

    async def send_command(
        self, func_id: int | str, data_type: int | str, value: Any
    ) -> None:
        """Send command frame to /dev/update."""
        if not self.ws or not self.connected:
            _LOGGER.warning(
                "Befehl kann nicht gesendet werden: Bmola nicht verbunden (fi=%s, v=%s)",
                func_id,
                value,
            )
            return

        self.sub_counter += 1
        sub_id = f"sub-{self.sub_counter}"
        frame = (
            "SUBSCRIBE\n"
            f"did:{self.device_id}\n"
            f"oid:{self.user_name}\n"
            f"fi:{func_id}\n"
            f"dt:{data_type}\n"
            f"v:{value}\n"
            f"id:{sub_id}\n"
            f"destination:/dev/update\n\n"
        )
        _LOGGER.debug(
            "Sende Steuerbefehl: did=%s, func_id=%s, dt=%s, val=%s (sub_id=%s)",
            self.device_id,
            func_id,
            data_type,
            value,
            sub_id,
        )
        await self.send_stomp(frame)

    async def _read_inbound(self, ws: websockets.WebSocketClientProtocol) -> None:
        """Read and process frames from WebSocket."""
        try:
            async for message in ws:
                if not self._running:
                    break
                if isinstance(message, bytes):
                    message = message.decode("utf-8", errors="ignore")

                frames = str(message).split("\x00")
                for frame in frames:
                    frame = frame.strip()
                    if not frame:
                        continue
                    if frame.startswith("CONNECTED"):
                        _LOGGER.debug("STOMP CONNECTED Frame empfangen.")
                        self._connected_event.set()
                    elif "destination:/user/" in frame or "{" in frame:
                        self._parse_frame(frame)
        except asyncio.CancelledError:
            pass
        except Exception as err:
            _LOGGER.debug("Inbound WebSocket Reader beendet: %s", err)

    async def connect_loop(self) -> None:
        """Maintain persistent connection with reconnects and exponential backoff."""
        retry_delay = 3
        max_retry_delay = 30

        while self._running:
            self.connected = False
            self.ws = None
            self._connected_event.clear()
            self._notify_callbacks()

            connected_at: float | None = None

            try:
                _LOGGER.info(
                    "Verbinde mit Bmola Cloud: %s (login=%s###%s)",
                    WS_URL,
                    self.user_name,
                    self.device_id,
                )
                async with websockets.connect(
                    WS_URL,
                    open_timeout=15,
                    close_timeout=5,
                    ping_interval=20,
                    ping_timeout=20,
                ) as ws:
                    self.ws = ws

                    # 1. Send CONNECT frame with login:user###device_id
                    conn_frame = (
                        "CONNECT\n"
                        f"login:{self.user_name}###{self.device_id}\n"
                        f"passcode:{self.password}\n"
                        "accept-version:1.2,1.1,1.0\n"
                        "heart-beat:10000,10000\n\n"
                    )
                    await self.send_stomp(conn_frame)

                    # Start inbound message processor task
                    inbound_task = asyncio.create_task(self._read_inbound(ws))

                    # 2. Wait for CONNECTED frame with timeout
                    try:
                        await asyncio.wait_for(
                            self._connected_event.wait(), timeout=10.0
                        )
                    except asyncio.TimeoutError:
                        _LOGGER.warning(
                            "Zeitüberschreitung beim Warten auf STOMP CONNECTED Frame."
                        )
                        inbound_task.cancel()
                        await ws.close()
                        continue

                    # Handshake successful
                    self.connected = True
                    connected_at = self.hass.loop.time()
                    _LOGGER.info(
                        "Bmola STOMP WebSocket erfolgreich verbunden und authentifiziert (Gerät %s).",
                        self.device_id,
                    )
                    self._notify_callbacks()

                    # 3. Subscribe to user update channel
                    sub_user = (
                        "SUBSCRIBE\n"
                        f"client:subscribe request from {self.user_name}\n"
                        "id:sub-0\n"
                        f"destination:/user/{self.user_name}/update\n\n"
                    )
                    await self.send_stomp(sub_user)

                    # 4. Subscribe to dev/init to trigger status flush
                    sub_dev_init = (
                        "SUBSCRIBE\n"
                        f"did:{self.device_id}\n"
                        "id:sub-1\n"
                        "destination:/dev/init\n\n"
                    )
                    await self.send_stomp(sub_dev_init)

                    # Wait until inbound task finishes
                    await inbound_task

            except asyncio.CancelledError:
                break
            except Exception as e:
                _LOGGER.warning("Bmola WebSocket Verbindung unterbrochen/Fehler: %s", e)
            finally:
                self.connected = False
                self.ws = None
                self._connected_event.clear()
                self._notify_callbacks()

            # If connection was stable for >15 seconds, reset backoff
            if connected_at and (self.hass.loop.time() - connected_at) > 15:
                retry_delay = 3

            if self._running:
                _LOGGER.info(
                    "Bmola automatischer Reconnect in %d Sekunden...", retry_delay
                )
                await asyncio.sleep(retry_delay)
                retry_delay = min(max_retry_delay, retry_delay * 2)

    def _parse_frame(self, frame: str) -> None:
        """Parse incoming STOMP frame body."""
        try:
            parts = frame.split("\n\n", 1)
            if len(parts) < 2:
                parts = frame.split("\r\n\r\n", 1)
            body = parts[1] if len(parts) >= 2 else parts[0]

            json_start = body.find("{")
            json_end = body.rfind("}")
            if json_start != -1 and json_end != -1:
                raw_json = body[json_start : json_end + 1]
                data = json.loads(raw_json)

                product_uid = data.get("productUid")
                if product_uid:
                    self.product_uid = str(product_uid)

                func_id = data.get("funcId")
                val = data.get("value")

                if func_id is not None:
                    try:
                        func_id_int = int(func_id)
                    except (ValueError, TypeError):
                        func_id_int = func_id

                    _LOGGER.debug(
                        "Bmola Status-Update: func_id=%s, value=%s",
                        func_id_int,
                        val,
                    )
                    self.states[func_id_int] = val
                    self._notify_callbacks()

        except Exception as err:
            _LOGGER.error("Fehler beim Parsen der Bmola Nachricht: %s", err)