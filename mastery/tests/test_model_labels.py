from types import SimpleNamespace
from typing import Any, cast

from django.test import SimpleTestCase

from mastery.models.doctrine_skillsetgroup_map import DoctrineSkillSetGroupMap
from mastery.models.fitting_skillset_map import FittingSkillsetMap


class TestModelLabels(SimpleTestCase):
    def test_fitting_skillset_map_str_prefers_readable_names(self):
        obj = SimpleNamespace(
            fitting=SimpleNamespace(name="Ferox Fleet"),
            skillset=SimpleNamespace(name="Ferox Fleet"),
            pk=1,
        )

        self.assertEqual(FittingSkillsetMap.__str__(cast(Any, obj)), "Ferox Fleet")

    def test_fitting_skillset_map_str_disambiguates_with_skillset(self):
        obj = SimpleNamespace(
            fitting=SimpleNamespace(name="Ferox Fleet"),
            skillset=SimpleNamespace(name="Ferox Fleet Doctrine"),
            pk=1,
        )

        self.assertEqual(
            FittingSkillsetMap.__str__(cast(Any, obj)),
            "Ferox Fleet [Ferox Fleet Doctrine]",
        )

    def test_doctrine_skillsetgroup_map_str_prefers_readable_names(self):
        obj = SimpleNamespace(
            doctrine=SimpleNamespace(name="Shield HAC"),
            skillset_group=SimpleNamespace(name="Shield HAC"),
            pk=2,
        )

        self.assertEqual(DoctrineSkillSetGroupMap.__str__(cast(Any, obj)), "Shield HAC")

    def test_doctrine_skillsetgroup_map_str_disambiguates_with_group(self):
        obj = SimpleNamespace(
            doctrine=SimpleNamespace(name="Shield HAC"),
            skillset_group=SimpleNamespace(name="Shield HAC Group"),
            pk=2,
        )

        self.assertEqual(
            DoctrineSkillSetGroupMap.__str__(cast(Any, obj)),
            "Shield HAC [Shield HAC Group]",
        )



