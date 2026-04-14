from memberaudit.models import CharacterSkillSetCheck, SkillSetSkill


class SkillCheckService:
    @staticmethod
    def get_character_progress(character, skillset):
        CharacterSkillSetCheck.objects.select_related(
            "character",
            "skill_set"
        ).prefetch_related("failed_required_skills", "failed_recommended_skills")

        check = CharacterSkillSetCheck.objects.filter(
            character=character,
            skill_set=skillset
        ).first()

        if not check:
            return None

        # Total Skills
        total_required = SkillSetSkill.objects.filter(
            skill_set=skillset,
            is_required=True
        ).count()

        total_recommended = SkillSetSkill.objects.filter(
            skill_set=skillset,
            is_required=False
        ).count()

        # Failed
        failed_required = check.failed_required_skills.count()
        failed_recommended = check.failed_recommended_skills.count()

        # Calcul %
        required_ok = total_required - failed_required
        recommended_ok = total_recommended - failed_recommended

        required_pct = (
            required_ok / total_required * 100
            if total_required else 100
        )

        recommended_pct = (
            recommended_ok / total_recommended * 100
            if total_recommended else 100
        )

        return {
            "required_pct": round(required_pct, 2),
            "recommended_pct": round(recommended_pct, 2),
            "failed_required": failed_required,
            "failed_recommended": failed_recommended
        }
