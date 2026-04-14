from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from mastery.views import _group_preview_skills, _resolve_row_levels


class TestViewHelpers(SimpleTestCase):
    def test_resolve_row_levels_with_default_keys(self):
        required_level, recommended_level = _resolve_row_levels(
            {
                "required_level": 3,
                "recommended_level": 4,
            }
        )

        self.assertEqual(required_level, 3)
        self.assertEqual(recommended_level, 4)

    def test_resolve_row_levels_uses_fallback_keys_and_override(self):
        required_level, recommended_level = _resolve_row_levels(
            {
                "required": "2",
                "recommended_level": "",
                "recommended_level_override": "5",
            }
        )

        self.assertEqual(required_level, 2)
        self.assertEqual(recommended_level, 5)

    def test_resolve_row_levels_never_returns_recommended_below_required(self):
        required_level, recommended_level = _resolve_row_levels(
            {
                "required_level": "4",
                "recommended": "3,0",
            }
        )

        self.assertEqual(required_level, 4)
        self.assertEqual(recommended_level, 4)

    def test_group_preview_skills_calculates_sp_totals_from_fallback_levels(self):
        mocked_skill = SimpleNamespace(
            id=101,
            name="Thermodynamics",
            description="Heat management skill",
            group=SimpleNamespace(id=55, name="Engineering"),
        )

        with patch("mastery.views.ItemType.objects.select_related") as mock_select_related, patch(
            "mastery.views.TypeDogma.objects.filter"
        ) as mock_dogma_filter:
            mock_select_related.return_value.filter.return_value = [mocked_skill]
            mock_dogma_filter.return_value.values.return_value = [
                {"item_type_id": 101, "value": 3},
            ]

            grouped = _group_preview_skills(
                [
                    {
                        "skill_type_id": "101",
                        "required": "2",
                        "recommended_level": "",
                        "recommended_level_override": "4",
                    }
                ]
            )

        self.assertIn("Engineering", grouped)
        payload = grouped["Engineering"]
        self.assertEqual(payload["required_total_sp"], 4243)
        self.assertEqual(payload["recommended_total_sp"], 135765)
        self.assertEqual(payload["skills"][0]["skill_name"], "Thermodynamics")


