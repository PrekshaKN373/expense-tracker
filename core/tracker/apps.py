from django.apps import AppConfig


class TrackerConfig(AppConfig):
    name = "tracker"

    def ready(self):
        try:
            from tracker.firebase import get_db
            get_db()
        except (ImportError, FileNotFoundError):
            pass  # Firebase optional for migrate; required at runtime
