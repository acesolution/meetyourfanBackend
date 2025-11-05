# sociallogins/urls.py

from django.urls import path  # built-in: maps URL patterns to view callables
from sociallogins.views import ig_login_start, ig_login_callback
urlpatterns = [
    path("auth/ig/login", ig_login_start, name="ig_login_start"),
    path("auth/ig/callback", ig_login_callback, name="ig_login_cb"),
]
