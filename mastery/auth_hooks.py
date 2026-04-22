from allianceauth import hooks
from allianceauth.services.hooks import UrlHook, MenuItemHook
from django.utils.translation import gettext_lazy as _

from . import urls
from .app_settings import securegroups_installed


if securegroups_installed():
    from .secure_groups import (
        MasteryDoctrineReadinessFilter,
        MasteryFittingEliteFilter,
        MasteryFittingProgressFilter,
        MasteryFittingStatusFilter,
    )

class MasteryMenu(MenuItemHook):
    def __init__(self):
        MenuItemHook.__init__(
            self,
            _("Skill Planner"),
            "fas fa-chart-bar",
            "mastery:pilot_index",
            navactive=["mastery:"],
        )

    def render(self, request):
        if request.user.has_perm("mastery.basic_access"):
            return MenuItemHook.render(self, request)
        return ""


@hooks.register("menu_item_hook")
def register_menu():
    return MasteryMenu()


@hooks.register("url_hook")
def register_urls():
    return UrlHook(urls, "fitting-mastery", r"^fitting-mastery/")


if securegroups_installed():
    @hooks.register("secure_group_filters")
    def register_secure_group_filters() -> list:
        """Expose mastery Smart Filter models to allianceauth-secure-groups."""
        return [
            MasteryFittingStatusFilter,
            MasteryFittingProgressFilter,
            MasteryDoctrineReadinessFilter,
            MasteryFittingEliteFilter,
        ]

