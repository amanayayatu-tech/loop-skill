"""Read-only v3 anti-corruption mapping and explicit v4 import."""

from .importer import (
    PUBLIC_V3_BASE_SHA,
    V3CompatibilityError,
    V3ImportPlan,
    cancel_import,
    confirm_import,
    preview_import,
    shadow_read,
)
from .legacy_entry import (
    LegacyEntryError,
    LegacyPreparedView,
    legacy_intake,
    legacy_prepare,
    map_legacy_input,
)

__all__ = [
    "PUBLIC_V3_BASE_SHA",
    "V3CompatibilityError",
    "V3ImportPlan",
    "cancel_import",
    "confirm_import",
    "preview_import",
    "shadow_read",
    "LegacyEntryError",
    "LegacyPreparedView",
    "legacy_intake",
    "legacy_prepare",
    "map_legacy_input",
]
