"""DataUpdateCoordinator for Talos Linux.

One coordinator per config entry (per cluster). Each cycle discovers the node
set, then polls every node concurrently with ``asyncio.gather`` so a single
unreachable node degrades on its own instead of failing the whole refresh. The
GitHub "latest release" check runs on a slower cadence than the node poll.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, cast

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .client import TalosAuthError, TalosClient, TalosError
from .const import (
    DEFAULT_STATE_INTERVAL,
    DEFAULT_UPGRADE_INTERVAL,
    DOMAIN,
    GITHUB_RELEASES_URL,
    OPT_PINNED_VERSION,
    OPT_STATE_INTERVAL,
    OPT_UPGRADE_INTERVAL,
    OPT_UPGRADE_MODE,
    SYSTEM_DISK_MOUNT,
    UPGRADE_MODE_PINNED,
)
from .talosconfig import TalosCredentials

_LOGGER = logging.getLogger(__name__)

CONTROL_PLANE_TYPES = {"controlplane", "control-plane", "ControlPlane"}


@dataclass
class NodeData:
    """One node's state for a single refresh."""

    address: str
    online: bool = False
    error: str | None = None
    hostname: str | None = None
    role: str | None = None
    version: str | None = None
    arch: str | None = None
    platform: str | None = None
    memory_used_pct: float | None = None
    memory_total: int | None = None
    cpu_pct: float | None = None
    disk_used_pct: float | None = None
    boot_time: int | None = None
    stage: str | None = None
    ready: bool | None = None
    schematic: str | None = None
    extensions: list[dict[str, Any]] = field(default_factory=list)
    services: list[dict[str, Any]] = field(default_factory=list)
    etcd_members: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class TalosData:
    """The whole coordinator payload."""

    nodes: dict[str, NodeData]
    latest_version: str | None = None
    target_version: str | None = None


def _interval(entry: ConfigEntry, key: str, default: timedelta) -> timedelta:
    value = entry.options.get(key)
    return timedelta(seconds=value) if value else default


class TalosCoordinator(DataUpdateCoordinator[TalosData]):
    """Polls every node in a Talos cluster on a shared cadence."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: TalosClient,
        credentials: TalosCredentials,
        endpoint: str,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=_interval(
                entry, OPT_STATE_INTERVAL, DEFAULT_STATE_INTERVAL
            ),
        )
        self.client = client
        self.creds = credentials
        self.entry = entry
        self._endpoint = endpoint
        self._cpu_prev: dict[str, tuple[float, float]] = {}
        self._latest_version: str | None = None
        self._latest_checked: datetime | None = None
        # True only when the last node list came from cluster discovery (not the
        # endpoint fallback). Stale-device pruning is gated on this so a transient
        # discovery failure can't remove healthy worker devices.
        self._discovery_complete = False

    async def _async_update_data(self) -> TalosData:
        nodes = await self._discover_nodes()
        results = await asyncio.gather(
            *(self._poll_node(node) for node in nodes), return_exceptions=True
        )
        node_map: dict[str, NodeData] = {}
        for node, result in zip(nodes, results, strict=True):
            address = node["address"]
            if isinstance(result, TalosAuthError):
                # A cert/role problem is cluster-wide; prompt re-auth.
                raise ConfigEntryAuthFailed(str(result)) from result
            if isinstance(result, BaseException):
                node_map[address] = NodeData(
                    address=address,
                    online=False,
                    error=str(result),
                    hostname=node.get("hostname"),
                    role=node.get("type"),
                )
            else:
                node_map[address] = result

        if not node_map:
            raise UpdateFailed("no Talos nodes could be reached")

        if self._discovery_complete:
            self._prune_stale_devices(set(node_map))

        latest = await self._maybe_check_latest()
        return TalosData(
            nodes=node_map,
            latest_version=latest,
            target_version=self._target_version(latest),
        )

    async def _discover_nodes(self) -> list[dict[str, Any]]:
        """Discover the node set, falling back to configured endpoints."""
        try:
            nodes = await self.client.discover_nodes(self._endpoint)
        except TalosError as err:
            _LOGGER.debug("node discovery failed, using endpoints: %s", err)
            nodes = []
        if nodes:
            self._discovery_complete = True
            return nodes
        self._discovery_complete = False
        endpoints = self.creds.endpoints or [self._endpoint]
        return [{"address": ep, "hostname": None, "type": None} for ep in endpoints]

    def _prune_stale_devices(self, keep: set[str]) -> None:
        """Remove node devices whose node is no longer in the cluster.

        Only per-node devices are considered; the cluster device (its identifier
        is the bare entry id, with no address suffix) is left alone.
        """
        registry = dr.async_get(self.hass)
        prefix = f"{self.entry.entry_id}_"
        for device in dr.async_entries_for_config_entry(registry, self.entry.entry_id):
            for domain, ident in device.identifiers:
                if domain != DOMAIN or not ident.startswith(prefix):
                    continue
                address = ident[len(prefix) :]
                if address and address not in keep:
                    _LOGGER.debug("removing stale Talos node device %s", address)
                    registry.async_update_device(
                        device.id, remove_config_entry_id=self.entry.entry_id
                    )
                break

    async def _poll_node(self, node: dict[str, Any]) -> NodeData:
        address = node["address"]
        data = NodeData(
            address=address, hostname=node.get("hostname"), role=node.get("type")
        )

        # Version establishes reachability; let auth/connection errors propagate.
        version = await self.client.version(address)
        data.version = version["tag"]
        data.arch = version["arch"]
        data.platform = version["platform"]
        # Prefer the discovery name (talos-cp-01); under apid fan-out the
        # Version reply's hostname is the targeted IP, not the node name.
        data.hostname = data.hostname or version.get("hostname")
        data.online = True

        memory, cpu, mounts, status, extensions, services, etcd = cast(
            "tuple[Any, Any, Any, Any, Any, Any, Any]",
            await asyncio.gather(
                self.client.memory(address),
                self.client.cpu_times(address),
                self.client.mounts(address),
                self.client.machine_status(address),
                self.client.extensions(address),
                self.client.services(address),
                self.client.etcd_members(address),
                return_exceptions=True,
            ),
        )

        if not isinstance(memory, Exception) and memory["total"]:
            data.memory_total = memory["total"]
            used = memory["total"] - memory["available"]
            data.memory_used_pct = round(used / memory["total"] * 100, 1)

        if not isinstance(cpu, Exception):
            data.boot_time = cpu["boot_time"]
            data.cpu_pct = self._cpu_percent(address, cpu)

        if not isinstance(mounts, Exception):
            data.disk_used_pct = self._disk_percent(mounts)

        if not isinstance(status, Exception):
            data.stage = status["stage"]
            data.ready = status["ready"]

        if not isinstance(extensions, Exception):
            data.extensions = extensions
            data.schematic = next(
                (e["version"] for e in extensions if e["name"] == "schematic"), None
            )

        if not isinstance(services, Exception):
            data.services = services

        if not isinstance(etcd, Exception):
            data.etcd_members = etcd

        return data

    def _cpu_percent(self, address: str, cpu: dict[str, float]) -> float | None:
        prev = self._cpu_prev.get(address)
        self._cpu_prev[address] = (cpu["total"], cpu["idle"])
        if prev is None:
            return None
        total_delta = cpu["total"] - prev[0]
        idle_delta = cpu["idle"] - prev[1]
        if total_delta <= 0:
            return None
        return round((1 - idle_delta / total_delta) * 100, 1)

    def _disk_percent(self, mounts: list[dict[str, Any]]) -> float | None:
        for mount in mounts:
            if mount["mounted_on"] == SYSTEM_DISK_MOUNT and mount["size"]:
                used = mount["size"] - mount["available"]
                return round(used / mount["size"] * 100, 1)
        return None

    async def _maybe_check_latest(self) -> str | None:
        """Fetch the latest Talos release, throttled to the upgrade interval."""
        interval = _interval(self.entry, OPT_UPGRADE_INTERVAL, DEFAULT_UPGRADE_INTERVAL)
        now = dt_util.utcnow()
        if (
            self._latest_version is not None
            and self._latest_checked is not None
            and now - self._latest_checked < interval
        ):
            return self._latest_version

        session = async_get_clientsession(self.hass)
        try:
            timeout = aiohttp.ClientTimeout(total=20)
            async with session.get(GITHUB_RELEASES_URL, timeout=timeout) as resp:
                resp.raise_for_status()
                payload = await resp.json()
            self._latest_version = payload.get("tag_name")
            self._latest_checked = now
        except Exception as err:  # noqa: BLE001 - non-fatal; keep last value
            _LOGGER.debug("latest-release check failed: %s", err)
        return self._latest_version

    def _target_version(self, latest: str | None) -> str | None:
        if self.entry.options.get(OPT_UPGRADE_MODE) == UPGRADE_MODE_PINNED:
            return self.entry.options.get(OPT_PINNED_VERSION) or latest
        return latest

    def is_control_plane(self, data: NodeData) -> bool:
        if data.role and data.role in CONTROL_PLANE_TYPES:
            return True
        return bool(data.etcd_members)
