"""Sensor platform for Talos Linux."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.util import dt as dt_util
from homeassistant.util import slugify

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

    value_fn: Callable[[TalosData], StateType | datetime]


NODE_SENSORS: tuple[TalosNodeSensorDescription, ...] = (
    TalosNodeSensorDescription(
        key="version",
        translation_key="version",
        value_fn=lambda n: n.version,
    ),
    TalosNodeSensorDescription(
        key="stage",
        translation_key="stage",
        device_class=SensorDeviceClass.ENUM,
        options=STAGES,
        value_fn=lambda n: n.stage,
    ),
    TalosNodeSensorDescription(
        key="cpu",
        translation_key="cpu",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda n: n.cpu_pct,
    ),
    TalosNodeSensorDescription(
        key="memory",
        translation_key="memory",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda n: n.memory_used_pct,
    ),
    TalosNodeSensorDescription(
        key="disk",
        translation_key="disk",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda n: n.disk_used_pct,
    ),
    TalosNodeSensorDescription(
        key="uptime",
        translation_key="uptime",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=_uptime,
    ),
    TalosNodeSensorDescription(
        key="schematic",
        translation_key="schematic",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda n: n.schematic,
    ),
    TalosNodeSensorDescription(
        key="extension_count",
        translation_key="extension_count",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda n: len(n.extensions),
    ),
    TalosNodeSensorDescription(
        key="arch",
        translation_key="arch",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda n: n.arch,
    ),
    TalosNodeSensorDescription(
        key="platform",
        translation_key="platform",
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
        translation_key="node_count",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: len(d.nodes),
    ),
    TalosClusterSensorDescription(
        key="controlplane_count",
        translation_key="controlplane_count",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_controlplane_count,
    ),
    TalosClusterSensorDescription(
        key="version_spread",
        translation_key="version_spread",
        value_fn=lambda d: len({n.version for n in d.nodes.values() if n.version}),
    ),
    TalosClusterSensorDescription(
        key="latest_version",
        translation_key="latest_version",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.latest_version,
    ),
    TalosClusterSensorDescription(
        key="cert_expires",
        translation_key="cert_expires",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.cert_expires,
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
    _register_volume_sensors(entry, coordinator, async_add_entities)


@callback
def _register_volume_sensors(
    entry: TalosConfigEntry,
    coordinator,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add one disk sensor per Talos user/data volume, as volumes appear.

    Keyed on (node, mount point); a volume that later goes away leaves its
    entity in place (reporting unavailable) rather than being re-created.
    """
    known: set[tuple[str, str]] = set()

    @callback
    def _discover() -> None:
        new: list[Entity] = []
        for address, node in coordinator.data.nodes.items():
            for vol in node.volumes:
                key = (address, vol["mounted_on"])
                if key not in known:
                    known.add(key)
                    new.append(
                        TalosVolumeSensor(
                            coordinator, entry, address, vol["mounted_on"]
                        )
                    )
        if new:
            async_add_entities(new)

    _discover()
    entry.async_on_unload(coordinator.async_add_listener(_discover))


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
    def native_value(self) -> StateType | datetime:
        return self.entity_description.value_fn(self.coordinator.data)


class TalosVolumeSensor(TalosNodeEntity, SensorEntity):
    """Usage of one Talos user/data volume (a /var/mnt mount)."""

    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 1
    _attr_icon = "mdi:harddisk"

    def __init__(self, coordinator, entry, address, mounted_on: str) -> None:
        super().__init__(coordinator, entry, address, f"volume_{slugify(mounted_on)}")
        self._mounted_on = mounted_on
        self._attr_name = f"Disk {mounted_on}"

    def _volume(self) -> dict[str, Any] | None:
        node = self._node
        if node is None:
            return None
        return next(
            (v for v in node.volumes if v["mounted_on"] == self._mounted_on), None
        )

    @property
    def native_value(self) -> StateType:
        vol = self._volume()
        return vol["used_pct"] if vol else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        vol = self._volume()
        if vol is None:
            return None
        return {
            "mounted_on": vol["mounted_on"],
            "filesystem": vol["filesystem"],
            "size_bytes": vol["size"],
            "available_bytes": vol["available"],
        }
