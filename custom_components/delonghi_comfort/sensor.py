"""Sensor platform for De'Longhi Comfort integration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# Sensors derived from live property dump of PAC-EL112 (AC000W021906461).
# Only properties confirmed present on this device are included.
# Properties marked entity_registry_enabled_default=False are registered but
# disabled by default -- enable per-device in the HA entity registry if needed.

AC_SENSOR_DESCRIPTIONS: tuple[SensorEntityDescription, ...] = (
    # --- Primary room sensors ---
    SensorEntityDescription(
        key="room_temp",
        translation_key="room_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        suggested_display_precision=1,
    ),
    SensorEntityDescription(
        key="room_hum",
        translation_key="room_humidity",
        device_class=SensorDeviceClass.HUMIDITY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=1,
    ),
    SensorEntityDescription(
        key="temp_setpoint",
        translation_key="target_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        suggested_display_precision=1,
    ),
    # --- CST (Cool Surround Technology) secondary sensor ---
    SensorEntityDescription(
        key="second_room_temp",
        translation_key="cst_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        suggested_display_precision=1,
    ),
    # --- Outdoor sensors (read from De'Longhi cloud weather feed) ---
    SensorEntityDescription(
        key="outdoor_temp",
        translation_key="outdoor_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        suggested_display_precision=1,
    ),
    SensorEntityDescription(
        key="outdoor_hum",
        translation_key="outdoor_humidity",
        device_class=SensorDeviceClass.HUMIDITY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=1,
    ),
    SensorEntityDescription(
        key="outdoor_Weather_condition",
        translation_key="outdoor_weather_condition",
        # No device_class: free-text string (e.g. "Sunny", "Cloudy")
        entity_registry_enabled_default=False,
    ),
    # --- Diagnostic sensors ---
    SensorEntityDescription(
        key="get_device_status",
        translation_key="device_status",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="get_device_mode",
        translation_key="device_mode",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="get_int_fan_speed",
        translation_key="fan_speed",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="get_real_feel_offset",
        translation_key="real_feel_offset",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    SensorEntityDescription(
        key="get_silent_function",
        translation_key="silent_mode",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    SensorEntityDescription(
        key="get_swing_function",
        translation_key="swing",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
)

# Human-readable transformations for integer-coded properties.
# Mode 4 = Real Feel confirmed via live device test (23 May 2026).
_STATUS_MAP = {1: "on", 2: "off"}
_MODE_MAP = {1: "cooling", 2: "dehumidification", 3: "fan_only", 4: "real_feel"}
_FAN_MAP = {1: "low", 2: "medium", 3: "high", 4: "auto"}
_BOOL_MAP = {0: "off", 1: "on"}


async def async_setup_entry(
    hass,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up De'Longhi sensor entities."""
    data = hass.data[DOMAIN][config_entry.entry_id]
    entities: list[SensorEntity] = []

    for coordinator in data["coordinators"]:
        entities.extend(
            DeLonghiSensor(coordinator=coordinator, description=description)
            for description in AC_SENSOR_DESCRIPTIONS
        )

    entities.extend(
        HeaterTemperature(coordinator=coordinator)
        for coordinator in data["heater_coordinators"]
    )

    async_add_entities(entities)


class DeLonghiSensor(CoordinatorEntity, SensorEntity):
    """Representation of a De'Longhi AC sensor."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator,
        description: SensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.dsn}_{description.key}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator.dsn)},
            "name": coordinator.device_name,
            "manufacturer": "De'Longhi",
            "model": coordinator.device_model,
            "sw_version": coordinator.device_version,
        }

    @property
    def native_value(self) -> Any:
        """Return the sensor value, applying human-readable mapping where appropriate."""
        value = self.coordinator.data.get(self.entity_description.key)
        if value is None:
            return None

        key = self.entity_description.key
        if key == "get_device_status":
            return _STATUS_MAP.get(value, "unknown")
        if key == "get_device_mode":
            return _MODE_MAP.get(value, "unknown")
        if key == "get_int_fan_speed":
            return _FAN_MAP.get(value, "unknown")
        if key in ("get_silent_function", "get_swing_function"):
            return _BOOL_MAP.get(value, "unknown")

        return value

    @property
    def available(self) -> bool:
        """Return True only if this sensor's key is in the coordinator data."""
        return (
            super().available
            and self.entity_description.key in self.coordinator.data
        )


class HeaterTemperature(CoordinatorEntity, SensorEntity):
    """Temperature sensor for De'Longhi heater devices."""

    _attr_has_entity_name = True
    _attr_name = "Temperature"
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator) -> None:
        """Initialize the heater temperature sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"delonghi_heater_{coordinator.dsn}_temperature"
        self._attr_device_info = coordinator.get_device_info()

    @property
    def native_value(self) -> float | None:
        return self.coordinator.data.get("room_temp")
