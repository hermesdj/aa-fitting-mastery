"""Service layer for doctrine SkillSetGroup map lifecycle."""
from fittings.models import Doctrine
from memberaudit.models import SkillSetGroup

from mastery.models import DoctrineSkillSetGroupMap


class DoctrineMapService:
    """Create and synchronize doctrine-level skillset-group mappings."""

    def __init__(self, doctrine_skill_service):
        """Store service dependency used to regenerate doctrine skill snapshots."""
        self._doctrine_skill_service = doctrine_skill_service

    def create_doctrine_map(self, doctrine: Doctrine) -> DoctrineSkillSetGroupMap:
        """Create the Doctrine -> SkillSetGroup map if missing and sync it."""
        doctrine_map = DoctrineSkillSetGroupMap.objects.filter(doctrine=doctrine).first()

        if doctrine_map:
            return doctrine_map

        group, _ = SkillSetGroup.objects.get_or_create(
            name=doctrine.name,
            defaults={
                "is_doctrine": True,
                "is_active": True,
                "description": doctrine.description,
            },
        )

        doctrine_map, _ = DoctrineSkillSetGroupMap.objects.update_or_create(
            doctrine=doctrine,
            defaults={"skillset_group": group},
        )

        self.sync(doctrine)

        return doctrine_map

    def sync(self, doctrine: Doctrine):
        """Regenerate all fitting skillsets attached to a doctrine."""
        doctrine_map = DoctrineSkillSetGroupMap.objects.filter(doctrine=doctrine).first()

        if not doctrine_map:
            doctrine_map = self.create_doctrine_map(doctrine)

        self._doctrine_skill_service.generate_for_doctrine(doctrine_map)
