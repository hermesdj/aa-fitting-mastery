from django.apps import AppConfig

from .app_settings import securegroups_installed


class MasteryConfig(AppConfig):
    name = "mastery"
    label = "mastery"
    verbose_name = "Fitting Mastery Plugin"

    def ready(self):
        # Register Secure Groups filter models only when the plugin is installed.
        # This ensures Django's ContentType framework discovers the filters and
        # secure-groups can populate its Smart Filter catalog automatically.
        if securegroups_installed():
            from mastery import secure_groups  # noqa: F401
