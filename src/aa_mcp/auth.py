import base64
import json
import logging
from datetime import datetime, timedelta, timezone

import httpx

from aa_mcp.exceptions import AuthenticationError
from aa_mcp.models.config import Settings

logger = logging.getLogger(__name__)


class AuthClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._token: str | None = None
        self._expiry: datetime | None = None

    async def get_token(self, http_client: httpx.AsyncClient) -> str:
        buffer = timedelta(seconds=self._settings.token_refresh_buffer_seconds)
        if self._token is None or (
            self._expiry is not None
            and datetime.now(timezone.utc) + buffer >= self._expiry
        ):
            await self._authenticate(http_client)
        return self._token  # type: ignore[return-value]

    async def force_refresh(self, http_client: httpx.AsyncClient) -> str:
        self._token = None
        self._expiry = None
        await self._authenticate(http_client)
        return self._token  # type: ignore[return-value]

    async def _authenticate(self, http_client: httpx.AsyncClient) -> None:
        url = f"{self._settings.control_room_url}/v2/authentication"
        payload = {
            "username": self._settings.username,
            "apiKey": self._settings.api_key,
        }
        try:
            response = await http_client.post(url, json=payload)
        except httpx.RequestError as exc:
            raise AuthenticationError(f"Network error during authentication: {exc}") from exc

        if response.status_code != 200:
            raise AuthenticationError(
                f"Authentication failed with HTTP {response.status_code}: {response.text}"
            )

        data = response.json()
        token = data.get("token")
        if not token:
            raise AuthenticationError("Authentication response did not contain a token")

        self._token = token
        self._expiry = self._parse_expiry(token)
        logger.info("Authenticated with Control Room; token expires at %s", self._expiry)

    def _parse_expiry(self, token: str) -> datetime | None:
        try:
            parts = token.split(".")
            if len(parts) != 3:
                return None
            # JWT payload is the middle segment — pad to multiple of 4 for base64
            padded = parts[1] + "=" * (4 - len(parts[1]) % 4)
            payload = json.loads(base64.urlsafe_b64decode(padded))
            exp = payload.get("exp")
            if exp is None:
                return None
            return datetime.fromtimestamp(exp, tz=timezone.utc)
        except Exception:
            logger.warning("Could not parse JWT expiry; token will not be proactively refreshed")
            return None
