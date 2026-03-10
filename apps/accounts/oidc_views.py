"""
OpenID Connect authentication views.

Flow:
1. GET  /api/accounts/oidc/providers/          → public list of enabled providers
2. GET  /api/accounts/oidc/authorize/<slug>/   → returns authorization URL
3. POST /api/accounts/oidc/callback/           → exchange code for tokens, issue JWT
"""

import hashlib
import hmac
import logging
import secrets
import time
from urllib.parse import urlencode

import jwt
import requests as http_requests
from django.conf import settings
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken

from .models import OIDCProvider, User
from .permissions import IsAdmin
from .serializers import (
    OIDCCallbackSerializer,
    OIDCProviderPublicSerializer,
    OIDCProviderSerializer,
)

logger = logging.getLogger(__name__)

# In-memory cache for OIDC discovery documents (provider_id → (doc, expiry))
_discovery_cache: dict[int, tuple[dict, float]] = {}
_jwks_cache: dict[str, tuple[dict, float]] = {}

DISCOVERY_TTL = 3600  # 1 hour
JWKS_TTL = 3600


def _get_discovery(provider: OIDCProvider) -> dict:
    """Fetch and cache the OIDC discovery document."""
    now = time.time()
    cached = _discovery_cache.get(provider.id)
    if cached and cached[1] > now:
        return cached[0]

    resp = http_requests.get(provider.discovery_url, timeout=10)
    resp.raise_for_status()
    doc = resp.json()
    _discovery_cache[provider.id] = (doc, now + DISCOVERY_TTL)
    return doc


def _get_jwks(jwks_uri: str) -> dict:
    """Fetch and cache JWKS from the provider."""
    now = time.time()
    cached = _jwks_cache.get(jwks_uri)
    if cached and cached[1] > now:
        return cached[0]

    resp = http_requests.get(jwks_uri, timeout=10)
    resp.raise_for_status()
    jwks = resp.json()
    _jwks_cache[jwks_uri] = (jwks, now + JWKS_TTL)
    return jwks


def _find_signing_key(jwks_data: dict, kid: str | None):
    """Find a matching signing key from JWKS data."""
    from jwt import PyJWK

    for key_data in jwks_data.get("keys", []):
        if kid and key_data.get("kid") != kid:
            continue
        return PyJWK(key_data).key
    return None


def _verify_id_token(id_token: str, provider: OIDCProvider, discovery: dict, expected_nonce: str | None = None) -> dict:
    """Verify and decode an OIDC ID token using the provider's JWKS."""
    jwks_uri = discovery["jwks_uri"]
    jwks_data = _get_jwks(jwks_uri)

    header = jwt.get_unverified_header(id_token)
    kid = header.get("kid")

    signing_key = _find_signing_key(jwks_data, kid)

    if signing_key is None:
        # Invalidate JWKS cache and retry once (key rotation)
        _jwks_cache.pop(jwks_uri, None)
        jwks_data = _get_jwks(jwks_uri)
        signing_key = _find_signing_key(jwks_data, kid)

    if signing_key is None:
        raise ValueError("Unable to find matching signing key in JWKS")

    algorithms = discovery.get("id_token_signing_alg_values_supported", ["RS256"])

    claims = jwt.decode(
        id_token,
        signing_key,
        algorithms=algorithms,
        audience=provider.client_id,
        issuer=discovery.get("issuer"),
        options={"verify_exp": True},
    )

    # Verify nonce if one was sent in the authorize request
    if expected_nonce:
        token_nonce = claims.get("nonce", "")
        if not hmac.compare_digest(token_nonce, expected_nonce):
            raise ValueError("Nonce mismatch in ID token")

    return claims


def _fetch_userinfo(access_token: str, discovery: dict) -> dict:
    """Fetch claims from the userinfo endpoint (fallback for sparse ID tokens)."""
    userinfo_endpoint = discovery.get("userinfo_endpoint")
    if not userinfo_endpoint:
        return {}
    try:
        resp = http_requests.get(
            userinfo_endpoint,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception:
        logger.warning("Failed to fetch userinfo from %s", userinfo_endpoint)
        return {}


def _generate_state(provider_slug: str) -> tuple[str, str]:
    """Generate a signed state parameter embedding the provider slug.

    Returns (state_string, nonce) where nonce should be sent in the
    authorize request and verified in the ID token.
    """
    random_part = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    secret = settings.SECRET_KEY
    payload = f"{provider_slug}:{random_part}:{nonce}"
    sig = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()[:16]
    return f"{payload}:{sig}", nonce


def _parse_state(state: str) -> tuple[str | None, str | None]:
    """Verify and extract (provider_slug, nonce) from a state parameter."""
    parts = state.split(":")
    if len(parts) != 4:
        return None, None
    provider_slug, random_part, nonce, sig = parts
    secret = settings.SECRET_KEY
    payload = f"{provider_slug}:{random_part}:{nonce}"
    expected = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()[:16]
    if not hmac.compare_digest(sig, expected):
        return None, None
    return provider_slug, nonce


def _resolve_user_level(claims: dict, provider: OIDCProvider) -> int:
    """Determine user level from IdP group claims.

    Walks the group_to_level_mapping and returns the highest matching level.
    Falls back to provider.default_user_level if no mapping matches.

    Supports nested claims via dot notation (e.g. "realm_access.roles").
    """
    mapping = provider.group_to_level_mapping or {}
    if not mapping:
        return provider.default_user_level

    # Resolve the group claim (supports dot notation like "realm_access.roles")
    group_claim = provider.group_claim or "groups"
    user_groups = claims
    for part in group_claim.split("."):
        if isinstance(user_groups, dict):
            user_groups = user_groups.get(part)
        else:
            user_groups = None
            break

    if not user_groups or not isinstance(user_groups, list):
        logger.debug("No groups found in claim '%s' for provider %s", group_claim, provider.name)
        return provider.default_user_level

    # Find the highest matching level
    matched_level = None
    for group_name, level in mapping.items():
        if group_name in user_groups:
            level_int = int(level)
            if matched_level is None or level_int > matched_level:
                matched_level = level_int

    if matched_level is not None:
        logger.info("OIDC group mapping: groups=%s → level=%d (provider: %s)", user_groups, matched_level, provider.name)
        return matched_level

    return provider.default_user_level


def _get_or_create_user(claims: dict, provider: OIDCProvider) -> User | None:
    """Find or create a local user from OIDC claims.

    Supports claim mappings for different providers (Authentik, Keycloak,
    Google, Azure AD, Authelia, etc.).  Falls back through several claim
    names to derive a username.
    """
    mapping = provider.claim_mapping or {}

    username_claim = mapping.get("username", "preferred_username")
    email_claim = mapping.get("email", "email")
    first_name_claim = mapping.get("first_name", "given_name")
    last_name_claim = mapping.get("last_name", "family_name")

    # Build username with broad fallback chain:
    # mapped claim → preferred_username → name → email prefix → sub
    username = (
        claims.get(username_claim)
        or claims.get("preferred_username")
        or claims.get("name")
        or (claims.get("email", "").split("@")[0] if claims.get("email") else None)
        or claims.get("sub")
    )
    email = claims.get(email_claim, "")
    first_name = claims.get(first_name_claim, "")
    last_name = claims.get(last_name_claim, "")

    # Some IdPs (e.g. Authentik) put the full name in given_name ("Ashish Raj")
    # while also sending family_name ("Raj"), causing "Ashish Raj Raj".
    # Strip the redundant suffix.
    if first_name and last_name and first_name.endswith(" " + last_name):
        first_name = first_name[: -(len(last_name) + 1)]

    # Some providers (e.g. Authentik) send full name in "name" but not split
    if not first_name and not last_name and claims.get("name"):
        parts = claims["name"].split(" ", 1)
        first_name = parts[0]
        last_name = parts[1] if len(parts) > 1 else ""

    if not username:
        logger.error(
            "OIDC claims missing username (tried %s, preferred_username, name, email, sub); available claims: %s",
            username_claim,
            list(claims.keys()),
        )
        return None

    # Try to find existing user by username
    try:
        user = User.objects.get(username=username)
        user_level = _resolve_user_level(claims, provider)
        return _update_user_claims(user, email, first_name, last_name, user_level, provider)
    except User.DoesNotExist:
        pass

    # Try by email if username not found
    if email:
        try:
            user = User.objects.get(email=email)
            user_level = _resolve_user_level(claims, provider)
            return _update_user_claims(user, email, first_name, last_name, user_level, provider)
        except User.DoesNotExist:
            pass

    # Auto-create if allowed
    if not provider.auto_create_users:
        logger.warning("OIDC auto-create disabled, user %s not found", username)
        return None

    user_level = _resolve_user_level(claims, provider)
    user = User.objects.create(
        username=username,
        email=email,
        first_name=first_name,
        last_name=last_name,
        user_level=user_level,
        oidc_provider=provider,
    )
    # Set unusable password – user authenticates via OIDC only
    user.set_unusable_password()
    user.save()
    logger.info("Auto-created OIDC user: %s (provider: %s)", username, provider.name)
    return user


def _update_user_claims(user: User, email: str, first_name: str, last_name: str, user_level: int | None = None, provider: OIDCProvider | None = None) -> User:
    """Update local user profile from fresh OIDC claims if changed."""
    changed = False
    if email and user.email != email:
        user.email = email
        changed = True
    if first_name and user.first_name != first_name:
        user.first_name = first_name
        changed = True
    if last_name and user.last_name != last_name:
        user.last_name = last_name
        changed = True
    if user_level is not None and user.user_level != user_level:
        user.user_level = user_level
        changed = True
    if provider is not None and user.oidc_provider_id != provider.pk:
        user.oidc_provider = provider
        changed = True
    if changed:
        user.save()
    return user


# ──────────────────────────────────────────────
# Public endpoints (no auth required)
# ──────────────────────────────────────────────


@api_view(["GET"])
@permission_classes([])
def oidc_providers_list(request):
    """Return enabled OIDC providers for the login page."""
    providers = OIDCProvider.objects.filter(is_enabled=True)
    serializer = OIDCProviderPublicSerializer(providers, many=True)
    return Response(serializer.data)


@api_view(["GET"])
@permission_classes([])
def oidc_authorize(request, slug):
    """Return the authorization URL for an OIDC provider."""
    try:
        provider = OIDCProvider.objects.get(slug=slug, is_enabled=True)
    except OIDCProvider.DoesNotExist:
        return Response({"error": "Provider not found"}, status=status.HTTP_404_NOT_FOUND)

    redirect_uri = request.query_params.get("redirect_uri")
    if not redirect_uri:
        return Response(
            {"error": "redirect_uri query parameter is required"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Validate redirect_uri (prevents open redirect)
    from urllib.parse import urlparse

    parsed = urlparse(redirect_uri)
    request_host = request.get_host().split(":")[0]
    allowed = {request_host}  # always allow the request's own origin
    for uri in (provider.allowed_redirect_uris or "").split(","):
        uri = uri.strip()
        if uri:
            allowed.add(urlparse(uri).hostname or uri)
    if not parsed.hostname or parsed.hostname not in allowed:
        return Response(
            {"error": "redirect_uri host not allowed"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        discovery = _get_discovery(provider)
    except Exception:
        logger.exception("Failed to fetch OIDC discovery for %s", provider.name)
        return Response(
            {"error": "Failed to contact identity provider"},
            status=status.HTTP_502_BAD_GATEWAY,
        )

    state, nonce = _generate_state(provider.slug)

    params = {
        "response_type": "code",
        "client_id": provider.client_id,
        "redirect_uri": redirect_uri,
        "scope": provider.scopes,
        "state": state,
        "nonce": nonce,
    }

    authorization_endpoint = discovery["authorization_endpoint"]
    authorize_url = f"{authorization_endpoint}?{urlencode(params)}"

    return Response({"authorize_url": authorize_url, "state": state})


@api_view(["POST"])
@permission_classes([])
def oidc_callback(request):
    """
    Exchange an authorization code for tokens and issue a local JWT.

    Expects JSON body: { code, state, redirect_uri }
    """
    serializer = OIDCCallbackSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data

    code = data["code"]
    state_param = data["state"]
    redirect_uri = data["redirect_uri"]

    # Verify and extract provider + nonce from state
    provider_slug, nonce = _parse_state(state_param)
    if not provider_slug:
        return Response({"error": "Invalid state parameter"}, status=status.HTTP_400_BAD_REQUEST)

    try:
        provider = OIDCProvider.objects.get(slug=provider_slug, is_enabled=True)
    except OIDCProvider.DoesNotExist:
        return Response({"error": "Provider not found"}, status=status.HTTP_404_NOT_FOUND)

    # Fetch discovery document
    try:
        discovery = _get_discovery(provider)
    except Exception:
        logger.exception("Failed to fetch OIDC discovery for %s", provider.name)
        return Response(
            {"error": "Failed to contact identity provider"},
            status=status.HTTP_502_BAD_GATEWAY,
        )

    # Exchange authorization code for tokens
    token_endpoint = discovery["token_endpoint"]
    try:
        token_resp = http_requests.post(
            token_endpoint,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "client_id": provider.client_id,
                "client_secret": provider.client_secret,
            },
            timeout=15,
        )
        token_resp.raise_for_status()
        token_data = token_resp.json()
    except http_requests.RequestException:
        logger.exception("OIDC token exchange failed for %s", provider.name)
        return Response(
            {"error": "Token exchange failed"},
            status=status.HTTP_502_BAD_GATEWAY,
        )

    id_token = token_data.get("id_token")
    if not id_token:
        return Response({"error": "No id_token in provider response"}, status=status.HTTP_502_BAD_GATEWAY)

    # Verify ID token (with nonce check)
    try:
        claims = _verify_id_token(id_token, provider, discovery, expected_nonce=nonce)
    except Exception:
        logger.exception("OIDC ID token verification failed for %s", provider.name)
        return Response(
            {"error": "ID token verification failed"},
            status=status.HTTP_401_UNAUTHORIZED,
        )

    # Supplement with userinfo if ID token claims are sparse
    # (some providers like Authentik/Azure AD put minimal claims in the ID token)
    access_token = token_data.get("access_token")
    if access_token:
        userinfo = _fetch_userinfo(access_token, discovery)
        # Merge – ID token claims take precedence
        merged = {**userinfo, **claims}
    else:
        merged = claims

    # Get or create local user
    user = _get_or_create_user(merged, provider)
    if user is None:
        return Response(
            {"error": "User account not found and auto-creation is disabled"},
            status=status.HTTP_403_FORBIDDEN,
        )

    if not user.is_active:
        return Response({"error": "User account is disabled"}, status=status.HTTP_403_FORBIDDEN)

    # Update last_login
    user.last_login = timezone.now()
    user.save(update_fields=["last_login"])

    # Log successful OIDC login
    from core.utils import log_system_event

    client_ip = request.META.get("REMOTE_ADDR", "unknown")
    user_agent = request.META.get("HTTP_USER_AGENT", "unknown")
    log_system_event(
        event_type="login_success",
        user=user.username,
        client_ip=client_ip,
        user_agent=user_agent,
    )
    logger.info("OIDC login success: user=%s provider=%s ip=%s", user.username, provider.name, client_ip)

    # Issue local JWT tokens
    refresh = RefreshToken.for_user(user)
    return Response(
        {
            "access": str(refresh.access_token),
            "refresh": str(refresh),
        }
    )


# ──────────────────────────────────────────────
# Admin endpoints (CRUD for OIDC providers)
# ──────────────────────────────────────────────


class OIDCProviderViewSet(viewsets.ModelViewSet):
    """Admin CRUD for OIDC providers."""

    queryset = OIDCProvider.objects.all()
    serializer_class = OIDCProviderSerializer
    permission_classes = [IsAdmin]
