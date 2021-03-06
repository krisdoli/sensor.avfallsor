"""Adds config flow for nordpool."""
import logging
from collections import OrderedDict

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from . import DOMAIN, garbage_types
from .utils import (check_settings, check_tomme_kalender, find_id,
                    find_id_from_lat_lon, get_tommeplan_page)

_LOGGER = logging.getLogger(__name__)


def create_schema(entry, option=False):
    """Create a default schema based on if a option or if settings
    is already filled out.
    """

    default_garbage_types_enabled = []

    if option:
        # We use .get here incase some of the texts gets changed.
        default_adress = entry.data.get("address", "")
        default_street_id = entry.data.get("street_id", "")
        for z in entry.data.get("garbage_types", garbage_types):
            default_garbage_types_enabled.append(z)
    else:
        default_adress = ""
        default_street_id = ""
        default_garbage_types_enabled = garbage_types

    data_schema = OrderedDict()
    data_schema[
        vol.Optional("address", default=default_adress, description="address")
    ] = str
    data_schema[
        vol.Optional("street_id", default=default_street_id, description="street_id")
    ] = str

    for gbt in garbage_types:
        if option:
            if gbt in default_garbage_types_enabled:
                data_schema[vol.Optional(gbt, default=True)] = bool
            else:
                data_schema[vol.Optional(gbt, default=False)] = bool
        else:
            data_schema[vol.Optional(gbt, default=True)] = bool

    return data_schema


class Mixin:
    async def test_setup(self, user_input):
        client = async_get_clientsession(self.hass)

        try:
            check_settings(user_input, self.hass)
        except ValueError:
            self._errors["base"] = "no_valid_settings"
            return False

        # This is what we really need.
        street_id = None

        if user_input.get("street_id"):
            street_id = user_input.get("street_id")

        # We only want to skip this if its blank, this is not required
        # if we got other info we can use.
        if user_input.get("address") is not None and street_id is None:
            street_id_from_adr = await find_id(user_input.get("address"), client)
            if street_id_from_adr is not None:
                street_id = street_id_from_adr
            else:
                self._errors["base"] = "invalid address"

        if street_id is None:
            try:
                street_id_from_lat_lon = await find_id_from_lat_lon(
                    self.hass.config.latitude, self.hass.config.longitude, client
                )

                if street_id_from_lat_lon is not None:
                    street_id = street_id_from_lat_lon
            except ValueError:
                self._errors["base"] = "wrong_lat_lon"

        if street_id is not None:
            # We need to parse this as the site returns a generic site without
            # any tømmeplan if the id invalid
            text = await get_tommeplan_page(street_id, client)
            if check_tomme_kalender(text) is True:
                return True
            else:
                self._errors["base"] = "invalid_street_id"
                return False

        else:
            self._errors["base"] = "nothing_worked"
            return False


class AvfallSorFlowHandler(Mixin, config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for Blueprint."""

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_CLOUD_POLL

    def __init__(self):
        """Initialize."""
        self._errors = {}

    async def async_step_user(
        self, user_input=None
    ):  # pylint: disable=dangerous-default-value
        """Handle a flow initialized by the user."""

        if user_input is not None:
            gbt = []
            for key, value in dict(user_input).items():
                if key in garbage_types and value is True:
                    gbt.append(key)
                    user_input.pop(key)

            if len(gbt):
                user_input["garbage_types"] = gbt

            adr = await self.test_setup(user_input)
            if adr:
                return self.async_create_entry(title="avfallsor", data=user_input)

        return await self._show_config_form(user_input)

    async def _show_config_form(self, user_input):
        """Show the configuration form to edit location data."""
        data_schema = create_schema(user_input)
        return self.async_show_form(
            step_id="user", data_schema=vol.Schema(data_schema), errors=self._errors
        )

    async def async_step_import(self, user_input):  # pylint: disable=unused-argument
        """Import a config entry.
        Special type of import, we're not actually going to store any data.
        Instead, we're going to rely on the values that are in config file.
        """
        return self.async_create_entry(title="configuration.yaml", data={})

    # @staticmethod
    # @callback
    # def async_get_options_flow(config_entry):  # TODO
    #     """Get the options flow for this handler."""
    #     return AvfallsorOptionsHandler(config_entry)


class AvfallsorOptionsHandler(config_entries.OptionsFlow, Mixin):
    """Now this class isnt like any normal option handlers.. as hav devsoption seems think options is
    #  supposed to be EXTRA options, i disagree, a user should be able to edit anything.."""

    def __init__(self, config_entry):
        self.config_entry = config_entry
        self.options = dict(config_entry.options)
        self._errors = {}

    async def async_step_init(self, user_input=None):

        return self.async_show_form(
            step_id="edit",
            data_schema=vol.Schema(create_schema(self.config_entry, option=True)),
            errors=self._errors,
        )

    async def async_step_edit(self, user_input):
        # edit does not work.
        if user_input is not None:
            gbt = []
            for key, value in dict(user_input).items():
                if key in garbage_types and value is True:
                    gbt.append(key)
                    user_input.pop(key)

            if len(gbt):
                user_input["garbage_types"] = gbt

            ok = await self.test_setup(user_input)
            if ok:
                self.hass.config_entries.async_update_entry(
                    self.config_entry, data=user_input
                )
                return self.async_create_entry(title="", data={})
            else:
                self._errors["base"] = "missing_addresse"
                # not suere this should be config_entry or user_input.
                return self.async_show_form(
                    step_id="edit",
                    data_schema=vol.Schema(
                        create_schema(self.config_entry, option=True)
                    ),
                    errors=self._errors,
                )
