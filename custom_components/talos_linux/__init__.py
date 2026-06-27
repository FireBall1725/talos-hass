"""The Talos Linux integration."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError
from homeassistant.helpers.device_registry import DeviceEntry

from .client import TalosClient, TalosDependencyError
from .const import CONF_ENDPOINT, CONF_PORT, CONF_TALOSCONFIG, DOMAIN
from .coordinator import TalosCoordinator
from .panel import async_register_panel, async_unregister_panel
from .services import async_setup_services, async_unload_services
from .talosconfig import TalosConfigError, parse_talosconfig

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.UPDATE,
]


@dataclass
class TalosRuntimeData:
    """Per-entry runtime objects."""

    client: TalosClient
    coordinator: TalosCoordinator


type TalosConfigEntry = ConfigEntry[TalosRuntimeData]


async def async_setup_entry(hass: HomeAssistant, entry: TalosConfigEntry) -> bool:
    """Set up Talos Linux from a config entry."""
    try:
        creds = parse_talosconfig(entry.data[CONF_TALOSCONFIG])
    except TalosConfigError as err:
        raise ConfigEntryError(f"Invalid talosconfig: {err}") from err

    endpoint = entry.data[CONF_ENDPOINT]
    client = TalosClient(endpoint, entry.data[CONF_PORT], creds)
    try:
        await client.connect()
    except TalosDependencyError as err:
        raise ConfigEntryError(str(err)) from err

    coordinator = TalosCoordinator(hass, entry, client, creds, endpoint)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = TalosRuntimeData(client=client, coordinator=coordinator)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    async_setup_services(hass)
    await async_register_panel(hass)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: TalosConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.client.close()
        others = [
            e
            for e in hass.config_entries.async_entries(DOMAIN)
            if e.entry_id != entry.entry_id and e.state is ConfigEntryState.LOADED
        ]
        if not others:
            async_unload_services(hass)
            async_unregister_panel(hass)
    return unloaded


async def _async_reload(hass: HomeAssistant, entry: TalosConfigEntry) -> None:
    """Reload when options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: TalosConfigEntry, device: DeviceEntry
) -> bool:
    """Allow deleting a device whose Talos node is no longer in the cluster."""
    coordinator = entry.runtime_data.coordinator
    prefix = f"{entry.entry_id}_"
    for domain, identifier in device.identifiers:
        if domain != DOMAIN:
            continue
        if identifier == entry.entry_id:
            return False  # the cluster device stays
        if identifier.startswith(prefix):
            return identifier[len(prefix) :] not in coordinator.data.nodes
    return True
