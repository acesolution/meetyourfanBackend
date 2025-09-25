# sociallogins/views.py
import os
import requests                                      # third-party HTTP client
from urllib.parse import urlencode                   # built-in: dict -> querystring
from django.shortcuts import redirect                # built-in: HTTP 302 helper
from django.http import HttpResponseBadRequest       # built-in: quick 400 response
from django.contrib.auth import get_user_model, login
from django.urls import reverse
from django.db import transaction
from .models import SocialProfile

GRAPH = os.getenv("META_GRAPH_URL", "https://graph.facebook.com/v19.0")
APP_ID = os.environ["META_APP_ID"]
APP_SECRET = os.environ["META_APP_SECRET"]
FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN", "https://meetyourfan.io")  # <— point to Next.js
DEBUG_IG = os.getenv("IG_DEBUG", "0") == "1"             # set IG_DEBUG=1 to log responses

def _abs_redirect_uri(request):
    """reverse() + build_absolute_uri() build the absolute callback URL (both are Django built-ins)."""
    return request.build_absolute_uri(reverse("ig-login-callback"))

def _fe(path, params=None):
    """Helper: redirect to frontend (Next.js) with optional query string."""
    qs = f"?{urlencode(params)}" if params else ""
    return redirect(f"{FRONTEND_ORIGIN}{path}{qs}")

def ig_login_start(request):
    """Start Instagram Business Login (Meta OAuth)."""
    params = {
        "client_id": APP_ID,
        "redirect_uri": _abs_redirect_uri(request),
        "response_type": "code",
        "scope": "instagram_basic,pages_show_list",  # minimum to resolve Page -> IG
        "auth_type": "rerequest",                    # re-prompt if user unchecked before
        "state": "csrf_or_signed_payload",           # TODO: sign & verify in prod
    }
    return redirect(f"https://www.facebook.com/v19.0/dialog/oauth?{urlencode(params)}")

def ig_login_callback(request):
    if request.GET.get("error"):
        return _fe("/authentication/login", {"error": request.GET.get("error")})

    code = request.GET.get("code")
    if not code:
        return HttpResponseBadRequest("Missing code")

    redirect_uri = _abs_redirect_uri(request)

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
        return _fe("/authentication/login", {"error": "token_exchange_failed"})

    # 1b) Inspect scopes carried by this token
    app_token = f"{APP_ID}|{APP_SECRET}"  # App access token format
    dbg = requests.get(
        f"{GRAPH}/debug_token",
        params={"input_token": user_token, "access_token": app_token},
    ).json()
    if DEBUG_IG: print("DEBUG_TOKEN:", dbg)
    scopes = set(dbg.get("data", {}).get("scopes") or [])
    has_pages_show_list = "pages_show_list" in scopes
    has_instagram_basic = "instagram_basic" in scopes
    if DEBUG_IG: print("SCOPES:", scopes)

    # 1c) Optional: see explicit grant/decline flags
    perms = requests.get(f"{GRAPH}/me/permissions", params={"access_token": user_token}).json()
    if DEBUG_IG: print("ME_PERMISSIONS:", perms)

    # 2) List Pages (requires pages_show_list; you must be Page admin)
    pages_json = requests.get(
        f"{GRAPH}/me/accounts",
        params={"access_token": user_token, "fields": "id,name,access_token,perms"},
    ).json()
    if DEBUG_IG: print("ME_ACCOUNTS:", pages_json)
    pages = pages_json.get("data", [])

    if not pages:
        reason = []
        if not has_pages_show_list:
            reason.append("missing pages_show_list")
        reason.append("no page selected or not an admin")
        return _fe("/connect-instagram", {"status": "no_pages", "why": ",".join(reason)})

    # 3) Resolve IG by asking BOTH possible Page fields
    ig_user_id = ig_username = None
    for page in pages:
        fields = (
            "instagram_business_account{username,id},"
            "connected_instagram_account{username,id}"
        )
        pr = requests.get(
            f"{GRAPH}/{page['id']}",
            params={"access_token": page["access_token"], "fields": fields},
        ).json()
        if DEBUG_IG: print("PAGE_FIELDS:", page["id"], pr)

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
        return _fe("/connect-instagram", {"status": "no_connected_ig"})

    # 4) Persist + login
    User = get_user_model()
    with transaction.atomic():                        # writes either all or nothing (built-in)
        user, _ = User.objects.get_or_create(         # SELECT-or-INSERT atomically (built-in)
            username=f"ig_{ig_user_id}",
            defaults={"first_name": ig_username or ""},
        )
        prof, _ = SocialProfile.objects.get_or_create(user=user)
        prof.ig_user_id = ig_user_id
        prof.ig_username = ig_username
        prof.save()

    login(request, user)                               # set Django session cookie (built-in)
    return _fe("/dashboard")
