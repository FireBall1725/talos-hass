"""WebSocket API feeding the Talos sidebar panel.

The panel needs richer per-node data than the entities expose (the full
extensions list, Talos service health, etcd members), so it pulls the
coordinator's data directly through one command instead of reading entity
states.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, callback

from .const import DOMAIN
from .coordinator import NodeData


def _serialize_node(node: NodeData) -> dict[str, Any]:
    return {
        "address": node.address,
        "hostname": node.hostname,
        "role": node.role,
        "online": node.online,
        "ready": node.ready,
        "stage": node.stage,
        "version": node.version,
        "arch": node.arch,
        "platform": node.platform,
        "cpu_pct": node.cpu_pct,
        "memory_used_pct": node.memory_used_pct,
        "memory_total": node.memory_total,
        "disk_used_pct": node.disk_used_pct,
        "boot_time": node.boot_time,
        "schematic": node.schematic,
        "extensions": node.extensions,
        "services": node.services,
        "etcd_members": node.etcd_members,
    }


@callback
@websocket_api.websocket_command({vol.Required("type"): "talos_linux/get"})
def ws_get(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return all loaded Talos clusters and their nodes."""
    clusters = []
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.state is not ConfigEntryState.LOADED:
            continue
        data = entry.runtime_data.coordinator.data
        nodes = list(data.nodes.values()) if data else []
        # Control plane first, then by name, for a stable readable order.
        nodes.sort(key=lambda n: (n.role != "controlplane", n.hostname or n.address))
        clusters.append(
            {
                "entry_id": entry.entry_id,
                "title": entry.title,
                "latest_version": data.latest_version if data else None,
                "target_version": data.target_version if data else None,
                "nodes": [_serialize_node(n) for n in nodes],
            }
        )
    connection.send_result(msg["id"], {"clusters": clusters})


@callback
def async_register_websocket_api(hass: HomeAssistant) -> None:
    """Register the panel's websocket command."""
    websocket_api.async_register_command(hass, ws_get)
