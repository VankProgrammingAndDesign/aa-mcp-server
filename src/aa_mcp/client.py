import logging
from typing import Any

import httpx

from aa_mcp.auth import AuthClient
from aa_mcp.exceptions import AuthenticationError, ControlRoomError, NetworkError
from aa_mcp.models.config import Settings

logger = logging.getLogger(__name__)


class ControlRoomClient:
    def __init__(self, settings: Settings, auth: AuthClient, http: httpx.AsyncClient) -> None:
        self._settings = settings
        self._auth = auth
        self._http = http

    async def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        return await self._request("GET", path, params=params)

    async def post(self, path: str, body: dict[str, Any] | None = None) -> Any:
        return await self._request("POST", path, json=body)

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        url = f"{self._settings.control_room_url}{path}"
        token = await self._auth.get_token(self._http)
        headers = {"X-Authorization": token, "Content-Type": "application/json"}

        logger.debug("%s %s", method, url)
        try:
            response = await self._http.request(method, url, headers=headers, **kwargs)
        except httpx.TimeoutException as exc:
            raise NetworkError(f"Request timed out: {url}") from exc
        except httpx.RequestError as exc:
            raise NetworkError(f"Connection error: {exc}") from exc

        logger.debug("Response: %s", response.status_code)

        if response.status_code == 401:
            # Token may have been revoked — refresh once and retry
            logger.info("Received 401; refreshing token and retrying")
            token = await self._auth.force_refresh(self._http)
            headers["X-Authorization"] = token
            try:
                response = await self._http.request(method, url, headers=headers, **kwargs)
            except httpx.RequestError as exc:
                raise NetworkError(f"Connection error on retry: {exc}") from exc
            if response.status_code == 401:
                raise AuthenticationError("Authentication failed after token refresh")

        if response.status_code >= 400:
            self._raise_for_status(response)

        return response.json() if response.content else {}

    def _raise_for_status(self, response: httpx.Response) -> None:
        try:
            message = response.json().get("message", response.text)
        except Exception:
            message = response.text
        raise ControlRoomError(response.status_code, message, response.text)
