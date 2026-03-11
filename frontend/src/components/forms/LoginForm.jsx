import React, { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import useAuthStore from '../../store/auth';
import useSettingsStore from '../../store/settings';
import { notifications } from '@mantine/notifications';
import API from '../../api';
import {
  Paper,
  Title,
  TextInput,
  Button,
  Center,
  Stack,
  Text,
  Image,
  Group,
  Divider,
  Modal,
  Anchor,
  Code,
  Checkbox,
} from '@mantine/core';
import logo from '../../assets/logo.png';

const LoginForm = () => {
  const login = useAuthStore((s) => s.login);
  const logout = useAuthStore((s) => s.logout);
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const initData = useAuthStore((s) => s.initData);
  const fetchVersion = useSettingsStore((s) => s.fetchVersion);
  const storedVersion = useSettingsStore((s) => s.version);

  const navigate = useNavigate(); // Hook to navigate to other routes
  const [formData, setFormData] = useState({ username: '', password: '' });
  const [rememberMe, setRememberMe] = useState(false);
  const [savePassword, setSavePassword] = useState(false);
  const [forgotPasswordOpened, setForgotPasswordOpened] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [oidcProviders, setOidcProviders] = useState([]);
  const [oidcLoading, setOidcLoading] = useState(null);
  const closedTimerRef = useRef(null);

  // Simple base64 encoding/decoding for localStorage
  // Note: This is obfuscation, not encryption. Use browser's password manager for real security.
  const encodePassword = (password) => {
    try {
      return btoa(password);
    } catch (error) {
      console.error('Encoding error:', error);
      return null;
    }
  };

  const decodePassword = (encoded) => {
    try {
      return atob(encoded);
    } catch (error) {
      console.error('Decoding error:', error);
      return '';
    }
  };

  useEffect(() => {
    fetchVersion();
  }, [fetchVersion]);

  useEffect(() => {
    return () => {
      if (closedTimerRef.current) clearInterval(closedTimerRef.current);
    };
  }, []);

  useEffect(() => {
    API.getOIDCProviders().then((providers) => {
      if (Array.isArray(providers)) setOidcProviders(providers);
    });
  }, []);

  const handleOIDCLogin = async (provider) => {
    setOidcLoading(provider.slug);
    try {
      const redirectUri = `${window.location.origin}/oidc/callback`;

      // Generate PKCE code_verifier (32 random bytes → base64url) and
      // code_challenge (SHA-256 of verifier → base64url) per RFC 7636.
      const verifierBytes = new Uint8Array(32);
      crypto.getRandomValues(verifierBytes);
      const codeVerifier = btoa(String.fromCharCode(...verifierBytes))
        .replace(/\+/g, '-')
        .replace(/\//g, '_')
        .replace(/=/g, '');
      const challengeBuffer = await crypto.subtle.digest(
        'SHA-256',
        new TextEncoder().encode(codeVerifier)
      );
      const codeChallenge = btoa(String.fromCharCode(...new Uint8Array(challengeBuffer)))
        .replace(/\+/g, '-')
        .replace(/\//g, '_')
        .replace(/=/g, '');

      const data = await API.getOIDCAuthorizeUrl(provider.slug, redirectUri, codeChallenge);
      if (data?.authorize_url && data?.state) {
        // Only persist the PKCE verifier when the backend confirmed the
        // provider supports S256 (code_challenge_methods_supported in
        // discovery). Sending a verifier to a non-PKCE provider causes a 400.
        if (data.pkce_supported) {
          localStorage.setItem('oidc_code_verifier', codeVerifier);
        }
        // Persist the state, redirect URI, and opener origin so OidcPopupHandler
        // can read them after the IdP redirects back into the popup window.
        localStorage.setItem('oidc_state', data.state);
        localStorage.setItem('oidc_redirect_uri', redirectUri);
        localStorage.setItem('oidc_opener_origin', window.location.origin);
        localStorage.setItem('oidc_popup', 'true');

        // Open a centered popup for the IdP authorization page.
        const w = 500;
        const h = 650;
        const left = window.screenX + (window.outerWidth - w) / 2;
        const top = window.screenY + (window.outerHeight - h) / 2;
        const popup = window.open(
          data.authorize_url,
          'oidc_login',
          `width=${w},height=${h},left=${left},top=${top},popup=yes`
        );

        if (!popup || popup.closed) {
          // Popup was blocked by the browser — fall back to a full-page redirect.
          localStorage.setItem('oidc_popup', 'false');
          window.location.href = data.authorize_url;
          return;
        }

        // Listen for the postMessage sent by OidcPopupHandler once it has
        // exchanged the authorization code for tokens.
        const handleMessage = async (event) => {
          // Reject messages from any origin other than our own app.
          if (event.origin !== window.location.origin) return;
          if (event.data?.type !== 'oidc_result') return;

          window.removeEventListener('message', handleMessage);
          clearInterval(closedTimerRef.current);
          closedTimerRef.current = null;
          setOidcLoading(null);

          const { tokens, error } = event.data;
          if (error) {
            notifications.show({
              title: 'OIDC Login Failed',
              message: error,
              color: 'red',
              autoClose: 8000,
            });
            return;
          }
          if (tokens?.access) {
            const handleOIDCTokens = useAuthStore.getState().handleOIDCTokens;
            await handleOIDCTokens(tokens);
            await initData();
          }
        };

        window.addEventListener('message', handleMessage);

        // Safety net: clean up if user closes the popup without completing login.
        closedTimerRef.current = setInterval(() => {
          if (popup.closed) {
            clearInterval(closedTimerRef.current);
            closedTimerRef.current = null;
            window.removeEventListener('message', handleMessage);
            // Clean up all OIDC localStorage keys set for this flow.
            localStorage.removeItem('oidc_state');
            localStorage.removeItem('oidc_redirect_uri');
            localStorage.removeItem('oidc_popup');
            localStorage.removeItem('oidc_opener_origin');
            localStorage.removeItem('oidc_code_verifier');
            setOidcLoading(null);
          }
        }, 500);
      }
    } catch (e) {
      console.error('OIDC login error:', e);
      setOidcLoading(null);
    }
  };

  useEffect(() => {
    // Load saved username if it exists
    const savedUsername = localStorage.getItem(
      'dispatcharr_remembered_username'
    );
    const savedPassword = localStorage.getItem('dispatcharr_saved_password');

    if (savedUsername) {
      setFormData((prev) => ({ ...prev, username: savedUsername }));
      setRememberMe(true);

      if (savedPassword) {
        try {
          const decrypted = decodePassword(savedPassword);
          if (decrypted) {
            setFormData((prev) => ({ ...prev, password: decrypted }));
            setSavePassword(true);
          }
        } catch {
          // If decoding fails, just skip
        }
      }
    }
  }, []);

  useEffect(() => {
    if (isAuthenticated) {
      navigate('/channels');
    }
  }, [isAuthenticated, navigate]);

  const handleInputChange = (e) => {
    setFormData({
      ...formData,
      [e.target.name]: e.target.value,
    });
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setIsLoading(true);

    try {
      await login(formData);

      // Save username if remember me is checked
      if (rememberMe) {
        localStorage.setItem(
          'dispatcharr_remembered_username',
          formData.username
        );

        // Save password if save password is checked
        if (savePassword) {
          const encoded = encodePassword(formData.password);
          if (encoded) {
            localStorage.setItem('dispatcharr_saved_password', encoded);
          }
        } else {
          localStorage.removeItem('dispatcharr_saved_password');
        }
      } else {
        localStorage.removeItem('dispatcharr_remembered_username');
        localStorage.removeItem('dispatcharr_saved_password');
      }

      await initData();
      // Navigation will happen automatically via the useEffect or route protection
    } catch (e) {
      console.log(`Failed to login: ${e}`);
      if (e?.message === 'Unauthorized') {
        notifications.show({
          title: 'Web UI Access Denied',
          message:
            'This account is a Streamer account and cannot log into the web UI. ' +
            'Your M3U and stream URLs still work. Contact an admin to upgrade your account level.',
          color: 'red',
          autoClose: 10000,
        });
      }
      await logout();
      setIsLoading(false);
    }
  };

  return (
    <Center
      style={{
        height: '100vh',
      }}
    >
      <Paper
        elevation={3}
        style={{
          padding: 30,
          width: '100%',
          maxWidth: 500,
          position: 'relative',
        }}
      >
        <Stack align="center" spacing="lg">
          <Image
            src={logo}
            alt="Dispatcharr Logo"
            width={120}
            height={120}
            fit="contain"
          />
          <Title order={2} align="center">
            Dispatcharr
          </Title>
          <Text size="sm" color="dimmed" align="center">
            Welcome back! Please log in to continue.
          </Text>
          <Divider style={{ width: '100%' }} />
        </Stack>
        <form onSubmit={handleSubmit}>
          <Stack>
            <TextInput
              label="Username"
              name="username"
              value={formData.username}
              onChange={handleInputChange}
              required
            />

            <TextInput
              label="Password"
              type="password"
              name="password"
              value={formData.password}
              onChange={handleInputChange}
              // required
            />

            <Group justify="space-between" align="center">
              <Group align="center" spacing="xs">
                <Checkbox
                  label="Remember me"
                  checked={rememberMe}
                  onChange={(e) => setRememberMe(e.currentTarget.checked)}
                  size="sm"
                />
                {rememberMe && (
                  <Checkbox
                    label="Save password"
                    checked={savePassword}
                    onChange={(e) => setSavePassword(e.currentTarget.checked)}
                    size="sm"
                  />
                )}
              </Group>
              <Anchor
                size="sm"
                component="button"
                type="button"
                onClick={(e) => {
                  e.preventDefault();
                  setForgotPasswordOpened(true);
                }}
              >
                Forgot password?
              </Anchor>
            </Group>

            <div
              style={{
                position: 'relative',
                height: '0',
                overflow: 'visible',
                marginBottom: '-4px',
              }}
            >
              {savePassword && (
                <Text
                  size="xs"
                  color="red"
                  style={{
                    marginTop: '-10px',
                    marginBottom: '0',
                    lineHeight: '1.2',
                  }}
                >
                  ⚠ Password will be stored locally without encryption. Only use
                  on trusted devices.
                </Text>
              )}
            </div>

            <Button
              type="submit"
              fullWidth
              loading={isLoading}
              disabled={isLoading}
              loaderProps={{ type: 'dots' }}
            >
              {isLoading ? 'Logging you in...' : 'Login'}
            </Button>

            {oidcProviders.length > 0 && (
              <>
                <Divider label="or sign in with" labelPosition="center" />
                {oidcProviders.map((provider) => (
                  <Button
                    key={provider.slug}
                    fullWidth
                    variant="outline"
                    loading={oidcLoading === provider.slug}
                    disabled={!!oidcLoading}
                    onClick={() => handleOIDCLogin(provider)}
                    style={{
                      borderColor: provider.button_color || '#4285F4',
                      color: provider.button_color || '#4285F4',
                    }}
                  >
                    {provider.button_text || `Sign in with ${provider.name}`}
                  </Button>
                ))}
              </>
            )}
          </Stack>
        </form>

        {storedVersion.version && (
          <Text
            size="xs"
            color="dimmed"
            style={{
              position: 'absolute',
              bottom: 6,
              right: 30,
            }}
          >
            v{storedVersion.version}
          </Text>
        )}
      </Paper>

      <Modal
        opened={forgotPasswordOpened}
        onClose={() => setForgotPasswordOpened(false)}
        title="Reset Your Password"
        centered
      >
        <Stack spacing="md">
          <Text>
            To reset your password, your administrator needs to run a Django
            management command:
          </Text>
          <div>
            <Text weight={500} size="sm" mb={8}>
              If running with Docker:
            </Text>
            <Code block>
              docker exec &lt;container_name&gt; python manage.py changepassword
              &lt;username&gt;
            </Code>
          </div>
          <div>
            <Text weight={500} size="sm" mb={8}>
              If running locally:
            </Text>
            <Code block>python manage.py changepassword &lt;username&gt;</Code>
          </div>
          <Text size="sm" color="dimmed">
            The command will prompt for a new password. Replace
            <code>&lt;container_name&gt;</code> with your Docker container name
            and <code>&lt;username&gt;</code> with the account username.
          </Text>
          <Text size="sm" color="dimmed" italic>
            Please contact your system administrator to perform a password
            reset.
          </Text>
        </Stack>
      </Modal>
    </Center>
  );
};

export default LoginForm;
