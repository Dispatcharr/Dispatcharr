# OIDC SSO — Architecture & Design Decisions

## Overview

Dispatcharr supports Single Sign-On via OpenID Connect (OIDC), allowing users to
authenticate through any standards-compliant identity provider (Authentik, Keycloak,
Azure AD, Google, Authelia, and others).  Multiple providers can be configured and
enabled simultaneously; each appears as a button on the login page.

The implementation follows the **Authorization Code Flow** (RFC 6749 §4.1) with
optional **PKCE** (RFC 7636) and full **ID token verification** via JWKS.

---

## Authentication Flow

```
Browser (Login Page)
      │
      │  1. GET /api/accounts/oidc/providers/
      │     ← [ { slug, name, button_text, button_color }, … ]
      │
      │  2. User clicks provider button
      │     Frontend generates PKCE code_verifier + code_challenge (S256)
      │
      │  3. GET /api/accounts/oidc/authorize/<slug>/?redirect_uri=…&code_challenge=…
      │     ← { authorize_url, state, pkce_supported }
      │
      │  4. Frontend opens a popup window → navigates to authorize_url
      │
      ▼
 Popup Window
      │
      │  5. User authenticates with the identity provider
      │     IdP redirects to /oidc/callback?code=…&state=…
      │
      │  6. OidcPopupHandler reads code + state from URL
      │     POST /api/accounts/oidc/callback/
      │         { code, state, redirect_uri, code_verifier? }
      │     ← { access, refresh }  (Dispatcharr JWTs)
      │
      │  7. popup.postMessage({ type: 'oidc_result', tokens }, opener)
      │     Popup closes itself
      │
      ▼
Browser (Login Page)
      │
      │  8. Opener receives postMessage, stores tokens, completes login
      ▼
  Authenticated
```

---

## Files

| File | Purpose |
|------|---------|
| `apps/accounts/models.py` | `OIDCProvider` model; `save()` encrypts `client_secret`; `decrypted_client_secret` property |
| `apps/accounts/encryption.py` | Fernet-based field encryption helpers (`encrypt_secret`, `decrypt_secret`) |
| `apps/accounts/oidc_views.py` | All three OIDC endpoints + state/token/user helpers |
| `apps/accounts/serializers.py` | `OIDCProviderSerializer`, `OIDCProviderPublicSerializer`, `OIDCCallbackSerializer` |
| `apps/accounts/api_urls.py` | URL routing for OIDC endpoints |
| `apps/accounts/tests.py` | OIDC-focused unit tests for state, authorize, callback, and user-resolution logic |
| `apps/accounts/migrations/0006_oidcprovider.py` | Single migration: creates `OIDCProvider`, adds FK to `User`, backfills encryption |
| `frontend/src/components/forms/LoginForm.jsx` | PKCE generation, popup launch, postMessage listener |
| `frontend/src/OidcPopupHandler.jsx` | Popup page: reads callback params, calls backend, posts result to opener |
| `frontend/src/pages/OidcCallback.jsx` | Redirect-mode callback page used when popup fallback triggers full-page auth flow |
| `frontend/src/api.js` | `getOIDCProviders`, `getOIDCAuthorizeUrl`, `oidcCallback` API methods |

---

## Backend Design Decisions

### 1. Authorization Code Flow (not Implicit)

The Implicit Flow (response_type=token) is deprecated by RFC 9700 because tokens
appear in the browser URL bar and referrer headers.  Authorization Code Flow keeps
all tokens server-side and is the current best practice for web applications.

### 2. State Token Format

```
{provider_slug}:{random}:{nonce}:{unix_timestamp}:{redirect_hash}:{hmac_sig}
```

The first five components are colon-delimited and signed together with
HMAC-SHA256 keyed on `settings.SECRET_KEY`. The signature is truncated to 32 hex
characters (128 bits), meeting the NIST SP 800-107 minimum tag length recommendation.

- **provider_slug** — embedded so the callback can look up the provider without a
  database round-trip before signature verification.
- **random** — 32 cryptographically-random bytes (URL-safe base64) prevent state
  prediction.
- **nonce** — sent in the authorize request and verified against the `nonce` claim
  in the ID token, binding the token to this exact browser session (prevents token
  injection, RFC 9700 §4.6).
- **unix_timestamp** — enables TTL enforcement without a database or cache lookup;
  tokens older than `STATE_TTL = 600s` (10 minutes, per RFC 9700) are rejected
  before any external call is made.
- **redirect_hash** — SHA-256 hash of the original `redirect_uri`, binding the
  callback URI to the authorization flow so a client cannot swap it at callback time.
- **hmac_sig** — `hmac.compare_digest` prevents timing attacks; tampering with any
  field invalidates the signature.

### 3. State Replay Prevention

After the HMAC/TTL/redirect-hash checks pass, the state is marked as used in the
Django cache (`oidc_used:<sha256-of-state>`) using an atomic `cache.add()` write.
This prevents concurrent duplicate submissions from both succeeding under load.

The cache key uses `SHA-256(state)` rather than the raw state string to bound the
key length regardless of how long the state is.  The TTL on the cache entry matches
`STATE_TTL` so keys expire naturally and do not accumulate indefinitely.

### 4. PKCE (RFC 7636)

PKCE is auto-detected per provider.  The frontend always generates a
`code_verifier`/`code_challenge` pair, but the flow only activates when the
provider's discovery document lists `S256` in `code_challenge_methods_supported`.
The backend returns a `pkce_supported` boolean so the frontend knows whether to
store the verifier.

Sending `code_challenge` to a provider that does not advertise PKCE support causes
a 400 from that provider's token endpoint.  Auto-detection avoids breaking
non-PKCE providers (e.g. older Authentik configurations).

### 5. ID Token Verification

The backend verifies every ID token using the provider's published JWKS:

1. Fetches `jwks_uri` from the discovery document (cached in Redis, 1-hour TTL).
2. Matches the token's `kid` header to a key in the JWKS.
3. If no match (possible key rotation), invalidates the JWKS cache entry and
   retries once.
4. Decodes with `PyJWT`, enforcing `exp`, `aud` (must equal `client_id`), and
   `iss` (must equal discovery `issuer`).
5. Verifies `nonce` with `hmac.compare_digest` to prevent timing side-channels.

**Algorithm allowlist** — Only asymmetric algorithms are accepted
(`RS256/384/512`, `ES256/384/512`, `PS256/384/512`).  `HS*` algorithms are
excluded because they require the IdP and client to share a symmetric key, which
is not the standard for confidential clients.  `"none"` is always excluded
(JWT algorithm confusion, RFC 8725 §3.1).  If the provider advertises only unsafe
algorithms the implementation falls back to `RS256`.

### 6. Client Secret Encryption

`OIDCProvider.client_secret` is never stored in plaintext.  `save()` calls
`encrypt_secret()` from `apps/accounts/encryption.py` on every write.

The encryption scheme is **Fernet** (AES-128-CBC + HMAC-SHA256 from the
`cryptography` package).  The Fernet key is derived deterministically:

```
key = base64url( SHA-256(settings.SECRET_KEY) )
```

This requires no extra configuration or key management beyond the existing
`SECRET_KEY`, which is already a secrets-management concern for all Django
deployments.

`encrypt_secret()` is **idempotent** — values that already carry the `enc$`
prefix are returned unchanged, so calling `save()` repeatedly is safe.

`decrypt_secret()` raises `ValueError` if the value lacks the `enc$` prefix
(direct DB write that bypassed the model) or if the ciphertext cannot be
decrypted (key rotation).  Both cases are caught in `oidc_callback` and
returned as a 502 with a clear operator message.

> **Key rotation note:** Rotating `SECRET_KEY` breaks existing ciphertext.
> Re-save each `OIDCProvider` after rotation to re-encrypt with the new key.

### 7. Redirect URI Validation

The `redirect_uri` is validated before generating the authorization URL to
prevent open-redirect attacks.

- **With allowlist configured:** the `redirect_uri` host+port must appear in
  `OIDCProvider.allowed_redirect_uris` (comma-separated). Entries can be full
  URLs or host/host:port strings.
- **Without allowlist:** falls back to same-host+port enforcement — the
  `redirect_uri` host+port must equal the request host. Suitable for simple
  single-domain deployments.

### 8. User Resolution

On every successful OIDC login the callback:

1. Looks up an existing user by **username** (using the mapped claim, defaulting
   to `preferred_username`).
2. Falls back to lookup by **email** if username lookup fails (handles IdP
   username renames).
3. Auto-creates a new local user if `provider.auto_create_users = True`.
4. Assigns a `user_level` via **group mapping** (`group_to_level_mapping` JSON
   field):  the highest matching level wins (max-privilege-wins semantics).
   Supports dot-notation for nested claims (e.g. `realm_access.roles` for
   Keycloak).
5. Syncs `email`, `first_name`, `last_name`, and `user_level` from fresh claims
   on every login so profile changes in the IdP propagate automatically.

Auto-created users receive an **unusable password**, preventing password
authentication.  They must log in via OIDC.

### 9. Userinfo Endpoint Fallback

Some providers (notably Authentik and Azure AD) put only a minimal set of claims
in the ID token and return the full profile from the userinfo endpoint.  After
verifying the ID token the backend fetches userinfo and merges the two claim sets,
with **ID token claims taking precedence** for security-sensitive fields.

### 10. Discovery and JWKS Caching

Both the discovery document and JWKS are cached in the **shared Django cache**
(Redis by default) with a 1-hour TTL.  This avoids a network round-trip on every
login while still reflecting provider configuration changes within an hour.

The cache is used instead of module-level dicts to ensure all uWSGI workers share
the same data and to prevent unbounded in-memory growth.

### 11. Network Access Policy

Both `oidc_authorize` and `oidc_callback` are gated by
`network_access_allowed(request, "UI")` — the same check applied to the standard
JWT login endpoint.  Blocked requests log a `login_failed` system event.

### 12. Audit Logging

All OIDC login outcomes write a `SystemEvent` via `log_system_event` to keep the
audit trail consistent with standard password logins.

| Outcome | event_type |
|---------|-----------|
| Network policy block | `login_failed` |
| State replay / invalid / expired | `login_failed` |
| ID token verification failure | `login_failed` |
| Auto-create disabled, user not found | `login_failed` |
| Account disabled | `login_failed` |
| Successful authentication | `login_success` |

---

## Frontend Design Decisions

### Popup Architecture

The IdP login page opens in a **centered popup window** rather than a full-page
redirect.  This preserves the Dispatcharr page state (unsaved form data, scroll
position) and provides a cleaner UX — the user sees a focused login dialog.

If the browser blocks the popup (user preference or extension), the code detects
`popup.closed === true` immediately after `window.open()` and falls back to a
full-page redirect.

### postMessage Communication

Once the popup completes (success or failure) it sends a `postMessage` to the
opener:

```js
window.opener.postMessage({ type: 'oidc_result', tokens? error? }, openerOrigin)
```

The opener validates `event.origin === window.location.origin` before acting on
the message, preventing cross-origin message injection.

`openerOrigin` is written to `localStorage` by the opener before the popup is
launched so the popup knows the correct target origin even after the IdP redirect
clears the URL.

### localStorage Keys

| Key | Written by | Read by | Cleared by |
|-----|-----------|---------|-----------|
| `oidc_state` | `LoginForm` | `OidcPopupHandler`, `OidcCallback` | Handler/callback on load; cleanup interval |
| `oidc_redirect_uri` | `LoginForm` | `OidcPopupHandler`, `OidcCallback` | Handler/callback on load; cleanup interval |
| `oidc_opener_origin` | `LoginForm` | `OidcPopupHandler` | Handler on load; cleanup interval |
| `oidc_popup` | `LoginForm` | `main.jsx` | Handler on load; cleanup interval |
| `oidc_code_verifier` | `LoginForm` (only when `pkce_supported`) | `OidcPopupHandler`, `OidcCallback` | Handler/callback on load; cleanup interval |

All keys are removed immediately when the handler runs (success or failure) and
also removed by a `setInterval` safety net in `LoginForm` that fires when the
popup is closed without completing the flow.

### PKCE Key Generation

`code_verifier` is 32 random bytes from `crypto.getRandomValues`, base64url-encoded
(no padding).  `code_challenge` is `SHA-256(verifier)`, also base64url-encoded,
computed via `crypto.subtle.digest` (Web Crypto API — no library dependency).

---

## Security Properties Summary

| Threat | Mitigation |
|--------|-----------|
| CSRF on callback | HMAC-signed state token; verified before any processing |
| State replay | Cache-based single-use enforcement per state token |
| State token forgery | HMAC-SHA256 with 128-bit tag keyed on `SECRET_KEY` |
| Expired state reuse | Timestamp embedded in state; 10-minute TTL |
| Open redirect | Host+port allowlist (or same-host+port fallback); validated before authorize URL is built |
| Callback `redirect_uri` tampering | `redirect_uri` hash embedded in state and revalidated at callback |
| Token injection (session fixation) | Nonce bound to state; verified with `hmac.compare_digest` against ID token |
| JWT algorithm confusion (`none`, `HS*`) | Asymmetric-only algorithm allowlist (`SAFE_ID_TOKEN_ALGORITHMS`) |
| JWT replay | `exp`, `aud`, `iss` verified by PyJWT; nonce single-use |
| Plaintext secret in DB | Fernet encryption on every `save()`; strict `ValueError` on unencrypted read |
| Cross-origin postMessage injection | Origin validated against `window.location.origin` in message listener |
| Network-level access control | `network_access_allowed("UI")` on authorize and callback endpoints |

---

## Configuration Reference (`OIDCProvider` fields)

| Field | Description |
|-------|-------------|
| `name` | Display name shown on the login button |
| `slug` | URL-safe identifier; used in all endpoints |
| `issuer_url` | OIDC issuer URL; discovery doc fetched from `{issuer}/.well-known/openid-configuration` |
| `client_id` | OAuth2 client ID |
| `client_secret` | OAuth2 client secret — stored encrypted at rest |
| `scopes` | Space-separated scopes (default: `openid profile email`) |
| `is_enabled` | Soft on/off switch; disabled providers do not appear on login page |
| `auto_create_users` | Create a local account on first OIDC login (default: true) |
| `default_user_level` | Level assigned to auto-created users: 0 Streamer, 1 Standard, 10 Admin |
| `claim_mapping` | JSON map of OIDC claim → local field (e.g. `{"preferred_username": "username"}`) |
| `group_claim` | Claim name containing IdP groups; supports dot notation (e.g. `realm_access.roles`) |
| `group_to_level_mapping` | JSON map of group name → Dispatcharr user level (highest matching level wins) |
| `button_text` | Custom login button label |
| `button_color` | Login button background colour (hex) |
| `allowed_redirect_uris` | Comma-separated hosts/URLs permitted for `redirect_uri`; empty = same-host+port only |
