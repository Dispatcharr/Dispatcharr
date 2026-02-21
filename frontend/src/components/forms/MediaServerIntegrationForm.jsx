import React, { useEffect, useRef, useState } from 'react';
import {
  Alert,
  Button,
  Flex,
  Group,
  Modal,
  MultiSelect,
  NumberInput,
  PasswordInput,
  Select,
  Stack,
  Switch,
  Text,
  TextInput,
} from '@mantine/core';
import { useForm } from '@mantine/form';
import { notifications } from '@mantine/notifications';
import { CircleAlert, ShieldCheck } from 'lucide-react';
import API from '../../api';

const PROVIDER_OPTIONS = [
  { value: 'plex', label: 'Plex' },
  { value: 'emby', label: 'Emby' },
  { value: 'jellyfin', label: 'Jellyfin' },
];

const AUTH_MODE_OPTIONS = [
  { value: 'credentials', label: 'Account Login (Username + Password)' },
  { value: 'token', label: 'API Key / Token' },
];

const SYNC_INTERVAL_UNITS = [
  { value: 'hours', label: 'Hours' },
  { value: 'days', label: 'Days' },
  { value: 'weeks', label: 'Weeks' },
];

const HOURS_PER_INTERVAL_UNIT = {
  hours: 1,
  days: 24,
  weeks: 168,
};

function decomposeSyncInterval(hours) {
  const normalized = Math.max(0, Number(hours) || 0);
  if (!normalized) {
    return { sync_interval_value: 0, sync_interval_unit: 'hours' };
  }
  if (normalized % HOURS_PER_INTERVAL_UNIT.weeks === 0) {
    return {
      sync_interval_value: normalized / HOURS_PER_INTERVAL_UNIT.weeks,
      sync_interval_unit: 'weeks',
    };
  }
  if (normalized % HOURS_PER_INTERVAL_UNIT.days === 0) {
    return {
      sync_interval_value: normalized / HOURS_PER_INTERVAL_UNIT.days,
      sync_interval_unit: 'days',
    };
  }
  return { sync_interval_value: normalized, sync_interval_unit: 'hours' };
}

function composeSyncIntervalHours(value, unit) {
  const numericValue = Number(value) || 0;
  if (numericValue <= 0) return 0;
  return numericValue * (HOURS_PER_INTERVAL_UNIT[unit] || 1);
}

const initialValues = {
  name: '',
  provider_type: 'plex',
  auth_mode: 'plex_signin',
  base_url: '',
  api_token: '',
  username: '',
  password: '',
  verify_ssl: true,
  enabled: true,
  add_to_vod: true,
  sync_interval_value: 0,
  sync_interval_unit: 'hours',
  include_libraries: [],
};

export default function MediaServerIntegrationForm({
  integration = null,
  isOpen,
  onClose,
  onSaved,
}) {
  const [submitting, setSubmitting] = useState(false);
  const [loadingLibraries, setLoadingLibraries] = useState(false);
  const [libraryOptions, setLibraryOptions] = useState([]);
  const [libraryLoadError, setLibraryLoadError] = useState('');
  const [apiError, setApiError] = useState('');
  const [plexSigningIn, setPlexSigningIn] = useState(false);
  const [plexPolling, setPlexPolling] = useState(false);
  const [plexServerOptions, setPlexServerOptions] = useState([]);
  const [plexServerMap, setPlexServerMap] = useState({});
  const [selectedPlexServer, setSelectedPlexServer] = useState('');
  const [testingConnection, setTestingConnection] = useState(false);
  const plexPollRef = useRef(null);

  const isEdit = Boolean(integration?.id);

  const form = useForm({
    mode: 'controlled',
    initialValues,
    validate: {
      name: (value) => (!value?.trim() ? 'Name is required' : null),
      provider_type: (value) =>
        !value?.trim() ? 'Provider type is required' : null,
      base_url: (value) => {
        const trimmed = (value || '').trim();
        if (!trimmed) return 'Base URL is required';
        try {
          new URL(trimmed);
          return null;
        } catch {
          return 'Base URL must be a valid URL';
        }
      },
      api_token: (value, values) => {
        const token = (value || '').trim();
        const canReuseExistingToken =
          isEdit &&
          integration?.provider_type === values.provider_type &&
          !!integration?.has_api_token;
        if (values.provider_type === 'plex' && !token) {
          if (!canReuseExistingToken) {
            return 'Sign in with Plex or provide a Plex token';
          }
        }
        if (values.provider_type !== 'plex' && values.auth_mode === 'token' && !token) {
          if (!canReuseExistingToken) {
            return 'API token is required';
          }
        }
        return null;
      },
      username: (value, values) => {
        if (
          values.provider_type !== 'plex' &&
          values.auth_mode === 'credentials' &&
          !(value || '').trim()
        ) {
          return 'Username is required';
        }
        return null;
      },
      password: (value, values) => {
        const password = (value || '').trim();
        const username = (values.username || '').trim();
        const providerChanged =
          isEdit &&
          integration?.provider_type &&
          integration.provider_type !== values.provider_type;
        if (
          values.provider_type !== 'plex' &&
          values.auth_mode === 'credentials' &&
          !isEdit &&
          !password
        ) {
          return 'Password is required';
        }
        if (
          values.provider_type !== 'plex' &&
          values.auth_mode === 'credentials' &&
          isEdit &&
          !password &&
          providerChanged &&
          username
        ) {
          return 'Password is required when switching providers with username login';
        }
        return null;
      },
    },
  });

  function stopPlexPolling() {
    if (plexPollRef.current) {
      window.clearInterval(plexPollRef.current);
      plexPollRef.current = null;
    }
    setPlexPolling(false);
  }

  function resetPlexAuthState() {
    stopPlexPolling();
    setPlexSigningIn(false);
    setPlexServerOptions([]);
    setPlexServerMap({});
    setSelectedPlexServer('');
  }

  useEffect(() => {
    return () => {
      stopPlexPolling();
    };
  }, []);

  useEffect(() => {
    if (!isOpen) return;
    if (!integration) {
      form.setValues(initialValues);
      form.resetDirty();
      form.clearErrors();
      setApiError('');
      setLibraryOptions([]);
      setLibraryLoadError('');
      resetPlexAuthState();
      return;
    }

    const providerType = integration.provider_type || 'plex';
    const authMode =
      providerType === 'plex'
        ? 'plex_signin'
        : integration.username
          ? 'credentials'
          : integration.has_api_token
            ? 'token'
            : 'credentials';

    form.setValues({
      name: integration.name || '',
      provider_type: providerType,
      auth_mode: authMode,
      base_url: integration.base_url || '',
      api_token: '',
      username: integration.username || '',
      password: '',
      verify_ssl: integration.verify_ssl ?? true,
      enabled: integration.enabled ?? true,
      add_to_vod: integration.add_to_vod ?? true,
      ...decomposeSyncInterval(integration.sync_interval),
      include_libraries: Array.isArray(integration.include_libraries)
        ? integration.include_libraries.map((entry) => String(entry))
        : [],
    });
    form.resetDirty();
    form.clearErrors();
    setApiError('');
    setLibraryLoadError('');
    resetPlexAuthState();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen, integration]);

  useEffect(() => {
    if (!isOpen || !integration?.id) return;
    const loadLibraries = async () => {
      setLoadingLibraries(true);
      setLibraryLoadError('');
      try {
        const libraries = await API.getMediaServerIntegrationLibraries(
          integration.id
        );
        const options = (Array.isArray(libraries) ? libraries : []).map(
          (library) => ({
            value: String(library.id),
            label: `${library.name} (${
              library.content_type === 'series'
                ? 'Series'
                : library.content_type === 'mixed'
                  ? 'Movies + Series'
                  : 'Movies'
            })`,
          })
        );
        setLibraryOptions(options);
      } catch (error) {
        console.error('Failed loading media server libraries', error);
        const backendMessage =
          (typeof error?.body === 'object' &&
            (error.body.error || error.body.detail)) ||
          '';
        setLibraryLoadError(
          String(backendMessage || error?.message || 'Unknown error')
        );
      } finally {
        setLoadingLibraries(false);
      }
    };
    loadLibraries();
  }, [isOpen, integration?.id]);

  const handleProviderChange = (value) => {
    const providerType = value || 'plex';
    form.setFieldValue('provider_type', providerType);
    if (providerType === 'plex') {
      form.setFieldValue('auth_mode', 'plex_signin');
      form.setFieldValue('username', '');
      form.setFieldValue('password', '');
      return;
    }

    resetPlexAuthState();
    form.setFieldValue('auth_mode', 'credentials');
    form.setFieldValue('api_token', '');
  };

  const applyPlexServerSelection = (serverId, optionsMap = plexServerMap) => {
    setSelectedPlexServer(serverId || '');
    if (!serverId) return;
    const server = optionsMap[serverId];
    if (!server) return;
    if (server.base_url) {
      form.setFieldValue('base_url', server.base_url);
    }
    if (server.access_token) {
      form.setFieldValue('api_token', server.access_token);
    }
  };

  const loadPlexServers = async (authToken, clientIdentifier) => {
    if (!authToken || !clientIdentifier) return;
    const response = await API.getPlexServers(authToken, clientIdentifier);
    const servers = Array.isArray(response?.servers) ? response.servers : [];
    const map = {};
    const options = [];

    servers.forEach((server) => {
      const id = String(server.id || '').trim();
      if (!id) return;
      map[id] = server;
      options.push({
        value: id,
        label: server.base_url
          ? `${server.name} (${server.base_url})`
          : server.name,
      });
    });

    setPlexServerMap(map);
    setPlexServerOptions(options);

    if (options.length === 1) {
      applyPlexServerSelection(options[0].value, map);
    }
  };

  const beginPlexSignIn = async () => {
    try {
      setApiError('');
      resetPlexAuthState();
      setPlexSigningIn(true);

      const start = await API.startPlexAuth();
      const pinId = String(start?.pin_id || '').trim();
      const clientIdentifier = String(start?.client_identifier || '').trim();
      const authUrl = String(start?.auth_url || '').trim();

      if (!pinId || !clientIdentifier || !authUrl) {
        throw new Error('Plex auth response missing required fields');
      }

      const popup = window.open(
        authUrl,
        'plex-auth',
        'popup=yes,width=920,height=720'
      );
      if (!popup) {
        notifications.show({
          title: 'Popup blocked',
          message: 'Allow popups and click "Sign in with Plex" again.',
          color: 'yellow',
        });
      }

      let attempts = 0;
      setPlexPolling(true);

      const poll = async () => {
        attempts += 1;
        try {
          const check = await API.checkPlexAuth(pinId, clientIdentifier);
          const token = String(check?.auth_token || '').trim();
          if (check?.claimed && token) {
            stopPlexPolling();
            form.setFieldValue('api_token', token);
            await loadPlexServers(token, clientIdentifier);
            notifications.show({
              title: 'Plex account linked',
              message: 'Select your Plex server and save.',
              color: 'green',
            });
            if (popup && !popup.closed) popup.close();
            return;
          }
        } catch (error) {
          console.error('Plex sign-in polling failed', error);
        }

        if (attempts >= 120) {
          stopPlexPolling();
          notifications.show({
            title: 'Plex sign-in expired',
            message: 'Try signing in again.',
            color: 'yellow',
          });
          if (popup && !popup.closed) popup.close();
        }
      };

      plexPollRef.current = window.setInterval(poll, 2500);
      await poll();
    } catch (error) {
      console.error('Failed to start Plex sign-in', error);
      setApiError(error?.message || 'Failed to start Plex sign-in');
    } finally {
      setPlexSigningIn(false);
    }
  };

  const handleClose = () => {
    setApiError('');
    form.clearErrors();
    resetPlexAuthState();
    onClose?.();
  };

  const onSubmit = async (values) => {
    try {
      setSubmitting(true);
      setApiError('');
      const providerChanged =
        isEdit &&
        integration?.provider_type &&
        integration.provider_type !== values.provider_type;

      const payload = {
        name: values.name.trim(),
        provider_type: values.provider_type,
        base_url: values.base_url.trim(),
        verify_ssl: values.verify_ssl,
        enabled: values.enabled,
        add_to_vod: values.add_to_vod,
        sync_interval: composeSyncIntervalHours(
          values.sync_interval_value,
          values.sync_interval_unit
        ),
        include_libraries: (values.include_libraries || []).map((entry) =>
          String(entry)
        ),
      };

      if (values.provider_type === 'plex') {
        payload.username = '';
        payload.password = '';
        const token = (values.api_token || '').trim();
        if (token) {
          payload.api_token = token;
        } else if (!isEdit || providerChanged) {
          payload.api_token = '';
        }
      } else if (values.auth_mode === 'token') {
        payload.username = '';
        payload.password = '';
        const token = (values.api_token || '').trim();
        if (token) {
          payload.api_token = token;
        } else if (!isEdit || providerChanged) {
          payload.api_token = '';
        }
      } else {
        payload.api_token = '';
        payload.username = (values.username || '').trim();
        const password = (values.password || '').trim();
        if (password) {
          payload.password = password;
        } else if (!isEdit || providerChanged) {
          payload.password = '';
        }
      }

      if (!isEdit) {
        await API.createMediaServerIntegration(payload);
      } else {
        await API.updateMediaServerIntegration(integration.id, payload);
      }

      await onSaved?.();
      handleClose();
    } catch (error) {
      console.error('Failed to save media server integration', error);
      const body = error?.body;
      if (body && typeof body === 'object') {
        const fieldErrors = {};
        Object.entries(body).forEach(([key, value]) => {
          if (key in form.values) {
            fieldErrors[key] = Array.isArray(value)
              ? value.join(', ')
              : String(value);
          }
        });
        if (Object.keys(fieldErrors).length > 0) {
          form.setErrors(fieldErrors);
        }
        if (body.detail) {
          setApiError(String(body.detail));
        } else if (!Object.keys(fieldErrors).length) {
          setApiError(JSON.stringify(body));
        }
      } else {
        setApiError(error?.message || 'Unknown error');
      }
    } finally {
      setSubmitting(false);
    }
  };

  const testConnection = async () => {
    const values = form.getValues();
    form.clearFieldError('provider_type');
    form.clearFieldError('base_url');
    form.clearFieldError('api_token');
    form.clearFieldError('username');
    form.clearFieldError('password');

    const providerError = form.validateField('provider_type');
    const baseUrlError = form.validateField('base_url');
    if (providerError?.hasError || baseUrlError?.hasError) {
      setApiError('Provider and server URL are required before testing.');
      return;
    }

    if (values.provider_type === 'plex' || values.auth_mode === 'token') {
      const apiTokenError = form.validateField('api_token');
      if (apiTokenError?.hasError) {
        setApiError(String(apiTokenError.error));
        return;
      }
    } else if (values.provider_type !== 'plex') {
      const usernameError = form.validateField('username');
      const passwordError = form.validateField('password');
      if (usernameError?.hasError || passwordError?.hasError) {
        setApiError(
          String(usernameError.error || passwordError.error || 'Missing credentials')
        );
        return;
      }
    }

    const payload = {
      integration_id: integration?.id,
      provider_type: values.provider_type,
      base_url: values.base_url?.trim() || '',
      verify_ssl: values.verify_ssl,
      include_libraries: (values.include_libraries || []).map((entry) =>
        String(entry)
      ),
    };
    const name = (values.name || '').trim();
    if (name) {
      payload.name = name;
    }

    const token = (values.api_token || '').trim();
    if (values.provider_type === 'plex' || values.auth_mode === 'token') {
      if (token) payload.api_token = token;
    } else {
      payload.username = (values.username || '').trim();
      const password = (values.password || '').trim();
      if (password) payload.password = password;
    }

    try {
      setTestingConnection(true);
      setApiError('');
      const response = await API.testMediaServerIntegrationConfig(payload);
      const libraries = Array.isArray(response?.libraries) ? response.libraries : [];
      const options = libraries.map((library) => ({
        value: String(library.id),
        label: `${library.name} (${
          library.content_type === 'series'
            ? 'Series'
            : library.content_type === 'mixed'
              ? 'Movies + Series'
              : 'Movies'
        })`,
      }));
      setLibraryOptions(options);
      setLibraryLoadError('');
      notifications.show({
        title: 'Connection successful',
        message: `Discovered ${response?.library_count || libraries.length || 0} libraries`,
        color: 'green',
      });
    } catch (error) {
      console.error('Media server connection test failed', error);
      const backendMessage =
        (typeof error?.body === 'object' &&
          (error.body.error || error.body.detail)) ||
        '';
      setApiError(
        String(
          backendMessage || error?.message || 'Connection test failed'
        )
      );
    } finally {
      setTestingConnection(false);
    }
  };

  const providerLabel =
    PROVIDER_OPTIONS.find(
      (entry) => entry.value === form.values.provider_type
    )?.label || 'Provider';

  const showTokenInput =
    form.values.provider_type === 'plex' || form.values.auth_mode === 'token';
  const showCredentialsInputs =
    form.values.provider_type !== 'plex' &&
    form.values.auth_mode === 'credentials';

  return (
    <Modal
      opened={isOpen}
      onClose={handleClose}
      size="lg"
      title={
        isEdit
          ? 'Edit Media Server Integration'
          : 'New Media Server Integration'
      }
    >
      <form onSubmit={form.onSubmit(onSubmit)}>
        <Stack gap="md">
          {apiError ? (
            <Alert
              color="red"
              icon={<CircleAlert size={16} />}
              title="Could not save integration"
            >
              {apiError}
            </Alert>
          ) : null}

          <TextInput
            label="Name"
            placeholder="Main Plex"
            {...form.getInputProps('name')}
            key={form.key('name')}
          />

          <Select
            label="Provider"
            data={PROVIDER_OPTIONS}
            value={form.values.provider_type}
            onChange={handleProviderChange}
          />

          {form.values.provider_type === 'plex' ? (
            <Text size="xs" c="dimmed">
              Uses Plex account sign-in (PIN flow), then you select a Plex server.
            </Text>
          ) : (
            <Text size="xs" c="dimmed">
              {providerLabel} integrations can use account login or an API key.
            </Text>
          )}

          {form.values.provider_type === 'plex' ? (
            <Stack gap="xs">
              <Group justify="space-between">
                <Button
                  type="button"
                  variant="light"
                  onClick={beginPlexSignIn}
                  loading={plexSigningIn || plexPolling}
                  leftSection={<ShieldCheck size={16} />}
                >
                  {form.values.api_token
                    ? 'Re-authenticate with Plex'
                    : 'Sign in with Plex'}
                </Button>
                {plexPolling ? (
                  <Text size="xs" c="dimmed">
                    Waiting for Plex authorization...
                  </Text>
                ) : null}
              </Group>

              {form.values.api_token ? (
                <Text size="xs" c="dimmed">
                  Plex token captured. You can now select a server and save.
                </Text>
              ) : null}

              {plexServerOptions.length > 0 ? (
                <Select
                  label="Plex Server"
                  placeholder="Select server"
                  searchable
                  data={plexServerOptions}
                  value={selectedPlexServer}
                  onChange={(value) => applyPlexServerSelection(value || '')}
                />
              ) : null}
            </Stack>
          ) : (
            <Select
              label={`${providerLabel} Authentication`}
              data={AUTH_MODE_OPTIONS}
              value={form.values.auth_mode}
              onChange={(value) =>
                form.setFieldValue('auth_mode', value || 'credentials')
              }
            />
          )}

          <TextInput
            label="Server URL"
            placeholder={
              form.values.provider_type === 'plex'
                ? 'http://192.168.1.10:32400'
                : 'http://192.168.1.20:8096'
            }
            {...form.getInputProps('base_url')}
            key={form.key('base_url')}
          />
          <Group justify="flex-start">
            <Button
              type="button"
              variant="light"
              onClick={testConnection}
              loading={testingConnection}
              disabled={submitting}
            >
              Test Connection
            </Button>
          </Group>

          {showTokenInput ? (
            <PasswordInput
              label={`${providerLabel} API Token`}
              placeholder={isEdit ? 'Leave blank to keep existing token' : 'Token'}
              {...form.getInputProps('api_token')}
              key={form.key('api_token')}
            />
          ) : null}

          {showCredentialsInputs ? (
            <Group grow>
              <TextInput
                label="Username"
                placeholder="Account username"
                {...form.getInputProps('username')}
                key={form.key('username')}
              />
              <PasswordInput
                label={isEdit ? 'Password (optional)' : 'Password'}
                placeholder={
                  isEdit
                    ? 'Leave blank to keep existing password'
                    : 'Account password'
                }
                {...form.getInputProps('password')}
                key={form.key('password')}
              />
            </Group>
          ) : null}

          <MultiSelect
            searchable
            clearable
            label="Include Libraries"
            placeholder={
              isEdit || libraryOptions.length > 0
                ? loadingLibraries
                  ? 'Loading libraries...'
                  : 'All media libraries'
                : 'Run test to discover libraries'
            }
            data={libraryOptions}
            disabled={loadingLibraries || (!isEdit && libraryOptions.length === 0)}
            {...form.getInputProps('include_libraries')}
            key={form.key('include_libraries')}
          />

          <Text size="xs" c="dimmed">
            Leave libraries empty to include all detected movie and series libraries.
          </Text>
          {!loadingLibraries && !libraryLoadError && (isEdit || libraryOptions.length > 0) && libraryOptions.length === 0 ? (
            <Text size="xs" c="yellow">
              No supported movie or series libraries were discovered on this server.
            </Text>
          ) : null}
          {libraryLoadError ? (
            <Text size="xs" c="yellow">
              Could not load libraries: {libraryLoadError}
            </Text>
          ) : null}

          <Group align="flex-end" grow>
            <NumberInput
              min={0}
              label="Auto Sync"
              description="Set 0 to disable scheduled sync"
              {...form.getInputProps('sync_interval_value')}
              key={form.key('sync_interval_value')}
            />
            <Select
              label="Unit"
              data={SYNC_INTERVAL_UNITS}
              value={form.values.sync_interval_unit}
              onChange={(value) =>
                form.setFieldValue('sync_interval_unit', value || 'hours')
              }
            />
          </Group>

          <Group grow>
            <Switch
              label="Verify SSL"
              {...form.getInputProps('verify_ssl', { type: 'checkbox' })}
              key={form.key('verify_ssl')}
            />
            <Switch
              label="Enabled"
              {...form.getInputProps('enabled', { type: 'checkbox' })}
              key={form.key('enabled')}
            />
            <Switch
              label="Add to VOD"
              {...form.getInputProps('add_to_vod', { type: 'checkbox' })}
              key={form.key('add_to_vod')}
            />
          </Group>

          <Flex justify="flex-end" gap="sm" mt="sm">
            <Button variant="default" onClick={handleClose}>
              Cancel
            </Button>
            <Button type="submit" loading={submitting}>
              Save
            </Button>
          </Flex>
        </Stack>
      </form>
    </Modal>
  );
}
