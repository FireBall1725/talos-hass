"""Button platform for Talos Linux.

A cluster-level Refresh button, plus per-node Reboot and Shut down buttons. The
destructive buttons are disabled by default and, even when enabled, refuse to
act unless ``allow_destructive`` is on and the talosconfig role can write. A
button carries no confirm step, so the disabled-by-default gate is deliberate;
the reboot/shutdown services keep the confirm_node echo for scripted use.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from homeassistant.components.button import (
    ButtonDeviceClass,
    ButtonEntity,
    ButtonEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import TalosConfigEntry
from .const import OPT_ALLOW_DESTRUCTIVE
from .coordinator import TalosCoordinator
from .entity import TalosClusterEntity, TalosNodeEntity, register_node_entities


async def _do_reboot(coordinator: TalosCoordinator, address: str) -> None:
    await coordinator.client.reboot(address)
    await coordinator.async_request_refresh()


async def _do_shutdown(coordinator: TalosCoordinator, address: str) -> None:
    await coordinator.client.shutdown(address)
    await coordinator.async_request_refresh()


@dataclass(frozen=True, kw_only=True)
class TalosNodeButtonDescription(ButtonEntityDescription):
    """A per-node action button."""

    press_fn: Callable[[TalosCoordinator, str], Awaitable[None]]


NODE_BUTTONS: tuple[TalosNodeButtonDescription, ...] = (
    TalosNodeButtonDescription(
        key="reboot",
        translation_key="reboot",
        device_class=ButtonDeviceClass.RESTART,
        entity_registry_enabled_default=False,
        press_fn=_do_reboot,
    ),
    TalosNodeButtonDescription(
        key="shutdown",
        translation_key="shutdown",
        icon="mdi:power",
        entity_registry_enabled_default=False,
        press_fn=_do_shutdown,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TalosConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Talos buttons."""
    coordinator = entry.runtime_data.coordinator
    register_node_entities(
        entry,
        coordinator,
        async_add_entities,
        lambda address: [
            TalosNodeButton(coordinator, entry, address, desc) for desc in NODE_BUTTONS
        ],
    )
    async_add_entities([TalosRefreshButton(coordinator, entry)])


class TalosNodeButton(TalosNodeEntity, ButtonEntity):
    """A gated per-node action button (reboot / shut down)."""

    entity_description: TalosNodeButtonDescription

    def __init__(self, coordinator, entry, address, description) -> None:
        super().__init__(coordinator, entry, address, description.key)
        self.entity_description = description

    async def async_press(self) -> None:
        if not (
            self._entry.options.get(OPT_ALLOW_DESTRUCTIVE)
            and self.coordinator.creds.can_write
        ):
            raise HomeAssistantError(
                "Destructive operations are disabled, or the talosconfig role "
                "cannot perform this action"
            )
        await self.entity_description.press_fn(self.coordinator, self._address)


class TalosRefreshButton(TalosClusterEntity, ButtonEntity):
    """Force an immediate poll of the whole cluster."""

    _attr_translation_key = "refresh"
    _attr_icon = "mdi:refresh"

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry, "refresh")

    async def async_press(self) -> None:
        await self.coordinator.async_request_refresh()
