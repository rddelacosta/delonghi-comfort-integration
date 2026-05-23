"""Switch platform for De'Longhi Comfort integration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import (
    SwitchDeviceClass,
    SwitchEntity,
    SwitchEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# Switch descriptions for AC (PAC series).
# Each entry maps a get_* read property to the corresponding set_* write property.
# Confirmed present on PAC-EL112 via property dump (AC000W021906461).
AC_SWITCH_DESCRIPTIONS: tuple[SwitchEntityDescription, ...] = (
    SwitchEntityDescription(
        key="get_silent_function",
        translation_key="silent_mode",
        icon="mdi:volume-mute",
    ),
    SwitchEntityDescription(
        key="get_swing_function",
        translation_key="swing",
        icon="mdi:arrow-oscillating",
    ),
)

# Map from get_* key to the corresponding set_* property name
_SET_PROPERTY: dict[str, str] = {
    "get_silent_function": "set_silent_function",
    "get_swing_function":  "set_swing_function",
}

HEATER_SWITCH_DESCRIPTIONS: tuple[SwitchEntityDescription, ...] = (
    SwitchEntityDescription(
        key="eco",
        icon="mdi:sprout",
        name="Eco",
    ),
    SwitchEntityDescription(
        key="lock",
        icon="mdi:lock",
        name="Child lock",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up De'Longhi switch entities."""
    data = hass.data[DOMAIN][config_entry.entry_id]
    entities: list[SwitchEntity] = []

    for coordinator in data["coordinators"]:
        entities.extend(
            DeLonghiSwitch(coordinator=coordinator, description=description)
            for description in AC_SWITCH_DESCRIPTIONS
        )

    for coordinator in data["heater_coordinators"]:
        entities.extend(
            HeaterSwitch(coordinator=coordinator, description=description)
            for description in HEATER_SWITCH_DESCRIPTIONS
        )

    async_add_entities(entities)


class DeLonghiSwitch(CoordinatorEntity, SwitchEntity):
    """A boolean switch for De'Longhi AC features (silent, swing)."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator,
        description: SwitchEntityDescription,
    ) -> None:
        """Initialize the switch entity."""
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
    def is_on(self) -> bool | None:
        """Return True if the switch is on. Device uses 1=on, 0=off for boolean props."""
        value = self.coordinator.data.get(self.entity_description.key)
        if value is None:
            return None
        return bool(value)

    @property
    def available(self) -> bool:
        """Return True only if this key is in coordinator data."""
        return (
            super().available
            and self.entity_description.key in self.coordinator.data
        )

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on."""
        success = await self._call_api(enabled=True)
        if success:
            await self.coordinator.async_request_refresh()
        else:
            _LOGGER.error(
                "Failed to enable %s on %s",
                self.entity_description.key,
                self.coordinator.dsn,
            )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off."""
        success = await self._call_api(enabled=False)
        if success:
            await self.coordinator.async_request_refresh()
        else:
            _LOGGER.error(
                "Failed to disable %s on %s",
                self.entity_description.key,
                self.coordinator.dsn,
            )

    async def _call_api(self, enabled: bool) -> bool:
        """Dispatch to the correct API method based on the switch key."""
        dsn = self.coordinator.dsn
        key = self.entity_description.key

        if key == "get_silent_function":
            return await self.coordinator.api.set_silent_mode(dsn, enabled)
        if key == "get_swing_function":
            return await self.coordinator.api.set_swing(dsn, enabled)

        # Fallback: use generic property setter with the set_* property name
        prop = _SET_PROPERTY.get(key)
        if prop:
            return await self.coordinator.api.set_device_property(
                dsn, prop, 1 if enabled else 0
            )

        _LOGGER.warning("No API handler for switch key: %s", key)
        return False


class HeaterSwitch(CoordinatorEntity, SwitchEntity):
    """Switch entity for De'Longhi heater features."""

    _attr_device_class = SwitchDeviceClass.SWITCH
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator,
        description: SwitchEntityDescription,
    ) -> None:
        """Initialize the heater switch."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_translation_key = description.key
        self._attr_unique_id = f"delonghi_heater_{coordinator.dsn}_{description.key}"
        self._attr_device_info = coordinator.get_device_info()

    @property
    def is_on(self) -> bool | None:
        value = self.coordinator.data.get(f"get_{self.entity_description.key}")
        if value is None:
            return None
        return value == 1

    async def async_turn_on(self, **kwargs: Any) -> None:
        success = await self.coordinator.api.set_device_property(
            self.coordinator.dsn, f"set_{self.entity_description.key}", 1
        )
        if success:
            await self.coordinator.async_request_refresh()
        else:
            _LOGGER.error("Failed to turn on: %s", self.entity_description.key)

    async def async_turn_off(self, **kwargs: Any) -> None:
        success = await self.coordinator.api.set_device_property(
            self.coordinator.dsn, f"set_{self.entity_description.key}", 0
        )
        if success:
            await self.coordinator.async_request_refresh()
        else:
            _LOGGER.error("Failed to turn off: %s", self.entity_description.key)
