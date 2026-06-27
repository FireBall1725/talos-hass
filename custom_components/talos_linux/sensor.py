"""Sensor platform for Talos Linux."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.util import dt as dt_util

from . import TalosConfigEntry
from .const import (
    STAGE_BOOTING,
    STAGE_INSTALLING,
    STAGE_MAINTENANCE,
    STAGE_REBOOTING,
    STAGE_RESETTING,
    STAGE_RUNNING,
    STAGE_SHUTTING_DOWN,
    STAGE_UPGRADING,
)
from .coordinator import NodeData, TalosData
from .entity import TalosClusterEntity, TalosNodeEntity, register_node_entities

STAGES = [
    STAGE_BOOTING,
    STAGE_INSTALLING,
    STAGE_MAINTENANCE,
    STAGE_RUNNING,
    STAGE_REBOOTING,
    STAGE_SHUTTING_DOWN,
    STAGE_RESETTING,
    STAGE_UPGRADING,
]


def _uptime(node: NodeData) -> datetime | None:
    if not node.boot_time:
        return None
    return dt_util.utc_from_timestamp(node.boot_time)


@dataclass(frozen=True, kw_only=True)
class TalosNodeSensorDescription(SensorEntityDescription):
    """A node sensor with a value function over NodeData."""

    value_fn: Callable[[NodeData], StateType | datetime]


@dataclass(frozen=True, kw_only=True)
class TalosClusterSensorDescription(SensorEntityDescription):
    """A cluster sensor with a value function over TalosData."""

    value_fn: Callable[[TalosData], StateType]


NODE_SENSORS: tuple[TalosNodeSensorDescription, ...] = (
    TalosNodeSensorDescription(
        key="version",
        name="Talos version",
        value_fn=lambda n: n.version,
    ),
    TalosNodeSensorDescription(
        key="stage",
        name="Machine stage",
        device_class=SensorDeviceClass.ENUM,
        options=STAGES,
        value_fn=lambda n: n.stage,
    ),
    TalosNodeSensorDescription(
        key="cpu",
        name="CPU usage",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda n: n.cpu_pct,
    ),
    TalosNodeSensorDescription(
        key="memory",
        name="Memory usage",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda n: n.memory_used_pct,
    ),
    TalosNodeSensorDescription(
        key="disk",
        name="System disk usage",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda n: n.disk_used_pct,
    ),
    TalosNodeSensorDescription(
        key="uptime",
        name="Last boot",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=_uptime,
    ),
    TalosNodeSensorDescription(
        key="schematic",
        name="Schematic ID",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda n: n.schematic,
    ),
    TalosNodeSensorDescription(
        key="extension_count",
        name="Extensions",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda n: len(n.extensions),
    ),
    TalosNodeSensorDescription(
        key="arch",
        name="Architecture",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda n: n.arch,
    ),
    TalosNodeSensorDescription(
        key="platform",
        name="Platform",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda n: n.platform,
    ),
)


def _controlplane_count(data: TalosData) -> int:
    return sum(
        1 for n in data.nodes.values() if n.etcd_members or n.role in ("controlplane",)
    )


CLUSTER_SENSORS: tuple[TalosClusterSensorDescription, ...] = (
    TalosClusterSensorDescription(
        key="node_count",
        name="Nodes",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: len(d.nodes),
    ),
    TalosClusterSensorDescription(
        key="controlplane_count",
        name="Control-plane nodes",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_controlplane_count,
    ),
    TalosClusterSensorDescription(
        key="version_spread",
        name="Talos version spread",
        value_fn=lambda d: len({n.version for n in d.nodes.values() if n.version}),
    ),
    TalosClusterSensorDescription(
        key="latest_version",
        name="Latest Talos release",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.latest_version,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TalosConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Talos sensors."""
    coordinator = entry.runtime_data.coordinator

    register_node_entities(
        entry,
        coordinator,
        async_add_entities,
        lambda address: [
            TalosNodeSensor(coordinator, entry, address, desc) for desc in NODE_SENSORS
        ],
    )
    async_add_entities(
        TalosClusterSensor(coordinator, entry, desc) for desc in CLUSTER_SENSORS
    )


class TalosNodeSensor(TalosNodeEntity, SensorEntity):
    """A per-node sensor."""

    entity_description: TalosNodeSensorDescription

    def __init__(self, coordinator, entry, address, description) -> None:
        super().__init__(coordinator, entry, address, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> StateType | datetime:
        node = self._node
        if node is None:
            return None
        return self.entity_description.value_fn(node)


class TalosClusterSensor(TalosClusterEntity, SensorEntity):
    """A cluster-wide sensor."""

    entity_description: TalosClusterSensorDescription

    def __init__(self, coordinator, entry, description) -> None:
        super().__init__(coordinator, entry, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> StateType:
        return self.entity_description.value_fn(self.coordinator.data)
