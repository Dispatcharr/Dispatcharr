import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import OidcPopupHandler from './OidcPopupHandler';

// Detect OIDC popup mode synchronously before any React renders.
// When the IdP redirects back to /oidc/callback inside a popup we render only
// OidcPopupHandler. This prevents the full app (WebSocket, AppShell, etc.)
// from mounting unnecessarily and avoids crashes caused by missing auth state.
const isOidcPopup =
  !!window.opener &&
  window.location.pathname === '/oidc/callback' &&
  localStorage.getItem('oidc_popup') === 'true';

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    {isOidcPopup ? <OidcPopupHandler /> : <App />}
  </React.StrictMode>
);
