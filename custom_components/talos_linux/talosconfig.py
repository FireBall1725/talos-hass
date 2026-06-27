"""Parse a talosconfig into connection credentials and RBAC roles.

Talos authenticates API clients with mTLS. The client certificate also carries
the caller's RBAC roles in its X.509 Subject Organization (``O=``) attributes,
so an ``os:admin`` cert has ``O=os:admin``. Reading those tells us, at setup
time, which write tiers the credential is even allowed to use, before we offer
any destructive action in the UI.
"""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass, field

import yaml
from cryptography import x509
from cryptography.x509.oid import NameOID

from .const import RESET_ROLES, WRITE_ROLES


class TalosConfigError(Exception):
    """Raised when a talosconfig is malformed or incomplete."""


@dataclass(slots=True)
class TalosCredentials:
    """mTLS material and roles drawn from one talosconfig context."""

    endpoints: list[str]
    ca_pem: bytes
    crt_pem: bytes
    key_pem: bytes
    roles: frozenset[str] = field(default_factory=frozenset)

    @property
    def can_write(self) -> bool:
        """True if the cert role permits reboot/upgrade/apply-config."""
        return bool(self.roles & WRITE_ROLES)

    @property
    def can_reset(self) -> bool:
        """True if the cert role permits a node reset/wipe."""
        return bool(self.roles & RESET_ROLES)


def _decode_b64(value: str, label: str) -> bytes:
    """Strict base64 decode with a field-specific error."""
    if not isinstance(value, str) or not value:
        raise TalosConfigError(f"missing {label} in talosconfig")
    try:
        return base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as err:
        raise TalosConfigError(f"invalid base64 for {label} in talosconfig") from err


def _normalize_key_pem(pem: bytes) -> bytes:
    """Rewrite Talos's nonstandard key PEM label to one OpenSSL accepts.

    Talos emits ``-----BEGIN ED25519 PRIVATE KEY-----`` with a PKCS#8 DER body.
    OpenSSL's PEM reader dispatches on the label and only knows ``PRIVATE KEY``
    for PKCS#8, so it rejects the Talos label even though the bytes are valid.
    The body is unchanged; only the label is rewritten.
    """
    return pem.replace(b"ED25519 PRIVATE KEY", b"PRIVATE KEY")


def extract_roles(crt_pem: bytes) -> frozenset[str]:
    """Read Talos RBAC roles from the client cert's Subject O attributes."""
    try:
        cert = x509.load_pem_x509_certificate(crt_pem)
    except ValueError as err:
        raise TalosConfigError("client certificate is not valid PEM") from err
    orgs = cert.subject.get_attributes_for_oid(NameOID.ORGANIZATION_NAME)
    return frozenset(
        attr.value for attr in orgs if isinstance(attr.value, str) and attr.value
    )


def credentials_from_fields(
    ca_b64: str, crt_b64: str, key_b64: str, endpoints: list[str]
) -> TalosCredentials:
    """Build credentials from already-separated base64 ca/crt/key fields."""
    crt = _decode_b64(crt_b64, "crt")
    return TalosCredentials(
        endpoints=list(endpoints),
        ca_pem=_decode_b64(ca_b64, "ca"),
        crt_pem=crt,
        key_pem=_normalize_key_pem(_decode_b64(key_b64, "key")),
        roles=extract_roles(crt),
    )


def parse_talosconfig(text: str) -> TalosCredentials:
    """Parse a full talosconfig YAML and return the active context's creds."""
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as err:
        raise TalosConfigError(f"talosconfig is not valid YAML: {err}") from err
    if not isinstance(data, dict):
        raise TalosConfigError("talosconfig is empty or malformed")

    contexts = data.get("contexts")
    if not isinstance(contexts, dict) or not contexts:
        raise TalosConfigError("talosconfig has no contexts")

    name = data.get("context")
    if name and name in contexts:
        ctx = contexts[name]
    elif len(contexts) == 1:
        # No active context named, but only one exists; use it.
        ctx = next(iter(contexts.values()))
    else:
        raise TalosConfigError(
            "talosconfig 'context' does not match any defined context"
        )
    if not isinstance(ctx, dict):
        raise TalosConfigError("talosconfig context is malformed")

    endpoints = ctx.get("endpoints") or []
    if not isinstance(endpoints, list):
        raise TalosConfigError("talosconfig endpoints must be a list")

    return credentials_from_fields(
        ctx.get("ca", ""), ctx.get("crt", ""), ctx.get("key", ""), endpoints
    )
