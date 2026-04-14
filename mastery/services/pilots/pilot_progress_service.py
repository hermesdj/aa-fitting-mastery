import math
from datetime import timedelta
import heapq

from eve_sde.models import ItemType
from eve_sde.models import TypeDogma


class PilotProgressService:
    EXPORT_MODE_REQUIRED = "required"
    EXPORT_MODE_RECOMMENDED = "recommended"

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
        ("ru", "Russian"),
        ("ja", "Japanese"),
        ("ko", "Korean"),
        ("zh", "Chinese"),
    ]

    def __init__(self):
        self._prereq_cache: dict[int, list[tuple[int, int]]] = {}
        self._skill_name_cache: dict[tuple[str, int], str] = {}

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
    def _sp_for_level(rank: int, level: int) -> int:
        if level <= 0:
            return 0
        return int(math.ceil(250 * rank * (2 ** (2.5 * (level - 1)))))

    def _estimate_missing(self, character, target_rows: list[dict[str, object]],
                          dogma_map: dict[int, dict[str, object | None]]) -> tuple[int, timedelta | None]:
        total_missing_sp = 0
        total_seconds = 0.0
        can_estimate_time = hasattr(character, "attributes")

        for row in target_rows:
            skill_type_id = int(row.get("skill_type_id", 0))
            target_level = int(row.get("target_level", 0))
            current_level = int(row.get("current_level", 0))
            current_sp = int(row.get("current_sp", 0))

            dogma = dogma_map.get(
                skill_type_id,
                {"rank": 1, "primary_attribute": None, "secondary_attribute": None},
            )
            rank = int(dogma.get("rank") or 1)

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

            primary_value = int(primary_value_raw)
            secondary_value = int(secondary_value_raw)

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

        missing_ids = [skill_id for skill_id in skill_type_ids if _cache_key(skill_id) not in self._skill_name_cache]
        if missing_ids:
            name_field = self._resolve_itemtype_name_field(language)
            for item_type in ItemType.objects.filter(id__in=missing_ids).only("id", name_field, "name_en", "name"):
                name_value = getattr(item_type, name_field, None) or getattr(item_type, "name_en", None) or getattr(item_type, "name", None)
                self._skill_name_cache[_cache_key(item_type.id)] = name_value or f"Skill {item_type.id}"
            for skill_id in missing_ids:
                self._skill_name_cache.setdefault(_cache_key(skill_id), f"Skill {skill_id}")

        return {
            skill_id: self._skill_name_cache.get(_cache_key(skill_id), f"Skill {skill_id}")
            for skill_id in skill_type_ids
        }

    @staticmethod
    def _load_current_levels(character, skill_type_ids: list[int]) -> dict[int, int]:
        if not character:
            return {}
        levels = {
            obj.eve_type_id: obj.active_skill_level
            for obj in character.skills.filter(eve_type_id__in=skill_type_ids)
        }
        for skill_id in skill_type_ids:
            levels.setdefault(skill_id, 0)
        return levels

    @classmethod
    def export_mode_choices(cls) -> list[tuple[str, str]]:
        return [
            (cls.EXPORT_MODE_REQUIRED, "Required"),
            (cls.EXPORT_MODE_RECOMMENDED, "Recommended"),
        ]

    @classmethod
    def export_language_choices(cls) -> list[tuple[str, str]]:
        return list(cls.EXPORT_LANGUAGE_CHOICES)

    @classmethod
    def normalize_export_language(cls, raw_language: str) -> str:
        if not raw_language:
            return "en"
        normalized = raw_language.strip().lower().replace("_", "-").split("-", 1)[0]
        valid = {code for code, _label in cls.EXPORT_LANGUAGE_CHOICES}
        if normalized in valid:
            return normalized
        return "en"

    @staticmethod
    def _resolve_itemtype_name_field(language: str) -> str:
        candidate = f"name_{language}"
        try:
            ItemType._meta.get_field(candidate)
            return candidate
        except Exception:
            pass

        for fallback in ("name_en", "name"):
            try:
                ItemType._meta.get_field(fallback)
                return fallback
            except Exception:
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

    def build_export_lines(self, progress: dict, mode: str, character=None, language: str = "en") -> list[str]:
        mode = mode or self.EXPORT_MODE_RECOMMENDED
        language = self.normalize_export_language(language)
        if mode == self.EXPORT_MODE_REQUIRED:
            source = progress.get("missing_required", [])
        else:
            source = progress.get("missing_recommended", [])

        if not source:
            return []

        # Base targets from selected mode.
        target_by_skill: dict[int, int] = {}
        current_levels: dict[int, int] = {}
        for row in source:
            skill_id = int(row["skill_type_id"])
            target_level = int(row["target_level"])
            current_level = int(row.get("current_level", 0))
            target_by_skill[skill_id] = max(target_by_skill.get(skill_id, 0), target_level)
            current_levels[skill_id] = max(current_levels.get(skill_id, 0), current_level)

        # Expand recursively with missing prerequisites.
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

        # Fill current levels for skills discovered via prerequisites.
        missing_level_skill_ids = [skill_id for skill_id in target_by_skill if skill_id not in current_levels]
        if missing_level_skill_ids:
            current_levels.update(self._load_current_levels(character, missing_level_skill_ids))

        # Build level nodes for all missing levels.
        nodes = set()
        first_missing_level = {}
        for skill_id, target_level in target_by_skill.items():
            current_level = int(current_levels.get(skill_id, 0))
            if current_level >= target_level:
                continue
            first_missing_level[skill_id] = current_level + 1
            for level in range(current_level + 1, target_level + 1):
                nodes.add((skill_id, level))

        if not nodes:
            return []

        # Build dependency graph.
        adjacency: dict[tuple[int, int], set[tuple[int, int]]] = {node: set() for node in nodes}
        indegree: dict[tuple[int, int], int] = {node: 0 for node in nodes}

        # Same-skill progression dependencies.
        for skill_id, target_level in target_by_skill.items():
            current_level = int(current_levels.get(skill_id, 0))
            for level in range(current_level + 2, target_level + 1):
                src = (skill_id, level - 1)
                dst = (skill_id, level)
                if src in adjacency and dst in adjacency and dst not in adjacency[src]:
                    adjacency[src].add(dst)
                    indegree[dst] += 1

        # Prerequisite dependencies before first missing level of dependent skill.
        prereq_all = self._load_skill_prerequisites(list(target_by_skill.keys()))
        for skill_id, prereqs in prereq_all.items():
            start_level = first_missing_level.get(skill_id)
            if start_level is None:
                continue
            dst = (skill_id, start_level)
            if dst not in adjacency:
                continue
            for prereq_skill_id, prereq_level in prereqs:
                src = (prereq_skill_id, prereq_level)
                if src in adjacency and dst not in adjacency[src]:
                    adjacency[src].add(dst)
                    indegree[dst] += 1

        skill_names = self._load_skill_names(list(target_by_skill.keys()), language=language)

        # Kahn topological sort, grouped naturally by level where possible.
        heap = []
        for node, degree in indegree.items():
            if degree == 0:
                skill_id, level = node
                heapq.heappush(heap, (level, skill_names.get(skill_id, f"Skill {skill_id}").lower(), skill_id, node))

        ordered_nodes = []
        while heap:
            _level, _name, _skill_id, node = heapq.heappop(heap)
            ordered_nodes.append(node)
            for nxt in adjacency[node]:
                indegree[nxt] -= 1
                if indegree[nxt] == 0:
                    nxt_skill_id, nxt_level = nxt
                    heapq.heappush(
                        heap,
                        (nxt_level, skill_names.get(nxt_skill_id, f"Skill {nxt_skill_id}").lower(), nxt_skill_id, nxt),
                    )

        # Fallback for unexpected cycles (should not happen in valid dogma data).
        if len(ordered_nodes) != len(nodes):
            remaining = [node for node in nodes if node not in set(ordered_nodes)]
            remaining.sort(key=lambda n: (n[1], skill_names.get(n[0], f"Skill {n[0]}").lower(), n[0]))
            ordered_nodes.extend(remaining)

        return [f"{skill_names.get(skill_id, f'Skill {skill_id}')} {self._roman(level)}" for skill_id, level in ordered_nodes]

    def build_for_character(self, character, skillset):
        skills_qs = skillset.skills.select_related("eve_type").order_by("eve_type__name")
        skills = list(skills_qs)
        skill_type_ids = [obj.eve_type_id for obj in skills]

        character_skills = {
            obj.eve_type_id: obj
            for obj in character.skills.filter(eve_type_id__in=skill_type_ids).select_related("eve_type")
        }

        missing_required = []
        missing_recommended = []
        total_required = 0
        total_recommended = 0

        for skill in skills:
            current = character_skills.get(skill.eve_type_id)
            current_level = 0 if current is None else current.active_skill_level
            current_sp = 0 if current is None else current.skillpoints_in_skill

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

        required_dogma_map = self._load_skill_dogma([obj["skill_type_id"] for obj in missing_required])
        required_missing_sp, required_missing_time = self._estimate_missing(character, missing_required,
                                                                            required_dogma_map)

        recommended_dogma_map = self._load_skill_dogma([obj["skill_type_id"] for obj in missing_recommended])
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
        progress["export_lines_by_mode"] = {
            mode: self.build_export_lines(progress, mode, character=character, language="en")
            for mode, _label in self.export_mode_choices()
        }
        progress["export_lines"] = progress["export_lines_by_mode"][self.EXPORT_MODE_RECOMMENDED]
        return progress
