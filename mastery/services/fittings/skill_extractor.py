"""Extracts required skill IDs and levels from EVE fittings."""
from django.db.models import Prefetch
from eve_sde.models import ItemType, TypeDogma

from mastery.services.skill_requirements import REQUIRED_SKILL_ATTRIBUTES

TypeDogma.objects.prefetch_related(
    Prefetch("dogmaAttributes")
)



class FittingSkillExtractor:
    """FittingSkillExtractor class."""
    def __init__(self):
        """Init."""
        self._type_cache = {}

    def _expand_required_skill_tree(self, direct_skills: dict) -> dict:
        """Expand required skills with recursive skill prerequisites."""
        expanded = {
            int(skill_id): int(level)
            for skill_id, level in direct_skills.items()
            if int(level) > 0
        }
        queue = list(expanded.keys())
        visited = set()

        while queue:
            skill_id = int(queue.pop())
            if skill_id in visited:
                continue
            visited.add(skill_id)

            prereq_rows = self.get_required_skills_for_type(skill_id)
            for prereq_skill_id, prereq_data in prereq_rows.items():
                prereq_id = int(prereq_skill_id)
                prereq_level = int(prereq_data.get("l", 0) or 0)
                if prereq_level <= 0:
                    continue

                if prereq_level > expanded.get(prereq_id, 0):
                    expanded[prereq_id] = prereq_level
                if prereq_id not in visited:
                    queue.append(prereq_id)

        return expanded

    def get_required_skills_for_fitting(self, fitting) -> dict:
        """
        fitting = modèle aa-fittings
        """

        skills = {}

        # 1. for the ship itself
        ship_skills = self.get_required_skills_for_type(fitting.ship_type_type_id)

        for skill_id, level in ship_skills.items():
            skills[skill_id] = max(skills.get(skill_id, 0), level['l'])

        # 2. for the modules
        for module in fitting.items.all():
            type_id = module.type_id

            item_skills = self.get_required_skills_for_type(type_id)

            for skill_id, level in item_skills.items():
                skills[skill_id] = max(skills.get(skill_id, 0), level['l'])

        return self._expand_required_skill_tree(skills)

    def get_required_skills_for_type(self, type_id: int) -> dict:
        """
        Retourne {skill_type_id: level}
        pour un module ou un vaisseau
        """
        if type_id in self._type_cache:
            return self._type_cache[type_id]

        skill_ids = [skill_id for skill_id, _ in REQUIRED_SKILL_ATTRIBUTES]
        level_ids = [level_id for _, level_id in REQUIRED_SKILL_ATTRIBUTES]

        _types = TypeDogma.objects.filter(
            item_type_id=type_id,
            dogma_attribute_id__in=skill_ids + level_ids,
        )

        required = {}
        skills = {}

        sids = set()

        for t in _types:
            if t.item_type_id not in required:
                required[t.item_type_id] = {
                    0: {"skill": 0, "level": 0},
                    1: {"skill": 0, "level": 0},
                    2: {"skill": 0, "level": 0},
                    3: {"skill": 0, "level": 0},
                    4: {"skill": 0, "level": 0},
                    5: {"skill": 0, "level": 0},
                }

            a = t.dogma_attribute_id
            v = int(t.value)

            if a in skill_ids:
                required[t.item_type_id][skill_ids.index(a)]["skill"] = int(v)
            elif a in level_ids:
                idx = level_ids.index(a)
                if required[t.item_type_id][idx]["level"] < v:
                    required[t.item_type_id][idx]["level"] = int(v)

            for t in required.values():
                for s in t.values():
                    if s["skill"]:
                        if s["skill"] not in skills:
                            skills[s["skill"]] = {"s": s["skill"], "l": 0, "n": ""}
                            sids.add(s["skill"])
                        if s["level"] > skills[s["skill"]]["l"]:
                            skills[s["skill"]]["l"] = s["level"]

        for t in ItemType.objects.filter(id__in=sids):
            skills[t.id]["n"] = t.name

        self._type_cache[type_id] = skills

        return skills
