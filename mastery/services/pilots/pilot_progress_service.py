"""Builds skill-progress data for pilot characters against skillsets."""
# pylint: disable=too-many-lines
import math
from datetime import timedelta
import heapq

from django.core.exceptions import ObjectDoesNotExist

from eve_sde.models import ItemType
from eve_sde.models import TypeDogma


class PilotProgressService:
    """Compute pilot readiness, training plans and export payloads for skillsets."""
    EXPORT_MODE_REQUIRED = "required"
    EXPORT_MODE_RECOMMENDED = "recommended"
    LARGE_SKILL_INJECTOR_TYPE_ID = 40520

    DOGMA_SKILL_TIME_CONSTANT = 275
    DOGMA_PRIMARY_ATTRIBUTE = 180
    DOGMA_SECONDARY_ATTRIBUTE = 181

    ATTRIBUTE_MAP = {
        164: "charisma",
        165: "intelligence",
        166: "memory",
        167: "perception",
        168: "willpower",
    }
    ATTRIBUTE_DISPLAY = {
        "charisma": "Charisma",
        "intelligence": "Intelligence",
        "memory": "Memory",
        "perception": "Perception",
        "willpower": "Willpower",
    }
    ATTRIBUTE_ORDER = ("charisma", "intelligence", "memory", "perception", "willpower")
    REMAP_MIN_ATTRIBUTE = 17
    REMAP_MAX_PRIMARY = 27
    REMAP_MAX_SECONDARY = 21
    IMPLANT_BONUS_ATTRIBUTE_MAP = {
        175: "charisma",
        176: "intelligence",
        177: "memory",
        178: "perception",
        179: "willpower",
    }
    LARGE_SKILL_INJECTOR_BREAKPOINTS = (
        (5_000_000, 500_000),
        (50_000_000, 400_000),
        (80_000_000, 300_000),
        (None, 150_000),
    )

    ROMAN_LEVEL = {1: "I", 2: "II", 3: "III", 4: "IV", 5: "V"}
    REQUIRED_SKILL_ATTRIBUTES = [
        (182, 277),
        (183, 278),
        (184, 279),
        (1285, 1286),
        (1289, 1287),
        (1290, 1288),
    ]
    EXPORT_LANGUAGE_CHOICES = [
        ("en", "English"),
        ("fr", "French"),
        ("de", "German"),
        ("es", "Spanish"),
        ("it", "Italian"),
        ("nl", "Dutch"),
        ("pl", "Polish"),
        ("ru", "Russian"),
        ("uk", "Ukrainian"),
        ("ja", "Japanese"),
        ("ko", "Korean"),
        ("zh", "Chinese"),
    ]

    def __init__(self):
        self._prereq_cache: dict[int, list[tuple[int, int]]] = {}
        self._skill_name_cache: dict[tuple[str, int], str] = {}

    @staticmethod
    def _safe_related(instance, attr_name: str):
        try:
            return getattr(instance, attr_name)
        except (AttributeError, ObjectDoesNotExist):
            return None

    @staticmethod
    def _as_int(value, default: int = 0) -> int:
        try:
            if value is None:
                return default
            return int(value)
        except (TypeError, ValueError):
            return default

    def _load_skill_dogma(self, skill_type_ids: list[int]) -> dict[int, dict[str, object | None]]:
        dogma_map: dict[int, dict[str, object | None]] = {
            skill_type_id: {
                "rank": 1,
                "primary_attribute": None,
                "secondary_attribute": None,
            }
            for skill_type_id in skill_type_ids
        }
        rows = TypeDogma.objects.filter(
            item_type_id__in=skill_type_ids,
            dogma_attribute_id__in=[
                self.DOGMA_SKILL_TIME_CONSTANT,
                self.DOGMA_PRIMARY_ATTRIBUTE,
                self.DOGMA_SECONDARY_ATTRIBUTE,
            ],
        ).values("item_type_id", "dogma_attribute_id", "value")

        for row in rows:
            skill_type_id = row["item_type_id"]
            attribute_id = row["dogma_attribute_id"]
            value = int(row["value"])
            if attribute_id == self.DOGMA_SKILL_TIME_CONSTANT:
                dogma_map[skill_type_id]["rank"] = max(1, value)
            elif attribute_id == self.DOGMA_PRIMARY_ATTRIBUTE:
                dogma_map[skill_type_id]["primary_attribute"] = self.ATTRIBUTE_MAP.get(value)
            elif attribute_id == self.DOGMA_SECONDARY_ATTRIBUTE:
                dogma_map[skill_type_id]["secondary_attribute"] = self.ATTRIBUTE_MAP.get(value)

        return dogma_map

    @staticmethod
    def _get_cache_bucket(cache_context: dict | None, bucket_name: str) -> dict | None:
        if cache_context is None:
            return None
        return cache_context.setdefault(bucket_name, {})

    def _load_skillset_skills(self, skillset, cache_context: dict | None = None) -> list:
        bucket = self._get_cache_bucket(cache_context, "skillset_skills")
        cache_key = getattr(skillset, "id", None)
        if bucket is not None and cache_key in bucket:
            return bucket[cache_key]

        skills = list(skillset.skills.select_related("eve_type").all())
        skills.sort(
            key=lambda obj: (
                (getattr(getattr(obj, "eve_type", None), "name", None) or "").lower(),
                obj.eve_type_id,
            )
        )

        if bucket is not None:
            bucket[cache_key] = skills

        return skills

    def _load_character_skill_map(self, character, cache_context: dict | None = None) -> dict[int, object]:
        if not character:
            return {}

        bucket = self._get_cache_bucket(cache_context, "character_skills")
        cache_key = getattr(character, "id", None)
        if bucket is not None and cache_key in bucket:
            return bucket[cache_key]

        skill_map = {
            obj.eve_type_id: obj
            for obj in character.skills.select_related("eve_type").all()
        }

        if bucket is not None:
            bucket[cache_key] = skill_map

        return skill_map

    def _load_skill_dogma_cached(
        self,
        skill_type_ids: list[int],
        cache_context: dict | None = None,
    ) -> dict[int, dict[str, object | None]]:
        normalized_ids = tuple(sorted({int(skill_type_id) for skill_type_id in skill_type_ids if skill_type_id}))
        if not normalized_ids:
            return {}

        bucket = self._get_cache_bucket(cache_context, "skill_dogma")
        if bucket is not None and normalized_ids in bucket:
            return bucket[normalized_ids]

        dogma_map = self._load_skill_dogma(list(normalized_ids))
        if bucket is not None:
            bucket[normalized_ids] = dogma_map

        return dogma_map

    @staticmethod
    def _sp_for_level(rank: int, level: int) -> int:
        if level <= 0:
            return 0
        return int(math.ceil(250 * rank * (2 ** (2.5 * (level - 1)))))

    @staticmethod
    def _skillpoints_per_hour(primary_value: int, secondary_value: int) -> int:
        return (int(primary_value) * 60) + (int(secondary_value) * 30)

    @classmethod
    def _empty_attribute_map(cls, default: int = 0) -> dict[str, int]:
        return {attribute_name: int(default) for attribute_name in cls.ATTRIBUTE_ORDER}

    def _resolve_implant_bonus_map(self, character) -> tuple[dict[str, int], bool]:
        bonus_by_attribute = self._empty_attribute_map(default=0)
        if not character:
            return bonus_by_attribute, False

        implants_qs = getattr(character, "implants", None)
        if implants_qs is None:
            return bonus_by_attribute, False

        has_implant_data = False
        for implant in implants_qs.select_related("eve_type").prefetch_related("eve_type__dogma_attributes"):
            implant_type = getattr(implant, "eve_type", None)
            if implant_type is None:
                continue

            dogma_rows = getattr(implant_type, "dogma_attributes", None)
            if dogma_rows is None:
                continue

            has_implant_data = True
            for dogma_obj in dogma_rows.all():
                attribute_name = self.IMPLANT_BONUS_ATTRIBUTE_MAP.get(
                    self._as_int(getattr(dogma_obj, "eve_dogma_attribute_id", 0))
                )
                if not attribute_name:
                    continue

                bonus_value = self._as_int(getattr(dogma_obj, "value", 0))
                if bonus_value > 0:
                    bonus_by_attribute[attribute_name] += bonus_value

        return bonus_by_attribute, has_implant_data

    @classmethod
    def _attribute_label(cls, attribute_name: str | None) -> str:
        if not attribute_name:
            return "Unknown"
        return cls.ATTRIBUTE_DISPLAY.get(attribute_name, attribute_name.replace("_", " ").title())

    @classmethod
    def large_skill_injector_gain(cls, total_sp: int) -> int:
        """Return gained SP for one large injector at a given total SP bracket."""
        total_sp = max(0, int(total_sp or 0))

        for cap, gain in cls.LARGE_SKILL_INJECTOR_BREAKPOINTS:
            if cap is None or total_sp < cap:
                return gain

        return cls.LARGE_SKILL_INJECTOR_BREAKPOINTS[-1][1]

    @classmethod
    def estimate_large_skill_injectors(cls, required_sp: int, current_total_sp: int | None) -> dict:
        """Estimate injector count and resulting SP totals for a required SP amount."""
        remaining_sp = max(0, int(required_sp or 0))
        if current_total_sp is None:
            return {
                "known": False,
                "count": None,
                "required_sp": remaining_sp,
                "gained_sp": 0,
                "final_total_sp": None,
            }

        total_sp = max(0, int(current_total_sp or 0))
        if remaining_sp == 0:
            return {
                "known": True,
                "count": 0,
                "required_sp": 0,
                "gained_sp": 0,
                "final_total_sp": total_sp,
            }

        count = 0
        gained_sp = 0

        while remaining_sp > 0:
            gain = cls.large_skill_injector_gain(total_sp)
            remaining_sp -= gain
            gained_sp += gain
            total_sp += gain
            count += 1

        return {
            "known": True,
            "count": count,
            "required_sp": max(0, int(required_sp or 0)),
            "gained_sp": gained_sp,
            "final_total_sp": total_sp,
        }

    def build_optimal_remap(self, plan_rows: list[dict], current_attributes=None, character=None) -> dict | None:
        """Compute a simple best remap recommendation for the given training plan rows."""
        eligible_rows = [
            row
            for row in plan_rows
            if int(row.get("missing_sp") or 0) > 0
            and row.get("primary_attribute")
            and row.get("secondary_attribute")
        ]
        if not eligible_rows:
            return None

        implant_bonus_map, has_implant_data = self._resolve_implant_bonus_map(character)

        def _effective_map(base_attribute_map: dict[str, int]) -> dict[str, int]:
            return {
                attribute_name: (
                    int(base_attribute_map.get(attribute_name, 0))
                    + int(implant_bonus_map.get(attribute_name, 0))
                )
                for attribute_name in self.ATTRIBUTE_ORDER
            }

        def _estimate_seconds(attribute_map: dict[str, int]) -> float:
            total_seconds = 0.0
            for row in eligible_rows:
                primary_value = attribute_map.get(row["primary_attribute"])
                secondary_value = attribute_map.get(row["secondary_attribute"])
                if primary_value is None or secondary_value is None:
                    return float("inf")

                skillpoints_per_hour = self._skillpoints_per_hour(primary_value, secondary_value)
                if skillpoints_per_hour <= 0:
                    return float("inf")

                total_seconds += (int(row["missing_sp"]) / skillpoints_per_hour) * 3600

            return total_seconds

        best_primary = None
        best_secondary = None
        best_map = None
        best_seconds = None

        for primary_attribute in self.ATTRIBUTE_ORDER:
            for secondary_attribute in self.ATTRIBUTE_ORDER:
                if primary_attribute == secondary_attribute:
                    continue

                attribute_map = {
                    attribute_name: self.REMAP_MIN_ATTRIBUTE
                    for attribute_name in self.ATTRIBUTE_ORDER
                }
                attribute_map[primary_attribute] = self.REMAP_MAX_PRIMARY
                attribute_map[secondary_attribute] = self.REMAP_MAX_SECONDARY

                total_seconds = _estimate_seconds(_effective_map(attribute_map))
                if best_seconds is None or total_seconds < best_seconds:
                    best_seconds = total_seconds
                    best_primary = primary_attribute
                    best_secondary = secondary_attribute
                    best_map = attribute_map

        current_seconds = None
        current_map = None
        current_base_map = None
        if current_attributes is not None:
            current_map = {}
            for attribute_name in self.ATTRIBUTE_ORDER:
                value = getattr(current_attributes, attribute_name, None)
                if value is None:
                    current_map = None
                    break
                current_map[attribute_name] = self._as_int(value)

            if current_map is not None:
                current_base_map = {
                    attribute_name: max(0, current_map[attribute_name] - implant_bonus_map[attribute_name])
                    for attribute_name in self.ATTRIBUTE_ORDER
                }
                current_seconds = _estimate_seconds(current_map)
                if math.isinf(current_seconds):
                    current_seconds = None

        best_seconds_int = 0 if best_seconds is None or math.isinf(best_seconds) else int(best_seconds)
        current_seconds_int = None if current_seconds is None else int(current_seconds)

        return {
            "primary_attribute": best_primary,
            "primary_label": self._attribute_label(best_primary),
            "secondary_attribute": best_secondary,
            "secondary_label": self._attribute_label(best_secondary),
            "attributes": [
                {
                    "name": attribute_name,
                    "label": self._attribute_label(attribute_name),
                    "value": best_map[attribute_name],
                    "base_value": best_map[attribute_name],
                    "implant_bonus": implant_bonus_map[attribute_name],
                    "effective_value": best_map[attribute_name] + implant_bonus_map[attribute_name],
                    "is_primary": attribute_name == best_primary,
                    "is_secondary": attribute_name == best_secondary,
                }
                for attribute_name in self.ATTRIBUTE_ORDER
            ],
            "current_attributes_rows": [] if current_map is None else [
                {
                    "name": attribute_name,
                    "label": self._attribute_label(attribute_name),
                    "value": current_map[attribute_name],
                    "base_value": current_base_map[attribute_name],
                    "implant_bonus": implant_bonus_map[attribute_name],
                    "effective_value": current_map[attribute_name],
                }
                for attribute_name in self.ATTRIBUTE_ORDER
            ],
            "implant_bonus_rows": [
                {
                    "name": attribute_name,
                    "label": self._attribute_label(attribute_name),
                    "value": implant_bonus_map[attribute_name],
                }
                for attribute_name in self.ATTRIBUTE_ORDER
                if implant_bonus_map[attribute_name] > 0
            ],
            "has_implant_bonus": any(value > 0 for value in implant_bonus_map.values()),
            "has_implant_data": has_implant_data,
            "estimated_time": timedelta(seconds=best_seconds_int),
            "current_time": (
                None if current_seconds_int is None
                else timedelta(seconds=current_seconds_int)
            ),
            "time_saved": (
                None if current_seconds_int is None
                else timedelta(seconds=max(0, current_seconds_int - best_seconds_int))
            ),
            "current_attributes": current_map,
        }

    def _estimate_missing(self, character, target_rows: list[dict[str, object]],
                          dogma_map: dict[int, dict[str, object | None]]) -> tuple[int, timedelta | None]:
        total_missing_sp = 0
        total_seconds = 0.0
        can_estimate_time = hasattr(character, "attributes")

        for row in target_rows:
            skill_type_id = self._as_int(row.get("skill_type_id", 0))
            target_level = self._as_int(row.get("target_level", 0))
            current_level = self._as_int(row.get("current_level", 0))
            current_sp = self._as_int(row.get("current_sp", 0))

            dogma = dogma_map.get(
                skill_type_id,
                {"rank": 1, "primary_attribute": None, "secondary_attribute": None},
            )
            rank = self._as_int(dogma.get("rank"), default=1)

            target_sp = self._sp_for_level(rank, target_level)
            current_level_sp = self._sp_for_level(rank, current_level)
            baseline_current_sp = max(current_sp, current_level_sp)
            missing_sp = max(0, target_sp - baseline_current_sp)
            row["missing_sp"] = missing_sp
            total_missing_sp += missing_sp

            if not can_estimate_time or missing_sp == 0:
                continue

            primary_attr_name = dogma.get("primary_attribute")
            secondary_attr_name = dogma.get("secondary_attribute")
            if not primary_attr_name or not secondary_attr_name:
                can_estimate_time = False
                continue

            primary_value_raw = getattr(character.attributes, str(primary_attr_name), None)
            secondary_value_raw = getattr(character.attributes, str(secondary_attr_name), None)
            if primary_value_raw is None or secondary_value_raw is None:
                can_estimate_time = False
                continue

            primary_value = self._as_int(primary_value_raw)
            secondary_value = self._as_int(secondary_value_raw)

            skillpoints_per_hour = (primary_value * 60) + (secondary_value * 30)
            if skillpoints_per_hour <= 0:
                can_estimate_time = False
                continue

            total_seconds += (missing_sp / skillpoints_per_hour) * 3600

        missing_time = timedelta(seconds=int(total_seconds)) if can_estimate_time else None
        return total_missing_sp, missing_time

    @staticmethod
    def _roman(level: int) -> str:
        return PilotProgressService.ROMAN_LEVEL.get(level, str(level))

    def _source_rows_for_mode(self, progress: dict, mode: str) -> list[dict]:
        mode = mode or self.EXPORT_MODE_RECOMMENDED
        if mode == self.EXPORT_MODE_REQUIRED:
            return list(progress.get("missing_required", []))
        return list(progress.get("missing_recommended", []))

    def _load_skill_prerequisites(self, skill_type_ids: list[int]) -> dict[int, list[tuple[int, int]]]:
        missing_ids = [skill_id for skill_id in skill_type_ids if skill_id not in self._prereq_cache]
        if missing_ids:
            skill_attr_ids = [skill_attr for skill_attr, _ in self.REQUIRED_SKILL_ATTRIBUTES]
            level_attr_ids = [level_attr for _, level_attr in self.REQUIRED_SKILL_ATTRIBUTES]
            rows = TypeDogma.objects.filter(
                item_type_id__in=missing_ids,
                dogma_attribute_id__in=skill_attr_ids + level_attr_ids,
            ).values("item_type_id", "dogma_attribute_id", "value")

            per_skill = {
                skill_id: {
                    idx: {"skill": 0, "level": 0}
                    for idx in range(len(self.REQUIRED_SKILL_ATTRIBUTES))
                }
                for skill_id in missing_ids
            }

            for row in rows:
                skill_id = int(row["item_type_id"])
                attr_id = int(row["dogma_attribute_id"])
                value = int(row["value"])
                if attr_id in skill_attr_ids:
                    idx = skill_attr_ids.index(attr_id)
                    per_skill[skill_id][idx]["skill"] = value
                elif attr_id in level_attr_ids:
                    idx = level_attr_ids.index(attr_id)
                    per_skill[skill_id][idx]["level"] = max(per_skill[skill_id][idx]["level"], value)

            for skill_id in missing_ids:
                prereqs = []
                for row in per_skill[skill_id].values():
                    if row["skill"] and row["level"]:
                        prereqs.append((int(row["skill"]), int(row["level"])))
                self._prereq_cache[skill_id] = prereqs

        return {skill_id: self._prereq_cache.get(skill_id, []) for skill_id in skill_type_ids}

    def _load_skill_names(self, skill_type_ids: list[int], language: str = "en") -> dict[int, str]:
        language = self.normalize_export_language(language)

        def _cache_key(skill_id: int) -> tuple[str, int]:
            return language, skill_id

        missing_ids = [
            skill_id
            for skill_id in skill_type_ids
            if _cache_key(skill_id) not in self._skill_name_cache
        ]
        if missing_ids:
            name_field = self._resolve_itemtype_name_field(language)
            for item_type in ItemType.objects.filter(id__in=missing_ids).only(
                "id", name_field, "name_en", "name"
            ):
                name_value = (
                    getattr(item_type, name_field, None)
                    or getattr(item_type, "name_en", None)
                    or getattr(item_type, "name", None)
                )
                self._skill_name_cache[_cache_key(item_type.id)] = name_value or f"Skill {item_type.id}"
            for skill_id in missing_ids:
                self._skill_name_cache.setdefault(_cache_key(skill_id), f"Skill {skill_id}")

        return {
            skill_id: self._skill_name_cache.get(_cache_key(skill_id), f"Skill {skill_id}")
            for skill_id in skill_type_ids
        }

    def _load_character_skills(
        self,
        character,
        skill_type_ids: list[int],
        cache_context: dict | None = None,
    ) -> dict[int, object]:
        if not character:
            return {}
        character_skills = self._load_character_skill_map(character, cache_context=cache_context)
        return {
            skill_type_id: character_skills[skill_type_id]
            for skill_type_id in skill_type_ids
            if skill_type_id in character_skills
        }

    def _load_current_levels(
        self,
        character,
        skill_type_ids: list[int],
        cache_context: dict | None = None,
    ) -> dict[int, int]:
        if not character:
            return {}
        character_skills = self._load_character_skill_map(character, cache_context=cache_context)
        levels = {
            skill_type_id: character_skills[skill_type_id].active_skill_level
            for skill_type_id in skill_type_ids
            if skill_type_id in character_skills
        }
        for skill_id in skill_type_ids:
            levels.setdefault(skill_id, 0)
        return levels

    @classmethod
    def export_mode_choices(cls) -> list[tuple[str, str]]:
        """Return available export modes for plan generation."""
        return [
            (cls.EXPORT_MODE_REQUIRED, "Required"),
            (cls.EXPORT_MODE_RECOMMENDED, "Recommended"),
        ]

    @classmethod
    def export_language_choices(cls) -> list[tuple[str, str]]:
        """Return supported localization languages for skill-name exports."""
        return list(cls.EXPORT_LANGUAGE_CHOICES)

    @classmethod
    def normalize_export_language(cls, raw_language: str) -> str:
        """Normalize user-provided language code and fallback to English."""
        if not raw_language:
            return "en"
        normalized = raw_language.strip().lower().replace("_", "-").split("-", 1)[0]
        valid = {code for code, _label in cls.EXPORT_LANGUAGE_CHOICES}
        if normalized in valid:
            return normalized
        return "en"

    @staticmethod
    def _resolve_itemtype_name_field(language: str) -> str:
        # eve_sde field names can be locale-specific (e.g. name_fr_fr, name_ko_kr, name_zh_hans).
        language_field_candidates = {
            "en": ("name_en",),
            "fr": ("name_fr", "name_fr_fr"),
            "de": ("name_de",),
            "es": ("name_es",),
            "it": ("name_it", "name_it_it"),
            "nl": ("name_nl", "name_nl_nl"),
            "pl": ("name_pl", "name_pl_pl"),
            "ru": ("name_ru",),
            "uk": ("name_uk",),
            "ja": ("name_ja",),
            "ko": ("name_ko", "name_ko_kr"),
            "zh": ("name_zh", "name_zh_hans"),
        }

        candidates = list(language_field_candidates.get(language, (f"name_{language}",)))
        candidates.append(f"name_{language}")

        for candidate in candidates:
            try:
                ItemType._meta.get_field(candidate)  # pylint: disable=protected-access
                return candidate
            except Exception:  # pylint: disable=broad-exception-caught  # FieldDoesNotExist or AttributeError
                continue

        for fallback in ("name_en", "name"):
            try:
                ItemType._meta.get_field(fallback)  # pylint: disable=protected-access
                return fallback
            except Exception:  # pylint: disable=broad-exception-caught
                continue

        return "name"

    @staticmethod
    def _status_meta(can_fly: bool, recommended_pct: float, required_pct: float) -> tuple[str, str]:
        if can_fly and recommended_pct == 100:
            return "Elite ready", "success"
        if can_fly:
            return "Flyable", "info"
        if required_pct >= 75:
            return "Almost ready", "warning"
        return "Training needed", "danger"

    def _collect_plan_targets(
        self, source: list[dict]
    ) -> tuple[dict[int, int], dict[int, int], dict[int, int]]:
        target_by_skill: dict[int, int] = {}
        current_levels: dict[int, int] = {}
        current_skillpoints: dict[int, int] = {}

        for row in source:
            skill_id = self._as_int(row["skill_type_id"])
            target_level = self._as_int(row["target_level"])
            current_level = self._as_int(row.get("current_level", 0))
            current_sp = self._as_int(row.get("current_sp", 0))

            target_by_skill[skill_id] = max(target_by_skill.get(skill_id, 0), target_level)
            current_levels[skill_id] = max(current_levels.get(skill_id, 0), current_level)
            current_skillpoints[skill_id] = max(current_skillpoints.get(skill_id, 0), current_sp)

        return target_by_skill, current_levels, current_skillpoints

    def _expand_prerequisite_targets(self, target_by_skill: dict[int, int]) -> None:
        queue = list(target_by_skill.keys())
        visited = set()

        while queue:
            skill_id = queue.pop()
            if skill_id in visited:
                continue
            visited.add(skill_id)

            prereq_map = self._load_skill_prerequisites([skill_id])
            for prereq_skill_id, prereq_level in prereq_map.get(skill_id, []):
                if target_by_skill.get(prereq_skill_id, 0) < prereq_level:
                    target_by_skill[prereq_skill_id] = prereq_level
                    queue.append(prereq_skill_id)

    def _merge_character_progress(
        self,
        target_by_skill: dict[int, int],
        current_levels: dict[int, int],
        current_skillpoints: dict[int, int],
        character,
    ) -> None:
        character_skills = self._load_character_skills(
            character=character,
            skill_type_ids=list(target_by_skill.keys()),
        )
        for skill_id in target_by_skill:
            current_skill = character_skills.get(skill_id)
            current_levels.setdefault(
                skill_id,
                0 if current_skill is None else self._as_int(getattr(current_skill, "active_skill_level", 0)),
            )
            current_skillpoints.setdefault(
                skill_id,
                0 if current_skill is None else self._as_int(getattr(current_skill, "skillpoints_in_skill", 0)),
            )

    @staticmethod
    def _build_missing_nodes(
        target_by_skill: dict[int, int],
        current_levels: dict[int, int],
    ) -> tuple[set[tuple[int, int]], dict[int, int]]:
        nodes: set[tuple[int, int]] = set()
        first_missing_level: dict[int, int] = {}

        for skill_id, target_level in target_by_skill.items():
            current_level = int(current_levels.get(skill_id, 0))
            if current_level >= target_level:
                continue

            first_missing_level[skill_id] = current_level + 1
            for level in range(current_level + 1, target_level + 1):
                nodes.add((skill_id, level))

        return nodes, first_missing_level

    def _build_plan_graph(
        self,
        nodes: set[tuple[int, int]],
        target_by_skill: dict[int, int],
        current_levels: dict[int, int],
        first_missing_level: dict[int, int],
    ) -> tuple[dict[tuple[int, int], set[tuple[int, int]]], dict[tuple[int, int], int]]:
        adjacency: dict[tuple[int, int], set[tuple[int, int]]] = {node: set() for node in nodes}
        indegree: dict[tuple[int, int], int] = {node: 0 for node in nodes}

        for skill_id, target_level in target_by_skill.items():
            current_level = int(current_levels.get(skill_id, 0))
            for level in range(current_level + 2, target_level + 1):
                src = (skill_id, level - 1)
                dst = (skill_id, level)
                if src in adjacency and dst in adjacency and dst not in adjacency[src]:
                    adjacency[src].add(dst)
                    indegree[dst] += 1

        prereq_all = self._load_skill_prerequisites(list(target_by_skill.keys()))
        for skill_id, prereqs in prereq_all.items():
            start_level = first_missing_level.get(skill_id)
            if start_level is None:
                continue

            dst = (self._as_int(skill_id), self._as_int(start_level))
            if dst not in adjacency:
                continue

            for prereq_skill_id, prereq_level in prereqs:
                src = (self._as_int(prereq_skill_id), self._as_int(prereq_level))
                if src in adjacency and dst not in adjacency[src]:
                    adjacency[src].add(dst)
                    indegree[dst] += 1

        return adjacency, indegree

    @staticmethod
    def _order_plan_nodes(
        nodes: set[tuple[int, int]],
        adjacency: dict[tuple[int, int], set[tuple[int, int]]],
        indegree: dict[tuple[int, int], int],
        skill_names: dict[int, str],
    ) -> list[tuple[int, int]]:
        heap: list[tuple[int, str, int, tuple[int, int]]] = []
        for node, degree in indegree.items():
            if degree == 0:
                skill_id, level = node
                heapq.heappush(
                    heap,
                    (level, skill_names.get(skill_id, f"Skill {skill_id}").lower(), skill_id, node),
                )

        ordered_nodes: list[tuple[int, int]] = []
        while heap:
            _level, _name, _skill_id, node = heapq.heappop(heap)
            ordered_nodes.append(node)
            for nxt in adjacency[node]:
                indegree[nxt] -= 1
                if indegree[nxt] == 0:
                    nxt_skill_id, nxt_level = nxt
                    heapq.heappush(
                        heap,
                        (
                            nxt_level,
                            skill_names.get(nxt_skill_id, f"Skill {nxt_skill_id}").lower(),
                            nxt_skill_id,
                            nxt,
                        ),
                    )

        if len(ordered_nodes) != len(nodes):
            remaining = [node for node in nodes if node not in set(ordered_nodes)]
            remaining.sort(key=lambda n: (n[1], skill_names.get(n[0], f"Skill {n[0]}").lower(), n[0]))
            ordered_nodes.extend(remaining)

        return ordered_nodes

    def _build_plan_row(
        self,
        skill_id: int,
        level: int,
        skill_names: dict[int, str],
        dogma_map: dict[int, dict[str, object | None]],
        current_levels: dict[int, int],
        current_skillpoints: dict[int, int],
    ) -> dict:
        dogma = dogma_map.get(
            skill_id,
            {"rank": 1, "primary_attribute": None, "secondary_attribute": None},
        )
        rank = self._as_int(dogma.get("rank"), default=1)
        current_level = self._as_int(current_levels.get(skill_id, 0))
        current_sp = self._as_int(current_skillpoints.get(skill_id, 0))
        primary_attribute = (
            None if dogma.get("primary_attribute") is None
            else str(dogma.get("primary_attribute"))
        )
        secondary_attribute = (
            None if dogma.get("secondary_attribute") is None
            else str(dogma.get("secondary_attribute"))
        )

        if level == current_level + 1:
            previous_level = current_level
            baseline_current_sp = max(current_sp, self._sp_for_level(rank, previous_level))
        else:
            previous_level = level - 1
            baseline_current_sp = self._sp_for_level(rank, previous_level)

        target_sp = self._sp_for_level(rank, level)
        missing_sp = max(0, target_sp - baseline_current_sp)

        return {
            "skill_type_id": skill_id,
            "skill_name": skill_names.get(skill_id, f"Skill {skill_id}"),
            "target_level": level,
            "current_level": previous_level,
            "current_sp": baseline_current_sp,
            "target_sp": target_sp,
            "missing_sp": missing_sp,
            "rank": rank,
            "primary_attribute": primary_attribute,
            "secondary_attribute": secondary_attribute,
            "primary_label": self._attribute_label(primary_attribute),
            "secondary_label": self._attribute_label(secondary_attribute),
            "line": f"{skill_names.get(skill_id, f'Skill {skill_id}')} {self._roman(level)}",
        }

    def _build_training_plan_rows(
        self, progress: dict, mode: str, character=None, language: str = "en"
    ) -> list[dict]:
        mode = mode or self.EXPORT_MODE_RECOMMENDED
        language = self.normalize_export_language(language)
        source = self._source_rows_for_mode(progress, mode)

        if not source:
            return []

        target_by_skill, current_levels, current_skillpoints = self._collect_plan_targets(source)
        self._expand_prerequisite_targets(target_by_skill)
        self._merge_character_progress(
            target_by_skill=target_by_skill,
            current_levels=current_levels,
            current_skillpoints=current_skillpoints,
            character=character,
        )
        nodes, first_missing_level = self._build_missing_nodes(target_by_skill, current_levels)

        if not nodes:
            return []

        adjacency, indegree = self._build_plan_graph(
            nodes=nodes,
            target_by_skill=target_by_skill,
            current_levels=current_levels,
            first_missing_level=first_missing_level,
        )

        dogma_map = self._load_skill_dogma(list(target_by_skill.keys()))
        skill_names = self._load_skill_names(list(target_by_skill.keys()), language=language)
        ordered_nodes = self._order_plan_nodes(
            nodes=nodes,
            adjacency=adjacency,
            indegree=indegree,
            skill_names=skill_names,
        )

        plan_rows = []
        for skill_id, level in ordered_nodes:
            plan_rows.append(
                self._build_plan_row(
                    skill_id=skill_id,
                    level=level,
                    skill_names=skill_names,
                    dogma_map=dogma_map,
                    current_levels=current_levels,
                    current_skillpoints=current_skillpoints,
                )
            )

        return plan_rows

    def build_export_lines(self, progress: dict, mode: str, character=None, language: str = "en") -> list[str]:
        """Build plain-text training lines for a given export mode."""
        return [
            row["line"]
            for row in self._build_training_plan_rows(
                progress=progress,
                mode=mode,
                character=character,
                language=language,
            )
        ]

    def build_skill_plan_summary(self, progress: dict, mode: str, character=None, language: str = "en") -> dict:
        """Build aggregate summary metadata for UI/API skill plan display."""
        plan_rows = self._build_training_plan_rows(
            progress=progress,
            mode=mode,
            character=character,
            language=language,
        )
        total_missing_sp = int(sum(int(row.get("missing_sp") or 0) for row in plan_rows))

        skillpoints_obj = self._safe_related(character, "skillpoints") if character else None
        current_total_sp = None if skillpoints_obj is None else int(skillpoints_obj.total or 0)
        current_unallocated_sp = None if skillpoints_obj is None else int(skillpoints_obj.unallocated or 0)
        usable_unallocated_sp = 0 if current_unallocated_sp is None else current_unallocated_sp
        remaining_sp_after_unallocated = max(0, total_missing_sp - usable_unallocated_sp)

        attributes_obj = self._safe_related(character, "attributes") if character else None
        optimal_remap = self.build_optimal_remap(
            plan_rows,
            current_attributes=attributes_obj,
            character=character,
        )
        injector_estimate = self.estimate_large_skill_injectors(
            remaining_sp_after_unallocated,
            current_total_sp,
        )
        injector_gain_now = None if current_total_sp is None else self.large_skill_injector_gain(current_total_sp)
        injector_overage_sp = max(0, int(injector_estimate.get("gained_sp") or 0) - remaining_sp_after_unallocated)

        return {
            "plan_rows": plan_rows,
            "line_count": len(plan_rows),
            "unique_skill_count": len({row["skill_type_id"] for row in plan_rows}),
            "total_missing_sp": total_missing_sp,
            "current_total_sp": current_total_sp,
            "current_unallocated_sp": current_unallocated_sp,
            "remaining_sp_after_unallocated": remaining_sp_after_unallocated,
            "optimal_remap": optimal_remap,
            "injector_estimate": {
                **injector_estimate,
                "large_skill_injector_type_id": self.LARGE_SKILL_INJECTOR_TYPE_ID,
                "current_gain_per_injector": injector_gain_now,
                "overage_sp": injector_overage_sp,
            },
        }

    def localize_missing_rows(self, rows: list[dict], language: str) -> list[dict]:
        """Return missing skill rows with skill_name localized for the given language."""
        language = self.normalize_export_language(language)
        if not rows:
            return []

        skill_ids = [int(row["skill_type_id"]) for row in rows if row.get("skill_type_id")]
        names = self._load_skill_names(skill_ids, language=language)

        localized = []
        for row in rows:
            skill_id = int(row.get("skill_type_id", 0))
            row_copy = dict(row)
            if skill_id:
                row_copy["skill_name"] = names.get(skill_id, row_copy.get("skill_name", f"Skill {skill_id}"))
            localized.append(row_copy)
        return localized

    def build_for_character(
        self,
        character,
        skillset,
        include_export_lines: bool = True,
        cache_context: dict | None = None,
    ):
        """Build required/recommended progress snapshot for one character and skillset."""
        skills = self._load_skillset_skills(skillset, cache_context=cache_context)
        skill_type_ids = [obj.eve_type_id for obj in skills]
        skill_dogma_map = self._load_skill_dogma_cached(skill_type_ids, cache_context=cache_context)

        character_skills = self._load_character_skills(
            character,
            skill_type_ids,
            cache_context=cache_context,
        )

        missing_required = []
        missing_recommended = []
        total_required = 0
        total_recommended = 0

        for skill in skills:
            current = character_skills.get(skill.eve_type_id)
            current_level = 0 if current is None else self._as_int(getattr(current, "active_skill_level", 0))
            current_sp = 0 if current is None else self._as_int(getattr(current, "skillpoints_in_skill", 0))

            if skill.required_level:
                total_required += 1
                if current_level < skill.required_level:
                    missing_required.append(
                        {
                            "skill_type_id": skill.eve_type_id,
                            "skill_name": skill.eve_type.name,
                            "current_level": current_level,
                            "target_level": skill.required_level,
                            "current_sp": current_sp,
                        }
                    )

            if skill.recommended_level:
                total_recommended += 1
                if current_level < skill.recommended_level:
                    missing_recommended.append(
                        {
                            "skill_type_id": skill.eve_type_id,
                            "skill_name": skill.eve_type.name,
                            "current_level": current_level,
                            "target_level": skill.recommended_level,
                            "current_sp": current_sp,
                        }
                    )

        required_pct = 100 if total_required == 0 else round((1 - (len(missing_required) / total_required)) * 100, 2)
        recommended_pct = 100 if total_recommended == 0 else round(
            (1 - (len(missing_recommended) / total_recommended)) * 100, 2)

        required_dogma_map = {
            skill_type_id: skill_dogma_map[skill_type_id]
            for skill_type_id in [obj["skill_type_id"] for obj in missing_required]
            if skill_type_id in skill_dogma_map
        }
        required_missing_sp, required_missing_time = self._estimate_missing(character, missing_required,
                                                                            required_dogma_map)

        recommended_dogma_map = {
            skill_type_id: skill_dogma_map[skill_type_id]
            for skill_type_id in [obj["skill_type_id"] for obj in missing_recommended]
            if skill_type_id in skill_dogma_map
        }
        recommended_missing_sp, recommended_missing_time = self._estimate_missing(character, missing_recommended,
                                                                                  recommended_dogma_map)

        can_fly = len(missing_required) == 0
        status_label, status_class = self._status_meta(can_fly, recommended_pct, required_pct)

        progress = {
            "can_fly": can_fly,
            "required_pct": required_pct,
            "recommended_pct": recommended_pct,
            "status_label": status_label,
            "status_class": status_class,
            "missing_required": sorted(missing_required, key=lambda x: x["skill_name"].lower()),
            "missing_recommended": sorted(missing_recommended, key=lambda x: x["skill_name"].lower()),
            "missing_required_count": len(missing_required),
            "missing_recommended_count": len(missing_recommended),
            # Backward-compatible summary values default to recommended mode.
            "total_missing_sp": recommended_missing_sp,
            "total_missing_time": recommended_missing_time,
            "mode_stats": {
                self.EXPORT_MODE_REQUIRED: {
                    "coverage_pct": required_pct,
                    "missing_count": len(missing_required),
                    "total_missing_sp": required_missing_sp,
                    "total_missing_time": required_missing_time,
                },
                self.EXPORT_MODE_RECOMMENDED: {
                    "coverage_pct": recommended_pct,
                    "missing_count": len(missing_recommended),
                    "total_missing_sp": recommended_missing_sp,
                    "total_missing_time": recommended_missing_time,
                },
            },
            "export_mode_choices": self.export_mode_choices(),
        }
        if include_export_lines:
            export_lines_by_mode = {
                mode: self.build_export_lines(progress, mode, character=character, language="en")
                for mode, _label in self.export_mode_choices()
            }
            progress["export_lines_by_mode"] = export_lines_by_mode
            progress["export_lines"] = export_lines_by_mode[self.EXPORT_MODE_RECOMMENDED]
        else:
            progress["export_lines_by_mode"] = {}
            progress["export_lines"] = []
        return progress
