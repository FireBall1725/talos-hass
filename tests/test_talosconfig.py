"""Tests for talosconfig parsing and role extraction (no HA needed)."""

from __future__ import annotations

import pytest
from custom_components.talos_linux.talosconfig import (
    TalosConfigError,
    _normalize_key_pem,
    parse_talosconfig,
)

from tests.conftest import make_talosconfig


def test_admin_roles() -> None:
    creds = parse_talosconfig(make_talosconfig("os:admin"))
    assert creds.endpoints == ["192.0.2.10"]
    assert creds.can_write
    assert creds.can_reset


def test_reader_roles() -> None:
    creds = parse_talosconfig(make_talosconfig("os:reader"))
    assert not creds.can_write
    assert not creds.can_reset


def test_operator_writes_but_does_not_reset() -> None:
    creds = parse_talosconfig(make_talosconfig("os:operator"))
    assert creds.can_write
    assert not creds.can_reset


def test_normalize_key_label() -> None:
    weird = (
        b"-----BEGIN ED25519 PRIVATE KEY-----\nx\n-----END ED25519 PRIVATE KEY-----\n"
    )
    expected = b"-----BEGIN PRIVATE KEY-----\nx\n-----END PRIVATE KEY-----\n"
    assert _normalize_key_pem(weird) == expected


def test_non_mapping_raises() -> None:
    with pytest.raises(TalosConfigError):
        parse_talosconfig("just a string")


def test_no_contexts_raises() -> None:
    with pytest.raises(TalosConfigError):
        parse_talosconfig("contexts: {}")
