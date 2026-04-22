"""Optional Secure Groups filter models for Fitting Mastery.

This module is only imported when ``allianceauth-secure-groups`` is installed.
All references to ``securegroups`` models are guarded with ``try/except``.

Four Smart Filter types are exposed:

* :class:`MasteryFittingStatusFilter`   – bucket-based status check on a fitting
* :class:`MasteryFittingProgressFilter` – % completion of the recommended / required plan
* :class:`MasteryDoctrineReadinessFilter` – "can fly N fittings in a doctrine"
* :class:`MasteryFittingEliteFilter`    – simplified elite-bucket check on a fitting
"""

# NOTE: This module intentionally uses broad exception guards because filters must
# fail-safe in optional-integration contexts and never break securegroups sync runs.
# pylint: disable=imported-auth-user,wrong-import-position,broad-exception-caught

from collections import defaultdict

from django.contrib.auth.models import User
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

from allianceauth.services.hooks import get_extension_logger

logger = get_extension_logger(__name__)

try:
    from securegroups.models import FilterBase
    _SECURE_GROUPS_AVAILABLE = True
except ImportError:  # pragma: no cover
    FilterBase = models.Model  # type: ignore[assignment,misc]
    _SECURE_GROUPS_AVAILABLE = False

# Import status-bucket helpers at module level so tests can patch them cleanly.
# These are always available (no conditional dependency).
from mastery.services.pilots.status_buckets import (  # noqa: E402
    BUCKET_ELITE,
    BUCKET_LABELS,
    BUCKET_RANK,
    bucket_for_progress,
)


# ──────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ──────────────────────────────────────────────────────────────────────────────

def _get_memberaudit_characters(user: User) -> list:
    """Return memberaudit Character objects for every character owned by *user*."""
    try:
        from memberaudit.models import Character  # import-outside-toplevel
        return list(
            Character.objects.owned_by_user(user).select_related(
                "eve_character",
                "eve_character__character_ownership",
            )
        )
    except Exception:  # noqa: BLE001
        return []


def _character_name(character) -> str:
    """Best-effort display name for a memberaudit Character."""
    try:
        name = character.eve_character.character_name
        if isinstance(name, str) and name:
            return name
    except Exception:  # noqa: BLE001
        pass

    try:
        # Backward-compatible fallback for mocked objects used in tests.
        name = character.character_ownership.character.character_name
        if isinstance(name, str) and name:
            return name
    except Exception:  # noqa: BLE001
        pass

    return str(character)


def _can_fly_via_progress(character, skillset, cache_context: dict | None = None) -> bool:
    """Fallback can-fly evaluation based on mastery-required progress.

    This is a defensive workaround for occasional Member Audit false negatives
    where recommended-only skills are incorrectly flagged as required.
    """
    progress = _build_progress(character, skillset, cache_context=cache_context)
    if not progress:
        return False
    required_pct = float(progress.get("required_pct") or 0)
    return bool(progress.get("can_fly", False)) and required_pct >= 100.0


def _can_fly_any(character, skillset, cache_context: dict | None = None) -> bool:
    """Return can-fly from Member Audit check, with strict mastery fallback."""
    if _can_fly_db(character, skillset.id):
        return True
    return _can_fly_via_progress(character, skillset, cache_context=cache_context)


def _can_fly_map_for_characters(characters: list, skillset) -> dict:
    """Build {character_id: can_fly} from Member Audit checks.

    Missing checks are treated as False to avoid accidental broad matches.
    """
    can_fly_map = _bulk_can_fly_map(characters, skillset.id)
    cache_context: dict = {}
    for character in characters:
        character_id = getattr(character, "id", None)
        if character_id is None:
            continue
        if can_fly_map.get(character_id, False):
            continue
        can_fly_map[character_id] = _can_fly_via_progress(
            character,
            skillset,
            cache_context=cache_context,
        )
    return can_fly_map


def _character_id(character):
    """Return character ID when available."""
    try:
        return character.id
    except Exception:  # noqa: BLE001
        return None


def _can_fly_db(character, skillset_id: int) -> bool:
    """
    Return whether *character* can fly a skillset using only a DB query
    (no PilotProgressService overhead).

    Relies on :attr:`~memberaudit.models.CharacterSkillSetCheck.can_fly`
    which checks ``not failed_required_skills.exists()``.
    """
    try:
        from memberaudit.models import CharacterSkillSetCheck  # import-outside-toplevel
        check = CharacterSkillSetCheck.objects.get(
            character=character,
            skill_set_id=skillset_id,
        )
        return check.can_fly
    except Exception:  # noqa: BLE001
        return False


def _build_progress(character, skillset, cache_context: dict | None = None) -> dict:
    """
    Return a progress dict from :class:`~mastery.services.pilots.pilot_progress_service.PilotProgressService`
    for (*character*, *skillset*).

    Returns an empty dict on any error so callers can safely use ``.get()``.
    """
    try:
        from mastery.services.pilots.pilot_progress_service import PilotProgressService  # import-outside-toplevel
        svc = PilotProgressService()
        return svc.build_for_character(
            character=character,
            skillset=skillset,
            include_export_lines=False,
            cache_context=cache_context,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("MasterySecureGroups: progress build failed for %s: %s", character, exc)
        return {}


def _best_progress_for_characters(characters: list, skillset) -> dict | None:
    """
    Return the progress dict with the highest bucket rank across *characters*.

    Returns ``None`` if no progress could be computed.
    """
    best: dict | None = None
    best_rank: int = -1

    for character in characters:
        progress = _build_progress(character, skillset)
        if not progress:
            continue
        bucket = bucket_for_progress(progress)
        rank = BUCKET_RANK.get(bucket, 0)
        if rank > best_rank:
            best_rank = rank
            best = dict(progress)
            best["_character_name"] = _character_name(character)

    return best


def _best_pct_for_characters(characters: list, skillset, use_required: bool = False) -> tuple[float, str]:
    """
    Return ``(max_pct, character_name)`` across all characters for *skillset*.

    Uses ``required_pct`` when *use_required* is True, ``recommended_pct`` otherwise.
    """
    max_pct: float = 0.0
    best_name: str = ""

    for character in characters:
        progress = _build_progress(character, skillset)
        if not progress:
            continue
        pct = float(progress.get("required_pct" if use_required else "recommended_pct") or 0)
        if pct > max_pct:
            max_pct = pct
            best_name = _character_name(character)

    return max_pct, best_name


def _bulk_can_fly_map(characters: list, skillset_id: int) -> dict:
    """
    Return ``{character_id: bool}`` for all characters in one DB query.

    Used by ``audit_filter`` implementations for performance.
    """
    try:
        from memberaudit.models import CharacterSkillSetCheck  # import-outside-toplevel
        checks = CharacterSkillSetCheck.objects.filter(
            character__in=characters,
            skill_set_id=skillset_id,
        ).prefetch_related("failed_required_skills")
        return {check.character_id: check.can_fly for check in checks}
    except Exception:  # noqa: BLE001
        return {}


def _user_to_characters_map(users) -> dict:
    """
    Return ``{user_id: [Character, …]}`` for all users in one DB query.
    """
    try:
        from memberaudit.models import Character  # import-outside-toplevel
        user_ids = [u.id for u in users]
        chars = Character.objects.filter(
            eve_character__character_ownership__user_id__in=user_ids
        ).select_related(
            "eve_character",
            "eve_character__character_ownership__user",
        )
        result: dict = defaultdict(list)
        for char in chars:
            try:
                uid = char.eve_character.character_ownership.user_id
                result[uid].append(char)
            except Exception:  # noqa: BLE001
                pass
        return result
    except Exception:  # noqa: BLE001
        return {}


# ──────────────────────────────────────────────────────────────────────────────
# Shared status-bucket choices (mirrors status_buckets constants)
# ──────────────────────────────────────────────────────────────────────────────

_STATUS_CHOICES = [
    ("needs_training", _("Needs training")),
    ("almost_fit", _("Almost fit")),
    ("can_fly", _("Can fly")),
    ("almost_elite", _("Almost elite")),
    ("elite", _("Elite")),
]

_STATUS_REQUIRES_PROGRESS_SERVICE = {"almost_elite", "elite"}


# ──────────────────────────────────────────────────────────────────────────────
# Filter 1 – Fitting Status (bucket-based)
# ──────────────────────────────────────────────────────────────────────────────

class MasteryFittingStatusFilter(FilterBase):  # type: ignore[valid-type,misc]
    """Gate a Smart Group on a pilot reaching a minimum status bucket for a fitting."""

    name = models.CharField(max_length=500, verbose_name=_("name"))
    description = models.CharField(max_length=500, verbose_name=_("description"))

    fitting_map = models.ForeignKey(
        "mastery.FittingSkillsetMap",
        on_delete=models.CASCADE,
        verbose_name=_("fitting skill plan"),
        related_name="+",
    )
    minimum_status = models.CharField(
        max_length=20,
        choices=_STATUS_CHOICES,
        default="can_fly",
        verbose_name=_("minimum status"),
        help_text=_("Minimum status bucket a pilot must reach to pass this filter."),
    )
    check_all_characters = models.BooleanField(
        default=False,
        verbose_name=_("require all characters"),
        help_text=_(
            "If checked, every registered character must reach the minimum status. "
            "By default, any single qualifying character is sufficient."
        ),
    )

    class Meta:
        verbose_name = _("Smart Filter: Mastery — Fitting Status")
        verbose_name_plural = _("Smart Filter: Mastery — Fitting Status")
        abstract = not _SECURE_GROUPS_AVAILABLE

    def __str__(self) -> str:
        return f"{self.name}: {self.description}"

    def _passes(self, characters: list, skillset) -> list[bool]:
        """Return list of pass/fail booleans, one per character."""
        min_rank = BUCKET_RANK.get(self.minimum_status, 0)
        results = []

        for character in characters:
            if self.minimum_status not in _STATUS_REQUIRES_PROGRESS_SERVICE:
                # Fast path: required skills only → use DB check
                can_fly = _can_fly_any(character, skillset)
                if self.minimum_status == "can_fly":
                    results.append(can_fly)
                    continue
                if self.minimum_status in ("needs_training", "almost_fit"):
                    # These are "below can_fly" statuses — always False as a minimum
                    # (meaning: user must at least reach this bucket, not be at this bucket)
                    # Interpretation: minimum_status = "needs_training" means "no restriction"
                    results.append(True)
                    continue

            progress = _build_progress(character, skillset)
            if not progress:
                results.append(False)
                continue
            bucket = bucket_for_progress(progress)
            results.append(BUCKET_RANK.get(bucket, 0) >= min_rank)

        return results

    def process_filter(self, user: User) -> bool:
        characters = _get_memberaudit_characters(user)
        if not characters:
            return False

        try:
            skillset = self.fitting_map.skillset
        except Exception:  # noqa: BLE001
            return False

        results = self._passes(characters, skillset)
        if not results:
            return False

        if self.check_all_characters:
            return all(results)
        return any(results)

    def audit_filter(self, users) -> dict:
        output: dict = defaultdict(lambda: {"check": False, "message": ""})
        try:
            skillset = self.fitting_map.skillset
        except Exception:  # noqa: BLE001
            return {u.id: {"check": False, "message": _("Fitting not configured")} for u in users}

        user_chars = _user_to_characters_map(users)
        min_rank = BUCKET_RANK.get(self.minimum_status, 0)
        can_fly_map = _can_fly_map_for_characters(
            [char for chars in user_chars.values() for char in chars],
            skillset,
        ) if self.minimum_status == "can_fly" else {}

        for user in users:
            characters = user_chars.get(user.id, [])
            if not characters:
                output[user.id] = {"check": False, "message": str(_("No registered characters"))}
                continue

            best_rank = -1
            best_label = ""
            best_char = ""
            results = []

            for character in characters:
                if self.minimum_status == "can_fly":
                    passed = bool(can_fly_map.get(_character_id(character), False))
                    results.append(passed)
                    rank = BUCKET_RANK.get("can_fly" if passed else "needs_training", 0)
                    label = str(BUCKET_LABELS.get("can_fly" if passed else "needs_training"))
                else:
                    progress = _build_progress(character, skillset)
                    if not progress:
                        results.append(False)
                        continue
                    bucket = bucket_for_progress(progress)
                    rank = BUCKET_RANK.get(bucket, 0)
                    label = str(BUCKET_LABELS.get(bucket, bucket))
                    results.append(rank >= min_rank)
                if rank > best_rank:
                    best_rank = rank
                    best_label = label
                    best_char = _character_name(character)

            if self.check_all_characters:
                passed = all(results) if results else False
            else:
                passed = any(results) if results else False

            message = f"{best_char}: {best_label}" if best_char else str(_("No data"))
            output[user.id] = {"check": passed, "message": message}

        return output


# ──────────────────────────────────────────────────────────────────────────────
# Filter 2 – Fitting Progress (% completion)
# ──────────────────────────────────────────────────────────────────────────────

class MasteryFittingProgressFilter(FilterBase):  # type: ignore[valid-type,misc]
    """Gate a Smart Group on % completion of the recommended (or required) skill plan."""

    name = models.CharField(max_length=500, verbose_name=_("name"))
    description = models.CharField(max_length=500, verbose_name=_("description"))

    fitting_map = models.ForeignKey(
        "mastery.FittingSkillsetMap",
        on_delete=models.CASCADE,
        verbose_name=_("fitting skill plan"),
        related_name="+",
    )
    minimum_progress_pct = models.PositiveSmallIntegerField(
        default=80,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        verbose_name=_("minimum progress (%)"),
        help_text=_("Pilot must have completed at least this percentage of the skill plan."),
    )
    use_required_plan = models.BooleanField(
        default=False,
        verbose_name=_("use required plan"),
        help_text=_(
            "If checked, progress is measured against the required skills plan. "
            "By default, the recommended skills plan is used."
        ),
    )

    class Meta:
        verbose_name = _("Smart Filter: Mastery — Fitting Progress")
        verbose_name_plural = _("Smart Filter: Mastery — Fitting Progress")
        abstract = not _SECURE_GROUPS_AVAILABLE

    def __str__(self) -> str:
        return f"{self.name}: {self.description}"

    def process_filter(self, user: User) -> bool:
        characters = _get_memberaudit_characters(user)
        if not characters:
            return False

        try:
            skillset = self.fitting_map.skillset
        except Exception:  # noqa: BLE001
            return False

        max_pct, _ = _best_pct_for_characters(characters, skillset, self.use_required_plan)
        return max_pct >= float(self.minimum_progress_pct)

    def audit_filter(self, users) -> dict:
        output: dict = defaultdict(lambda: {"check": False, "message": ""})
        try:
            skillset = self.fitting_map.skillset
        except Exception:  # noqa: BLE001
            return {u.id: {"check": False, "message": str(_("Fitting not configured"))} for u in users}

        user_chars = _user_to_characters_map(users)
        pct_key = "required_pct" if self.use_required_plan else "recommended_pct"

        for user in users:
            characters = user_chars.get(user.id, [])
            if not characters:
                output[user.id] = {"check": False, "message": str(_("No registered characters"))}
                continue

            max_pct = 0.0
            best_char = ""
            for character in characters:
                progress = _build_progress(character, skillset)
                if not progress:
                    continue
                pct = float(progress.get(pct_key) or 0)
                if pct > max_pct:
                    max_pct = pct
                    best_char = _character_name(character)

            passed = max_pct >= float(self.minimum_progress_pct)
            label = f"{best_char}: {max_pct:.1f}%" if best_char else str(_("No data"))
            output[user.id] = {"check": passed, "message": label}

        return output


# ──────────────────────────────────────────────────────────────────────────────
# Filter 3 – Doctrine Readiness (can fly N fittings)
# ──────────────────────────────────────────────────────────────────────────────

class MasteryDoctrineReadinessFilter(FilterBase):  # type: ignore[valid-type,misc]
    """Gate a Smart Group on being able to fly at least N fittings of a doctrine."""

    name = models.CharField(max_length=500, verbose_name=_("name"))
    description = models.CharField(max_length=500, verbose_name=_("description"))

    doctrine_map = models.ForeignKey(
        "mastery.DoctrineSkillSetGroupMap",
        on_delete=models.CASCADE,
        verbose_name=_("doctrine skill plan"),
        related_name="+",
    )
    minimum_fittings = models.PositiveSmallIntegerField(
        default=1,
        validators=[MinValueValidator(1)],
        verbose_name=_("minimum flyable fittings"),
        help_text=_("Number of fittings in this doctrine the pilot must be able to fly."),
    )
    approved_only = models.BooleanField(
        default=False,
        verbose_name=_("approved fittings only"),
        help_text=_(
            "If checked, only fittings with 'Approved' status are counted "
            "toward the minimum. Fittings in 'In progress' or 'Not approved' are skipped."
        ),
    )

    class Meta:
        verbose_name = _("Smart Filter: Mastery — Doctrine Readiness")
        verbose_name_plural = _("Smart Filter: Mastery — Doctrine Readiness")
        abstract = not _SECURE_GROUPS_AVAILABLE

    def __str__(self) -> str:
        return f"{self.name}: {self.description}"

    def _get_fitting_maps(self):
        """Return FittingSkillsetMap queryset for this doctrine (with optional approved filter)."""
        qs = self.doctrine_map.fittings.select_related("skillset", "fitting")
        if self.approved_only:
            from mastery.models import FittingSkillsetMap  # import-outside-toplevel
            qs = qs.filter(status=FittingSkillsetMap.ApprovalStatus.APPROVED)
        return list(qs)

    def _count_flyable(self, characters: list, fitting_maps: list) -> tuple[int, list[str]]:
        """
        Return ``(count_flyable, [fitting_names])`` for the given characters.

        Uses DB-direct check (no PilotProgressService) for performance.
        """
        flyable_count = 0
        flyable_names = []

        for fm in fitting_maps:
            can_fly_any = any(_can_fly_any(char, fm.skillset) for char in characters)
            if can_fly_any:
                flyable_count += 1
                try:
                    flyable_names.append(fm.fitting.name)
                except Exception:  # noqa: BLE001
                    flyable_names.append(str(fm.fitting_id))

        return flyable_count, flyable_names

    def process_filter(self, user: User) -> bool:
        characters = _get_memberaudit_characters(user)
        if not characters:
            return False

        fitting_maps = self._get_fitting_maps()
        if not fitting_maps:
            return False

        count, _ = self._count_flyable(characters, fitting_maps)
        return count >= self.minimum_fittings

    def audit_filter(self, users) -> dict:
        output: dict = defaultdict(lambda: {"check": False, "message": ""})
        fitting_maps = self._get_fitting_maps()
        total = len(fitting_maps)

        if not fitting_maps:
            for user in users:
                output[user.id] = {"check": False, "message": str(_("No fittings configured"))}
            return output

        user_chars = _user_to_characters_map(users)

        for user in users:
            characters = user_chars.get(user.id, [])
            if not characters:
                output[user.id] = {
                    "check": False,
                    "message": str(_("No registered characters")),
                }
                continue

            count, names = self._count_flyable(characters, fitting_maps)
            passed = count >= self.minimum_fittings

            if names:
                names_str = ", ".join(names[:5])
                if len(names) > 5:
                    names_str += f" (+{len(names) - 5})"
                message = f"{count}/{total}: {names_str}"
            else:
                message = f"0/{total}"

            output[user.id] = {"check": passed, "message": message}

        return output


# ──────────────────────────────────────────────────────────────────────────────
# Filter 4 – Fitting Elite (simplified)
# ──────────────────────────────────────────────────────────────────────────────

class MasteryFittingEliteFilter(FilterBase):  # type: ignore[valid-type,misc]
    """Gate a Smart Group on a pilot reaching the Elite bucket for a specific fitting.

    Equivalent to :class:`MasteryFittingStatusFilter` with ``minimum_status='elite'``,
    but with simpler admin configuration.
    """

    name = models.CharField(max_length=500, verbose_name=_("name"))
    description = models.CharField(max_length=500, verbose_name=_("description"))

    fitting_map = models.ForeignKey(
        "mastery.FittingSkillsetMap",
        on_delete=models.CASCADE,
        verbose_name=_("fitting skill plan"),
        related_name="+",
    )

    class Meta:
        verbose_name = _("Smart Filter: Mastery — Fitting Elite")
        verbose_name_plural = _("Smart Filter: Mastery — Fitting Elite")
        abstract = not _SECURE_GROUPS_AVAILABLE

    def __str__(self) -> str:
        return f"{self.name}: {self.description}"

    def process_filter(self, user: User) -> bool:
        characters = _get_memberaudit_characters(user)
        if not characters:
            return False

        try:
            skillset = self.fitting_map.skillset
        except Exception:  # noqa: BLE001
            return False

        for character in characters:
            progress = _build_progress(character, skillset)
            if not progress:
                continue
            if bucket_for_progress(progress) == BUCKET_ELITE:
                return True

        return False

    def audit_filter(self, users) -> dict:
        output: dict = defaultdict(lambda: {"check": False, "message": ""})
        try:
            skillset = self.fitting_map.skillset
        except Exception:  # noqa: BLE001
            return {u.id: {"check": False, "message": str(_("Fitting not configured"))} for u in users}

        user_chars = _user_to_characters_map(users)

        for user in users:
            characters = user_chars.get(user.id, [])
            if not characters:
                output[user.id] = {"check": False, "message": str(_("No registered characters"))}
                continue

            passed = False
            best_char = ""
            best_pct = 0.0
            for character in characters:
                progress = _build_progress(character, skillset)
                if not progress:
                    continue
                rec_pct = float(progress.get("recommended_pct") or 0)
                if bucket_for_progress(progress) == BUCKET_ELITE:
                    passed = True
                    best_char = _character_name(character)
                    best_pct = rec_pct
                    break
                if rec_pct > best_pct:
                    best_pct = rec_pct
                    best_char = _character_name(character)

            if passed:
                message = f"{best_char}: Elite ({best_pct:.1f}%)"
            elif best_char:
                message = f"{best_char}: {best_pct:.1f}% (not elite)"
            else:
                message = str(_("No data"))

            output[user.id] = {"check": passed, "message": message}

        return output
