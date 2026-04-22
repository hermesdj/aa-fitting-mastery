import importlib
import sys
import types
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from mastery.auth_hooks import MasteryMenu


class TestMasteryMenu(SimpleTestCase):
    def test_render_returns_empty_when_user_has_no_access(self):
        request = SimpleNamespace(user=SimpleNamespace(has_perm=lambda _perm: False))

        menu = MasteryMenu()

        self.assertEqual(menu.render(request), "")

    def test_render_returns_menu_html_when_user_has_access(self):
        request = SimpleNamespace(
            user=SimpleNamespace(has_perm=lambda _perm: True),
            path="/fitting-mastery/",
        )

        menu = MasteryMenu()

        rendered = menu.render(request)

        self.assertIn("Skill Planner", rendered)
        self.assertIn("fitting-mastery", rendered)


class TestSecureGroupsHook(SimpleTestCase):
    def test_register_secure_group_filters_returns_expected_models(self):
        auth_hooks_module = importlib.import_module("mastery.auth_hooks")

        fake_secure_groups = types.ModuleType("mastery.secure_groups")

        class _StatusFilter:
            pass

        class _ProgressFilter:
            pass

        class _DoctrineFilter:
            pass

        class _EliteFilter:
            pass

        fake_secure_groups.MasteryFittingStatusFilter = _StatusFilter
        fake_secure_groups.MasteryFittingProgressFilter = _ProgressFilter
        fake_secure_groups.MasteryDoctrineReadinessFilter = _DoctrineFilter
        fake_secure_groups.MasteryFittingEliteFilter = _EliteFilter

        try:
            with patch("mastery.app_settings.securegroups_installed", return_value=True), patch.dict(
                sys.modules,
                {"mastery.secure_groups": fake_secure_groups},
            ):
                importlib.reload(auth_hooks_module)
                filters = auth_hooks_module.register_secure_group_filters()
                self.assertEqual(
                    filters,
                    [_StatusFilter, _ProgressFilter, _DoctrineFilter, _EliteFilter],
                )
        finally:
            importlib.reload(auth_hooks_module)

