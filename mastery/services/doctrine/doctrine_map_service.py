from fittings.models import Doctrine
from memberaudit.models import SkillSetGroup

from mastery.models import DoctrineSkillSetGroupMap


class DoctrineMapService:
    def __init__(self, doctrine_skill_service):
        self._doctrine_skill_service = doctrine_skill_service

    def create_doctrine_map(self, doctrine: Doctrine) -> DoctrineSkillSetGroupMap:
        doctrine_map = DoctrineSkillSetGroupMap.objects.filter(doctrine=doctrine).first()

        if doctrine_map:
            return doctrine_map

        group = SkillSetGroup.objects.create(
            name=doctrine.name,
            is_doctrine=True,
            is_active=True,
            description=doctrine.description
        )

        DoctrineSkillSetGroupMap.objects.update_or_create(
            doctrine=doctrine,
            skillset_group=group
        )

        doctrine_map = DoctrineSkillSetGroupMap.objects.get(doctrine=doctrine, skillset_group=group)

        self.sync(doctrine)

        return doctrine_map

    def sync(self, doctrine: Doctrine):
        doctrine_map = DoctrineSkillSetGroupMap.objects.filter(doctrine=doctrine).first()

        if not doctrine_map:
            doctrine_map = self.create_doctrine_map(doctrine)

        self._doctrine_skill_service.generate_for_doctrine(doctrine_map)
