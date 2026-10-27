from django.apps import AppConfig


class StaysConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "stays"
    verbose_name = "Apartments & bookings"

    def ready(self):
        from . import signals  # noqa: F401  (activity log + housekeeping hooks)
