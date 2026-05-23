"""Climate platform for De'Longhi Comfort integration."""

import logging
from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
    PRESET_NONE,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, PRESET_REAL_FEEL

_LOGGER = logging.getLogger(__name__)

# Mode mappings confirmed via live property dump of PAC-EL112 (AC000W021906461).
# get_device_mode: 3=Fan observed; 1=Cool and 2=Dry from integration source.
# Real Feel is NOT a separate mode value -- implemented as a preset per HA guidelines.
# Context7/HA dev docs: "only built-in HVACMode values allowed; custom modes go in presets."
# If testing reveals a mode 4, update DEVICE_MODE_TO_HVAC accordingly.
DEVICE_MODE_TO_HVAC: dict[int, HVACMode] = {
    1: HVACMode.COOL,
    2: HVACMode.DRY,
    3: HVACMode.FAN_ONLY,
}
HVAC_MODE_TO_DEVICE: dict[HVACMode, int] = {v: k for k, v in DEVICE_MODE_TO_HVAC.items()}

FAN_SPEED_TO_NAME: dict[int, str] = {1: "low", 2: "medium", 3: "high", 4: "auto"}
FAN_NAME_TO_SPEED: dict[str, int] = {v: k for k, v in FAN_SPEED_TO_NAME.items()}


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up De'Longhi climate entities."""
    data = hass.data[DOMAIN][config_entry.entry_id]

    entities: list[ClimateEntity] = [
        DeLonghiClimate(coordinator=coordinator)
        for coordinator in data["coordinators"]
    ]
    entities.extend(
        DeLonghiHeater(coordinator=coordinator)
        for coordinator in data["heater_coordinators"]
    )
    async_add_entities(entities)


class DeLonghiClimate(CoordinatorEntity, ClimateEntity):
    """Representation of a De'Longhi portable AC (PAC series)."""

    _attr_has_entity_name = True
    _attr_name = None  # use device name from device_info

    def __init__(self, coordinator) -> None:
        """Initialize the climate entity."""
        super().__init__(coordinator)
        self._dsn = coordinator.dsn
        self._api = coordinator.api

        self._attr_unique_id = f"delonghi_comfort_{self._dsn}"
        self._attr_name = coordinator.device_name

        self._attr_supported_features = (
            ClimateEntityFeature.TARGET_TEMPERATURE
            | ClimateEntityFeature.FAN_MODE
            | ClimateEntityFeature.PRESET_MODE
            | ClimateEntityFeature.TURN_ON
            | ClimateEntityFeature.TURN_OFF
        )

        self._attr_hvac_modes = [
            HVACMode.OFF,
            HVACMode.COOL,
            HVACMode.DRY,
            HVACMode.FAN_ONLY,
        ]

        # Real Feel is a preset on top of Cool mode -- HA guidelines require
        # only built-in HVACMode values; custom modes go in presets.
        self._attr_preset_modes = [PRESET_NONE, PRESET_REAL_FEEL]

        self._attr_fan_modes = ["auto", "low", "medium", "high"]

        self._attr_temperature_unit = UnitOfTemperature.CELSIUS
        self._attr_min_temp = 16   # PAC-EL112 minimum (set_temp_setpoint min)
        self._attr_max_temp = 32
        self._attr_target_temperature_step = 1.0
        self._attr_precision = 1.0

        # Real Feel active state tracked locally -- the device exposes no dedicated
        # read-back property for "Real Feel enabled". get_real_feel_offset is always
        # 16 on this device regardless of mode, so it cannot be used as a signal.
        # None = unknown (cold start / HA restart); True/False = user-set this session.
        self._real_feel_active: bool | None = None

        self._attr_device_info = {
            "identifiers": {(DOMAIN, self._dsn)},
            "name": coordinator.device_name,
            "manufacturer": "De'Longhi",
            "model": coordinator.device_model,
            "sw_version": coordinator.device_version,
        }

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return (
            self.coordinator.last_update_success
            and self.coordinator.data is not None
        )

    @property
    def hvac_mode(self) -> HVACMode:
        """Return current HVAC mode."""
        if self.coordinator.data.get("get_device_status") == 2:
            return HVACMode.OFF
        device_mode = self.coordinator.data.get("get_device_mode")
        return DEVICE_MODE_TO_HVAC.get(device_mode, HVACMode.OFF)

    @property
    def hvac_action(self) -> HVACAction | None:
        """Return the current running HVAC action."""
        if self.coordinator.data.get("get_device_status") == 2:
            return HVACAction.OFF
        device_mode = self.coordinator.data.get("get_device_mode")
        return {
            1: HVACAction.COOLING,
            2: HVACAction.DRYING,
            3: HVACAction.FAN,
        }.get(device_mode, HVACAction.IDLE)

    @property
    def preset_mode(self) -> str | None:
        """Return the current preset mode.

        Tracked via local optimistic state (_real_feel_active) because the device
        exposes no authoritative read-back property for Real Feel activation.
        Returns None on cold start (HA restart) until user explicitly sets a preset.
        """
        if self._real_feel_active is True:
            return PRESET_REAL_FEEL
        if self._real_feel_active is False:
            return PRESET_NONE
        return None  # Unknown -- cold start, no user action yet this session

    @property
    def current_temperature(self) -> float | None:
        """Return the current room temperature."""
        return self.coordinator.data.get("room_temp")

    @property
    def target_temperature(self) -> float | None:
        """Return the target temperature setpoint."""
        return self.coordinator.data.get("temp_setpoint")

    @property
    def current_humidity(self) -> float | None:
        """Return the current room humidity."""
        return self.coordinator.data.get("room_hum")

    @property
    def fan_mode(self) -> str:
        """Return the current fan mode."""
        fan_speed = self.coordinator.data.get("get_int_fan_speed")
        return FAN_SPEED_TO_NAME.get(fan_speed, "auto")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return Pinguino-specific attributes useful for automations."""
        data = self.coordinator.data
        return {
            "second_room_temp": data.get("second_room_temp"),
            "real_feel_offset": data.get("get_real_feel_offset"),
            "sensors_used": data.get("get_sensors_used"),
            "silent_mode": bool(data.get("get_silent_function")),
            "swing": bool(data.get("get_swing_function")),
            "outdoor_temp": data.get("outdoor_temp"),
            "outdoor_hum": data.get("outdoor_hum"),
            "outdoor_weather": data.get("outdoor_Weather_condition"),
            "firmware": data.get("firmware_version"),
        }

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set new HVAC mode."""
        if hvac_mode == HVACMode.OFF:
            if not await self._api.set_device_status(self._dsn, 2):
                _LOGGER.error("Failed to turn off %s", self._dsn)
                return
        else:
            if self.coordinator.data.get("get_device_status") == 2:
                if not await self._api.set_device_status(self._dsn, 1):
                    _LOGGER.error("Failed to turn on %s", self._dsn)
                    return
            device_mode = HVAC_MODE_TO_DEVICE.get(hvac_mode)
            if device_mode is None:
                _LOGGER.error("Unknown HVAC mode: %s", hvac_mode)
                return
            if not await self._api.set_device_mode(self._dsn, device_mode):
                _LOGGER.error("Failed to set mode %s on %s", hvac_mode, self._dsn)
                return
        await self.coordinator.async_request_refresh()

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set preset mode.

        PRESET_REAL_FEEL: ensures Cool mode, then writes the Real Feel offset
        to activate comfort-sensor mode. Offset is preserved from last known
        value (default 16 if unavailable).

        PRESET_NONE: writes offset=0 as best-effort disable (unverified on
        firmware -- needs live testing to confirm). Tracks state locally.

        State is optimistic (local only). On HA restart _real_feel_active
        resets to None (unknown) since the device has no read-back property.
        """
        if preset_mode == PRESET_REAL_FEEL:
            if self.coordinator.data.get("get_device_status") == 2:
                if not await self._api.set_device_status(self._dsn, 1):
                    _LOGGER.error("Failed to turn on device for Real Feel preset")
                    return
            if self.hvac_mode != HVACMode.COOL:
                if not await self._api.set_device_mode(self._dsn, 1):
                    _LOGGER.error("Failed to set Cool mode for Real Feel preset")
                    return
            offset = self.coordinator.data.get("get_real_feel_offset") or 16
            if not await self._api.set_real_feel_offset(self._dsn, int(offset)):
                _LOGGER.error("Failed to set Real Feel offset on %s", self._dsn)
                return
            self._real_feel_active = True

        elif preset_mode == PRESET_NONE:
            # Best-effort disable: write offset=0. Not empirically confirmed --
            # update this once tested on live device.
            if not await self._api.set_real_feel_offset(self._dsn, 0):
                _LOGGER.warning(
                    "Failed to clear Real Feel offset on %s -- state set locally",
                    self._dsn,
                )
            self._real_feel_active = False

        else:
            raise ValueError(f"Unsupported preset mode: {preset_mode!r}")

        await self.coordinator.async_request_refresh()

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature."""
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return
        if not await self._api.set_temperature_setpoint(self._dsn, float(temperature)):
            _LOGGER.error("Failed to set temperature on %s", self._dsn)
            return
        await self.coordinator.async_request_refresh()

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        """Set new fan mode."""
        fan_speed = FAN_NAME_TO_SPEED.get(fan_mode)
        if fan_speed is None:
            _LOGGER.error("Unknown fan mode: %s", fan_mode)
            return
        if not await self._api.set_fan_speed(self._dsn, fan_speed):
            _LOGGER.error("Failed to set fan mode %s on %s", fan_mode, self._dsn)
            return
        await self.coordinator.async_request_refresh()

    async def async_turn_on(self) -> None:
        """Turn the AC on."""
        if not await self._api.set_device_status(self._dsn, 1):
            _LOGGER.error("Failed to turn on %s", self._dsn)
            return
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self) -> None:
        """Turn the AC off."""
        if not await self._api.set_device_status(self._dsn, 2):
            _LOGGER.error("Failed to turn off %s", self._dsn)
            return
        await self.coordinator.async_request_refresh()


class DeLonghiHeater(CoordinatorEntity, ClimateEntity):
    """Representation of a De'Longhi electric heater."""

    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.FAN_MODE
        | ClimateEntityFeature.PRESET_MODE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )
    _attr_has_entity_name = True
    _attr_name = None
    _attr_translation_key = "heater"
    _attr_icon = "mdi:radiator"

    _attr_fan_modes = ["0%", "20%", "40%", "60%", "80%", "100%"]
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT]
    _attr_max_temp = 28
    _attr_min_temp = 10
    _attr_preset_modes = ["Day mode", "Night mode", "Antifrost", "Manual"]
    _attr_target_temperature_step = 0.5
    _attr_temperature_unit = UnitOfTemperature.CELSIUS

    def __init__(self, coordinator) -> None:
        """Initialize the heater entity."""
        super().__init__(coordinator)
        self._dsn = coordinator.dsn
        self._api = coordinator.api
        self._attr_unique_id = f"delonghi_heater_{self._dsn}"
        self._attr_device_info = coordinator.get_device_info()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return dict(self.coordinator.data)

    @property
    def hvac_mode(self) -> HVACMode:
        status = self.coordinator.data.get("device_status")
        return HVACMode.HEAT if status == 1 else HVACMode.OFF

    @property
    def hvac_action(self) -> HVACAction | None:
        status = self.coordinator.data.get("device_status")
        if status == 1:
            power_level = self.coordinator.data.get("MDH_Resources")
            return HVACAction.IDLE if power_level == 0 else HVACAction.HEATING
        return HVACAction.OFF

    @property
    def preset_mode(self) -> str | None:
        device_mode = self.coordinator.data.get("device_mode")
        if isinstance(device_mode, int) and 1 <= device_mode <= 4:
            return self._attr_preset_modes[device_mode - 1]
        return None

    @property
    def current_temperature(self) -> float | None:
        return self.coordinator.data.get("room_temp")

    @property
    def target_temperature(self) -> float | None:
        return self.coordinator.data.get("temperature_setpoint")

    @property
    def fan_mode(self) -> str | None:
        power_level = self.coordinator.data.get("current_power_level", 0)
        if isinstance(power_level, int) and 0 <= power_level < len(self._attr_fan_modes):
            return self._attr_fan_modes[power_level]
        return self._attr_fan_modes[0]

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        if hvac_mode == HVACMode.OFF:
            await self.async_turn_off()
        else:
            await self.async_turn_on()

    async def async_turn_on(self) -> None:
        if await self._api.set_device_property(self._dsn, "set_status", 1):
            await self.coordinator.async_request_refresh()
        else:
            _LOGGER.error("Failed to turn on heater %s", self._dsn)

    async def async_turn_off(self) -> None:
        if await self._api.set_device_property(self._dsn, "set_status", 2):
            await self.coordinator.async_request_refresh()
        else:
            _LOGGER.error("Failed to turn off heater %s", self._dsn)

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        if preset_mode not in self._attr_preset_modes:
            _LOGGER.error("Invalid preset mode: %s", preset_mode)
            return
        device_mode = self._attr_preset_modes.index(preset_mode) + 1
        if await self._api.set_device_property(self._dsn, "set_device_mode", device_mode):
            await self.coordinator.async_request_refresh()
        else:
            _LOGGER.error("Failed to set preset %s on heater %s", preset_mode, self._dsn)

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        if fan_mode not in self._attr_fan_modes:
            _LOGGER.error("Invalid fan mode: %s", fan_mode)
            return
        power_level = self._attr_fan_modes.index(fan_mode)
        if await self._api.set_device_property(self._dsn, "set_power_level", power_level):
            await self.coordinator.async_request_refresh()
        else:
            _LOGGER.error("Failed to set fan mode %s on heater %s", fan_mode, self._dsn)

    async def async_set_temperature(self, **kwargs: Any) -> None:
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return
        if await self._api.set_device_property(
            self._dsn, "temperature_setpoint", float(temperature)
        ):
            await self.coordinator.async_request_refresh()
        else:
            _LOGGER.error("Failed to set temperature on heater %s", self._dsn)
