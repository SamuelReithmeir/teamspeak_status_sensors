"""Integration tests: coordinator, entities, persistence, failure handling."""

from __future__ import annotations

import logging
from datetime import timedelta

from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.samuelre_teamspeak.const import DOMAIN

from .conftest import BASE, clientlist_without, mock_server


async def setup(hass, entry, aioclient_mock, **kw):
    mock_server(aioclient_mock, **kw)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry.runtime_data


async def refresh(hass, entry, aioclient_mock, **kw):
    mock_server(aioclient_mock, **kw)
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()


async def test_server_sensor_counts_only_real_clients(hass, entry, aioclient_mock):
    await setup(hass, entry, aioclient_mock)
    state = hass.states.get("sensor.test_server_clients_online")
    assert state.state == "2"  # serverinfo says 3 (incl. the query client)
    assert state.attributes["query_clients"] == 1
    listed = state.attributes["client_list"]
    assert len(listed) == 3
    assert set(listed[0]) <= {
        "cid",
        "clid",
        "client_database_id",
        "client_nickname",
        "client_type",
    }
    assert "UID" not in str(state.attributes)


async def test_user_devices_and_entity_ids(hass, entry, aioclient_mock):
    await setup(hass, entry, aioclient_mock)
    dev_reg = dr.async_get(hass)
    server = dev_reg.async_get_device({(DOMAIN, "MASKED_SERVER_UID=")})
    bob = dev_reg.async_get_device({(DOMAIN, "MASKED_SERVER_UID=_user_7")})
    assert bob.name == "TeamSpeak Bob"
    assert bob.via_device_id == server.id

    ent_reg = er.async_get(hass)
    assert (
        ent_reg.async_get_entity_id(
            "binary_sensor", DOMAIN, "MASKED_SERVER_UID=_user_7_online"
        )
        == "binary_sensor.tsonline_bob"
    )
    # disabled by default
    for key in ("microphone_muted", "talking"):
        e = ent_reg.async_get(
            ent_reg.async_get_entity_id(
                "binary_sensor", DOMAIN, f"MASKED_SERVER_UID=_user_7_{key}"
            )
        )
        assert e.disabled_by is er.RegistryEntryDisabler.INTEGRATION
    for key in ("headphones_muted", "away"):
        e = ent_reg.async_get(
            ent_reg.async_get_entity_id(
                "binary_sensor", DOMAIN, f"MASKED_SERVER_UID=_user_7_{key}"
            )
        )
        assert e.disabled_by is None


async def test_online_state_and_attributes(hass, entry, aioclient_mock):
    await setup(hass, entry, aioclient_mock)
    state = hass.states.get("binary_sensor.tsonline_alice")
    assert state.state == "on"
    assert state.attributes["device_class"] == "presence"
    assert state.attributes["since"] == "2023-11-14T22:13:20+00:00"
    assert state.attributes["since_estimated"] is False
    assert state.attributes["nickname"] == "Alice"
    assert state.attributes["database_id"] == 4
    assert state.attributes["channel"] == "Lobby"
    assert state.attributes["headphones_muted"] is True
    assert state.attributes["microphone_muted"] is False
    assert state.attributes["talking"] is False
    for secret in ("uid", "unique", "ip"):
        assert not [k for k in state.attributes if secret in k]

    assert hass.states.get("sensor.teamspeak_alice_channel").state == "Lobby"
    assert hass.states.get("sensor.teamspeak_alice_total_connections").state == "12"
    assert (
        hass.states.get("binary_sensor.teamspeak_alice_headphones_muted").state == "on"
    )
    assert hass.states.get("binary_sensor.teamspeak_alice_away").state == "off"
    assert (
        hass.states.get("sensor.teamspeak_alice_online_since_last_seen").state
        == "2023-11-14T22:13:20+00:00"
    )


async def test_duplicate_nicknames_use_db_id(hass, entry, aioclient_mock):
    """Account 48 is also called Alice but is not online."""
    hass.config_entries.async_update_entry(
        entry,
        options={"users": [{"db_id": 48, "uid": "MASKED_UID_48=", "name": "Alice2"}]},
    )
    await setup(hass, entry, aioclient_mock)
    state = hass.states.get("binary_sensor.tsonline_alice2")
    assert state.state == "off"
    assert state.attributes["since_estimated"] is True  # never observed
    assert state.attributes["since"] == "2023-07-22T04:26:40+00:00"


async def test_going_offline_is_observed_and_persisted(
    hass, entry, aioclient_mock, freezer: FrozenDateTimeFactory, hass_storage
):
    await setup(hass, entry, aioclient_mock)
    freezer.tick(timedelta(minutes=5))
    left = dt_util.utcnow().replace(microsecond=0)
    await refresh(hass, entry, aioclient_mock, clientlist=clientlist_without("7"))

    state = hass.states.get("binary_sensor.tsonline_bob")
    assert state.state == "off"
    assert state.attributes["since"] == left.isoformat()
    assert state.attributes["since_estimated"] is False
    assert state.attributes["channel"] is None
    # status sensors are unavailable while offline; since sensor keeps a value
    assert hass.states.get("binary_sensor.teamspeak_bob_away").state == "unavailable"
    assert hass.states.get("sensor.teamspeak_bob_channel").state == "unavailable"
    assert (
        hass.states.get("sensor.teamspeak_bob_online_since_last_seen").state
        == left.isoformat()
    )

    key = f"{DOMAIN}.{entry.entry_id}"
    assert hass_storage[key]["data"]["users"]["7"]["offline_since"] == left.isoformat()

    # HA restart (still offline): observed time survives
    freezer.tick(timedelta(hours=2))
    assert await hass.config_entries.async_unload(entry.entry_id)
    mock_server(aioclient_mock, clientlist=clientlist_without("7"))
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    state = hass.states.get("binary_sensor.tsonline_bob")
    assert state.attributes["since"] == left.isoformat()
    assert state.attributes["since_estimated"] is False


async def test_left_while_ha_was_down_is_estimated(
    hass, entry, aioclient_mock, hass_storage
):
    hass_storage[f"{DOMAIN}.{entry.entry_id}"] = {
        "version": 1,
        "key": f"{DOMAIN}.{entry.entry_id}",
        "data": {"users": {"7": {"online": True, "offline_since": None}}},
    }
    await setup(hass, entry, aioclient_mock, clientlist=clientlist_without("7"))
    state = hass.states.get("binary_sensor.tsonline_bob")
    assert state.state == "off"
    assert state.attributes["since_estimated"] is True
    assert state.attributes["since"] == "2023-11-14T22:30:00+00:00"


async def test_stale_observation_is_discarded_if_user_reconnected_meanwhile(
    hass, entry, aioclient_mock, hass_storage
):
    hass_storage[f"{DOMAIN}.{entry.entry_id}"] = {
        "version": 1,
        "key": f"{DOMAIN}.{entry.entry_id}",
        "data": {
            "users": {
                "7": {"online": False, "offline_since": "2023-01-01T00:00:00+00:00"}
            }
        },
    }
    await setup(hass, entry, aioclient_mock, clientlist=clientlist_without("7"))
    state = hass.states.get("binary_sensor.tsonline_bob")
    assert state.attributes["since_estimated"] is True


async def test_request_budget_per_poll(hass, entry, aioclient_mock, freezer):
    await setup(hass, entry, aioclient_mock)
    paths = [str(c[1].path) for c in aioclient_mock.mock_calls]
    assert sorted(p.rsplit("/", 1)[1] for p in paths) == [
        "channellist",
        "clientdblist",
        "clientlist",
        "serverinfo",
    ]
    aioclient_mock.clear_requests() if False else None
    before = aioclient_mock.call_count
    freezer.tick(timedelta(seconds=61))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    names = [
        str(c[1].path).rsplit("/", 1)[1] for c in aioclient_mock.mock_calls[before:]
    ]
    assert names == ["serverinfo", "clientlist"]  # slow data is not refetched


async def test_failure_marks_unavailable_backs_off_and_recovers(
    hass, entry, aioclient_mock, caplog
):
    coordinator = await setup(hass, entry, aioclient_mock)
    aioclient_mock.clear_requests()
    aioclient_mock.post(f"{BASE}/serverinfo", exc=TimeoutError())
    caplog.set_level(logging.DEBUG)

    await coordinator.async_refresh()
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.tsonline_bob").state == "unavailable"
    assert hass.states.get("sensor.test_server_clients_online").state == "unavailable"
    assert coordinator.update_interval == timedelta(seconds=240)  # 60 * 2**2
    warnings = [
        r
        for r in caplog.records
        if r.levelno == logging.WARNING and "Failed to connect" in r.message
    ]
    assert len(warnings) == 1
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert "SECRET-API-KEY" not in caplog.text

    await refresh(hass, entry, aioclient_mock)
    assert hass.states.get("binary_sensor.tsonline_bob").state == "on"
    assert coordinator.update_interval == timedelta(seconds=60)


async def test_start_with_server_down_retries(hass, entry, aioclient_mock):
    aioclient_mock.post(f"{BASE}/serverinfo", exc=TimeoutError())
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert aioclient_mock.call_count == 1  # one request, no retry loop
