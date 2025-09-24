# sociallogins/views.py
import os
import requests                                    # third-party HTTP client
from urllib.parse import urlencode                 # built-in: dict -> querystring
from django.shortcuts import redirect              # built-in: 302 redirect
from django.contrib.auth import get_user_model, login  # built-in: user model + session login
from django.urls import reverse                    # built-in: build URL by name
from django.db import transaction                  # built-in: atomic DB block
from .models import SocialProfile

GRAPH = "https://graph.facebook.com/v19.0"
APP_ID = os.environ["META_APP_ID"]
APP_SECRET = os.environ["META_APP_SECRET"]

def ig_login_start(request):
    # Build Meta OAuth URL (Instagram Business Login). urlencode is a built-in helper.
    params = {
        "client_id": APP_ID,
        "redirect_uri": request.build_absolute_uri(reverse("ig-login-callback")),  # built-in: absolute URL
        "response_type": "code",
        "scope": "instagram_basic,pages_show_list",  # minimum to resolve IG handle
        "state": "csrf_or_signed_payload",           # TODO: sign & later verify
    }
    return redirect(f"https://www.facebook.com/v19.0/dialog/oauth?{urlencode(params)}")

def ig_login_callback(request):
    code = request.GET.get("code")                  # dict.get is a built-in: safe key access
    if not code:
        return redirect("/login?error=denied")

    # 1) Exchange code -> user access token
    token_res = requests.get(
        f"{GRAPH}/oauth/access_token",
        params={
            "client_id": APP_ID,
            "client_secret": APP_SECRET,
            "redirect_uri": request.build_absolute_uri(reverse("ig-login-callback")),
            "code": code,
        },
    ).json()
    user_token = token_res.get("access_token")
    if not user_token:
        return redirect("/login?error=token_exchange_failed")

    # 2) Resolve IG account (two paths):
    # Preferred: Page -> connected_instagram_account (requires IG linked to a FB Page)
    pages = requests.get(
        f"{GRAPH}/me/accounts",
        params={"access_token": user_token, "fields": "id,name,access_token"},
    ).json().get("data", [])                        # list default via built-in get()

    ig_user_id = ig_username = None
    for page in pages:                               # for-loop is built-in
        r = requests.get(
            f"{GRAPH}/{page['id']}",
            params={
                "access_token": page["access_token"],
                "fields": "connected_instagram_account{username,id}",
            },
        ).json()
        ig = (r.get("connected_instagram_account") or {})  # dict.get: safe access
        if ig.get("id"):
            ig_user_id = ig["id"]
            ig_username = ig.get("username")
            break

    # If IG isn’t linked to a Page yet, you won’t get it here. You can still consider the user “logged in”
    # but you should route them to a wizard explaining: (1) Switch to Professional, (2) Link IG to a FB Page.
    if not ig_user_id:
        # OPTIONAL: Try a fallback endpoint *if* Meta exposes a direct IG id via your login URL variant.
        # If not, guide the user to link IG<->Page and retry.
        return redirect("/connect-instagram?status=link_page_first")

    # 3) Create/sign in a Django user keyed by ig_user_id (email isn’t guaranteed by IG login)
    User = get_user_model()                           # built-in: fetch AUTH_USER_MODEL
    with transaction.atomic():                        # built-in: commit/rollback as one unit
        user, _ = User.objects.get_or_create(         # built-in: SELECT or INSERT atomically
            username=f"ig_{ig_user_id}",
            defaults={"first_name": ig_username or ""},
        )
        prof, _ = SocialProfile.objects.get_or_create(user=user)
        prof.ig_user_id = ig_user_id
        prof.ig_username = ig_username
        prof.save()

    login(request, user)                              # built-in: sets session cookie
    return redirect("/dashboard")
