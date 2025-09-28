# sociallogins/urls.py

from django.urls import path  # built-in: maps URL patterns to view callables
from sociallogins.views import instagram_start, instagram_callback

urlpatterns = [
    path("auth/instagram/start/", instagram_start, name="ig-login-start"),
    path("auth/instagram/callback/", instagram_callback, name="ig-login-callback"),
]
