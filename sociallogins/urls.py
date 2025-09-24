# sociallogins/urls.py
from django.urls import path
from .views import ig_login_start, ig_login_callback
urlpatterns = [
    path("auth/instagram/start", ig_login_start, name="ig-login-start"),
    path("auth/instagram/callback", ig_login_callback, name="ig-login-callback"),
]
