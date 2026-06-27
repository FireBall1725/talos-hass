"""Shared base entities and dynamic node-entity registration."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import NodeData, TalosCoordinator

if TYPE_CHECKING:
    from . import TalosConfigEntry

MANUFACTURER = "Sidero Labs"


class TalosNodeEntity(CoordinatorEntity[TalosCoordinator]):
    """Base entity tied to one Talos node."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: TalosCoordinator,
        entry: TalosConfigEntry,
        address: str,
        key: str,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._address = address
        self._attr_unique_id = f"{entry.entry_id}_{address}_{key}"

    @property
    def _node(self) -> NodeData | None:
        return self.coordinator.data.nodes.get(self._address)

    @property
    def available(self) -> bool:
        return super().available and self._node is not None

    @property
    def device_info(self) -> DeviceInfo:
        node = self._node
        name = node.hostname if node and node.hostname else self._address
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self._entry.entry_id}_{self._address}")},
            name=name,
            manufacturer=MANUFACTURER,
            model="Talos node",
            sw_version=node.version if node else None,
            via_device=(DOMAIN, self._entry.entry_id),
        )


class TalosClusterEntity(CoordinatorEntity[TalosCoordinator]):
    """Base entity for cluster-wide values."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: TalosCoordinator, entry: TalosConfigEntry, key: str
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_cluster_{key}"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name="Talos cluster",
            manufacturer=MANUFACTURER,
            model="Talos Linux cluster",
        )


@callback
def register_node_entities(
    entry: TalosConfigEntry,
    coordinator: TalosCoordinator,
    async_add_entities: AddConfigEntryEntitiesCallback,
    builder: Callable[[str], list[Entity]],
) -> None:
    """Add entities for current nodes and for any that appear later."""
    known: set[str] = set()

    @callback
    def _discover() -> None:
        new: list[Entity] = []
        for address in coordinator.data.nodes:
            if address not in known:
                known.add(address)
                new.extend(builder(address))
        if new:
            async_add_entities(new)

    _discover()
    entry.async_on_unload(coordinator.async_add_listener(_discover))
