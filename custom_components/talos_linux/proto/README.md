# Generated protobuf and gRPC stubs

These files are generated. Do not hand-edit them. To regenerate, run
`scripts/generate_proto.sh` from the repo root.

The message stubs (`*_pb2.py`) are standard protobuf, built by `protoc
--python_out`. The service stubs (`*_grpc.py`) are grpclib, built by grpclib's
`protoc-gen-python_grpc` plugin via `protoc --python_grpc_out`. grpcio is not
used: its bundled BoringSSL can't do Ed25519 client certificates, and Talos
issues an Ed25519 PKI, so Ed25519 mTLS is required. grpclib runs on Python's
own `ssl` module, which handles Ed25519.

## Source

| Stub | Kind | Proto source | Repo @ tag |
|---|---|---|---|
| `common_pb2` | message (protobuf) | `api/common/common.proto` | siderolabs/talos @ v1.13.5 |
| `machine_pb2`, `machine_grpc` | message + service (grpclib) | `api/machine/machine.proto` (`MachineService`) | siderolabs/talos @ v1.13.5 |
| `resource_pb2` | message (protobuf) | `v1alpha1/resource.proto` | cosi-project/runtime @ v1.14.1 |
| `state_pb2`, `state_grpc` | message + service (grpclib) | `v1alpha1/state.proto` (`cosi.resource.State`) | cosi-project/runtime @ v1.14.1 |

Only `machine.proto` and `state.proto` declare a service, so only those produce
a `*_grpc.py`. `common.proto` and `resource.proto` are message-only; grpclib
emits empty `*_grpc.py` files for them, which the regen script drops.

The cosi-project/runtime version is read from the Talos tag's `go.mod`, so it
tracks whatever that Talos release pins.

The cosi runtime repo no longer ships the `state.proto` / `resource.proto`
sources at this tag, only generated Go. The regen script reconstructs a
`FileDescriptorSet` from the `FileDescriptorProto` bytes embedded in those
`.pb.go` files and feeds it to `protoc --descriptor_set_in`.

## Layout and imports

The stubs are flattened into this one package. Both code generators emit
imports rooted at each proto's package dir: protobuf writes `from machine import
machine_pb2`, grpclib writes `import machine.machine_pb2`. The regen script
rewrites both shapes to package-relative (`from . import machine_pb2`) so the
package imports from anywhere on `sys.path`. The grpclib stub `__init__`
constructors take a `grpclib.client.Channel` (`MachineServiceStub(channel)`,
`StateStub(channel)`).

## Runtime dependencies

`common.proto` imports `google/rpc/status.proto`, so `common_pb2` does
`from google.rpc import status_pb2`. Provide it at runtime via the
`googleapis-common-protos` package. The `google.protobuf.*` types come from
`protobuf`. Neither set of google types is vendored here. The service stubs
import `grpclib`.

## Regenerate

```bash
scripts/generate_proto.sh            # default tag v1.13.5
scripts/generate_proto.sh v1.14.0    # bump the Talos pin
```
