from django.test import RequestFactory, SimpleTestCase
from unittest.mock import Mock, patch

from mastery.views.fitting import _require_post_and_resolve
from mastery import views
from django.http import HttpResponseBadRequest

class TestRefactorHelpers(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    @staticmethod
    def _user():
        return type(
            "U",
            (),
            {
                "is_authenticated": True,
                "has_perm": lambda self, _perm: True,
                "has_perms": lambda self, _perms: True,
            },
        )()

    def test_require_post_and_resolve_returns_bad_request_for_get(self):
        request = self.factory.get("/fitting/1/")
        resolved, error = _require_post_and_resolve(request, fitting_id=1)
        self.assertIsNone(resolved)
        self.assertIsNotNone(error)
        self.assertEqual(getattr(error, "status_code", None), 400)

    def test_apply_suggestions_returns_bad_request_when_missing_map(self):
        # simulate the helper returning an error response
        request = self.factory.post("/fitting/1/skills/apply-suggestions/", data={})
        request.user = self._user()
        # monkeypatch the require helper to return an error
        from unittest.mock import patch

        with patch("mastery.views.fitting._require_post_and_resolve", return_value=(None, HttpResponseBadRequest("No doctrine map found for fitting"))):
            response = views.apply_suggestions_view(request, fitting_id=1)
        self.assertEqual(response.status_code, 400)
        self.assertIn(b"No doctrine map found for fitting", response.content)

    def test_apply_skill_suggestion_invalid_skill_type_returns_bad_request(self):
        request = self.factory.post("/fitting/1/skills/apply-suggestion/", data={"skill_type_id": "abc"})
        request.user = self._user()
        response = views.apply_skill_suggestion_view(request, fitting_id=1)
        self.assertEqual(response.status_code, 400)

    def test_update_fitting_approval_status_approve_requires_synced(self):
        request = self.factory.post("/fitting/1/approval/", data={"action": "approve"})
        request.user = self._user()
        # create a fake resolved tuple with fitting_map missing last_synced_at
        fake_fitting = object()
        fake_doctrine = object()
        fake_doctrine_map = object()
        fake_fitting_map = object()
        from unittest.mock import patch

        with patch("mastery.views.fitting._require_post_and_resolve", return_value=((fake_fitting, fake_doctrine, fake_doctrine_map, fake_fitting_map), None)):
            response = views.update_fitting_approval_status_view(request, fitting_id=1)
        self.assertEqual(response.status_code, 400)

    def test_update_skill_group_controls_unsupported_action_returns_bad_request(self):
        request = self.factory.post(
            "/fitting/1/skills/group-controls/",
            data={"action": "unsupported", "skill_type_ids": ["55"]},
        )
        request.user = self._user()

        fake_resolved = (object(), object(), object(), None)
        from unittest.mock import patch

        with patch("mastery.views.fitting._require_post_and_resolve", return_value=(fake_resolved, None)):
            response = views.update_skill_group_controls_view(request, fitting_id=1)

        self.assertEqual(response.status_code, 400)

    def test_add_manual_skill_returns_bad_request_when_skill_not_found(self):
        request = self.factory.post(
            "/fitting/1/skills/manual/add/",
            data={"skill_name": "Missing Skill", "recommended_level": "2"},
        )
        request.user = self._user()

        fake_resolved = (object(), object(), object(), None)
        from unittest.mock import patch

        with patch("mastery.views.fitting._require_post_and_resolve", return_value=(fake_resolved, None)), patch(
            "mastery.views.fitting.ItemType.objects.filter"
        ) as mock_filter:
            mock_filter.return_value.first.return_value = None
            response = views.add_manual_skill_view(request, fitting_id=1)

        self.assertEqual(response.status_code, 400)

    def test_remove_manual_skill_success(self):
        request = self.factory.post(
            "/fitting/1/skills/manual/remove/",
            data={"skill_type_id": "55"},
        )
        request.user = self._user()

        fake_fitting = object()
        fake_doctrine = object()
        fake_doctrine_map = object()
        from unittest.mock import patch
        from django.http import JsonResponse

        with patch(
            "mastery.views.fitting._require_post_and_resolve",
            return_value=((fake_fitting, fake_doctrine, fake_doctrine_map, None), None),
        ), patch("mastery.views.fitting.control_service.remove_manual_skill") as mock_remove, patch(
            "mastery.views.fitting.doctrine_skill_service.generate_for_fitting"
        ) as mock_generate, patch(
            "mastery.views.fitting._finalize_fitting_skills_action",
            return_value=JsonResponse({"status": "ok"}),
        ):
            response = views.remove_manual_skill_view(request, fitting_id=1)

        self.assertEqual(response.status_code, 200)
        mock_remove.assert_called_once_with(fitting_id=1, skill_type_id=55)
        mock_generate.assert_called_once()

    @patch("mastery.views.fitting._get_doctrine_and_map_for_fitting")
    def test_resolve_fitting_context_returns_error_when_doctrine_missing(self, mock_get):
        from mastery.views.fitting import _resolve_fitting_context

        request = self.factory.post("/fitting/1/")
        mock_get.return_value = (object(), None, None, None)

        resolved, error = _resolve_fitting_context(request, fitting_id=1)
        self.assertIsNone(resolved)
        self.assertEqual(error.status_code, 400)

    @patch("mastery.views.fitting.doctrine_map_service.create_doctrine_map")
    @patch("mastery.views.fitting._get_doctrine_and_map_for_fitting")
    def test_resolve_fitting_context_creates_missing_map(self, mock_get, mock_create_map):
        from mastery.views.fitting import _resolve_fitting_context

        request = self.factory.post("/fitting/1/")
        fitting = object()
        doctrine = object()
        doctrine_map = object()
        mock_get.return_value = (fitting, doctrine, None, None)
        mock_create_map.return_value = doctrine_map

        resolved, error = _resolve_fitting_context(request, fitting_id=1)
        self.assertIsNone(error)
        self.assertEqual(resolved, (fitting, doctrine, doctrine_map, None))

    def test_update_fitting_mastery_requires_post(self):
        request = self.factory.get("/fitting/1/mastery/")
        request.user = self._user()

        response = views.update_fitting_mastery(request, fitting_id=1)
        self.assertEqual(response.status_code, 400)

    @patch("mastery.views.fitting._parse_mastery_level", side_effect=ValueError("bad mastery"))
    @patch("mastery.views.fitting.fitting_map_service.create_fitting_map")
    @patch("mastery.views.fitting.DoctrineSkillSetGroupMap.objects.filter")
    @patch("mastery.views.fitting.get_object_or_404")
    def test_update_fitting_mastery_invalid_level_returns_bad_request(
        self,
        mock_get_object_or_404,
        mock_filter,
        mock_create_fitting_map,
        _mock_parse,
    ):
        doctrine = object()
        fitting = object()
        fitting_map = Mock()
        mock_get_object_or_404.side_effect = [doctrine, fitting]
        mock_filter.return_value.first.return_value = object()
        mock_create_fitting_map.return_value = fitting_map

        request = self.factory.post("/fitting/1/mastery/", data={"doctrine_id": "2", "mastery_level": "x"})
        request.user = self._user()

        response = views.update_fitting_mastery(request, fitting_id=1)
        self.assertEqual(response.status_code, 400)
        self.assertIn(b"bad mastery", response.content)

    @patch("mastery.views.fitting._build_fitting_skills_ajax_response")
    @patch("mastery.views.fitting.doctrine_skill_service.generate_for_fitting")
    @patch("mastery.views.fitting._parse_mastery_level", return_value=4)
    @patch("mastery.views.fitting.fitting_map_service.create_fitting_map")
    @patch("mastery.views.fitting.DoctrineSkillSetGroupMap.objects.filter")
    @patch("mastery.views.fitting.get_object_or_404")
    def test_update_fitting_mastery_ajax_success(
        self,
        mock_get_object_or_404,
        mock_filter,
        mock_create_fitting_map,
        _mock_parse,
        mock_generate,
        mock_ajax,
    ):
        doctrine = object()
        fitting = object()
        fitting_map = Mock()
        mock_get_object_or_404.side_effect = [doctrine, fitting]
        mock_filter.return_value.first.return_value = object()
        mock_create_fitting_map.return_value = fitting_map
        mock_ajax.return_value = HttpResponseBadRequest("ok")

        request = self.factory.post(
            "/fitting/1/mastery/",
            data={"doctrine_id": "2", "mastery_level": "4"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        request.user = self._user()

        response = views.update_fitting_mastery(request, fitting_id=1)
        self.assertEqual(response.status_code, 400)
        fitting_map.save.assert_called_once_with(update_fields=["mastery_level"])
        mock_generate.assert_called_once()
        mock_ajax.assert_called_once()

    @patch("mastery.views.fitting._get_doctrine_and_map_for_fitting")
    def test_fitting_skills_preview_no_doctrine_returns_bad_request(self, mock_get):
        mock_get.return_value = (object(), None, None, None)
        request = self.factory.get("/fitting/1/preview/")
        request.user = self._user()

        response = views.fitting_skills_preview_view(request, fitting_id=1)
        self.assertEqual(response.status_code, 400)

    @patch("mastery.views.fitting._get_doctrine_and_map_for_fitting")
    def test_fitting_skills_preview_invalid_mastery_level_returns_bad_request(self, mock_get):
        doctrine = object()
        fitting = object()
        fitting_map = type("FM", (), {"status": "approved"})()
        doctrine_map = object()
        mock_get.return_value = (fitting, doctrine, doctrine_map, fitting_map)

        request = self.factory.get("/fitting/1/preview/?mastery_level=abc")
        request.user = type(
            "U",
            (),
            {
                "is_authenticated": True,
                "has_perm": lambda self, perm: perm == "mastery.manage_fittings",
                "has_perms": lambda self, _perms: True,
            },
        )()

        response = views.fitting_skills_preview_view(request, fitting_id=1)
        self.assertEqual(response.status_code, 400)

