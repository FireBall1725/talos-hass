"""Services for Talos Linux, with call-time safety gating.

Tiers:
  0  refresh, get_service_status        always available (reads / no-op)
  1  reboot_node, upgrade_node, apply_config   needs allow_destructive + a
                                               write-capable cert role
  2  reset_node                         needs allow_reset + an admin cert role

Every tier-1/2 call must pass confirm_node matching node, and an explicit
config_entry_id (no "first cluster" fallback).
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv

from .client import TalosError
from .const import (
    ATTR_CONFIG,
    ATTR_CONFIG_ENTRY_ID,
    ATTR_CONFIRM_NODE,
    ATTR_GRACEFUL,
    ATTR_MODE,
    ATTR_NODE,
    ATTR_VERSION,
    DOMAIN,
    FACTORY_INSTALLER_BASE,
    OPT_ALLOW_DESTRUCTIVE,
    OPT_ALLOW_RESET,
    SERVICE_APPLY_CONFIG,
    SERVICE_GET_SERVICE_STATUS,
    SERVICE_REBOOT_NODE,
    SERVICE_REFRESH,
    SERVICE_RESET_NODE,
    SERVICE_UPGRADE_NODE,
)

_LOGGER = logging.getLogger(__name__)

_ENTRY: dict[Any, Any] = {vol.Required(ATTR_CONFIG_ENTRY_ID): cv.string}
_NODE_READ: dict[Any, Any] = {**_ENTRY, vol.Required(ATTR_NODE): cv.string}
_NODE_WRITE: dict[Any, Any] = {**_NODE_READ, vol.Required(ATTR_CONFIRM_NODE): cv.string}

REFRESH_SCHEMA = vol.Schema(_ENTRY)
STATUS_SCHEMA = vol.Schema(_NODE_READ)
REBOOT_SCHEMA = vol.Schema(
    {
        **_NODE_WRITE,
        vol.Optional(ATTR_MODE, default="DEFAULT"): vol.In(
            ["DEFAULT", "POWERCYCLE", "FORCE"]
        ),
    }
)
UPGRADE_SCHEMA = vol.Schema({**_NODE_WRITE, vol.Optional(ATTR_VERSION): cv.string})
APPLY_SCHEMA = vol.Schema(
    {
        **_NODE_WRITE,
        vol.Required(ATTR_CONFIG): cv.string,
        vol.Optional(ATTR_MODE, default="STAGED"): vol.In(
            ["REBOOT", "AUTO", "NO_REBOOT", "STAGED", "TRY"]
        ),
    }
)
RESET_SCHEMA = vol.Schema(
    {
        **_NODE_WRITE,
        vol.Optional(ATTR_GRACEFUL, default=True): cv.boolean,
        vol.Optional(ATTR_MODE, default="SYSTEM_DISK"): vol.In(
            ["ALL", "SYSTEM_DISK", "USER_DISKS"]
        ),
    }
)


def _resolve(call: ServiceCall) -> tuple[Any, Any, Any]:
    """Return (entry, coordinator, client) for the targeted cluster."""
    entry_id = call.data[ATTR_CONFIG_ENTRY_ID]
    entry = call.hass.config_entries.async_get_entry(entry_id)
    if entry is None or entry.domain != DOMAIN:
        raise ServiceValidationError(f"Unknown Talos config entry: {entry_id}")
    if entry.state is not ConfigEntryState.LOADED:
        raise ServiceValidationError("That Talos config entry is not loaded")
    runtime = entry.runtime_data
    return entry, runtime.coordinator, runtime.client


def _target_node(call: ServiceCall, coordinator: Any, *, confirm: bool) -> str:
    node = call.data[ATTR_NODE]
    if confirm and call.data.get(ATTR_CONFIRM_NODE) != node:
        raise ServiceValidationError("confirm_node must match node exactly")
    if node not in coordinator.data.nodes:
        raise ServiceValidationError(f"Unknown node: {node}")
    return node


def _require_destructive(entry: Any, coordinator: Any) -> None:
    if not entry.options.get(OPT_ALLOW_DESTRUCTIVE):
        raise ServiceValidationError(
            "Destructive operations are disabled. Enable them in the "
            "integration options first."
        )
    if not coordinator.creds.can_write:
        raise ServiceValidationError(
            "This talosconfig role cannot perform write operations"
        )


def _require_reset(entry: Any, coordinator: Any) -> None:
    if not entry.options.get(OPT_ALLOW_RESET):
        raise ServiceValidationError(
            "Node reset is disabled. Enable it in the integration options first."
        )
    if not coordinator.creds.can_reset:
        raise ServiceValidationError("This talosconfig role cannot reset nodes")


async def _async_refresh(call: ServiceCall) -> None:
    _entry, coordinator, _client = _resolve(call)
    await coordinator.async_request_refresh()


async def _async_get_service_status(call: ServiceCall) -> ServiceResponse:
    _entry, coordinator, client = _resolve(call)
    node = _target_node(call, coordinator, confirm=False)
    try:
        services = await client.services(node)
    except TalosError as err:
        raise HomeAssistantError(f"Could not read services: {err}") from err
    return {"node": node, "services": services}


async def _async_reboot(call: ServiceCall) -> None:
    entry, coordinator, client = _resolve(call)
    _require_destructive(entry, coordinator)
    node = _target_node(call, coordinator, confirm=True)
    try:
        await client.reboot(node, mode=call.data[ATTR_MODE])
    except TalosError as err:
        raise HomeAssistantError(f"Reboot failed: {err}") from err
    await coordinator.async_request_refresh()


async def _async_upgrade(call: ServiceCall) -> None:
    entry, coordinator, client = _resolve(call)
    _require_destructive(entry, coordinator)
    node = _target_node(call, coordinator, confirm=True)
    node_data = coordinator.data.nodes[node]
    target = call.data.get(ATTR_VERSION) or coordinator.data.target_version
    if not target:
        raise ServiceValidationError("No target version given and none is known")
    if not node_data.schematic:
        raise ServiceValidationError(
            "Node schematic is unknown; cannot build the installer image"
        )
    image = f"{FACTORY_INSTALLER_BASE}/{node_data.schematic}:{target}"
    try:
        await client.upgrade(node, image, preserve=True)
    except TalosError as err:
        raise HomeAssistantError(f"Upgrade failed: {err}") from err
    await coordinator.async_request_refresh()


async def _async_apply_config(call: ServiceCall) -> None:
    entry, coordinator, client = _resolve(call)
    _require_destructive(entry, coordinator)
    node = _target_node(call, coordinator, confirm=True)
    try:
        await client.apply_configuration(
            node, call.data[ATTR_CONFIG].encode(), mode=call.data[ATTR_MODE]
        )
    except TalosError as err:
        raise HomeAssistantError(f"Apply config failed: {err}") from err
    await coordinator.async_request_refresh()


async def _async_reset(call: ServiceCall) -> None:
    entry, coordinator, client = _resolve(call)
    _require_reset(entry, coordinator)
    node = _target_node(call, coordinator, confirm=True)
    try:
        await client.reset(
            node, graceful=call.data[ATTR_GRACEFUL], mode=call.data[ATTR_MODE]
        )
    except TalosError as err:
        raise HomeAssistantError(f"Reset failed: {err}") from err
    await coordinator.async_request_refresh()


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register Talos services once for the domain."""
    if hass.services.has_service(DOMAIN, SERVICE_REFRESH):
        return
    hass.services.async_register(
        DOMAIN, SERVICE_REFRESH, _async_refresh, REFRESH_SCHEMA
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_SERVICE_STATUS,
        _async_get_service_status,
        STATUS_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN, SERVICE_REBOOT_NODE, _async_reboot, REBOOT_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_UPGRADE_NODE, _async_upgrade, UPGRADE_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_APPLY_CONFIG, _async_apply_config, APPLY_SCHEMA
    )
    hass.services.async_register(DOMAIN, SERVICE_RESET_NODE, _async_reset, RESET_SCHEMA)


@callback
def async_unload_services(hass: HomeAssistant) -> None:
    """Remove Talos services when the last entry unloads."""
    for service in (
        SERVICE_REFRESH,
        SERVICE_GET_SERVICE_STATUS,
        SERVICE_REBOOT_NODE,
        SERVICE_UPGRADE_NODE,
        SERVICE_APPLY_CONFIG,
        SERVICE_RESET_NODE,
    ):
        hass.services.async_remove(DOMAIN, service)
