"""API client tests (mocked HTTP)."""

from __future__ import annotations

import pytest
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from custom_components.samuelre_teamspeak.api import (
    CannotConnect,
    InvalidAuth,
    TeamSpeakWebQueryClient,
)

from .conftest import BASE, load


def make(hass):
    return TeamSpeakWebQueryClient(
        "ts.test", 10080, 1, "SECRET/K+Y", async_get_clientsession(hass)
    )


async def test_clientlist_flags(hass, aioclient_mock):
    aioclient_mock.post(f"{BASE}/clientlist", json=load("clientlist"))
    await make(hass).get_client_list()
    url = aioclient_mock.mock_calls[0][1].raw_query_string
    assert url == "-uid&-away&-voice&-times&-groups&-info&-country&api-key=SECRET/K%2BY"


async def test_dblist_paging_stops_on_short_page_and_empty_result(
    hass, aioclient_mock, monkeypatch
):
    monkeypatch.setattr("custom_components.samuelre_teamspeak.api.DB_PAGE_DELAY", 0)
    monkeypatch.setattr("custom_components.samuelre_teamspeak.api.DB_PAGE_SIZE", 2)
    row = {"cldbid": "1"}
    aioclient_mock.post(
        f"{BASE}/clientdblist",
        params={"start": "0"},
        json={"status": {"code": 0}, "body": [row, row]},
    )
    aioclient_mock.post(
        f"{BASE}/clientdblist",
        params={"start": "2"},
        json={"status": {"code": 1281, "message": "empty"}},
    )
    assert len(await make(hass).get_client_db_list()) == 2
    assert aioclient_mock.call_count == 2


async def test_invalid_key(hass, aioclient_mock):
    aioclient_mock.post(
        f"{BASE}/serverinfo", json={"status": {"code": 3329, "message": "bad"}}
    )
    with pytest.raises(InvalidAuth):
        await make(hass).get_server_info()


async def test_errors_do_not_leak_key(hass, aioclient_mock):
    aioclient_mock.post(f"{BASE}/serverinfo", status=500)
    with pytest.raises(CannotConnect) as err:
        await make(hass).get_server_info()
    assert "SECRET" not in str(err.value)
