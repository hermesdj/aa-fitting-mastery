"""Service for managing skill plan progressions and user state."""
from collections import defaultdict
from typing import Dict, List

from django.db.models import Prefetch

from mastery.models import SkillPlanProgression, SkillPlanProgressionStep

class SkillPlanProgressionService:
    """Business logic for skill learning progressions."""

    @staticmethod
    def get_active_progressions(order_by_field: str = "order") -> List[SkillPlanProgression]:
        """Return all active progressions with their steps, ordered for display."""
        return list(
            SkillPlanProgression.objects.filter(is_active=True)
            .prefetch_related(
                Prefetch(
                    "steps",
                    SkillPlanProgressionStep.objects.all().order_by("order"),
                )
            )
            .order_by(order_by_field)
        )

    @staticmethod
    def get_progression_with_steps(progression_id: int) -> SkillPlanProgression:
        """Return a single progression with all its steps."""
        return SkillPlanProgression.objects.prefetch_related(
            Prefetch(
                "steps",
                SkillPlanProgressionStep.objects.all().order_by("order"),
            )
        ).get(id=progression_id)

    @staticmethod
    def calculate_user_progression_state(
        user,
        progression: SkillPlanProgression,
    ) -> Dict:
        """Calculate the user's progress through a progression.

        Returns a dict with:
        - progression: the progression object
        - steps: list of step dicts with status (completed, current, pending, or optional)
        - overall_completion_percent: 0-100
        - current_step: step dict or None
        """
        # Resolve completed SkillSetGroup IDs for all characters visible to the user.
        try:
            from memberaudit.models import Character, CharacterSkillSetCheck  # pylint: disable=import-outside-toplevel

            characters = Character.objects.user_has_scope(user)
            if not characters.exists():
                return SkillPlanProgressionService._build_progression_state(
                    progression,
                    set(),
                )

            completed_group_ids = set(
                CharacterSkillSetCheck.objects.filter(
                    character__in=characters,
                    failed_required_skills__isnull=True,
                )
                .values_list("skill_set__groups__id", flat=True)
            )
            completed_group_ids.discard(None)

        except Exception:  # pylint: disable=broad-except
            completed_group_ids = set()

        return SkillPlanProgressionService._build_progression_state(
            progression,
            completed_group_ids,
        )

    @staticmethod
    def _build_progression_state(
        progression: SkillPlanProgression,
        completed_group_ids: set,
    ) -> Dict:
        """Build the progression state dict from completed skillsets.

        Args:
            progression: the progression object
            completed_group_ids: set of SkillSetGroup IDs the user has completed

        Returns:
            Dict with progression state
        """
        steps = list(progression.steps.all())
        step_dicts = []
        completed_count = 0
        current_order = None
        completed_branch_keys = {
            step.branch_key
            for step in steps
            if step.branch_key and step.skillset_group_id in completed_group_ids
        }

        for step in steps:
            is_completed = (
                step.skillset_group_id in completed_group_ids
                or (step.branch_key and step.branch_key in completed_branch_keys)
            )

            if is_completed:
                status = "completed"
                completed_count += 1
            elif current_order is None:
                status = "current"
                current_order = step.order
            elif step.order == current_order:
                status = "current"
            else:
                status = "pending"

            step_dict = {
                "id": step.id,
                "progression_id": step.progression_id,
                "step_number": step.step_number,
                "skillset_group_id": step.skillset_group_id,
                "skillset_group_name": step.skillset_group.name,
                "description": step.description,
                "is_required": step.is_required,
                "branch_key": step.branch_key,
                "status": status,  # completed, current, pending, optional
            }
            step_dicts.append(step_dict)

        overall_percent = (
            (completed_count / len(steps) * 100) if steps else 0
        )

        current_step = next((step for step in step_dicts if step["status"] == "current"), None)

        return {
            "progression": progression,
            "steps": step_dicts,
            "completed_count": completed_count,
            "total_steps": len(steps),
            "overall_completion_percent": int(overall_percent),
            "current_step": current_step,
        }

    @staticmethod
    def reorder_progression_steps(progression_id: int, new_order: List[int]) -> None:
        """Reorder the steps of a progression based on a list of step IDs.

        Args:
            progression_id: ID of the progression
            new_order: List of step IDs in the desired order

        Raises:
            ValueError: if any step ID is not part of the progression
        """
        steps = SkillPlanProgressionStep.objects.filter(
            progression_id=progression_id
        ).values_list("id", flat=True)
        step_id_set = set(steps)
        new_order_set = set(new_order)

        if step_id_set != new_order_set:
            raise ValueError(
                f"Step ID mismatch: expected {step_id_set}, got {new_order_set}"
            )

        for idx, step_id in enumerate(new_order):
            SkillPlanProgressionStep.objects.filter(id=step_id).update(order=idx)

    @staticmethod
    def get_branch_groups(progression: SkillPlanProgression) -> Dict[str, List]:
        """Return steps grouped by branch_key for UI rendering.

        Returns:
            Dict mapping branch_key (or None) to list of steps
        """
        branches = defaultdict(list)
        for step in progression.steps.all():
            branches[step.branch_key].append(step)
        return dict(branches)

    @staticmethod
    def bulk_get_user_progressions(
        user,
        progressions: List[SkillPlanProgression] = None,
    ) -> List[Dict]:
        """Get user state for multiple progressions efficiently.

        Args:
            user: the user
            progressions: list of SkillPlanProgression objects (or None to fetch all active)

        Returns:
            List of progression state dicts
        """
        if progressions is None:
            progressions = SkillPlanProgressionService.get_active_progressions()

        result = []
        for progression in progressions:
            state = SkillPlanProgressionService.calculate_user_progression_state(
                user, progression
            )
            result.append(state)

        return result
