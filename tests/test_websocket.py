"""The talos_linux/get websocket command feeding the panel."""

from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.talos_linux.websocket_api import ws_get


async def test_ws_get_returns_nodes_with_extensions(
    hass, init_integration, admin_talosconfig
) -> None:
    await init_integration(admin_talosconfig)
    connection = MagicMock()

    ws_get(hass, connection, {"id": 7, "type": "talos_linux/get"})

    connection.send_result.assert_called_once()
    msg_id, payload = connection.send_result.call_args[0]
    assert msg_id == 7

    clusters = payload["clusters"]
    assert len(clusters) == 1
    nodes = clusters[0]["nodes"]
    assert len(nodes) == 1

    node = nodes[0]
    assert node["hostname"] == "talos-cp-01"
    assert node["version"] == "v1.13.5"
    assert node["memory_total"] == 8108956
    # The full extensions list is exposed (entities only expose the count).
    assert any(e["name"] == "iscsi-tools" for e in node["extensions"])
    assert any(s["id"] == "apid" for s in node["services"])
