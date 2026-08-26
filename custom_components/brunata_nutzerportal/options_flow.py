from __future__ import annotations

import voluptuous as vol
from homeassistant import config_entries

from .const import CONF_UPDATE_HOURS, DEFAULT_UPDATE_INTERVAL_HOURS


class BrunataOptionsFlow(config_entries.OptionsFlow):
    async def async_step_init(self, user_input: dict | None = None):
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        current = self.config_entry.options.get(
            CONF_UPDATE_HOURS, DEFAULT_UPDATE_INTERVAL_HOURS
        )

        schema = vol.Schema(
            {
                vol.Required(CONF_UPDATE_HOURS, default=current): vol.All(
                    vol.Coerce(int), vol.Range(min=1, max=168)
                ),
            }
        )

        return self.async_show_form(step_id="init", data_schema=schema)
