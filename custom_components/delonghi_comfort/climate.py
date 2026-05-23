    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return Pinguino-specific attributes useful for automations.

        device_mode_raw: raw integer from get_device_mode — use this to
        diagnose unknown mode values (e.g. when Real Feel is active).
        """
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
            "device_mode_raw": data.get("get_device_mode"),
            "device_status_raw": data.get("get_device_status"),
            "real_feel_colour": data.get("real_feel_colour"),
        }
