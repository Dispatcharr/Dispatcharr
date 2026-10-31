import { useCallback, useEffect, useState } from 'react';
import {
  ActionIcon,
  Badge,
  Button,
  Checkbox,
  Group,
  Loader,
  Paper,
  Stack,
  Switch,
  Table,
  Text,
  Tooltip,
} from '@mantine/core';
import { PlugZap, SquarePen } from 'lucide-react';
import api from '../../../api';
import { formatApiError } from '../../../utils';
import {
  libraryFieldError,
  notifyLibraryError,
} from '../../../utils/libraryFeedback.js';
import { showNotification } from '../../../utils/notificationUtils.js';
import { SensitivePasswordInput } from '../../SensitiveFields.jsx';
import CleanupRulesEditor from './CleanupRulesEditor.jsx';
import { LibraryDialog } from '../../LibraryDialogs.jsx';
import MetadataLanguagesInput from './MetadataLanguagesInput.jsx';
import { MAX_METADATA_LANGUAGES } from '../../../utils/vodMetadataLanguages.js';
import classes from '../../LibraryWorkspace.module.css';

const FIELDS = {
  metadata: ['languages', 'auto_enrich', 'match_missing', 'prefer_artwork'],
  cleanup: ['title_rules', 'removal_rules', 'year_rules'],
};
const ownedValues = (settings, section) =>
  Object.fromEntries(FIELDS[section].map((field) => [field, settings[field]]));

export function MetadataSettingsForm() {
  return <VODSettingsForm section="metadata" />;
}

export function CleanupSettingsForm() {
  return <VODSettingsForm section="cleanup" />;
}

function VODSettingsForm({ section }) {
  const metadata = section === 'metadata';
  const [initial, setInitial] = useState(null);
  const [draft, setDraft] = useState(null);
  const [info, setInfo] = useState(null);
  const [token, setToken] = useState('');
  const [clearToken, setClearToken] = useState(false);
  const [providerEditing, setProviderEditing] = useState(false);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [cleanupDirty, setCleanupDirty] = useState(false);
  const [connection, setConnection] = useState(null);
  const testConnection = async () => {
    if (busy) return;
    setBusy(true);
    setError('');
    try {
      const result = await api.vodLibraryAction(
        'test-connection',
        providerEditing && token.trim() ? { api_token: token.trim() } : {}
      );
      setConnection(result);
      if (!providerEditing || !token.trim())
        setInfo((current) => ({ ...current, connection: result }));
      if (result.status === 'connected')
        showNotification({
          title: 'TMDB',
          message: result.detail,
          color: 'green',
        });
      else {
        setError({ body: { api_token: [result.detail] } });
        notifyLibraryError(new Error(result.detail), 'TMDB connection');
      }
    } catch (err) {
      // A failed check concerns the credential, not the other settings.
      setError({ body: { api_token: [formatApiError(err)] } });
      notifyLibraryError(err, 'TMDB connection');
    } finally {
      setBusy(false);
    }
  };
  const providerStatus =
    info?.connection?.status ||
    (info?.token_configured ? 'unchecked' : 'not_configured');
  const providerStatusLabels = {
    connected: 'Connected',
    unchecked: 'Not checked',
    error: 'Connection error',
    not_configured: 'Not configured',
  };
  const dirty =
    !!draft &&
    (cleanupDirty ||
      JSON.stringify(draft) !== JSON.stringify(initial) ||
      !!token ||
      clearToken);
  const languagesChanged =
    JSON.stringify(draft?.languages) !== JSON.stringify(initial?.languages);
  const languageError =
    metadata &&
    draft &&
    (!draft.languages.length
      ? 'Choose at least one metadata language.'
      : languagesChanged && draft.languages.length > MAX_METADATA_LANGUAGES
        ? 'Choose no more than 5 metadata languages.'
        : undefined);
  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const settings = await api.getVODLibrarySettings();
      setInfo(settings);
      setConnection(settings.connection || null);
      setInitial(ownedValues(settings, section));
      setDraft(ownedValues(settings, section));
    } catch (err) {
      setError(err);
      notifyLibraryError(
        err,
        metadata ? 'Metadata settings' : 'Cleanup settings'
      );
    } finally {
      setLoading(false);
    }
  }, [section, metadata]);
  useEffect(() => {
    load();
  }, [load]);
  useEffect(() => {
    if (!dirty) return undefined;
    const warn = (event) => {
      event.preventDefault();
      event.returnValue = '';
    };
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [dirty]);
  const update = (field, value) => {
    setDraft((current) => ({ ...current, [field]: value }));
  };
  const persist = async (values, { providerOnly = false } = {}) => {
    if (busy) return false;
    setBusy(true);
    setError('');
    try {
      const settings = await api.updateVODLibrarySettings(values);
      setInfo(settings);
      if (!providerOnly) {
        setInitial(ownedValues(settings, section));
        setDraft(ownedValues(settings, section));
      }
      setToken('');
      setClearToken(false);
      if (providerOnly) setProviderEditing(false);
      showNotification({
        title: metadata ? 'Metadata' : 'Cleanup',
        message: 'Settings saved successfully',
        color: 'green',
        autoClose: 2000,
      });
      return true;
    } catch (err) {
      setError(err);
      notifyLibraryError(
        err,
        metadata ? 'Metadata settings' : 'Cleanup settings'
      );
      return false;
    } finally {
      setBusy(false);
    }
  };
  const save = async (event) => {
    event.preventDefault();
    if (!metadata || !dirty || busy || providerEditing || languageError) return;
    const values = { ...draft };
    if (!languagesChanged && draft.languages.length > MAX_METADATA_LANGUAGES)
      delete values.languages;
    await persist(values);
  };
  const saveProvider = () => {
    if (!providerEditing || busy || (!token.trim() && !clearToken)) return;
    persist(
      clearToken ? { clear_api_token: true } : { api_token: token.trim() },
      { providerOnly: true }
    );
  };
  return (
    <form onSubmit={save}>
      <Stack
        component="fieldset"
        disabled={busy}
        gap="md"
        style={{ border: 0, padding: 0, margin: 0, minWidth: 0 }}
      >
        {error && !draft && (
          <Button variant="subtle" onClick={load}>
            Retry
          </Button>
        )}
        {loading && <Loader size="sm" />}
        {draft && (
          <>
            {metadata && (
              <>
                <Paper withBorder p="md">
                  <Stack gap="sm">
                    <Text fw={600}>Metadata providers</Text>
                    <div className={classes.tableFrame}>
                      <Table.ScrollContainer minWidth={400}>
                        <Table
                          striped
                          className={classes.cleanupTable}
                          aria-label="Metadata providers"
                        >
                          <Table.Thead>
                            <Table.Tr>
                              <Table.Th>Provider</Table.Th>
                              <Table.Th>Status</Table.Th>
                              <Table.Th
                                style={{ textAlign: 'center', width: 96 }}
                              >
                                Actions
                              </Table.Th>
                            </Table.Tr>
                          </Table.Thead>
                          <Table.Tbody>
                            <Table.Tr>
                              <Table.Td>
                                <Text fw={500}>TMDB</Text>
                              </Table.Td>
                              <Table.Td>
                                <Tooltip
                                  label={
                                    info.connection?.checked_at
                                      ? `${info.connection.detail} Checked ${new Date(info.connection.checked_at).toLocaleString()}`
                                      : 'Test the connection to verify the configured credential.'
                                  }
                                >
                                  <Badge
                                    color={
                                      providerStatus === 'connected'
                                        ? 'green'
                                        : providerStatus === 'error'
                                          ? 'red'
                                          : 'gray'
                                    }
                                    variant="light"
                                  >
                                    {providerStatusLabels[providerStatus]}
                                  </Badge>
                                </Tooltip>
                              </Table.Td>
                              <Table.Td style={{ textAlign: 'center' }}>
                                <Group gap={4} justify="center" wrap="nowrap">
                                  <Tooltip label="Test TMDB connection">
                                    <ActionIcon
                                      type="button"
                                      variant="subtle"
                                      aria-label="Test TMDB connection"
                                      disabled={
                                        busy ||
                                        providerEditing ||
                                        !info.token_configured
                                      }
                                      onClick={testConnection}
                                    >
                                      <PlugZap size={16} />
                                    </ActionIcon>
                                  </Tooltip>
                                  <Tooltip
                                    label={
                                      info.token_source === 'environment'
                                        ? 'Configured by the server environment.'
                                        : 'Edit TMDB'
                                    }
                                  >
                                    <span>
                                      <ActionIcon
                                        type="button"
                                        variant="subtle"
                                        color="yellow"
                                        aria-label="Edit TMDB"
                                        disabled={
                                          busy ||
                                          providerEditing ||
                                          info.token_source === 'environment'
                                        }
                                        onClick={() => {
                                          setProviderEditing(true);
                                          setError('');
                                          setConnection(null);
                                        }}
                                      >
                                        <SquarePen size={16} />
                                      </ActionIcon>
                                    </span>
                                  </Tooltip>
                                </Group>
                              </Table.Td>
                            </Table.Tr>
                          </Table.Tbody>
                        </Table>
                      </Table.ScrollContainer>
                    </div>
                    {providerEditing && (
                      <LibraryDialog
                        title="Configure TMDB"
                        busy={busy}
                        dirty={!!token || clearToken}
                        onClose={() => {
                          setToken('');
                          setClearToken(false);
                          setProviderEditing(false);
                          setError('');
                        }}
                      >
                        <Stack gap="md">
                          <Stack gap="xs">
                            <SensitivePasswordInput
                              label="API Read Access Token"
                              aria-invalid={
                                !!libraryFieldError(error, 'api_token')
                              }
                              error={libraryFieldError(error, 'api_token')}
                              description={
                                info.token_source === 'environment'
                                  ? 'Configured by the server environment.'
                                  : info.token_configured
                                    ? 'A token is stored. Leave blank to keep it.'
                                    : 'Use the TMDB API Read Access Token (recommended). A v3 API key is also supported.'
                              }
                              value={token}
                              onChange={(e) => {
                                setToken(e.currentTarget.value);
                                setClearToken(false);
                                setConnection(null);
                                setError('');
                              }}
                              autoComplete="new-password"
                              autoFocus
                              onKeyDown={(event) => {
                                if (
                                  event.key === 'Enter' &&
                                  !event.nativeEvent.isComposing
                                ) {
                                  event.preventDefault();
                                  saveProvider();
                                }
                              }}
                              disabled={
                                busy || info.token_source === 'environment'
                              }
                            />
                            {info.token_source === 'stored' && (
                              <Checkbox
                                label="Remove stored token"
                                checked={clearToken}
                                disabled={busy}
                                onChange={(e) => {
                                  setClearToken(e.currentTarget.checked);
                                  setToken('');
                                }}
                              />
                            )}
                          </Stack>
                          <Group justify="flex-end">
                            <Button
                              type="button"
                              variant="default"
                              onClick={testConnection}
                              disabled={
                                busy ||
                                clearToken ||
                                (!token.trim() && !info.token_configured)
                              }
                            >
                              Test connection
                            </Button>
                            {connection?.status === 'connected' && (
                              <Badge color="green">Connected</Badge>
                            )}
                            <Button
                              type="button"
                              aria-label="Save TMDB"
                              loading={busy}
                              disabled={!token.trim() && !clearToken}
                              onClick={saveProvider}
                            >
                              Save
                            </Button>
                          </Group>
                        </Stack>
                      </LibraryDialog>
                    )}
                  </Stack>
                </Paper>
                <Paper withBorder p="md">
                  <Stack gap="sm">
                    <Text fw={600}>Languages</Text>
                    <MetadataLanguagesInput
                      value={draft.languages}
                      onChange={(value) => update('languages', value)}
                      error={
                        libraryFieldError(error, 'languages') || languageError
                      }
                      disabled={busy || providerEditing}
                    />
                    {draft.languages.length > MAX_METADATA_LANGUAGES && (
                      <Text size="xs" c="dimmed">
                        Existing languages are kept. A changed selection must
                        contain no more than 5 languages.
                      </Text>
                    )}
                  </Stack>
                </Paper>
                <Paper withBorder p="md">
                  <Stack gap="sm">
                    <Text fw={600}>Settings</Text>
                    <Switch
                      label="Enrich new imported titles automatically"
                      checked={draft.auto_enrich}
                      disabled={providerEditing}
                      onChange={(e) =>
                        update('auto_enrich', e.currentTarget.checked)
                      }
                    />
                    <Switch
                      label="Search TMDB for titles without external IDs"
                      checked={draft.match_missing}
                      disabled={providerEditing}
                      onChange={(e) =>
                        update('match_missing', e.currentTarget.checked)
                      }
                    />
                    <Switch
                      label="Prefer TMDB artwork in the Library"
                      checked={draft.prefer_artwork}
                      disabled={providerEditing}
                      onChange={(e) =>
                        update('prefer_artwork', e.currentTarget.checked)
                      }
                    />
                  </Stack>
                </Paper>
              </>
            )}
            {!metadata && (
              <CleanupRulesEditor
                settings={draft}
                busy={busy}
                onSave={persist}
                onDirtyChange={setCleanupDirty}
                onResetFeedback={() => {
                  setError('');
                }}
              />
            )}
            {metadata && (
              <Group justify="flex-end">
                <Button
                  type="submit"
                  loading={busy}
                  disabled={!dirty || providerEditing || !!languageError}
                >
                  Save
                </Button>
              </Group>
            )}
          </>
        )}
      </Stack>
    </form>
  );
}
