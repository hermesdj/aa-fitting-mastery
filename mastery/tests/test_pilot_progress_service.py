from django.core.exceptions import FieldDoesNotExist
from django.test import SimpleTestCase
from unittest.mock import patch
from types import SimpleNamespace

from eve_sde.models import ItemType

from mastery.services.pilots.pilot_progress_service import PilotProgressService


class TestPilotProgressService(SimpleTestCase):
    def test_export_language_choices_include_all_supported_sde_languages(self):
        choices = {code for code, _label in PilotProgressService.export_language_choices()}

        self.assertTrue({"en", "de", "es", "fr", "it", "ja", "ko", "nl", "pl", "ru", "uk", "zh"}.issubset(choices))

    def test_resolve_itemtype_name_field_prefers_fr_fr_field(self):
        available = {"name_fr_fr", "name_en", "name"}

        def _fake_get_field(name):
            if name in available:
                return object()
            raise FieldDoesNotExist(name)

        with patch.object(ItemType._meta, "get_field", side_effect=_fake_get_field):
            result = PilotProgressService._resolve_itemtype_name_field("fr")

        self.assertEqual(result, "name_fr_fr")

    def test_resolve_itemtype_name_field_prefers_zh_hans_field(self):
        available = {"name_zh_hans", "name_en", "name"}

        def _fake_get_field(name):
            if name in available:
                return object()
            raise FieldDoesNotExist(name)

        with patch.object(ItemType._meta, "get_field", side_effect=_fake_get_field):
            result = PilotProgressService._resolve_itemtype_name_field("zh")

        self.assertEqual(result, "name_zh_hans")

    def test_estimate_large_skill_injectors_crosses_thresholds(self):
        result = PilotProgressService.estimate_large_skill_injectors(
            required_sp=600_000,
            current_total_sp=4_900_000,
        )

        self.assertTrue(result["known"])
        self.assertEqual(result["count"], 2)
        self.assertEqual(result["gained_sp"], 900_000)
        self.assertEqual(result["final_total_sp"], 5_800_000)

    def test_build_optimal_remap_prefers_most_valuable_attribute_pair(self):
        service = PilotProgressService()
        plan_rows = [
            {
                "missing_sp": 600_000,
                "primary_attribute": "perception",
                "secondary_attribute": "willpower",
            },
            {
                "missing_sp": 450_000,
                "primary_attribute": "perception",
                "secondary_attribute": "willpower",
            },
            {
                "missing_sp": 75_000,
                "primary_attribute": "memory",
                "secondary_attribute": "intelligence",
            },
        ]
        current_attributes = SimpleNamespace(
            charisma=17,
            intelligence=21,
            memory=27,
            perception=17,
            willpower=17,
        )

        result = service.build_optimal_remap(
            plan_rows,
            current_attributes=current_attributes,
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["primary_attribute"], "perception")
        self.assertEqual(result["secondary_attribute"], "willpower")
        attribute_values = {row["name"]: row["value"] for row in result["attributes"]}
        self.assertEqual(attribute_values["perception"], 27)
        self.assertEqual(attribute_values["willpower"], 21)
        self.assertEqual(attribute_values["memory"], 17)
        self.assertIsNotNone(result["estimated_time"])
        self.assertIsNotNone(result["time_saved"])

    def test_build_optimal_remap_applies_implants_to_recommended_simulation(self):
        class DummyDogmaList(list):
            def all(self):
                return self

        class DummyImplantList(list):
            def select_related(self, *_args, **_kwargs):
                return self

            def prefetch_related(self, *_args, **_kwargs):
                return self

        service = PilotProgressService()
        plan_rows = [
            {
                "missing_sp": 1_000_000,
                "primary_attribute": "perception",
                "secondary_attribute": "willpower",
            }
        ]
        current_attributes = SimpleNamespace(
            charisma=25,
            intelligence=25,
            memory=25,
            perception=25,
            willpower=25,
        )

        implants = DummyImplantList(
            [
                SimpleNamespace(eve_type=SimpleNamespace(dogma_attributes=DummyDogmaList([
                    SimpleNamespace(eve_dogma_attribute_id=175, value=5),
                ]))),
                SimpleNamespace(eve_type=SimpleNamespace(dogma_attributes=DummyDogmaList([
                    SimpleNamespace(eve_dogma_attribute_id=176, value=5),
                ]))),
                SimpleNamespace(eve_type=SimpleNamespace(dogma_attributes=DummyDogmaList([
                    SimpleNamespace(eve_dogma_attribute_id=177, value=5),
                ]))),
                SimpleNamespace(eve_type=SimpleNamespace(dogma_attributes=DummyDogmaList([
                    SimpleNamespace(eve_dogma_attribute_id=178, value=5),
                ]))),
                SimpleNamespace(eve_type=SimpleNamespace(dogma_attributes=DummyDogmaList([
                    SimpleNamespace(eve_dogma_attribute_id=179, value=5),
                ]))),
            ]
        )
        character = SimpleNamespace(implants=implants)

        result = service.build_optimal_remap(
            plan_rows,
            current_attributes=current_attributes,
            character=character,
        )

        self.assertIsNotNone(result)
        self.assertTrue(result["has_implant_bonus"])
        self.assertEqual(result["primary_attribute"], "perception")
        self.assertEqual(result["secondary_attribute"], "willpower")

        suggested_perception = next(row for row in result["attributes"] if row["name"] == "perception")
        self.assertEqual(suggested_perception["base_value"], 27)
        self.assertEqual(suggested_perception["effective_value"], 32)

        current_perception = next(row for row in result["current_attributes_rows"] if row["name"] == "perception")
        self.assertEqual(current_perception["base_value"], 20)
        self.assertEqual(current_perception["effective_value"], 25)

        self.assertTrue(any(row["name"] == "perception" and row["value"] == 5 for row in result["implant_bonus_rows"]))
        self.assertIsNotNone(result["time_saved"])
        self.assertGreater(result["time_saved"].total_seconds(), 0)

