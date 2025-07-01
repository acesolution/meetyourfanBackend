# profileapp/apps.py
from django.apps import AppConfig

class ProfileAppConfig(AppConfig):
    name = 'profileapp'
    default_auto_field = 'django.db.models.BigAutoField'

    def ready(self):
        # Import signals so that they are registered.
        import profileapp.signals
