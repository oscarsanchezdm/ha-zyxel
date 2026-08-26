"""Entity registry migration for ha_zyxel unique_id changes.

After cross-endpoint dedupe, telemetry sensors use unique_ids based on the
path *after* the API root (cardpage / device / cellular), e.g.:

  {entry_id}_CellIntfInfo.Upstream

instead of the previous per-root ids:

  {entry_id}_cardpage.CellIntfInfo.Upstream
  {entry_id}_device.CellIntfInfo.Upstream

Without migration, Home Assistant creates new entities while the old ones
remain in the registry (often disabled by the user). This module collapses
those groups onto the new unique_id, preferring the entity that already
carries user settings.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# Must stay aligned with sensor._DEDUP_ROOTS.
_DEDUP_ROOTS = frozenset({"cardpage", "device", "cellular"})
_ROOT_RANK = {"cellular": 3, "device": 2, "cardpage": 1}


def parse_legacy_unique_id(
    unique_id: str, entry_id: str
) -> tuple[str, str] | None:
    """Return (root, identity) for a pre-dedupe unique_id, else None."""
    prefix = f"{entry_id}_"
    if not unique_id.startswith(prefix):
        return None
    rest = unique_id[len(prefix) :]
    if "." not in rest:
        return None
    root, identity = rest.split(".", 1)
    if root not in _DEDUP_ROOTS or not identity:
        return None
    return root, identity


def target_unique_id(entry_id: str, identity: str) -> str:
    """Build the post-dedupe unique_id for an identity."""
    return f"{entry_id}_{identity}"


def _is_target_unique_id(unique_id: str, entry_id: str, identity: str) -> bool:
    return unique_id == target_unique_id(entry_id, identity)


def _disabled_rank(disabled_by: str | None) -> int:
    # Prefer enabled, then user-disabled (intentional), then integration-disabled.
    if disabled_by is None:
        return 2
    if disabled_by == "user":
        return 1
    return 0


def _created_timestamp(created: Any) -> float:
    """Return a comparable timestamp for RegistryEntry.created_at."""
    if created is None:
        return 0.0
    if hasattr(created, "timestamp"):
        try:
            return float(created.timestamp())
        except (TypeError, ValueError, OSError):
            return 0.0
    if isinstance(created, str):
        try:
            return datetime.fromisoformat(created.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return 0.0
    return 0.0


def _keeper_sort_key(reg_entry: er.RegistryEntry, entry_id: str) -> tuple:
    """Higher tuple sorts first (used with max())."""
    legacy = parse_legacy_unique_id(reg_entry.unique_id, entry_id)
    root_rank = _ROOT_RANK.get(legacy[0], 0) if legacy else 0
    legacy_rank = 1 if legacy else 0
    created_ts = _created_timestamp(getattr(reg_entry, "created_at", None))
    return (
        _disabled_rank(reg_entry.disabled_by),
        1 if reg_entry.name else 0,
        legacy_rank,
        root_rank,
        -created_ts,
    )


def choose_keeper(
    entries: list[er.RegistryEntry], entry_id: str
) -> er.RegistryEntry:
    """Pick the registry row to keep for an identity group."""
    return max(entries, key=lambda e: _keeper_sort_key(e, entry_id))


def group_entities_for_migration(
    entities: list[er.RegistryEntry], entry_id: str
) -> dict[str, list[er.RegistryEntry]]:
    """Group registry entries that share a post-dedupe identity."""
    groups: dict[str, list[er.RegistryEntry]] = {}
    identities_with_legacy: set[str] = set()

    for entity in entities:
        legacy = parse_legacy_unique_id(entity.unique_id, entry_id)
        if legacy is None:
            continue
        _root, identity = legacy
        identities_with_legacy.add(identity)
        groups.setdefault(identity, []).append(entity)

    if not identities_with_legacy:
        return {}

    # Attach already-migrated (new-format) siblings so they can be removed.
    for entity in entities:
        prefix = f"{entry_id}_"
        if not entity.unique_id.startswith(prefix):
            continue
        if parse_legacy_unique_id(entity.unique_id, entry_id) is not None:
            continue
        identity = entity.unique_id[len(prefix) :]
        if identity in identities_with_legacy:
            groups.setdefault(identity, []).append(entity)

    return groups


async def async_migrate_unique_ids(
    hass: HomeAssistant, config_entry_id: str
) -> int:
    """Migrate legacy root-prefixed unique_ids for one config entry.

    Returns the number of identity groups that were migrated.
    """
    registry = er.async_get(hass)
    domain_entities = [
        entry
        for entry in registry.entities.values()
        if entry.domain == "sensor"
        and entry.platform == DOMAIN
        and entry.config_entry_id == config_entry_id
    ]

    groups = group_entities_for_migration(domain_entities, config_entry_id)
    if not groups:
        return 0

    migrated = 0
    for identity, members in groups.items():
        if len(members) == 1:
            only = members[0]
            legacy = parse_legacy_unique_id(only.unique_id, config_entry_id)
            if legacy is None:
                continue
            # Single legacy entity: just rename unique_id if target is free.
            new_uid = target_unique_id(config_entry_id, identity)
            if registry.async_get_entity_id("sensor", DOMAIN, new_uid):
                continue
            try:
                registry.async_update_entity(only.entity_id, new_unique_id=new_uid)
            except Exception:  # noqa: BLE001 - keep setup resilient
                _LOGGER.exception(
                    "Failed to migrate unique_id for %s -> %s",
                    only.entity_id,
                    new_uid,
                )
                continue
            _LOGGER.info(
                "Migrated %s unique_id to %s", only.entity_id, new_uid
            )
            migrated += 1
            continue

        keeper = choose_keeper(members, config_entry_id)
        new_uid = target_unique_id(config_entry_id, identity)

        for member in members:
            if member.entity_id == keeper.entity_id:
                continue
            try:
                registry.async_remove(member.entity_id)
            except Exception:  # noqa: BLE001
                _LOGGER.exception(
                    "Failed to remove duplicate entity %s", member.entity_id
                )
                continue
            _LOGGER.info(
                "Removed duplicate Zyxel entity %s (unique_id=%s)",
                member.entity_id,
                member.unique_id,
            )

        if keeper.unique_id != new_uid:
            # Target might still be occupied if remove failed; skip rename then.
            existing = registry.async_get_entity_id("sensor", DOMAIN, new_uid)
            if existing and existing != keeper.entity_id:
                _LOGGER.warning(
                    "Skipping unique_id migrate for %s; %s still owns %s",
                    keeper.entity_id,
                    existing,
                    new_uid,
                )
                continue
            try:
                registry.async_update_entity(
                    keeper.entity_id, new_unique_id=new_uid
                )
            except Exception:  # noqa: BLE001
                _LOGGER.exception(
                    "Failed to migrate unique_id for %s -> %s",
                    keeper.entity_id,
                    new_uid,
                )
                continue
            _LOGGER.info(
                "Migrated %s unique_id to %s", keeper.entity_id, new_uid
            )

        migrated += 1

    if migrated:
        _LOGGER.info(
            "Migrated %s Zyxel sensor identity group(s) for config entry %s",
            migrated,
            config_entry_id,
        )
    return migrated
