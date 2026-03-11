import { useEffect, useRef } from 'react';

// Handles /oidc/callback when sign-in runs in a popup.
export default function OidcPopupHandler() {
  // Guard against StrictMode double-invocation in development.
  const handled = useRef(false);

  useEffect(() => {
    if (handled.current) return;
    handled.current = true;

    const params = new URLSearchParams(window.location.search);
    const code = params.get('code');
    const state = params.get('state');
    const storedState = localStorage.getItem('oidc_state');
    const redirectUri = localStorage.getItem('oidc_redirect_uri');
    const codeVerifier = localStorage.getItem('oidc_code_verifier');
    const openerOrigin = localStorage.getItem('oidc_opener_origin') || window.location.origin;

    // Clear transient OIDC keys for this flow.
    localStorage.removeItem('oidc_state');
    localStorage.removeItem('oidc_redirect_uri');
    localStorage.removeItem('oidc_popup');
    localStorage.removeItem('oidc_opener_origin');
    localStorage.removeItem('oidc_code_verifier');

    // Post result to opener and close popup.
    const finish = (result) => {
      if (window.opener) {
        window.opener.postMessage({ type: 'oidc_result', ...result }, openerOrigin);
      }
      window.close();
    };

    // Handle identity-provider error responses.
    const idpError = params.get('error');
    if (idpError) return finish({ error: params.get('error_description') || idpError });
    if (!code || !state) return finish({ error: 'Missing authorization code or state.' });

    // Validate state to prevent CSRF.
    if (!storedState || state !== storedState)
      return finish({ error: 'State mismatch - possible CSRF. Please try again.' });

    // Match api.js behavior for dev vs production base URL.
    const apiBase = import.meta.env.DEV ? `http://${window.location.hostname}:5656` : '';

    // Include PKCE verifier when present.
    const callbackBody = { code, state, redirect_uri: redirectUri };
    if (codeVerifier) callbackBody.code_verifier = codeVerifier;

    fetch(`${apiBase}/api/accounts/oidc/callback/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(callbackBody),
    })
      .then((res) =>
        res.json().then((data) => {
          if (res.ok && data.access) finish({ tokens: data });
          else finish({ error: data.error || data.detail || 'Authentication failed.' });
        })
      )
      .catch((e) => finish({ error: e.message || 'Network error during authentication.' }));
  }, []);

  // No UI: this component only handles popup side effects.
  return null;
}
