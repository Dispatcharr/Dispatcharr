import React, { useEffect, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { Center, Loader, Stack, Text, Paper } from '@mantine/core';
import useAuthStore from '../store/auth';
import API from '../api';

// Handles the OIDC authorization code callback in redirect mode.
// This is the fallback path used when a popup could not be opened (e.g. blocked
// by the browser). Popup mode is handled by OidcPopupHandler in main.jsx,
// which runs before the router and never reaches this component.
const OIDCCallback = () => {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const handleOIDCTokens = useAuthStore((s) => s.handleOIDCTokens);
  const initData = useAuthStore((s) => s.initData);
  const [error, setError] = useState(null);
  const processed = useRef(false);

  useEffect(() => {
    if (processed.current) return;
    processed.current = true;

    const processCallback = async () => {
      const code = searchParams.get('code');
      const state = searchParams.get('state');
      const storedState = localStorage.getItem('oidc_state');
      const redirectUri = localStorage.getItem('oidc_redirect_uri');

      localStorage.removeItem('oidc_state');
      localStorage.removeItem('oidc_redirect_uri');
      localStorage.removeItem('oidc_popup');

      const idpError = searchParams.get('error');
      if (idpError) {
        setError(searchParams.get('error_description') || idpError);
        return;
      }
      if (!code || !state) {
        setError('Missing authorization code or state parameter.');
        return;
      }
      if (!storedState || state !== storedState) {
        setError('State mismatch \u2013 possible CSRF attack. Please try again.');
        return;
      }

      try {
        const tokens = await API.oidcCallback({ code, state, redirect_uri: redirectUri });
        if (tokens?.access) {
          await handleOIDCTokens(tokens);
          await initData();
          navigate('/channels', { replace: true });
        } else {
          setError('Failed to obtain authentication tokens.');
        }
      } catch (e) {
        setError(e?.body?.error || e?.message || 'OIDC authentication failed.');
      }
    };

    processCallback();
    // searchParams and navigate are stable across renders; omitting them from
    // the dependency array is intentional to prevent double-execution.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (error) {
    return (
      <Center style={{ height: '100vh' }}>
        <Paper p="xl" style={{ maxWidth: 420 }}>
          <Stack align="center">
            <Text size="lg" fw={600} c="red">
              Authentication Failed
            </Text>
            <Text size="sm" c="dimmed" ta="center">
              {error}
            </Text>
            <Text
              size="sm"
              c="blue"
              style={{ cursor: 'pointer' }}
              onClick={() => navigate('/login', { replace: true })}
            >
              Return to login
            </Text>
          </Stack>
        </Paper>
      </Center>
    );
  }

  return (
    <Center style={{ height: '100vh' }}>
      <Stack align="center">
        <Loader size="lg" />
        <Text size="sm" c="dimmed">
          Completing sign-in...
        </Text>
      </Stack>
    </Center>
  );
};

export default OIDCCallback;
