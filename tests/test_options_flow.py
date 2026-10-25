"""Options flow tests: add / edit / remove users."""

from __future__ import annotations

from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from custom_components.samuelre_teamspeak.const import DOMAIN

from .conftest import mock_server


async def start(hass, entry, aioclient_mock, options=None):
    if options is not None:
        hass.config_entries.async_update_entry(entry, options=options)
    mock_server(aioclient_mock)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return await hass.config_entries.options.async_init(entry.entry_id)


async def test_menu_without_users_only_offers_add(hass, entry, aioclient_mock):
    result = await start(hass, entry, aioclient_mock, options={"users": []})
    assert result["type"] is FlowResultType.MENU
    assert result["menu_options"] == ["add_user"]


async def test_add_user_dropdown_and_entry(hass, entry, aioclient_mock):
    result = await start(hass, entry, aioclient_mock, options={"users": []})
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "add_user"}
    )
    labels = {
        o["value"]: o["label"]
        for o in result["data_schema"].schema["db_id"].config["options"]
    }
    # query client (ID 1) excluded; both "Alice" accounts distinguishable
    assert labels == {"48": "Alice (ID 48)", "4": "Alice (ID 4)", "7": "Bob (ID 7)"}

    calls_before = aioclient_mock.call_count
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"db_id": "7", "name": "Bob"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options["users"] == [
        {"db_id": 7, "uid": "MASKED_UID_7=", "name": "Bob"}
    ]
    await hass.async_block_till_done()  # reload
    assert hass.states.get("binary_sensor.tsonline_bob") is not None
    assert aioclient_mock.call_count > calls_before


async def test_add_user_rejects_duplicate_name(hass, entry, aioclient_mock):
    result = await start(hass, entry, aioclient_mock)  # Alice + Bob configured
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "add_user"}
    )
    labels = [
        o["value"] for o in result["data_schema"].schema["db_id"].config["options"]
    ]
    assert labels == ["48"]  # already configured users are not offered again
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"db_id": "48", "name": "Alice"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"name": "name_exists"}


async def test_edit_user_renames_device_but_keeps_entity_id(
    hass, entry, aioclient_mock
):
    result = await start(hass, entry, aioclient_mock)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "edit_user"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"db_id": "7"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"name": "Marcus"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    device = dr.async_get(hass).async_get_device(
        {(DOMAIN, "MASKED_SERVER_UID=_user_7")}
    )
    assert device.name == "TeamSpeak Marcus"
    assert hass.states.get("binary_sensor.tsonline_bob") is not None


async def test_remove_user_removes_device_and_entities(hass, entry, aioclient_mock):
    result = await start(hass, entry, aioclient_mock)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "remove_user"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"users": ["7"]}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    dev_reg = dr.async_get(hass)
    assert dev_reg.async_get_device({(DOMAIN, "MASKED_SERVER_UID=_user_7")}) is None
    assert dev_reg.async_get_device({(DOMAIN, "MASKED_SERVER_UID=_user_4")}) is not None
    assert dev_reg.async_get_device({(DOMAIN, "MASKED_SERVER_UID=")}) is not None
    assert hass.states.get("binary_sensor.tsonline_bob") is None
    assert not [
        e for e in er.async_get(hass).entities.values() if "_user_7_" in e.unique_id
    ]
    assert hass.states.get("binary_sensor.tsonline_alice").state == "on"
