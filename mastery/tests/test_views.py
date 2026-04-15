import json
from types import SimpleNamespace
from unittest.mock import patch

from django.http import JsonResponse
from django.test import RequestFactory, SimpleTestCase

from mastery import views
from mastery.templatetags.skill_render import group_has_active_skills, group_has_blacklisted_skills
from mastery.views import _build_fitting_skills_ajax_response, _group_preview_skills, _resolve_row_levels


def _view_user():
    return SimpleNamespace(
        is_authenticated=True,
        has_perm=lambda _perm: True,
        has_perms=lambda _perms: True,
    )


class TestViewHelpers(SimpleTestCase):
    def test_group_state_filters_detect_active_and_blacklisted_rows(self):
        skills = [
            {"is_blacklisted": True},
            {"is_blacklisted": False},
        ]

        self.assertTrue(group_has_active_skills(skills))
        self.assertTrue(group_has_blacklisted_skills(skills))

    def test_group_state_filters_handle_empty_or_all_blacklisted_rows(self):
        self.assertFalse(group_has_active_skills([]))
        self.assertFalse(group_has_blacklisted_skills([]))
        self.assertFalse(group_has_active_skills([{"is_blacklisted": True}]))
        self.assertTrue(group_has_blacklisted_skills([{"is_blacklisted": True}]))

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

        with patch("mastery.views.common.ItemType.objects.select_related") as mock_select_related, patch(
            "mastery.views.common.TypeDogma.objects.filter"
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

    def test_group_preview_skills_excludes_blacklisted_rows_from_sp_totals(self):
        mocked_skill = SimpleNamespace(
            id=202,
            name="Capacitor Management",
            description="",
            group=SimpleNamespace(id=55, name="Engineering"),
        )

        with patch("mastery.views.common.ItemType.objects.select_related") as mock_select_related, patch(
            "mastery.views.common.TypeDogma.objects.filter"
        ) as mock_dogma_filter:
            mock_select_related.return_value.filter.return_value = [mocked_skill]
            mock_dogma_filter.return_value.values.return_value = [
                {"item_type_id": 202, "value": 1},
            ]

            grouped = _group_preview_skills(
                [
                    {
                        "skill_type_id": "202",
                        "required_level": 3,
                        "recommended_level": 4,
                        "is_blacklisted": True,
                    }
                ]
            )

        payload = grouped["Engineering"]
        self.assertEqual(payload["required_total_sp"], 0)
        self.assertEqual(payload["recommended_total_sp"], 0)

    def test_group_preview_skills_exposes_group_blacklist_state_flags(self):
        mocked_skill = SimpleNamespace(
            id=303,
            name="Hull Upgrades",
            description="",
            group=SimpleNamespace(id=55, name="Engineering"),
        )

        with patch("mastery.views.common.ItemType.objects.select_related") as mock_select_related, patch(
            "mastery.views.common.TypeDogma.objects.filter"
        ) as mock_dogma_filter:
            mock_select_related.return_value.filter.return_value = [mocked_skill]
            mock_dogma_filter.return_value.values.return_value = [
                {"item_type_id": 303, "value": 2},
            ]

            grouped = _group_preview_skills(
                [
                    {
                        "skill_type_id": "303",
                        "required_level": 2,
                        "recommended_level": 4,
                        "is_blacklisted": True,
                    },
                    {
                        "skill_type_id": "303",
                        "required_level": 1,
                        "recommended_level": 3,
                        "is_blacklisted": False,
                    },
                ]
            )

        payload = grouped["Engineering"]
        self.assertEqual(payload["group_id"], 55)
        self.assertEqual(payload["blacklisted_count"], 1)
        self.assertEqual(payload["active_skill_count"], 1)
        self.assertTrue(payload["has_blacklisted_skills"])
        self.assertTrue(payload["has_active_skills"])
        self.assertFalse(payload["all_blacklisted"])

    @patch("mastery.views.common._build_plan_kpis")
    @patch("mastery.views.common._get_skill_name_options", return_value=[])
    @patch("mastery.views.common._group_preview_skills", return_value={})
    @patch("mastery.views.common.doctrine_skill_service.preview_fitting")
    def test_build_fitting_preview_context_excludes_blacklisted_rows_from_global_kpis(
        self,
        mock_preview_fitting,
        _mock_group_preview_skills,
        _mock_get_skill_name_options,
        mock_build_plan_kpis,
    ):
        from mastery.views.common import _build_fitting_preview_context

        fitting = SimpleNamespace(id=1)
        doctrine_map = SimpleNamespace(default_mastery_level=4)
        mock_preview_fitting.return_value = {
            "effective_mastery_level": 4,
            "skills": [
                {"skill_type_id": 1, "is_blacklisted": False},
                {"skill_type_id": 2, "is_blacklisted": True},
            ],
        }
        mock_build_plan_kpis.return_value = {
            "required_plan_total_sp": 0,
            "required_plan_total_time": "0m",
            "recommended_plan_total_sp": 0,
            "recommended_plan_total_time": "0m",
        }

        _build_fitting_preview_context(
            fitting=fitting,
            doctrine_map=doctrine_map,
            fitting_map=None,
        )

        mock_build_plan_kpis.assert_called_once_with([
            {"skill_type_id": 1, "is_blacklisted": False},
        ])


class TestFittingSkillsAjax(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    @patch("mastery.views.common._render_ajax_messages_html", return_value="<div>Saved</div>")
    @patch("mastery.views.common._render_fitting_skills_editor_html", return_value="<section>Editor</section>")
    def test_build_fitting_skills_ajax_response_returns_fragment_payload(
        self,
        mock_render_editor,
        mock_render_messages,
    ):
        request = self.factory.post(
            "/fitting/1/skills/",
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        request.user = _view_user()

        fitting = SimpleNamespace(id=1)
        doctrine = SimpleNamespace(id=2)
        doctrine_map = SimpleNamespace(id=3)

        response = _build_fitting_skills_ajax_response(
            request,
            fitting=fitting,
            doctrine=doctrine,
            doctrine_map=doctrine_map,
            message="Saved",
        )

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.content.decode())
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["html"], "<section>Editor</section>")
        self.assertEqual(payload["messages_html"], "<div>Saved</div>")
        mock_render_editor.assert_called_once_with(
            request,
            fitting=fitting,
            doctrine=doctrine,
            doctrine_map=doctrine_map,
            fitting_map=None,
        )
        mock_render_messages.assert_called_once_with(request, message="Saved", level="success")

    @patch("mastery.views.common._build_fitting_skills_ajax_response")
    @patch("mastery.views.fitting.doctrine_skill_service.generate_for_fitting")
    @patch("mastery.views.fitting.control_service.set_blacklist")
    @patch("mastery.views.fitting._get_doctrine_and_map_for_fitting")
    def test_toggle_skill_blacklist_view_returns_json_for_ajax_requests(
        self,
        mock_get_doctrine_and_map,
        mock_set_blacklist,
        mock_generate,
        mock_build_ajax_response,
    ):
        fitting = SimpleNamespace(id=1)
        doctrine = SimpleNamespace(id=2)
        doctrine_map = SimpleNamespace(id=3)
        mock_get_doctrine_and_map.return_value = (fitting, doctrine, doctrine_map, None)
        mock_build_ajax_response.return_value = JsonResponse({"status": "ok", "html": "updated"})

        request = self.factory.post(
            "/fitting/1/blacklist/",
            data={"skill_type_id": "55", "value": "true"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        request.user = _view_user()

        response = views.toggle_skill_blacklist_view(request, fitting_id=1)

        self.assertEqual(response.status_code, 200)
        mock_set_blacklist.assert_called_once_with(fitting_id=1, skill_type_id=55, value=True)
        mock_generate.assert_called_once_with(doctrine_map, fitting)
        mock_build_ajax_response.assert_called_once_with(
            request,
            fitting=fitting,
            doctrine=doctrine,
            doctrine_map=doctrine_map,
            message="Skill blacklist updated",
            message_level="success",
        )

    @patch("mastery.views.fitting._get_doctrine_and_map_for_fitting")
    @patch("mastery.views.fitting.extractor_service.get_required_skills_for_fitting")
    def test_update_skill_group_controls_view_returns_json_error_for_invalid_group_level(
        self,
        mock_required_skills,
        mock_get_doctrine_and_map,
    ):
        mock_get_doctrine_and_map.return_value = (
            SimpleNamespace(id=1),
            SimpleNamespace(id=2),
            SimpleNamespace(id=3),
            None,
        )
        mock_required_skills.return_value = {55: 3}

        request = self.factory.post(
            "/fitting/1/skills/group-controls/",
            data={
                "action": "set_group_recommended",
                "recommended_level": "2",
                "skill_type_ids": ["55"],
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        request.user = _view_user()

        response = views.update_skill_group_controls_view(request, fitting_id=1)

        self.assertEqual(response.status_code, 400)
        payload = json.loads(response.content.decode())
        self.assertEqual(payload["status"], "error")
        self.assertIn("recommended_level cannot be lower", payload["message"])

    @patch("mastery.views.fitting._finalize_fitting_skills_action")
    @patch("mastery.views.fitting.doctrine_skill_service.generate_for_fitting")
    @patch("mastery.views.fitting.control_service.set_recommended_level_batch")
    @patch("mastery.views.fitting.extractor_service.get_required_skills_for_fitting")
    @patch("mastery.views.fitting._get_doctrine_and_map_for_fitting")
    def test_update_skill_group_controls_view_allows_auto_to_clear_group_recommended(
        self,
        mock_get_doctrine_and_map,
        mock_required_skills,
        mock_set_recommended_level_batch,
        mock_generate,
        mock_finalize,
    ):
        fitting = SimpleNamespace(id=1)
        doctrine = SimpleNamespace(id=2)
        doctrine_map = SimpleNamespace(id=3)
        mock_get_doctrine_and_map.return_value = (fitting, doctrine, doctrine_map, None)
        mock_required_skills.return_value = {55: 3}
        mock_finalize.return_value = JsonResponse({"status": "ok"})

        request = self.factory.post(
            "/fitting/1/skills/group-controls/",
            data={
                "action": "set_group_recommended",
                "recommended_level": "",
                "skill_type_ids": ["55"],
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        request.user = _view_user()

        response = views.update_skill_group_controls_view(request, fitting_id=1)

        self.assertEqual(response.status_code, 200)
        mock_set_recommended_level_batch.assert_called_once_with(
            fitting_id=1,
            skill_type_ids=[55],
            level=None,
        )
        mock_generate.assert_called_once_with(doctrine_map, fitting)
        mock_finalize.assert_called_once()

    @patch("mastery.views.common._build_fitting_skills_ajax_response")
    @patch("mastery.views.fitting._apply_preview_suggestions", return_value=0)
    @patch("mastery.views.fitting._get_doctrine_and_map_for_fitting")
    def test_apply_suggestions_view_returns_info_message_for_ajax_when_nothing_pending(
        self,
        mock_get_doctrine_and_map,
        _mock_apply_preview_suggestions,
        mock_build_ajax_response,
    ):
        fitting = SimpleNamespace(id=1)
        doctrine = SimpleNamespace(id=2)
        doctrine_map = SimpleNamespace(id=3)
        mock_get_doctrine_and_map.return_value = (fitting, doctrine, doctrine_map, None)
        mock_build_ajax_response.return_value = JsonResponse({"status": "ok", "html": "updated"})

        request = self.factory.post(
            "/fitting/1/skills/apply-suggestions/",
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        request.user = _view_user()

        response = views.apply_suggestions_view(request, fitting_id=1)

        self.assertEqual(response.status_code, 200)
        mock_build_ajax_response.assert_called_once_with(
            request,
            fitting=fitting,
            doctrine=doctrine,
            doctrine_map=doctrine_map,
            message="No pending suggestion to apply",
            message_level="info",
        )


