from __future__ import annotations

import voluptuous as vol

from homeassistant import config_entries

from brunata_api.errors import LoginError

from .client_factory import async_create_brunata_client
from .const import (
    DOMAIN,
    CONF_BASE_URL,
    CONF_USERNAME,
    CONF_PASSWORD,
    CONF_SAP_CLIENT,
    DEFAULT_BASE_URL,
    DEFAULT_SAP_CLIENT,
)


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
