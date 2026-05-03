"""Helpers for resolving Alpha clone-grade skill caps."""

from mastery.models import SdeCloneGradeSkill


class NullCloneGradeService:
    """Fallback resolver used when clone-grade lookups are disabled."""

    @staticmethod
    def get_alpha_caps(skill_type_ids: list[int] | set[int] | tuple[int, ...]) -> dict[int, int]:
        """Return no Alpha caps when clone-grade lookups are disabled."""
        del skill_type_ids
        return {}

    @staticmethod
    def get_alpha_max_level(skill_type_id: int) -> int:
        """Return zero so every positive target is treated as Omega-only."""
        del skill_type_id
        return 0

    @staticmethod
    def requires_omega(skill_type_id: int, target_level: int) -> bool:
        """Treat any positive target level as requiring Omega in null mode."""
        del skill_type_id
        normalized_target = max(0, int(target_level or 0))
        return normalized_target > 0


class CloneGradeService:
    """Resolve and cache Alpha max levels by skill type id."""

    def __init__(self):
        self._caps_cache: dict[int, int | None] = {}

    def get_alpha_caps(self, skill_type_ids: list[int] | set[int] | tuple[int, ...]) -> dict[int, int]:
        """Return persisted Alpha max levels for the requested skill ids."""
        normalized_ids = {int(skill_type_id) for skill_type_id in skill_type_ids if int(skill_type_id) > 0}
        if not normalized_ids:
            return {}

        missing_ids = [skill_type_id for skill_type_id in normalized_ids if skill_type_id not in self._caps_cache]
        if missing_ids:
            rows = SdeCloneGradeSkill.objects.filter(skill_type_id__in=missing_ids).values(
                "skill_type_id",
                "max_alpha_level",
            )
            found_ids = set()
            for row in rows:
                skill_type_id = int(row["skill_type_id"])
                self._caps_cache[skill_type_id] = int(row["max_alpha_level"])
                found_ids.add(skill_type_id)

            for skill_type_id in missing_ids:
                if skill_type_id not in found_ids:
                    self._caps_cache[skill_type_id] = None

        caps = {}
        for skill_type_id in normalized_ids:
            cap_value = self._caps_cache.get(skill_type_id)
            if cap_value is None:
                continue
            caps[skill_type_id] = int(cap_value)

        return caps

    def get_alpha_max_level(self, skill_type_id: int) -> int:
        """Return the persisted Alpha cap for one skill, or zero when absent."""
        normalized_id = int(skill_type_id)
        if normalized_id <= 0:
            return 0

        caps = self.get_alpha_caps([normalized_id])
        return int(caps.get(normalized_id, 0) or 0)

    def requires_omega(self, skill_type_id: int, target_level: int) -> bool:
        """Return whether the requested target level exceeds the Alpha cap."""
        normalized_target = max(0, int(target_level or 0))
        if normalized_target == 0:
            return False

        return normalized_target > self.get_alpha_max_level(skill_type_id)
