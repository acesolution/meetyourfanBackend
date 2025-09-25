# sociallogins/views.py
import os
import requests                                     # third-party HTTP client
from urllib.parse import urlencode                  # built-in: dict -> querystring
from django.shortcuts import redirect               # built-in: HTTP 302 helper
from django.http import HttpResponseBadRequest      # built-in: quick 400 response
from django.contrib.auth import get_user_model, login  # built-in: auth helpers
from django.urls import reverse                     # built-in: build URL by name
from django.db import transaction                   # built-in: atomic DB writes
from .models import SocialProfile

GRAPH = os.getenv("META_GRAPH_URL", "https://graph.facebook.com/v19.0")
APP_ID = os.environ["META_APP_ID"]
APP_SECRET = os.environ["META_APP_SECRET"]
DEBUG_IG = os.getenv("IG_DEBUG", "0") == "1"        # set IG_DEBUG=1 to log responses

def _abs_redirect_uri(request):
    """
    Build the absolute callback URL.
    - reverse(): Django built-in that returns '/auth/instagram/callback'
    - build_absolute_uri(): Django built-in that prefixes with scheme+host to make it absolute
    """
    return request.build_absolute_uri(reverse("ig-login-callback"))

def ig_login_start(request):
    """
    Start Instagram Business Login (Meta OAuth).
    - urlencode(): stdlib helper that safely encodes a dict for a query string
    - redirect(): Django built-in that returns a 302 to the OAuth dialog URL
    """
    params = {
        "client_id": APP_ID,
        "redirect_uri": _abs_redirect_uri(request),
        "response_type": "code",
        "scope": "instagram_basic,pages_show_list",    # minimum to resolve Page -> IG
        "auth_type": "rerequest",                      # re-prompt if user unchecked before
        "state": "csrf_or_signed_payload",             # TODO: sign & verify in prod
    }
    url = f"https://www.facebook.com/v19.0/dialog/oauth?{urlencode(params)}"
    return redirect(url)  # built-in: sends HTTP 302

def ig_login_callback(request):
    """
    Handle Meta redirect, exchange code -> token, resolve IG via the linked Page,
    create/login the Django user, and redirect to your app.
    """
    # dict.get(): Python built-in that returns None (or a default) instead of raising KeyError
    if request.GET.get("error"):
        return redirect("/login?error=" + request.GET.get("error"))

    code = request.GET.get("code")
    if not code:
        return HttpResponseBadRequest("Missing code")  # built-in: quick 400

    redirect_uri = _abs_redirect_uri(request)

    # 1) Exchange code -> User Access Token (server-side because APP_SECRET is used)
    token_json = requests.get(
        f"{GRAPH}/oauth/access_token",
        params={
            "client_id": APP_ID,
            "client_secret": APP_SECRET,
            "redirect_uri": redirect_uri,
            "code": code,
        },
    ).json()
    if DEBUG_IG: print("IG TOKEN EXCHANGE:", token_json)  # built-in: print to logs
    user_token = token_json.get("access_token")
    if not user_token:
        return redirect("/login?error=token_exchange_failed")

    # 2) List Pages this user manages (needs pages_show_list)
    pages_json = requests.get(
        f"{GRAPH}/me/accounts",
        params={"access_token": user_token, "fields": "id,name,access_token"},
    ).json()
    if DEBUG_IG: print("IG PAGES:", pages_json)
    pages = pages_json.get("data", [])  # dict.get(): safe default (empty list)

    if not pages:
        # Either the user didn’t select any Page in consent, or they lack admin access
        return redirect("/connect-instagram?status=no_pages")

    # 3) For each Page, try BOTH possible link fields and grab the IG id/username
    ig_user_id = ig_username = None
    for page in pages:                                    # for-loop: Python built-in iterator
        page_id = page["id"]                              # dict indexing: built-in op (raises KeyError if missing)
        fields = "instagram_business_account{username,id},connected_instagram_account{username,id}"
        pr = requests.get(
            f"{GRAPH}/{page_id}",
            params={"access_token": page["access_token"], "fields": fields},
        ).json()
        if DEBUG_IG: print("IG PAGE->FIELDS:", page_id, pr)

        # Pick whichever field is present; dict.get() avoids KeyError on missing keys
        node = (pr.get("instagram_business_account")
                or pr.get("connected_instagram_account")
                or {})

        if node.get("id"):
            ig_user_id = node["id"]
            ig_username = node.get("username")
            # Sometimes username isn't inlined; fetch it directly by IG id
            if not ig_username:
                ig_info = requests.get(
                    f"{GRAPH}/{ig_user_id}",
                    params={"access_token": user_token, "fields": "username"},
                ).json()
                if DEBUG_IG: print("IG USER LOOKUP:", ig_info)
                ig_username = ig_info.get("username")
            break                                         # built-in: exit loop once found

    if not ig_user_id:
        # Page exists but no IG linked (or link not recognized by Graph)
        return redirect("/connect-instagram?status=no_connected_ig")

    # 4) Persist and sign the user in
    User = get_user_model()                                # built-in: get AUTH_USER_MODEL
    with transaction.atomic():                             # built-in: single commit/rollback
        # get_or_create(): Django built-in that does SELECT-or-INSERT atomically
        user, _ = User.objects.get_or_create(
            username=f"ig_{ig_user_id}",
            defaults={"first_name": ig_username or ""},
        )
        profile, _ = SocialProfile.objects.get_or_create(user=user)
        profile.ig_user_id = ig_user_id
        profile.ig_username = ig_username
        profile.save()                                     # built-in ORM persist

    login(request, user)                                   # built-in: attach user to session
    return redirect("/dashboard")                          # built-in: 302 to your app
