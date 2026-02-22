import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  Alert,
  Badge,
  Box,
  Button,
  Divider,
  Flex,
  Group,
  Loader,
  Modal,
  MultiSelect,
  NumberInput,
  Paper,
  PasswordInput,
  ScrollArea,
  Select,
  Stack,
  Switch,
  Text,
  TextInput,
  UnstyledButton,
} from '@mantine/core';
import { useForm } from '@mantine/form';
import { notifications } from '@mantine/notifications';
import {
  ArrowUp,
  ChevronRight,
  CircleAlert,
  Folder,
  FolderOpen,
  Home,
  Plus,
  Search,
  ShieldCheck,
  Trash2,
} from 'lucide-react';
import API from '../../api';

const PROVIDER_OPTIONS = [
  { value: 'plex', label: 'Plex' },
  { value: 'emby', label: 'Emby' },
  { value: 'jellyfin', label: 'Jellyfin' },
  { value: 'local', label: 'Local' },
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

const LOCAL_CONTENT_TYPE_OPTIONS = [
  { value: 'movie', label: 'Movies' },
  { value: 'series', label: 'Series' },
  { value: 'mixed', label: 'Mixed' },
];

function defaultLocalLocation() {
  return {
    path: '',
    content_type: 'movie',
    include_subdirectories: true,
    name: '',
  };
}

function buildBreadcrumbs(inputPath) {
  const normalized = (inputPath || '/').replace(/\\/g, '/');
  const hasDrivePrefix = /^[A-Za-z]:\//.test(normalized);

  if (hasDrivePrefix) {
    const drive = normalized.slice(0, 2);
    const crumbs = [{ label: drive, path: `${drive}/` }];
    const parts = normalized
      .slice(3)
      .split('/')
      .filter(Boolean);
    let current = `${drive}/`;
    parts.forEach((part) => {
      current = current.endsWith('/') ? `${current}${part}` : `${current}/${part}`;
      crumbs.push({ label: part, path: current });
    });
    return crumbs;
  }

  const parts = normalized.split('/').filter(Boolean);
  const crumbs = [{ label: '/', path: '/' }];
  let current = '';
  parts.forEach((part) => {
    current = `${current}/${part}`;
    crumbs.push({ label: part, path: current });
  });
  return crumbs;
}

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

function extractApiErrorMessage(body, fallback = '') {
  if (!body || typeof body !== 'object') {
    return fallback;
  }

  const directMessage = [body.error, body.detail].find(
    (value) => typeof value === 'string' && value.trim()
  );
  if (directMessage) {
    return directMessage.trim();
  }

  for (const value of Object.values(body)) {
    if (Array.isArray(value)) {
      const first = value.find(
        (entry) => typeof entry === 'string' && entry.trim()
      );
      if (first) {
        return first.trim();
      }
      continue;
    }

    if (typeof value === 'string' && value.trim()) {
      return value.trim();
    }

    if (value && typeof value === 'object') {
      const nested = extractApiErrorMessage(value, '');
      if (nested) {
        return nested;
      }
    }
  }

  return fallback;
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
  local_locations: [defaultLocalLocation()],
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
  const [browser, setBrowser] = useState({
    open: false,
    index: null,
    path: '',
    parent: null,
    entries: [],
    loading: false,
    error: null,
  });
  const [browserSearch, setBrowserSearch] = useState('');
  const plexPollRef = useRef(null);

  const isEdit = Boolean(integration?.id);

  const form = useForm({
    mode: 'controlled',
    initialValues,
    validate: {
      name: (value) => (!value?.trim() ? 'Name is required' : null),
      provider_type: (value) =>
        !value?.trim() ? 'Provider type is required' : null,
      base_url: (value, values) => {
        if (values.provider_type === 'local') return null;
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
          values.provider_type !== 'local' &&
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
          values.provider_type !== 'local' &&
          values.provider_type !== 'plex' &&
          values.auth_mode === 'credentials' &&
          !isEdit &&
          !password
        ) {
          return 'Password is required';
        }
        if (
          values.provider_type !== 'local' &&
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
      local_locations: (value, values) => {
        if (values.provider_type !== 'local') return null;
        const locations = Array.isArray(value) ? value : [];
        if (locations.length === 0) {
          return 'Add at least one local media location';
        }
        for (let i = 0; i < locations.length; i += 1) {
          const location = locations[i] || {};
          const path = (location.path || '').trim();
          if (!path) {
            return `Location ${i + 1} is missing a path`;
          }
          const contentType = String(location.content_type || '').trim();
          if (!['movie', 'series', 'mixed'].includes(contentType)) {
            return `Location ${i + 1} has an invalid media type`;
          }
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

  const loadDirectory = async (targetPath) => {
    const normalizedPath = targetPath ?? '';
    setBrowser((prev) => ({ ...prev, loading: true, error: null }));
    try {
      const response = await API.browseLocalMediaPath(normalizedPath);
      setBrowser((prev) => ({
        ...prev,
        path: response.path ?? normalizedPath,
        parent: response.parent || null,
        entries: Array.isArray(response.entries) ? response.entries : [],
        loading: false,
      }));
    } catch (error) {
      console.error('Failed to browse local paths', error);
      setBrowser((prev) => ({
        ...prev,
        loading: false,
        error: 'Unable to load directories. Check permissions and try again.',
      }));
    }
  };

  const openLocalBrowser = (locationIndex) => {
    const current = form.values.local_locations?.[locationIndex]?.path || '';
    setBrowserSearch('');
    setBrowser({
      open: true,
      index: locationIndex,
      path: current,
      parent: null,
      entries: [],
      loading: true,
      error: null,
    });
    void loadDirectory(current);
  };

  const closeLocalBrowser = () => {
    setBrowserSearch('');
    setBrowser({
      open: false,
      index: null,
      path: '',
      parent: null,
      entries: [],
      loading: false,
      error: null,
    });
  };

  const handleSelectDirectory = (path) => {
    void loadDirectory(path ?? '');
  };

  const handleUseDirectory = () => {
    if (browser.index == null) {
      closeLocalBrowser();
      return;
    }
    form.setFieldValue(`local_locations.${browser.index}.path`, browser.path || '');
    closeLocalBrowser();
  };

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
      closeLocalBrowser();
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
      local_locations: Array.isArray(integration.provider_config?.locations)
        ? integration.provider_config.locations.map((location) => ({
            id: location.id || '',
            path: location.path || '',
            content_type: location.content_type || 'movie',
            include_subdirectories: location.include_subdirectories ?? true,
            name: location.name || '',
          }))
        : [defaultLocalLocation()],
    });
    form.resetDirty();
    form.clearErrors();
    setApiError('');
    setLibraryLoadError('');
    resetPlexAuthState();
    closeLocalBrowser();
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
    setApiError('');

    if (providerType === 'plex') {
      form.setFieldValue('auth_mode', 'plex_signin');
      form.setFieldValue('username', '');
      form.setFieldValue('password', '');
      return;
    }

    if (providerType === 'local') {
      resetPlexAuthState();
      form.setFieldValue('auth_mode', 'credentials');
      form.setFieldValue('base_url', '');
      form.setFieldValue('api_token', '');
      form.setFieldValue('username', '');
      form.setFieldValue('password', '');
      form.setFieldValue('include_libraries', []);
      const locations = form.values.local_locations;
      if (!Array.isArray(locations) || locations.length === 0) {
        form.setFieldValue('local_locations', [defaultLocalLocation()]);
      }
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
    closeLocalBrowser();
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
      const normalizedLocalLocations = Array.isArray(values.local_locations)
        ? values.local_locations
            .map((location) => ({
              id: (location.id || '').trim(),
              path: (location.path || '').trim(),
              name: (location.name || '').trim(),
              content_type: (location.content_type || 'movie').trim(),
              include_subdirectories: location.include_subdirectories ?? true,
            }))
            .filter((location) => location.path)
        : [];

      const payload = {
        name: values.name.trim(),
        provider_type: values.provider_type,
        base_url:
          values.provider_type === 'local' ? '' : (values.base_url || '').trim(),
        verify_ssl: values.verify_ssl,
        enabled: values.enabled,
        add_to_vod: values.add_to_vod,
        sync_interval: composeSyncIntervalHours(
          values.sync_interval_value,
          values.sync_interval_unit
        ),
        include_libraries:
          values.provider_type === 'local'
            ? []
            : (values.include_libraries || []).map((entry) => String(entry)),
        provider_config:
          values.provider_type === 'local'
            ? { locations: normalizedLocalLocations }
            : {},
      };

      if (values.provider_type === 'local') {
        payload.api_token = '';
        payload.username = '';
        payload.password = '';
      } else if (values.provider_type === 'plex') {
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
        const backendMessage = extractApiErrorMessage(body, '');
        if (backendMessage) {
          setApiError(backendMessage);
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
    form.clearFieldError('local_locations');

    const providerError = form.validateField('provider_type');
    const localLocationsError = form.validateField('local_locations');
    const isLocal = values.provider_type === 'local';
    const baseUrlError = isLocal ? null : form.validateField('base_url');
    if (providerError?.hasError || baseUrlError?.hasError) {
      setApiError('Provider and server URL are required before testing.');
      return;
    }
    if (isLocal && localLocationsError?.hasError) {
      setApiError(String(localLocationsError.error));
      return;
    }

    if (!isLocal && (values.provider_type === 'plex' || values.auth_mode === 'token')) {
      const apiTokenError = form.validateField('api_token');
      if (apiTokenError?.hasError) {
        setApiError(String(apiTokenError.error));
        return;
      }
    } else if (!isLocal && values.provider_type !== 'plex') {
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
      base_url: isLocal ? '' : (values.base_url?.trim() || ''),
      verify_ssl: values.verify_ssl,
      include_libraries: isLocal
        ? []
        : (values.include_libraries || []).map((entry) => String(entry)),
    };
    if (isLocal) {
      payload.provider_config = {
        locations: (values.local_locations || [])
          .map((location) => ({
            id: (location.id || '').trim(),
            path: (location.path || '').trim(),
            name: (location.name || '').trim(),
            content_type: (location.content_type || 'movie').trim(),
            include_subdirectories: location.include_subdirectories ?? true,
          }))
          .filter((location) => location.path),
      };
    }
    const name = (values.name || '').trim();
    if (name) {
      payload.name = name;
    }

    const token = (values.api_token || '').trim();
    if (!isLocal && (values.provider_type === 'plex' || values.auth_mode === 'token')) {
      if (token) payload.api_token = token;
    } else if (!isLocal) {
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
      const backendMessage = extractApiErrorMessage(error?.body, '');
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

  const isLocalProvider = form.values.provider_type === 'local';
  const showTokenInput =
    !isLocalProvider &&
    (form.values.provider_type === 'plex' || form.values.auth_mode === 'token');
  const showCredentialsInputs =
    !isLocalProvider &&
    form.values.provider_type !== 'plex' &&
    form.values.auth_mode === 'credentials';
  const currentBrowserPath = browser.path || '/';
  const breadcrumbs = useMemo(
    () => buildBreadcrumbs(currentBrowserPath),
    [currentBrowserPath]
  );

  const filteredEntries = useMemo(() => {
    const entries = Array.isArray(browser.entries) ? browser.entries : [];
    const query = browserSearch.trim().toLowerCase();
    if (!query) return entries;
    return entries.filter((entry) => {
      const name = (entry.name || '').toLowerCase();
      const path = (entry.path || '').toLowerCase();
      return name.includes(query) || path.includes(query);
    });
  }, [browser.entries, browserSearch]);

  const addLocalLocation = () => {
    form.insertListItem('local_locations', defaultLocalLocation());
  };

  const removeLocalLocation = (index) => {
    const current = Array.isArray(form.values.local_locations)
      ? form.values.local_locations
      : [];
    if (current.length <= 1) {
      form.setFieldValue('local_locations', [defaultLocalLocation()]);
      return;
    }
    form.removeListItem('local_locations', index);
  };

  return (
    <>
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
          ) : isLocalProvider ? (
            <Stack gap={6}>
              <Text size="xs" c="dimmed">
                Local provider imports files directly from folders on this server.
              </Text>
              <Alert color="yellow" icon={<CircleAlert size={14} />}>
                Local provider requires a TMDB API key. Set it in Settings &gt; Stream Settings before saving.
              </Alert>
            </Stack>
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
          ) : !isLocalProvider ? (
            <Select
              label={`${providerLabel} Authentication`}
              data={AUTH_MODE_OPTIONS}
              value={form.values.auth_mode}
              onChange={(value) =>
                form.setFieldValue('auth_mode', value || 'credentials')
              }
            />
          ) : null}

          {!isLocalProvider ? (
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
          ) : null}

          {isLocalProvider ? (
            <Stack gap="xs">
              <Group justify="space-between" align="center">
                <Text fw={500}>Local Media Locations</Text>
                <Button
                  type="button"
                  variant="light"
                  size="xs"
                  leftSection={<Plus size={14} />}
                  onClick={addLocalLocation}
                >
                  Add Location
                </Button>
              </Group>

              {(form.values.local_locations || []).map((location, index) => (
                <Stack key={`local-location-${index}`} gap={6}>
                  <Group grow align="end">
                    <TextInput
                      label={index === 0 ? 'Path' : undefined}
                      placeholder="/mnt/media/movies"
                      value={location.path || ''}
                      onChange={(event) =>
                        form.setFieldValue(
                          `local_locations.${index}.path`,
                          event.currentTarget.value
                        )
                      }
                    />
                    <Select
                      label={index === 0 ? 'Type' : undefined}
                      data={LOCAL_CONTENT_TYPE_OPTIONS}
                      value={location.content_type || 'movie'}
                      onChange={(value) =>
                        form.setFieldValue(
                          `local_locations.${index}.content_type`,
                          value || 'movie'
                        )
                      }
                    />
                  </Group>
                  <Group justify="space-between" align="center">
                    <Button
                      type="button"
                      variant="default"
                      size="xs"
                      leftSection={<FolderOpen size={14} />}
                      onClick={() => openLocalBrowser(index)}
                    >
                      Choose Folder
                    </Button>
                    <Group gap="xs">
                      <Switch
                        label="Recursive"
                        checked={location.include_subdirectories ?? true}
                        onChange={(event) =>
                          form.setFieldValue(
                            `local_locations.${index}.include_subdirectories`,
                            event.currentTarget.checked
                          )
                        }
                      />
                      <Button
                        type="button"
                        variant="subtle"
                        color="red"
                        size="xs"
                        leftSection={<Trash2 size={14} />}
                        onClick={() => removeLocalLocation(index)}
                      >
                        Remove
                      </Button>
                    </Group>
                  </Group>
                  {index < (form.values.local_locations || []).length - 1 ? (
                    <Divider my={4} />
                  ) : null}
                </Stack>
              ))}

              {form.errors.local_locations ? (
                <Text size="xs" c="red">
                  {String(form.errors.local_locations)}
                </Text>
              ) : null}
            </Stack>
          ) : null}

          <Group justify="flex-start">
            <Button
              type="button"
              variant="light"
              onClick={testConnection}
              loading={testingConnection}
              disabled={submitting}
            >
              {isLocalProvider ? 'Test Local Paths' : 'Test Connection'}
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

          {!isLocalProvider ? (
            <>
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
              {!loadingLibraries &&
              !libraryLoadError &&
              (isEdit || libraryOptions.length > 0) &&
              libraryOptions.length === 0 ? (
                <Text size="xs" c="yellow">
                  No supported movie or series libraries were discovered on this server.
                </Text>
              ) : null}
              {libraryLoadError ? (
                <Text size="xs" c="yellow">
                  Could not load libraries: {libraryLoadError}
                </Text>
              ) : null}
            </>
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
            {!isLocalProvider ? (
              <Switch
                label="Verify SSL"
                {...form.getInputProps('verify_ssl', { type: 'checkbox' })}
                key={form.key('verify_ssl')}
              />
            ) : null}
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

      <Modal
        opened={browser.open}
        onClose={closeLocalBrowser}
        title="Select local media directory"
        size="xl"
        overlayProps={{ backgroundOpacity: 0.6, blur: 4 }}
        zIndex={410}
      >
        <Stack gap="md">
          <Paper withBorder radius="md" p="sm">
            <Group justify="space-between" align="center" wrap="nowrap">
              <ScrollArea type="auto" offsetScrollbars style={{ flex: 1 }}>
                <Group gap={6} wrap="nowrap">
                  <FolderOpen size={16} />
                  {breadcrumbs.map((crumb, index) => (
                    <Group key={`${crumb.path}-${index}`} gap={6} wrap="nowrap">
                      <Button
                        variant="subtle"
                        size="compact-xs"
                        leftSection={
                          index === 0 ? <Home size={12} /> : undefined
                        }
                        onClick={() => handleSelectDirectory(crumb.path)}
                        type="button"
                      >
                        {crumb.label}
                      </Button>
                      {index < breadcrumbs.length - 1 ? (
                        <ChevronRight size={12} color="var(--mantine-color-dimmed)" />
                      ) : null}
                    </Group>
                  ))}
                </Group>
              </ScrollArea>
              <Badge variant="light" color="gray">
                {browser.entries.length} folders
              </Badge>
            </Group>
          </Paper>

          <Group gap="sm" align="flex-end">
            <TextInput
              label="Filter folders"
              placeholder="Search current directory"
              value={browserSearch}
              onChange={(event) => setBrowserSearch(event.currentTarget.value)}
              leftSection={<Search size={14} />}
              style={{ flex: 1 }}
            />
            <Button
              size="xs"
              variant="light"
              leftSection={<ArrowUp size={14} />}
              onClick={() => handleSelectDirectory(browser.parent)}
              disabled={!browser.parent || browser.loading}
              type="button"
            >
              Up one level
            </Button>
          </Group>

          {browser.error ? (
            <Text size="sm" c="red">
              {browser.error}
            </Text>
          ) : null}

          <Paper withBorder radius="md" p={4}>
            <ScrollArea h={320} offsetScrollbars>
              {browser.loading ? (
                <Group justify="center" py="xl">
                  <Loader size="sm" />
                </Group>
              ) : filteredEntries.length === 0 ? (
                <Stack align="center" py="xl" gap={4}>
                  <Text c="dimmed" size="sm">
                    {browser.entries.length === 0
                      ? 'No subdirectories found.'
                      : 'No folders match your search.'}
                  </Text>
                </Stack>
              ) : (
                <Stack gap={4}>
                  {filteredEntries.map((entry) => (
                    <UnstyledButton
                      key={entry.path}
                      onClick={() => handleSelectDirectory(entry.path)}
                      style={{
                        width: '100%',
                        padding: '10px 12px',
                        borderRadius: 8,
                        border: '1px solid rgba(148, 163, 184, 0.18)',
                        background: 'rgba(15, 23, 42, 0.35)',
                      }}
                    >
                      <Group justify="space-between" align="center" wrap="nowrap">
                        <Group gap="sm" align="center" wrap="nowrap" style={{ minWidth: 0 }}>
                          <Folder size={16} />
                          <Box style={{ minWidth: 0 }}>
                            <Text size="sm" fw={600} lineClamp={1}>
                              {entry.name || entry.path}
                            </Text>
                            <Text size="xs" c="dimmed" lineClamp={1}>
                              {entry.path}
                            </Text>
                          </Box>
                        </Group>
                        <ChevronRight size={14} color="var(--mantine-color-dimmed)" />
                      </Group>
                    </UnstyledButton>
                  ))}
                </Stack>
              )}
            </ScrollArea>
          </Paper>

          <Group justify="space-between">
            <Button
              variant="light"
              size="xs"
              onClick={() => void loadDirectory(browser.path)}
              loading={browser.loading}
              type="button"
            >
              Refresh
            </Button>
            <Group gap="sm">
              <Button
                type="button"
                variant="subtle"
                onClick={closeLocalBrowser}
              >
                Cancel
              </Button>
              <Button type="button" onClick={handleUseDirectory}>
                Use this folder
              </Button>
            </Group>
          </Group>
        </Stack>
      </Modal>
    </>
  );
}
