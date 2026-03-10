import { useEffect, useRef } from 'react';

/**
 * Handles the OIDC authorization code callback inside a popup window.
 *
 * Rendered instead of <App /> by main.jsx when the page is detected as an
 * OIDC popup (window.opener present + oidc_popup flag in localStorage).
 * Reads the authorization code from the URL, exchanges it for tokens via the
 * backend, then uses postMessage to send the result back to the opener before
 * closing itself.
 */
export default function OidcPopupHandler() {
  // Guard against React StrictMode's double-invocation of effects in development.
  const handled = useRef(false);

  useEffect(() => {
    if (handled.current) return;
    handled.current = true;

    const params = new URLSearchParams(window.location.search);
    const code = params.get('code');
    const state = params.get('state');
    const storedState = localStorage.getItem('oidc_state');
    const redirectUri = localStorage.getItem('oidc_redirect_uri');
    const openerOrigin = localStorage.getItem('oidc_opener_origin') || window.location.origin;

    // Clean up all OIDC keys immediately so they are not visible after the flow
    // completes, regardless of success or failure.
    localStorage.removeItem('oidc_state');
    localStorage.removeItem('oidc_redirect_uri');
    localStorage.removeItem('oidc_popup');
    localStorage.removeItem('oidc_opener_origin');

    // Send the result back to the opener via postMessage and close the popup.
    const finish = (result) => {
      if (window.opener) {
        window.opener.postMessage({ type: 'oidc_result', ...result }, openerOrigin);
      }
      window.close();
    };

    // Handle error responses sent directly by the identity provider.
    const idpError = params.get('error');
    if (idpError) return finish({ error: params.get('error_description') || idpError });
    if (!code || !state) return finish({ error: 'Missing authorization code or state.' });

    // Validate the state parameter to prevent CSRF attacks.
    if (!storedState || state !== storedState)
      return finish({ error: 'State mismatch – possible CSRF. Please try again.' });

    // In development the frontend (port 9191) and API (port 5656) run on
    // different ports, so an explicit base URL is required. In production
    // both are served from the same origin and a relative URL suffices.
    const apiBase = window.location.hostname === 'localhost' ? 'http://localhost:5656' : '';
    fetch(`${apiBase}/api/accounts/oidc/callback/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ code, state, redirect_uri: redirectUri }),
    })
      .then((res) =>
        res.json().then((data) => {
          if (res.ok && data.access) finish({ tokens: data });
          else finish({ error: data.error || data.detail || 'Authentication failed.' });
        })
      )
      .catch((e) => finish({ error: e.message || 'Network error during authentication.' }));
  }, []);

  // Renders nothing — this component exists solely for its side effect.
  return null;
}
