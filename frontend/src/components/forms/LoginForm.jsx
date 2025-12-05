import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import useAuthStore from '../../store/auth';
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

  const navigate = useNavigate(); // Hook to navigate to other routes
  const [formData, setFormData] = useState({ username: '', password: '' });
  const [rememberMe, setRememberMe] = useState(false);
  const [savePassword, setSavePassword] = useState(false);
  const [forgotPasswordOpened, setForgotPasswordOpened] = useState(false);
  const [version, setVersion] = useState(null);
  const [isLoading, setIsLoading] = useState(false);

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
    // Fetch version info
    API.getVersion().then((data) => {
      setVersion(data?.version);
    });
  }, []);

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
                  ⚠ Password will be stored locally without encryption. Only
                  use on trusted devices.
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
          </Stack>
        </form>

        {version && (
          <Text
            size="xs"
            color="dimmed"
            style={{
              position: 'absolute',
              bottom: 6,
              right: 30,
            }}
          >
            v{version}
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
