"""Constants for the Talos Linux integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "talos_linux"

# Pin recorded for the vendored proto stubs. Regenerate stubs when this changes.
PROTO_TALOS_VERSION: Final = "v1.13.5"

# --- Connection -------------------------------------------------------------
DEFAULT_PORT: Final = 50000

CONF_ENDPOINT: Final = "endpoint"
CONF_PORT: Final = "port"
CONF_TALOSCONFIG: Final = "talosconfig"
CONF_CA: Final = "ca"
CONF_CRT: Final = "crt"
CONF_KEY: Final = "key"

# --- Options ----------------------------------------------------------------
OPT_STATE_INTERVAL: Final = "state_interval"
OPT_UPGRADE_INTERVAL: Final = "upgrade_check_interval"
OPT_UPGRADE_MODE: Final = "upgrade_target_mode"
OPT_PINNED_VERSION: Final = "pinned_version"
OPT_ALLOW_DESTRUCTIVE: Final = "allow_destructive"
OPT_ALLOW_RESET: Final = "allow_reset"

UPGRADE_MODE_LATEST: Final = "latest_stable"
UPGRADE_MODE_PINNED: Final = "pinned"

DEFAULT_STATE_INTERVAL: Final = timedelta(seconds=45)
DEFAULT_UPGRADE_INTERVAL: Final = timedelta(hours=1)

# --- Talos RBAC roles (read from the talosconfig cert) ----------------------
ROLE_READER: Final = "os:reader"
ROLE_OPERATOR: Final = "os:operator"
ROLE_ADMIN: Final = "os:admin"

# Roles permitted to run each write tier.
WRITE_ROLES: Final = frozenset({ROLE_OPERATOR, ROLE_ADMIN})
RESET_ROLES: Final = frozenset({ROLE_ADMIN})

# --- Machine stages (MachineStatus resource) --------------------------------
STAGE_BOOTING: Final = "booting"
STAGE_INSTALLING: Final = "installing"
STAGE_MAINTENANCE: Final = "maintenance"
STAGE_RUNNING: Final = "running"
STAGE_REBOOTING: Final = "rebooting"
STAGE_SHUTTING_DOWN: Final = "shuttingDown"
STAGE_RESETTING: Final = "resetting"
STAGE_UPGRADING: Final = "upgrading"

# --- apid / COSI -----------------------------------------------------------
# apid metadata keys for proxying. MachineService supports one-to-many
# fan-out (plural `nodes`); the COSI State service only supports one-to-one
# proxying and requires the singular `node`. Using the wrong one fails with
# "one-2-many proxying is not supported".
NODES_METADATA_KEY: Final = "nodes"
NODE_METADATA_KEY: Final = "node"

# COSI resource coordinates (namespace, type, id). Confirmed against a live
# Talos v1.13.5 cluster: the State API returns a populated yaml_spec (a dict
# after parsing), not proto_spec.
COSI_NS_RUNTIME: Final = "runtime"
COSI_NS_CLUSTER: Final = "cluster"
RES_MACHINE_STATUS_TYPE: Final = "MachineStatuses.runtime.talos.dev"
RES_MACHINE_STATUS_ID: Final = "machine"
RES_EXTENSION_STATUS_TYPE: Final = "ExtensionStatuses.runtime.talos.dev"
RES_MEMBER_TYPE: Final = "Members.cluster.talos.dev"

# The Image Factory schematic ID is not its own resource. It is a synthetic
# ExtensionStatus whose spec.metadata.name is this, with the hash in
# spec.metadata.version.
SCHEMATIC_EXTENSION_NAME: Final = "schematic"

# The ephemeral/system data volume mounts here on Talos (xfs on the system
# disk). Used for the system-disk usage sensor.
SYSTEM_DISK_MOUNT: Final = "/var"

# --- Upgrade image construction ---------------------------------------------
# factory.talos.dev/installer/<schematic-id>:<version>
FACTORY_INSTALLER_BASE: Final = "factory.talos.dev/installer"

# --- GitHub release source for upgrade availability -------------------------
GITHUB_RELEASES_URL: Final = (
    "https://api.github.com/repos/siderolabs/talos/releases/latest"
)
GITHUB_RELEASE_TAG_URL: Final = "https://github.com/siderolabs/talos/releases/tag/{tag}"

# --- Services ---------------------------------------------------------------
SERVICE_REFRESH: Final = "refresh"
SERVICE_GET_SERVICE_STATUS: Final = "get_service_status"
SERVICE_REBOOT_NODE: Final = "reboot_node"
SERVICE_UPGRADE_NODE: Final = "upgrade_node"
SERVICE_APPLY_CONFIG: Final = "apply_config"
SERVICE_RESET_NODE: Final = "reset_node"

ATTR_CONFIG_ENTRY_ID: Final = "config_entry_id"
ATTR_NODE: Final = "node"
ATTR_CONFIRM_NODE: Final = "confirm_node"
ATTR_VERSION: Final = "version"
ATTR_MODE: Final = "mode"
ATTR_CONFIG: Final = "config"
ATTR_GRACEFUL: Final = "graceful"
