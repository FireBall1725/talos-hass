"""Button platform: registration, gating, and the refresh action."""

from __future__ import annotations

from custom_components.talos_linux.const import DOMAIN
from homeassistant.helpers import entity_registry as er


async def test_action_buttons_registered(
    hass, init_integration, admin_talosconfig
) -> None:
    entry = await init_integration(admin_talosconfig)
    reg = er.async_get(hass)

    reboot = reg.async_get_entity_id(
        "button", DOMAIN, f"{entry.entry_id}_192.0.2.10_reboot"
    )
    shutdown = reg.async_get_entity_id(
        "button", DOMAIN, f"{entry.entry_id}_192.0.2.10_shutdown"
    )
    refresh = reg.async_get_entity_id(
        "button", DOMAIN, f"{entry.entry_id}_cluster_refresh"
    )

    # Destructive buttons are opt-in (disabled by default); refresh is enabled.
    assert reboot is not None and reg.async_get(reboot).disabled_by is not None
    assert shutdown is not None and reg.async_get(shutdown).disabled_by is not None
    assert refresh is not None and reg.async_get(refresh).disabled_by is None


async def test_refresh_button_triggers_poll(
    hass, init_integration, admin_talosconfig, mock_client
) -> None:
    entry = await init_integration(admin_talosconfig)
    refresh = er.async_get(hass).async_get_entity_id(
        "button", DOMAIN, f"{entry.entry_id}_cluster_refresh"
    )
    before = mock_client.version.await_count
    await hass.services.async_call(
        "button", "press", {"entity_id": refresh}, blocking=True
    )
    assert mock_client.version.await_count > before
