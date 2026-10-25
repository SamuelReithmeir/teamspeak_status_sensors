"""Fixtures for the TeamSpeak tests (mocked HTTP only, never a live server)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.samuelre_teamspeak.const import DOMAIN

FIXTURES = Path(__file__).parent / "fixtures"
BASE = "http://ts.test:10080/1"

ENTRY_DATA = {
    "host": "ts.test",
    "port": 10080,
    "server_id": 1,
    "api_key": "SECRET-API-KEY",
    "scan_interval": 60,
}
USERS = [
    {"db_id": 4, "uid": "MASKED_UID_4=", "name": "Maxi"},
    {"db_id": 7, "uid": "MASKED_UID_7=", "name": "Maku"},
]


def load(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / f"{name}.json").read_text())


def mock_server(aioclient_mock, clientlist: dict | None = None, **overrides) -> None:
    """Register the four allowed endpoints."""
    aioclient_mock.clear_requests()
    for endpoint in ("serverinfo", "clientlist", "clientdblist", "channellist"):
        data = overrides.get(endpoint) or load(endpoint)
        if endpoint == "clientlist" and clientlist is not None:
            data = clientlist
        aioclient_mock.post(f"{BASE}/{endpoint}", json=data)


def clientlist_without(*db_ids: str) -> dict[str, Any]:
    data = load("clientlist")
    data["body"] = [c for c in data["body"] if c["client_database_id"] not in db_ids]
    return data


@pytest.fixture(autouse=True)
def _enable(enable_custom_integrations):
    """Allow loading custom_components."""


@pytest.fixture
def entry(hass) -> MockConfigEntry:
    e = MockConfigEntry(
        domain=DOMAIN,
        data=ENTRY_DATA,
        options={"users": USERS},
        unique_id="MASKED_SERVER_UID=",
        title="Test Server",
    )
    e.add_to_hass(hass)
    return e
