"""Update platform for Talos Linux.

One update entity per node. The latest version comes from the coordinator's
GitHub check (or a pinned target). Install builds the node's exact Image
Factory installer from its schematic, so the upgrade preserves that node's
system extensions instead of stripping them.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.update import (
    UpdateDeviceClass,
    UpdateEntity,
    UpdateEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import TalosConfigEntry
from .const import (
    FACTORY_INSTALLER_BASE,
    GITHUB_RELEASE_TAG_URL,
    OPT_ALLOW_DESTRUCTIVE,
    STAGE_UPGRADING,
)
from .entity import TalosNodeEntity, register_node_entities


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TalosConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Talos update entities."""
    coordinator = entry.runtime_data.coordinator
    register_node_entities(
        entry,
        coordinator,
        async_add_entities,
        lambda address: [TalosUpdateEntity(coordinator, entry, address)],
    )


class TalosUpdateEntity(TalosNodeEntity, UpdateEntity):
    """Talos OS version + schematic-aware upgrade for one node."""

    _attr_name = "Talos OS"
    _attr_device_class = UpdateDeviceClass.FIRMWARE

    def __init__(self, coordinator, entry, address) -> None:
        super().__init__(coordinator, entry, address, "os_update")
        if self._install_allowed():
            self._attr_supported_features = UpdateEntityFeature.INSTALL

    def _install_allowed(self) -> bool:
        return bool(
            self._entry.options.get(OPT_ALLOW_DESTRUCTIVE)
            and self.coordinator.creds.can_write
        )

    @property
    def installed_version(self) -> str | None:
        node = self._node
        return node.version if node else None

    @property
    def latest_version(self) -> str | None:
        return self.coordinator.data.target_version or self.installed_version

    @property
    def release_url(self) -> str | None:
        target = self.coordinator.data.target_version
        return GITHUB_RELEASE_TAG_URL.format(tag=target) if target else None

    @property
    def in_progress(self) -> bool:
        node = self._node
        return bool(node and node.stage == STAGE_UPGRADING)

    async def async_install(
        self, version: str | None, backup: bool, **kwargs: Any
    ) -> None:
        node = self._node
        if node is None:
            raise HomeAssistantError("Node is not available")
        if not self._install_allowed():
            raise HomeAssistantError(
                "Destructive operations are disabled, or the talosconfig role "
                "cannot perform upgrades"
            )
        target = version or self.coordinator.data.target_version
        if not target:
            raise HomeAssistantError("No target Talos version is known")
        if not node.schematic:
            raise HomeAssistantError(
                "Node schematic is unknown; cannot build the installer image"
            )
        image = f"{FACTORY_INSTALLER_BASE}/{node.schematic}:{target}"
        await self.coordinator.client.upgrade(self._address, image, preserve=True)
        await self.coordinator.async_request_refresh()
