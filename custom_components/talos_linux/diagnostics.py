"""Diagnostics for Talos Linux.

The config entry stores the raw talosconfig (base64 CA/cert/private key), so it
is redacted out. Everything the coordinator polls is operational, non-secret
node state, which is exactly what a bug report needs, so it is included as-is.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import TalosConfigEntry
from .const import CONF_TALOSCONFIG

TO_REDACT = {CONF_TALOSCONFIG}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: TalosConfigEntry
) -> dict[str, Any]:
    """Return redacted diagnostics for a Talos config entry."""
    coordinator = entry.runtime_data.coordinator
    creds = coordinator.creds
    return {
        "entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": dict(entry.options),
        },
        "credentials": {
            # The cert bytes stay out; only the derived, non-secret facts.
            "roles": sorted(creds.roles),
            "can_write": creds.can_write,
            "can_reset": creds.can_reset,
            "not_after": creds.not_after.isoformat() if creds.not_after else None,
            "endpoints": creds.endpoints,
        },
        "data": asdict(coordinator.data),
    }
