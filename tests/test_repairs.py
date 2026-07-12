"""Repair issues: client-cert near-expiry."""

from __future__ import annotations

from datetime import timedelta

import homeassistant.util.dt as dt_util
from custom_components.talos_linux.const import DOMAIN, ISSUE_CERT_EXPIRING
from homeassistant.helpers import issue_registry as ir


async def test_cert_expiry_issue_created_and_cleared(
    hass, init_integration, admin_talosconfig
) -> None:
    entry = await init_integration(admin_talosconfig)
    coordinator = entry.runtime_data.coordinator
    reg = ir.async_get(hass)
    issue_id = f"{ISSUE_CERT_EXPIRING}_{entry.entry_id}"

    # Conftest cert expires in 2030, so no issue at first.
    assert reg.async_get_issue(DOMAIN, issue_id) is None

    # Bring expiry inside the warning window -> issue raised on next refresh.
    coordinator.creds.not_after = dt_util.utcnow() + timedelta(days=5)
    await coordinator.async_refresh()
    assert reg.async_get_issue(DOMAIN, issue_id) is not None

    # Push expiry back out -> issue cleared.
    coordinator.creds.not_after = dt_util.utcnow() + timedelta(days=365)
    await coordinator.async_refresh()
    assert reg.async_get_issue(DOMAIN, issue_id) is None
