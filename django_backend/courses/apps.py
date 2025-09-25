from django.apps import AppConfig


class CoursesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'courses'

    def ready(self):
        # Import signals to auto-create notifications when files are added
        from . import signals  # noqa: F401