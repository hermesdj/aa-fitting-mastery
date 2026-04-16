import json
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

from django.http import HttpResponse
from django.http import JsonResponse
from django.test import RequestFactory, SimpleTestCase

from mastery import views
from mastery.templatetags.skill_render import group_has_active_skills, group_has_blacklisted_skills
from mastery.views import _build_fitting_skills_ajax_response, _group_preview_skills, _resolve_row_levels
from mastery.views.summary_helpers import (
    _annotate_member_detail_pilots,
    _build_doctrine_kpis,
    _build_fitting_kpis,
    _build_fitting_user_rows,
    _get_selected_summary_group,
    _get_summary_group_by_id,
    _parse_activity_days,
    _parse_training_days,
    _summary_entity_catalog,
)


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


class TestDoctrineViews(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    @patch("mastery.views.doctrine.render", return_value=HttpResponse("ok"))
    @patch("mastery.views.doctrine.FittingSkillsetMap.objects.filter")
    @patch("mastery.views.doctrine.DoctrineSkillSetGroupMap.objects.filter")
    @patch("mastery.views.doctrine.Doctrine.objects.prefetch_related")
    def test_doctrine_list_view_builds_initialized_and_uninitialized_rows(
        self,
        mock_prefetch_related,
        mock_doctrine_map_filter,
        mock_fitting_map_filter,
        mock_render,
    ):
        doctrine_one = SimpleNamespace(
            pk=1,
            name="Alpha",
            icon_url="icon-a",
            fittings=Mock(),
        )
        doctrine_one.fittings.all.return_value.count.return_value = 2
        doctrine_two = SimpleNamespace(
            pk=2,
            name="Beta",
            icon_url="icon-b",
            fittings=Mock(),
        )
        doctrine_two.fittings.all.return_value.count.return_value = 1
        mock_prefetch_related.return_value = [doctrine_one, doctrine_two]

        first_qs = Mock()
        first_qs.first.return_value = SimpleNamespace(default_mastery_level=3)
        second_qs = Mock()
        second_qs.first.return_value = None
        mock_doctrine_map_filter.side_effect = [first_qs, second_qs]
        mock_fitting_map_filter.return_value.count.return_value = 1

        request = self.factory.get("/doctrines/")
        request.user = _view_user()

        response = views.doctrine_list_view(request)

        self.assertEqual(response.status_code, 200)
        context = mock_render.call_args[0][2]
        self.assertEqual(len(context["doctrines"]), 2)
        self.assertTrue(context["doctrines"][0]["initialized"])
        self.assertEqual(context["doctrines"][0]["configured"], 1)
        self.assertEqual(context["doctrines"][0]["default_mastery_level"], 3)
        self.assertFalse(context["doctrines"][1]["initialized"])
        self.assertIsNone(context["doctrines"][1]["default_mastery_level"])

    @patch("mastery.views.doctrine.render", return_value=HttpResponse("ok"))
    @patch("mastery.views.doctrine.FittingSkillsetMap.objects.filter")
    @patch("mastery.views.doctrine.DoctrineSkillSetGroupMap.objects.filter")
    @patch("mastery.views.doctrine.Doctrine.objects.prefetch_related")
    def test_doctrine_detail_view_uses_override_or_doctrine_default_mastery(
        self,
        mock_prefetch_related,
        mock_doctrine_map_filter,
        mock_fitting_map_filter,
        mock_render,
    ):
        fitting_one = SimpleNamespace(id=10, name="Fit A", ship_type_type_id=100, ship_type=SimpleNamespace(name="Ship A"))
        fitting_two = SimpleNamespace(id=11, name="Fit B", ship_type_type_id=101, ship_type=SimpleNamespace(name="Ship B"))
        doctrine = SimpleNamespace(fittings=Mock())
        doctrine.fittings.all.return_value = [fitting_one, fitting_two]
        mock_prefetch_related.return_value.get.return_value = doctrine

        doctrine_map_qs = Mock()
        doctrine_map_qs.first.return_value = SimpleNamespace(default_mastery_level=3)
        mock_doctrine_map_filter.return_value = doctrine_map_qs

        first_fitting_map_qs = Mock()
        first_fitting_map_qs.first.return_value = SimpleNamespace(mastery_level=5)
        second_fitting_map_qs = Mock()
        second_fitting_map_qs.first.return_value = None
        mock_fitting_map_filter.side_effect = [first_fitting_map_qs, second_fitting_map_qs]

        request = self.factory.get("/doctrines/1/")
        request.user = _view_user()

        response = views.doctrine_detail_view(request, doctrine_id=1)

        self.assertEqual(response.status_code, 200)
        context = mock_render.call_args[0][2]
        self.assertEqual(context["doctrine_default_mastery_level"], 3)
        self.assertEqual(context["fittings"][0]["effective_mastery_level"], 5)
        self.assertEqual(context["fittings"][1]["effective_mastery_level"], 3)

    @patch("mastery.views.doctrine.redirect", return_value=HttpResponse("redirect"))
    @patch("mastery.views.doctrine.doctrine_map_service.create_doctrine_map")
    @patch("mastery.views.doctrine.DoctrineSkillSetGroupMap.objects.filter")
    @patch("mastery.views.doctrine.Doctrine.objects.get")
    def test_generate_doctrine_creates_map_when_missing(
        self,
        mock_doctrine_get,
        mock_doctrine_map_filter,
        mock_create_doctrine_map,
        mock_redirect,
    ):
        doctrine = SimpleNamespace(id=42)
        mock_doctrine_get.return_value = doctrine
        mock_doctrine_map_filter.return_value.exists.return_value = False

        request = self.factory.get("/doctrines/42/generate/")
        request.user = _view_user()

        response = views.generate_doctrine(request, doctrine_id=42)

        self.assertEqual(response.status_code, 200)
        mock_create_doctrine_map.assert_called_once_with(doctrine)
        mock_redirect.assert_called_once_with("mastery:doctrine_detail", doctrine_id=42)

    @patch("mastery.views.doctrine.redirect", return_value=HttpResponse("redirect"))
    @patch("mastery.views.doctrine.doctrine_map_service.sync")
    @patch("mastery.views.doctrine.Doctrine.objects.get")
    def test_sync_doctrine_calls_sync_and_redirects(self, mock_doctrine_get, mock_sync, mock_redirect):
        doctrine = SimpleNamespace(id=9)
        mock_doctrine_get.return_value = doctrine

        request = self.factory.get("/doctrines/9/sync/")
        request.user = _view_user()

        response = views.sync_doctrine(request, doctrine_id=9)

        self.assertEqual(response.status_code, 200)
        mock_sync.assert_called_once_with(doctrine)
        mock_redirect.assert_called_once_with("mastery:doctrine_detail", doctrine_id=9)

    def test_update_doctrine_mastery_requires_post(self):
        request = self.factory.get("/doctrines/1/mastery/")
        request.user = _view_user()

        response = views.update_doctrine_mastery(request, doctrine_id=1)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.content.decode(), "POST required")

    @patch("mastery.views.doctrine.redirect", return_value=HttpResponse("redirect"))
    @patch("mastery.views.doctrine._parse_mastery_level", return_value=5)
    @patch("mastery.views.doctrine.doctrine_map_service.sync")
    @patch("mastery.views.doctrine.doctrine_map_service.create_doctrine_map")
    @patch("mastery.views.doctrine.DoctrineSkillSetGroupMap.objects.filter")
    @patch("mastery.views.doctrine.get_object_or_404")
    def test_update_doctrine_mastery_creates_missing_map_and_syncs(
        self,
        mock_get_object_or_404,
        mock_doctrine_map_filter,
        mock_create_doctrine_map,
        mock_sync,
        _mock_parse_mastery_level,
        mock_redirect,
    ):
        doctrine = SimpleNamespace(id=1)
        doctrine_map = Mock(default_mastery_level=4)
        mock_get_object_or_404.return_value = doctrine
        mock_doctrine_map_filter.return_value.first.return_value = None
        mock_create_doctrine_map.return_value = doctrine_map

        request = self.factory.post("/doctrines/1/mastery/", data={"mastery_level": "5"})
        request.user = _view_user()

        response = views.update_doctrine_mastery(request, doctrine_id=1)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(doctrine_map.default_mastery_level, 5)
        doctrine_map.save.assert_called_once_with(update_fields=["default_mastery_level"])
        mock_sync.assert_called_once_with(doctrine)
        mock_redirect.assert_called_once_with("mastery:doctrine_detail", doctrine_id=1)

    @patch("mastery.views.doctrine._parse_mastery_level", side_effect=ValueError("invalid mastery"))
    @patch("mastery.views.doctrine.DoctrineSkillSetGroupMap.objects.filter")
    @patch("mastery.views.doctrine.get_object_or_404")
    def test_update_doctrine_mastery_returns_bad_request_for_invalid_level(
        self,
        mock_get_object_or_404,
        mock_doctrine_map_filter,
        _mock_parse_mastery_level,
    ):
        doctrine = SimpleNamespace(id=1)
        doctrine_map = Mock(default_mastery_level=4)
        mock_get_object_or_404.return_value = doctrine
        mock_doctrine_map_filter.return_value.first.return_value = doctrine_map

        request = self.factory.post("/doctrines/1/mastery/", data={"mastery_level": "x"})
        request.user = _view_user()

        response = views.update_doctrine_mastery(request, doctrine_id=1)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.content.decode(), "invalid mastery")


# ---------------------------------------------------------------------------
# Summary helpers – pure-Python functions (no DB required)
# ---------------------------------------------------------------------------


class TestSummaryHelpers(SimpleTestCase):
    # -- _parse_activity_days / _parse_training_days -------------------------

    def test_parse_activity_days_returns_default_when_none(self):
        self.assertEqual(_parse_activity_days(None, default=14), 14)

    def test_parse_activity_days_clamps_to_min_1(self):
        self.assertEqual(_parse_activity_days("0"), 1)

    def test_parse_activity_days_clamps_to_max_90(self):
        self.assertEqual(_parse_activity_days("999"), 90)

    def test_parse_activity_days_returns_default_for_non_numeric(self):
        self.assertEqual(_parse_activity_days("abc", default=14), 14)

    def test_parse_activity_days_parses_valid_integer(self):
        self.assertEqual(_parse_activity_days("30"), 30)

    def test_parse_training_days_returns_default_when_none(self):
        self.assertEqual(_parse_training_days(None, default=7), 7)

    def test_parse_training_days_clamps_and_parses(self):
        self.assertEqual(_parse_training_days("0"), 1)
        self.assertEqual(_parse_training_days("100"), 90)
        self.assertEqual(_parse_training_days("14"), 14)

    # -- _get_summary_group_by_id --------------------------------------------

    @patch("mastery.views.summary_helpers.SummaryAudienceGroup.objects.filter")
    def test_get_summary_group_by_id_returns_none_for_blank(self, _mock_filter):
        self.assertIsNone(_get_summary_group_by_id(""))
        self.assertIsNone(_get_summary_group_by_id(None))

    @patch("mastery.views.summary_helpers.SummaryAudienceGroup.objects.filter")
    def test_get_summary_group_by_id_returns_none_for_non_integer(self, _mock_filter):
        self.assertIsNone(_get_summary_group_by_id("abc"))

    @patch("mastery.views.summary_helpers.SummaryAudienceGroup.objects.filter")
    def test_get_summary_group_by_id_queries_and_returns_first(self, mock_filter):
        group = SimpleNamespace(id=5)
        mock_filter.return_value.prefetch_related.return_value.first.return_value = group
        result = _get_summary_group_by_id("5")
        self.assertEqual(result, group)

    # -- _get_selected_summary_group -----------------------------------------

    @patch("mastery.views.summary_helpers.SummaryAudienceGroup.objects.prefetch_related")
    def test_get_selected_summary_group_picks_first_when_no_id(self, mock_prefetch):
        group_a = SimpleNamespace(id=1, name="Alpha")
        group_b = SimpleNamespace(id=2, name="Beta")
        mock_prefetch.return_value.order_by.return_value = [group_a, group_b]
        groups, selected = _get_selected_summary_group(None)
        self.assertEqual(groups, [group_a, group_b])
        self.assertEqual(selected, group_a)

    @patch("mastery.views.summary_helpers.SummaryAudienceGroup.objects.prefetch_related")
    def test_get_selected_summary_group_finds_by_id(self, mock_prefetch):
        group_a = SimpleNamespace(id=1, name="Alpha")
        group_b = SimpleNamespace(id=2, name="Beta")
        mock_prefetch.return_value.order_by.return_value = [group_a, group_b]
        groups, selected = _get_selected_summary_group("2")
        self.assertEqual(selected, group_b)

    @patch("mastery.views.summary_helpers.SummaryAudienceGroup.objects.prefetch_related")
    def test_get_selected_summary_group_falls_back_to_first_for_unknown_id(self, mock_prefetch):
        group_a = SimpleNamespace(id=1, name="Alpha")
        mock_prefetch.return_value.order_by.return_value = [group_a]
        groups, selected = _get_selected_summary_group("999")
        self.assertEqual(selected, group_a)

    @patch("mastery.views.summary_helpers.SummaryAudienceGroup.objects.prefetch_related")
    def test_get_selected_summary_group_returns_none_when_empty(self, mock_prefetch):
        mock_prefetch.return_value.order_by.return_value = []
        groups, selected = _get_selected_summary_group(None)
        self.assertEqual(groups, [])
        self.assertIsNone(selected)

    # -- _build_fitting_kpis -------------------------------------------------

    def _make_user_row(self, can_fly=False, recommended_pct=0.0, required_pct=0.0, required_time=None):
        pilot_progress = {
            "can_fly": can_fly,
            "recommended_pct": recommended_pct,
            "required_pct": required_pct,
            "mode_stats": {
                "required": {
                    "total_missing_time": required_time,
                    "total_missing_sp": 0,
                },
                "recommended": {
                    "total_missing_time": required_time,
                    "total_missing_sp": 0,
                },
            },
        }
        return {
            "user": SimpleNamespace(id=1),
            "best_progress": pilot_progress,
            "character_rows": [{"character": SimpleNamespace(id=10), "progress": pilot_progress}],
            "flyable_count": 1 if can_fly else 0,
            "active_count": 1,
            "total_count": 1,
            "last_seen": None,
        }

    def test_build_fitting_kpis_empty_rows(self):
        kpis = _build_fitting_kpis([])
        self.assertEqual(kpis["users_total"], 0)
        self.assertEqual(kpis["flyable_now_users"], 0)
        self.assertEqual(kpis["recommended_avg_pct"], 0.0)

    def test_build_fitting_kpis_all_flyable_and_recommended(self):
        rows = [self._make_user_row(can_fly=True, recommended_pct=100.0)]
        kpis = _build_fitting_kpis(rows)
        self.assertEqual(kpis["users_total"], 1)
        self.assertEqual(kpis["flyable_now_users"], 1)
        self.assertEqual(kpis["flyable_now_characters"], 1)
        self.assertEqual(kpis["recommended_ready"], 1)
        self.assertEqual(kpis["recommended_avg_pct"], 100.0)


    # -- _build_doctrine_kpis ------------------------------------------------

    def _make_fitting_entry(self, configured=True, user_rows=None):
        return {
            "configured": configured,
            "user_rows": user_rows or [],
        }

    def test_build_doctrine_kpis_empty_fittings(self):
        kpis = _build_doctrine_kpis([], users_tracked=0)
        self.assertEqual(kpis["users_total"], 0)
        self.assertEqual(kpis["flyable_now_users"], 0)

    def test_build_doctrine_kpis_skips_unconfigured_fittings(self):
        kpis = _build_doctrine_kpis(
            [self._make_fitting_entry(configured=False)],
            users_tracked=5,
        )
        self.assertEqual(kpis["flyable_now_users"], 0)
        self.assertEqual(kpis["users_total"], 5)

    def test_build_doctrine_kpis_counts_flyable_users_once_per_user(self):
        user = SimpleNamespace(id=42)
        progress = {
            "can_fly": True,
            "recommended_pct": 100.0,
            "required_pct": 100.0,
            "mode_stats": {},
        }
        row = {
            "user": user,
            "best_progress": progress,
            "character_rows": [{"character": SimpleNamespace(id=1), "progress": progress}],
        }
        fittings = [
            self._make_fitting_entry(configured=True, user_rows=[row]),
            self._make_fitting_entry(configured=True, user_rows=[row]),
        ]
        kpis = _build_doctrine_kpis(fittings, users_tracked=1)
        self.assertEqual(kpis["flyable_now_users"], 1)
        self.assertEqual(kpis["flyable_now_characters"], 1)

    # -- _annotate_member_detail_pilots --------------------------------------

    def _make_pilot_row(self, can_fly=False, required_pct=0.0, recommended_pct=0.0, required_time=None):
        progress = {
            "can_fly": can_fly,
            "required_pct": required_pct,
            "recommended_pct": recommended_pct,
            "mode_stats": {
                "required": {
                    "total_missing_time": required_time,
                    "total_missing_sp": 100,
                },
                "recommended": {
                    "total_missing_time": required_time,
                    "total_missing_sp": 200,
                },
            },
        }
        return {"character": SimpleNamespace(id=1), "progress": progress}

    def _make_annotate_row(self, flyable_count=0, character_rows=None):
        return {
            "user": SimpleNamespace(id=1),
            "flyable_count": flyable_count,
            "character_rows": character_rows or [],
        }

    def test_annotate_member_detail_pilots_drops_rows_with_no_flyable_and_no_near(self):
        row = self._make_annotate_row(
            flyable_count=0,
            character_rows=[self._make_pilot_row(can_fly=False, required_pct=10.0)],
        )
        result = _annotate_member_detail_pilots([row])
        self.assertEqual(result, [])

    def test_annotate_member_detail_pilots_keeps_rows_with_flyable(self):
        row = self._make_annotate_row(
            flyable_count=1,
            character_rows=[self._make_pilot_row(can_fly=True, recommended_pct=80.0)],
        )
        result = _annotate_member_detail_pilots([row])
        self.assertEqual(len(result), 1)
        self.assertIn("req_ready_not_recommended", result[0])
        self.assertEqual(len(result[0]["req_ready_not_recommended"]), 1)

    def test_annotate_member_detail_pilots_keeps_near_required_pilots(self):
        row = self._make_annotate_row(
            flyable_count=0,
            character_rows=[
                self._make_pilot_row(can_fly=False, required_pct=95.0, required_time=timedelta(days=2)),
            ],
        )
        result = _annotate_member_detail_pilots([row], training_days=7)
        self.assertEqual(len(result), 1)
        self.assertTrue(result[0]["near_required"][0]["is_trainable_soon"])

    # -- _build_fitting_user_rows --------------------------------------------

    @patch("mastery.views.summary_helpers.pilot_progress_service")
    def test_build_fitting_user_rows_returns_sorted_rows(self, mock_progress_service):
        progress_a = {
            "can_fly": False,
            "recommended_pct": 60.0,
            "required_pct": 80.0,
        }
        progress_b = {
            "can_fly": True,
            "recommended_pct": 100.0,
            "required_pct": 100.0,
        }
        mock_progress_service.build_for_character.side_effect = [progress_a, progress_b]

        char_a = SimpleNamespace(id=10)
        char_b = SimpleNamespace(id=11)
        user_a = SimpleNamespace(id=1)
        user_b = SimpleNamespace(id=2)
        skillset = SimpleNamespace(id=99)
        fitting_map = SimpleNamespace(skillset=skillset)

        member_groups = [
            {
                "user": user_a,
                "main_character": SimpleNamespace(character_name="Alpha"),
                "characters": [char_a],
                "total_count": 1,
                "last_seen": None,
            },
            {
                "user": user_b,
                "main_character": SimpleNamespace(character_name="Beta"),
                "characters": [char_b],
                "total_count": 1,
                "last_seen": None,
            },
        ]

        rows = _build_fitting_user_rows(fitting_map=fitting_map, member_groups=member_groups, progress_cache={})

        self.assertEqual(len(rows), 2)
        # should be sorted descending: flyable first
        self.assertTrue(rows[0]["best_progress"]["can_fly"])
        self.assertFalse(rows[1]["best_progress"]["can_fly"])

    # -- _summary_entity_catalog ---------------------------------------------

    @patch("mastery.views.summary_helpers.EveCharacter.objects.all")
    def test_summary_entity_catalog_groups_corps_and_alliances(self, mock_all):
        eve_chars = [
            SimpleNamespace(corporation_id=100, corporation_name="Corp Alpha", alliance_id=200, alliance_name="Alliance X"),
            SimpleNamespace(corporation_id=100, corporation_name="Corp Alpha", alliance_id=None, alliance_name=None),
            SimpleNamespace(corporation_id=101, corporation_name="Corp Beta", alliance_id=200, alliance_name="Alliance X"),
        ]
        mock_all.return_value = eve_chars

        corps, alliances = _summary_entity_catalog()

        self.assertEqual(len(corps), 2)
        corp_alpha = next(c for c in corps if c["id"] == 100)
        self.assertEqual(corp_alpha["count"], 2)

        self.assertEqual(len(alliances), 1)
        self.assertEqual(alliances[0]["id"], 200)
        self.assertEqual(alliances[0]["count"], 2)

    @patch("mastery.views.summary_helpers.EveCharacter.objects.all")
    def test_summary_entity_catalog_returns_empty_lists_when_no_chars(self, mock_all):
        mock_all.return_value = []
        corps, alliances = _summary_entity_catalog()
        self.assertEqual(corps, [])
        self.assertEqual(alliances, [])


# ---------------------------------------------------------------------------
# Summary views
# ---------------------------------------------------------------------------


class TestSummaryViews(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def _req(self, method="get", path="/", **kwargs):
        req = getattr(self.factory, method)(path, **kwargs)
        req.user = _view_user()
        return req

    # -- summary_doctrine_detail_view ----------------------------------------

    @patch("mastery.views.summary._get_selected_summary_group")
    def test_summary_doctrine_detail_view_returns_400_when_no_group(self, mock_get_group):
        mock_get_group.return_value = ([], None)
        req = self._req(path="/summary/doctrine/1/")
        response = views.summary_doctrine_detail_view(req, doctrine_id=1)
        self.assertEqual(response.status_code, 400)

    # -- summary_fitting_detail_view -----------------------------------------

    @patch("mastery.views.summary._get_selected_summary_group")
    def test_summary_fitting_detail_view_returns_400_when_no_group(self, mock_get_group):
        mock_get_group.return_value = ([], None)
        req = self._req(path="/summary/fitting/1/")
        response = views.summary_fitting_detail_view(req, fitting_id=1)
        self.assertEqual(response.status_code, 400)

    @patch("mastery.views.summary.render", return_value=HttpResponse("ok"))
    @patch("mastery.views.summary._annotate_member_detail_pilots", return_value=[])
    @patch("mastery.views.summary._build_fitting_kpis", return_value={})
    @patch("mastery.views.summary._build_fitting_user_rows", return_value=[])
    @patch("mastery.views.summary._build_member_groups_for_summary", return_value=[])
    @patch("mastery.views.summary.FittingSkillsetMap.objects.select_related")
    @patch("mastery.views.summary._get_accessible_fitting_or_404")
    @patch("mastery.views.summary._get_selected_summary_group")
    def test_summary_fitting_detail_view_returns_400_when_no_fitting_map(
        self,
        mock_get_group,
        mock_fitting_404,
        _mock_fitting_maps,
        _mock_member_groups,
        _mock_user_rows,
        _mock_kpis,
        _mock_annotate,
        _mock_render,
    ):
        selected_group = SimpleNamespace(id=1, name="Group", entries=Mock())
        mock_get_group.return_value = ([selected_group], selected_group)
        mock_fitting_404.return_value = (
            SimpleNamespace(id=1, name="Fit"),
            None,  # no fitting_map
            SimpleNamespace(id=2),
        )
        req = self._req(path="/summary/fitting/1/")
        response = views.summary_fitting_detail_view(req, fitting_id=1)
        self.assertEqual(response.status_code, 400)

    @patch("mastery.views.summary.render", return_value=HttpResponse("ok"))
    @patch("mastery.views.summary._annotate_member_detail_pilots", return_value=[])
    @patch("mastery.views.summary._build_fitting_kpis", return_value={})
    @patch("mastery.views.summary._build_fitting_user_rows", return_value=[])
    @patch("mastery.views.summary._build_member_groups_for_summary", return_value=[])
    @patch("mastery.views.summary.FittingSkillsetMap.objects.select_related")
    @patch("mastery.views.summary._get_accessible_fitting_or_404")
    @patch("mastery.views.summary._get_selected_summary_group")
    @patch("mastery.views.summary.pilot_progress_service")
    def test_summary_fitting_detail_view_renders_with_valid_fitting_map(
        self,
        mock_pilot_service,
        mock_get_group,
        mock_fitting_404,
        _mock_fitting_maps,
        _mock_member_groups,
        _mock_user_rows,
        _mock_kpis,
        _mock_annotate,
        mock_render,
    ):
        selected_group = SimpleNamespace(id=1, name="Group", entries=Mock())
        mock_get_group.return_value = ([selected_group], selected_group)
        fitting_map = SimpleNamespace(skillset=SimpleNamespace(id=10))
        mock_fitting_404.return_value = (
            SimpleNamespace(id=1, name="Fit"),
            fitting_map,
            SimpleNamespace(id=2),
        )
        mock_pilot_service.export_mode_choices.return_value = []
        req = self._req(path="/summary/fitting/1/")
        response = views.summary_fitting_detail_view(req, fitting_id=1)
        self.assertEqual(response.status_code, 200)

    # -- summary_list_view ---------------------------------------------------

    @patch("mastery.views.summary.render", return_value=HttpResponse("ok"))
    @patch("mastery.views.summary._build_doctrine_summary")
    @patch("mastery.views.summary._build_member_groups_for_summary", return_value=[])
    @patch("mastery.views.summary.FittingSkillsetMap.objects.select_related")
    @patch("mastery.views.summary.pilot_access_service")
    @patch("mastery.views.summary._get_selected_summary_group")
    def test_summary_list_view_renders_successfully(
        self,
        mock_get_group,
        mock_pilot_access,
        _mock_fitting_maps,
        _mock_member_groups,
        mock_build_doctrine_summary,
        mock_render,
    ):
        selected_group = SimpleNamespace(id=1, name="Group", entries=Mock())
        mock_get_group.return_value = ([selected_group], selected_group)
        doctrine = SimpleNamespace(
            id=1,
            name="Alpha",
            fittings=Mock(),
        )
        doctrine.fittings.all.return_value = []
        mock_pilot_access.accessible_doctrines.return_value.prefetch_related.return_value = [doctrine]
        _mock_fitting_maps.return_value.all.return_value = []
        mock_build_doctrine_summary.return_value = {"doctrine": doctrine, "fittings": []}

        req = self._req(path="/summary/")
        response = views.summary_list_view(req)
        self.assertEqual(response.status_code, 200)
        context = mock_render.call_args[0][2]
        self.assertIn("doctrine_summaries", context)

    # -- summary_settings_view GET -------------------------------------------

    @patch("mastery.views.summary.render", return_value=HttpResponse("ok"))
    @patch("mastery.views.summary._summary_entity_catalog")
    @patch("mastery.views.summary._get_selected_summary_group")
    def test_summary_settings_view_get_renders_template(
        self,
        mock_get_group,
        mock_catalog,
        mock_render,
    ):
        mock_get_group.return_value = ([], None)
        mock_catalog.return_value = ([], [])

        req = self._req(path="/summary/settings/")
        response = views.summary_settings_view(req)
        self.assertEqual(response.status_code, 200)
        context = mock_render.call_args[0][2]
        self.assertIn("summary_groups", context)

    # -- summary_settings_view POST create_group -----------------------------

    def test_summary_settings_view_post_create_group_returns_400_when_no_name(self):
        req = self._req(method="post", path="/summary/settings/", data={"action": "create_group", "name": ""})
        response = views.summary_settings_view(req)
        self.assertEqual(response.status_code, 400)

    @patch("mastery.views.summary.redirect", return_value=HttpResponse(status=302))
    @patch("mastery.views.summary.messages")
    @patch("mastery.views.summary.SummaryAudienceGroup.objects.create")
    def test_summary_settings_view_post_create_group_creates_and_redirects(
        self,
        mock_create,
        mock_messages,
        mock_redirect,
    ):
        req = self._req(method="post", path="/summary/settings/", data={"action": "create_group", "name": "My Group"})
        response = views.summary_settings_view(req)
        mock_create.assert_called_once()
        mock_redirect.assert_called_once_with("mastery:summary_settings")
        self.assertEqual(response.status_code, 302)

    # -- summary_settings_view POST delete_group -----------------------------

    @patch("mastery.views.summary.redirect", return_value=HttpResponse(status=302))
    @patch("mastery.views.summary.messages")
    @patch("mastery.views.summary.get_object_or_404")
    def test_summary_settings_view_post_delete_group_deletes_and_redirects(
        self,
        mock_get_object_or_404,
        mock_messages,
        mock_redirect,
    ):
        group = Mock()
        mock_get_object_or_404.return_value = group
        req = self._req(
            method="post",
            path="/summary/settings/",
            data={"action": "delete_group", "group_id": "5"},
        )
        response = views.summary_settings_view(req)
        group.delete.assert_called_once()
        self.assertEqual(response.status_code, 302)

    # -- summary_settings_view POST add_entry validation ---------------------

    @patch("mastery.views.summary.get_object_or_404")
    def test_summary_settings_view_post_add_entry_returns_400_for_invalid_type(self, mock_get_object_or_404):
        mock_get_object_or_404.return_value = Mock()
        req = self._req(
            method="post",
            path="/summary/settings/",
            data={"action": "add_entry", "group_id": "1", "entity_type": "invalid", "entity_id": "123"},
        )
        response = views.summary_settings_view(req)
        self.assertEqual(response.status_code, 400)

    @patch("mastery.views.summary.get_object_or_404")
    def test_summary_settings_view_post_add_entry_returns_400_for_invalid_id(self, mock_get_object_or_404):
        mock_get_object_or_404.return_value = Mock()
        req = self._req(
            method="post",
            path="/summary/settings/",
            data={"action": "add_entry", "group_id": "1", "entity_type": "corporation", "entity_id": "notanint"},
        )
        response = views.summary_settings_view(req)
        self.assertEqual(response.status_code, 400)

    def test_summary_settings_view_post_unsupported_action_returns_400(self):
        req = self._req(method="post", path="/summary/settings/", data={"action": "explode"})
        response = views.summary_settings_view(req)
        self.assertEqual(response.status_code, 400)

    # -- summary_settings_view POST delete_entry -----------------------------

    @patch("mastery.views.summary.redirect")
    @patch("mastery.views.summary.messages")
    @patch("mastery.views.summary.get_object_or_404")
    def test_summary_settings_view_post_delete_entry_deletes_and_redirects(
        self,
        mock_get_object_or_404,
        mock_messages,
        mock_redirect,
    ):
        entry = Mock()
        entry.group_id = 7
        mock_get_object_or_404.return_value = entry
        inner_redirect = Mock()
        inner_redirect.url = "/summary/settings/"
        mock_redirect.return_value = inner_redirect

        req = self._req(
            method="post",
            path="/summary/settings/",
            data={"action": "delete_entry", "entry_id": "3"},
        )
        response = views.summary_settings_view(req)
        entry.delete.assert_called_once()


# ---------------------------------------------------------------------------
# Pilot views
# ---------------------------------------------------------------------------


class TestPilotViews(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def _req(self, path="/", method="get", **kwargs):
        req = getattr(self.factory, method)(path, **kwargs)
        req.user = _view_user()
        return req

    # -- pilot_fitting_detail_view -------------------------------------------

    @patch("mastery.views.pilot._get_accessible_fitting_or_404")
    def test_pilot_fitting_detail_view_returns_400_when_no_fitting_map(self, mock_fitting_404):
        fitting = SimpleNamespace(id=1, name="Fit", ship_type=SimpleNamespace(name="Drake"))
        mock_fitting_404.return_value = (fitting, None, SimpleNamespace(id=2))

        req = self._req(path="/fitting/1/")
        response = views.pilot_fitting_detail_view(req, fitting_id=1)
        self.assertEqual(response.status_code, 400)
        self.assertIn("No skillset configured", response.content.decode())

    @patch("mastery.views.pilot.render", return_value=HttpResponse("ok"))
    @patch("mastery.views.pilot.pilot_progress_service")
    @patch("mastery.views.pilot._get_pilot_detail_characters")
    @patch("mastery.views.pilot._get_accessible_fitting_or_404")
    def test_pilot_fitting_detail_view_renders_when_fitting_map_present(
        self,
        mock_fitting_404,
        mock_get_chars,
        mock_progress_service,
        mock_render,
    ):
        fitting = SimpleNamespace(id=1, name="Fit", ship_type=SimpleNamespace(name="Drake"))
        skillset = SimpleNamespace(id=10)
        fitting_map = SimpleNamespace(skillset=skillset, doctrine_map=None)
        doctrine = SimpleNamespace(id=2)
        mock_fitting_404.return_value = (fitting, fitting_map, doctrine)
        mock_get_chars.return_value = []
        mock_progress_service.export_mode_choices.return_value = [("recommended", "Recommended")]
        mock_progress_service.EXPORT_MODE_RECOMMENDED = "recommended"
        mock_progress_service.normalize_export_language.return_value = "en"

        req = self._req(path="/fitting/1/")
        response = views.pilot_fitting_detail_view(req, fitting_id=1)
        self.assertEqual(response.status_code, 200)

    @patch("mastery.views.pilot.render", return_value=HttpResponse("ok"))
    @patch("mastery.views.pilot.pilot_progress_service")
    @patch("mastery.views.pilot._get_pilot_detail_characters")
    @patch("mastery.views.pilot._get_accessible_fitting_or_404")
    def test_pilot_fitting_detail_view_filters_rows_and_defaults_to_can_fly_now(
        self,
        mock_fitting_404,
        mock_get_chars,
        mock_progress_service,
        mock_render,
    ):
        def _progress(can_fly, required_pct, recommended_pct, status_label):
            return {
                "can_fly": can_fly,
                "required_pct": required_pct,
                "recommended_pct": recommended_pct,
                "status_label": status_label,
                "status_class": "success" if can_fly else "warning",
                "missing_required": [],
                "missing_recommended": [],
                "missing_required_count": 0,
                "missing_recommended_count": 0,
                "total_missing_sp": 0,
                "mode_stats": {"recommended": {"coverage_pct": recommended_pct, "total_missing_sp": 0, "total_missing_time": None}},
            }

        fitting = SimpleNamespace(id=1, name="Fit", ship_type=SimpleNamespace(name="Drake"))
        fitting_map = SimpleNamespace(skillset=SimpleNamespace(id=10), doctrine_map=None)
        doctrine = SimpleNamespace(id=2)
        mock_fitting_404.return_value = (fitting, fitting_map, doctrine)
        characters = [
            SimpleNamespace(id=1, eve_character=SimpleNamespace(character_name="Flyable")),
            SimpleNamespace(id=2, eve_character=SimpleNamespace(character_name="Elite")),
            SimpleNamespace(id=3, eve_character=SimpleNamespace(character_name="Almost Req")),
            SimpleNamespace(id=4, eve_character=SimpleNamespace(character_name="Almost Elite")),
        ]
        mock_get_chars.return_value = characters
        mock_progress_service.build_for_character.side_effect = [
            _progress(True, 100, 60, "Flyable"),
            _progress(True, 100, 100, "Elite ready"),
            _progress(False, 95, 50, "Almost ready"),
            _progress(True, 100, 80, "Flyable"),
        ]
        mock_progress_service.export_mode_choices.return_value = [("recommended", "Recommended")]
        mock_progress_service.EXPORT_MODE_RECOMMENDED = "recommended"
        mock_progress_service.normalize_export_language.return_value = "en"
        mock_progress_service.localize_missing_rows.side_effect = lambda rows, language: rows
        mock_progress_service.build_export_lines.return_value = []
        mock_progress_service.build_skill_plan_summary.return_value = None
        mock_progress_service.export_language_choices.return_value = [("en", "English")]

        req = self._req(path="/fitting/1/")
        response = views.pilot_fitting_detail_view(req, fitting_id=1)

        self.assertEqual(response.status_code, 200)
        context = mock_render.call_args[0][2]
        self.assertEqual(context["selected_character_filter"], "can_fly_now")
        self.assertEqual([row["character"].id for row in context["filtered_character_rows"]], [1, 2, 4])
        self.assertEqual(context["selected_character"].id, 1)
        choice_map = dict(context["character_filter_choices"])
        self.assertIn("can_fly_now", choice_map)
        self.assertTrue(choice_map["can_fly_now"].endswith("(3)"))
        self.assertNotIn("needs_training", choice_map)

    @patch("mastery.views.pilot.render", return_value=HttpResponse("ok"))
    @patch("mastery.views.pilot.pilot_progress_service")
    @patch("mastery.views.pilot._get_pilot_detail_characters")
    @patch("mastery.views.pilot._get_accessible_fitting_or_404")
    def test_pilot_fitting_detail_view_switches_to_all_when_can_fly_filter_is_empty(
        self,
        mock_fitting_404,
        mock_get_chars,
        mock_progress_service,
        mock_render,
    ):
        """Test that when can_fly filter returns no results, it switches to 'all' filter."""
        def _progress(can_fly, required_pct, recommended_pct, status_label):
            return {
                "can_fly": can_fly,
                "required_pct": required_pct,
                "recommended_pct": recommended_pct,
                "status_label": status_label,
                "status_class": "success" if can_fly else "warning",
                "missing_required": [],
                "missing_recommended": [],
                "missing_required_count": 0,
                "missing_recommended_count": 0,
                "total_missing_sp": 0,
                "mode_stats": {"recommended": {"coverage_pct": recommended_pct, "total_missing_sp": 0, "total_missing_time": None}},
            }

        fitting = SimpleNamespace(id=1, name="Fit", ship_type=SimpleNamespace(name="Drake"))
        fitting_map = SimpleNamespace(skillset=SimpleNamespace(id=10), doctrine_map=None)
        doctrine = SimpleNamespace(id=2)
        mock_fitting_404.return_value = (fitting, fitting_map, doctrine)
        characters = [
            SimpleNamespace(id=1, eve_character=SimpleNamespace(character_name="Training")),
            SimpleNamespace(id=2, eve_character=SimpleNamespace(character_name="Almost Ready")),
        ]
        mock_get_chars.return_value = characters
        # All characters need training (can_fly=False)
        mock_progress_service.build_for_character.side_effect = [
            _progress(False, 50, 60, "Training"),
            _progress(False, 95, 50, "Almost ready"),
        ]
        mock_progress_service.export_mode_choices.return_value = [("recommended", "Recommended")]
        mock_progress_service.EXPORT_MODE_RECOMMENDED = "recommended"
        mock_progress_service.normalize_export_language.return_value = "en"
        mock_progress_service.localize_missing_rows.side_effect = lambda rows, language: rows
        mock_progress_service.build_export_lines.return_value = []
        mock_progress_service.build_skill_plan_summary.return_value = None
        mock_progress_service.export_language_choices.return_value = [("en", "English")]

        req = self._req(path="/fitting/1/")
        response = views.pilot_fitting_detail_view(req, fitting_id=1)

        self.assertEqual(response.status_code, 200)
        context = mock_render.call_args[0][2]
        # Filter should have switched from "can_fly_now" to "all"
        self.assertEqual(context["selected_character_filter"], "all")
        # All characters should be visible
        self.assertEqual([row["character"].id for row in context["filtered_character_rows"]], [1, 2])
        # The empty can_fly_now option must not be presented
        choice_map = dict(context["character_filter_choices"])
        self.assertNotIn("can_fly_now", choice_map)
        self.assertIn("all", choice_map)
        self.assertTrue(choice_map["all"].endswith("(2)"))
        # First character should be selected
        self.assertEqual(context["selected_character"].id, 1)

    @patch("mastery.views.pilot.render", return_value=HttpResponse("ok"))
    @patch("mastery.views.pilot.pilot_progress_service")
    @patch("mastery.views.pilot._get_pilot_detail_characters")
    @patch("mastery.views.pilot._get_accessible_fitting_or_404")
    def test_pilot_fitting_detail_view_keeps_selected_character_visible_outside_filter(
        self,
        mock_fitting_404,
        mock_get_chars,
        mock_progress_service,
        mock_render,
    ):
        def _progress(can_fly, required_pct, recommended_pct, status_label):
            return {
                "can_fly": can_fly,
                "required_pct": required_pct,
                "recommended_pct": recommended_pct,
                "status_label": status_label,
                "status_class": "success" if can_fly else "warning",
                "missing_required": [],
                "missing_recommended": [],
                "missing_required_count": 0,
                "missing_recommended_count": 0,
                "total_missing_sp": 0,
                "mode_stats": {"recommended": {"coverage_pct": recommended_pct, "total_missing_sp": 0, "total_missing_time": None}},
            }

        fitting = SimpleNamespace(id=1, name="Fit", ship_type=SimpleNamespace(name="Drake"))
        fitting_map = SimpleNamespace(skillset=SimpleNamespace(id=10), doctrine_map=None)
        doctrine = SimpleNamespace(id=2)
        mock_fitting_404.return_value = (fitting, fitting_map, doctrine)
        characters = [
            SimpleNamespace(id=1, eve_character=SimpleNamespace(character_name="Flyable")),
            SimpleNamespace(id=3, eve_character=SimpleNamespace(character_name="Almost Req")),
        ]
        mock_get_chars.return_value = characters
        mock_progress_service.build_for_character.side_effect = [
            _progress(True, 100, 60, "Flyable"),
            _progress(False, 95, 50, "Almost ready"),
        ]
        mock_progress_service.export_mode_choices.return_value = [("recommended", "Recommended")]
        mock_progress_service.EXPORT_MODE_RECOMMENDED = "recommended"
        mock_progress_service.normalize_export_language.return_value = "en"
        mock_progress_service.localize_missing_rows.side_effect = lambda rows, language: rows
        mock_progress_service.build_export_lines.return_value = []
        mock_progress_service.build_skill_plan_summary.return_value = None
        mock_progress_service.export_language_choices.return_value = [("en", "English")]

        req = self._req(path="/fitting/1/?character_id=3&character_filter=can_fly_now")
        response = views.pilot_fitting_detail_view(req, fitting_id=1)

        self.assertEqual(response.status_code, 200)
        context = mock_render.call_args[0][2]
        # Focused pilot outside can_fly_now should not be shown in filtered rows
        self.assertEqual(context["selected_character_filter"], "can_fly_now")
        self.assertEqual([row["character"].id for row in context["filtered_character_rows"]], [1])
        self.assertEqual(context["selected_character"].id, 1)

    # -- pilot_fitting_skillplan_export_view ---------------------------------

    @patch("mastery.views.pilot._get_accessible_fitting_or_404")
    def test_skillplan_export_returns_400_when_no_fitting_map(self, mock_fitting_404):
        mock_fitting_404.return_value = (SimpleNamespace(id=1), None, None)
        req = self._req(path="/fitting/1/export/")
        response = views.pilot_fitting_skillplan_export_view(req, fitting_id=1)
        self.assertEqual(response.status_code, 400)

    @patch("mastery.views.pilot._get_accessible_fitting_or_404")
    def test_skillplan_export_returns_400_when_no_character_id(self, mock_fitting_404):
        mock_fitting_404.return_value = (
            SimpleNamespace(id=1),
            SimpleNamespace(skillset=SimpleNamespace(id=10)),
            None,
        )
        req = self._req(path="/fitting/1/export/")
        response = views.pilot_fitting_skillplan_export_view(req, fitting_id=1)
        self.assertEqual(response.status_code, 400)
        self.assertIn("character_id is required", response.content.decode())

    @patch("mastery.views.pilot._get_accessible_fitting_or_404")
    def test_skillplan_export_returns_400_for_invalid_character_id(self, mock_fitting_404):
        mock_fitting_404.return_value = (
            SimpleNamespace(id=1),
            SimpleNamespace(skillset=SimpleNamespace(id=10)),
            None,
        )
        req = self._req(path="/fitting/1/export/?character_id=notanint")
        response = views.pilot_fitting_skillplan_export_view(req, fitting_id=1)
        self.assertEqual(response.status_code, 400)
        self.assertIn("invalid character_id", response.content.decode())

    @patch("mastery.views.pilot._get_pilot_detail_characters")
    @patch("mastery.views.pilot._get_accessible_fitting_or_404")
    def test_skillplan_export_returns_400_when_character_not_found(
        self, mock_fitting_404, mock_get_chars
    ):
        mock_fitting_404.return_value = (
            SimpleNamespace(id=1),
            SimpleNamespace(skillset=SimpleNamespace(id=10)),
            None,
        )
        char_qs = Mock()
        char_qs.filter.return_value.first.return_value = None
        mock_get_chars.return_value = char_qs

        req = self._req(path="/fitting/1/export/?character_id=99")
        response = views.pilot_fitting_skillplan_export_view(req, fitting_id=1)
        self.assertEqual(response.status_code, 400)
        self.assertIn("character not found", response.content.decode())

    @patch("mastery.views.pilot.pilot_progress_service")
    @patch("mastery.views.pilot._get_pilot_detail_characters")
    @patch("mastery.views.pilot._get_accessible_fitting_or_404")
    def test_skillplan_export_returns_text_file_for_valid_request(
        self,
        mock_fitting_404,
        mock_get_chars,
        mock_progress_service,
    ):
        fitting = SimpleNamespace(id=5)
        skillset = SimpleNamespace(id=10)
        fitting_map = SimpleNamespace(skillset=skillset)
        mock_fitting_404.return_value = (fitting, fitting_map, None)

        char = SimpleNamespace(id=99)
        char_qs = Mock()
        char_qs.filter.return_value.first.return_value = char
        mock_get_chars.return_value = char_qs

        mock_progress_service.EXPORT_MODE_RECOMMENDED = "recommended"
        mock_progress_service.normalize_export_language.return_value = "en"
        mock_progress_service.export_mode_choices.return_value = [("recommended", "Recommended")]
        mock_progress_service.build_for_character.return_value = {"can_fly": True}
        mock_progress_service.build_export_lines.return_value = ["Skill A 5", "Skill B 4"]

        req = self._req(path="/fitting/5/export/?character_id=99")
        response = views.pilot_fitting_skillplan_export_view(req, fitting_id=5)

        self.assertEqual(response.status_code, 200)
        self.assertIn("text/plain", response.get("Content-Type", ""))
        self.assertIn("attachment", response.get("Content-Disposition", ""))
        self.assertIn("Skill A 5", response.content.decode())

    # -- index ---------------------------------------------------------------

    @patch("mastery.views.pilot.render", return_value=HttpResponse("ok"))
    @patch("mastery.views.pilot.FittingSkillsetMap.objects.select_related")
    @patch("mastery.views.pilot._get_member_characters")
    @patch("mastery.views.pilot.pilot_access_service")
    def test_pilot_index_renders_empty_cards_when_no_fittings(
        self,
        mock_access_service,
        mock_get_chars,
        mock_fitting_maps,
        mock_render,
    ):
        doctrine = SimpleNamespace(id=1, name="Alpha", fittings=Mock())
        doctrine.fittings.all.return_value = []
        mock_access_service.accessible_doctrines.return_value = [doctrine]
        mock_get_chars.return_value = []
        mock_fitting_maps.return_value.all.return_value = []

        req = self._req(path="/")
        response = views.index(req)
        self.assertEqual(response.status_code, 200)
        context = mock_render.call_args[0][2]
        self.assertEqual(context["doctrine_cards"], [])
        self.assertEqual(context["configured_fittings_count"], 0)
