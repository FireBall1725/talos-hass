"""Binary sensor platform for Talos Linux."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import TalosConfigEntry
from .coordinator import NodeData
from .entity import TalosNodeEntity, register_node_entities


@dataclass(frozen=True, kw_only=True)
class TalosBinarySensorDescription(BinarySensorEntityDescription):
    """A node binary sensor with a value function over NodeData."""

    value_fn: Callable[[NodeData], bool | None]


NODE_BINARY_SENSORS: tuple[TalosBinarySensorDescription, ...] = (
    TalosBinarySensorDescription(
        key="online",
        name="Reachable",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        value_fn=lambda n: n.online,
    ),
    TalosBinarySensorDescription(
        key="ready",
        name="Ready",
        device_class=BinarySensorDeviceClass.RUNNING,
        value_fn=lambda n: n.ready,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TalosConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Talos binary sensors."""
    coordinator = entry.runtime_data.coordinator
    register_node_entities(
        entry,
        coordinator,
        async_add_entities,
        lambda address: [
            TalosBinarySensor(coordinator, entry, address, desc)
            for desc in NODE_BINARY_SENSORS
        ],
    )


class TalosBinarySensor(TalosNodeEntity, BinarySensorEntity):
    """A per-node binary sensor."""

    entity_description: TalosBinarySensorDescription

    def __init__(self, coordinator, entry, address, description) -> None:
        super().__init__(coordinator, entry, address, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        node = self._node
        if node is None:
            return None
        return self.entity_description.value_fn(node)
