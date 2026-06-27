"""Node discovery: VIP exclusion and address selection."""

from __future__ import annotations

from unittest.mock import AsyncMock

from custom_components.talos_linux.client import TalosClient
from custom_components.talos_linux.talosconfig import TalosCredentials


def _client(endpoints: list[str]) -> TalosClient:
    creds = TalosCredentials(
        endpoints=endpoints,
        ca_pem=b"",
        crt_pem=b"",
        key_pem=b"",
        roles=frozenset(),
    )
    return TalosClient("192.0.2.10", 50000, creds)


async def test_discover_excludes_vip_and_names_by_member_id() -> None:
    client = _client(["192.0.2.10", "192.0.2.11", "192.0.2.12"])
    # talos-cp-01 holds the VIP 192.0.2.9 (listed first), real IP is 192.0.2.10.
    client.list_resources = AsyncMock(  # type: ignore[method-assign]
        return_value=[
            {
                "id": "talos-cp-01",
                "spec": {
                    "addresses": ["192.0.2.9", "192.0.2.10", "fd00::1"],
                    "machineType": "controlplane",
                },
            },
            {
                "id": "talos-cp-02",
                "spec": {"addresses": ["192.0.2.11"], "machineType": "controlplane"},
            },
            {
                "id": "talos-wk-01",
                "spec": {"addresses": ["192.0.2.31"], "machineType": "worker"},
            },
        ]
    )
    nodes = await client.discover_nodes("192.0.2.10")
    by_name = {n["hostname"]: n for n in nodes}

    # The VIP is never chosen, and never appears as a node address.
    assert by_name["talos-cp-01"]["address"] == "192.0.2.10"
    assert "192.0.2.9" not in {n["address"] for n in nodes}
    assert by_name["talos-cp-02"]["address"] == "192.0.2.11"
    assert by_name["talos-wk-01"]["address"] == "192.0.2.31"
    assert by_name["talos-wk-01"]["type"] == "worker"


async def test_discover_skips_members_without_ipv4() -> None:
    client = _client([])
    client.list_resources = AsyncMock(  # type: ignore[method-assign]
        return_value=[
            {
                "id": "ipv6-only",
                "spec": {"addresses": ["fd00::5"], "machineType": "worker"},
            },
        ]
    )
    assert await client.discover_nodes("192.0.2.10") == []
