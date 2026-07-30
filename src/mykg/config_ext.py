"""Fork-local configuration derivations.

This module owns every config constant that the fork adds on top of upstream
mykg (the ``build-wiki`` / ``build-topics`` / ``watch`` features). Keeping the
derivations here — instead of inline in ``config.py`` — shrinks the fork's
footprint in that heavily-churned upstream file to a single call, so future
``upstream`` syncs stop colliding on it.

``derive()`` is a *pure* function: it takes the config primitives it needs and
returns a plain ``{name: value}`` dict. ``config.py`` calls it from its module
body and injects the result into its own namespace. Because ``config.py`` is
re-executed by ``importlib.reload()`` on every ``--profile`` switch, that call
re-runs too, so these constants always reflect the active profile.
"""

from __future__ import annotations

from typing import Any, Callable


def derive(
    get_opt: Callable[[str, str, Any], Any],
    raw: dict,
    user_paths: dict,
) -> dict[str, Any]:
    """Return the fork's config constants derived from the loaded YAML.

    Args:
        get_opt: ``config._get_opt`` — reads ``(section, key, default)`` from the
            active profile's pipeline block.
        raw: ``config.RAW`` — the fully-resolved config mapping (for the
            top-level, profile-independent ``watch:`` block).
        user_paths: ``config.RAW["paths"]`` — the profile-independent paths block.
    """
    watch = raw.get("watch", {}) or {}
    return {
        # Wiki (build-wiki command) — optional; defaults apply when a profile
        # omits `wiki:`.
        "WIKI_MAX_WORKERS": int(get_opt("wiki", "max_workers", 4)),
        "WIKI_MIN_ATTR_CONFIDENCE": float(get_opt("wiki", "min_attr_confidence", 0.3)),
        "WIKI_MIN_EDGE_CONFIDENCE": float(get_opt("wiki", "min_edge_confidence", 0.3)),
        "WIKI_MAX_GROUNDING_TOKENS": int(get_opt("wiki", "max_grounding_tokens", 4000)),
        "WIKI_NEIGHBORS_MAX": int(get_opt("wiki", "neighbors_max", 25)),
        # Topics (build-topics command) — optional; defaults apply when a profile
        # omits `topics:`.
        "TOPICS_RESOLUTION": float(get_opt("topics", "resolution", 1.0)),
        "TOPICS_MIN_SIZE": int(get_opt("topics", "min_size", 3)),
        "TOPICS_MEMBERS_MAX": int(get_opt("topics", "members_max", 25)),
        "TOPICS_ENABLED": bool(get_opt("topics", "enabled", True)),
        # User/environment bootstrap — top-level `paths:` block.
        "WIKI_ROOT": user_paths["wiki_root"],
        # Watch — top-level `watch:` block (profile-independent). Defaults applied
        # here so the block's optional keys can be omitted.
        "WATCH_POLL_INTERVAL_SECONDS": int(watch.get("poll_interval_seconds", 300)),
        "WATCH_DEBOUNCE_SECONDS": int(watch.get("debounce_seconds", 600)),
        "WATCH_QUEUE_DIR": str(watch.get("queue_dir", "_watch_queue")),
        "WATCH_AUTOPILOT": bool(watch.get("autopilot", False)),
        "WATCH_ENTRIES": list(watch.get("entries", []) or []),
    }
