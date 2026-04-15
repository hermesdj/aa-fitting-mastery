"""Service for creating/fetching FittingSkillsetMap entries."""
from fittings.models import Fitting
from memberaudit.models import SkillSet

from mastery.models import FittingSkillsetMap, DoctrineSkillSetGroupMap


class FittingMapService:
    """Manage Doctrine->Fitting->SkillSet map records."""

    @staticmethod
    def create_fitting_map(doctrine_map: DoctrineSkillSetGroupMap, fitting: Fitting) -> FittingSkillsetMap:
        """Get or create the fitting map and backing SkillSet for one fitting."""
        fitting_map = FittingSkillsetMap.objects.filter(fitting=fitting).first()

        if fitting_map:
            return fitting_map

        skillset = SkillSet.objects.create(
            name=fitting.name,
            description=fitting.description,
            is_visible=True,
            ship_type_id=fitting.ship_type_type_id,
        )

        doctrine_map.skillset_group.skill_sets.add(skillset)

        return FittingSkillsetMap.objects.create(
            fitting=fitting,
            skillset=skillset,
            doctrine_map=doctrine_map,
            mastery_level=None
        )
