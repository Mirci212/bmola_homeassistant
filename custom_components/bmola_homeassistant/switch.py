"""Switch platform for Bmola / SanNcco Air Purifier."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import (
    SwitchEntity,
    SwitchEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import BmolaHub, DOMAIN


@dataclass(frozen=True, kw_only=True)
class BmolaSwitchEntityDescription(SwitchEntityDescription):
    """Describes Bmola switch entity."""

    func_id: int
    data_type: int = 1
    invert: bool = False


SWITCH_DESCRIPTIONS: tuple[BmolaSwitchEntityDescription, ...] = (
    BmolaSwitchEntityDescription(
        key="child_lock",
        name="Kindersicherung",
        icon="mdi:lock",
        func_id=2,
        data_type=1,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Bmola switches from a config entry."""
    hub: BmolaHub = hass.data[DOMAIN][entry.entry_id]
    entities = [
        BmolaSwitch(hub, description) for description in SWITCH_DESCRIPTIONS
    ]
    async_add_entities(entities)


class BmolaSwitch(SwitchEntity):
    """Representation of a Bmola switch entity."""

    entity_description: BmolaSwitchEntityDescription
    _attr_has_entity_name = False

    def __init__(
        self,
        hub: BmolaHub,
        description: BmolaSwitchEntityDescription,
    ) -> None:
        """Initialize the switch."""
        self._hub = hub
        self.entity_description = description
        self._attr_name = f"Bmola {description.name}"
        self._attr_unique_id = f"{hub.device_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, hub.device_id)},
            name="Bmola Luftreiniger",
            manufacturer="Bmola / SanNcco",
            model=hub.product_uid,
        )
        self._remove_callback = None

    async def async_added_to_hass(self) -> None:
        """Register callback when entity is added."""
        self._remove_callback = self._hub.register_callback(
            self.async_write_ha_state
        )

    async def async_will_remove_from_hass(self) -> None:
        """Unregister callback when entity is removed."""
        if self._remove_callback:
            self._remove_callback()

    @property
    def available(self) -> bool:
        """Return True if hub is connected to cloud."""
        return self._hub.connected

    @property
    def is_on(self) -> bool | None:
        """Return True if switch is on."""
        val = self._hub.states.get(self.entity_description.func_id)
        if val is None:
            return None
        raw_bool = str(val).lower() in ("true", "1")
        return not raw_bool if self.entity_description.invert else raw_bool

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the switch."""
        target_val = "false" if self.entity_description.invert else "true"
        await self._hub.send_command(
            self.entity_description.func_id,
            self.entity_description.data_type,
            target_val,
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the switch."""
        target_val = "true" if self.entity_description.invert else "false"
        await self._hub.send_command(
            self.entity_description.func_id,
            self.entity_description.data_type,
            target_val,
        )
