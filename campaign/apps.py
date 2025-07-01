# campaign/apps.py
from django.apps import AppConfig

class CampaignConfig(AppConfig):
    name = 'campaign'
    default_auto_field = 'django.db.models.BigAutoField'

    def ready(self):
        import campaign.signals  # This ensures your signal handlers are registered
