"""OIDC authentication views and helpers."""

import hashlib
import hmac
import logging
import secrets
import time
from urllib.parse import urlencode, urlparse

import jwt
import requests as http_requests
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken

from core.utils import log_system_event
from dispatcharr.utils import network_access_allowed
from .models import OIDCProvider, User
from .permissions import IsAdmin
from .serializers import (
    OIDCCallbackSerializer,
    OIDCProviderPublicSerializer,
    OIDCProviderSerializer,
)

logger = logging.getLogger(__name__)

_DISCOVERY_CACHE_PREFIX = "oidc_discovery:"
_JWKS_CACHE_PREFIX = "oidc_jwks:"

DISCOVERY_TTL = 3600
JWKS_TTL = 3600
STATE_TTL = 600  # 10 minutes

# Accept asymmetric JWT algs only.
SAFE_ID_TOKEN_ALGORITHMS = frozenset({
    "RS256", "RS384", "RS512",
    "ES256", "ES384", "ES512",
    "PS256", "PS384", "PS512",
})


def _default_port_for_scheme(scheme: str) -> int | None:
    if scheme == "https":
        return 443
    if scheme == "http":
        return 80
    return None


def _effective_http_port(scheme: str, parsed_port: int | None) -> int | None:
    return parsed_port if parsed_port is not None else _default_port_for_scheme(scheme)


def _get_discovery(provider: OIDCProvider) -> dict:
    """Fetch and cache the OIDC discovery document."""
    cache_key = f"{_DISCOVERY_CACHE_PREFIX}{provider.id}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    resp = http_requests.get(provider.discovery_url, timeout=(5, 10))
    resp.raise_for_status()
    doc = resp.json()
    cache.set(cache_key, doc, timeout=DISCOVERY_TTL)
    return doc


def _get_jwks(jwks_uri: str) -> dict:
    """Fetch and cache JWKS from the provider."""
    cache_key = f"{_JWKS_CACHE_PREFIX}{jwks_uri}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    resp = http_requests.get(jwks_uri, timeout=(5, 10))
    resp.raise_for_status()
    jwks = resp.json()
    cache.set(cache_key, jwks, timeout=JWKS_TTL)
    return jwks


def _find_signing_key(jwks_data: dict, kid: str | None):
    """Return the signing key matching the given kid, or the first key if kid is None."""
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
        cache.delete(f"{_JWKS_CACHE_PREFIX}{jwks_uri}")
        jwks_data = _get_jwks(jwks_uri)
        signing_key = _find_signing_key(jwks_data, kid)

    if signing_key is None:
        raise ValueError("Unable to find matching signing key in JWKS")

    # Keep only safe algorithms and ensure decode gets a non-empty list.
    raw_algs = discovery.get("id_token_signing_alg_values_supported", ["RS256"])
    algorithms = [alg for alg in raw_algs if alg in SAFE_ID_TOKEN_ALGORITHMS] or ["RS256"]

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
            timeout=(5, 10),
        )
        resp.raise_for_status()
        return resp.json()
    except Exception:
        logger.warning("Failed to fetch userinfo from %s", userinfo_endpoint)
        return {}


def _redirect_hash(redirect_uri: str) -> str:
    """Return a deterministic hash for redirect_uri binding."""
    return hashlib.sha256(redirect_uri.encode()).hexdigest()[:32]


def _generate_state(provider_slug: str, redirect_uri: str) -> tuple[str, str]:
    """Generate a signed state token and matching nonce."""
    random_part = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    ts = str(int(time.time()))
    redirect_hash = _redirect_hash(redirect_uri)
    secret = settings.SECRET_KEY
    payload = f"{provider_slug}:{random_part}:{nonce}:{ts}:{redirect_hash}"
    sig = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()[:32]
    return f"{payload}:{sig}", nonce


def _parse_state(state: str) -> tuple[str | None, str | None, str | None]:
    """Verify state and return (provider_slug, nonce, redirect_hash)."""
    parts = state.split(":")
    if len(parts) != 6:
        return None, None, None
    provider_slug, random_part, nonce, ts, redirect_hash, sig = parts
    secret = settings.SECRET_KEY
    payload = f"{provider_slug}:{random_part}:{nonce}:{ts}:{redirect_hash}"
    expected = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()[:32]
    if not hmac.compare_digest(sig, expected):
        return None, None, None
    try:
        issued_at = int(ts)
    except ValueError:
        return None, None, None
    age = time.time() - issued_at
    if age > STATE_TTL:
        logger.warning("OIDC state token expired (age=%ds, ttl=%ds)", int(age), STATE_TTL)
        return None, None, None
    return provider_slug, nonce, redirect_hash


def _resolve_user_level(claims: dict, provider: OIDCProvider) -> int:
    """Determine user level from group claims."""
    mapping = provider.group_to_level_mapping or {}
    if not mapping:
        return provider.default_user_level

    # Resolve nested group claims, e.g. "realm_access.roles".
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

    matched_level = None
    for group_name, level in mapping.items():
        if group_name in user_groups:
            level_int = int(level)
            if matched_level is None or level_int > matched_level:
                matched_level = level_int

    if matched_level is not None:
        logger.info("OIDC group mapping: groups=%s -> level=%d (provider: %s)", user_groups, matched_level, provider.name)
        return matched_level

    return provider.default_user_level


def _get_or_create_user(claims: dict, provider: OIDCProvider) -> User | None:
    """Find or create a local user from OIDC claims."""
    mapping = provider.claim_mapping or {}

    username_claim = mapping.get("username", "preferred_username")
    email_claim = mapping.get("email", "email")
    first_name_claim = mapping.get("first_name", "given_name")
    last_name_claim = mapping.get("last_name", "family_name")

    # Username fallback chain:
    # mapped claim -> preferred_username -> name -> email prefix -> sub
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

    # Avoid duplicate suffix when first_name already includes last_name.
    if first_name and last_name and first_name.endswith(" " + last_name):
        first_name = first_name[: -(len(last_name) + 1)]

    # Some providers send full name in "name" without split fields.
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

    try:
        user = User.objects.get(username=username)
        user_level = _resolve_user_level(claims, provider)
        return _update_user_claims(user, email, first_name, last_name, user_level, provider)
    except User.DoesNotExist:
        pass

    if email:
        try:
            user = User.objects.get(email=email)
            user_level = _resolve_user_level(claims, provider)
            return _update_user_claims(user, email, first_name, last_name, user_level, provider)
        except User.DoesNotExist:
            pass

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
    # OIDC users do not use local passwords.
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
    """Return the authorization URL for the given OIDC provider."""
    if not network_access_allowed(request, "UI"):
        client_ip = request.META.get("REMOTE_ADDR", "unknown")
        logger.info(f"OIDC authorize blocked by network policy: slug={slug} ip={client_ip}")
        return Response({"error": "Forbidden"}, status=status.HTTP_403_FORBIDDEN)

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

    # Validate redirect_uri using allowlist host+port or same-host fallback.
    allowed_uris = [
        u.strip()
        for u in (provider.allowed_redirect_uris or "").split(",")
        if u.strip()
    ]
    parsed_redirect = urlparse(redirect_uri)
    if parsed_redirect.scheme not in {"http", "https"}:
        return Response(
            {"error": "redirect_uri must use http or https"},
            status=status.HTTP_400_BAD_REQUEST,
        )
    redirect_host = (parsed_redirect.hostname or "").lower()
    if not redirect_host:
        return Response(
            {"error": "redirect_uri host not allowed"},
            status=status.HTTP_400_BAD_REQUEST,
        )
    try:
        redirect_port = _effective_http_port(parsed_redirect.scheme, parsed_redirect.port)
    except ValueError:
        return Response(
            {"error": "redirect_uri port is invalid"},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if redirect_port is None:
        return Response(
            {"error": "redirect_uri port is invalid"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if allowed_uris:
        allowed_host_ports = set()
        for allowed_entry in allowed_uris:
            normalized = allowed_entry if "://" in allowed_entry else f"//{allowed_entry}"
            parsed_allowed = urlparse(normalized)
            if parsed_allowed.scheme and parsed_allowed.scheme not in {"http", "https"}:
                continue
            host = (parsed_allowed.hostname or "").lower()
            if host:
                try:
                    if parsed_allowed.scheme:
                        allowed_port = _effective_http_port(
                            parsed_allowed.scheme,
                            parsed_allowed.port,
                        )
                    else:
                        allowed_port = parsed_allowed.port
                        if allowed_port is None:
                            # Bare host entries use the redirect scheme default port.
                            allowed_port = _default_port_for_scheme(parsed_redirect.scheme)
                except ValueError:
                    logger.warning(
                        "OIDC provider '%s' has invalid allowed_redirect_uris entry '%s'",
                        provider.slug,
                        allowed_entry,
                    )
                    continue
                if allowed_port is not None:
                    allowed_host_ports.add((host, allowed_port))
        if (redirect_host, redirect_port) not in allowed_host_ports:
            return Response(
                {"error": "redirect_uri host/port is not in the provider's configured allowlist"},
                status=status.HTTP_400_BAD_REQUEST,
            )
    else:
        # Parse host safely (IPv6 and mixed-case host headers).
        request_host = (urlparse(f"//{request.get_host()}").hostname or "").lower()
        try:
            request_raw_port = urlparse(f"//{request.get_host()}").port
        except ValueError:
            return Response(
                {"error": "request host port is invalid"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        request_port = _effective_http_port(
            "https" if request.is_secure() else "http",
            request_raw_port,
        )
        if (redirect_host, redirect_port) != (request_host, request_port):
            return Response(
                {"error": "redirect_uri host/port not allowed"},
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

    state, nonce = _generate_state(provider.slug, redirect_uri)

    params = {
        "response_type": "code",
        "client_id": provider.client_id,
        "redirect_uri": redirect_uri,
        "scope": provider.scopes,
        "state": state,
        "nonce": nonce,
    }

    # Only send PKCE params when provider discovery advertises S256.
    code_challenge = request.query_params.get("code_challenge")
    pkce_methods = discovery.get("code_challenge_methods_supported", [])
    pkce_supported = "S256" in pkce_methods
    if code_challenge and pkce_supported:
        params["code_challenge"] = code_challenge
        params["code_challenge_method"] = "S256"

    authorization_endpoint = discovery["authorization_endpoint"]
    authorize_url = f"{authorization_endpoint}?{urlencode(params)}"

    return Response({"authorize_url": authorize_url, "state": state, "pkce_supported": pkce_supported})


@api_view(["POST"])
@permission_classes([])
def oidc_callback(request):
    """Exchange an authorization code for tokens and issue a local JWT pair."""
    if not network_access_allowed(request, "UI"):
        client_ip = request.META.get("REMOTE_ADDR", "unknown")
        logger.info(f"OIDC callback blocked by network policy: ip={client_ip}")
        log_system_event(
            event_type="login_failed",
            client_ip=client_ip,
            user_agent=request.META.get("HTTP_USER_AGENT", "unknown"),
            reason="Network access denied (OIDC)",
        )
        return Response({"error": "Forbidden"}, status=status.HTTP_403_FORBIDDEN)

    serializer = OIDCCallbackSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data

    code = data["code"]
    state_param = data["state"]
    redirect_uri = data["redirect_uri"]

    provider_slug, nonce, expected_redirect_hash = _parse_state(state_param)
    if not provider_slug:
        client_ip = request.META.get("REMOTE_ADDR", "unknown")
        logger.warning(f"OIDC invalid state parameter: ip={client_ip}")
        log_system_event(
            event_type="login_failed",
            client_ip=client_ip,
            user_agent=request.META.get("HTTP_USER_AGENT", "unknown"),
            reason="OIDC invalid or expired state token",
        )
        return Response({"error": "Invalid state parameter"}, status=status.HTTP_400_BAD_REQUEST)

    if not expected_redirect_hash or not hmac.compare_digest(
        expected_redirect_hash,
        _redirect_hash(redirect_uri),
    ):
        client_ip = request.META.get("REMOTE_ADDR", "unknown")
        logger.warning(f"OIDC redirect_uri mismatch in callback: ip={client_ip}")
        log_system_event(
            event_type="login_failed",
            client_ip=client_ip,
            user_agent=request.META.get("HTTP_USER_AGENT", "unknown"),
            reason="OIDC redirect_uri mismatch",
        )
        return Response({"error": "Invalid redirect_uri for this authorization flow"}, status=status.HTTP_400_BAD_REQUEST)

    # Mark state as used before external calls to block replay.
    state_cache_key = f"oidc_used:{hashlib.sha256(state_param.encode()).hexdigest()}"
    if not cache.add(state_cache_key, 1, timeout=STATE_TTL):
        client_ip = request.META.get("REMOTE_ADDR", "unknown")
        logger.warning(f"OIDC state token replay attempt rejected: ip={client_ip}")
        log_system_event(
            event_type="login_failed",
            client_ip=client_ip,
            user_agent=request.META.get("HTTP_USER_AGENT", "unknown"),
            reason="OIDC state token replay attempt",
        )
        return Response({"error": "State token has already been used"}, status=status.HTTP_400_BAD_REQUEST)

    try:
        provider = OIDCProvider.objects.get(slug=provider_slug, is_enabled=True)
    except OIDCProvider.DoesNotExist:
        return Response({"error": "Provider not found"}, status=status.HTTP_404_NOT_FOUND)

    try:
        discovery = _get_discovery(provider)
    except Exception:
        logger.exception("Failed to fetch OIDC discovery for %s", provider.name)
        return Response(
            {"error": "Failed to contact identity provider"},
            status=status.HTTP_502_BAD_GATEWAY,
        )

    token_endpoint = discovery["token_endpoint"]
    try:
        client_secret = provider.decrypted_client_secret
    except ValueError:
        logger.exception(
            "Cannot decrypt client_secret for OIDC provider '%s' - "
            "SECRET_KEY mismatch. Re-save the provider to fix.",
            provider.name,
        )
        return Response(
            {"error": "OIDC provider configuration error - please re-save the provider credentials."},
            status=status.HTTP_502_BAD_GATEWAY,
        )
    token_payload = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": provider.client_id,
        "client_secret": client_secret,
    }
    if data.get("code_verifier"):
        token_payload["code_verifier"] = data["code_verifier"]
    try:
        token_resp = http_requests.post(
            token_endpoint,
            data=token_payload,
            timeout=(5, 15),
        )
        if not token_resp.ok:
            logger.error(
                "OIDC token exchange 400/error from %s - status=%d body=%s payload_keys=%s",
                provider.name,
                token_resp.status_code,
                token_resp.text[:500],
                list(token_payload.keys()),
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

    try:
        claims = _verify_id_token(id_token, provider, discovery, expected_nonce=nonce)
    except Exception:
        client_ip = request.META.get("REMOTE_ADDR", "unknown")
        logger.exception(f"OIDC ID token verification failed for {provider.name}: ip={client_ip}")
        log_system_event(
            event_type="login_failed",
            client_ip=client_ip,
            user_agent=request.META.get("HTTP_USER_AGENT", "unknown"),
            reason=f"OIDC ID token verification failed (provider: {provider.name})",
        )
        return Response(
            {"error": "ID token verification failed"},
            status=status.HTTP_401_UNAUTHORIZED,
        )

    # Supplement sparse ID token claims from userinfo.
    access_token = token_data.get("access_token")
    if access_token:
        userinfo = _fetch_userinfo(access_token, discovery)
        # ID token claims take precedence.
        merged = {**userinfo, **claims}
    else:
        merged = claims

    user = _get_or_create_user(merged, provider)
    if user is None:
        client_ip = request.META.get("REMOTE_ADDR", "unknown")
        log_system_event(
            event_type="login_failed",
            client_ip=client_ip,
            user_agent=request.META.get("HTTP_USER_AGENT", "unknown"),
            reason=f"OIDC auto-create disabled, user not found (provider: {provider.name})",
        )
        return Response(
            {"error": "User account not found and auto-creation is disabled"},
            status=status.HTTP_403_FORBIDDEN,
        )

    if not user.is_active:
        client_ip = request.META.get("REMOTE_ADDR", "unknown")
        logger.warning(f"OIDC login rejected - account disabled: user={user.username} ip={client_ip}")
        log_system_event(
            event_type="login_failed",
            user=user.username,
            client_ip=client_ip,
            user_agent=request.META.get("HTTP_USER_AGENT", "unknown"),
            reason="Account disabled",
        )
        return Response({"error": "User account is disabled"}, status=status.HTTP_403_FORBIDDEN)

    user.last_login = timezone.now()
    user.save(update_fields=["last_login"])

    client_ip = request.META.get("REMOTE_ADDR", "unknown")
    user_agent = request.META.get("HTTP_USER_AGENT", "unknown")

    log_system_event(
        event_type="login_success",
        user=user.username,
        client_ip=client_ip,
        user_agent=user_agent,
    )
    logger.info(f"OIDC login success: user={user.username} provider={provider.name} ip={client_ip}")

    refresh = RefreshToken.for_user(user)
    return Response(
        {
            "access": str(refresh.access_token),
            "refresh": str(refresh),
        }
    )

class OIDCProviderViewSet(viewsets.ModelViewSet):
    """Admin CRUD for OIDC providers."""

    queryset = OIDCProvider.objects.all()
    serializer_class = OIDCProviderSerializer
    permission_classes = [IsAdmin]
