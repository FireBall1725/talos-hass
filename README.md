# Talos Linux for Home Assistant

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![Tests](https://github.com/fireball1725/talos-hass/actions/workflows/tests.yaml/badge.svg)](https://github.com/fireball1725/talos-hass/actions/workflows/tests.yaml)
[![Hassfest](https://github.com/fireball1725/talos-hass/actions/workflows/hassfest.yaml/badge.svg)](https://github.com/fireball1725/talos-hass/actions/workflows/hassfest.yaml)

[![Open your Home Assistant instance and open this repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=fireball1725&repository=talos-hass&category=integration)

A Home Assistant integration that surfaces Talos Linux cluster state: node OS versions, available upgrades, machine stage, system extensions, etcd health, and per-node metrics. It talks to the Talos API (`apid`) directly over mTLS, so it sees the Talos-native data that the generic `kubernetes` integration can't reach.

> **Status: pre-release (0.1.0), under active development.** Not yet published to the HACS default store. Expect breaking changes until 1.0.

## Why this exists

The existing [`kubernetes`](https://github.com/tibuntu/homeassistant-kubernetes) integration reads nodes through the Kubernetes API. From there a Talos node looks like any other node: a version string, a kubelet version, a ready condition. Talos keeps the rest behind its own gRPC API on port 50000: the running Talos version, the machine stage, installed system extensions, the Image Factory schematic ID, etcd member health, and per-node disk, CPU, and memory. This integration reads that API.

The headline feature is a per-node `update` entity that knows each node's schematic and builds the exact upgrade installer image, so an upgrade started from Home Assistant keeps that node's extensions instead of stripping them.

## Requirements

- A Talos Linux cluster reachable on `apid` port 50000.
- A `talosconfig` with at least the `os:reader` role. Write actions (reboot, upgrade, apply config, reset) need `os:operator` or `os:admin`.
- 64-bit Home Assistant (amd64 or aarch64). The integration depends on `grpcio`, which ships prebuilt wheels for 64-bit glibc and musl. 32-bit ARM (armv7) has no wheel and is not supported.

## Install (HACS custom repository)

Click the **Open in HACS** button above, or add it manually:

1. HACS → three-dot menu → Custom repositories.
2. Add `https://github.com/fireball1725/talos-hass` as an Integration.
3. Install **Talos Linux**, then restart Home Assistant.
4. Settings → Devices & Services → Add Integration → **Talos Linux**, or use this button:

[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=talos_linux)

## Configuration

The config flow asks for one control-plane endpoint and your `talosconfig`. `apid` proxies from that endpoint to every node, so node discovery is automatic. The flow detects the cert's role and tells you which write actions are available.

Options (set after setup):

- **Poll intervals** — node state (default 45s) and the upgrade-availability check (default hourly).
- **Upgrade target** — track the latest stable Talos release, or pin a target version that matches your upgrade plan.
- **Allow destructive operations** — off by default. Gates reboot, upgrade, and apply-config services.
- **Allow node reset/wipe** — a separate toggle, off by default. Gates the one service that destroys a node.

## Entities

One device per Talos node, plus a cluster device. Per node: Talos version, Kubernetes version, kernel version, machine stage, CPU/memory/disk usage, uptime, schematic ID, extension count, and an `update` entity. Binary sensors cover node ready, etcd member health, reboot pending, and Secure Boot. The cluster device carries version-spread, etcd quorum, node counts, and (planned) certificate expiry.

## Services and safety

Write actions are gated three ways at once: the matching options toggle must be on, the cert role must allow it, and the call must pass a `confirm_node` field that string-matches the target node. A service whose tier is disabled is not registered at all.

**Single node only.** There is no orchestration in this integration. It will not cordon, drain, or sequence anything for you. Upgrading or rebooting more than one control-plane node at a time breaks etcd quorum. Ordering across nodes is your job, in your own automation.

## Development

Run the same checks CI runs:

```
pip install -r requirements_test.txt
ruff check custom_components/ tests/
ruff format --check custom_components/ tests/
mypy custom_components/talos_linux
pytest tests/
```

The gRPC stubs under `custom_components/talos_linux/proto/` are generated, not hand-edited. To regenerate them for a new Talos tag, run `scripts/generate_proto.sh`.

## Credits

Built by FireBall1725. Talos Linux is made by [Sidero Labs](https://www.siderolabs.com/).

## License

GNU Affero General Public License v3.0. Copyright © 2026 FireBall1725. See [LICENSE](LICENSE).
