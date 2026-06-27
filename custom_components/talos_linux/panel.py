"""Register the Talos sidebar panel, its static JS, and the websocket API."""

from __future__ import annotations

from pathlib import Path

from homeassistant.components import panel_custom
from homeassistant.components.frontend import async_remove_panel
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .websocket_api import async_register_websocket_api

PANEL_URL_PATH = "talos-linux"
JS_URL = "/talos_linux_frontend/talos-panel.js"
_JS_FILE = Path(__file__).parent / "frontend" / "talos-panel.js"


async def async_register_panel(hass: HomeAssistant) -> None:
    """Register the panel, static JS, and websocket command (idempotent).

    The websocket command needs only ``websocket_api``; the sidebar panel and
    its static JS additionally need ``http``, ``frontend``, and ``panel_custom``.
    Each part is guarded on the component being loaded, so the integration sets
    up cleanly even where the frontend stack is absent (e.g. test rigs).
    """
    data = hass.data.setdefault(DOMAIN, {})
    components = hass.config.components

    if "websocket_api" in components and not data.get("ws_registered"):
        async_register_websocket_api(hass)
        data["ws_registered"] = True

    if not {"http", "frontend", "panel_custom"} <= components:
        return

    if not data.get("static_registered"):
        await hass.http.async_register_static_paths(
            [StaticPathConfig(JS_URL, str(_JS_FILE), cache_headers=False)]
        )
        data["static_registered"] = True

    if not data.get("panel_registered"):
        await panel_custom.async_register_panel(
            hass,
            frontend_url_path=PANEL_URL_PATH,
            webcomponent_name="talos-linux-panel",
            module_url=JS_URL,
            sidebar_title="Talos",
            sidebar_icon="mdi:server-network",
            require_admin=False,
            config={},
            embed_iframe=False,
        )
        data["panel_registered"] = True


def async_unregister_panel(hass: HomeAssistant) -> None:
    """Remove the sidebar panel when the last entry unloads."""
    data = hass.data.get(DOMAIN, {})
    if data.get("panel_registered"):
        async_remove_panel(hass, PANEL_URL_PATH)
        data["panel_registered"] = False
