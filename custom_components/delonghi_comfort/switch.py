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
# Using name= directly (not translation_key=) to avoid fallback to device name.
# device_status uses 1=ON / 2=OFF — NOT a standard boolean.
# Silent and swing use 0=OFF / 1=ON — standard boolean.
AC_SWITCH_DESCRIPTIONS: tuple[SwitchEntityDescription, ...] = (
    SwitchEntityDescription(
        key="get_device_status",
        name="Power",
        icon="mdi:power",
    ),
    SwitchEntityDescription(
        key="get_silent_function",
        name="Silent mode",
        icon="mdi:volume-mute",
    ),
    SwitchEntityDescription(
        key="get_swing_function",
        name="Swing",
        icon="mdi:arrow-oscillating",
    ),
)

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
    """A boolean switch for De'Longhi AC features."""

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
        """Return True if switch is on.

        device_status: 1=ON, 2=OFF (not a standard boolean — bool(2) would be True).
        silent/swing: 0=OFF, 1=ON (standard boolean).
        """
        value = self.coordinator.data.get(self.entity_description.key)
        if value is None:
            return None
        if self.entity_description.key == "get_device_status":
            return value == 1
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

        if key == "get_device_status":
            # device_status: 1=ON, 2=OFF
            return await self.coordinator.api.set_device_status(dsn, 1 if enabled else 2)
        if key == "get_silent_function":
            return await self.coordinator.api.set_silent_mode(dsn, enabled)
        if key == "get_swing_function":
            return await self.coordinator.api.set_swing(dsn, enabled)

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
