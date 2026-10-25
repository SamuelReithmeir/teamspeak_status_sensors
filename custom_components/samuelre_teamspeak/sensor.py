"""Sensor platform for TeamSpeak Server Info integration."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import UnitOfDataRate, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import TeamSpeakConfigEntry
from .const import CONF_USERS
from .coordinator import TeamSpeakDataUpdateCoordinator
from .entity import TeamSpeakUserEntity, server_device_info


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TeamSpeakConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up TeamSpeak sensor platform."""
    coordinator = entry.runtime_data

    # Get server info for device creation
    server_info = coordinator.data["server_info"]
    server_unique_id = server_info.get("virtualserver_unique_identifier", "")

    # Create all sensors
    sensors = [
        TeamSpeakClientsOnlineSensor(coordinator, server_unique_id),
        TeamSpeakChannelsSensor(coordinator, server_unique_id),
        TeamSpeakUptimeSensor(coordinator, server_unique_id),
        TeamSpeakMaxClientsSensor(coordinator, server_unique_id),
        TeamSpeakBandwidthReceivedSensor(coordinator, server_unique_id),
        TeamSpeakBandwidthSentSensor(coordinator, server_unique_id),
        TeamSpeakServerStatusSensor(coordinator, server_unique_id),
    ]

    for user in entry.options.get(CONF_USERS, []):
        sensors.append(TeamSpeakUserChannelSensor(coordinator, user))
        sensors.append(TeamSpeakUserSinceSensor(coordinator, user))
        sensors.append(TeamSpeakUserTotalConnectionsSensor(coordinator, user))

    async_add_entities(sensors)


class TeamSpeakBaseSensor(
    CoordinatorEntity[TeamSpeakDataUpdateCoordinator], SensorEntity
):
    """Base class for TeamSpeak sensors."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: TeamSpeakDataUpdateCoordinator,
        server_unique_id: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._server_unique_id = server_unique_id

        # Device info shared by all sensors
        self._attr_device_info = server_device_info(coordinator)


class TeamSpeakClientsOnlineSensor(TeamSpeakBaseSensor):
    """Sensor for number of clients online."""

    _attr_translation_key = "clients_online"
    _attr_icon = "mdi:account-multiple"

    def __init__(
        self,
        coordinator: TeamSpeakDataUpdateCoordinator,
        server_unique_id: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, server_unique_id)
        self._attr_unique_id = f"{server_unique_id}_clients_online"

    @property
    def native_value(self) -> int | None:
        """Return the number of real clients online (query clients excluded)."""
        return self.coordinator.data["real_clients"]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        return {
            "client_list": self.coordinator.data["client_list"],
            "query_clients": self.coordinator.data["query_clients"],
        }


class TeamSpeakChannelsSensor(TeamSpeakBaseSensor):
    """Sensor for number of channels."""

    _attr_translation_key = "channels"
    _attr_icon = "mdi:pound"

    def __init__(
        self,
        coordinator: TeamSpeakDataUpdateCoordinator,
        server_unique_id: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, server_unique_id)
        self._attr_unique_id = f"{server_unique_id}_channels"

    @property
    def native_value(self) -> int | None:
        """Return the number of channels."""
        server_info = self.coordinator.data["server_info"]
        value = server_info.get("virtualserver_channelsonline")
        return int(value) if value is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        return {
            "channel_list": self.coordinator.data["channel_list"],
        }


class TeamSpeakUptimeSensor(TeamSpeakBaseSensor):
    """Sensor for server uptime."""

    _attr_translation_key = "uptime"
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS
    _attr_icon = "mdi:clock-outline"

    def __init__(
        self,
        coordinator: TeamSpeakDataUpdateCoordinator,
        server_unique_id: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, server_unique_id)
        self._attr_unique_id = f"{server_unique_id}_uptime"

    @property
    def native_value(self) -> int | None:
        """Return the server uptime in seconds."""
        server_info = self.coordinator.data["server_info"]
        value = server_info.get("virtualserver_uptime")
        return int(value) if value is not None else None


class TeamSpeakMaxClientsSensor(TeamSpeakBaseSensor):
    """Sensor for maximum clients allowed."""

    _attr_translation_key = "max_clients"
    _attr_icon = "mdi:account-group"

    def __init__(
        self,
        coordinator: TeamSpeakDataUpdateCoordinator,
        server_unique_id: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, server_unique_id)
        self._attr_unique_id = f"{server_unique_id}_max_clients"

    @property
    def native_value(self) -> int | None:
        """Return the maximum number of clients."""
        server_info = self.coordinator.data["server_info"]
        value = server_info.get("virtualserver_maxclients")
        return int(value) if value is not None else None


class TeamSpeakBandwidthReceivedSensor(TeamSpeakBaseSensor):
    """Sensor for bandwidth received."""

    _attr_translation_key = "bandwidth_received"
    _attr_device_class = SensorDeviceClass.DATA_RATE
    _attr_native_unit_of_measurement = UnitOfDataRate.BYTES_PER_SECOND
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 2

    def __init__(
        self,
        coordinator: TeamSpeakDataUpdateCoordinator,
        server_unique_id: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, server_unique_id)
        self._attr_unique_id = f"{server_unique_id}_bandwidth_received"

    @property
    def native_value(self) -> int | None:
        """Return the bandwidth received in bytes per second."""
        server_info = self.coordinator.data["server_info"]
        value = server_info.get("connection_bandwidth_received_last_second_total")
        return int(value) if value is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        server_info = self.coordinator.data["server_info"]
        return {
            "total_bytes": int(server_info.get("connection_bytes_received_total", 0)),
            "last_minute": int(
                server_info.get("connection_bandwidth_received_last_minute_total", 0)
            ),
        }


class TeamSpeakBandwidthSentSensor(TeamSpeakBaseSensor):
    """Sensor for bandwidth sent."""

    _attr_translation_key = "bandwidth_sent"
    _attr_device_class = SensorDeviceClass.DATA_RATE
    _attr_native_unit_of_measurement = UnitOfDataRate.BYTES_PER_SECOND
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 2

    def __init__(
        self,
        coordinator: TeamSpeakDataUpdateCoordinator,
        server_unique_id: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, server_unique_id)
        self._attr_unique_id = f"{server_unique_id}_bandwidth_sent"

    @property
    def native_value(self) -> int | None:
        """Return the bandwidth sent in bytes per second."""
        server_info = self.coordinator.data["server_info"]
        value = server_info.get("connection_bandwidth_sent_last_second_total")
        return int(value) if value is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        server_info = self.coordinator.data["server_info"]
        return {
            "total_bytes": int(server_info.get("connection_bytes_sent_total", 0)),
            "last_minute": int(
                server_info.get("connection_bandwidth_sent_last_minute_total", 0)
            ),
        }


class TeamSpeakServerStatusSensor(TeamSpeakBaseSensor):
    """Sensor for server status."""

    _attr_translation_key = "server_status"
    _attr_icon = "mdi:server"

    def __init__(
        self,
        coordinator: TeamSpeakDataUpdateCoordinator,
        server_unique_id: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, server_unique_id)
        self._attr_unique_id = f"{server_unique_id}_server_status"

    @property
    def native_value(self) -> str | None:
        """Return the server status."""
        server_info = self.coordinator.data["server_info"]
        return server_info.get("virtualserver_status")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        server_info = self.coordinator.data["server_info"]
        return {
            "server_name": server_info.get("virtualserver_name"),
            "server_version": server_info.get("virtualserver_version"),
            "platform": server_info.get("virtualserver_platform"),
            "server_port": server_info.get("virtualserver_port"),
        }


class TeamSpeakUserChannelSensor(TeamSpeakUserEntity, SensorEntity):
    """Channel a tracked user is currently in."""

    _requires_online = True
    _attr_icon = "mdi:pound"

    def __init__(
        self, coordinator: TeamSpeakDataUpdateCoordinator, user: dict[str, Any]
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, user, "channel")

    @property
    def native_value(self) -> str | None:
        """Return the channel name."""
        return data.channel if (data := self.user_data) else None


class TeamSpeakUserSinceSensor(TeamSpeakUserEntity, SensorEntity):
    """Online since (while online) or last seen (while offline)."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(
        self, coordinator: TeamSpeakDataUpdateCoordinator, user: dict[str, Any]
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, user, "since")

    @property
    def available(self) -> bool:
        """Unavailable while there is no timestamp to show."""
        data = self.user_data
        return super().available and data is not None and data.since is not None

    @property
    def native_value(self) -> datetime | None:
        """Return the session start or the moment the user went offline."""
        return data.since if (data := self.user_data) else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        data = self.user_data
        return {
            "online": data.online if data else None,
            "since_estimated": data.since_estimated if data else None,
        }


class TeamSpeakUserTotalConnectionsSensor(TeamSpeakUserEntity, SensorEntity):
    """How often a tracked user has connected to the server."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:counter"

    def __init__(
        self, coordinator: TeamSpeakDataUpdateCoordinator, user: dict[str, Any]
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, user, "total_connections")

    @property
    def available(self) -> bool:
        """Unavailable until clientdblist knows the user."""
        data = self.user_data
        return (
            super().available
            and data is not None
            and data.total_connections is not None
        )

    @property
    def native_value(self) -> int | None:
        """Return the total number of connections."""
        return data.total_connections if (data := self.user_data) else None
