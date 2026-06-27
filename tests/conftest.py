"""Shared fixtures for the Talos Linux tests."""

from __future__ import annotations

import base64
import datetime
from collections.abc import Callable
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.x509.oid import NameOID
from custom_components.talos_linux.const import (
    CONF_ENDPOINT,
    CONF_PORT,
    CONF_TALOSCONFIG,
    DOMAIN,
    GITHUB_RELEASES_URL,
)
from pytest_homeassistant_custom_component.common import MockConfigEntry


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Let HA load the custom integration in tests."""
    yield


def make_talosconfig(*roles: str) -> str:
    """A valid talosconfig YAML with an Ed25519 cert carrying the given roles."""
    key = ed25519.Ed25519PrivateKey.generate()
    name = x509.Name(
        [x509.NameAttribute(NameOID.COMMON_NAME, "talos")]
        + [x509.NameAttribute(NameOID.ORGANIZATION_NAME, r) for r in roles]
    )
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(1)
        .not_valid_before(datetime.datetime(2020, 1, 1))
        .not_valid_after(datetime.datetime(2030, 1, 1))
        .sign(key, None)
    )
    crt = cert.public_bytes(serialization.Encoding.PEM)
    key_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )

    def b(value: bytes) -> str:
        return base64.b64encode(value).decode()

    return (
        "context: home\n"
        "contexts:\n"
        "  home:\n"
        "    endpoints:\n"
        "      - 192.0.2.10\n"
        f"    ca: {b(crt)}\n"
        f"    crt: {b(crt)}\n"
        f"    key: {b(key_pem)}\n"
    )


@pytest.fixture
def admin_talosconfig() -> str:
    return make_talosconfig("os:admin")


@pytest.fixture
def reader_talosconfig() -> str:
    return make_talosconfig("os:reader")


@pytest.fixture
def mock_client() -> AsyncMock:
    """A TalosClient mock returning live-shaped data for one control-plane node."""
    client = AsyncMock()
    client.discover_nodes.return_value = [
        {"address": "192.0.2.10", "hostname": "talos-cp-01", "type": "controlplane"}
    ]
    client.version.return_value = {
        "hostname": "talos-cp-01",
        "tag": "v1.13.5",
        "sha": "abc",
        "os": "linux",
        "arch": "amd64",
        "platform": "vmware",
        "platform_mode": "metal",
    }
    client.memory.return_value = {
        "total": 8108956,
        "available": 5202912,
        "free": 2283852,
    }
    client.cpu_times.return_value = {
        "total": 115836.73,
        "idle": 107562.35,
        "boot_time": 1782477038,
    }
    client.mounts.return_value = [
        {
            "filesystem": "/dev/sda5",
            "mounted_on": "/var",
            "size": 105099821056,
            "available": 94522085376,
        }
    ]
    client.machine_status.return_value = {
        "stage": "running",
        "ready": True,
        "unmet_conditions": [],
    }
    client.extensions.return_value = [
        {"id": "3", "name": "schematic", "version": "a28d863"},
        {"id": "0", "name": "iscsi-tools", "version": "v0.2.0"},
    ]
    client.services.return_value = [
        {"id": "apid", "state": "Running", "healthy": True, "unknown": False}
    ]
    client.etcd_members.return_value = [
        {"id": 1, "hostname": "talos-cp-01", "is_learner": False}
    ]
    return client


@pytest.fixture
def init_integration(
    hass, mock_client: AsyncMock, aioclient_mock
) -> Callable[..., Any]:
    """Factory: set up the integration with the mock client and given options."""

    async def _setup(
        talosconfig: str, options: dict[str, Any] | None = None
    ) -> MockConfigEntry:
        aioclient_mock.get(GITHUB_RELEASES_URL, json={"tag_name": "v1.13.5"})
        entry = MockConfigEntry(
            domain=DOMAIN,
            data={
                CONF_ENDPOINT: "192.0.2.10",
                CONF_PORT: 50000,
                CONF_TALOSCONFIG: talosconfig,
            },
            options=options or {},
            unique_id="cluster-1",
        )
        entry.add_to_hass(hass)
        with patch(
            "custom_components.talos_linux.TalosClient", return_value=mock_client
        ):
            await hass.config_entries.async_setup(entry.entry_id)
            await hass.async_block_till_done()
        return entry

    return _setup
