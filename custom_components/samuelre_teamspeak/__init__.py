"""The TeamSpeak Server Info integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT, CONF_SCAN_INTERVAL, Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.util import slugify

from .api import TeamSpeakWebQueryClient
from .const import (
    CONF_API_KEY,
    CONF_SERVER_ID,
    CONF_USER_DB_ID,
    CONF_USER_NAME,
    DOMAIN,
    ONLINE_OBJECT_ID_PREFIX,
)
from .coordinator import STORAGE_VERSION, TeamSpeakDataUpdateCoordinator
from .entity import server_device_info, user_device_identifier, user_device_info

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BINARY_SENSOR]

type TeamSpeakConfigEntry = ConfigEntry[TeamSpeakDataUpdateCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: TeamSpeakConfigEntry) -> bool:
    """Set up TeamSpeak Server Info from a config entry."""
    # Create API client
    session = async_get_clientsession(hass)
    client = TeamSpeakWebQueryClient(
        host=entry.data[CONF_HOST],
        port=entry.data[CONF_PORT],
        server_id=entry.data[CONF_SERVER_ID],
        api_key=entry.data[CONF_API_KEY],
        session=session,
    )

    # Create coordinator
    coordinator = TeamSpeakDataUpdateCoordinator(
        hass=hass,
        client=client,
        config_entry=entry,
        update_interval=entry.data[CONF_SCAN_INTERVAL],
    )

    # Load persisted offline timestamps, then fetch initial data. A failing first
    # refresh raises ConfigEntryNotReady, so no separate connection test is needed
    # (the query server runs on one thread; every request counts).
    await coordinator.async_load()
    await coordinator.async_config_entry_first_refresh()

    # Store coordinator in runtime data
    entry.runtime_data = coordinator

    _async_sync_devices(hass, entry, coordinator)

    # Setup platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Changing the tracked users (options) reloads the entry
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    return True


async def _async_update_listener(
    hass: HomeAssistant, entry: TeamSpeakConfigEntry
) -> None:
    """Reload the entry when its options change."""
    await hass.config_entries.async_reload(entry.entry_id)


@callback
def _async_sync_devices(
    hass: HomeAssistant,
    entry: TeamSpeakConfigEntry,
    coordinator: TeamSpeakDataUpdateCoordinator,
) -> None:
    """Create the server and user devices, and drop devices of removed users."""
    device_registry = dr.async_get(hass)
    entity_registry = er.async_get(hass)
    server_uid = coordinator.server_unique_id

    # The server device must exist before user devices reference it via_device.
    device_registry.async_get_or_create(
        config_entry_id=entry.entry_id, **server_device_info(coordinator)
    )

    wanted: set[tuple[str, str]] = set()
    for user in coordinator.users:
        identifier = user_device_identifier(server_uid, user[CONF_USER_DB_ID])
        wanted.add(identifier)
        device = device_registry.async_get_or_create(
            config_entry_id=entry.entry_id, **user_device_info(coordinator, user)
        )
        # Pin the entity id of the online sensor (binary_sensor.tsonline_<name>)
        # so templates and widgets can rely on it. Only used on first registration.
        entity_registry.async_get_or_create(
            Platform.BINARY_SENSOR,
            DOMAIN,
            f"{server_uid}_user_{user[CONF_USER_DB_ID]}_online",
            config_entry=entry,
            device_id=device.id,
            suggested_object_id=f"{ONLINE_OBJECT_ID_PREFIX}{slugify(user[CONF_USER_NAME])}",
        )

    for device in dr.async_entries_for_config_entry(device_registry, entry.entry_id):
        user_ids = {
            ident
            for domain, ident in device.identifiers
            if domain == DOMAIN and "_user_" in ident
        }
        if user_ids and not any((DOMAIN, i) in wanted for i in user_ids):
            device_registry.async_remove_device(device.id)


async def async_unload_entry(hass: HomeAssistant, entry: TeamSpeakConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: TeamSpeakConfigEntry) -> None:
    """Delete persisted data when the entry is removed."""
    await Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}").async_remove()
