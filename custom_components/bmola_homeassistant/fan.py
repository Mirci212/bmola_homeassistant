"""Fan platform for Bmola / SanNcco Air Purifier."""
from __future__ import annotations

import math
from typing import Any

from homeassistant.components.fan import FanEntity, FanEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util.percentage import (
    percentage_to_ranged_value,
    ranged_value_to_percentage,
)

from . import BmolaHub, DOMAIN

SPEED_RANGE = (1, 11)

PRESET_MANUAL = "Manual"
PRESET_ECO = "Eco"
PRESET_AUTO = "Auto"
PRESET_MODES = [PRESET_AUTO, PRESET_MANUAL, PRESET_ECO]

MODE_TO_PRESET: dict[Any, str] = {
    0: PRESET_MANUAL,
    "0": PRESET_MANUAL,
    1: PRESET_ECO,
    "1": PRESET_ECO,
    2: PRESET_AUTO,
    "2": PRESET_AUTO,
}

PRESET_TO_MODE: dict[str, int] = {
    PRESET_MANUAL: 0,
    PRESET_ECO: 1,
    PRESET_AUTO: 2,
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Bmola Fan from a config entry."""
    hub: BmolaHub = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([BmolaFan(hub)])


class BmolaFan(FanEntity):
    """Representation of the Bmola Air Purifier Fan."""

    _attr_has_entity_name = False
    _attr_supported_features = (
        FanEntityFeature.SET_SPEED
        | FanEntityFeature.TURN_OFF
        | FanEntityFeature.TURN_ON
        | FanEntityFeature.PRESET_MODE
    )
    _attr_speed_count = 11
    _attr_preset_modes = PRESET_MODES

    def __init__(self, hub: BmolaHub) -> None:
        """Initialize the fan entity."""
        self._hub = hub
        self._attr_name = "Bmola Luftreiniger"
        self._attr_unique_id = f"{hub.device_id}_fan"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, hub.device_id)},
            name="Bmola Luftreiniger",
            manufacturer="Bmola / SanNcco",
            model=hub.product_uid,
        )
        self._remove_callback = None

    async def async_added_to_hass(self) -> None:
        """Register callbacks when added to hass."""
        self._remove_callback = self._hub.register_callback(
            self.async_write_ha_state
        )

    async def async_will_remove_from_hass(self) -> None:
        """Remove callbacks when removed from hass."""
        if self._remove_callback:
            self._remove_callback()

    @property
    def available(self) -> bool:
        """Return True if hub is connected to cloud."""
        return self._hub.connected

    @property
    def is_on(self) -> bool | None:
        """Return True if fan is on."""
        val = self._hub.states.get(1)
        if val is None:
            return None
        return str(val).lower() in ("true", "1")

    @property
    def percentage(self) -> int | None:
        """Return the current speed percentage."""
        val = self._hub.states.get(98)
        if val is None:
            return None
        try:
            speed = int(val)
            if speed < 1:
                return 0
            return ranged_value_to_percentage(SPEED_RANGE, speed)
        except (ValueError, TypeError):
            return None

    @property
    def preset_mode(self) -> str | None:
        """Return the current preset mode (Manual, Eco, Auto)."""
        val = self._hub.states.get(97)
        if val is None:
            return None
        return MODE_TO_PRESET.get(val, PRESET_MANUAL)

    async def async_turn_on(
        self,
        percentage: int | None = None,
        preset_mode: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Turn on the fan and optionally set speed or preset mode."""
        await self._hub.send_command(1, 1, "true")
        if preset_mode is not None:
            await self.async_set_preset_mode(preset_mode)
        if percentage is not None:
            await self.async_set_percentage(percentage)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the fan."""
        await self._hub.send_command(1, 1, "false")

    async def async_set_percentage(self, percentage: int) -> None:
        """Set the speed percentage of the fan (1-11 steps)."""
        if percentage == 0:
            await self.async_turn_off()
            return

        speed = math.ceil(percentage_to_ranged_value(SPEED_RANGE, percentage))
        speed = max(1, min(11, speed))
        await self._hub.send_command(98, 2, str(speed))

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set preset mode (Manual=0, Eco=1, Auto=2)."""
        if preset_mode in PRESET_TO_MODE:
            mode_val = PRESET_TO_MODE[preset_mode]
            await self._hub.send_command(97, 4, mode_val)