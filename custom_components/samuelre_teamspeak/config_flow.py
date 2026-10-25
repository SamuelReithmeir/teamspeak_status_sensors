"""Config flow for the TeamSpeak Server Info integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_HOST, CONF_PORT, CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)
from homeassistant.util import slugify

from .api import CannotConnect, InvalidAuth, TeamSpeakWebQueryClient
from .const import (
    CLIENT_TYPE_QUERY,
    CONF_API_KEY,
    CONF_SERVER_ID,
    CONF_USER_DB_ID,
    CONF_USER_NAME,
    CONF_USER_UID,
    CONF_USERS,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SERVER_ID,
    DOMAIN,
    MIN_SCAN_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_PORT, default=DEFAULT_PORT): int,
        vol.Required(CONF_SERVER_ID, default=DEFAULT_SERVER_ID): int,
        vol.Required(CONF_API_KEY): str,
        vol.Required(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): vol.All(
            int, vol.Range(min=MIN_SCAN_INTERVAL)
        ),
    }
)


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Validate the user input allows us to connect.

    Data has the keys from STEP_USER_DATA_SCHEMA with values provided by the user.
    """
    session = async_get_clientsession(hass)
    client = TeamSpeakWebQueryClient(
        host=data[CONF_HOST],
        port=data[CONF_PORT],
        server_id=data[CONF_SERVER_ID],
        api_key=data[CONF_API_KEY],
        session=session,
    )

    server_info = await client.test_connection()

    # Return info that you want to store in the config entry.
    return {
        "title": server_info.get("virtualserver_name", "TeamSpeak Server"),
        "unique_id": server_info.get("virtualserver_unique_identifier"),
    }


class TeamSpeakConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for TeamSpeak Server Info."""

    VERSION = 1

    @staticmethod
    def async_get_options_flow(config_entry: ConfigEntry) -> TeamSpeakOptionsFlow:
        """Create the options flow."""
        return TeamSpeakOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                info = await validate_input(self.hass, user_input)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except Exception:
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                # Set unique ID to prevent duplicate setups
                await self.async_set_unique_id(info["unique_id"])
                self._abort_if_unique_id_configured()

                return self.async_create_entry(title=info["title"], data=user_input)

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )


def _label(name: str, db_id: int) -> str:
    return f"{name} (ID {db_id})"


class TeamSpeakOptionsFlow(OptionsFlow):
    """Manage the TeamSpeak users that get their own device."""

    def __init__(self) -> None:
        """Initialize the options flow."""
        self._users: list[dict[str, Any]] | None = None
        self._edit_db_id: int | None = None

    @property
    def users(self) -> list[dict[str, Any]]:
        """Return the working copy of the configured users."""
        if self._users is None:
            self._users = [
                dict(u) for u in self.config_entry.options.get(CONF_USERS, [])
            ]
        return self._users

    def _save(self) -> ConfigFlowResult:
        return self.async_create_entry(
            data={**self.config_entry.options, CONF_USERS: self.users}
        )

    def _name_taken(self, name: str, ignore_db_id: int | None = None) -> bool:
        """The online entity id derives from the name, so names must be unique."""
        slug = slugify(name)
        return not slug or any(
            slugify(u[CONF_USER_NAME]) == slug
            for u in self.users
            if u[CONF_USER_DB_ID] != ignore_db_id
        )

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the menu."""
        menu = ["add_user"]
        if self.users:
            menu += ["edit_user", "remove_user"]
        return self.async_show_menu(step_id="init", menu_options=menu)

    async def async_step_add_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick a known TeamSpeak user and give it a display name."""
        errors: dict[str, str] = {}
        coordinator = getattr(self.config_entry, "runtime_data", None)
        if coordinator is None:
            return self.async_abort(reason="not_loaded")

        try:
            # Cached for a few minutes; this is the only request this step makes.
            db_list = await coordinator.async_get_db_list()
        except (CannotConnect, InvalidAuth):
            return self.async_abort(reason="cannot_connect")

        query_db_ids = {
            c["client_database_id"]
            for c in coordinator.data["client_list"]
            if c.get("client_type") == CLIENT_TYPE_QUERY
        }
        known = {u[CONF_USER_DB_ID] for u in self.users}
        candidates = {}
        for entry in db_list:
            try:
                db_id = int(entry["cldbid"])
            except (KeyError, ValueError):
                continue
            if (
                db_id in known
                or entry["cldbid"] in query_db_ids
                or entry.get("client_login_name")
            ):
                continue
            candidates[db_id] = entry

        if not candidates:
            return self.async_abort(reason="no_users")

        if user_input is not None:
            db_id = int(user_input[CONF_USER_DB_ID])
            entry = candidates[db_id]
            name = user_input.get(CONF_USER_NAME, "").strip() or entry.get(
                "client_nickname", ""
            )
            if self._name_taken(name):
                errors[CONF_USER_NAME] = "name_exists"
            else:
                self.users.append(
                    {
                        CONF_USER_DB_ID: db_id,
                        CONF_USER_UID: entry.get("client_unique_identifier", ""),
                        CONF_USER_NAME: name,
                    }
                )
                return self._save()

        options = [
            SelectOptionDict(
                value=str(db_id), label=_label(e.get("client_nickname", "?"), db_id)
            )
            for db_id, e in sorted(
                candidates.items(),
                key=lambda i: i[1].get("client_nickname", "").lower(),
            )
        ]
        return self.async_show_form(
            step_id="add_user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_USER_DB_ID): SelectSelector(
                        SelectSelectorConfig(
                            options=options, mode=SelectSelectorMode.DROPDOWN
                        )
                    ),
                    vol.Optional(CONF_USER_NAME): str,
                }
            ),
            errors=errors,
        )

    def _user_options(self) -> list[SelectOptionDict]:
        return [
            SelectOptionDict(
                value=str(u[CONF_USER_DB_ID]),
                label=_label(u[CONF_USER_NAME], u[CONF_USER_DB_ID]),
            )
            for u in self.users
        ]

    async def async_step_edit_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose which user to rename."""
        if user_input is not None:
            self._edit_db_id = int(user_input[CONF_USER_DB_ID])
            return await self.async_step_edit_name()
        return self.async_show_form(
            step_id="edit_user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_USER_DB_ID): SelectSelector(
                        SelectSelectorConfig(
                            options=self._user_options(),
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    )
                }
            ),
        )

    async def async_step_edit_name(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Rename the chosen user."""
        errors: dict[str, str] = {}
        user = next(u for u in self.users if u[CONF_USER_DB_ID] == self._edit_db_id)
        if user_input is not None:
            name = user_input[CONF_USER_NAME].strip()
            if self._name_taken(name, ignore_db_id=self._edit_db_id):
                errors[CONF_USER_NAME] = "name_exists"
            else:
                user[CONF_USER_NAME] = name
                return self._save()
        return self.async_show_form(
            step_id="edit_name",
            data_schema=vol.Schema(
                {vol.Required(CONF_USER_NAME, default=user[CONF_USER_NAME]): str}
            ),
            errors=errors,
            description_placeholders={
                "user": _label(user[CONF_USER_NAME], user[CONF_USER_DB_ID])
            },
        )

    async def async_step_remove_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Remove users; their devices are removed when the entry reloads."""
        if user_input is not None:
            remove = {int(i) for i in user_input[CONF_USERS]}
            self._users = [u for u in self.users if u[CONF_USER_DB_ID] not in remove]
            return self._save()
        return self.async_show_form(
            step_id="remove_user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_USERS): SelectSelector(
                        SelectSelectorConfig(
                            options=self._user_options(),
                            multiple=True,
                            mode=SelectSelectorMode.LIST,
                        )
                    )
                }
            ),
        )
