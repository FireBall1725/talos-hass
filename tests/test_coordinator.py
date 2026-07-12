"""Coordinator behavior: data shape, failure isolation, auth -> reauth."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from custom_components.talos_linux.client import TalosAuthError, TalosConnectionError


async def test_node_data(hass, init_integration, admin_talosconfig) -> None:
    entry = await init_integration(admin_talosconfig)
    coordinator = entry.runtime_data.coordinator
    node = coordinator.data.nodes["192.0.2.10"]

    assert node.online is True
    assert node.version == "v1.13.5"
    assert node.stage == "running"
    assert node.ready is True
    assert node.schematic == "a28d863"
    assert node.disk_used_pct == pytest.approx(
        (105099821056 - 94522085376) / 105099821056 * 100, abs=0.1
    )
    assert node.memory_used_pct == pytest.approx(
        (8108956 - 5202912) / 8108956 * 100, abs=0.1
    )
    # First cycle has no previous CPU sample.
    assert node.cpu_pct is None
    assert coordinator.data.target_version == "v1.13.5"
    # Client-cert expiry comes off the talosconfig cert (conftest: 2030-01-01).
    assert coordinator.data.cert_expires == datetime(2030, 1, 1, tzinfo=UTC)


async def test_volumes_filtered_to_var_mnt(
    hass, init_integration, admin_talosconfig, mock_client
) -> None:
    mock_client.mounts.return_value = [
        {"filesystem": "/dev/sda5", "mounted_on": "/var", "size": 100, "available": 40},
        {
            "filesystem": "/dev/sdb1",
            "mounted_on": "/var/mnt/longhorn-data",
            "size": 200,
            "available": 50,
        },
        # tmpfs under /var/mnt is not a real block device -> excluded.
        {
            "filesystem": "tmpfs",
            "mounted_on": "/var/mnt/ram",
            "size": 10,
            "available": 10,
        },
        # kubelet pod bind mount (not under /var/mnt) -> excluded.
        {
            "filesystem": "/dev/sdc1",
            "mounted_on": "/var/lib/kubelet/pods/x",
            "size": 5,
            "available": 1,
        },
    ]
    entry = await init_integration(admin_talosconfig)
    node = entry.runtime_data.coordinator.data.nodes["192.0.2.10"]
    vols = {v["mounted_on"]: v for v in node.volumes}
    assert set(vols) == {"/var/mnt/longhorn-data"}
    assert vols["/var/mnt/longhorn-data"]["used_pct"] == pytest.approx(
        (200 - 50) / 200 * 100, abs=0.1
    )


async def test_cpu_percent_after_second_cycle(
    hass, init_integration, admin_talosconfig, mock_client
) -> None:
    entry = await init_integration(admin_talosconfig)
    coordinator = entry.runtime_data.coordinator
    # Advance the cumulative counters: 50 of 100 added jiffies were idle -> 50%.
    mock_client.cpu_times.return_value = {
        "total": 115936.73,
        "idle": 107612.35,
        "boot_time": 1782477038,
    }
    await coordinator.async_refresh()
    assert coordinator.data.nodes["192.0.2.10"].cpu_pct == pytest.approx(50.0, abs=0.5)


async def test_per_node_failure_isolation(
    hass, init_integration, admin_talosconfig, mock_client
) -> None:
    entry = await init_integration(admin_talosconfig)
    coordinator = entry.runtime_data.coordinator
    mock_client.version.side_effect = TalosConnectionError("down")
    await coordinator.async_refresh()
    node = coordinator.data.nodes["192.0.2.10"]
    assert node.online is False
    assert coordinator.last_update_success is True


async def test_auth_error_triggers_reauth(
    hass, init_integration, admin_talosconfig, mock_client
) -> None:
    entry = await init_integration(admin_talosconfig)
    coordinator = entry.runtime_data.coordinator
    mock_client.version.side_effect = TalosAuthError("denied")
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    flows = hass.config_entries.flow.async_progress()
    assert any(flow["context"].get("source") == "reauth" for flow in flows)
