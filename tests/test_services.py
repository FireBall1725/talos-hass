"""Service gating tests."""

from __future__ import annotations

import pytest
from custom_components.talos_linux.const import (
    ATTR_CONFIG_ENTRY_ID,
    ATTR_CONFIRM_NODE,
    ATTR_NODE,
    DOMAIN,
    OPT_ALLOW_DESTRUCTIVE,
    OPT_ALLOW_RESET,
    SERVICE_REBOOT_NODE,
    SERVICE_RESET_NODE,
)
from homeassistant.exceptions import ServiceValidationError


def _call(entry, node="192.0.2.10", confirm="192.0.2.10"):
    return {
        ATTR_CONFIG_ENTRY_ID: entry.entry_id,
        ATTR_NODE: node,
        ATTR_CONFIRM_NODE: confirm,
    }


async def test_reboot_blocked_when_destructive_off(
    hass, init_integration, admin_talosconfig, mock_client
) -> None:
    entry = await init_integration(admin_talosconfig)
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, SERVICE_REBOOT_NODE, _call(entry), blocking=True
        )
    mock_client.reboot.assert_not_called()


async def test_reboot_allowed_with_toggle_and_admin(
    hass, init_integration, admin_talosconfig, mock_client
) -> None:
    entry = await init_integration(admin_talosconfig, {OPT_ALLOW_DESTRUCTIVE: True})
    await hass.services.async_call(
        DOMAIN, SERVICE_REBOOT_NODE, _call(entry), blocking=True
    )
    mock_client.reboot.assert_awaited_once()


async def test_reboot_blocked_for_reader_cert(
    hass, init_integration, reader_talosconfig, mock_client
) -> None:
    entry = await init_integration(reader_talosconfig, {OPT_ALLOW_DESTRUCTIVE: True})
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, SERVICE_REBOOT_NODE, _call(entry), blocking=True
        )
    mock_client.reboot.assert_not_called()


async def test_confirm_node_mismatch_blocks(
    hass, init_integration, admin_talosconfig, mock_client
) -> None:
    entry = await init_integration(admin_talosconfig, {OPT_ALLOW_DESTRUCTIVE: True})
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_REBOOT_NODE,
            _call(entry, confirm="192.0.2.99"),
            blocking=True,
        )
    mock_client.reboot.assert_not_called()


async def test_reset_blocked_without_reset_toggle(
    hass, init_integration, admin_talosconfig, mock_client
) -> None:
    # Destructive on, but the separate reset toggle is off.
    entry = await init_integration(admin_talosconfig, {OPT_ALLOW_DESTRUCTIVE: True})
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, SERVICE_RESET_NODE, _call(entry), blocking=True
        )
    mock_client.reset.assert_not_called()


async def test_reset_allowed_with_both_toggles_and_admin(
    hass, init_integration, admin_talosconfig, mock_client
) -> None:
    entry = await init_integration(
        admin_talosconfig, {OPT_ALLOW_DESTRUCTIVE: True, OPT_ALLOW_RESET: True}
    )
    await hass.services.async_call(
        DOMAIN, SERVICE_RESET_NODE, _call(entry), blocking=True
    )
    mock_client.reset.assert_awaited_once()
