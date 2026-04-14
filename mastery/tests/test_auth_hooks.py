from types import SimpleNamespace

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
