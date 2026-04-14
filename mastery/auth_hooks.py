from allianceauth import hooks
from allianceauth.services.hooks import UrlHook, MenuItemHook

from . import urls

class MasteryMenu(MenuItemHook):
    def __init__(self):
        MenuItemHook.__init__(
            self,
            "Skill Planner",
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
