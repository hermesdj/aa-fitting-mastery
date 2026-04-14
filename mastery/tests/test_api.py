import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import RequestFactory, SimpleTestCase

from mastery import api


def _api_user():
    return SimpleNamespace(
        is_authenticated=True,
        has_perm=lambda _perm: True,
        has_perms=lambda _perms: True,
    )


class TestMasteryApi(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def _post_json(self, path: str, payload: dict):
        request = self.factory.post(path, data=json.dumps(payload), content_type="application/json")
        request.user = _api_user()
        return request

    @patch("mastery.api.Fitting.objects.filter")
    @patch("mastery.api.Doctrine.objects.filter")
    def test_toggle_blacklist_returns_400_when_entities_not_found(self, mock_doctrine_filter, mock_fitting_filter):
        mock_fitting_filter.return_value.first.return_value = None
        mock_doctrine_filter.return_value.first.return_value = None

        request = self._post_json(
            "/api/skill/toggle_blacklist",
            {"fitting_id": 1, "skill_type_id": 10, "value": True},
        )

        response = api.toggle_blacklist(request)

        self.assertEqual(response.status_code, 400)
        payload = json.loads(response.content.decode())
        self.assertEqual(payload["status"], "error")

    @patch("mastery.api.doctrine_skill_service.generate_for_fitting")
    @patch("mastery.api.control_service.set_blacklist")
    @patch("mastery.api.DoctrineSkillSetGroupMap.objects.filter")
    @patch("mastery.api.Doctrine.objects.filter")
    @patch("mastery.api.Fitting.objects.filter")
    def test_toggle_blacklist_applies_explicit_true_value(
        self,
        mock_fitting_filter,
        mock_doctrine_filter,
        mock_map_filter,
        mock_set_blacklist,
        mock_generate,
    ):
        fitting = Mock()
        doctrine = Mock()
        doctrine_map = Mock()
        mock_fitting_filter.return_value.first.return_value = fitting
        mock_doctrine_filter.return_value.first.return_value = doctrine
        mock_map_filter.return_value.first.return_value = doctrine_map

        request = self._post_json(
            "/api/skill/toggle_blacklist",
            {"fitting_id": 8, "skill_type_id": 55, "value": "true"},
        )

        response = api.toggle_blacklist(request)

        self.assertEqual(response.status_code, 200)
        mock_set_blacklist.assert_called_once_with(fitting_id=8, skill_type_id=55, value=True)
        mock_generate.assert_called_once_with(doctrine_map, fitting)
        payload = json.loads(response.content.decode())
        self.assertEqual(payload["blacklisted"], True)

    @patch("mastery.api.doctrine_skill_service.generate_for_fitting")
    @patch("mastery.api.control_service.set_blacklist")
    @patch("mastery.api.control_service.get_blacklist")
    @patch("mastery.api.doctrine_map_service.create_doctrine_map")
    @patch("mastery.api.DoctrineSkillSetGroupMap.objects.filter")
    @patch("mastery.api.Doctrine.objects.filter")
    @patch("mastery.api.Fitting.objects.filter")
    def test_toggle_blacklist_without_value_uses_toggle_logic_and_can_create_map(
        self,
        mock_fitting_filter,
        mock_doctrine_filter,
        mock_map_filter,
        mock_create_map,
        mock_get_blacklist,
        mock_set_blacklist,
        mock_generate,
    ):
        fitting = Mock()
        doctrine = Mock()
        doctrine_map = Mock()
        mock_fitting_filter.return_value.first.return_value = fitting
        mock_doctrine_filter.return_value.first.return_value = doctrine
        mock_map_filter.return_value.first.return_value = None
        mock_create_map.return_value = doctrine_map
        mock_get_blacklist.return_value = {101}

        request = self._post_json(
            "/api/skill/toggle_blacklist",
            {"fitting_id": 8, "skill_type_id": 55},
        )

        response = api.toggle_blacklist(request)

        self.assertEqual(response.status_code, 200)
        mock_create_map.assert_called_once_with(doctrine)
        mock_set_blacklist.assert_called_once_with(fitting_id=8, skill_type_id=55, value=True)
        mock_generate.assert_called_once_with(doctrine_map, fitting)
        payload = json.loads(response.content.decode())
        self.assertEqual(payload["blacklisted"], True)

    def test_update_skill_level_returns_not_implemented(self):
        request = self.factory.post("/api/skill/update/", data={})
        request.user = _api_user()

        response = api.update_skill_level(request)

        self.assertEqual(response.status_code, 501)
        payload = json.loads(response.content.decode())
        self.assertEqual(payload["status"], "not_implemented")

