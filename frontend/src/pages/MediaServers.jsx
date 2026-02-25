import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Badge,
  Box,
  Button,
  Card,
  Divider,
  Flex,
  Group,
  Loader,
  Modal,
  Select,
  Stack,
  Switch,
  Text,
  TextInput,
  Title,
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import {
  ArrowDownToLine,
  ArrowUpFromLine,
  CircleCheckBig,
  CircleDashed,
  CirclePlay,
  CircleX,
  FolderKanban,
  HardDrive,
  Pencil,
  RefreshCw,
  ScanSearch,
  Server,
  SquarePlus,
  Trash2,
} from 'lucide-react';

import API from '../api';
import useAuthStore from '../store/auth';
import { USER_LEVELS } from '../constants';
import MediaServerIntegrationForm from '../components/forms/MediaServerIntegrationForm';
import MediaServerSyncDrawer from '../components/MediaServerSyncDrawer';

const EXPORT_TARGET_OPTIONS = [{ value: 'jellyfin_emby', label: 'Jellyfin / Emby' }];

const DEFAULT_EXPORT_PROFILE = {
  id: '',
  integration_name: 'Dispatcharr Output',
  target_provider: 'jellyfin_emby',
  export_mode: 'strm_nfo',
  export_enabled: true,
  strm_output_path: '/data/media/strm',
  strm_include_nfo: true,
  strm_last_built_at: '',
  strm_last_build_summary: null,
  updated_at: '',
};

const LEGACY_OUTPUT_ID = '__legacy-output__';

const OUTPUT_SETTINGS_LEGACY_KEYS_TO_CLEAR = [
  'scan_control_enabled',
  'scan_control_integration_id',
  'scan_control_schedule_time',
  'scan_control_library_ids',
  'scan_control_timeout_seconds',
  'scan_control_wait_for_idle_seconds',
  'scan_last_run_at',
  'scan_last_status',
  'scan_last_message',
  'scan_last_summary',
  'scan_schedule_time',
  'scan_target_server_url',
  'scan_target_server_token',
  'scan_target_server_verify_ssl',
  'target_base_url',
  'target_api_token',
  'target_verify_ssl',
  'strm_client_output_path',
];

function statusColor(status) {
  switch (status) {
    case 'success':
      return 'green';
    case 'running':
      return 'blue';
    case 'error':
      return 'red';
    default:
      return 'gray';
  }
}

function statusIcon(status) {
  switch (status) {
    case 'success':
      return <CircleCheckBig size={14} />;
    case 'running':
      return <CirclePlay size={14} />;
    case 'error':
      return <CircleX size={14} />;
    default:
      return <CircleDashed size={14} />;
  }
}

function providerLabel(provider) {
  const normalized = String(provider || '').toLowerCase();
  if (normalized === 'plex') return 'Plex';
  if (normalized === 'jellyfin_emby') return 'Jellyfin/Emby';
  if (normalized === 'emby') return 'Emby';
  if (normalized === 'jellyfin') return 'Jellyfin';
  if (normalized === 'local') return 'Local';
  return provider || 'Unknown';
}

function ProviderBadge({ provider }) {
  return (
    <Badge variant="light" color="indigo">
      {providerLabel(provider)}
    </Badge>
  );
}

function formatSyncInterval(syncIntervalHours) {
  const hours = Number(syncIntervalHours) || 0;
  if (hours <= 0) return 'Disabled';
  if (hours % 168 === 0) {
    const weeks = hours / 168;
    return `${weeks} week${weeks === 1 ? '' : 's'}`;
  }
  if (hours % 24 === 0) {
    const days = hours / 24;
    return `${days} day${days === 1 ? '' : 's'}`;
  }
  return `${hours} hour${hours === 1 ? '' : 's'}`;
}

function parseBoolean(value, fallback = false) {
  if (typeof value === 'boolean') return value;
  if (typeof value === 'number') return value !== 0;
  if (typeof value === 'string') {
    const normalized = value.trim().toLowerCase();
    if (['1', 'true', 'yes', 'on'].includes(normalized)) return true;
    if (['0', 'false', 'no', 'off', ''].includes(normalized)) return false;
  }
  return fallback;
}

function parseCount(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric) || numeric < 0) return 0;
  return Math.trunc(numeric);
}

function normalizeSettingsValue(rawValue) {
  if (rawValue && typeof rawValue === 'object' && !Array.isArray(rawValue)) {
    return rawValue;
  }
  if (typeof rawValue === 'string') {
    try {
      const parsed = JSON.parse(rawValue);
      if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
        return parsed;
      }
    } catch (error) {
      void error;
      return {};
    }
  }
  return {};
}

function normalizeExportTarget(value) {
  const normalized = String(value || '').trim().toLowerCase();
  if (normalized === 'emby' || normalized === 'jellyfin' || normalized === 'jellyfin_emby') {
    return 'jellyfin_emby';
  }
  return DEFAULT_EXPORT_PROFILE.target_provider;
}

function deriveExportMode() {
  return 'strm_nfo';
}

function createExportProfileId() {
  if (
    typeof crypto !== 'undefined' &&
    crypto &&
    typeof crypto.randomUUID === 'function'
  ) {
    return crypto.randomUUID();
  }
  return `output-${Date.now().toString(36)}-${Math.random()
    .toString(36)
    .slice(2, 10)}`;
}

function buildExportProfile(rawSettings = {}) {
  const normalized = normalizeSettingsValue(rawSettings);
  const targetProvider = normalizeExportTarget(normalized.target_provider);
  const profileId =
    String(normalized.id || normalized.integration_id || '').trim() ||
    createExportProfileId();

  return {
    id: profileId,
    integration_name:
      String(normalized.integration_name || '').trim() ||
      DEFAULT_EXPORT_PROFILE.integration_name,
    target_provider: targetProvider,
    export_mode: deriveExportMode(),
    export_enabled: parseBoolean(normalized.export_enabled, true),
    strm_output_path:
      String(normalized.strm_output_path || '').trim() ||
      DEFAULT_EXPORT_PROFILE.strm_output_path,
    strm_include_nfo: parseBoolean(
      normalized.strm_include_nfo,
      DEFAULT_EXPORT_PROFILE.strm_include_nfo
    ),
    strm_last_built_at: String(normalized.strm_last_built_at || '').trim(),
    strm_last_build_summary:
      normalized.strm_last_build_summary &&
      typeof normalized.strm_last_build_summary === 'object'
        ? normalized.strm_last_build_summary
        : null,
    updated_at: String(normalized.updated_at || '').trim(),
  };
}

function hasLegacyOutputConfig(rawSettings) {
  const normalized = normalizeSettingsValue(rawSettings);
  return Boolean(
    parseBoolean(normalized.export_enabled, false) ||
      String(normalized.updated_at || '').trim() ||
      String(normalized.strm_last_built_at || '').trim() ||
      String(normalized.strm_output_path || '').trim() ||
      String(normalized.integration_name || '').trim()
  );
}

function buildExportProfiles(rawSettings) {
  const normalized = normalizeSettingsValue(rawSettings);
  const rawProfiles = Array.isArray(normalized.output_integrations)
    ? normalized.output_integrations
    : [];

  if (rawProfiles.length > 0) {
    const usedIds = new Set();
    return rawProfiles
      .filter((profile) => profile && typeof profile === 'object')
      .map((profile) => buildExportProfile(profile))
      .filter((profile) => {
        const profileId = String(profile.id || '').trim();
        if (!profileId || usedIds.has(profileId)) {
          return false;
        }
        usedIds.add(profileId);
        return true;
      });
  }

  if (!hasLegacyOutputConfig(normalized)) {
    return [];
  }

  return [
    buildExportProfile({
      ...normalized,
      id:
        String(normalized.id || normalized.integration_id || '').trim() ||
        LEGACY_OUTPUT_ID,
    }),
  ];
}

function buildLegacyOutputFields(profile) {
  if (!profile || typeof profile !== 'object') {
    return {
      integration_name: '',
      target_provider: '',
      export_mode: '',
      export_enabled: false,
      target_base_url: '',
      target_api_token: '',
      target_verify_ssl: true,
      strm_output_path: DEFAULT_EXPORT_PROFILE.strm_output_path,
      strm_include_nfo: DEFAULT_EXPORT_PROFILE.strm_include_nfo,
      strm_last_built_at: '',
      strm_last_build_summary: null,
      updated_at: '',
    };
  }

  return {
    integration_name:
      String(profile.integration_name || '').trim() ||
      DEFAULT_EXPORT_PROFILE.integration_name,
    target_provider: normalizeExportTarget(profile.target_provider),
    export_mode: deriveExportMode(),
    export_enabled: parseBoolean(profile.export_enabled, true),
    target_base_url: '',
    target_api_token: '',
    target_verify_ssl: true,
    strm_output_path:
      String(profile.strm_output_path || '').trim() ||
      DEFAULT_EXPORT_PROFILE.strm_output_path,
    strm_include_nfo: parseBoolean(profile.strm_include_nfo, true),
    strm_last_built_at: String(profile.strm_last_built_at || '').trim(),
    strm_last_build_summary:
      profile.strm_last_build_summary &&
      typeof profile.strm_last_build_summary === 'object'
        ? profile.strm_last_build_summary
        : null,
    updated_at: String(profile.updated_at || '').trim() || new Date().toISOString(),
  };
}

function sanitizeOutputSettings(value) {
  const output = { ...value };
  OUTPUT_SETTINGS_LEGACY_KEYS_TO_CLEAR.forEach((key) => {
    if (Object.prototype.hasOwnProperty.call(output, key)) {
      delete output[key];
    }
  });
  return output;
}

export default function MediaServersPage() {
  const authUser = useAuthStore((s) => s.user);
  const isAdmin = authUser?.user_level === USER_LEVELS.ADMIN;

  const [integrations, setIntegrations] = useState([]);
  const [loading, setLoading] = useState(false);
  const [formOpen, setFormOpen] = useState(false);
  const [activeIntegration, setActiveIntegration] = useState(null);
  const [busyById, setBusyById] = useState({});
  const [scanDrawerOpen, setScanDrawerOpen] = useState(false);
  const [scanIntegrationId, setScanIntegrationId] = useState(null);

  const [integrationTypeOpen, setIntegrationTypeOpen] = useState(false);
  const [exportSetupOpen, setExportSetupOpen] = useState(false);

  const [exportStateLoading, setExportStateLoading] = useState(false);
  const [savingExportProfile, setSavingExportProfile] = useState(false);
  const [deletingExportProfileId, setDeletingExportProfileId] = useState('');
  const [syncingExportId, setSyncingExportId] = useState('');
  const [outputSetting, setOutputSetting] = useState(null);
  const [exportProfiles, setExportProfiles] = useState([]);
  const [activeExportId, setActiveExportId] = useState('');
  const [exportProfile, setExportProfile] = useState(
    buildExportProfile(DEFAULT_EXPORT_PROFILE)
  );

  const [strmBuildLoading, setStrmBuildLoading] = useState(false);
  const [strmBuildError, setStrmBuildError] = useState('');
  const [strmBuildResult, setStrmBuildResult] = useState(null);

  const setBusy = (id, value) => {
    setBusyById((prev) => ({ ...prev, [id]: value }));
  };

  const fetchIntegrations = useCallback(async () => {
    setLoading(true);
    try {
      const response = await API.getMediaServerIntegrations();
      setIntegrations(Array.isArray(response) ? response : response?.results || []);
    } finally {
      setLoading(false);
    }
  }, []);

  const fetchExportIntegrationState = useCallback(async () => {
    setExportStateLoading(true);
    try {
      const outputState = await API.getOutputIntegrationState();
      const existingSetting =
        outputState && typeof outputState.setting === 'object'
          ? outputState.setting
          : null;
      setOutputSetting(existingSetting);

      const rawValue = normalizeSettingsValue(outputState?.value);
      const nextProfiles = buildExportProfiles(rawValue);
      setExportProfiles(nextProfiles);

      if (!exportSetupOpen) {
        if (nextProfiles.length > 0) {
          setActiveExportId(nextProfiles[0].id);
          setExportProfile(nextProfiles[0]);
        } else {
          const blankProfile = buildExportProfile({
            ...DEFAULT_EXPORT_PROFILE,
            id: createExportProfileId(),
            export_enabled: true,
          });
          setActiveExportId(blankProfile.id);
          setExportProfile(blankProfile);
        }
      }
    } catch (error) {
      console.error('Failed to load output integration state:', error);
    } finally {
      setExportStateLoading(false);
    }
  }, [exportSetupOpen]);

  useEffect(() => {
    fetchIntegrations();
    fetchExportIntegrationState();
  }, [fetchIntegrations, fetchExportIntegrationState]);

  const dockerMountSnippet = useMemo(() => {
    const outputRoot =
      String(exportProfile.strm_output_path || '').trim() ||
      DEFAULT_EXPORT_PROFILE.strm_output_path;
    const moviesPath = `${outputRoot}/Movies`;
    const showsPath = `${outputRoot}/TV Shows`;
    return `- "${moviesPath}:${moviesPath}:ro"\n- "${showsPath}:${showsPath}:ro"`;
  }, [exportProfile.strm_output_path]);

  const openCreate = () => {
    setIntegrationTypeOpen(true);
  };

  const closeIntegrationType = () => {
    setIntegrationTypeOpen(false);
  };

  const startImportIntegration = () => {
    setIntegrationTypeOpen(false);
    setActiveIntegration(null);
    setFormOpen(true);
  };

  const openExportSetup = useCallback((profile = null) => {
    setStrmBuildError('');
    setStrmBuildResult(null);
    const nextProfile = buildExportProfile(
      profile && typeof profile === 'object'
        ? {
            ...profile,
            id: String(profile.id || '').trim() || createExportProfileId(),
            export_enabled: true,
          }
        : {
            ...DEFAULT_EXPORT_PROFILE,
            id: createExportProfileId(),
            export_enabled: true,
          }
    );
    setActiveExportId(nextProfile.id);
    setExportProfile(nextProfile);
    setIntegrationTypeOpen(false);
    setExportSetupOpen(true);
  }, []);

  const closeExportSetup = () => {
    setExportSetupOpen(false);
  };

  const openEdit = (integration) => {
    setActiveIntegration(integration);
    setFormOpen(true);
  };

  const closeForm = () => {
    setFormOpen(false);
    setActiveIntegration(null);
  };

  const onSaved = async () => {
    await fetchIntegrations();
  };

  const toggleEnabled = async (integration) => {
    setBusy(integration.id, true);
    try {
      await API.updateMediaServerIntegration(integration.id, {
        enabled: !integration.enabled,
      });
      await fetchIntegrations();
    } finally {
      setBusy(integration.id, false);
    }
  };

  const runSync = async (integration, options = {}) => {
    const { suppressRefresh = false } = options;
    setBusy(integration.id, true);
    try {
      const response = await API.syncMediaServerIntegration(integration.id);
      notifications.show({
        title: 'Sync started',
        message: response?.message || `Sync started for ${integration.name}`,
        color: 'blue',
      });
      if (!suppressRefresh) {
        await fetchIntegrations();
      }
      return response;
    } finally {
      setBusy(integration.id, false);
    }
  };

  const testConnection = async (integration) => {
    setBusy(integration.id, true);
    try {
      const response = await API.testMediaServerIntegration(integration.id);
      notifications.show({
        title: 'Connection successful',
        message: `${integration.name}: discovered ${response?.library_count || 0} libraries`,
        color: 'green',
      });
      await fetchIntegrations();
    } finally {
      setBusy(integration.id, false);
    }
  };

  const deleteIntegration = async (integration) => {
    const confirmed = window.confirm(`Delete integration "${integration.name}"?`);
    if (!confirmed) return;

    setBusy(integration.id, true);
    try {
      await API.deleteMediaServerIntegration(integration.id);
      if (scanIntegrationId === integration.id) {
        setScanDrawerOpen(false);
        setScanIntegrationId(null);
      }
      await fetchIntegrations();
    } finally {
      setBusy(integration.id, false);
    }
  };

  const openScanDrawer = (integration) => {
    setScanIntegrationId(integration.id);
    setScanDrawerOpen(true);
  };

  const closeScanDrawer = () => {
    setScanDrawerOpen(false);
  };

  const buildStrmSnapshot = async () => {
    const selectedIntegrationId = String(activeExportId || exportProfile.id || '').trim();
    const persistedIntegrationId = exportProfiles.some(
      (profile) => String(profile.id || '').trim() === selectedIntegrationId
    )
      ? selectedIntegrationId
      : '';

    setStrmBuildLoading(true);
    setStrmBuildError('');
    try {
      const response = await API.buildStrmExportSnapshot({
        integrationId: persistedIntegrationId,
        outputPath: exportProfile.strm_output_path,
        includeNfo: exportProfile.strm_include_nfo,
      });
      setStrmBuildResult(response);
      notifications.show({
        title: 'STRM/NFO snapshot generated',
        message: `Wrote ${response?.total_files_written || 0} files.`,
        color: 'green',
      });
      await fetchExportIntegrationState();
    } catch (error) {
      console.error('Failed to build STRM/NFO snapshot', error);
      setStrmBuildError(
        error?.body?.detail || error?.message || 'Failed to build STRM/NFO snapshot.'
      );
    } finally {
      setStrmBuildLoading(false);
    }
  };

  const syncExportProfile = async (profile) => {
    const profileId = String(profile?.id || '').trim();
    if (!profileId) return;

    setSyncingExportId(profileId);
    try {
      const response = await API.buildStrmExportSnapshot({
        integrationId: profileId,
        outputPath: profile?.strm_output_path,
        includeNfo: parseBoolean(profile?.strm_include_nfo, true),
      });
      notifications.show({
        title: 'STRM/NFO snapshot updated',
        message: `Wrote ${response?.total_files_written || 0} files.`,
        color: 'green',
      });
      await fetchExportIntegrationState();
    } catch (error) {
      console.error('Failed to sync output integration', error);
    } finally {
      setSyncingExportId('');
    }
  };

  const saveExportProfile = async () => {
    setSavingExportProfile(true);
    try {
      const outputState = await API.getOutputIntegrationState();
      const existingSetting =
        (outputState && typeof outputState.setting === 'object'
          ? outputState.setting
          : null) || outputSetting;

      const existingValue = normalizeSettingsValue(outputState?.value);
      const existingValueWithoutDeprecatedPath = sanitizeOutputSettings(existingValue);
      const existingProfiles = buildExportProfiles(existingValueWithoutDeprecatedPath);
      const storedProfileList = Array.isArray(
        existingValueWithoutDeprecatedPath.output_integrations
      )
        ? existingValueWithoutDeprecatedPath.output_integrations
        : [];
      const replacingLegacyOnlyProfile =
        storedProfileList.length === 0 &&
        existingProfiles.length === 1 &&
        String(existingProfiles[0]?.id || '').trim() === LEGACY_OUTPUT_ID;

      const integrationName =
        String(exportProfile.integration_name || '').trim() ||
        DEFAULT_EXPORT_PROFILE.integration_name;
      const draftProfileId =
        String(exportProfile.id || activeExportId || '').trim() || createExportProfileId();
      const persistedProfileId =
        draftProfileId === LEGACY_OUTPUT_ID ? createExportProfileId() : draftProfileId;

      const normalizedDraftProfile = buildExportProfile({
        ...exportProfile,
        id: persistedProfileId,
        integration_name: integrationName,
        target_provider: normalizeExportTarget(exportProfile.target_provider),
        export_mode: deriveExportMode(),
        export_enabled: true,
        strm_output_path:
          String(exportProfile.strm_output_path || '').trim() ||
          DEFAULT_EXPORT_PROFILE.strm_output_path,
        strm_include_nfo: parseBoolean(exportProfile.strm_include_nfo, true),
        updated_at: new Date().toISOString(),
      });

      const nextProfiles = replacingLegacyOnlyProfile ? [] : [...existingProfiles];
      const existingProfileIndex = nextProfiles.findIndex(
        (profile) =>
          String(profile.id || '').trim() === persistedProfileId ||
          (draftProfileId === LEGACY_OUTPUT_ID &&
            String(profile.id || '').trim() === LEGACY_OUTPUT_ID)
      );
      const isNewOutputIntegration = existingProfileIndex < 0;

      if (existingProfileIndex >= 0) {
        nextProfiles[existingProfileIndex] = normalizedDraftProfile;
      } else {
        nextProfiles.push(normalizedDraftProfile);
      }

      const primaryProfile = nextProfiles[0] || null;
      const legacyOutputFields = buildLegacyOutputFields(primaryProfile);
      const nextValue = sanitizeOutputSettings({
        ...existingValueWithoutDeprecatedPath,
        ...legacyOutputFields,
        output_integrations: nextProfiles,
      });

      if (existingSetting?.id) {
        await API.updateSetting({
          id: existingSetting.id,
          key: existingSetting.key,
          name: existingSetting.name || 'Output Settings',
          value: nextValue,
        });
      } else {
        await API.createSetting({
          key: 'output_settings',
          name: 'Output Settings',
          value: nextValue,
        });
      }

      let initialBuildSucceeded = true;
      if (isNewOutputIntegration) {
        setStrmBuildLoading(true);
        setStrmBuildError('');
        try {
          const buildResponse = await API.buildStrmExportSnapshot({
            integrationId: normalizedDraftProfile.id,
            outputPath: normalizedDraftProfile.strm_output_path,
            includeNfo: normalizedDraftProfile.strm_include_nfo,
          });
          setStrmBuildResult(buildResponse);
          notifications.show({
            title: 'Output integration saved',
            message: `Initial STRM/NFO snapshot generated (${buildResponse?.total_files_written || 0} files).`,
            color: 'green',
          });
        } catch (buildError) {
          initialBuildSucceeded = false;
          setStrmBuildResult(null);
          const message =
            buildError?.body?.detail ||
            buildError?.message ||
            'Failed to build initial STRM/NFO snapshot.';
          setStrmBuildError(message);
          notifications.show({
            title: 'Output integration saved',
            message: `Initial STRM/NFO snapshot failed: ${message}`,
            color: 'red',
          });
        } finally {
          setStrmBuildLoading(false);
        }
      } else {
        notifications.show({
          title: 'Output integration saved',
          message: `${integrationName} is now configured.`,
          color: 'green',
        });
      }

      setActiveExportId(normalizedDraftProfile.id);
      setExportProfile(normalizedDraftProfile);
      await fetchExportIntegrationState();
      if (!isNewOutputIntegration || initialBuildSucceeded) {
        setExportSetupOpen(false);
      }
    } catch (error) {
      console.error('Error saving output profile:', error);
    } finally {
      setSavingExportProfile(false);
    }
  };

  const deleteExportProfile = async (profile) => {
    const profileId = String(profile?.id || '').trim();
    if (!profileId) {
      return;
    }
    const profileName =
      String(profile?.integration_name || '').trim() || 'this output integration';
    const confirmed = window.confirm(
      `Delete "${profileName}"? This will remove the saved output profile.`
    );
    if (!confirmed) return;

    setDeletingExportProfileId(profileId);
    try {
      const response = await API.deleteOutputIntegration({
        integrationId: profileId,
        deleteStrmFiles: true,
      });
      const cleanup = response?.strm_cleanup || {};

      let message = response?.message || 'Output integration deleted.';
      let color = 'green';
      if (cleanup?.attempted) {
        if (cleanup?.skipped) {
          color = 'yellow';
          const linkedIntegrations = Array.isArray(cleanup?.in_use_by)
            ? cleanup.in_use_by
                .map((entry) => String(entry?.integration_name || '').trim())
                .filter(Boolean)
                .join(', ')
            : '';
          message = cleanup?.skip_reason || 'STRM cleanup was skipped.';
          if (linkedIntegrations) {
            message = `${message} In use by: ${linkedIntegrations}.`;
          }
        } else if (cleanup?.deleted) {
          const outputPath = String(cleanup?.output_path || '').trim();
          message = outputPath
            ? `Output integration deleted. Removed STRM files from ${outputPath}.`
            : 'Output integration deleted. STRM files were removed.';
        } else {
          message = 'Output integration deleted. No STRM files were found to remove.';
        }
      }

      notifications.show({
        title: 'Output integration deleted',
        message,
        color,
      });

      if (profileId === activeExportId) {
        setExportSetupOpen(false);
      }
      await fetchExportIntegrationState();
    } catch (error) {
      console.error('Failed to delete output integration:', error);
    } finally {
      setDeletingExportProfileId('');
    }
  };

  const activeScanIntegration =
    integrations.find((integration) => integration.id === scanIntegrationId) || null;

  const editingExistingExport = useMemo(
    () =>
      exportProfiles.some(
        (profile) =>
          String(profile.id || '').trim() === String(activeExportId || '').trim()
      ),
    [activeExportId, exportProfiles]
  );

  const exportIntegrated = exportProfiles.length > 0;

  const integrationCards = integrations.map((integration) => {
    const busy = !!busyById[integration.id];
    return (
      <Card
        key={integration.id}
        withBorder
        radius="md"
        p="md"
        style={{ backgroundColor: '#27272A', borderColor: '#3f3f46' }}
      >
        <Stack gap="sm">
          <Group justify="space-between" align="flex-start">
            <Stack gap={2}>
              <Group gap={8}>
                <Server size={16} />
                <Text fw={700}>{integration.name}</Text>
              </Group>
              <Text size="xs" c="dimmed">
                {integration.provider_type === 'local'
                  ? 'Local filesystem import'
                  : integration.base_url}
              </Text>
            </Stack>
            <Switch
              label="Enabled"
              checked={!!integration.enabled}
              onChange={() => toggleEnabled(integration)}
              disabled={busy}
            />
          </Group>

          <Group gap="xs">
            <ProviderBadge provider={integration.provider_type} />
            <Badge
              variant="light"
              color={statusColor(integration.last_sync_status)}
              leftSection={statusIcon(integration.last_sync_status)}
            >
              {integration.last_sync_status || 'idle'}
            </Badge>
            <Badge
              variant="outline"
              color={integration.add_to_vod ? 'green' : 'gray'}
            >
              {integration.add_to_vod ? 'VOD Enabled' : 'VOD Disabled'}
            </Badge>
          </Group>

          <Group gap={8}>
            <FolderKanban size={14} />
            <Text size="sm">
              {Array.isArray(integration.include_libraries) &&
              integration.include_libraries.length > 0
                ? `${integration.include_libraries.length} selected librar${integration.include_libraries.length > 1 ? 'ies' : 'y'}`
                : 'All media libraries'}
            </Text>
          </Group>

          <Text size="xs" c="dimmed">
            Last synced:{' '}
            {integration.last_synced_at
              ? new Date(integration.last_synced_at).toLocaleString()
              : 'Never'}
          </Text>
          <Text size="xs" c="dimmed">
            Auto sync: {formatSyncInterval(integration.sync_interval)}
          </Text>
          {integration.last_sync_message ? (
            <Text size="xs" c="dimmed" lineClamp={2}>
              {integration.last_sync_message}
            </Text>
          ) : null}

          <Flex justify="flex-end" gap="xs" mt="sm" wrap="wrap">
            <Button
              size="xs"
              variant="light"
              leftSection={<CircleCheckBig size={14} />}
              onClick={() => testConnection(integration)}
              loading={busy}
            >
              Test
            </Button>
            <Button
              size="xs"
              variant="light"
              leftSection={<RefreshCw size={14} />}
              onClick={() => runSync(integration)}
              loading={busy}
            >
              Sync
            </Button>
            <Button
              size="xs"
              variant="default"
              leftSection={<ScanSearch size={14} />}
              onClick={() => openScanDrawer(integration)}
              disabled={busy}
            >
              View Scan
            </Button>
            <Button
              size="xs"
              variant="default"
              onClick={() => openEdit(integration)}
              disabled={busy}
            >
              Edit
            </Button>
            <Button
              size="xs"
              color="red"
              variant="outline"
              onClick={() => deleteIntegration(integration)}
              disabled={busy}
            >
              Delete
            </Button>
          </Flex>
        </Stack>
      </Card>
    );
  });

  const exportCards = exportProfiles.map((profile) => {
    const deletingThisProfile =
      String(deletingExportProfileId || '').trim() ===
      String(profile.id || '').trim();
    const syncingThisProfile =
      String(syncingExportId || '').trim() === String(profile.id || '').trim();
    const lastBuildSummary =
      profile.strm_last_build_summary &&
      typeof profile.strm_last_build_summary === 'object'
        ? profile.strm_last_build_summary
        : null;
    const strmItemsWritten = parseCount(lastBuildSummary?.strm_files_written);
    const moviesWritten = parseCount(lastBuildSummary?.movies_written);
    const seriesWritten = parseCount(lastBuildSummary?.series_written);
    const episodesWritten = parseCount(lastBuildSummary?.episodes_written);

    return (
      <Card
        key={`dispatcharr-export-${profile.id}`}
        withBorder
        radius="md"
        p="md"
        style={{ backgroundColor: '#27272A', borderColor: '#3f3f46' }}
      >
        <Stack gap="sm">
          <Group justify="space-between" align="flex-start">
            <Stack gap={2}>
              <Group gap={8}>
                <HardDrive size={16} />
                <Text fw={700}>{profile.integration_name || 'Dispatcharr Output'}</Text>
              </Group>
              <Text size="xs" c="dimmed">
                Jellyfin/Emby output via STRM + NFO files.
              </Text>
            </Stack>
            <Badge variant="light" color="indigo">
              Export
            </Badge>
          </Group>

          <Group gap="xs">
            <ProviderBadge provider={profile.target_provider} />
            <Badge
              variant="outline"
              color={parseBoolean(profile.export_enabled, false) ? 'green' : 'gray'}
            >
              {parseBoolean(profile.export_enabled, false) ? 'Enabled' : 'Disabled'}
            </Badge>
            <Badge variant="outline" color="blue">
              STRM/NFO
            </Badge>
          </Group>

          <Text size="xs" c="dimmed">
            Output path:{' '}
            {profile.strm_output_path || DEFAULT_EXPORT_PROFILE.strm_output_path}
          </Text>

          {lastBuildSummary ? (
            <Text size="xs" c="dimmed">
              Items: {strmItemsWritten} (Movies: {moviesWritten}, Series:{' '}
              {seriesWritten}, Episodes: {episodesWritten})
            </Text>
          ) : null}

          {profile.strm_last_build_summary?.message ? (
            <Text size="xs" c="dimmed" lineClamp={2}>
              {profile.strm_last_build_summary.message}
            </Text>
          ) : null}

          <Flex justify="flex-end" gap="xs" mt="sm" wrap="wrap">
            <Button
              size="xs"
              variant="light"
              leftSection={<RefreshCw size={14} />}
              loading={syncingThisProfile}
              onClick={() => syncExportProfile(profile)}
            >
              Sync
            </Button>
            <Button
              size="xs"
              variant="light"
              leftSection={<Pencil size={14} />}
              onClick={() => openExportSetup(profile)}
            >
              Edit
            </Button>
            <Button
              size="xs"
              color="red"
              variant="outline"
              leftSection={<Trash2 size={14} />}
              loading={deletingThisProfile}
              onClick={() => deleteExportProfile(profile)}
            >
              Delete
            </Button>
          </Flex>
        </Stack>
      </Card>
    );
  });

  let content = null;
  if (loading) {
    content = (
      <Flex justify="center" py="xl">
        <Loader />
      </Flex>
    );
  } else {
    content = (
      <Box
        style={{
          display: 'grid',
          gap: '1rem',
          gridTemplateColumns: 'repeat(auto-fill, minmax(380px, 1fr))',
        }}
      >
        {exportCards}
        {integrationCards}
        {!integrations.length && !exportIntegrated ? (
          <Card
            withBorder
            radius="md"
            p="xl"
            style={{ backgroundColor: '#27272A', borderColor: '#3f3f46' }}
          >
            <Stack align="center" gap="sm">
              <Server size={24} />
              <Text fw={600}>No integrations configured</Text>
              <Text size="sm" c="dimmed" ta="center">
                Add an import integration to ingest content, or add an output
                integration to publish VODs.
              </Text>
            </Stack>
          </Card>
        ) : null}
      </Box>
    );
  }

  if (!isAdmin) {
    return (
      <Box p="md">
        <Title order={3}>Media Servers</Title>
        <Text c="dimmed" mt="sm">
          Admin access is required.
        </Text>
      </Box>
    );
  }

  return (
    <Box p="md">
      <Group justify="space-between" mb="md">
        <Title order={3}>Media Servers</Title>
        <Button
          leftSection={<SquarePlus size={14} />}
          variant="light"
          size="xs"
          onClick={openCreate}
          p={5}
          color="green"
          style={{
            borderWidth: '1px',
            borderColor: 'green',
            color: 'white',
          }}
        >
          Add Media Server
        </Button>
      </Group>

      {content}

      <Modal
        opened={integrationTypeOpen}
        onClose={closeIntegrationType}
        size="md"
        title="New Integration"
      >
        <Stack gap="md">
          <Text size="sm" c="dimmed">
            Choose whether Dispatcharr should ingest media from a source, or
            publish Dispatcharr VODs to an external media server.
          </Text>

          <Card withBorder radius="md" p="md" style={{ borderColor: '#3f3f46' }}>
            <Stack gap="xs">
              <Group gap="xs">
                <ArrowDownToLine size={16} />
                <Text fw={600}>Ingest Media Into Dispatcharr</Text>
              </Group>
              <Text size="sm" c="dimmed">
                Connect Plex, Emby, Jellyfin, or Local folders so Dispatcharr can
                import titles into VOD.
              </Text>
              <Flex justify="flex-end">
                <Button size="xs" variant="light" onClick={startImportIntegration}>
                  Import
                </Button>
              </Flex>
            </Stack>
          </Card>

          <Card withBorder radius="md" p="md" style={{ borderColor: '#3f3f46' }}>
            <Stack gap="xs">
              <Group gap="xs">
                <ArrowUpFromLine size={16} />
                <Text fw={600}>Publish Dispatcharr VODs</Text>
              </Group>
              <Text size="sm" c="dimmed">
                Export VOD files as STRM/NFO output for Jellyfin or Emby.
              </Text>
              <Flex justify="flex-end">
                <Button size="xs" variant="light" onClick={openExportSetup}>
                  Export
                </Button>
              </Flex>
            </Stack>
          </Card>
        </Stack>
      </Modal>

      <MediaServerIntegrationForm
        integration={activeIntegration}
        isOpen={formOpen}
        onClose={closeForm}
        onSaved={onSaved}
      />

      <MediaServerSyncDrawer
        opened={scanDrawerOpen}
        onClose={closeScanDrawer}
        integration={activeScanIntegration}
        onRefreshIntegrations={fetchIntegrations}
        onRunSync={runSync}
      />

      <Modal
        opened={exportSetupOpen}
        onClose={closeExportSetup}
        size="lg"
        title={editingExistingExport ? 'VOD Export' : 'New VOD Export'}
      >
        <Stack gap="md">
          <Text size="sm" c="dimmed">
            Configure how Dispatcharr publishes VODs to your target media server.
          </Text>

          {exportStateLoading ? (
            <Group gap="xs">
              <Loader size="sm" />
              <Text size="sm" c="dimmed">
                Loading output integration state...
              </Text>
            </Group>
          ) : null}

          <TextInput
            label="Integration Name"
            value={exportProfile.integration_name}
            onChange={(event) => {
              const value = event.currentTarget.value;
              setExportProfile((prev) => ({
                ...prev,
                integration_name: value,
              }));
            }}
            placeholder="Dispatcharr Output"
          />

          <Select
            label="Target Media Server"
            data={EXPORT_TARGET_OPTIONS}
            value={normalizeExportTarget(exportProfile.target_provider)}
            onChange={(value) => {
              const provider = normalizeExportTarget(value);
              setExportProfile((prev) => ({
                ...prev,
                target_provider: provider,
                export_mode: deriveExportMode(provider),
              }));
              setStrmBuildError('');
              setStrmBuildResult(null);
            }}
            allowDeselect={false}
          />

          <Divider label="STRM/NFO Export" labelPosition="left" />

          <TextInput
            label="Server Output Path (Docker Mount Source)"
            description="Path on the Dispatcharr host where STRM/NFO files are generated."
            value={exportProfile.strm_output_path}
            onChange={(event) => {
              const value = event.currentTarget.value;
              setExportProfile((prev) => ({
                ...prev,
                strm_output_path: value,
              }));
            }}
          />

          <Switch
            label="Generate NFO files"
            checked={!!exportProfile.strm_include_nfo}
            onChange={(event) => {
              const checked = event.currentTarget.checked;
              setExportProfile((prev) => ({
                ...prev,
                strm_include_nfo: checked,
              }));
            }}
          />

          <Group gap="xs" wrap="wrap">
            <Button
              type="button"
              size="xs"
              variant="light"
              loading={strmBuildLoading}
              leftSection={<RefreshCw size={14} />}
              onClick={buildStrmSnapshot}
            >
              Initialize STRM source
            </Button>
          </Group>

          {strmBuildError ? (
            <Alert color="red" variant="light" title="STRM Build Error">
              {strmBuildError}
            </Alert>
          ) : null}

          {strmBuildResult ? (
            <Alert color="green" variant="light" title="STRM Snapshot Ready">
              <Text size="sm">
                Files: {strmBuildResult?.total_files_written || 0} (STRM:{' '}
                {strmBuildResult?.strm_files_written || 0}, NFO:{' '}
                {strmBuildResult?.nfo_files_written || 0})
              </Text>
              <Text size="xs" c="dimmed">
                Output: {strmBuildResult?.output_root}
              </Text>
            </Alert>
          ) : null}

          <Text size="xs" c="dimmed">
            These are example mounts for Movies and TV. Adjust paths to match your setup.
          </Text>
          <Text
            component="pre"
            p="sm"
            style={{
              fontFamily:
                'ui-monospace, Menlo, Monaco, Consolas, "Liberation Mono", monospace',
              fontSize: '0.82rem',
              whiteSpace: 'pre-wrap',
              border: '1px solid var(--mantine-color-gray-4)',
              borderRadius: 8,
              backgroundColor: 'rgba(0, 0, 0, 0.2)',
              overflowX: 'auto',
            }}
          >
            {dockerMountSnippet}
          </Text>

          <Flex justify="flex-end" gap="xs">
            <Button variant="default" onClick={closeExportSetup}>
              Cancel
            </Button>
            <Button loading={savingExportProfile} onClick={saveExportProfile}>
              Save
            </Button>
          </Flex>
        </Stack>
      </Modal>
    </Box>
  );
}
