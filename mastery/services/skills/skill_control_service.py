from mastery.models.fitting_skill_control import FittingSkillControl


class SkillControlService:
    @staticmethod
    def get_blacklist(fitting_id: int) -> set:
        return set(
            FittingSkillControl.objects.filter(
                fitting_id=fitting_id,
                is_blacklisted=True
            ).values_list('skill_type_id', flat=True)
        )

    def apply_blacklist(self, fitting_id: int, skills: dict) -> dict:
        blacklist = self.get_blacklist(fitting_id)
        return {
            skill_type_id: level for skill_type_id, level in skills.items() if skill_type_id not in blacklist
        }

    @staticmethod
    def set_blacklist(fitting_id: int, skill_type_id: int, value: bool):
        obj, _ = FittingSkillControl.objects.update_or_create(
            fitting_id=fitting_id,
            skill_type_id=skill_type_id,
            defaults={'is_blacklisted': value}
        )
        return obj

    @staticmethod
    def get_controls_map(fitting_id: int) -> dict:
        rows = FittingSkillControl.objects.filter(fitting_id=fitting_id).values(
            "skill_type_id",
            "is_blacklisted",
            "is_suggested",
            "reason",
            "recommended_level_override",
            "is_manual",
        )
        return {
            row["skill_type_id"]: row
            for row in rows
        }

    @staticmethod
    def add_manual_skill(fitting_id: int, skill_type_id: int, level: int):
        obj, _ = FittingSkillControl.objects.update_or_create(
            fitting_id=fitting_id,
            skill_type_id=skill_type_id,
            defaults={
                "is_manual": True,
                "is_blacklisted": False,
                "recommended_level_override": level,
            },
        )
        return obj

    @staticmethod
    def remove_manual_skill(fitting_id: int, skill_type_id: int):
        return FittingSkillControl.objects.filter(
            fitting_id=fitting_id,
            skill_type_id=skill_type_id,
            is_manual=True,
        ).delete()

    @staticmethod
    def set_recommended_level(fitting_id: int, skill_type_id: int, level):
        obj, _ = FittingSkillControl.objects.update_or_create(
            fitting_id=fitting_id,
            skill_type_id=skill_type_id,
            defaults={'recommended_level_override': level}
        )
        return obj

    def set_blacklist_batch(self, fitting_id: int, skill_type_ids: list, value: bool):
        for skill_type_id in skill_type_ids:
            self.set_blacklist(fitting_id=fitting_id, skill_type_id=skill_type_id, value=value)

    def set_recommended_level_batch(self, fitting_id: int, skill_type_ids: list, level):
        for skill_type_id in skill_type_ids:
            self.set_recommended_level(
                fitting_id=fitting_id,
                skill_type_id=skill_type_id,
                level=level,
            )

    @staticmethod
    def sync_suggestions(fitting_id: int, suggestions: dict):
        FittingSkillControl.objects.filter(fitting_id=fitting_id).update(
            is_suggested=False,
            reason=None,
        )

        for skill_type_id, suggestion in suggestions.items():
            FittingSkillControl.objects.update_or_create(
                fitting_id=fitting_id,
                skill_type_id=skill_type_id,
                defaults={
                    'is_suggested': True,
                    'reason': suggestion['reason'],
                },
            )

