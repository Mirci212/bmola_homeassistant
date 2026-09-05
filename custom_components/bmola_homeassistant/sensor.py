"""Sensor platform for Bmola / SanNcco Air Purifier."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONCENTRATION_MICROGRAMS_PER_CUBIC_METER,
    CONCENTRATION_MILLIGRAMS_PER_CUBIC_METER,
    CONCENTRATION_PARTS_PER_MILLION,
    PERCENTAGE,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import BmolaHub, DOMAIN


@dataclass(frozen=True, kw_only=True)
class BmolaSensorEntityDescription(SensorEntityDescription):
    """Describes Bmola sensor entity."""

    func_id: int
    value_fn: Callable[[Any], Any] | None = None


SENSOR_DESCRIPTIONS: tuple[BmolaSensorEntityDescription, ...] = (
    BmolaSensorEntityDescription(
        key="pm25",
        name="PM2.5",
        native_unit_of_measurement=CONCENTRATION_MICROGRAMS_PER_CUBIC_METER,
        device_class=SensorDeviceClass.PM25,
        state_class=SensorStateClass.MEASUREMENT,
        func_id=99,
    ),
    BmolaSensorEntityDescription(
        key="voc",
        name="VOC",
        native_unit_of_measurement=CONCENTRATION_MILLIGRAMS_PER_CUBIC_METER,
        device_class=SensorDeviceClass.VOLATILE_ORGANIC_COMPOUNDS,
        state_class=SensorStateClass.MEASUREMENT,
        func_id=100,
        value_fn=lambda val: round(float(val) / 1000.0, 3),
    ),
    BmolaSensorEntityDescription(
        key="co2",
        name="CO2",
        native_unit_of_measurement=CONCENTRATION_PARTS_PER_MILLION,
        device_class=SensorDeviceClass.CO2,
        state_class=SensorStateClass.MEASUREMENT,
        func_id=101,
    ),
    BmolaSensorEntityDescription(
        key="temperature",
        name="Temperatur",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        func_id=102,
    ),
    BmolaSensorEntityDescription(
        key="humidity",
        name="Luftfeuchtigkeit",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.HUMIDITY,
        state_class=SensorStateClass.MEASUREMENT,
        func_id=103,
    ),
    BmolaSensorEntityDescription(
        key="filter_remaining",
        name="Filter Restlaufzeit",
        native_unit_of_measurement=UnitOfTime.HOURS,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        func_id=110,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Bmola sensor entities from a config entry."""
    hub: BmolaHub = hass.data[DOMAIN][entry.entry_id]
    entities = [
        BmolaSensor(hub, description) for description in SENSOR_DESCRIPTIONS
    ]
    async_add_entities(entities)


class BmolaSensor(SensorEntity):
    """Representation of a Bmola sensor."""

    entity_description: BmolaSensorEntityDescription
    _attr_has_entity_name = False

    def __init__(
        self,
        hub: BmolaHub,
        description: BmolaSensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
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
    def native_value(self) -> Any:
        """Return the state of the sensor."""
        raw_val = self._hub.states.get(self.entity_description.func_id)
        if raw_val is None:
            return None

        if self.entity_description.value_fn is not None:
            try:
                return self.entity_description.value_fn(raw_val)
            except (ValueError, TypeError):
                return None

        try:
            val_str = str(raw_val).strip()
            if "." in val_str:
                return float(val_str)
            return int(val_str)
        except (ValueError, TypeError):
            return raw_val