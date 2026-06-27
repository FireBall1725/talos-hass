"""Config and options flow for Talos Linux."""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import selector

from .client import (
    TalosAuthError,
    TalosClient,
    TalosConnectionError,
    TalosDependencyError,
    TalosError,
)
from .const import (
    CONF_ENDPOINT,
    CONF_PORT,
    CONF_TALOSCONFIG,
    DEFAULT_PORT,
    DEFAULT_STATE_INTERVAL,
    DEFAULT_UPGRADE_INTERVAL,
    DOMAIN,
    OPT_ALLOW_DESTRUCTIVE,
    OPT_ALLOW_RESET,
    OPT_PINNED_VERSION,
    OPT_STATE_INTERVAL,
    OPT_UPGRADE_INTERVAL,
    OPT_UPGRADE_MODE,
    UPGRADE_MODE_LATEST,
    UPGRADE_MODE_PINNED,
)
from .talosconfig import TalosConfigError, TalosCredentials, parse_talosconfig

_LOGGER = logging.getLogger(__name__)


def _cluster_id(creds: TalosCredentials) -> str:
    """Stable per-cluster id from the CA, so re-adding a cluster dedupes."""
    return hashlib.sha256(creds.ca_pem).hexdigest()[:16]


async def _validate(
    hass: HomeAssistant, data: Mapping[str, Any]
) -> tuple[TalosCredentials, dict[str, Any], str, str, int]:
    """Parse the talosconfig, resolve the endpoint, connect, read version.

    The endpoint comes from the talosconfig's own ``endpoints`` list; the user
    only supplies an endpoint to override that (e.g. a talosconfig with no
    endpoints, or to reach apid by a different address).
    """
    creds = parse_talosconfig(data[CONF_TALOSCONFIG])
    override = str(data.get(CONF_ENDPOINT) or "").strip()
    endpoint = override or (creds.endpoints[0] if creds.endpoints else "")
    if not endpoint:
        raise TalosConfigError(
            "The talosconfig has no endpoints; add one or set an endpoint override"
        )
    port = int(data.get(CONF_PORT) or DEFAULT_PORT)
    client = TalosClient(endpoint, port, creds)
    await client.connect()
    try:
        info = await client.version(endpoint)
    finally:
        await client.close()
    return creds, info, _cluster_id(creds), endpoint, port


def _connection_schema(defaults: Mapping[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_TALOSCONFIG): selector.TextSelector(
                selector.TextSelectorConfig(multiline=True)
            ),
            vol.Optional(
                CONF_ENDPOINT,
                description={"suggested_value": defaults.get(CONF_ENDPOINT, "")},
            ): selector.TextSelector(),
            vol.Optional(
                CONF_PORT, default=defaults.get(CONF_PORT, DEFAULT_PORT)
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=1, max=65535, mode=selector.NumberSelectorMode.BOX
                )
            ),
        }
    )


def _resolved_data(
    user_input: Mapping[str, Any], endpoint: str, port: int
) -> dict[str, Any]:
    """The entry data we persist: the talosconfig plus the resolved endpoint."""
    return {
        CONF_TALOSCONFIG: user_input[CONF_TALOSCONFIG],
        CONF_ENDPOINT: endpoint,
        CONF_PORT: port,
    }


class TalosLinuxConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the Talos Linux config flow."""

    VERSION = 1

    async def _try(
        self, user_input: Mapping[str, Any], errors: dict[str, str]
    ) -> tuple[TalosCredentials, dict[str, Any], str, str, int] | None:
        try:
            return await _validate(self.hass, user_input)
        except TalosConfigError:
            errors["base"] = "invalid_config"
        except TalosAuthError:
            errors["base"] = "invalid_auth"
        except TalosConnectionError:
            errors["base"] = "cannot_connect"
        except TalosDependencyError:
            errors["base"] = "missing_dependency"
        except TalosError:
            errors["base"] = "unknown"
        return None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            result = await self._try(user_input, errors)
            if result is not None:
                _creds, _info, cluster_id, endpoint, port = result
                await self.async_set_unique_id(cluster_id)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"Talos ({endpoint})",
                    data=_resolved_data(user_input, endpoint, port),
                )
        return self.async_show_form(
            step_id="user",
            data_schema=_connection_schema(user_input or {}),
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            merged = {**entry.data, **user_input}
            result = await self._try(merged, errors)
            if result is not None:
                _creds, _info, cluster_id, endpoint, port = result
                await self.async_set_unique_id(cluster_id)
                self._abort_if_unique_id_mismatch(reason="wrong_cluster")
                return self.async_update_reload_and_abort(
                    entry, data=_resolved_data(merged, endpoint, port)
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=_connection_schema(entry.data),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            result = await self._try(user_input, errors)
            if result is not None:
                _creds, _info, cluster_id, endpoint, port = result
                await self.async_set_unique_id(cluster_id)
                self._abort_if_unique_id_mismatch(reason="wrong_cluster")
                return self.async_update_reload_and_abort(
                    entry, data=_resolved_data(user_input, endpoint, port)
                )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_connection_schema(user_input or entry.data),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> TalosOptionsFlow:
        return TalosOptionsFlow()


class TalosOptionsFlow(OptionsFlow):
    """Behavioral toggles; connection lives in entry data."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        opts = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Required(
                    OPT_STATE_INTERVAL,
                    default=opts.get(
                        OPT_STATE_INTERVAL, int(DEFAULT_STATE_INTERVAL.total_seconds())
                    ),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=15,
                        max=600,
                        unit_of_measurement="s",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(
                    OPT_UPGRADE_INTERVAL,
                    default=opts.get(
                        OPT_UPGRADE_INTERVAL,
                        int(DEFAULT_UPGRADE_INTERVAL.total_seconds()),
                    ),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=300,
                        max=86400,
                        unit_of_measurement="s",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(
                    OPT_UPGRADE_MODE,
                    default=opts.get(OPT_UPGRADE_MODE, UPGRADE_MODE_LATEST),
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[UPGRADE_MODE_LATEST, UPGRADE_MODE_PINNED],
                        translation_key="upgrade_mode",
                    )
                ),
                vol.Optional(
                    OPT_PINNED_VERSION,
                    description={"suggested_value": opts.get(OPT_PINNED_VERSION, "")},
                ): selector.TextSelector(),
                vol.Required(
                    OPT_ALLOW_DESTRUCTIVE,
                    default=opts.get(OPT_ALLOW_DESTRUCTIVE, False),
                ): selector.BooleanSelector(),
                vol.Required(
                    OPT_ALLOW_RESET, default=opts.get(OPT_ALLOW_RESET, False)
                ): selector.BooleanSelector(),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
