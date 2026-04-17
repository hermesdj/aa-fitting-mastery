from unittest.mock import patch

from django.template import Context, Template
from django.test import RequestFactory, SimpleTestCase
from django.test import override_settings

from mastery.views import common


class TestCommonHelpersExtra(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_parse_posted_int_accepts_localized_values(self):
        self.assertEqual(common._parse_posted_int("1 234", "x"), 1234)
        self.assertEqual(common._parse_posted_int("1,0", "x"), 1)

    def test_parse_posted_int_rejects_non_integer(self):
        with self.assertRaises(ValueError):
            common._parse_posted_int("1.5", "x")

    def test_get_user_display_prefers_full_name_then_username(self):
        user_full = type("U", (), {"get_full_name": lambda self: "John Doe", "username": "jdoe"})()
        user_username = type("U", (), {"get_full_name": lambda self: "", "username": "jdoe"})()

        self.assertEqual(common._get_user_display(user_full), "John Doe")
        self.assertEqual(common._get_user_display(user_username), "jdoe")

    def test_build_actor_display_handles_none(self):
        self.assertIsNone(common._build_actor_display(None))

    def test_bad_request_response_ajax_and_non_ajax(self):
        ajax_request = self.factory.post("/", HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        normal_request = self.factory.post("/")

        ajax_response = common._bad_request_response(ajax_request, "oops")
        normal_response = common._bad_request_response(normal_request, "oops")

        self.assertEqual(ajax_response.status_code, 400)
        self.assertEqual(normal_response.status_code, 400)
        self.assertIn(b"oops", normal_response.content)

    @patch("mastery.views.common.render_to_string", return_value="<div>alert</div>")
    def test_render_ajax_messages_html(self, _mock_render):
        request = self.factory.get("/")
        html = common._render_ajax_messages_html(request, message="Saved", level="error")
        self.assertIn("alert", html)

    def test_render_ajax_messages_html_returns_empty_without_message(self):
        request = self.factory.get("/")
        self.assertEqual(common._render_ajax_messages_html(request, message=None), "")

    def test_format_duration_from_seconds(self):
        self.assertEqual(common._format_duration_from_seconds(0), "0m")
        self.assertEqual(common._format_duration_from_seconds(3660), "1h 1m")

    @patch("mastery.views.common._build_fitting_skills_ajax_response")
    def test_finalize_action_uses_ajax_builder_for_ajax_requests(self, mock_ajax_builder):
        request = self.factory.post("/", HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        mock_ajax_builder.return_value = common.JsonResponse({"status": "ok"})

        response = common._finalize_fitting_skills_action(
            request,
            fitting=type("F", (), {"id": 1})(),
            doctrine=object(),
            doctrine_map=object(),
            message="Saved",
        )

        self.assertEqual(response.status_code, 200)
        mock_ajax_builder.assert_called_once()

    @patch("mastery.views.common.redirect")
    @patch("mastery.views.common._add_feedback_message")
    def test_finalize_action_redirects_to_next(self, mock_feedback, mock_redirect):
        request = self.factory.post("/", data={"next": "/return"})
        mock_redirect.return_value = common.HttpResponseBadRequest("redirected")

        response = common._finalize_fitting_skills_action(
            request,
            fitting=type("F", (), {"id": 1})(),
            doctrine=object(),
            doctrine_map=object(),
            message="Saved",
        )

        self.assertEqual(response.status_code, 400)
        mock_feedback.assert_called_once()
        mock_redirect.assert_called_once_with("/return")

    @patch("mastery.views.common.redirect")
    @patch("mastery.views.common._add_feedback_message")
    def test_finalize_action_redirects_to_next_with_active_group(self, mock_feedback, mock_redirect):
        request = self.factory.post("/", data={"next": "/return?x=1", "active_group": "217"})
        mock_redirect.return_value = common.HttpResponseBadRequest("redirected")

        response = common._finalize_fitting_skills_action(
            request,
            fitting=type("F", (), {"id": 1})(),
            doctrine=object(),
            doctrine_map=object(),
            message="Saved",
        )

        self.assertEqual(response.status_code, 400)
        mock_feedback.assert_called_once()
        mock_redirect.assert_called_once_with("/return?x=1&active_group=217")

    @patch("mastery.views.common.redirect")
    @patch("mastery.views.common._add_feedback_message")
    def test_finalize_action_normalizes_localized_active_group(self, mock_feedback, mock_redirect):
        request = self.factory.post("/", data={"next": "/return", "active_group": "1,217"})
        mock_redirect.return_value = common.HttpResponseBadRequest("redirected")

        response = common._finalize_fitting_skills_action(
            request,
            fitting=type("F", (), {"id": 1})(),
            doctrine=object(),
            doctrine_map=object(),
            message="Saved",
        )

        self.assertEqual(response.status_code, 400)
        mock_feedback.assert_called_once()
        mock_redirect.assert_called_once_with("/return?active_group=1217")

    @override_settings(USE_THOUSAND_SEPARATOR=True)
    def test_group_key_template_fragment_uses_unlocalize(self):
        template = Template(
            "{% load l10n %}{% localize on %}"
            "<button data-group-key=\"{{ value|default:'other'|unlocalize }}\"></button>"
            "<input type=\"hidden\" name=\"_group_key\" value=\"{{ value|default:'other'|unlocalize }}\">"
            "{% endlocalize %}"
        )
        rendered = template.render(Context({"value": 1217}))

        self.assertIn('data-group-key="1217"', rendered)
        self.assertIn('name="_group_key" value="1217"', rendered)

    @patch("mastery.views.common.doctrine_skill_service.generate_for_fitting")
    @patch("mastery.views.common.control_service.set_blacklist")
    @patch("mastery.views.common.doctrine_skill_service.preview_fitting")
    def test_apply_preview_suggestions_applies_add_remove(self, mock_preview, mock_set_blacklist, mock_generate):
        fitting = type("F", (), {"id": 10})()
        doctrine_map = object()
        mock_preview.return_value = {
            "skill_rows": [
                {"skill_type_id": 55, "is_suggested": True, "suggestion_action": "remove"},
                {"skill_type_id": 66, "is_suggested": True, "suggestion_action": "add"},
            ]
        }

        applied = common._apply_preview_suggestions(fitting=fitting, doctrine_map=doctrine_map, modified_by="u")

        self.assertEqual(applied, 2)
        self.assertEqual(mock_set_blacklist.call_count, 2)
        mock_generate.assert_called_once()

    @patch("mastery.views.common.doctrine_skill_service.generate_for_fitting")
    @patch("mastery.views.common.control_service.set_blacklist")
    @patch("mastery.views.common.doctrine_skill_service.preview_fitting")
    def test_apply_preview_suggestions_returns_zero_when_filtered_out(self, mock_preview, mock_set_blacklist, mock_generate):
        fitting = type("F", (), {"id": 10})()
        doctrine_map = object()
        mock_preview.return_value = {
            "skill_rows": [
                {"skill_type_id": 55, "is_suggested": True, "suggestion_action": "remove"},
            ]
        }

        applied = common._apply_preview_suggestions(
            fitting=fitting,
            doctrine_map=doctrine_map,
            allowed_skill_ids={66},
            modified_by="u",
        )

        self.assertEqual(applied, 0)
        mock_set_blacklist.assert_not_called()
        mock_generate.assert_not_called()

