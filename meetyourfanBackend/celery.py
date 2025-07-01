#Project/celery.py

import os
from celery import Celery

# Set the default Django settings module for the 'celery' program.
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'meetyourfanBackend.settings')

# Create the Celery app instance
app = Celery('meetyourfanBackend')

# Load task modules from all registered Django app configs.
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()

# Configure beat schedule
app.conf.beat_schedule = {
    'close-expired-campaigns-every-minute': {
         'task': 'campaign.tasks.close_expired_campaigns',
         'schedule': 60.0,  # runs every minute
    },
}
