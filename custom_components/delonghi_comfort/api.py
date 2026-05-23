"""API client for De'Longhi Comfort devices."""

import json
import logging
import urllib.parse
from datetime import datetime
from typing import Any

import aiohttp

from .const import (
    API_KEY,
    CLIENT_ID,
    AUTHORIZATION_HEADER,
    APP_ID,
    APP_SECRET,
    BROWSER_USER_AGENT,
    TOKEN_USER_AGENT,
    API_USER_AGENT,
    SDK_BUILD,
)

_LOGGER = logging.getLogger(__name__)


class DeLonghiAPI:
    """API client for De'Longhi Comfort devices."""

    def __init__(
        self,
        username: str,
        password: str,
        session: aiohttp.ClientSession,
        language: str = "en",
    ) -> None:
        """Initialize the API client."""
        self.username = username
        self.password = password
        self.language = language
        self.session = session
        self.access_token: str | None = None
        self.refresh_token: str | None = None

    def get_query_param(self, url: str, param: str) -> str | None:
        """Extract query parameter from URL."""
        query = urllib.parse.urlparse(url).query
        params = urllib.parse.parse_qs(query)
        return params.get(param, [None])[0]

    def url_encode(self, value: str) -> str:
        """URL encode a value."""
        return urllib.parse.quote(value)

    async def authenticate(self) -> bool:
        """Authenticate with the De'Longhi API."""
        try:
            self.access_token = await self._get_new_access_token()
            return self.access_token is not None
        except Exception as e:
            _LOGGER.error("Authentication failed: %s", e)
            return False

    async def _get_new_access_token(self) -> str | None:
        """Get a new access token through the full authentication flow."""

        # Thanks to https://github.com/duckwc/ECAMpy for the code to token conversion
        # Thanks to https://github.com/rtfpessoa/delonghi-comfort-client for the auth flow
        try:
            # Step 1: Start authentication process
            async with self.session.get(
                f"https://fidm.eu1.gigya.com/oidc/op/v1.0/{API_KEY}/authorize",
                headers={"User-Agent": BROWSER_USER_AGENT},
                params={
                    "client_id": CLIENT_ID,
                    "response_type": "code",
                    "redirect_uri": "https://google.it",
                    "scope": "openid email profile UID comfort en alexa",
                    "nonce": str(int(datetime.now().timestamp())),
                },
                allow_redirects=False,
            ) as response:
                context = self.get_query_param(response.headers["Location"], "context")

            # Step 2: Fetch Gigya session data
            async with self.session.get(
                "https://socialize.eu1.gigya.com/socialize.getIDs",
                headers={"User-Agent": BROWSER_USER_AGENT},
                params={
                    "APIKey": API_KEY,
                    "includeTicket": "true",
                    "pageURL": "https://aylaopenid.delonghigroup.com/",
                    "sdk": "js_latest",
                    "sdkBuild": SDK_BUILD,
                    "format": "json",
                },
            ) as response:
                data = await response.text()
                data = json.loads(data)

            ucid = data["ucid"]
            gmid = data["gmid"]
            gmid_ticket = data["gmidTicket"]

            # Step 3: Login
            risk_context_json = json.dumps(
                {
                    "b0": 4494,
                    "b1": [0, 2, 2, 0],
                    "b2": 2,
                    "b3": [],
                    "b4": 2,
                    "b5": 1,
                    "b6": BROWSER_USER_AGENT,
                    "b7": [
                        {
                            "name": "PDF Viewer",
                            "filename": "internal-pdf-viewer",
                            "length": 2,
                        },
                        {
                            "name": "Chrome PDF Viewer",
                            "filename": "internal-pdf-viewer",
                            "length": 2,
                        },
                        {
                            "name": "Chromium PDF Viewer",
                            "filename": "internal-pdf-viewer",
                            "length": 2,
                        },
                        {
                            "name": "Microsoft Edge PDF Viewer",
                            "filename": "internal-pdf-viewer",
                            "length": 2,
                        },
                        {
                            "name": "WebKit built-in PDF",
                            "filename": "internal-pdf-viewer",
                            "length": 2,
                        },
                    ],
                    "b8": datetime.now().strftime("%H:%M:%S"),
                    "b9": 0,
                    "b10": {"state": "denied"},
                    "b11": False,
                    "b13": [5, "440|956|24", False, True],
                }
            )

            async with self.session.post(
                "https://accounts.eu1.gigya.com/accounts.login",
                headers={"User-Agent": BROWSER_USER_AGENT},
                data={
                    "loginID": self.username,
                    "password": self.password,
                    "sessionExpiration": 7884009,
                    "targetEnv": "jssdk",
                    "include": "profile,data,emails,subscriptions,preferences",
                    "includeUserInfo": "true",
                    "loginMode": "standard",
                    "lang": self.language,
                    "riskContext": self.url_encode(risk_context_json),
                    "APIKey": API_KEY,
                    "source": "showScreenSet",
                    "sdk": "js_latest",
                    "authMode": "cookie",
                    "pageURL": "https://aylaopenid.delonghigroup.com/",
                    "gmid": gmid,
                    "ucid": ucid,
                    "sdkBuild": SDK_BUILD,
                    "format": "json",
                },
            ) as response:
                login_data = await response.text()
                login_data = json.loads(login_data)

            if login_data.get("statusCode") != 200:
                _LOGGER.error(
                    "Login failed: %s", login_data.get("errorDetails", "Unknown error")
                )
                return None

            login_token = login_data["sessionInfo"]["login_token"]

            # Step 4: Get user info
            async with self.session.post(
                "https://socialize.eu1.gigya.com/socialize.getUserInfo",
                headers={"User-Agent": BROWSER_USER_AGENT},
                data={
                    "enabledProviders": "*",
                    "APIKey": API_KEY,
                    "sdk": "js_latest",
                    "login_token": login_token,
                    "authMode": "cookie",
                    "pageURL": "https://aylaopenid.delonghigroup.com/",
                    "gmid": gmid,
                    "ucid": ucid,
                    "sdkBuild": SDK_BUILD,
                    "format": "json",
                },
            ) as response:
                user_data = await response.text()
                user_data = json.loads(user_data)

            user_uid = user_data["UID"]
            user_uid_signature = user_data["UIDSignature"]
            user_signature_timestamp = user_data["signatureTimestamp"]

            # Step 5: Consent
            async with self.session.get(
                "https://aylaopenid.delonghigroup.com/OIDCConsentPage.php",
                headers={"User-Agent": BROWSER_USER_AGENT},
                params={
                    "lang": self.language,
                    "context": context,
                    "clientID": CLIENT_ID,
                    "scope": "openid+email+profile+UID+comfort+en+alexa",
                    "UID": user_uid,
                    "UIDSignature": user_uid_signature,
                    "signatureTimestamp": user_signature_timestamp,
                },
            ) as response:
                consent_text = await response.text()

            signature = consent_text.split("const consentObj2Sig = '")[1].split("';")[0]

            # Step 6: Authorization
            async with self.session.get(
                f"https://fidm.eu1.gigya.com/oidc/op/v1.0/{API_KEY}/authorize/continue",
                headers={"User-Agent": BROWSER_USER_AGENT},
                params={
                    "context": context,
                    "login_token": login_token,
                    "consent": json.dumps(
                        {
                            "scope": "openid email profile UID comfort en alexa",
                            "clientID": CLIENT_ID,
                            "context": context,
                            "UID": user_uid,
                            "consent": True,
                        },
                        separators=(",", ":"),
                    ),
                    "sig": signature,
                    "gmidTicket": gmid_ticket,
                },
                allow_redirects=False,
            ) as response:
                code = self.get_query_param(response.headers["Location"], "code")

            # Step 7: Get IDP access token
            async with self.session.post(
                f"https://fidm.eu1.gigya.com/oidc/op/v1.0/{API_KEY}/token",
                headers={
                    "User-Agent": TOKEN_USER_AGENT,
                    "Authorization": AUTHORIZATION_HEADER,
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                data={
                    "code": code,
                    "grant_type": "authorization_code",
                    "redirect_uri": "https://google.it",
                },
            ) as response:
                token_data = await response.text()
                token_data = json.loads(token_data)

            idp_token = token_data["access_token"]

            # Step 8: Exchange IDP token for Ayla token
            async with self.session.post(
                "https://user-field-eu.aylanetworks.com/api/v1/token_sign_in",
                headers={"User-Agent": TOKEN_USER_AGENT},
                data={
                    "app_id": APP_ID,
                    "app_secret": APP_SECRET,
                    "token": idp_token,
                },
            ) as response:
                ayla_data = await response.text()
                ayla_data = json.loads(ayla_data)

            self.refresh_token = ayla_data["refresh_token"]
            return ayla_data["access_token"]

        except Exception as e:
            _LOGGER.error("Failed to get access token: %s", e)
            return None

    async def refresh_access_token(self) -> str | None:
        """Refresh the access token using the refresh token."""
        if not self.refresh_token:
            return await self._get_new_access_token()

        try:
            async with self.session.post(
                "https://user-field-eu.aylanetworks.com/users/refresh_token.json",
                headers={
                    "User-Agent": TOKEN_USER_AGENT,
                    "Content-Type": "application/json",
                },
                json={"user": {"refresh_token": self.refresh_token}},
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    new_access_token = data["access_token"]
                    new_refresh_token = data.get("refresh_token")
                    if new_refresh_token:
                        self.refresh_token = new_refresh_token
                    return new_access_token

                _LOGGER.warning("Failed to refresh token, falling back to full login")
                return await self._get_new_access_token()

        except Exception as e:
            _LOGGER.error("Failed to refresh access token: %s", e)
            return await self._get_new_access_token()

    async def get_devices(self) -> list[dict[str, Any]]:
        """Get all devices associated with the account."""
        if not self.access_token:
            if not await self.authenticate():
                return []
        try:
            response = await self._get_request("apiv1/devices.json")
            return response if isinstance(response, list) else []
        except Exception as e:
            _LOGGER.error("Failed to get devices: %s", e)
            return []

    async def get_device_properties(self, dsn: str) -> list[dict[str, Any]]:
        """Get device properties by DSN."""
        if not self.access_token:
            if not await self.authenticate():
                return []
        try:
            response = await self._get_request(f"apiv1/dsns/{dsn}/properties.json")
            return response if isinstance(response, list) else []
        except Exception as e:
            _LOGGER.error("Failed to get device properties for %s: %s", dsn, e)
            return []

    def get_property_value(
        self, properties: list[dict], property_name: str
    ) -> Any | None:
        """Extract a property value from the properties list by property name."""
        for prop in properties:
            if "property" in prop and prop["property"]["name"] == property_name:
                return prop["property"]["value"]
        return None

    # -------------------------------------------------------------------------
    # Device control methods — all use set_device_* property names confirmed
    # via live property dump of PAC-EL112 (DSN AC000W021906461).
    # -------------------------------------------------------------------------

    async def set_device_status(self, dsn: str, status: int) -> bool:
        """Set device on/off status. status: 1=ON, 2=OFF."""
        return await self._set_datapoint(dsn, "set_device_status", int(status))

    async def set_device_mode(self, dsn: str, mode: int) -> bool:
        """Set device mode. mode: 1=Cool, 2=Dry, 3=Fan."""
        return await self._set_datapoint(dsn, "set_device_mode", int(mode))

    async def set_temperature_setpoint(self, dsn: str, temperature: float) -> bool:
        """Set temperature setpoint (16-32 degC)."""
        return await self._set_datapoint(dsn, "set_temp_setpoint", float(temperature))

    async def set_fan_speed(self, dsn: str, fan_speed: int) -> bool:
        """Set fan speed. fan_speed: 1=Low, 2=Mid, 3=High, 4=Auto."""
        # NOTE: must send int, not str -- confirmed from property dump (base_type=integer)
        return await self._set_datapoint(dsn, "set_int_fan_speed", int(fan_speed))

    async def set_silent_mode(self, dsn: str, enabled: bool) -> bool:
        """Enable or disable silent function."""
        return await self._set_datapoint(
            dsn, "set_silent_function", 1 if enabled else 0
        )

    async def set_swing(self, dsn: str, enabled: bool) -> bool:
        """Enable or disable swing/oscillation function."""
        return await self._set_datapoint(
            dsn, "set_swing_function", 1 if enabled else 0
        )

    async def set_real_feel_offset(self, dsn: str, offset: int) -> bool:
        """Set the Real Feel temperature offset (typically 0-30).

        The Real Feel feature uses both room_temp and second_room_temp
        (CST sensor) to calculate a perceived-comfort temperature.
        Writing to set_real_feel_offset activates/adjusts this mode.
        Default observed value on PAC-EL112: 16.
        Writing 0 is used as best-effort disable (needs live verification).
        """
        return await self._set_datapoint(dsn, "set_real_feel_offset", int(offset))

    async def set_device_property(self, dsn: str, prop_name: str, value: Any) -> bool:
        """Generic property setter -- use for heater or future properties."""
        return await self._set_datapoint(dsn, prop_name, value)

    # -------------------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------------------

    async def _set_datapoint(self, dsn: str, prop_name: str, value: Any) -> bool:
        """Post a datapoint to a single device property."""
        try:
            response = await self._post_request(
                f"apiv1/dsns/{dsn}/properties/{prop_name}/datapoints.json",
                {"datapoint": {"value": value}},
            )
            return response is not None
        except Exception as e:
            _LOGGER.error(
                "Failed to set %s=%s on %s: %s", prop_name, value, dsn, e
            )
            return False

    async def _get_request(self, path: str) -> Any | None:
        """Make an authenticated GET request to the Ayla EU endpoint."""
        url = f"https://ads-eu.aylanetworks.com/{path}"
        headers = {
            "User-Agent": API_USER_AGENT,
            "Authorization": f"auth_token {self.access_token}",
            "Accept": "application/json",
        }

        try:
            async with self.session.get(url, headers=headers) as response:
                response.raise_for_status()
                return await response.json()
        except aiohttp.ClientResponseError as e:
            if e.status == 401:
                self.access_token = await self.refresh_access_token()
                if self.access_token:
                    headers["Authorization"] = f"auth_token {self.access_token}"
                    async with self.session.get(url, headers=headers) as response:
                        response.raise_for_status()
                        return await response.json()
            _LOGGER.error("GET %s failed: %s", path, e)
            return None
        except Exception as e:
            _LOGGER.error("GET %s failed: %s", path, e)
            return None

    async def _post_request(self, path: str, data: dict[str, Any]) -> Any | None:
        """Make an authenticated POST request to the Ayla EU endpoint."""
        url = f"https://ads-eu.aylanetworks.com/{path}"
        headers = {
            "User-Agent": API_USER_AGENT,
            "Authorization": f"auth_token {self.access_token}",
            "Content-Type": "application/json",
        }

        try:
            async with self.session.post(url, headers=headers, json=data) as response:
                response.raise_for_status()
                return await response.json()
        except aiohttp.ClientResponseError as e:
            if e.status == 401:
                self.access_token = await self.refresh_access_token()
                if self.access_token:
                    headers["Authorization"] = f"auth_token {self.access_token}"
                    async with self.session.post(
                        url, headers=headers, json=data
                    ) as response:
                        response.raise_for_status()
                        return await response.json()
            _LOGGER.error("POST %s failed: %s", path, e)
            return None
        except Exception as e:
            _LOGGER.error("POST %s failed: %s", path, e)
            return None
