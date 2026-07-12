"""Diagnostics redaction and shape."""

from __future__ import annotations

from custom_components.talos_linux.const import CONF_TALOSCONFIG
from custom_components.talos_linux.diagnostics import (
    async_get_config_entry_diagnostics,
)


async def test_diagnostics_redacts_talosconfig(
    hass, init_integration, admin_talosconfig
) -> None:
    entry = await init_integration(admin_talosconfig)
    diag = await async_get_config_entry_diagnostics(hass, entry)

    # The raw talosconfig (base64 CA/cert/key) must not leak.
    assert diag["entry"]["data"][CONF_TALOSCONFIG] == "**REDACTED**"
    assert admin_talosconfig not in repr(diag)

    # Non-secret operational state is present and useful.
    assert diag["credentials"]["roles"] == ["os:admin"]
    assert diag["credentials"]["can_write"] is True
    assert "192.0.2.10" in diag["data"]["nodes"]
    assert diag["data"]["nodes"]["192.0.2.10"]["version"] == "v1.13.5"
