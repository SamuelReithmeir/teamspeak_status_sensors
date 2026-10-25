"""Shared entity helpers for the TeamSpeak integration."""

from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_USER_DB_ID, CONF_USER_NAME, DOMAIN
from .coordinator import TeamSpeakDataUpdateCoordinator, UserData


def server_device_info(coordinator: TeamSpeakDataUpdateCoordinator) -> DeviceInfo:
    """Return the device info of the virtual server."""
    server_info = coordinator.data["server_info"]
    return DeviceInfo(
        identifiers={(DOMAIN, coordinator.server_unique_id)},
        name=server_info.get("virtualserver_name", "TeamSpeak Server"),
        manufacturer="TeamSpeak Systems GmbH",
        model="TeamSpeak Server",
        sw_version=server_info.get("virtualserver_version", "Unknown"),
        configuration_url=f"http://{coordinator.client.host}:{coordinator.client.port}",
    )


def user_device_identifier(server_unique_id: str, db_id: int) -> tuple[str, str]:
    """Return the device registry identifier of a tracked user."""
    return (DOMAIN, f"{server_unique_id}_user_{db_id}")


def user_device_info(
    coordinator: TeamSpeakDataUpdateCoordinator, user: dict[str, Any]
) -> DeviceInfo:
    """Return the device info of a tracked user."""
    return DeviceInfo(
        identifiers={
            user_device_identifier(coordinator.server_unique_id, user[CONF_USER_DB_ID])
        },
        name=f"TeamSpeak {user[CONF_USER_NAME]}",
        manufacturer="TeamSpeak Systems GmbH",
        model="TeamSpeak User",
        via_device=(DOMAIN, coordinator.server_unique_id),
    )


class TeamSpeakUserEntity(CoordinatorEntity[TeamSpeakDataUpdateCoordinator]):
    """Base class for entities that belong to a tracked user."""

    _attr_has_entity_name = True
    # Entities that only make sense while the user is online.
    _requires_online = False

    def __init__(
        self,
        coordinator: TeamSpeakDataUpdateCoordinator,
        user: dict[str, Any],
        key: str,
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self._db_id: int = user[CONF_USER_DB_ID]
        self._attr_translation_key = key
        self._attr_unique_id = (
            f"{coordinator.server_unique_id}_user_{self._db_id}_{key}"
        )
        self._attr_device_info = user_device_info(coordinator, user)

    @property
    def user_data(self) -> UserData | None:
        """Return the derived state of this user."""
        return self.coordinator.data["users"].get(self._db_id)

    @property
    def available(self) -> bool:
        """Return if the entity is available."""
        if not super().available or (data := self.user_data) is None:
            return False
        return data.online or not self._requires_online
