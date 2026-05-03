import json
from datetime import datetime, timedelta, timezone as dt_timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.http import HttpResponse
from django.http import JsonResponse
from django.template import Context, Template
from django.template.loader import render_to_string
from django.test import RequestFactory, SimpleTestCase
from django.utils.translation import override

from mastery import views
from mastery.models import FittingSkillsetMap
from mastery.templatetags.skill_render import (
    active_skills,
    group_has_active_skills,
    group_has_blacklisted_skills,
    grouped_has_active_skills,
)
from mastery.views import _build_fitting_skills_ajax_response, _group_preview_skills, _resolve_row_levels
from mastery.views.summary_helpers import (
    _approved_fitting_maps,
    _annotate_member_detail_pilots,
    _build_member_groups_for_summary,
    _build_doctrine_summary,
    _build_doctrine_kpis,
    _build_fitting_kpis,
    _build_fitting_user_rows,
    _get_member_characters,
    _get_pilot_detail_characters,
    _get_selected_summary_group,
    _get_summary_group_by_id,
    _is_approved_fitting_map,
    _missing_skillset_error,
    _parse_activity_days,
    _parse_training_days,
    _progress_for_character,
    _prime_summary_character_skills_cache_context,
    _summary_entity_catalog,
    _summary_group_users,
)


def _view_user():
    return SimpleNamespace(
        is_authenticated=True,
        has_perm=lambda _perm: True,
        has_perms=lambda _perms: True,
    )


class TestViewHelpers(SimpleTestCase):
    def test_debug_ratio_template_handles_missing_progress_cache_misses(self):
        template = Template(
            """
            {% with p0=snapshot.metrics.p0_metrics.summary_view %}
                {% with p0_hits=p0.progress_cache_hits|default:0 p0_misses=p0.progress_cache_misses|default:0 %}
                    {% with total=p0_hits|add:p0_misses %}
                        {% if total %}
                            {% widthratio p0_hits total 100 %}
                        {% else %}
                            -
                        {% endif %}
                    {% endwith %}
                {% endwith %}
            {% endwith %}
            """
        )

        output = template.render(
            Context(
                {
                    "snapshot": {
                        "metrics": {
                            "p0_metrics": {
                                "summary_view": {
                                    "progress_cache_hits": 3,
                                    # progress_cache_misses missing on purpose
                                }
                            }
                        }
                    }
                }
            )
        )

        self.assertIn("100", output)

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

    def test_active_skills_returns_only_non_blacklisted_rows(self):
        rows = [
            {"skill_name": "A", "is_blacklisted": True},
            {"skill_name": "B", "is_blacklisted": False},
            {"skill_name": "C", "is_blacklisted": False},
        ]

        self.assertEqual([row["skill_name"] for row in active_skills(rows)], ["B", "C"])

    def test_grouped_has_active_skills_detects_visible_preview_rows(self):
        grouped = {
            "Engineering": {
                "skills": [
                    {"skill_name": "A", "is_blacklisted": True},
                    {"skill_name": "B", "is_blacklisted": False},
                ]
            }
        }

        self.assertTrue(grouped_has_active_skills(grouped))

    def test_grouped_has_active_skills_returns_false_when_all_rows_blacklisted(self):
        grouped = {
            "Engineering": {
                "skills": [
                    {"skill_name": "A", "is_blacklisted": True},
                ]
            }
        }

        self.assertFalse(grouped_has_active_skills(grouped))

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

    def test_clone_grade_badge_partial_renders_greek_symbols_with_accessible_label(self):
        alpha_html = render_to_string(
            "mastery/partials/_clone_grade_badge.html",
            {"requires_omega": False},
        )
        omega_html = render_to_string(
            "mastery/partials/_clone_grade_badge.html",
            {"requires_omega": True},
        )

        self.assertIn("&alpha;", alpha_html)
        self.assertIn("visually-hidden", alpha_html)
        self.assertIn("Alpha", alpha_html)
        self.assertIn("background-color:#dbeafe", alpha_html)
        self.assertIn("--mastery-clone-badge-bg:#dbeafe", alpha_html)
        self.assertIn('data-bs-tooltip="aa-mastery"', alpha_html)
        self.assertIn('data-bs-title="Alpha clone compatible"', alpha_html)
        self.assertIn("&Omega;", omega_html)
        self.assertIn("Omega", omega_html)
        self.assertIn("background-color:#fff3cd", omega_html)
        self.assertIn("--mastery-clone-badge-bg:#fff3cd", omega_html)
        self.assertIn('data-bs-title="Requires Omega clone"', omega_html)

    def test_clone_grade_badge_partial_translates_tooltip_in_french(self):
        with override("fr_FR"):
            omega_html = render_to_string(
                "mastery/partials/_clone_grade_badge.html",
                {"requires_omega": True},
            )

        self.assertIn('data-bs-title="Clone Omega requis"', omega_html)

    def test_recommended_plan_clone_badge_switches_between_alpha_and_omega(self):
        template = Template(
            """
            {% if recommended_plan_alpha_compatible %}
                {% include 'mastery/partials/_clone_grade_badge.html' with requires_omega=False %}
            {% else %}
                {% include 'mastery/partials/_clone_grade_badge.html' with requires_omega=True %}
            {% endif %}
            """
        )

        alpha_output = template.render(Context({"recommended_plan_alpha_compatible": True}))
        omega_output = template.render(Context({"recommended_plan_alpha_compatible": False}))

        self.assertIn("mastery-clone-badge-alpha", alpha_output)
        self.assertNotIn("mastery-clone-badge-omega", alpha_output)
        self.assertIn("mastery-clone-badge-omega", omega_output)

    def test_missing_skill_rows_show_omega_badge_only_for_omega_targets(self):
        template = Template(
            """
            {% for skill in skills %}
                <span class="badge mastery-level-badge-target">{{ skill.target_level }}</span>
                {% if skill.target_requires_omega %}
                    {% include 'mastery/partials/_clone_grade_badge.html' with requires_omega=True size='sm' %}
                {% endif %}
            {% endfor %}
            """
        )

        output = template.render(
            Context(
                {
                    "skills": [
                        {"target_level": 4, "target_requires_omega": False},
                        {"target_level": 5, "target_requires_omega": True},
                    ]
                }
            )
        )

        self.assertEqual(output.count("mastery-clone-badge-omega"), 1)
        self.assertNotIn("mastery-clone-badge-alpha", output)

    def test_group_preview_skills_propagates_clone_grade_flags_to_row_payload(self):
        mocked_skill = SimpleNamespace(
            id=404,
            name="Long Range Targeting",
            description="",
            group=SimpleNamespace(id=42, name="Targeting"),
        )

        with patch("mastery.views.common.ItemType.objects.select_related") as mock_select_related, patch(
            "mastery.views.common.TypeDogma.objects.filter"
        ) as mock_dogma_filter:
            mock_select_related.return_value.filter.return_value = [mocked_skill]
            mock_dogma_filter.return_value.values.return_value = []

            grouped = _group_preview_skills(
                [
                    {
                        "skill_type_id": 404,
                        "required_level": 3,
                        "recommended_level": 4,
                        "required_requires_omega": False,
                        "recommended_requires_omega": True,
                        "requires_omega": True,
                    }
                ]
            )

        row = grouped["Targeting"]["skills"][0]
        self.assertFalse(row["required_requires_omega"])
        self.assertTrue(row["recommended_requires_omega"])
        self.assertTrue(row["requires_omega"])

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

    @patch("mastery.views.common._build_plan_kpis", return_value={"required_plan_omega_skill_count": 2})
    @patch("mastery.views.common._get_skill_name_options", return_value=[])
    @patch("mastery.views.common._group_preview_skills", return_value={})
    @patch("mastery.views.common.doctrine_skill_service.preview_fitting")
    def test_build_fitting_preview_context_exposes_plan_kpis(
        self,
        mock_preview_fitting,
        _mock_group_preview_skills,
        _mock_get_skill_name_options,
        _mock_build_plan_kpis,
    ):
        from mastery.views.common import _build_fitting_preview_context

        mock_preview_fitting.return_value = {
            "effective_mastery_level": 4,
            "skills": [{"skill_type_id": 1, "is_blacklisted": False}],
        }

        context = _build_fitting_preview_context(
            fitting=SimpleNamespace(id=1),
            doctrine_map=SimpleNamespace(default_mastery_level=4),
            fitting_map=None,
        )

        self.assertEqual(context["required_plan_omega_skill_count"], 2)

    @patch(
        "mastery.views.common._build_plan_kpis",
        return_value={
            "required_plan_alpha_compatible": True,
            "recommended_plan_alpha_compatible": False,
        },
    )
    @patch("mastery.views.common._get_skill_name_options", return_value=[])
    @patch("mastery.views.common._group_preview_skills", return_value={})
    @patch("mastery.views.common.doctrine_skill_service.preview_fitting")
    def test_build_fitting_preview_context_exposes_alpha_conversion_availability(
        self,
        mock_preview_fitting,
        _mock_group_preview_skills,
        _mock_get_skill_name_options,
        _mock_build_plan_kpis,
    ):
        from mastery.views.common import _build_fitting_preview_context

        mock_preview_fitting.return_value = {
            "effective_mastery_level": 4,
            "skills": [{"skill_type_id": 1, "is_blacklisted": False}],
        }

        context = _build_fitting_preview_context(
            fitting=SimpleNamespace(id=1),
            doctrine_map=SimpleNamespace(default_mastery_level=4),
            fitting_map=None,
        )

        self.assertTrue(context["can_make_recommended_plan_alpha_compatible"])

    @patch(
        "mastery.views.common._build_plan_kpis",
        return_value={
            "required_plan_alpha_compatible": False,
            "recommended_plan_alpha_compatible": False,
        },
    )
    @patch("mastery.views.common._get_skill_name_options", return_value=[])
    @patch("mastery.views.common._group_preview_skills", return_value={})
    @patch("mastery.views.common.doctrine_skill_service.preview_fitting")
    def test_build_fitting_preview_context_hides_alpha_conversion_when_required_needs_omega(
        self,
        mock_preview_fitting,
        _mock_group_preview_skills,
        _mock_get_skill_name_options,
        _mock_build_plan_kpis,
    ):
        from mastery.views.common import _build_fitting_preview_context

        mock_preview_fitting.return_value = {
            "effective_mastery_level": 4,
            "skills": [{"skill_type_id": 1, "is_blacklisted": False}],
        }

        context = _build_fitting_preview_context(
            fitting=SimpleNamespace(id=1),
            doctrine_map=SimpleNamespace(default_mastery_level=4),
            fitting_map=None,
        )

        self.assertFalse(context["can_make_recommended_plan_alpha_compatible"])

    @patch("mastery.views.common.TypeDogma.objects.filter")
    def test_build_plan_kpis_includes_alpha_omega_compatibility_counts(self, mock_dogma_filter):
        from mastery.views.common import _build_plan_kpis

        mock_dogma_filter.return_value.values.return_value = []

        kpis = _build_plan_kpis(
            [
                {
                    "skill_type_id": 1,
                    "required_level": 3,
                    "recommended_level": 4,
                    "required_requires_omega": False,
                    "recommended_requires_omega": False,
                },
                {
                    "skill_type_id": 2,
                    "required_level": 2,
                    "recommended_level": 2,
                    "required_requires_omega": True,
                    "recommended_requires_omega": True,
                },
                {
                    "skill_type_id": 3,
                    "required_level": 0,
                    "recommended_level": 1,
                    "required_requires_omega": False,
                    "recommended_requires_omega": True,
                },
            ]
        )

        self.assertEqual(kpis["required_plan_skill_count"], 2)
        self.assertEqual(kpis["required_plan_omega_skill_count"], 1)
        self.assertFalse(kpis["required_plan_alpha_compatible"])

        self.assertEqual(kpis["recommended_plan_skill_count"], 3)
        self.assertEqual(kpis["recommended_plan_omega_skill_count"], 2)
        self.assertFalse(kpis["recommended_plan_alpha_compatible"])


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
        mock_generate.assert_called_once()
        call_args = mock_generate.call_args
        self.assertEqual(call_args[0], (doctrine_map, fitting))
        self.assertEqual(call_args[1]["modified_by"], request.user)
        self.assertEqual(call_args[1]["status"], FittingSkillsetMap.ApprovalStatus.IN_PROGRESS)
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
        mock_generate.assert_called_once()
        call_args = mock_generate.call_args
        self.assertEqual(call_args[0], (doctrine_map, fitting))
        self.assertEqual(call_args[1]["modified_by"], request.user)
        self.assertEqual(call_args[1]["status"], FittingSkillsetMap.ApprovalStatus.IN_PROGRESS)
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

    @patch("mastery.views.fitting._finalize_fitting_skills_action")
    @patch("mastery.views.fitting.doctrine_skill_service.generate_for_fitting")
    @patch("mastery.views.fitting.control_service.set_recommended_level")
    @patch("mastery.views.fitting.doctrine_skill_service.preview_fitting")
    @patch("mastery.views.fitting._get_doctrine_and_map_for_fitting")
    def test_make_recommended_plan_alpha_compatible_updates_over_omega_recommended_levels(
        self,
        mock_get_doctrine_and_map,
        mock_preview,
        mock_set_recommended_level,
        mock_generate,
        mock_finalize,
    ):
        fitting = SimpleNamespace(id=1)
        doctrine = SimpleNamespace(id=2)
        doctrine_map = SimpleNamespace(id=3)
        mock_get_doctrine_and_map.return_value = (fitting, doctrine, doctrine_map, None)
        mock_preview.return_value = {
            "skills": [
                {
                    "skill_type_id": 55,
                    "required_requires_omega": False,
                    "recommended_level": 4,
                    "max_alpha_level": 3,
                    "is_blacklisted": False,
                },
                {
                    "skill_type_id": 66,
                    "required_requires_omega": False,
                    "recommended_level": 2,
                    "max_alpha_level": 2,
                    "is_blacklisted": False,
                },
            ]
        }
        mock_finalize.return_value = JsonResponse({"status": "ok"})

        request = self.factory.post(
            "/fitting/1/skills/make-alpha-compatible/",
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        request.user = _view_user()

        response = views.make_recommended_plan_alpha_compatible_view(request, fitting_id=1)

        self.assertEqual(response.status_code, 200)
        mock_preview.assert_called_once_with(doctrine_map=doctrine_map, fitting=fitting)
        mock_set_recommended_level.assert_called_once_with(
            fitting_id=1,
            skill_type_id=55,
            level=3,
        )
        mock_generate.assert_called_once()
        call_args = mock_generate.call_args
        self.assertEqual(call_args[0], (doctrine_map, fitting))
        self.assertEqual(call_args[1]["modified_by"], request.user)
        self.assertEqual(call_args[1]["status"], FittingSkillsetMap.ApprovalStatus.IN_PROGRESS)
        mock_finalize.assert_called_once_with(
            request,
            fitting=fitting,
            doctrine=doctrine,
            doctrine_map=doctrine_map,
            message="Recommended plan converted to Alpha compatibility",
        )

    @patch("mastery.views.fitting.doctrine_skill_service.preview_fitting")
    @patch("mastery.views.fitting._get_doctrine_and_map_for_fitting")
    def test_make_recommended_plan_alpha_compatible_rejects_when_required_skill_needs_omega(
        self,
        mock_get_doctrine_and_map,
        mock_preview,
    ):
        mock_get_doctrine_and_map.return_value = (
            SimpleNamespace(id=1),
            SimpleNamespace(id=2),
            SimpleNamespace(id=3),
            None,
        )
        mock_preview.return_value = {
            "skills": [
                {
                    "skill_type_id": 77,
                    "required_requires_omega": True,
                    "recommended_level": 4,
                    "max_alpha_level": 3,
                    "is_blacklisted": False,
                }
            ]
        }

        request = self.factory.post(
            "/fitting/1/skills/make-alpha-compatible/",
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        request.user = _view_user()

        response = views.make_recommended_plan_alpha_compatible_view(request, fitting_id=1)

        self.assertEqual(response.status_code, 400)
        payload = json.loads(response.content.decode())
        self.assertEqual(payload["status"], "error")
        self.assertIn("cannot be made Alpha compatible", payload["message"])


class TestFittingPreviewAccess(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    @patch("mastery.views.fitting._get_doctrine_and_map_for_fitting")
    def test_fitting_skills_preview_blocks_non_approved_for_basic_access(self, mock_get_doctrine):
        fitting = SimpleNamespace(id=1)
        doctrine = SimpleNamespace(id=2)
        doctrine_map = SimpleNamespace(id=3)
        fitting_map = SimpleNamespace(status=FittingSkillsetMap.ApprovalStatus.IN_PROGRESS)
        mock_get_doctrine.return_value = (fitting, doctrine, doctrine_map, fitting_map)

        request = self.factory.get("/fitting/1/preview/")
        request.user = SimpleNamespace(
            is_authenticated=True,
            has_perm=lambda perm: perm == "mastery.basic_access",
            has_perms=lambda perms: all(perm == "mastery.basic_access" for perm in perms),
        )

        response = views.fitting_skills_preview_view(request, fitting_id=1)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.content.decode(), "No approved skillset configured for this fitting yet")

    @patch("mastery.views.fitting.render", return_value=HttpResponse("ok"))
    @patch("mastery.views.fitting._build_fitting_preview_context", return_value={})
    @patch("mastery.views.fitting._get_doctrine_and_map_for_fitting")
    def test_fitting_skills_preview_allows_non_approved_for_manage_fittings(
        self,
        mock_get_doctrine,
        _mock_preview_context,
        _mock_render,
    ):
        fitting = SimpleNamespace(id=1)
        doctrine = SimpleNamespace(id=2)
        doctrine_map = SimpleNamespace(id=3)
        fitting_map = SimpleNamespace(status=FittingSkillsetMap.ApprovalStatus.IN_PROGRESS)
        mock_get_doctrine.return_value = (fitting, doctrine, doctrine_map, fitting_map)

        request = self.factory.get("/fitting/1/preview/")
        request.user = SimpleNamespace(
            is_authenticated=True,
            has_perm=lambda _perm: True,
            has_perms=lambda _perms: True,
        )

        response = views.fitting_skills_preview_view(request, fitting_id=1)

        self.assertEqual(response.status_code, 200)


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
        first_qs.first.return_value = SimpleNamespace(default_mastery_level=3, priority=8)
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
        self.assertEqual(context["doctrines"][0]["priority"], 8)
        self.assertFalse(context["doctrines"][1]["initialized"])
        self.assertIsNone(context["doctrines"][1]["default_mastery_level"])
        self.assertEqual(context["doctrines"][1]["priority"], 0)

    @patch("mastery.views.doctrine.render", return_value=HttpResponse("ok"))
    @patch("mastery.views.doctrine.FittingSkillsetMap.objects.select_related")
    @patch("mastery.views.doctrine.DoctrineSkillSetGroupMap.objects.filter")
    @patch("mastery.views.doctrine.Doctrine.objects.prefetch_related")
    def test_doctrine_detail_view_uses_override_or_doctrine_default_mastery(
        self,
        mock_prefetch_related,
        mock_doctrine_map_filter,
        mock_fitting_map_select_related,
        mock_render,
    ):
        approved_main = SimpleNamespace(id=99)
        approved_by = SimpleNamespace(
            username="approver",
            get_full_name=lambda: "",
            profile=SimpleNamespace(main_character=approved_main),
        )
        fitting_one = SimpleNamespace(id=10, name="Fit A", ship_type_type_id=100, ship_type=SimpleNamespace(name="Ship A"))
        fitting_two = SimpleNamespace(id=11, name="Fit B", ship_type_type_id=101, ship_type=SimpleNamespace(name="Ship B"))
        doctrine = SimpleNamespace(fittings=Mock())
        doctrine.fittings.all.return_value = [fitting_one, fitting_two]
        mock_prefetch_related.return_value.get.return_value = doctrine

        doctrine_map_qs = Mock()
        doctrine_map_qs.first.return_value = SimpleNamespace(default_mastery_level=3)
        mock_doctrine_map_filter.return_value = doctrine_map_qs

        first_fitting_map_qs = Mock()
        first_fitting_map_qs.first.return_value = SimpleNamespace(
            mastery_level=5,
            status=FittingSkillsetMap.ApprovalStatus.APPROVED,
            approved_by=approved_by,
            approved_at=datetime(2026, 4, 16, tzinfo=dt_timezone.utc),
            modified_by=None,
            modified_at=None,
        )
        second_fitting_map_qs = Mock()
        second_fitting_map_qs.first.return_value = None
        mock_fitting_map_select_related.return_value.filter.side_effect = [first_fitting_map_qs, second_fitting_map_qs]

        request = self.factory.get("/doctrines/1/")
        request.user = _view_user()

        response = views.doctrine_detail_view(request, doctrine_id=1)

        self.assertEqual(response.status_code, 200)
        context = mock_render.call_args[0][2]
        self.assertEqual(context["doctrine_default_mastery_level"], 3)
        self.assertEqual(context["fittings"][0]["effective_mastery_level"], 5)
        self.assertEqual(context["fittings"][1]["effective_mastery_level"], 3)
        self.assertEqual(context["fittings"][0]["approved_by_actor"]["display_name"], "approver")
        self.assertEqual(context["fittings"][0]["approved_by_actor"]["main_character"], approved_main)
        self.assertIsNone(context["fittings"][0]["modified_by_actor"])

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
        mock_sync.assert_called_once()
        call_args = mock_sync.call_args
        self.assertEqual(call_args[0], (doctrine,))
        self.assertEqual(call_args[1]["modified_by"], request.user)
        self.assertEqual(call_args[1]["status"], FittingSkillsetMap.ApprovalStatus.IN_PROGRESS)
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
        mock_sync.assert_called_once()
        call_args = mock_sync.call_args
        self.assertEqual(call_args[0], (doctrine,))
        self.assertEqual(call_args[1]["modified_by"], request.user)
        self.assertEqual(call_args[1]["status"], FittingSkillsetMap.ApprovalStatus.IN_PROGRESS)
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

    def test_update_fitting_priority_requires_post(self):
        request = self.factory.get("/fitting/1/priority/")
        request.user = _view_user()

        response = views.update_fitting_priority(request, fitting_id=1)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.content.decode(), "POST required")

    @patch("mastery.views.doctrine.messages")
    @patch("mastery.views.doctrine.redirect", return_value=HttpResponse("redirect"))
    @patch("mastery.views.doctrine.fitting_map_service.create_fitting_map")
    @patch("mastery.views.doctrine.doctrine_map_service.create_doctrine_map")
    @patch("mastery.views.doctrine.FittingSkillsetMap.objects.select_related")
    @patch("mastery.views.doctrine.DoctrineSkillSetGroupMap.objects.filter")
    @patch("mastery.views.doctrine.get_object_or_404")
    def test_update_fitting_priority_creates_missing_map_and_redirects(
        self,
        mock_get_object_or_404,
        mock_doctrine_map_filter,
        mock_fitting_map_select_related,
        mock_create_doctrine_map,
        mock_create_fitting_map,
        mock_redirect,
        mock_messages,
    ):
        fitting = SimpleNamespace(id=55, ship_type=SimpleNamespace(name="Drake"))
        doctrine = SimpleNamespace(id=9, name="Alpha")
        doctrine_map = SimpleNamespace(id=3, doctrine=doctrine)
        fitting_map = Mock(priority=0)
        mock_get_object_or_404.side_effect = [fitting, doctrine]
        mock_doctrine_map_filter.return_value.first.return_value = None
        mock_fitting_map_select_related.return_value.filter.return_value.first.return_value = None
        mock_create_doctrine_map.return_value = doctrine_map
        mock_create_fitting_map.return_value = fitting_map

        request = self.factory.post(
            "/fitting/55/priority/",
            data={"doctrine_id": "9", "priority": "7"},
        )
        request.user = _view_user()

        response = views.update_fitting_priority(request, fitting_id=55)

        self.assertEqual(response.status_code, 200)
        mock_create_doctrine_map.assert_called_once_with(doctrine)
        mock_create_fitting_map.assert_called_once_with(doctrine_map, fitting)
        self.assertEqual(fitting_map.priority, 7)
        fitting_map.save.assert_called_once_with(update_fields=["priority"])
        mock_messages.success.assert_called_once()
        mock_redirect.assert_called_once_with("mastery:doctrine_detail", doctrine_id=9)

    @patch("mastery.views.doctrine._build_fitting_skills_ajax_response")
    @patch("mastery.views.doctrine.FittingSkillsetMap.objects.select_related")
    @patch("mastery.views.doctrine.DoctrineSkillSetGroupMap.objects.filter")
    @patch("mastery.views.doctrine.get_object_or_404")
    def test_update_fitting_priority_returns_ajax_fragment(
        self,
        mock_get_object_or_404,
        mock_doctrine_map_filter,
        mock_fitting_map_select_related,
        mock_build_ajax,
    ):
        fitting = SimpleNamespace(id=55, ship_type=SimpleNamespace(name="Drake"))
        doctrine = SimpleNamespace(id=9, name="Alpha")
        doctrine_map = SimpleNamespace(id=3, doctrine=doctrine, priority=4)
        fitting_map = Mock(priority=0)
        mock_get_object_or_404.side_effect = [fitting, doctrine]
        mock_doctrine_map_filter.return_value.first.return_value = doctrine_map
        mock_fitting_map_select_related.return_value.filter.return_value.first.return_value = fitting_map
        mock_build_ajax.return_value = JsonResponse({"status": "ok"})

        request = self.factory.post(
            "/fitting/55/priority/",
            data={"doctrine_id": "9", "priority": "10"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        request.user = _view_user()

        response = views.update_fitting_priority(request, fitting_id=55)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(fitting_map.priority, 10)
        fitting_map.save.assert_called_once_with(update_fields=["priority"])
        mock_build_ajax.assert_called_once_with(
            request,
            fitting=fitting,
            doctrine=doctrine,
            doctrine_map=doctrine_map,
            fitting_map=fitting_map,
            message="Fitting priority updated",
        )

    @patch("mastery.views.doctrine.FittingSkillsetMap.objects.select_related")
    @patch("mastery.views.doctrine.DoctrineSkillSetGroupMap.objects.filter")
    @patch("mastery.views.doctrine.get_object_or_404")
    def test_update_fitting_priority_rejects_invalid_value(
        self,
        mock_get_object_or_404,
        mock_doctrine_map_filter,
        mock_fitting_map_select_related,
    ):
        fitting = SimpleNamespace(id=55, ship_type=SimpleNamespace(name="Drake"))
        doctrine = SimpleNamespace(id=9, name="Alpha")
        doctrine_map = SimpleNamespace(id=3, doctrine=doctrine)
        fitting_map = Mock(priority=0)
        mock_get_object_or_404.side_effect = [fitting, doctrine]
        mock_doctrine_map_filter.return_value.first.return_value = doctrine_map
        mock_fitting_map_select_related.return_value.filter.return_value.first.return_value = fitting_map

        request = self.factory.post(
            "/fitting/55/priority/",
            data={"doctrine_id": "9", "priority": "11"},
        )
        request.user = _view_user()

        response = views.update_fitting_priority(request, fitting_id=55)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.content.decode(), "Priority must be between 0 and 10.")


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

    @patch("mastery.views.summary_helpers.User.objects.filter")
    @patch("mastery.views.summary_helpers.Character.objects.filter")
    def test_summary_group_users_uses_any_owned_character_for_audience_matching(
        self,
        mock_character_filter,
        mock_user_filter,
    ):
        entry_corp = SimpleNamespace(entity_type="corporation", entity_id=99000123)
        entry_alliance = SimpleNamespace(entity_type="alliance", entity_id=99000999)
        summary_group = SimpleNamespace(entries=SimpleNamespace(all=lambda: [entry_corp, entry_alliance]))

        character_qs = Mock()
        values_list_qs = Mock()
        mock_character_filter.return_value = character_qs
        character_qs.values_list.return_value = values_list_qs
        values_list_qs.distinct.return_value = [10, 20]

        user_qs = Mock()
        mock_user_filter.return_value = user_qs
        user_qs.distinct.return_value = "eligible-users"

        result = _summary_group_users(summary_group)

        self.assertEqual(result, "eligible-users")
        self.assertEqual(mock_character_filter.call_count, 1)
        call_args, call_kwargs = mock_character_filter.call_args
        self.assertEqual(call_kwargs, {"eve_character__character_ownership__user_id__isnull": False})
        self.assertEqual(len(call_args), 1)
        query_repr = str(call_args[0])
        self.assertIn("eve_character__corporation_id__in", query_repr)
        self.assertIn("eve_character__alliance_id__in", query_repr)
        self.assertNotIn("profile__main_character", query_repr)
        mock_user_filter.assert_called_once_with(id__in=[10, 20])

    @patch("mastery.views.summary_helpers.Character.objects.owned_by_user")
    def test_get_member_characters_uses_memberaudit_owned_by_user_manager(self, mock_owned_by_user):
        user = SimpleNamespace(id=55)
        owned_qs = Mock()
        mock_owned_by_user.return_value = owned_qs
        owned_qs.select_related.return_value.order_by.return_value = "member-characters"

        result = _get_member_characters(user)

        self.assertEqual(result, "member-characters")
        mock_owned_by_user.assert_called_once_with(user)
        owned_qs.select_related.assert_called_once_with("eve_character", "online_status")
        owned_qs.select_related.return_value.order_by.assert_called_once_with(
            "eve_character__character_name"
        )

    @patch("mastery.views.summary_helpers.Character.objects.filter")
    @patch("mastery.views.summary_helpers._summary_group_characters_queryset")
    @patch("mastery.views.summary_helpers._summary_group_users")
    @patch("mastery.views.summary_helpers.timezone.now")
    def test_build_member_groups_for_summary_keeps_only_in_scope_characters_and_uses_main_activity(
        self,
        mock_now,
        mock_group_users,
        mock_summary_group_characters_queryset,
        mock_character_filter,
    ):
        now = datetime(2026, 4, 27, tzinfo=dt_timezone.utc)
        mock_now.return_value = now
        summary_group = SimpleNamespace(id=3)
        user = SimpleNamespace(
            id=7,
            username="pilot7",
            profile=SimpleNamespace(
                main_character=SimpleNamespace(id=101, character_name="Main Outside Audience"),
            ),
        )
        eligible_users = Mock()
        eligible_users.exists.return_value = True
        mock_group_users.return_value = eligible_users

        matching_alt = SimpleNamespace(
            id=202,
            eve_character=SimpleNamespace(
                character_name="Alt In Audience",
                character_ownership=SimpleNamespace(user=user),
            ),
            online_status=SimpleNamespace(last_login=now - timedelta(days=2), last_logout=None),
        )
        scoped_queryset = Mock()
        mock_summary_group_characters_queryset.return_value = scoped_queryset
        scoped_queryset.select_related.return_value.order_by.return_value = [matching_alt]

        main_activity_character = SimpleNamespace(
            id=101,
            eve_character=SimpleNamespace(
                character_name="Main Outside Audience",
                character_ownership=SimpleNamespace(user=user),
            ),
            online_status=SimpleNamespace(last_login=now - timedelta(days=1), last_logout=None),
        )
        mock_character_filter.return_value.select_related.return_value = [main_activity_character]

        groups = _build_member_groups_for_summary(
            summary_group=summary_group,
            activity_days=14,
            include_inactive=False,
        )

        self.assertEqual(len(groups), 1)
        group = groups[0]
        self.assertEqual(group["user"], user)
        self.assertEqual(group["main_character"].character_name, "Main Outside Audience")
        self.assertEqual([character.id for character in group["characters"]], [202])
        self.assertEqual(group["active_count"], 1)
        self.assertEqual(group["total_count"], 1)
        mock_summary_group_characters_queryset.assert_called_once_with(
            summary_group=summary_group,
            users=eligible_users,
        )
        mock_character_filter.assert_called_once_with(
            eve_character_id__in={101},
            eve_character__character_ownership__user_id__in={7},
        )

    @patch("mastery.views.summary_helpers.Character.objects.filter")
    @patch("mastery.views.summary_helpers._summary_group_characters_queryset")
    @patch("mastery.views.summary_helpers._summary_group_users")
    @patch("mastery.views.summary_helpers.timezone.now")
    def test_build_member_groups_for_summary_excludes_user_when_main_is_inactive(
        self,
        mock_now,
        mock_group_users,
        mock_summary_group_characters_queryset,
        mock_character_filter,
    ):
        now = datetime(2026, 4, 27, tzinfo=dt_timezone.utc)
        mock_now.return_value = now
        user = SimpleNamespace(
            id=10,
            username="pilot10",
            profile=SimpleNamespace(main_character=SimpleNamespace(id=606, character_name="Main P10")),
        )
        eligible_users = Mock()
        eligible_users.exists.return_value = True
        mock_group_users.return_value = eligible_users

        in_scope_alt = SimpleNamespace(
            id=707,
            eve_character=SimpleNamespace(
                character_name="Alt Scoped",
                character_ownership=SimpleNamespace(user=user),
            ),
            online_status=SimpleNamespace(last_login=now - timedelta(days=1), last_logout=None),
        )
        scoped_queryset = Mock()
        mock_summary_group_characters_queryset.return_value = scoped_queryset
        scoped_queryset.select_related.return_value.order_by.return_value = [in_scope_alt]

        main_activity_character = SimpleNamespace(
            id=808,
            eve_character=SimpleNamespace(
                character_name="Main P10",
                character_ownership=SimpleNamespace(user=user),
            ),
            online_status=SimpleNamespace(last_login=now - timedelta(days=30), last_logout=None),
        )
        mock_character_filter.return_value.select_related.return_value = [main_activity_character]

        groups = _build_member_groups_for_summary(
            summary_group=SimpleNamespace(id=9),
            activity_days=14,
            include_inactive=False,
        )

        self.assertEqual(groups, [])

    @patch("mastery.views.summary_helpers.summary_cache")
    @patch("mastery.views.summary_helpers.pilot_progress_service")
    def test_build_fitting_user_rows_uses_best_alt_character_progress_for_user(self, mock_progress_service, mock_summary_cache):
        main_progress = {
            "can_fly": False,
            "recommended_pct": 40.0,
            "required_pct": 80.0,
        }
        alt_progress = {
            "can_fly": True,
            "recommended_pct": 100.0,
            "required_pct": 100.0,
        }
        mock_progress_service.build_for_character.side_effect = [main_progress, alt_progress]
        mock_summary_cache.get_cached_progress.return_value = (None, "test_key")

        main_character = SimpleNamespace(id=11)
        alt_character = SimpleNamespace(id=22)
        fitting_map = SimpleNamespace(skillset=SimpleNamespace(id=99))
        member_groups = [
            {
                "user": SimpleNamespace(id=5),
                "main_character": SimpleNamespace(character_name="Main Outside Audience"),
                "characters": [main_character, alt_character],
                "total_count": 2,
                "last_seen": None,
            }
        ]

        rows = _build_fitting_user_rows(
            fitting_map=fitting_map,
            member_groups=member_groups,
            progress_cache={},
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["best_character"].id, 22)
        self.assertTrue(rows[0]["best_progress"]["can_fly"])
        self.assertEqual(rows[0]["flyable_count"], 1)

    @patch("mastery.views.summary_helpers.User.objects.none")
    @patch("mastery.views.summary_helpers.Character.objects.filter")
    def test_summary_group_users_returns_none_when_group_has_no_entries(
        self,
        mock_character_filter,
        mock_user_none,
    ):
        mock_user_none.return_value = "empty-users"
        summary_group = SimpleNamespace(entries=SimpleNamespace(all=lambda: []))

        result = _summary_group_users(summary_group)

        self.assertEqual(result, "empty-users")
        mock_character_filter.assert_not_called()
        mock_user_none.assert_called_once_with()

    @patch("mastery.views.summary_helpers._build_member_groups_for_summary")
    def test_get_pilot_detail_characters_uses_summary_groups_and_flattens_sorted_characters(
        self,
        mock_build_member_groups,
    ):
        char_z = SimpleNamespace(id=10, eve_character=SimpleNamespace(character_name="Zulu"))
        char_a = SimpleNamespace(id=11, eve_character=SimpleNamespace(character_name="Alpha"))
        summary_group = SimpleNamespace(id=5)
        mock_build_member_groups.return_value = [
            {"characters": [char_z]},
            {"characters": [char_a]},
        ]

        result = _get_pilot_detail_characters(
            _view_user(),
            summary_group=summary_group,
            activity_days=14,
            include_inactive=False,
        )

        self.assertEqual(result, [char_a, char_z])
        mock_build_member_groups.assert_called_once_with(
            summary_group=summary_group,
            activity_days=14,
            include_inactive=False,
        )

    @patch("mastery.views.summary_helpers.Character.objects.filter")
    @patch("mastery.views.summary_helpers._summary_group_characters_queryset")
    @patch("mastery.views.summary_helpers._summary_group_users")
    @patch("mastery.views.summary_helpers.timezone.now")
    def test_build_member_groups_for_summary_include_inactive_keeps_all_in_scope_only(
        self,
        mock_now,
        mock_group_users,
        mock_summary_group_characters_queryset,
        mock_character_filter,
    ):
        now = datetime(2026, 4, 27, tzinfo=dt_timezone.utc)
        mock_now.return_value = now
        user = SimpleNamespace(
            id=11,
            username="pilot11",
            profile=SimpleNamespace(main_character=SimpleNamespace(id=901, character_name="Main P11")),
        )
        eligible_users = Mock()
        eligible_users.exists.return_value = True
        mock_group_users.return_value = eligible_users

        in_scope_old = SimpleNamespace(
            id=1001,
            eve_character=SimpleNamespace(
                character_name="Scoped Old",
                character_ownership=SimpleNamespace(user=user),
            ),
            online_status=SimpleNamespace(last_login=now - timedelta(days=70), last_logout=None),
        )
        in_scope_recent = SimpleNamespace(
            id=1002,
            eve_character=SimpleNamespace(
                character_name="Scoped Recent",
                character_ownership=SimpleNamespace(user=user),
            ),
            online_status=SimpleNamespace(last_login=now - timedelta(days=2), last_logout=None),
        )
        scoped_queryset = Mock()
        mock_summary_group_characters_queryset.return_value = scoped_queryset
        scoped_queryset.select_related.return_value.order_by.return_value = [in_scope_old, in_scope_recent]
        mock_character_filter.return_value.select_related.return_value = []

        groups = _build_member_groups_for_summary(
            summary_group=SimpleNamespace(id=10),
            activity_days=14,
            include_inactive=True,
        )

        self.assertEqual(len(groups), 1)
        self.assertEqual([char.id for char in groups[0]["characters"]], [1001, 1002])
        self.assertEqual(groups[0]["total_count"], 2)
        mock_character_filter.assert_not_called()

    @patch("mastery.views.summary_helpers._summary_group_characters_queryset")
    @patch("mastery.views.summary_helpers._summary_group_users")
    @patch("mastery.views.summary_helpers.timezone.now")
    def test_build_member_groups_for_summary_skips_users_without_in_scope_characters(
        self,
        mock_now,
        mock_group_users,
        mock_summary_group_characters_queryset,
    ):
        mock_now.return_value = datetime(2026, 4, 27, tzinfo=dt_timezone.utc)
        eligible_users = Mock()
        eligible_users.exists.return_value = True
        mock_group_users.return_value = eligible_users

        scoped_queryset = Mock()
        mock_summary_group_characters_queryset.return_value = scoped_queryset
        scoped_queryset.select_related.return_value.order_by.return_value = []

        groups = _build_member_groups_for_summary(
            summary_group=SimpleNamespace(id=11),
            activity_days=14,
            include_inactive=False,
        )

        self.assertEqual(groups, [])

    @patch("mastery.views.summary_helpers._summary_group_characters_queryset")
    @patch("mastery.views.summary_helpers._summary_group_users")
    @patch("mastery.views.summary_helpers.timezone.now")
    def test_build_member_groups_for_summary_does_not_call_exists_on_eligible_users(
        self,
        mock_now,
        mock_group_users,
        mock_summary_group_characters_queryset,
    ):
        mock_now.return_value = datetime(2026, 4, 27, tzinfo=dt_timezone.utc)
        eligible_users = Mock()
        eligible_users.exists.side_effect = AssertionError("exists() should not be called")
        mock_group_users.return_value = eligible_users

        scoped_queryset = Mock()
        mock_summary_group_characters_queryset.return_value = scoped_queryset
        scoped_queryset.select_related.return_value.order_by.return_value = []

        groups = _build_member_groups_for_summary(
            summary_group=SimpleNamespace(id=77),
            activity_days=14,
            include_inactive=False,
        )

        self.assertEqual(groups, [])

    @patch("mastery.views.summary_helpers.CharacterSkill.objects.filter")
    def test_prime_summary_character_skills_cache_context_preloads_uncached_characters(self, mock_filter):
        cached_skill_map = {88: {42: "already-cached"}}
        cache_context = {"character_skills": cached_skill_map.copy()}
        member_groups = [
            {
                "characters": [
                    SimpleNamespace(id=10),
                    SimpleNamespace(id=11),
                    SimpleNamespace(id=88),
                ]
            }
        ]
        preloaded_skill = SimpleNamespace(character_id=10, eve_type_id=1001)
        mock_filter.return_value.select_related.return_value = [preloaded_skill]

        _prime_summary_character_skills_cache_context(
            member_groups=member_groups,
            cache_context=cache_context,
        )

        called_ids = mock_filter.call_args.kwargs["character_id__in"]
        self.assertCountEqual(called_ids, [10, 11])
        self.assertEqual(cache_context["character_skills"][10][1001], preloaded_skill)
        self.assertEqual(cache_context["character_skills"][11], {})
        self.assertEqual(cache_context["character_skills"][88], {42: "already-cached"})
        self.assertEqual(
            cache_context["p2_metrics"]["character_skills"],
            {
                "prime_calls": 1,
                "prime_character_ids_total": 3,
                "prime_already_cached": 1,
                "prime_uncached": 2,
                "prime_rows_loaded": 1,
                "cache_hits": 0,
                "cache_misses": 0,
                "db_loads": 0,
                "skills_loaded": 0,
            },
        )

    @patch("mastery.views.summary_helpers.summary_cache")
    @patch("mastery.views.summary_helpers.pilot_progress_service.build_for_character")
    def test_progress_for_character_tracks_p0_progress_cache_metrics(self, mock_build_for_character, mock_summary_cache):
        skillset = SimpleNamespace(id=10)
        character = SimpleNamespace(id=20)
        progress_cache = {}
        progress_context = {}
        mock_build_for_character.return_value = {"can_fly": True}
        mock_summary_cache.get_cached_progress.return_value = (None, "test_key")

        first = _progress_for_character(skillset, character, progress_cache, progress_context)
        second = _progress_for_character(skillset, character, progress_cache, progress_context)

        self.assertEqual(first, second)
        mock_build_for_character.assert_called_once()
        self.assertEqual(
            progress_context["p0_metrics"]["summary_view"],
            {
                "progress_calls": 2,
                "progress_cache_hits": 1,
                "progress_cache_misses": 1,
            },
        )

    @patch("mastery.views.summary_helpers.summary_cache")
    @patch("mastery.views.summary_helpers.pilot_progress_service.build_for_character")
    def test_progress_for_character_p3_cache_hit_skips_build_and_increments_metrics(
        self, mock_build_for_character, mock_summary_cache
    ):
        """P3 cache hit: build_for_character is not called and p3 hit counter incremented."""
        cached = {"can_fly": True, "recommended_pct": 100.0, "required_pct": 100.0}
        mock_summary_cache.get_cached_progress.return_value = (cached, "test_key")

        skillset = SimpleNamespace(id=10)
        character = SimpleNamespace(id=20)
        progress_cache = {}
        progress_context = {}

        result = _progress_for_character(skillset, character, progress_cache, progress_context)

        mock_build_for_character.assert_not_called()
        mock_summary_cache.set_cached_progress.assert_not_called()
        self.assertEqual(result, cached)
        self.assertEqual(progress_context["p3_metrics"]["shared_progress_cache"]["cache_hits"], 1)
        self.assertEqual(progress_context["p3_metrics"]["shared_progress_cache"]["cache_misses"], 0)
        self.assertEqual(progress_context["p3_metrics"]["shared_progress_cache"]["cache_writes"], 0)

    @patch("mastery.views.summary_helpers.summary_cache")
    @patch("mastery.views.summary_helpers.pilot_progress_service.build_for_character")
    def test_progress_for_character_p3_cache_miss_calls_build_and_writes_cache(
        self, mock_build_for_character, mock_summary_cache
    ):
        """P3 cache miss: build_for_character is called, result written to shared cache."""
        computed = {"can_fly": False, "recommended_pct": 50.0, "required_pct": 80.0}
        mock_build_for_character.return_value = computed
        mock_summary_cache.get_cached_progress.return_value = (None, "test_key")

        skillset = SimpleNamespace(id=10)
        character = SimpleNamespace(id=20)
        progress_cache = {}
        progress_context = {}

        result = _progress_for_character(skillset, character, progress_cache, progress_context)

        mock_build_for_character.assert_called_once()
        mock_summary_cache.set_cached_progress.assert_called_once_with("test_key", computed)
        self.assertEqual(result, computed)
        self.assertEqual(progress_context["p3_metrics"]["shared_progress_cache"]["cache_misses"], 1)
        self.assertEqual(progress_context["p3_metrics"]["shared_progress_cache"]["cache_writes"], 1)
        self.assertEqual(progress_context["p3_metrics"]["shared_progress_cache"]["cache_hits"], 0)

    @patch("mastery.views.summary_helpers.summary_cache")
    @patch("mastery.views.summary_helpers.pilot_progress_service.build_for_character")
    def test_progress_for_character_p3_cache_hit_then_p0_intra_request_hit(
        self, mock_build_for_character, mock_summary_cache
    ):
        """Second call on same character/skillset uses P0 intra-request cache, not P3."""
        cached = {"can_fly": True, "recommended_pct": 100.0, "required_pct": 100.0}
        mock_summary_cache.get_cached_progress.return_value = (cached, "test_key")

        skillset = SimpleNamespace(id=10)
        character = SimpleNamespace(id=20)
        progress_cache = {}
        progress_context = {}

        first = _progress_for_character(skillset, character, progress_cache, progress_context)
        second = _progress_for_character(skillset, character, progress_cache, progress_context)

        self.assertEqual(first, second)
        # P3 get_cached_progress only called once (second hit goes via intra-request cache)
        mock_summary_cache.get_cached_progress.assert_called_once()
        self.assertEqual(progress_context["p0_metrics"]["summary_view"]["progress_cache_hits"], 1)
        self.assertEqual(progress_context["p3_metrics"]["shared_progress_cache"]["cache_hits"], 1)

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
        self.assertEqual(kpis["characters_total"], 0)
        self.assertEqual(kpis["flyable_now_users"], 0)
        self.assertEqual(kpis["recommended_avg_pct"], 0.0)

    def test_build_fitting_kpis_all_flyable_and_recommended(self):
        rows = [self._make_user_row(can_fly=True, recommended_pct=100.0)]
        kpis = _build_fitting_kpis(rows)
        self.assertEqual(kpis["users_total"], 1)
        self.assertEqual(kpis["characters_total"], 1)
        self.assertEqual(kpis["flyable_now_users"], 1)
        self.assertEqual(kpis["flyable_now_characters"], 1)
        self.assertEqual(kpis["recommended_ready"], 1)
        self.assertEqual(kpis["recommended_avg_pct"], 100.0)

    def test_build_fitting_kpis_counts_total_characters_and_only_flyable_now(self):
        flyable_progress = {
            "can_fly": True,
            "recommended_pct": 100.0,
            "required_pct": 100.0,
            "mode_stats": {},
        }
        training_progress = {
            "can_fly": False,
            "recommended_pct": 40.0,
            "required_pct": 80.0,
            "mode_stats": {},
        }
        rows = [
            {
                "user": SimpleNamespace(id=1),
                "best_progress": flyable_progress,
                "character_rows": [
                    {"character": SimpleNamespace(id=10), "progress": flyable_progress},
                    {"character": SimpleNamespace(id=11), "progress": training_progress},
                ],
                "flyable_count": 1,
                "active_count": 2,
                "total_count": 2,
                "last_seen": None,
            }
        ]

        kpis = _build_fitting_kpis(rows)

        self.assertEqual(kpis["characters_total"], 2)
        self.assertEqual(kpis["flyable_now_characters"], 1)


    # -- _build_doctrine_kpis ------------------------------------------------

    def _make_fitting_entry(self, configured=True, user_rows=None):
        return {
            "configured": configured,
            "user_rows": user_rows or [],
        }

    def test_build_doctrine_kpis_empty_fittings(self):
        kpis = _build_doctrine_kpis([], users_tracked=0)
        self.assertEqual(kpis["users_total"], 0)
        self.assertEqual(kpis["characters_total"], 0)
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
        self.assertEqual(kpis["characters_total"], 1)
        self.assertEqual(kpis["flyable_now_characters"], 1)

    def test_build_doctrine_kpis_distinguishes_flyable_and_total_characters(self):
        user = SimpleNamespace(id=99)
        elite_progress = {
            "can_fly": True,
            "recommended_pct": 100.0,
            "required_pct": 100.0,
            "mode_stats": {},
        }
        almost_fit_progress = {
            "can_fly": False,
            "recommended_pct": 20.0,
            "required_pct": 95.0,
            "mode_stats": {},
        }
        row = {
            "user": user,
            "best_progress": elite_progress,
            "character_rows": [
                {"character": SimpleNamespace(id=201), "progress": elite_progress},
                {"character": SimpleNamespace(id=202), "progress": almost_fit_progress},
            ],
        }

        kpis = _build_doctrine_kpis(
            [self._make_fitting_entry(configured=True, user_rows=[row])],
            users_tracked=1,
        )

        self.assertEqual(kpis["characters_total"], 2)
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

    @patch("mastery.views.summary_helpers.DoctrineSkillSetGroupMap.objects.filter")
    @patch("mastery.views.summary_helpers._build_fitting_user_rows")
    def test_build_doctrine_summary_exposes_priority_and_sorts_fittings(
        self,
        mock_build_user_rows,
        mock_doctrine_map_filter,
    ):
        doctrine = SimpleNamespace(id=1, name="Alpha", fittings=Mock())
        fit_low = SimpleNamespace(id=10, name="Fit Low")
        fit_high = SimpleNamespace(id=11, name="Fit High")
        doctrine.fittings.all.return_value = [fit_low, fit_high]
        mock_doctrine_map_filter.return_value.values_list.return_value.first.return_value = 8
        mock_build_user_rows.return_value = []

        summary = _build_doctrine_summary(
            doctrine=doctrine,
            fitting_maps={
                fit_low.id: SimpleNamespace(
                    priority=2,
                    skillset=SimpleNamespace(id=101),
                    status=FittingSkillsetMap.ApprovalStatus.APPROVED,
                ),
                fit_high.id: SimpleNamespace(
                    priority=9,
                    skillset=SimpleNamespace(id=102),
                    status=FittingSkillsetMap.ApprovalStatus.APPROVED,
                ),
            },
            member_groups=[],
            progress_cache={},
            progress_context={},
        )

        self.assertEqual(summary["priority"], 8)
        self.assertEqual([row["fitting"].name for row in summary["fittings"]], ["Fit High", "Fit Low"])

    @patch("mastery.views.summary_helpers._build_doctrine_kpis", return_value={"needs_training_characters": 2})
    @patch("mastery.views.summary_helpers._build_fitting_kpis", return_value={"needs_training_characters": 2})
    @patch("mastery.views.summary_helpers._annotate_member_detail_pilots")
    @patch("mastery.views.summary_helpers.DoctrineSkillSetGroupMap.objects.filter")
    @patch("mastery.views.summary_helpers._build_fitting_user_rows")
    def test_build_doctrine_summary_builds_kpis_from_filtered_rows(
        self,
        mock_build_user_rows,
        mock_doctrine_map_filter,
        mock_annotate_rows,
        mock_fit_kpis,
        mock_doctrine_kpis,
    ):
        doctrine = SimpleNamespace(id=1, name="Alpha", fittings=Mock())
        fitting = SimpleNamespace(id=10, name="Fit")
        doctrine.fittings.all.return_value = [fitting]
        mock_doctrine_map_filter.return_value.values_list.return_value.first.return_value = 5

        raw_rows = [
            {
                "user": SimpleNamespace(id=7),
                "flyable_count": 0,
                "best_progress": {"required_pct": 20.0, "recommended_pct": 10.0},
                "character_rows": [{"progress": {"can_fly": False}}],
            }
        ]
        visible_rows = [
            {
                "user": SimpleNamespace(id=7),
                "flyable_count": 0,
                "best_progress": {"required_pct": 20.0, "recommended_pct": 10.0},
                "character_rows": [{"progress": {"can_fly": False}}],
            }
        ]
        mock_build_user_rows.return_value = raw_rows
        mock_annotate_rows.return_value = visible_rows

        summary = _build_doctrine_summary(
            doctrine=doctrine,
            fitting_maps={
                fitting.id: SimpleNamespace(
                    priority=4,
                    skillset=SimpleNamespace(id=101),
                    status=FittingSkillsetMap.ApprovalStatus.APPROVED,
                )
            },
            member_groups=[{"active_count": 1}],
            progress_cache={},
            progress_context={},
        )

        self.assertEqual(summary["fittings"][0]["user_rows"], visible_rows)
        mock_fit_kpis.assert_called_once_with(visible_rows)
        doctrine_kpi_fittings = mock_doctrine_kpis.call_args.kwargs["fittings"]
        self.assertEqual(doctrine_kpi_fittings[0]["user_rows"], visible_rows)

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

    def test_is_approved_fitting_map_handles_missing_or_unapproved(self):
        self.assertFalse(_is_approved_fitting_map(None))
        self.assertFalse(
            _is_approved_fitting_map(
                SimpleNamespace(status=FittingSkillsetMap.ApprovalStatus.IN_PROGRESS),
            )
        )
        self.assertTrue(
            _is_approved_fitting_map(
                SimpleNamespace(status=FittingSkillsetMap.ApprovalStatus.APPROVED),
            )
        )

    def test_missing_skillset_error_returns_expected_messages(self):
        self.assertEqual(_missing_skillset_error(None), "No skillset configured for this fitting yet")
        self.assertEqual(
            _missing_skillset_error(SimpleNamespace(skillset=None, status=FittingSkillsetMap.ApprovalStatus.APPROVED)),
            "No skillset configured for this fitting yet",
        )
        self.assertEqual(
            _missing_skillset_error(
                SimpleNamespace(skillset=SimpleNamespace(id=1), status=FittingSkillsetMap.ApprovalStatus.NOT_APPROVED),
            ),
            "No approved skillset configured for this fitting yet",
        )
        self.assertIsNone(
            _missing_skillset_error(
                SimpleNamespace(skillset=SimpleNamespace(id=1), status=FittingSkillsetMap.ApprovalStatus.APPROVED),
            )
        )

    @patch("mastery.views.summary_helpers.FittingSkillsetMap.objects.filter")
    def test_approved_fitting_maps_filters_only_approved_status(self, mock_filter):
        approved = SimpleNamespace(fitting_id=10, status=FittingSkillsetMap.ApprovalStatus.APPROVED)
        mock_filter.return_value.select_related.return_value = [approved]

        result = _approved_fitting_maps()

        self.assertEqual(result, {10: approved})
        mock_filter.assert_called_once_with(status=FittingSkillsetMap.ApprovalStatus.APPROVED)


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

    @patch("mastery.views.summary.render", return_value=HttpResponse("ok"))
    @patch("mastery.views.summary._prime_summary_character_skills_cache_context")
    @patch("mastery.views.summary._build_doctrine_summary")
    @patch("mastery.views.summary._build_member_groups_for_summary", return_value=[])
    @patch("mastery.views.summary._approved_fitting_maps")
    @patch("mastery.views.summary.pilot_access_service")
    @patch("mastery.views.summary.get_object_or_404")
    @patch("mastery.views.summary._get_selected_summary_group")
    def test_summary_doctrine_detail_view_propagates_activity_scope(
        self,
        mock_get_group,
        mock_get_object_or_404,
        mock_pilot_access,
        mock_approved_fitting_maps,
        mock_member_groups,
        mock_build_summary,
        mock_prime_character_skills,
        mock_render,
    ):
        selected_group = SimpleNamespace(id=7, name="Group", entries=Mock())
        doctrine = SimpleNamespace(id=1, name="Alpha", fittings=Mock())
        doctrine.fittings.all.return_value = []
        mock_get_group.return_value = ([selected_group], selected_group)
        mock_pilot_access.accessible_doctrines.return_value.prefetch_related.return_value = Mock()
        mock_get_object_or_404.return_value = doctrine
        mock_approved_fitting_maps.return_value = {}
        mock_build_summary.return_value = {
            "doctrine": doctrine,
            "fittings": [],
            "kpis": {"flyable_now_users": 0, "users_total": 0},
        }

        req = self._req(path="/summary/doctrine/1/?group_id=7&activity_days=21&include_inactive=1")
        response = views.summary_doctrine_detail_view(req, doctrine_id=1)

        self.assertEqual(response.status_code, 200)
        mock_member_groups.assert_called_once_with(
            summary_group=selected_group,
            activity_days=21,
            include_inactive=True,
        )
        context = mock_render.call_args[0][2]
        self.assertEqual(context["selected_group"], selected_group)
        self.assertEqual(context["activity_days"], 21)
        self.assertTrue(context["include_inactive"])
        mock_prime_character_skills.assert_called_once()

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
    @patch("mastery.views.summary._approved_fitting_maps")
    @patch("mastery.views.summary._get_accessible_fitting_or_404")
    @patch("mastery.views.summary._get_selected_summary_group")
    def test_summary_fitting_detail_view_returns_400_when_no_fitting_map(
        self,
        mock_get_group,
        mock_fitting_404,
        _mock_approved_fitting_maps,
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
    @patch("mastery.views.summary._approved_fitting_maps")
    @patch("mastery.views.summary._get_accessible_fitting_or_404")
    @patch("mastery.views.summary._get_selected_summary_group")
    @patch("mastery.views.summary.pilot_progress_service")
    def test_summary_fitting_detail_view_renders_with_valid_fitting_map(
        self,
        mock_pilot_service,
        mock_get_group,
        mock_fitting_404,
        _mock_approved_fitting_maps,
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

    @patch("mastery.views.summary.render", return_value=HttpResponse("ok"))
    @patch("mastery.views.summary._build_fitting_kpis", return_value={})
    @patch("mastery.views.summary._annotate_member_detail_pilots")
    @patch("mastery.views.summary._build_fitting_user_rows")
    @patch("mastery.views.summary._build_member_groups_for_summary", return_value=[])
    @patch("mastery.views.summary._approved_fitting_maps")
    @patch("mastery.views.summary._get_accessible_fitting_or_404")
    @patch("mastery.views.summary._get_selected_summary_group")
    @patch("mastery.views.summary.pilot_progress_service")
    def test_summary_fitting_detail_view_builds_kpis_from_annotated_rows(
        self,
        mock_pilot_service,
        mock_get_group,
        mock_fitting_404,
        _mock_approved_fitting_maps,
        _mock_member_groups,
        mock_build_user_rows,
        mock_annotate,
        mock_build_kpis,
        _mock_render,
    ):
        selected_group = SimpleNamespace(id=1, name="Group", entries=Mock())
        mock_get_group.return_value = ([selected_group], selected_group)
        fitting_map = SimpleNamespace(skillset=SimpleNamespace(id=10), doctrine_map=SimpleNamespace(priority=0))
        mock_fitting_404.return_value = (
            SimpleNamespace(id=1, name="Fit"),
            fitting_map,
            SimpleNamespace(id=2),
        )
        mock_pilot_service.export_mode_choices.return_value = []

        raw_rows = [{"user": SimpleNamespace(id=1), "character_rows": [{"progress": {"can_fly": False}}]}]
        visible_rows = [{"user": SimpleNamespace(id=1), "character_rows": [{"progress": {"can_fly": False}}]}]
        mock_build_user_rows.return_value = raw_rows
        mock_annotate.return_value = visible_rows

        req = self._req(path="/summary/fitting/1/")
        response = views.summary_fitting_detail_view(req, fitting_id=1)

        self.assertEqual(response.status_code, 200)
        mock_build_kpis.assert_called_once_with(visible_rows)

    @patch("mastery.views.summary.render", return_value=HttpResponse("ok"))
    @patch("mastery.views.summary._prime_summary_character_skills_cache_context")
    @patch("mastery.views.summary._annotate_member_detail_pilots", return_value=[])
    @patch("mastery.views.summary._build_fitting_kpis", return_value={})
    @patch("mastery.views.summary._build_fitting_user_rows", return_value=[])
    @patch("mastery.views.summary._build_member_groups_for_summary", return_value=[])
    @patch("mastery.views.summary._approved_fitting_maps")
    @patch("mastery.views.summary._get_accessible_fitting_or_404")
    @patch("mastery.views.summary._get_selected_summary_group")
    @patch("mastery.views.summary.pilot_progress_service")
    def test_summary_fitting_detail_view_propagates_activity_scope(
        self,
        mock_pilot_service,
        mock_get_group,
        mock_fitting_404,
        _mock_approved_fitting_maps,
        mock_member_groups,
        _mock_user_rows,
        _mock_kpis,
        _mock_annotate,
        mock_prime_character_skills,
        mock_render,
    ):
        selected_group = SimpleNamespace(id=7, name="Group", entries=Mock())
        mock_get_group.return_value = ([selected_group], selected_group)
        fitting_map = SimpleNamespace(skillset=SimpleNamespace(id=10))
        fitting = SimpleNamespace(id=1, name="Fit")
        doctrine = SimpleNamespace(id=2)
        mock_fitting_404.return_value = (fitting, fitting_map, doctrine)
        mock_pilot_service.export_mode_choices.return_value = [("recommended", "Recommended")]

        req = self._req(path="/summary/fitting/1/?group_id=7&activity_days=21&include_inactive=1")
        response = views.summary_fitting_detail_view(req, fitting_id=1)

        self.assertEqual(response.status_code, 200)
        mock_member_groups.assert_called_once_with(
            summary_group=selected_group,
            activity_days=21,
            include_inactive=True,
        )
        context = mock_render.call_args[0][2]
        self.assertEqual(context["selected_group"], selected_group)
        self.assertEqual(context["activity_days"], 21)
        self.assertTrue(context["include_inactive"])
        mock_prime_character_skills.assert_called_once()

    # -- summary_list_view ---------------------------------------------------

    @patch("mastery.views.summary.render", return_value=HttpResponse("ok"))
    @patch("mastery.views.summary._prime_summary_character_skills_cache_context")
    @patch("mastery.views.summary._build_doctrine_summary")
    @patch("mastery.views.summary._build_member_groups_for_summary", return_value=[])
    @patch("mastery.views.summary._approved_fitting_maps")
    @patch("mastery.views.summary.pilot_access_service")
    @patch("mastery.views.summary._get_selected_summary_group")
    def test_summary_list_view_renders_successfully(
        self,
        mock_get_group,
        mock_pilot_access,
        mock_approved_fitting_maps,
        _mock_member_groups,
        mock_build_doctrine_summary,
        mock_prime_character_skills,
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
        mock_approved_fitting_maps.return_value = {}
        mock_build_doctrine_summary.return_value = {"doctrine": doctrine, "fittings": []}

        req = self._req(path="/summary/")
        response = views.summary_list_view(req)
        self.assertEqual(response.status_code, 200)
        context = mock_render.call_args[0][2]
        self.assertIn("doctrine_summaries", context)
        mock_prime_character_skills.assert_called_once()

    @patch("mastery.views.summary.render", return_value=HttpResponse("ok"))
    @patch("mastery.views.summary._build_member_groups_for_summary", return_value=[])
    @patch("mastery.views.summary._approved_fitting_maps")
    @patch("mastery.views.summary.pilot_access_service")
    @patch("mastery.views.summary._get_selected_summary_group")
    def test_summary_list_view_keeps_only_doctrines_with_configured_fittings(
        self,
        mock_get_group,
        mock_pilot_access,
        mock_approved_fitting_maps,
        _mock_member_groups,
        mock_render,
    ):
        selected_group = SimpleNamespace(id=1, name="Group", entries=Mock())
        mock_get_group.return_value = ([selected_group], selected_group)
        doctrine_with_plan = SimpleNamespace(id=1, name="Alpha", fittings=Mock())
        doctrine_without_plan = SimpleNamespace(id=2, name="Beta", fittings=Mock())
        fitting_with_plan = SimpleNamespace(id=101)
        fitting_without_plan = SimpleNamespace(id=202)
        doctrine_with_plan.fittings.all.return_value = [fitting_with_plan]
        doctrine_without_plan.fittings.all.return_value = [fitting_without_plan]
        mock_pilot_access.accessible_doctrines.return_value.prefetch_related.return_value = [
            doctrine_with_plan,
            doctrine_without_plan,
        ]
        mock_approved_fitting_maps.return_value = {
            fitting_with_plan.id: SimpleNamespace(
                skillset=SimpleNamespace(id=1),
                status=FittingSkillsetMap.ApprovalStatus.APPROVED,
            )
        }

        req = self._req(path="/summary/")
        response = views.summary_list_view(req)

        self.assertEqual(response.status_code, 200)
        context = mock_render.call_args[0][2]
        self.assertEqual(len(context["doctrine_summaries"]), 1)
        self.assertEqual(context["doctrine_summaries"][0]["doctrine"], doctrine_with_plan)

    @patch("mastery.views.summary.render", return_value=HttpResponse("ok"))
    @patch("mastery.views.summary._build_doctrine_summary")
    @patch("mastery.views.summary._build_member_groups_for_summary", return_value=[])
    @patch("mastery.views.summary._approved_fitting_maps")
    @patch("mastery.views.summary.pilot_access_service")
    @patch("mastery.views.summary._get_selected_summary_group")
    def test_summary_list_view_sorts_doctrines_by_priority(
        self,
        mock_get_group,
        mock_pilot_access,
        mock_approved_fitting_maps,
        _mock_member_groups,
        mock_build_doctrine_summary,
        mock_render,
    ):
        selected_group = SimpleNamespace(id=1, name="Group", entries=Mock())
        doctrine_low = SimpleNamespace(id=1, name="Alpha", fittings=Mock())
        doctrine_high = SimpleNamespace(id=2, name="Zulu", fittings=Mock())
        doctrine_low.fittings.all.return_value = []
        doctrine_high.fittings.all.return_value = []
        mock_get_group.return_value = ([selected_group], selected_group)
        mock_pilot_access.accessible_doctrines.return_value.prefetch_related.return_value = [
            doctrine_low,
            doctrine_high,
        ]
        mock_approved_fitting_maps.return_value = {}
        mock_build_doctrine_summary.side_effect = [
            {
                "doctrine": doctrine_low,
                "configured_fittings": 1,
                "priority": 1,
                "fittings": [],
                "active_characters_total": 0,
                "kpis": {},
            },
            {
                "doctrine": doctrine_high,
                "configured_fittings": 1,
                "priority": 9,
                "fittings": [],
                "active_characters_total": 0,
                "kpis": {},
            },
        ]

        req = self._req(path="/summary/")
        response = views.summary_list_view(req)

        self.assertEqual(response.status_code, 200)
        context = mock_render.call_args[0][2]
        self.assertEqual(
            [item["doctrine"].name for item in context["doctrine_summaries"]],
            ["Zulu", "Alpha"],
        )

    @patch("mastery.views.summary.render", return_value=HttpResponse("ok"))
    @patch("mastery.views.summary._store_summary_metrics_debug_snapshot")
    @patch("mastery.views.summary._build_doctrine_summary")
    @patch("mastery.views.summary._build_member_groups_for_summary", return_value=[])
    @patch("mastery.views.summary._approved_fitting_maps")
    @patch("mastery.views.summary.pilot_access_service")
    @patch("mastery.views.summary._get_selected_summary_group")
    def test_summary_list_view_stores_summary_debug_snapshot_for_admin_debug(
        self,
        mock_get_group,
        mock_pilot_access,
        mock_approved_fitting_maps,
        _mock_member_groups,
        mock_build_doctrine_summary,
        mock_store_snapshot,
        _mock_render,
    ):
        selected_group = SimpleNamespace(id=1, name="Group", entries=Mock())
        doctrine = SimpleNamespace(id=1, name="Alpha", fittings=Mock())
        doctrine.fittings.all.return_value = []
        mock_get_group.return_value = ([selected_group], selected_group)
        mock_pilot_access.accessible_doctrines.return_value.prefetch_related.return_value = [doctrine]
        mock_approved_fitting_maps.return_value = {}
        mock_build_doctrine_summary.return_value = {
            "doctrine": doctrine,
            "configured_fittings": 1,
            "priority": 0,
            "fittings": [],
            "active_characters_total": 0,
            "kpis": {},
        }

        req = self._req(path="/summary/")
        req.session = {}
        response = views.summary_list_view(req)

        self.assertEqual(response.status_code, 200)
        mock_store_snapshot.assert_called_once()
        self.assertEqual(mock_store_snapshot.call_args.kwargs["source"], "summary_list")
        progress_context = mock_store_snapshot.call_args.kwargs["progress_context"]
        self.assertEqual(progress_context["p0_metrics"]["summary_view"]["member_groups"], 0)
        self.assertEqual(progress_context["p0_metrics"]["summary_view"]["visible_doctrines"], 1)

    def test_store_p2_metrics_debug_snapshot_skips_non_admin_user(self):
        from mastery.views.summary import _store_summary_metrics_debug_snapshot

        req = self._req(path="/summary/")
        req.user = SimpleNamespace(
            is_authenticated=True,
            has_perm=lambda perm: perm != "mastery.manage_fittings",
            has_perms=lambda _perms: True,
        )
        req.session = {}

        _store_summary_metrics_debug_snapshot(
            request=req,
            source="summary_list",
            progress_context={
                "p0_metrics": {"summary_view": {"progress_calls": 1}},
                "p2_metrics": {"character_skills": {"prime_calls": 1}},
            },
        )

        self.assertEqual(req.session, {})

    def test_store_p2_metrics_debug_snapshot_keeps_last_five_per_source(self):
        from mastery.views.summary import _store_summary_metrics_debug_snapshot

        req = self._req(path="/summary/")
        req.session = {}

        for idx in range(7):
            _store_summary_metrics_debug_snapshot(
                request=req,
                source="summary_list",
                progress_context={
                    "p0_metrics": {"summary_view": {"progress_calls": idx}},
                    "p2_metrics": {"character_skills": {"prime_calls": idx}},
                },
            )

        for idx in range(7):
            _store_summary_metrics_debug_snapshot(
                request=req,
                source="summary_fitting_detail",
                progress_context={
                    "p0_metrics": {"summary_view": {"progress_calls": idx}},
                    "p2_metrics": {"character_skills": {"prime_calls": idx}},
                },
            )

        snapshots = req.session["mastery_p2_metrics_debug_snapshots"]
        self.assertEqual(len(snapshots), 10)

        summary_list_rows = [row for row in snapshots if row["source"] == "summary_list"]
        summary_fit_rows = [row for row in snapshots if row["source"] == "summary_fitting_detail"]

        self.assertEqual(len(summary_list_rows), 5)
        self.assertEqual(len(summary_fit_rows), 5)
        self.assertEqual(summary_list_rows[0]["metrics"]["p0_metrics"]["summary_view"]["progress_calls"], 2)
        self.assertEqual(summary_list_rows[-1]["metrics"]["p0_metrics"]["summary_view"]["progress_calls"], 6)
        self.assertEqual(summary_fit_rows[0]["metrics"]["p0_metrics"]["summary_view"]["progress_calls"], 2)
        self.assertEqual(summary_fit_rows[-1]["metrics"]["p0_metrics"]["summary_view"]["progress_calls"], 6)

    @patch("mastery.views.summary.connection", new=SimpleNamespace(queries=[1, 2, 3, 4]))
    @patch("mastery.views.summary.perf_counter", return_value=10.123)
    def test_store_p2_metrics_debug_snapshot_enriches_p0_trace_metrics(self, _mock_perf_counter):
        from mastery.views.summary import _store_summary_metrics_debug_snapshot

        req = self._req(path="/summary/")
        req.session = {}

        _store_summary_metrics_debug_snapshot(
            request=req,
            source="summary_list",
            progress_context={"p0_metrics": {"summary_view": {}}, "p2_metrics": {"character_skills": {}}},
            trace={"started_at": 10.0, "sql_queries_start": 1},
        )

        snapshot = req.session["mastery_p2_metrics_debug_snapshots"][0]
        self.assertEqual(snapshot["metrics"]["p0_metrics"]["summary_view"]["view_total_ms"], 123.0)
        self.assertEqual(snapshot["metrics"]["p0_metrics"]["summary_view"]["sql_query_count"], 3)

    @patch("mastery.views.summary.render", return_value=HttpResponse("ok"))
    def test_summary_p2_metrics_debug_view_renders_latest_snapshots(self, mock_render):
        req = self._req(path="/summaries/debug/p2-metrics/")
        req.session = {
            "mastery_p2_metrics_debug_snapshots": [
                {
                    "captured_at": "2026-05-02T08:00:00+00:00",
                    "source": "summary_list",
                    "metrics": {
                        "p0_metrics": {"summary_view": {"progress_calls": 1}},
                        "p2_metrics": {"character_skills": {"prime_calls": 1}},
                    },
                },
                {
                    "captured_at": "2026-05-02T09:00:00+00:00",
                    "source": "summary_fitting_detail",
                    "metrics": {
                        "p0_metrics": {"summary_view": {"progress_calls": 2}},
                        "p2_metrics": {"character_skills": {"prime_calls": 2}},
                    },
                },
                {
                    "captured_at": "2026-05-02T10:00:00+00:00",
                    "source": "summary_list",
                    "metrics": {
                        "p0_metrics": {"summary_view": {"progress_calls": 3, "view_total_ms": 1200}},
                        "p2_metrics": {"character_skills": {"prime_calls": 3}},
                    },
                },
            ]
        }

        response = views.summary_p2_metrics_debug_view(req)

        self.assertEqual(response.status_code, 200)
        context = mock_render.call_args[0][2]
        self.assertEqual(context["snapshot_count"], 3)
        self.assertEqual(context["snapshots"][0]["source"], "summary_list")
        self.assertEqual(context["snapshots"][1]["source"], "summary_fitting_detail")
        self.assertEqual(context["snapshots"][2]["source"], "summary_list")

        # Grouped structure for source tabs
        self.assertEqual(context["snapshot_sources"][0]["source"], "summary_list")
        self.assertEqual(len(context["snapshot_sources"][0]["snapshots"]), 2)
        self.assertEqual(context["snapshot_sources"][0]["snapshots"][0]["captured_at"], "2026-05-02T10:00:00+00:00")
        self.assertEqual(context["snapshot_sources"][0]["snapshots"][1]["captured_at"], "2026-05-02T08:00:00+00:00")
        self.assertEqual(context["snapshot_sources"][1]["source"], "summary_fitting_detail")
        self.assertEqual(len(context["snapshot_sources"][1]["snapshots"]), 1)

    def test_summary_fitting_member_coverage_csv_response_contains_only_provided_rows(self):
        from mastery.views.summary import _summary_fitting_member_coverage_csv_response

        fitting = SimpleNamespace(id=5)
        in_scope_character = SimpleNamespace(eve_character=SimpleNamespace(character_name="In Scope Pilot"))
        out_scope_name = "Out Scope Pilot"
        user_rows = [
            {
                "user": SimpleNamespace(username="pilot_user"),
                "main_character": SimpleNamespace(character_name="Main Label"),
                "elite_pilots": [
                    {
                        "character": in_scope_character,
                        "progress": {"required_pct": 100, "recommended_pct": 100, "can_fly": True},
                        "required_missing_sp": 0,
                        "recommended_missing_sp": 0,
                    }
                ],
                "almost_elite_pilots": [],
                "can_fly_pilots": [],
                "almost_fit_pilots": [],
                "needs_training_pilots": [],
            }
        ]

        response = _summary_fitting_member_coverage_csv_response(
            fitting=fitting,
            user_rows=user_rows,
        )
        payload = response.content.decode("utf-8")

        self.assertIn("In Scope Pilot", payload)
        self.assertNotIn(out_scope_name, payload)

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
        doctrine_map = SimpleNamespace(priority=7)
        fitting_map = SimpleNamespace(skillset=skillset, doctrine_map=doctrine_map, priority=9)
        doctrine = SimpleNamespace(id=2)
        mock_fitting_404.return_value = (fitting, fitting_map, doctrine)
        mock_get_chars.return_value = []
        mock_progress_service.export_mode_choices.return_value = [("recommended", "Recommended")]
        mock_progress_service.EXPORT_MODE_RECOMMENDED = "recommended"
        mock_progress_service.normalize_export_language.return_value = "en"

        req = self._req(path="/fitting/1/")
        response = views.pilot_fitting_detail_view(req, fitting_id=1)
        self.assertEqual(response.status_code, 200)
        context = mock_render.call_args[0][2]
        self.assertEqual(context["fitting_priority"], 9)
        self.assertEqual(context["doctrine_priority"], 7)

    @patch("mastery.views.pilot.render", return_value=HttpResponse("ok"))
    @patch("mastery.views.pilot.pilot_progress_service")
    @patch("mastery.views.pilot._get_pilot_detail_characters")
    @patch("mastery.views.pilot._get_accessible_fitting_or_404")
    def test_pilot_fitting_detail_view_exposes_recommended_clone_profile(
        self,
        mock_fitting_404,
        mock_get_chars,
        mock_progress_service,
        mock_render,
    ):
        fitting = SimpleNamespace(id=1, name="Fit", ship_type=SimpleNamespace(name="Drake"))
        skillset = SimpleNamespace(id=10)
        fitting_map = SimpleNamespace(skillset=skillset, doctrine_map=None, priority=0)
        mock_fitting_404.return_value = (fitting, fitting_map, SimpleNamespace(id=2))
        mock_get_chars.return_value = []
        mock_progress_service.export_mode_choices.return_value = [("recommended", "Recommended")]
        mock_progress_service.EXPORT_MODE_RECOMMENDED = "recommended"
        mock_progress_service.normalize_export_language.return_value = "en"
        mock_progress_service.export_language_choices.return_value = [("en", "English")]
        mock_progress_service.summarize_plan_clone_requirements.return_value = {
            "recommended_plan_skill_count": 6,
            "recommended_plan_omega_skill_count": 2,
            "recommended_plan_alpha_compatible": False,
        }

        req = self._req(path="/fitting/1/")
        response = views.pilot_fitting_detail_view(req, fitting_id=1)

        self.assertEqual(response.status_code, 200)
        context = mock_render.call_args[0][2]
        self.assertEqual(context["recommended_plan_skill_count"], 6)
        self.assertEqual(context["recommended_plan_omega_skill_count"], 2)
        self.assertFalse(context["recommended_plan_alpha_compatible"])
        mock_progress_service.summarize_plan_clone_requirements.assert_called_once_with(
            skillset,
            cache_context={},
        )

    @patch("mastery.views.pilot.render", return_value=HttpResponse("ok"))
    @patch("mastery.views.pilot.pilot_progress_service")
    @patch("mastery.views.pilot._get_summary_group_by_id")
    @patch("mastery.views.pilot._get_pilot_detail_characters")
    @patch("mastery.views.pilot._get_accessible_fitting_or_404")
    def test_pilot_fitting_detail_view_applies_group_activity_window(
        self,
        mock_fitting_404,
        mock_get_chars,
        mock_get_group,
        mock_progress_service,
        mock_render,
    ):
        fitting = SimpleNamespace(id=1, name="Fit", ship_type=SimpleNamespace(name="Drake"))
        skillset = SimpleNamespace(id=10)
        fitting_map = SimpleNamespace(skillset=skillset, doctrine_map=None)
        doctrine = SimpleNamespace(id=2)
        summary_group = SimpleNamespace(id=99, name="Group")
        character = SimpleNamespace(id=5, eve_character=SimpleNamespace(character_name="Scoped Pilot"))
        mock_fitting_404.return_value = (fitting, fitting_map, doctrine)
        mock_get_group.return_value = summary_group
        mock_get_chars.return_value = [character]
        mock_progress_service.build_for_character.return_value = {
            "can_fly": True,
            "required_pct": 100,
            "recommended_pct": 100,
            "status_label": "Elite ready",
            "status_class": "success",
            "missing_required": [],
            "missing_recommended": [],
            "missing_required_count": 0,
            "missing_recommended_count": 0,
            "total_missing_sp": 0,
            "mode_stats": {"recommended": {"coverage_pct": 100, "total_missing_sp": 0, "total_missing_time": None}},
        }
        mock_progress_service.export_mode_choices.return_value = [("recommended", "Recommended")]
        mock_progress_service.EXPORT_MODE_RECOMMENDED = "recommended"
        mock_progress_service.normalize_export_language.return_value = "en"
        mock_progress_service.localize_missing_rows.side_effect = lambda rows, language: rows
        mock_progress_service.build_export_lines.return_value = []
        mock_progress_service.build_skill_plan_summary.return_value = None
        mock_progress_service.export_language_choices.return_value = [("en", "English")]

        req = self._req(path="/fitting/1/?group_id=99&activity_days=21&include_inactive=1")
        response = views.pilot_fitting_detail_view(req, fitting_id=1)

        self.assertEqual(response.status_code, 200)
        mock_get_chars.assert_called_once_with(
            req.user,
            summary_group=summary_group,
            activity_days=21,
            include_inactive=True,
        )
        context = mock_render.call_args[0][2]
        self.assertEqual(context["activity_days"], 21)
        self.assertTrue(context["include_inactive"])
        self.assertIn("activity_days=21", context["character_rows"][0]["action_url"])
        self.assertIn("include_inactive=1", context["character_rows"][0]["action_url"])

    @patch("mastery.views.pilot._get_summary_group_by_id", return_value=None)
    @patch("mastery.views.pilot._get_accessible_fitting_or_404")
    def test_pilot_fitting_detail_view_returns_400_for_invalid_summary_group(
        self,
        mock_fitting_404,
        _mock_get_group,
    ):
        fitting = SimpleNamespace(id=1, name="Fit", ship_type=SimpleNamespace(name="Drake"))
        fitting_map = SimpleNamespace(skillset=SimpleNamespace(id=10), doctrine_map=None)
        doctrine = SimpleNamespace(id=2)
        mock_fitting_404.return_value = (fitting, fitting_map, doctrine)

        req = self._req(path="/fitting/1/?group_id=999")
        response = views.pilot_fitting_detail_view(req, fitting_id=1)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.content.decode(), "Invalid summary group")

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
    @patch("mastery.views.pilot._get_summary_group_by_id")
    @patch("mastery.views.pilot._get_pilot_detail_characters")
    @patch("mastery.views.pilot._get_accessible_fitting_or_404")
    def test_skillplan_export_returns_text_file_for_valid_request(
        self,
        mock_fitting_404,
        mock_get_chars,
        mock_get_group,
        mock_progress_service,
    ):
        fitting = SimpleNamespace(id=5)
        skillset = SimpleNamespace(id=10)
        fitting_map = SimpleNamespace(skillset=skillset)
        mock_fitting_404.return_value = (fitting, fitting_map, None)
        summary_group = SimpleNamespace(id=7, name="Group")
        mock_get_group.return_value = summary_group

        char = SimpleNamespace(id=99)
        char_qs = Mock()
        char_qs.filter.return_value.first.return_value = char
        mock_get_chars.return_value = char_qs

        mock_progress_service.EXPORT_MODE_RECOMMENDED = "recommended"
        mock_progress_service.normalize_export_language.return_value = "en"
        mock_progress_service.export_mode_choices.return_value = [("recommended", "Recommended")]
        mock_progress_service.build_for_character.return_value = {"can_fly": True}
        mock_progress_service.build_export_lines.return_value = ["Skill A 5", "Skill B 4"]

        req = self._req(path="/fitting/5/export/?character_id=99&group_id=7&activity_days=21&include_inactive=1")
        response = views.pilot_fitting_skillplan_export_view(req, fitting_id=5)

        self.assertEqual(response.status_code, 200)
        self.assertIn("text/plain", response.get("Content-Type", ""))
        self.assertIn("attachment", response.get("Content-Disposition", ""))
        self.assertIn("Skill A 5", response.content.decode())
        mock_get_chars.assert_called_once_with(
            req.user,
            summary_group=summary_group,
            activity_days=21,
            include_inactive=True,
        )

    @patch("mastery.views.pilot._get_summary_group_by_id", return_value=None)
    @patch("mastery.views.pilot._get_accessible_fitting_or_404")
    def test_skillplan_export_returns_400_for_invalid_summary_group(
        self,
        mock_fitting_404,
        _mock_get_group,
    ):
        mock_fitting_404.return_value = (
            SimpleNamespace(id=1),
            SimpleNamespace(skillset=SimpleNamespace(id=10)),
            None,
        )

        req = self._req(path="/fitting/1/export/?character_id=99&group_id=999")
        response = views.pilot_fitting_skillplan_export_view(req, fitting_id=1)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.content.decode(), "Invalid summary group")

    # -- index ---------------------------------------------------------------

    @patch("mastery.views.pilot.render", return_value=HttpResponse("ok"))
    @patch("mastery.views.pilot._get_doctrine_priority_map", return_value={1: 6})
    @patch("mastery.views.pilot.pilot_progress_service")
    @patch("mastery.views.pilot._approved_fitting_maps")
    @patch("mastery.views.pilot._get_member_characters")
    @patch("mastery.views.pilot.pilot_access_service")
    def test_pilot_index_exposes_recommended_clone_profile_per_fitting(
        self,
        mock_access_service,
        mock_get_chars,
        mock_approved_fitting_maps,
        mock_progress_service,
        _mock_doctrine_priority_map,
        mock_render,
    ):
        fitting = SimpleNamespace(
            id=5,
            name="Cerb Fleet",
            ship_type=SimpleNamespace(name="Cerberus"),
            ship_type_type_id=123,
        )
        doctrine = SimpleNamespace(id=1, name="Shield", fittings=Mock())
        doctrine.fittings.all.return_value = [fitting]
        skillset = SimpleNamespace(id=10)
        fitting_map = SimpleNamespace(skillset=skillset, priority=8)
        character = SimpleNamespace(id=42, eve_character=SimpleNamespace(character_name="Pilot One"))

        mock_access_service.accessible_doctrines.return_value = [doctrine]
        mock_get_chars.return_value = [character]
        mock_approved_fitting_maps.return_value = {5: fitting_map}
        mock_progress_service.build_for_character.return_value = {
            "can_fly": True,
            "required_pct": 100,
            "recommended_pct": 80,
            "status_label": "Can fly",
            "status_class": "info",
            "missing_required": [],
            "missing_recommended": [],
            "missing_required_count": 0,
            "missing_recommended_count": 1,
            "total_missing_sp": 1234,
            "mode_stats": {"required": {"total_missing_sp": 0}, "recommended": {"total_missing_sp": 1234}},
        }
        mock_progress_service.summarize_plan_clone_requirements.return_value = {
            "recommended_plan_skill_count": 7,
            "recommended_plan_omega_skill_count": 2,
            "recommended_plan_alpha_compatible": False,
        }

        req = self._req(path="/")
        response = views.index(req)

        self.assertEqual(response.status_code, 200)
        context = mock_render.call_args[0][2]
        self.assertEqual(context["configured_fittings_count"], 1)
        fit_card = context["doctrine_cards"][0]["fittings"][0]
        self.assertEqual(fit_card["recommended_plan_skill_count"], 7)
        self.assertEqual(fit_card["recommended_plan_omega_skill_count"], 2)
        self.assertFalse(fit_card["recommended_plan_alpha_compatible"])
        mock_progress_service.summarize_plan_clone_requirements.assert_called_once()

    @patch("mastery.views.pilot.render", return_value=HttpResponse("ok"))
    @patch("mastery.views.pilot._approved_fitting_maps")
    @patch("mastery.views.pilot._get_member_characters")
    @patch("mastery.views.pilot.pilot_access_service")
    def test_pilot_index_renders_empty_cards_when_no_fittings(
        self,
        mock_access_service,
        mock_get_chars,
        mock_approved_fitting_maps,
        mock_render,
    ):
        doctrine = SimpleNamespace(id=1, name="Alpha", fittings=Mock())
        doctrine.fittings.all.return_value = []
        mock_access_service.accessible_doctrines.return_value = [doctrine]
        mock_get_chars.return_value = []
        mock_approved_fitting_maps.return_value = {}

        req = self._req(path="/")
        response = views.index(req)
        self.assertEqual(response.status_code, 200)
        context = mock_render.call_args[0][2]
        self.assertEqual(context["doctrine_cards"], [])
        self.assertEqual(context["configured_fittings_count"], 0)
