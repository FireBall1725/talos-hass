"""Async gRPC client for the Talos machine API (apid) and COSI State.

Uses grpclib, not grpcio: a Talos PKI is Ed25519 by default, and grpcio's
bundled BoringSSL can't negotiate Ed25519 mTLS. grpclib does TLS through a
stdlib ``ssl.SSLContext`` (OpenSSL), which handles Ed25519, and is pure-Python
so there are no wheel/arch concerns.

apid multiplexes: a request carries the target node addresses in gRPC metadata
and the response is a repeated ``messages`` list, one per node, each tagged with
``metadata.hostname`` and an optional ``metadata.error``. This client targets
one node per call so a single unreachable node degrades on its own; the
coordinator gathers across nodes.

grpclib and the generated stubs are imported lazily so a missing dependency
raises ``TalosDependencyError`` (which the integration turns into a repair
issue) rather than blocking startup.
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import os
import ssl
import tempfile
from typing import Any

from .const import (
    COSI_NS_CLUSTER,
    COSI_NS_RUNTIME,
    NODE_METADATA_KEY,
    NODES_METADATA_KEY,
    RES_EXTENSION_STATUS_TYPE,
    RES_MACHINE_STATUS_ID,
    RES_MACHINE_STATUS_TYPE,
    RES_MEMBER_TYPE,
    SCHEMATIC_EXTENSION_NAME,
)
from .talosconfig import TalosCredentials

_LOGGER = logging.getLogger(__name__)

DEFAULT_CALL_TIMEOUT = 15.0


class TalosError(Exception):
    """Base error for the Talos client."""


class TalosDependencyError(TalosError):
    """grpclib or the generated stubs could not be imported."""


class TalosAuthError(TalosError):
    """Authentication or authorization was rejected by apid."""


class TalosConnectionError(TalosError):
    """The endpoint was unreachable, TLS failed, or the call timed out."""


class TalosNodeError(TalosError):
    """apid returned a per-node error in the response metadata."""


def _load_grpclib() -> dict[str, Any]:
    try:
        from grpclib.client import Channel  # noqa: PLC0415
        from grpclib.const import Status  # noqa: PLC0415
        from grpclib.exceptions import (  # noqa: PLC0415
            GRPCError,
            StreamTerminatedError,
        )
    except ImportError as err:  # pragma: no cover - exercised via repair flow
        raise TalosDependencyError(
            "grpclib is not available; install the integration requirements"
        ) from err
    return {
        "Channel": Channel,
        "Status": Status,
        "GRPCError": GRPCError,
        "StreamTerminatedError": StreamTerminatedError,
    }


def _load_stubs() -> dict[str, Any]:
    try:
        from google.protobuf import empty_pb2  # noqa: PLC0415

        from .proto import (  # noqa: PLC0415
            machine_grpc,
            machine_pb2,
            state_grpc,
            state_pb2,
        )
    except ImportError as err:  # pragma: no cover
        raise TalosDependencyError(
            "Talos protobuf stubs could not be imported"
        ) from err
    return {
        "empty": empty_pb2,
        "machine_pb2": machine_pb2,
        "machine_grpc": machine_grpc,
        "state_pb2": state_pb2,
        "state_grpc": state_grpc,
    }


def _build_ssl_context(creds: TalosCredentials) -> ssl.SSLContext:
    """Build a client mTLS context. Runs in an executor (does file I/O)."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_verify_locations(cadata=creds.ca_pem.decode())
    # stdlib ssl can't load a cert/key from memory, only from a path, so write
    # short-lived temp files and unlink them as soon as the context has parsed.
    crt_fd, crt_path = tempfile.mkstemp()
    key_fd, key_path = tempfile.mkstemp()
    try:
        os.write(crt_fd, creds.crt_pem)
        os.write(key_fd, creds.key_pem)
        os.close(crt_fd)
        os.close(key_fd)
        os.chmod(key_path, 0o600)
        ctx.load_cert_chain(certfile=crt_path, keyfile=key_path)
    finally:
        os.unlink(crt_path)
        os.unlink(key_path)
    # gRPC requires HTTP/2; advertise it via ALPN.
    ctx.set_alpn_protocols(["h2"])
    return ctx


def _is_ipv4(value: str) -> bool:
    try:
        return isinstance(ipaddress.ip_address(value), ipaddress.IPv4Address)
    except ValueError:
        return False


class TalosClient:
    """One mTLS channel to a single Talos endpoint, fanning out per node."""

    def __init__(self, host: str, port: int, credentials: TalosCredentials) -> None:
        self._host = host
        self._port = port
        self._creds = credentials
        self._g: dict[str, Any] = {}
        self._stubs: dict[str, Any] = {}
        self._channel: Any = None
        self._machine: Any = None
        self._state: Any = None

    async def connect(self) -> None:
        """Build the SSL context, channel, and stubs."""
        self._g = _load_grpclib()
        self._stubs = _load_stubs()
        loop = asyncio.get_running_loop()
        ctx = await loop.run_in_executor(None, _build_ssl_context, self._creds)
        self._channel = self._g["Channel"](self._host, self._port, ssl=ctx)
        self._machine = self._stubs["machine_grpc"].MachineServiceStub(self._channel)
        self._state = self._stubs["state_grpc"].StateStub(self._channel)

    async def close(self) -> None:
        if self._channel is not None:
            self._channel.close()
            self._channel = None

    # -- low-level call helpers ---------------------------------------------

    def _node_metadata(
        self, node: str | None, *, fanout: bool = True
    ) -> dict[str, str] | None:
        """Build apid routing metadata.

        MachineService accepts one-to-many fan-out (plural ``nodes``); the COSI
        State service only does one-to-one proxying and needs the singular
        ``node``. Pass ``fanout=False`` for COSI calls.
        """
        if not node:
            return None
        key = NODES_METADATA_KEY if fanout else NODE_METADATA_KEY
        return {key: node}

    def _map_grpc_error(self, err: Any) -> TalosError:
        status = getattr(err, "status", None)
        Status = self._g["Status"]
        message = getattr(err, "message", None) or str(status)
        if status in (Status.UNAUTHENTICATED, Status.PERMISSION_DENIED):
            return TalosAuthError(message)
        if status in (Status.UNAVAILABLE, Status.DEADLINE_EXCEEDED):
            return TalosConnectionError(message)
        return TalosError(f"{status}: {message}")

    async def _unary(
        self, method: Any, request: Any, node: str | None, *, fanout: bool = True
    ) -> Any:
        g = self._g
        try:
            return await method(
                request,
                timeout=DEFAULT_CALL_TIMEOUT,
                metadata=self._node_metadata(node, fanout=fanout),
            )
        except g["GRPCError"] as err:
            raise self._map_grpc_error(err) from err
        except (TimeoutError, g["StreamTerminatedError"], OSError) as err:
            raise TalosConnectionError(str(err)) from err

    async def _server_stream(
        self, method: Any, request: Any, node: str | None, *, fanout: bool = True
    ) -> list[Any]:
        g = self._g
        out: list[Any] = []
        try:
            async with method.open(
                timeout=DEFAULT_CALL_TIMEOUT,
                metadata=self._node_metadata(node, fanout=fanout),
            ) as stream:
                await stream.send_message(request, end=True)
                async for reply in stream:
                    out.append(reply)
        except g["GRPCError"] as err:
            raise self._map_grpc_error(err) from err
        except (TimeoutError, g["StreamTerminatedError"], OSError) as err:
            raise TalosConnectionError(str(err)) from err
        return out

    def _first(self, response: Any) -> Any:
        """Return the single node message, raising on a per-node error."""
        messages = list(response.messages)
        if not messages:
            raise TalosError("apid returned no messages")
        msg = messages[0]
        if msg.metadata.error:
            raise TalosNodeError(msg.metadata.error)
        return msg

    def _empty(self) -> Any:
        return self._stubs["empty"].Empty()

    # -- reads (one node per call) ------------------------------------------

    async def version(self, node: str) -> dict[str, Any]:
        msg = self._first(await self._unary(self._machine.Version, self._empty(), node))
        vi = msg.version
        return {
            "hostname": msg.metadata.hostname,
            "tag": vi.tag,
            "sha": vi.sha,
            "os": vi.os,
            "arch": vi.arch,
            "platform": msg.platform.name,
            "platform_mode": msg.platform.mode,
        }

    async def memory(self, node: str) -> dict[str, int]:
        msg = self._first(await self._unary(self._machine.Memory, self._empty(), node))
        mi = msg.meminfo
        return {"total": mi.memtotal, "available": mi.memavailable, "free": mi.memfree}

    async def cpu_times(self, node: str) -> dict[str, float]:
        """Cumulative CPU jiffies; the coordinator deltas these into a percent."""
        msg = self._first(
            await self._unary(self._machine.SystemStat, self._empty(), node)
        )
        c = msg.cpu_total
        total = (
            c.user
            + c.nice
            + c.system
            + c.idle
            + c.iowait
            + c.irq
            + c.soft_irq
            + c.steal
        )
        return {"total": total, "idle": c.idle + c.iowait, "boot_time": msg.boot_time}

    async def mounts(self, node: str) -> list[dict[str, Any]]:
        msg = self._first(await self._unary(self._machine.Mounts, self._empty(), node))
        return [
            {
                "filesystem": s.filesystem,
                "mounted_on": s.mounted_on,
                "size": s.size,
                "available": s.available,
            }
            for s in msg.stats
        ]

    async def services(self, node: str) -> list[dict[str, Any]]:
        msg = self._first(
            await self._unary(self._machine.ServiceList, self._empty(), node)
        )
        return [
            {
                "id": s.id,
                "state": s.state,
                "healthy": s.health.healthy,
                "unknown": s.health.unknown,
            }
            for s in msg.services
        ]

    async def etcd_members(self, node: str) -> list[dict[str, Any]]:
        request = self._stubs["machine_pb2"].EtcdMemberListRequest()
        resp = await self._unary(self._machine.EtcdMemberList, request, node)
        msg = self._first(resp)
        return [
            {"id": m.id, "hostname": m.hostname, "is_learner": m.is_learner}
            for m in msg.members
        ]

    # -- COSI resource reads -------------------------------------------------

    async def get_resource(
        self, node: str, resource_type: str, resource_id: str, namespace: str
    ) -> dict[str, Any]:
        """Get one COSI resource. Talos populates yaml_spec (parsed to a dict)."""
        request = self._stubs["state_pb2"].GetRequest(
            namespace=namespace, type=resource_type, id=resource_id
        )
        resp = await self._unary(self._state.Get, request, node, fanout=False)
        return self._decode_resource(resp.resource)

    async def list_resources(
        self, node: str, resource_type: str, namespace: str
    ) -> list[dict[str, Any]]:
        request = self._stubs["state_pb2"].ListRequest(
            namespace=namespace, type=resource_type
        )
        replies = await self._server_stream(
            self._state.List, request, node, fanout=False
        )
        return [self._decode_resource(r.resource) for r in replies]

    def _decode_resource(self, resource: Any) -> dict[str, Any]:
        spec: Any = resource.spec.yaml_spec or resource.spec.proto_spec
        if isinstance(spec, str) and spec:
            try:
                import yaml  # noqa: PLC0415

                spec = yaml.safe_load(spec)
            except Exception:  # noqa: BLE001 - keep raw on any parse issue
                pass
        return {
            "id": resource.metadata.id,
            "type": resource.metadata.type,
            "namespace": resource.metadata.namespace,
            "version": resource.metadata.version,
            "spec": spec,
        }

    async def machine_status(self, node: str) -> dict[str, Any]:
        res = await self.get_resource(
            node, RES_MACHINE_STATUS_TYPE, RES_MACHINE_STATUS_ID, COSI_NS_RUNTIME
        )
        spec = res.get("spec") or {}
        status = spec.get("status") or {}
        return {
            "stage": spec.get("stage"),
            "ready": bool(status.get("ready")),
            "unmet_conditions": status.get("unmetConditions") or [],
        }

    async def extensions(self, node: str) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for res in await self.list_resources(
            node, RES_EXTENSION_STATUS_TYPE, COSI_NS_RUNTIME
        ):
            meta = (res.get("spec") or {}).get("metadata") or {}
            out.append(
                {
                    "id": res["id"],
                    "name": meta.get("name"),
                    "version": meta.get("version"),
                }
            )
        return out

    async def schematic_id(self, node: str) -> str | None:
        """The Image Factory schematic is the extension named 'schematic'."""
        for ext in await self.extensions(node):
            if ext["name"] == SCHEMATIC_EXTENSION_NAME:
                return ext["version"]
        return None

    async def discover_nodes(self, endpoint: str) -> list[dict[str, Any]]:
        """List cluster members from a control-plane endpoint.

        A node that holds a shared control-plane VIP reports both the VIP and
        its real IP in spec.addresses, and within the Members resource the VIP
        cannot be told apart from a real IP (no flag, no prefix). We pick the
        real IP by preferring an address that is a known node address: a
        talosconfig endpoint, or the endpoint we connected to. The VIP is none
        of those. The display name is the member id (e.g. talos-cp-01). The
        coordinator falls back to the configured endpoints if this is empty.
        """
        known = set(self._creds.endpoints)
        known.add(endpoint)
        nodes: list[dict[str, Any]] = []
        for res in await self.list_resources(
            endpoint, RES_MEMBER_TYPE, COSI_NS_CLUSTER
        ):
            spec = res.get("spec") or {}
            ipv4s = [a for a in (spec.get("addresses") or []) if _is_ipv4(a)]
            if not ipv4s:
                continue
            preferred = [a for a in ipv4s if a in known]
            address = preferred[0] if preferred else ipv4s[0]
            nodes.append(
                {
                    "address": address,
                    "hostname": res.get("id") or spec.get("hostname"),
                    "type": spec.get("machineType") or spec.get("machine_type"),
                }
            )
        return nodes

    # -- writes --------------------------------------------------------------

    async def upgrade(
        self, node: str, image: str, *, preserve: bool = True, stage: bool = False
    ) -> None:
        request = self._stubs["machine_pb2"].UpgradeRequest(
            image=image, preserve=preserve, stage=stage
        )
        await self._unary(self._machine.Upgrade, request, node)

    async def reboot(self, node: str, *, mode: str = "DEFAULT") -> None:
        machine = self._stubs["machine_pb2"]
        request = machine.RebootRequest(mode=getattr(machine.RebootRequest, mode))
        await self._unary(self._machine.Reboot, request, node)

    async def shutdown(self, node: str) -> None:
        request = self._stubs["machine_pb2"].ShutdownRequest()
        await self._unary(self._machine.Shutdown, request, node)

    async def reset(
        self,
        node: str,
        *,
        graceful: bool = True,
        reboot: bool = True,
        mode: str = "SYSTEM_DISK",
    ) -> None:
        machine = self._stubs["machine_pb2"]
        request = machine.ResetRequest(
            graceful=graceful, reboot=reboot, mode=getattr(machine.ResetRequest, mode)
        )
        await self._unary(self._machine.Reset, request, node)

    async def apply_configuration(
        self, node: str, data: bytes, *, mode: str = "STAGED", dry_run: bool = False
    ) -> None:
        machine = self._stubs["machine_pb2"]
        request = machine.ApplyConfigurationRequest(
            data=data,
            mode=getattr(machine.ApplyConfigurationRequest, mode),
            dry_run=dry_run,
        )
        await self._unary(self._machine.ApplyConfiguration, request, node)
