from django.apps import AppConfig


class AdminPanelConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.adminpanel'
    verbose_name = 'Admin dashboard'

    def ready(self):
        from . import signals  # noqa: F401
