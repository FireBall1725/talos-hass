"""Config flow tests."""

from __future__ import annotations

from unittest.mock import patch

from custom_components.talos_linux.client import TalosConnectionError
from custom_components.talos_linux.config_flow import _cluster_id
from custom_components.talos_linux.const import (
    CONF_ENDPOINT,
    CONF_PORT,
    CONF_TALOSCONFIG,
    DOMAIN,
)
from custom_components.talos_linux.talosconfig import parse_talosconfig
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from tests.conftest import make_talosconfig


async def test_user_flow_success(hass, mock_client) -> None:
    talosconfig = make_talosconfig("os:admin")
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM

    with (
        patch(
            "custom_components.talos_linux.config_flow.TalosClient",
            return_value=mock_client,
        ),
        patch("custom_components.talos_linux.async_setup_entry", return_value=True),
    ):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_ENDPOINT: "192.0.2.10",
                CONF_PORT: 50000,
                CONF_TALOSCONFIG: talosconfig,
            },
        )
    assert result2["type"] is FlowResultType.CREATE_ENTRY
    assert result2["data"][CONF_ENDPOINT] == "192.0.2.10"


async def test_user_flow_derives_endpoint_from_talosconfig(hass, mock_client) -> None:
    # Only the talosconfig is provided; the endpoint comes from its endpoints list.
    talosconfig = make_talosconfig("os:admin")
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    with (
        patch(
            "custom_components.talos_linux.config_flow.TalosClient",
            return_value=mock_client,
        ),
        patch("custom_components.talos_linux.async_setup_entry", return_value=True),
    ):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_TALOSCONFIG: talosconfig}
        )
    assert result2["type"] is FlowResultType.CREATE_ENTRY
    assert result2["data"][CONF_ENDPOINT] == "192.0.2.10"
    assert result2["data"][CONF_PORT] == 50000


async def test_user_flow_cannot_connect(hass, mock_client) -> None:
    mock_client.version.side_effect = TalosConnectionError("unreachable")
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    with patch(
        "custom_components.talos_linux.config_flow.TalosClient",
        return_value=mock_client,
    ):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_ENDPOINT: "192.0.2.10",
                CONF_PORT: 50000,
                CONF_TALOSCONFIG: make_talosconfig("os:admin"),
            },
        )
    assert result2["type"] is FlowResultType.FORM
    assert result2["errors"] == {"base": "cannot_connect"}


async def test_duplicate_cluster_aborts(hass, mock_client) -> None:
    talosconfig = make_talosconfig("os:admin")
    cluster_id = _cluster_id(parse_talosconfig(talosconfig))
    MockConfigEntry(domain=DOMAIN, unique_id=cluster_id).add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    with patch(
        "custom_components.talos_linux.config_flow.TalosClient",
        return_value=mock_client,
    ):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_ENDPOINT: "192.0.2.10",
                CONF_PORT: 50000,
                CONF_TALOSCONFIG: talosconfig,
            },
        )
    assert result2["type"] is FlowResultType.ABORT
    assert result2["reason"] == "already_configured"
