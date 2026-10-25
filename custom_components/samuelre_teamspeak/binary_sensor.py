"""Binary sensor platform for TeamSpeak users."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import TeamSpeakConfigEntry
from .const import CONF_USERS
from .coordinator import TeamSpeakDataUpdateCoordinator, as_flag
from .entity import TeamSpeakUserEntity

# key -> (client field, enabled by default)
STATUS_SENSORS: dict[str, tuple[str, bool]] = {
    "microphone_muted": ("client_input_muted", False),
    "headphones_muted": ("client_output_muted", True),
    "away": ("client_away", True),
    "talking": ("client_flag_talking", False),
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TeamSpeakConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the TeamSpeak binary sensors."""
    coordinator = entry.runtime_data
    entities: list[BinarySensorEntity] = []
    for user in entry.options.get(CONF_USERS, []):
        entities.append(TeamSpeakUserOnlineSensor(coordinator, user))
        entities.extend(
            TeamSpeakUserStatusSensor(coordinator, user, key, field, default)
            for key, (field, default) in STATUS_SENSORS.items()
        )
    async_add_entities(entities)


class TeamSpeakUserOnlineSensor(TeamSpeakUserEntity, BinarySensorEntity):
    """Whether a tracked user is connected to the server."""

    _attr_device_class = BinarySensorDeviceClass.PRESENCE

    def __init__(
        self, coordinator: TeamSpeakDataUpdateCoordinator, user: dict[str, Any]
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, user, "online")

    @property
    def is_on(self) -> bool | None:
        """Return true if the user is online."""
        return data.online if (data := self.user_data) else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        data = self.user_data
        if data is None:
            return {}
        client = data.client
        return {
            "since": data.since.isoformat() if data.since else None,
            "since_estimated": data.since_estimated,
            "nickname": client.get("client_nickname") if client else None,
            "database_id": self._db_id,
            "channel": data.channel,
            "microphone_muted": as_flag(client, "client_input_muted"),
            "headphones_muted": as_flag(client, "client_output_muted"),
            "away": as_flag(client, "client_away"),
            "talking": as_flag(client, "client_flag_talking"),
        }


class TeamSpeakUserStatusSensor(TeamSpeakUserEntity, BinarySensorEntity):
    """A flag of a tracked user's client (muted, away, talking)."""

    _requires_online = True

    def __init__(
        self,
        coordinator: TeamSpeakDataUpdateCoordinator,
        user: dict[str, Any],
        key: str,
        field: str,
        enabled_default: bool,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, user, key)
        self._field = field
        self._attr_entity_registry_enabled_default = enabled_default

    @property
    def is_on(self) -> bool | None:
        """Return the flag of the user's client."""
        data = self.user_data
        return as_flag(data.client, self._field) if data else None
