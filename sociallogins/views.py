# sociallogins/views.py
import os
import logging                                      # ← use python logging (built-in)
import requests
from urllib.parse import urlencode                  # built-in: dict -> querystring
from django.shortcuts import redirect               # built-in: HTTP 302 helper
from django.http import HttpResponseBadRequest      # built-in: quick 400 response
from django.contrib.auth import get_user_model, login
from django.urls import reverse
from django.db import transaction
from .models import SocialProfile

logger = logging.getLogger(__name__)                # ← module logger (inherits Django config)

GRAPH = os.getenv("META_GRAPH_URL", "https://graph.facebook.com/v19.0")
APP_ID = os.environ["META_APP_ID"]
APP_SECRET = os.environ["META_APP_SECRET"]
FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN", "https://meetyourfan.io")
DEBUG_IG = os.getenv("IG_DEBUG", "0") == "1"        # set IG_DEBUG=1 to include DEBUG logs
REQ_TIMEOUT = float(os.getenv("IG_HTTP_TIMEOUT", "8.0"))  # seconds

def _abs_redirect_uri(request):
    """reverse() + build_absolute_uri() build the absolute callback URL (both are Django built-ins)."""
    return request.build_absolute_uri(reverse("ig-login-callback"))

def _fe(path, params=None):
    """Helper: redirect to frontend (Next.js) with optional query string."""
    qs = f"?{urlencode(params)}" if params else ""
    return redirect(f"{FRONTEND_ORIGIN}{path}{qs}")

def _safe_tail(token: str, n: int = 8) -> str:
    """Return last n chars of a token for correlation without leaking secrets (built-in slicing)."""
    if not token:
        return ""
    return token[-n:]

def ig_login_start(request):
    """Start Instagram Business Login (Meta OAuth)."""
    params = {
        "client_id": APP_ID,
        "redirect_uri": _abs_redirect_uri(request),
        "response_type": "code",
        "scope": "instagram_basic,pages_show_list",
        "auth_type": "rerequest",                    # re-prompt if user unchecked before
        "state": "csrf_or_signed_payload",           # TODO: sign & verify in prod
    }
    url = f"https://www.facebook.com/v19.0/dialog/oauth?{urlencode(params)}"
    logger.info("IG login start → redirecting to Meta OAuth", extra={"oauth_url": "facebook.com/dialog/oauth"})
    return redirect(url)

def ig_login_callback(request):
    """Handle Meta redirect, exchange code → token, resolve IG via Page, persist user, redirect FE."""
    if request.GET.get("error"):
        err = request.GET.get("error")
        logger.warning("IG callback with error from Meta", extra={"error": err})
        return _fe("/authentication/login", {"error": err})

    code = request.GET.get("code")
    if not code:
        logger.warning("IG callback missing code")
        return HttpResponseBadRequest("Missing code")

    redirect_uri = _abs_redirect_uri(request)

    # 1) Exchange code -> user token (server-side uses APP_SECRET)
    try:
        token_json = requests.get(
            f"{GRAPH}/oauth/access_token",
            params={"client_id": APP_ID, "client_secret": APP_SECRET, "redirect_uri": redirect_uri, "code": code},
            timeout=REQ_TIMEOUT,
        ).json()
    except requests.RequestException as e:
        logger.exception("Token exchange request failed")
        return _fe("/authentication/login", {"error": "token_exchange_http_error"})

    user_token = token_json.get("access_token")
    if DEBUG_IG:
        logger.debug("TOKEN_EXCHANGE", extra={"ok": bool(user_token), "token_tail": _safe_tail(user_token)})
    if not user_token:
        logger.error("Token exchange did not return access_token", extra={"resp": token_json})
        return _fe("/authentication/login", {"error": "token_exchange_failed"})

    # 1b) Inspect scopes carried by this token (/debug_token)
    app_token = f"{APP_ID}|{APP_SECRET}"  # app access token format
    try:
        dbg = requests.get(
            f"{GRAPH}/debug_token",
            params={"input_token": user_token, "access_token": app_token},
            timeout=REQ_TIMEOUT,
        ).json()
    except requests.RequestException:
        logger.exception("debug_token call failed")
        return _fe("/authentication/login", {"error": "debug_token_failed"})

    scopes = set(dbg.get("data", {}).get("scopes") or [])
    if DEBUG_IG:
        logger.debug("DEBUG_TOKEN", extra={"scopes": sorted(scopes), "token_tail": _safe_tail(user_token)})

    # 1c) Optional: see explicit grant/decline flags
    try:
        perms = requests.get(f"{GRAPH}/me/permissions", params={"access_token": user_token}, timeout=REQ_TIMEOUT).json()
    except requests.RequestException:
        perms = {}
        logger.exception("me/permissions call failed")
    if DEBUG_IG:
        logger.debug("ME_PERMISSIONS", extra={"perms": perms})

    # 2) List Pages (requires pages_show_list; user must be Page admin)
    try:
        pages_json = requests.get(
            f"{GRAPH}/me/accounts",
            params={"access_token": user_token, "fields": "id,name,access_token,perms"},
            timeout=REQ_TIMEOUT,
        ).json()
    except requests.RequestException:
        logger.exception("me/accounts call failed")
        return _fe("/connect-instagram", {"status": "no_pages", "why": "http_error"})

    pages = pages_json.get("data", [])
    if DEBUG_IG:
        logger.debug("ME_ACCOUNTS", extra={"count": len(pages), "token_tail": _safe_tail(user_token)})

    if not pages:
        reasons = []
        if "pages_show_list" not in scopes:
            reasons.append("missing pages_show_list")
        reasons.append("no page selected or not an admin")
        why = ",".join(reasons)
        logger.info("No pages visible to token", extra={"why": why, "token_tail": _safe_tail(user_token)})
        return _fe("/connect-instagram", {"status": "no_pages", "why": why})

    # 3) Resolve IG by asking BOTH possible Page fields
    ig_user_id = ig_username = None
    for page in pages:  # for-loop: built-in iterator
        page_id = page["id"]
        fields = (
            "instagram_business_account{username,id},"
            "connected_instagram_account{username,id}"
        )
        try:
            pr = requests.get(
                f"{GRAPH}/{page_id}",
                params={"access_token": page["access_token"], "fields": fields},
                timeout=REQ_TIMEOUT,
            ).json()
        except requests.RequestException:
            logger.exception("page fields call failed", extra={"page_id": page_id})
            continue

        node = (pr.get("instagram_business_account") or pr.get("connected_instagram_account") or {})
        if DEBUG_IG:
            logger.debug("PAGE_FIELDS", extra={"page_id": page_id, "has_iba": bool(pr.get("instagram_business_account")),
                                               "has_cia": bool(pr.get("connected_instagram_account"))})

        if node.get("id"):
            ig_user_id = node["id"]
            ig_username = node.get("username")
            # sometimes username is not inlined; fetch it by IG id
            if not ig_username:
                try:
                    ig_info = requests.get(
                        f"{GRAPH}/{ig_user_id}",
                        params={"access_token": user_token, "fields": "username"},
                        timeout=REQ_TIMEOUT,
                    ).json()
                    ig_username = ig_info.get("username")
                except requests.RequestException:
                    logger.exception("ig user lookup failed", extra={"ig_user_id": ig_user_id})
            break  # built-in: exit loop once found

    if not ig_user_id:
        logger.info("Page found but no connected IG", extra={"pages": len(pages)})
        return _fe("/connect-instagram", {"status": "no_connected_ig"})

    # 4) Persist + login
    User = get_user_model()
    with transaction.atomic():  # built-in: commit/rollback as one unit
        user, _ = User.objects.get_or_create(  # built-in: SELECT-or-INSERT atomically
            username=f"ig_{ig_user_id}",
            defaults={"first_name": ig_username or ""},
        )
        prof, _ = SocialProfile.objects.get_or_create(user=user)
        prof.ig_user_id = ig_user_id
        prof.ig_username = ig_username
        prof.save()

    login(request, user)  # built-in: attach user to session
    logger.info("IG login success", extra={"user": user.pk, "ig_user_id": ig_user_id, "ig_username": ig_username})
    return _fe("/dashboard")
