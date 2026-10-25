"""Data update coordinator for TeamSpeak integration."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigEntryAuthFailed
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import CannotConnect, InvalidAuth, TeamSpeakWebQueryClient
from .const import (
    CLIENT_TYPE_QUERY,
    CLIENT_TYPE_USER,
    CONF_USER_DB_ID,
    CONF_USER_UID,
    CONF_USERS,
    DOMAIN,
    MAX_BACKOFF_INTERVAL,
    SLOW_REFRESH_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1

# Fields of a client that are safe to expose as an attribute.
PUBLIC_CLIENT_FIELDS = (
    "cid",
    "clid",
    "client_database_id",
    "client_nickname",
    "client_type",
)


class _WarningLogger(logging.LoggerAdapter):
    """Log the coordinator's one-off "update failed" message as a warning."""

    def error(self, msg: Any, *args: Any, **kwargs: Any) -> None:
        self.warning(msg, *args, **kwargs)


def parse_timestamp(value: Any) -> datetime | None:
    """Convert a Unix timestamp string from the API to an aware datetime."""
    try:
        seconds = int(value)
    except (TypeError, ValueError):
        return None
    if seconds <= 0:
        return None
    return dt_util.utc_from_timestamp(seconds)


def as_flag(client: dict[str, Any] | None, key: str) -> bool | None:
    """Return an API 0/1 string field as a bool."""
    if client is None or key not in client:
        return None
    return str(client[key]) == "1"


@dataclass
class UserData:
    """Derived state of one tracked user."""

    online: bool
    client: dict[str, Any] | None
    since: datetime | None
    since_estimated: bool
    channel: str | None
    total_connections: int | None


class TeamSpeakDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Class to manage fetching TeamSpeak data."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: TeamSpeakWebQueryClient,
        config_entry: ConfigEntry,
        update_interval: int,
    ) -> None:
        """Initialize coordinator."""
        super().__init__(
            hass,
            _WarningLogger(_LOGGER),  # type: ignore[arg-type]
            name="TeamSpeak Server Info",
            update_interval=timedelta(seconds=update_interval),
            config_entry=config_entry,
        )
        self.client = client
        self._base_interval = update_interval
        self._failures = 0

        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{config_entry.entry_id}"
        )
        # db_id (as str) -> {"online": bool, "offline_since": iso str | None}
        self._persisted: dict[str, dict[str, Any]] = {}
        # db_ids whose previous state was observed by this process
        self._observed: set[int] = set()

        self._slow_fetched_at: datetime | None = None
        self._db_list: list[dict[str, Any]] = []
        self._channel_list: list[dict[str, Any]] = []

    @property
    def users(self) -> list[dict[str, Any]]:
        """Return the users configured in the options."""
        return self.config_entry.options.get(CONF_USERS, [])

    @property
    def server_unique_id(self) -> str:
        """Return the unique identifier of the virtual server."""
        return self.data["server_info"].get("virtualserver_unique_identifier", "")

    async def async_load(self) -> None:
        """Load persisted offline timestamps."""
        stored = await self._store.async_load() or {}
        configured = {str(user[CONF_USER_DB_ID]) for user in self.users}
        self._persisted = {
            db_id: state
            for db_id, state in stored.get("users", {}).items()
            if db_id in configured
        }

    async def async_get_db_list(self) -> list[dict[str, Any]]:
        """Return clientdblist, using the cache unless it is stale."""
        if self._slow_due(dt_util.utcnow()) or not self._db_list:
            await self._async_fetch_slow(dt_util.utcnow(), strict=True)
        return self._db_list

    def _slow_due(self, now: datetime) -> bool:
        return (
            self._slow_fetched_at is None
            or now - self._slow_fetched_at >= timedelta(seconds=SLOW_REFRESH_INTERVAL)
        )

    async def _async_fetch_slow(self, now: datetime, strict: bool = False) -> None:
        """Refresh clientdblist and channellist (rarely changing data)."""
        # Mark as attempted first so a failing server is not asked again each poll.
        self._slow_fetched_at = now
        try:
            db_list = await self.client.get_client_db_list()
            channel_list = await self.client.get_channel_list()
        except InvalidAuth:
            raise
        except CannotConnect as err:
            if strict:
                raise
            _LOGGER.debug("Keeping previous db/channel list: %s", err)
            return
        self._db_list = db_list
        self._channel_list = channel_list

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from TeamSpeak server."""
        now = dt_util.utcnow().replace(microsecond=0)
        try:
            # TeamSpeak WebQuery requires sequential requests using the same session
            # The server crashes if we create new sessions or close connections
            server_info = await self.client.get_server_info()
            clients = await self.client.get_client_list()
            if self._slow_due(now):
                await self._async_fetch_slow(now)
        except InvalidAuth as err:
            raise ConfigEntryAuthFailed("Invalid API key") from err
        except CannotConnect as err:
            self._failures += 1
            # Back off instead of hammering a struggling server.
            self.update_interval = timedelta(
                seconds=min(
                    self._base_interval * 2**self._failures, MAX_BACKOFF_INTERVAL
                )
            )
            raise UpdateFailed(f"Failed to connect to TeamSpeak server: {err}") from err

        if self._failures:
            self._failures = 0
            self.update_interval = timedelta(seconds=self._base_interval)

        users = await self._async_build_users(now, clients)
        return {
            "server_info": server_info,
            "client_list": [
                {key: c[key] for key in PUBLIC_CLIENT_FIELDS if key in c}
                for c in clients
            ],
            "real_clients": sum(
                1 for c in clients if c.get("client_type") == CLIENT_TYPE_USER
            ),
            "query_clients": sum(
                1 for c in clients if c.get("client_type") == CLIENT_TYPE_QUERY
            ),
            "channel_list": self._channel_list,
            "users": users,
        }

    def _find_client(
        self, user: dict[str, Any], clients: list[dict[str, Any]]
    ) -> dict[str, Any] | None:
        """Find the real client for a configured user (db id first, then uid)."""
        real = [c for c in clients if c.get("client_type") == CLIENT_TYPE_USER]
        db_id = str(user[CONF_USER_DB_ID])
        for c in real:
            if c.get("client_database_id") == db_id:
                return c
        uid = user.get(CONF_USER_UID)
        if uid:
            for c in real:
                if c.get("client_unique_identifier") == uid:
                    return c
        return None

    def _find_db_entry(self, user: dict[str, Any]) -> dict[str, Any] | None:
        db_id = str(user[CONF_USER_DB_ID])
        for entry in self._db_list:
            if entry.get("cldbid") == db_id:
                return entry
        uid = user.get(CONF_USER_UID)
        if uid:
            for entry in self._db_list:
                if entry.get("client_unique_identifier") == uid:
                    return entry
        return None

    async def _async_build_users(
        self, now: datetime, clients: list[dict[str, Any]]
    ) -> dict[int, UserData]:
        """Derive per-user state and track online/offline transitions."""
        channel_names = {
            c.get("cid"): c.get("channel_name") for c in self._channel_list
        }
        result: dict[int, UserData] = {}
        changed = False

        for user in self.users:
            db_id = user[CONF_USER_DB_ID]
            key = str(db_id)
            client = self._find_client(user, clients)
            db_entry = self._find_db_entry(user)
            db_last = (
                parse_timestamp(db_entry.get("client_lastconnected"))
                if db_entry
                else None
            )
            total = None
            if db_entry is not None:
                try:
                    total = int(db_entry["client_totalconnections"])
                except (KeyError, TypeError, ValueError):
                    total = None

            persisted = self._persisted.get(key)
            if client is not None:
                since = parse_timestamp(client.get("client_lastconnected"))
                estimated = False
                channel = channel_names.get(client.get("cid")) or (
                    f"Channel {client['cid']}" if client.get("cid") else None
                )
                if persisted is None or persisted.get("online") is not True:
                    self._persisted[key] = {"online": True, "offline_since": None}
                    changed = True
                self._observed.add(db_id)
            else:
                channel = None
                offline_since: datetime | None = None
                if persisted is not None and persisted.get("online") is not True:
                    offline_since = dt_util.parse_datetime(
                        persisted.get("offline_since") or ""
                    )
                if db_id in self._observed:
                    # We saw the user online earlier in this run: this is the
                    # moment we noticed them leaving.
                    offline_since = now
                    self._observed.discard(db_id)
                    self._persisted[key] = {
                        "online": False,
                        "offline_since": now.isoformat(),
                    }
                    changed = True
                elif persisted is None or persisted.get("online") is not False:
                    # Never seen offline by us (first run, or HA was down when
                    # they left): remember it, but there is no observed time.
                    self._persisted[key] = {"online": False, "offline_since": None}
                    changed = True
                    offline_since = None

                if (
                    offline_since is not None
                    and db_last is not None
                    and db_last > offline_since
                ):
                    # They connected again while HA was not running.
                    offline_since = None

                if offline_since is not None:
                    since, estimated = offline_since, False
                else:
                    since, estimated = db_last, db_last is not None

            result[db_id] = UserData(
                online=client is not None,
                client=client,
                since=since,
                since_estimated=estimated,
                channel=channel,
                total_connections=total,
            )

        if changed:
            await self._store.async_save({"users": self._persisted})
        return result
