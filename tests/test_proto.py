"""Import the vendored gRPC stubs under the real protobuf runtime.

The rest of the suite mocks TalosClient, so the generated stubs are never
imported through it. That hid a protobuf gencode/runtime mismatch: the stubs
were stamped with a gencode newer than the protobuf Home Assistant ships, so
they raised VersionError on a real instance. Importing them here (at module
load) runs the runtime-version check under the protobuf that
pytest-homeassistant-custom-component installs alongside Home Assistant; a
mismatch fails collection of this module.
"""

from __future__ import annotations

from custom_components.talos_linux.proto import (
    common_pb2,
    machine_grpc,
    machine_pb2,
    resource_pb2,
    state_grpc,
    state_pb2,
)


def test_proto_stubs_import() -> None:
    assert machine_grpc.MachineServiceStub is not None
    assert state_grpc.StateStub is not None
    assert machine_pb2.UpgradeRequest is not None
    assert state_pb2.GetRequest is not None
    assert resource_pb2 is not None
    assert common_pb2 is not None
