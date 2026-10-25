"""TeamSpeak WebQuery API Client."""

from __future__ import annotations

import asyncio
from typing import Any
from urllib.parse import quote

from aiohttp import ClientError, ClientSession
from homeassistant.exceptions import HomeAssistantError

# Flags for clientlist; each one only adds fields to the reply.
CLIENTLIST_FLAGS = ("-uid", "-away", "-voice", "-times", "-groups", "-info", "-country")

# clientdblist is paged; the page size and a hard cap keep the request count bounded.
DB_PAGE_SIZE = 50
DB_MAX_PAGES = 20
DB_PAGE_DELAY = 1.0  # seconds between pages, the query runs on one thread

ERROR_EMPTY_RESULT = 1281  # "database empty result set"
ERROR_INVALID_API_KEY = 3329


class TeamSpeakWebQueryClient:
    """Client for TeamSpeak WebQuery API."""

    def __init__(
        self,
        host: str,
        port: int,
        server_id: int,
        api_key: str,
        session: ClientSession,
    ) -> None:
        """Initialize the TeamSpeak WebQuery client."""
        self.host = host
        self.port = port
        self.server_id = server_id
        self.api_key = api_key
        self.session = session
        self.base_url = f"http://{host}:{port}/{server_id}"
        # The query runs on a single server thread: never have two requests in flight.
        self._lock = asyncio.Lock()

    def _redact(self, text: str) -> str:
        """Remove the API key from text that may end up in logs."""
        if not self.api_key:
            return text
        return text.replace(self.api_key, "***").replace(quote(self.api_key), "***")

    async def _request(
        self, endpoint: str, flags: tuple[str, ...] = (), **params: Any
    ) -> dict[str, Any]:
        """Make a request to the TeamSpeak WebQuery API."""
        # Flags are value-less query keys (e.g. ``?-uid&-away``), so the query
        # string is built by hand.
        query = [*flags, *(f"{k}={quote(str(v))}" for k, v in params.items())]
        query.append(f"api-key={quote(self.api_key)}")
        url = f"{self.base_url}/{endpoint}?{'&'.join(query)}"

        async with self._lock:
            try:
                async with asyncio.timeout(8):
                    # TeamSpeak WebQuery requires using the same session for all
                    # requests. Creating new sessions or closing connections
                    # crashes the server.
                    response = await self.session.post(url)
                    response.raise_for_status()
                    data = await response.json()
            except TimeoutError as err:
                raise CannotConnect("Timeout connecting to TeamSpeak server") from err
            except ClientError as err:
                raise CannotConnect(
                    self._redact(f"Error connecting to TeamSpeak server: {err}")
                ) from err
            except Exception as err:
                raise CannotConnect(self._redact(f"Unexpected error: {err}")) from err

        # Check API response status
        status = data.get("status", {})
        code = status.get("code", 0)
        if code != 0:
            error_msg = status.get("message", "Unknown error")
            if code == ERROR_INVALID_API_KEY:
                raise InvalidAuth(f"Invalid API key: {error_msg}")
            raise TeamSpeakApiError(f"API error: {error_msg}", code)

        return data

    async def test_connection(self) -> dict[str, Any]:
        """Test the connection and return server info."""
        data = await self._request("serverinfo")
        body = data.get("body", [])
        if not body:
            raise CannotConnect("Empty response from server")
        return body[0]

    async def get_server_info(self) -> dict[str, Any]:
        """Get server information."""
        data = await self._request("serverinfo")
        body = data.get("body", [])
        if not body:
            raise CannotConnect("Empty server info response")
        return body[0]

    async def get_client_list(self) -> list[dict[str, Any]]:
        """Get list of connected clients."""
        data = await self._request("clientlist", flags=CLIENTLIST_FLAGS)
        return data.get("body", [])

    async def get_client_db_list(self) -> list[dict[str, Any]]:
        """Get every client the server has ever seen (paged, one request at a time)."""
        result: list[dict[str, Any]] = []
        for page in range(DB_MAX_PAGES):
            if page:
                await asyncio.sleep(DB_PAGE_DELAY)
            try:
                data = await self._request(
                    "clientdblist", start=page * DB_PAGE_SIZE, duration=DB_PAGE_SIZE
                )
            except TeamSpeakApiError as err:
                if err.code == ERROR_EMPTY_RESULT:
                    break
                raise
            body = data.get("body", [])
            result.extend(body)
            if len(body) < DB_PAGE_SIZE:
                break
        return result

    async def get_channel_list(self) -> list[dict[str, Any]]:
        """Get list of channels."""
        data = await self._request("channellist")
        return data.get("body", [])


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class TeamSpeakApiError(CannotConnect):
    """The server answered with a non-zero status code."""

    def __init__(self, message: str, code: int) -> None:
        """Initialize the error."""
        super().__init__(message)
        self.code = code


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""
