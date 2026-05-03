"""P3 – Shared progress cache utilities for doctrine summary views.

Keys
----
- Skillset version counter : ``mastery:sv:{skillset_id}``
  Persisted without TTL (or with a very long one) so it always outlives progress
  entries.  Incremented whenever a skillset is regenerated via
  ``invalidate_progress_cache_for_skillset()``.

- Progress entry          : ``mastery:progress:v1:{character_id}:{skillset_id}:{version}``
  TTL driven by ``MASTERY_SUMMARY_PROGRESS_CACHE_TTL`` (default 600 s).
  Automatically stale when the version counter is bumped even before TTL expiry.

Usage
-----
Typical call-site in summary helpers::

    cached, key = get_cached_progress(character.id, skillset.id, version_context)
    if cached is not None:
        ...  # P3 hit
    else:
        result = pilot_progress_service.build_for_character(...)
        set_cached_progress(key, result)

Invalidation::

    invalidate_progress_cache_for_skillset(fitting_map.skillset_id)
"""
import logging

from django.core.cache import cache

from mastery import app_settings

logger = logging.getLogger(__name__)

_KEY_VERSION = "v1"
_SKILLSET_VERSION_PREFIX = "mastery:sv:"
_PROGRESS_PREFIX = "mastery:progress:"

# Long TTL for version counters so they always outlive their associated
# progress entries (which are bounded by MASTERY_SUMMARY_PROGRESS_CACHE_TTL).
_SKILLSET_VERSION_TTL = 7 * 24 * 3600  # 7 days


# ---------------------------------------------------------------------------
# Skillset version helpers
# ---------------------------------------------------------------------------

def _skillset_version_key(skillset_id: int) -> str:
    return f"{_SKILLSET_VERSION_PREFIX}{skillset_id}"


def get_skillset_cache_version(skillset_id: int, version_context: dict | None = None) -> int:
    """Return the current generation version counter for *skillset_id*.

    *version_context* is an optional request-scoped dict that prevents repeated
    cache lookups for the same skillset within a single HTTP request.
    """
    if version_context is not None and skillset_id in version_context:
        return version_context[skillset_id]

    try:
        raw = cache.get(_skillset_version_key(skillset_id))
    except Exception:  # pylint: disable=broad-except
        raw = None

    version = int(raw) if raw is not None else 1
    if version_context is not None:
        version_context[skillset_id] = version
    return version


def invalidate_progress_cache_for_skillset(skillset_id: int) -> None:
    """Bump the skillset generation counter, invalidating all cached progress entries.

    After this call every progress key that embeds the old version number will
    result in a cache miss, and fresh values will be calculated and stored under
    the new version.
    """
    version_key = _skillset_version_key(skillset_id)
    try:
        cache.incr(version_key)
    except ValueError:
        # Key does not exist yet – start the counter at 2 so initial "version 1"
        # entries are immediately invalidated.
        try:
            cache.set(version_key, 2, timeout=_SKILLSET_VERSION_TTL)
        except Exception:  # pylint: disable=broad-except
            logger.warning(
                "P3: Failed to set version counter for skillset %s",
                skillset_id,
            )
    except Exception:  # pylint: disable=broad-except
        logger.warning(
            "P3: Failed to invalidate progress cache for skillset %s",
            skillset_id,
        )


# ---------------------------------------------------------------------------
# Progress entry helpers
# ---------------------------------------------------------------------------

def build_progress_cache_key(character_id: int, skillset_id: int, version: int) -> str:
    """Build the full cache key for a character/skillset progress entry."""
    return f"{_PROGRESS_PREFIX}{_KEY_VERSION}:{character_id}:{skillset_id}:{version}"


def get_cached_progress(
    character_id: int,
    skillset_id: int,
    version_context: dict | None = None,
) -> tuple[dict | None, str]:
    """Return *(progress_dict, cache_key)* for the given pair.

    *progress_dict* is ``None`` on a cache miss so the caller can compute and
    store the value with :func:`set_cached_progress`.
    *cache_key* is always returned so the caller can pass it directly to
    :func:`set_cached_progress` without reconstructing it.
    """
    ttl = int(app_settings.MASTERY_SUMMARY_PROGRESS_CACHE_TTL)
    if ttl <= 0:
        # Cache disabled by configuration.
        key = build_progress_cache_key(character_id, skillset_id, 1)
        return None, key

    version = get_skillset_cache_version(skillset_id, version_context=version_context)
    key = build_progress_cache_key(character_id, skillset_id, version)
    try:
        value = cache.get(key)
    except Exception:  # pylint: disable=broad-except
        logger.debug("P3: Cache read error for key %s", key)
        value = None

    return value, key


def set_cached_progress(cache_key: str, progress: dict) -> None:
    """Persist *progress* in the shared cache under *cache_key*.

    A no-op when the configured TTL is zero (cache disabled).
    """
    ttl = int(app_settings.MASTERY_SUMMARY_PROGRESS_CACHE_TTL)
    if ttl <= 0:
        return
    try:
        cache.set(cache_key, progress, timeout=ttl)
    except Exception:  # pylint: disable=broad-except
        logger.debug("P3: Cache write error for key %s", cache_key)
