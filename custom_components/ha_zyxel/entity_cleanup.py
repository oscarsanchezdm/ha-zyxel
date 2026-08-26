"""Remove entities that belong to disabled optional OID polls."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import disabled_optional_data_roots

_LOGGER = logging.getLogger(__name__)

# Pre-0.3.8 cellwan sensors used stripped identities (cellular was in _DEDUP_ROOTS).
_LEGACY_CELLULAR_SUFFIX_PREFIXES = (
    "INTF_",
    "NSA_",
    "SCC_Info",
    "USIM_",
    "CELL_",
    "Antenna_",
)


def _suffix_belongs_to_disabled_root(suffix: str, disabled: frozenset[str]) -> bool:
    """Return True if this unique_id suffix maps to a disabled optional root."""
    root = suffix.split(".", 1)[0]
    if root in disabled:
        return True
    # Legacy cellwan unique_ids without the ``cellular.`` prefix.
    if "cellular" in disabled and any(
        suffix.startswith(p) for p in _LEGACY_CELLULAR_SUFFIX_PREFIXES
    ):
        return True
    return False


def async_cleanup_disabled_endpoint_entities(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    """Drop registry entries whose unique_id is under a disabled data root.

    Sensor unique_ids are ``{entry_id}_{root}.…`` (or a legacy stripped
    cellwan identity). Optional roots keep the full path prefix so unchecking
    an option can remove every related entity.
    """
    disabled = disabled_optional_data_roots(entry.options)
    if not disabled:
        return

    registry = er.async_get(hass)
    prefix = f"{entry.entry_id}_"
    removed = 0

    for entity_entry in er.async_entries_for_config_entry(registry, entry.entry_id):
        uid = entity_entry.unique_id or ""
        if not uid.startswith(prefix):
            continue
        suffix = uid[len(prefix) :]
        if not _suffix_belongs_to_disabled_root(suffix, disabled):
            continue
        registry.async_remove(entity_entry.entity_id)
        removed += 1

    if removed:
        _LOGGER.info(
            "Removed %s Zyxel entit%s for disabled endpoints %s",
            removed,
            "y" if removed == 1 else "ies",
            sorted(disabled),
        )
