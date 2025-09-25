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
    if request.GET.get("error"):
        return redirect("/login?error=" + request.GET.get("error"))

    code = request.GET.get("code")
    if not code:
        return HttpResponseBadRequest("Missing code")

    redirect_uri = request.build_absolute_uri(reverse("ig-login-callback"))

    # 1) Exchange code -> user token
    token_json = requests.get(
        f"{GRAPH}/oauth/access_token",
        params={
            "client_id": APP_ID,
            "client_secret": APP_SECRET,
            "redirect_uri": redirect_uri,
            "code": code,
        },
    ).json()
    if DEBUG_IG: print("TOKEN:", token_json)
    user_token = token_json.get("access_token")
    if not user_token:
        return redirect("/login?error=token_exchange_failed")

    # 1b) DIAG: What scopes does this token really have?
    # /debug_token shows scopes the token carries
    app_token = f"{APP_ID}|{APP_SECRET}"  # app access token format
    dbg = requests.get(
        f"{GRAPH}/debug_token",
        params={"input_token": user_token, "access_token": app_token},
    ).json()
    if DEBUG_IG: print("DEBUG_TOKEN:", dbg)
    scopes = set(dbg.get("data", {}).get("scopes") or [])
    has_pages_show_list = "pages_show_list" in scopes
    has_instagram_basic = "instagram_basic" in scopes

    # 1c) DIAG: User explicitly granted/declined permissions?
    perms = requests.get(
        f"{GRAPH}/me/permissions",
        params={"access_token": user_token},
    ).json()
    if DEBUG_IG: print("ME_PERMISSIONS:", perms)

    # 2) List Pages (requires pages_show_list and the user must be Page admin)
    pages_json = requests.get(
        f"{GRAPH}/me/accounts",
        params={"access_token": user_token, "fields": "id,name,access_token,perms"},
    ).json()
    pages = pages_json.get("data", [])  # dict.get() is a Python built-in safe accessor
    if DEBUG_IG: print("ME_ACCOUNTS:", pages_json)

    if not pages:
        # Be explicit about why we think it's empty
        reason = []
        if not has_pages_show_list:
            reason.append("missing pages_show_list")
        # If you didn't tick the Page in the consent, Facebook returns [] even with scope present.
        # We can't detect that server-side except by saying "no page selected/admin".
        reason.append("no page selected or not an admin")
        reason_str = ",".join(reason)
        return redirect(f"/connect-instagram?status=no_pages&why={reason_str}")

    # 3) Resolve IG from the Page using BOTH possible fields
    ig_user_id = ig_username = None
    for page in pages:                           # for-loop: Python built-in iterator
        page_id = page["id"]
        fields = "instagram_business_account{username,id},connected_instagram_account{username,id}"
        pr = requests.get(
            f"{GRAPH}/{page_id}",
            params={"access_token": page["access_token"], "fields": fields},
        ).json()
        if DEBUG_IG: print("PAGE_FIELDS:", page_id, pr)

        node = (pr.get("instagram_business_account")
                or pr.get("connected_instagram_account")
                or {})

        if node.get("id"):
            ig_user_id = node["id"]
            ig_username = node.get("username")
            if not ig_username:
                ig_info = requests.get(
                    f"{GRAPH}/{ig_user_id}",
                    params={"access_token": user_token, "fields": "username"},
                ).json()
                if DEBUG_IG: print("IG_INFO:", ig_info)
                ig_username = ig_info.get("username")
            break

    if not ig_user_id:
        return redirect("/connect-instagram?status=no_connected_ig")

    # 4) Persist + login
    User = get_user_model()
    with transaction.atomic():                   # atomic is a Django built-in
        user, _ = User.objects.get_or_create(
            username=f"ig_{ig_user_id}",
            defaults={"first_name": ig_username or ""},
        )
        prof, _ = SocialProfile.objects.get_or_create(user=user)
        prof.ig_user_id = ig_user_id
        prof.ig_username = ig_username
        prof.save()

    login(request, user)                         # Django built-in: create session cookie
    return redirect("/dashboard")