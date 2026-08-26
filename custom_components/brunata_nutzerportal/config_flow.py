from __future__ import annotations

from typing import Any

import voluptuous as vol
from brunata_api.errors import LoginError
from homeassistant import config_entries

from .client_factory import async_create_brunata_client
from .const import (
    CONF_BASE_URL,
    CONF_PASSWORD,
    CONF_SAP_CLIENT,
    CONF_USERNAME,
    DEFAULT_BASE_URL,
    DEFAULT_SAP_CLIENT,
    DOMAIN,
)
from .options_flow import BrunataOptionsFlow


async def _validate(hass, data: dict) -> None:
    client = await async_create_brunata_client(
        hass,
        base_url=data[CONF_BASE_URL],
        username=data[CONF_USERNAME],
        password=data[CONF_PASSWORD],
        sap_client=data[CONF_SAP_CLIENT],
    )
    try:
        await client.login()
        await client.get_account()
    finally:
        await client.aclose()


class BrunataConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1
    OPTIONS_FLOW = BrunataOptionsFlow

    async def async_step_user(self, user_input=None):
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                await _validate(self.hass, user_input)
            except LoginError:
                errors["base"] = "auth"
            except Exception:
                errors["base"] = "unknown"
            else:
                username_cf = user_input[CONF_USERNAME].casefold()
                self.async_set_unique_id(username_cf)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title="BRUdirekt",
                    data=user_input,
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_USERNAME): str,
                vol.Required(CONF_PASSWORD): str,
                vol.Optional(CONF_BASE_URL, default=DEFAULT_BASE_URL): str,
                vol.Optional(CONF_SAP_CLIENT, default=DEFAULT_SAP_CLIENT): str,
            }
        )

        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_reauth(self, entry_data: dict[str, Any]):
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        reauth_entry = self._get_reauth_entry()

        if user_input is not None:
            new_data: dict[str, Any] = {**reauth_entry.data, **user_input}
            try:
                await _validate(self.hass, new_data)
            except LoginError:
                errors["base"] = "auth"
            except Exception:
                errors["base"] = "unknown"
            else:
                self.hass.config_entries.async_update_entry(
                    reauth_entry, data=new_data
                )
                await self.hass.config_entries.async_reload(reauth_entry.entry_id)
                return self.async_abort(reason="reauth_successful")

        schema = vol.Schema({vol.Required(CONF_PASSWORD): str})

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "username": reauth_entry.data[CONF_USERNAME],
            },
        )
