from django.db import transaction
from django.utils import timezone
from fittings.models import Doctrine
from memberaudit.models import SkillSetSkill

from mastery.models import DoctrineSkillSetGroupMap
from mastery.services.fittings import FittingSkillExtractor, FittingMapService
from mastery.services.sde import MasteryService
from mastery.services.skills import SkillControlService, SkillSuggestionService


class DoctrineSkillService:

    def __init__(
            self,
            extractor: FittingSkillExtractor,
            mastery_service: MasteryService,
            control_service: SkillControlService,
            suggestion_service: SkillSuggestionService,
            fitting_map_service: FittingMapService
    ):
        self._extractor = extractor
        self._mastery_service = mastery_service
        self._control_service = control_service
        self._suggestion_service = suggestion_service
        self._fitting_map_service = fitting_map_service

    @staticmethod
    def _resolve_effective_mastery_level(doctrine_map, fitting_map, mastery_level: int = None) -> int:
        if mastery_level is not None:
            return mastery_level

        if fitting_map and fitting_map.mastery_level is not None:
            return fitting_map.mastery_level

        return doctrine_map.default_mastery_level

    def preview_fitting(self, doctrine_map: DoctrineSkillSetGroupMap, fitting, mastery_level: int = None) -> dict:
        fitting_map = self._fitting_map_service.create_fitting_map(doctrine_map, fitting)
        effective_mastery_level = self._resolve_effective_mastery_level(
            doctrine_map=doctrine_map,
            fitting_map=fitting_map,
            mastery_level=mastery_level,
        )

        min_skills = self._extractor.get_required_skills_for_fitting(fitting)
        recommended_skills = self._mastery_service.get_ship_skills(
            fitting.ship_type_type_id,
            effective_mastery_level,
        )
        blacklisted = self._control_service.get_blacklist(fitting.id)
        controls_map = self._control_service.get_controls_map(fitting.id)
        suggestions = self._suggestion_service.suggest(
            fitting, recommended_skills, fitting_required_skills=min_skills
        )
        all_skill_ids = sorted(set(min_skills) | set(recommended_skills) | set(controls_map))

        skill_rows = []
        pending_suggestions = {}
        for skill_id in all_skill_ids:
            suggestion = suggestions.get(skill_id)
            control = controls_map.get(skill_id)
            required_level = min_skills.get(skill_id, 0)
            recommended_override = None if control is None else control["recommended_level_override"]
            is_manual = False if control is None else control.get("is_manual", False)
            recommended_level = recommended_skills.get(skill_id, 0)
            if recommended_override is not None:
                recommended_level = recommended_override
            if recommended_level < required_level:
                recommended_level = required_level
            is_blacklisted = skill_id in blacklisted

            # Une suggestion est consideree comme deja appliquee si l'etat actuel
            # correspond deja a l'action demandee.
            if suggestion is not None:
                suggestion_action = suggestion.get("action", "remove")
                if suggestion_action == "remove" and is_blacklisted:
                    suggestion = None
                elif suggestion_action == "add" and not is_blacklisted:
                    suggestion = None

            if suggestion is None and is_blacklisted and (required_level > 0 or recommended_level > 0):
                suggestion = {
                    "action": "add",
                    "reason": "Skill is required/recommended for this fitting at the selected mastery level",
                    "group": None,
                }

            if suggestion is not None:
                pending_suggestions[skill_id] = suggestion

            skill_rows.append(
                {
                    "skill_type_id": skill_id,
                    "required_level": required_level,
                    "recommended_level": recommended_level,
                    "recommended_level_override": recommended_override,
                    "is_manual": is_manual,
                    "is_blacklisted": is_blacklisted,
                    "is_suggested": suggestion is not None,
                    "suggestion_action": None if suggestion is None else suggestion.get("action", "remove"),
                    "suggestion_reason": None if suggestion is None else suggestion["reason"],
                    "suggestion_group": None if suggestion is None else suggestion.get("group"),
                }
            )

        return {
            "effective_mastery_level": effective_mastery_level,
            "skill_rows": skill_rows,
            "skills": skill_rows,
            "suggestions": pending_suggestions,
            "fitting_map": fitting_map,
        }

    def generate_for_fitting(
        self,
        doctrine_map: DoctrineSkillSetGroupMap,
        fitting,
        mastery_level: int = None,
    ):
        preview = self.preview_fitting(
            doctrine_map=doctrine_map,
            fitting=fitting,
            mastery_level=mastery_level,
        )
        fitting_map = preview["fitting_map"]

        fitting_map.skillset.skills.all().delete()

        entries = [
            SkillSetSkill(
                skill_set=fitting_map.skillset,
                eve_type_id=row["skill_type_id"],
                required_level=row["required_level"],
                recommended_level=row["recommended_level"],
            )
            for row in preview["skill_rows"]
            if not row["is_blacklisted"]
        ]

        with transaction.atomic():
            SkillSetSkill.objects.bulk_create(entries)

        fitting_map.last_synced_at = timezone.now()
        fitting_map.save(update_fields=["last_synced_at"])

        self._control_service.sync_suggestions(fitting.id, preview["suggestions"])

    def generate_for_doctrine(self, doctrine_map: DoctrineSkillSetGroupMap, mastery_level: int = None):
        """
        Génère un snapshot de compétences pour une doctrine donnée
        """
        doctrine_id = doctrine_map.doctrine.id
        doctrine = Doctrine.objects.prefetch_related("fittings__items").get(id=doctrine_id)

        for fitting in doctrine.fittings.all():
            self.generate_for_fitting(
                doctrine_map=doctrine_map,
                fitting=fitting,
                mastery_level=mastery_level,
            )
