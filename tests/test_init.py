"""Setup, entities, and unload."""

from __future__ import annotations

from custom_components.talos_linux.const import DOMAIN, SERVICE_REBOOT_NODE
from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import device_registry as dr


async def test_setup_creates_entities(
    hass, init_integration, admin_talosconfig
) -> None:
    entry = await init_integration(admin_talosconfig)
    assert entry.state is ConfigEntryState.LOADED

    version = hass.states.get("sensor.talos_cp_01_talos_version")
    assert version is not None
    assert version.state == "v1.13.5"

    reachable = hass.states.get("binary_sensor.talos_cp_01_reachable")
    assert reachable is not None
    assert reachable.state == "on"

    nodes = hass.states.get("sensor.talos_cluster_nodes")
    assert nodes is not None
    assert nodes.state == "1"

    update = hass.states.get("update.talos_cp_01_talos_os")
    assert update is not None


async def test_stale_node_device_pruned_on_refresh(
    hass, init_integration, admin_talosconfig
) -> None:
    entry = await init_integration(admin_talosconfig)
    registry = dr.async_get(hass)
    stale = {(DOMAIN, f"{entry.entry_id}_192.0.2.99")}
    registry.async_get_or_create(
        config_entry_id=entry.entry_id, identifiers=stale, name="old node"
    )
    assert registry.async_get_device(identifiers=stale) is not None

    await entry.runtime_data.coordinator.async_refresh()
    await hass.async_block_till_done()

    # The stale node device is gone; the live node and cluster devices remain.
    assert registry.async_get_device(identifiers=stale) is None
    assert (
        registry.async_get_device(
            identifiers={(DOMAIN, f"{entry.entry_id}_192.0.2.10")}
        )
        is not None
    )
    assert registry.async_get_device(identifiers={(DOMAIN, entry.entry_id)}) is not None


async def test_services_registered(hass, init_integration, admin_talosconfig) -> None:
    await init_integration(admin_talosconfig)
    assert hass.services.has_service(DOMAIN, SERVICE_REBOOT_NODE)


async def test_unload_removes_services(
    hass, init_integration, admin_talosconfig
) -> None:
    entry = await init_integration(admin_talosconfig)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED
    assert not hass.services.has_service(DOMAIN, SERVICE_REBOOT_NODE)
