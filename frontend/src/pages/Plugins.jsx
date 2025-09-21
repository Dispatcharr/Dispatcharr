import React, { useEffect, useState } from 'react';
import {
  AppShell,
  Box,
  Alert,
  Button,
  Card,
  Group,
  Loader,
  Stack,
  Switch,
  Text,
  TextInput,
  NumberInput,
  Select,
  Divider,
  ActionIcon,
  SimpleGrid,
  Modal,
  FileInput,
} from '@mantine/core';
import { Dropzone } from '@mantine/dropzone';
import { RefreshCcw, Trash2 } from 'lucide-react';
import API from '../api';
import { notifications } from '@mantine/notifications';

const Field = ({ field, value, onChange }) => {
  const common = { label: field.label, description: field.help_text };
  const effective = value ?? field.default;
  switch (field.type) {
    case 'boolean':
      return (
        <Switch
          checked={!!effective}
          onChange={(e) => onChange(field.id, e.currentTarget.checked)}
          label={field.label}
          description={field.help_text}
        />
      );
    case 'number':
      return (
        <NumberInput
          value={value ?? field.default ?? 0}
          onChange={(v) => onChange(field.id, v)}
          {...common}
        />
      );
    case 'select':
      return (
        <Select
          value={(value ?? field.default ?? '') + ''}
          data={(field.options || []).map((o) => ({
            value: o.value + '',
            label: o.label,
          }))}
          onChange={(v) => onChange(field.id, v)}
          {...common}
        />
      );
    case 'string':
    default:
      return (
        <TextInput
          value={value ?? field.default ?? ''}
          onChange={(e) => onChange(field.id, e.currentTarget.value)}
          {...common}
        />
      );
  }
};

const PluginCard = ({
  plugin,
  onSaveSettings,
  onRunAction,
  onToggleEnabled,
  onRequireTrust,
  onRequestDelete,
}) => {
  const [settings, setSettings] = useState(plugin.settings || {});
  const [saving, setSaving] = useState(false);
  const [running, setRunning] = useState(false);
  const [enabled, setEnabled] = useState(!!plugin.enabled);
  const [lastResult, setLastResult] = useState(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [confirmConfig, setConfirmConfig] = useState({
    title: '',
    message: '',
    onConfirm: null,
  });

  // Keep local enabled state in sync with props (e.g., after import + enable)
  React.useEffect(() => {
    setEnabled(!!plugin.enabled);
  }, [plugin.enabled]);
  // Sync settings if plugin changes identity
  React.useEffect(() => {
    setSettings(plugin.settings || {});
  }, [plugin.key]);

  const updateField = (id, val) => {
    setSettings((prev) => ({ ...prev, [id]: val }));
  };

  const save = async () => {
    setSaving(true);
    try {
      await onSaveSettings(plugin.key, settings);
      notifications.show({
        title: 'Saved',
        message: `${plugin.name} settings updated`,
        color: 'green',
      });
    } finally {
      setSaving(false);
    }
  };

  const missing = plugin.missing;
  return (
    <Card
      shadow="sm"
      radius="md"
      withBorder
      style={{ opacity: !missing && enabled ? 1 : 0.6 }}
    >
      <Group justify="space-between" mb="xs" align="center">
        <div>
          <Text fw={600}>{plugin.name}</Text>
          <Text size="sm" c="dimmed">
            {plugin.description}
          </Text>
        </div>
        <Group gap="xs" align="center">
          <ActionIcon
            variant="subtle"
            color="red"
            title="Delete plugin"
            onClick={() => onRequestDelete && onRequestDelete(plugin)}
          >
            <Trash2 size={16} />
          </ActionIcon>
          <Text size="xs" c="dimmed">
            v{plugin.version || '1.0.0'}
          </Text>
          <Switch
            checked={!missing && enabled}
            onChange={async (e) => {
              const next = e.currentTarget.checked;
              if (next && !plugin.ever_enabled && onRequireTrust) {
                const ok = await onRequireTrust(plugin);
                if (!ok) {
                  // Revert
                  setEnabled(false);
                  return;
                }
              }
              setEnabled(next);
              const resp = await onToggleEnabled(plugin.key, next);
              if (next && resp?.ever_enabled) {
                plugin.ever_enabled = true;
              }
            }}
            size="xs"
            onLabel="On"
            offLabel="Off"
            disabled={missing}
          />
        </Group>
      </Group>

      {missing && (
        <Text size="sm" c="red">
          Missing plugin files. Re-import or delete this entry.
        </Text>
      )}

      {!missing && plugin.fields && plugin.fields.length > 0 && (
        <Stack gap="xs" mt="sm">
          {plugin.fields.map((f) => (
            <Field
              key={f.id}
              field={f}
              value={settings?.[f.id]}
              onChange={updateField}
            />
          ))}
          <Group>
            <Button loading={saving} onClick={save} variant="default" size="xs">
              Save Settings
            </Button>
          </Group>
        </Stack>
      )}

      {!missing && plugin.actions && plugin.actions.length > 0 && (
        <>
          <Divider my="sm" />
          <Stack gap="xs">
            {plugin.actions.map((a) => (
              <Group key={a.id} justify="space-between">
                <div>
                  <Text>{a.label}</Text>
                  {a.description && (
                    <Text size="sm" c="dimmed">
                      {a.description}
                    </Text>
                  )}
                </div>
                <Button
                  loading={running}
                  disabled={!enabled}
                  onClick={async () => {
                    setRunning(true);
                    setLastResult(null);
                    try {
                      // Determine if confirmation is required from action metadata or fallback field
                      const actionConfirm = a.confirm;
                      const confirmField = (plugin.fields || []).find(
                        (f) => f.id === 'confirm'
                      );
                      let requireConfirm = false;
                      let confirmTitle = `Run ${a.label}?`;
                      let confirmMessage = `You're about to run "${a.label}" from "${plugin.name}".`;
                      if (actionConfirm) {
                        if (typeof actionConfirm === 'boolean') {
                          requireConfirm = actionConfirm;
                        } else if (typeof actionConfirm === 'object') {
                          requireConfirm = actionConfirm.required !== false;
                          if (actionConfirm.title)
                            confirmTitle = actionConfirm.title;
                          if (actionConfirm.message)
                            confirmMessage = actionConfirm.message;
                        }
                      } else if (confirmField) {
                        const settingVal = settings?.confirm;
                        const effectiveConfirm =
                          (settingVal !== undefined
                            ? settingVal
                            : confirmField.default) ?? false;
                        requireConfirm = !!effectiveConfirm;
                      }

                      if (requireConfirm) {
                        await new Promise((resolve) => {
                          setConfirmConfig({
                            title: confirmTitle,
                            message: confirmMessage,
                            onConfirm: resolve,
                          });
                          setConfirmOpen(true);
                        });
                      }

                      // Save settings before running to ensure backend uses latest values
                      try {
                        await onSaveSettings(plugin.key, settings);
                      } catch (e) {
                        /* ignore, run anyway */
                      }
                      const resp = await onRunAction(plugin.key, a.id);
                      if (resp?.success) {
                        setLastResult(resp.result || {});
                        const msg =
                          resp.result?.message || 'Plugin action completed';
                        notifications.show({
                          title: plugin.name,
                          message: msg,
                          color: 'green',
                        });
                      } else {
                        const err = resp?.error || 'Unknown error';
                        setLastResult({ error: err });
                        notifications.show({
                          title: `${plugin.name} error`,
                          message: String(err),
                          color: 'red',
                        });
                      }
                    } finally {
                      setRunning(false);
                    }
                  }}
                  size="xs"
                >
                  {running ? 'Running…' : 'Run'}
                </Button>
              </Group>
            ))}
            {running && (
              <Text size="sm" c="dimmed">
                Running action… please wait
              </Text>
            )}
            {!running && lastResult?.file && (
              <Text size="sm" c="dimmed">
                Output: {lastResult.file}
              </Text>
            )}
            {!running && lastResult?.error && (
              <Text size="sm" c="red">
                Error: {String(lastResult.error)}
              </Text>
            )}
          </Stack>
        </>
      )}
      <Modal
        opened={confirmOpen}
        onClose={() => {
          setConfirmOpen(false);
          setConfirmConfig({ title: '', message: '', onConfirm: null });
        }}
        title={confirmConfig.title}
        centered
      >
        <Stack>
          <Text size="sm">{confirmConfig.message}</Text>
          <Group justify="flex-end">
            <Button
              variant="default"
              size="xs"
              onClick={() => {
                setConfirmOpen(false);
                setConfirmConfig({ title: '', message: '', onConfirm: null });
              }}
            >
              Cancel
            </Button>
            <Button
              size="xs"
              onClick={() => {
                const cb = confirmConfig.onConfirm;
                setConfirmOpen(false);
                setConfirmConfig({ title: '', message: '', onConfirm: null });
                cb && cb(true);
              }}
            >
              Confirm
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Card>
  );
};

export default function PluginsPage() {
  const [loading, setLoading] = useState(true);
  const [plugins, setPlugins] = useState([]);
  const [importOpen, setImportOpen] = useState(false);
  const [importFile, setImportFile] = useState(null);
  const [importing, setImporting] = useState(false);
  const [imported, setImported] = useState(null);
  const [enableAfterImport, setEnableAfterImport] = useState(false);
  const [trustOpen, setTrustOpen] = useState(false);
  const [trustResolve, setTrustResolve] = useState(null);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [deleting, setDeleting] = useState(false);
  const [uploadNoticeId, setUploadNoticeId] = useState(null);

  const load = async () => {
    setLoading(true);
    try {
      const list = await API.getPlugins();
      setPlugins(list);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const requireTrust = (plugin) => {
    return new Promise((resolve) => {
      setTrustResolve(() => resolve);
      setTrustOpen(true);
    });
  };

  return (
    <AppShell.Main style={{ padding: 16 }}>
      <Group justify="space-between" mb="md">
        <Text fw={700} size="lg">
          Plugins
        </Text>
        <Group>
          <Button
            size="xs"
            variant="light"
            onClick={() => {
              setImportOpen(true);
              setImported(null);
              setImportFile(null);
              setEnableAfterImport(false);
            }}
          >
            Import Plugin
          </Button>
          <ActionIcon
            variant="light"
            onClick={async () => {
              await API.reloadPlugins();
              await load();
            }}
            title="Reload"
          >
            <RefreshCcw size={18} />
          </ActionIcon>
        </Group>
      </Group>

      {loading ? (
        <Loader />
      ) : (
        <>
          <SimpleGrid
            cols={2}
            spacing="md"
            verticalSpacing="md"
            breakpoints={[{ maxWidth: '48em', cols: 1 }]}
          >
            {plugins.map((p) => (
              <PluginCard
                key={p.key}
                plugin={p}
                onSaveSettings={API.updatePluginSettings}
                onRunAction={API.runPluginAction}
                onToggleEnabled={async (key, next) => {
                  const resp = await API.setPluginEnabled(key, next);
                  if (resp?.ever_enabled !== undefined) {
                    setPlugins((prev) =>
                      prev.map((pl) =>
                        pl.key === key
                          ? {
                              ...pl,
                              ever_enabled: resp.ever_enabled,
                              enabled: resp.enabled,
                            }
                          : pl
                      )
                    );
                  } else {
                    setPlugins((prev) =>
                      prev.map((pl) =>
                        pl.key === key ? { ...pl, enabled: next } : pl
                      )
                    );
                  }
                  return resp;
                }}
                onRequireTrust={requireTrust}
                onRequestDelete={(plugin) => {
                  setDeleteTarget(plugin);
                  setDeleteOpen(true);
                }}
              />
            ))}
          </SimpleGrid>
          {plugins.length === 0 && (
            <Box>
              <Text c="dimmed">
                No plugins found. Drop a plugin into <code>/data/plugins</code>{' '}
                and reload.
              </Text>
            </Box>
          )}
        </>
      )}
      {/* Import Plugin Modal */}
      <Modal
        opened={importOpen}
        onClose={() => setImportOpen(false)}
        title="Import Plugin"
        centered
      >
        <Stack>
          <Text size="sm" c="dimmed">
            Upload a ZIP containing your plugin folder or package.
          </Text>
          <Alert color="yellow" variant="light" title="Heads up">
            Importing a plugin may briefly restart the backend (you might see a
            temporary disconnect). Please wait a few seconds and the app will
            reconnect automatically.
          </Alert>
          <Dropzone
            onDrop={(files) => files[0] && setImportFile(files[0])}
            onReject={() => {}}
            maxFiles={1}
            accept={[
              'application/zip',
              'application/x-zip-compressed',
              'application/octet-stream',
            ]}
            multiple={false}
          >
            <Group justify="center" mih={80}>
              <Text size="sm">Drag and drop plugin .zip here</Text>
            </Group>
          </Dropzone>
          <FileInput
            placeholder="Select plugin .zip"
            value={importFile}
            onChange={setImportFile}
            accept=".zip"
            clearable
          />
          <Group justify="flex-end">
            <Button
              variant="default"
              onClick={() => setImportOpen(false)}
              size="xs"
            >
              Close
            </Button>
            <Button
              size="xs"
              loading={importing}
              disabled={!importFile}
              onClick={async () => {
                setImporting(true);
                const id = notifications.show({
                  title: 'Uploading plugin',
                  message: 'Backend may restart; please wait…',
                  loading: true,
                  autoClose: false,
                  withCloseButton: false,
                });
                setUploadNoticeId(id);
                try {
                  const resp = await API.importPlugin(importFile);
                  if (resp?.success && resp.plugin) {
                    setImported(resp.plugin);
                    setPlugins((prev) => [
                      resp.plugin,
                      ...prev.filter((p) => p.key !== resp.plugin.key),
                    ]);
                    notifications.update({
                      id,
                      loading: false,
                      color: 'green',
                      title: 'Imported',
                      message:
                        'Plugin imported. If the app briefly disconnected, it should be back now.',
                      autoClose: 3000,
                    });
                  } else {
                    notifications.update({
                      id,
                      loading: false,
                      color: 'red',
                      title: 'Import failed',
                      message: resp?.error || 'Unknown error',
                      autoClose: 5000,
                    });
                  }
                } catch (e) {
                  // API.importPlugin already showed a concise error; just update the loading notice
                  notifications.update({
                    id,
                    loading: false,
                    color: 'red',
                    title: 'Import failed',
                    message:
                      (e?.body && (e.body.error || e.body.detail)) ||
                      e?.message ||
                      'Failed',
                    autoClose: 5000,
                  });
                } finally {
                  setImporting(false);
                  setUploadNoticeId(null);
                }
              }}
            >
              Upload
            </Button>
          </Group>
          {imported && (
            <Box>
              <Divider my="sm" />
              <Text fw={600}>{imported.name}</Text>
              <Text size="sm" c="dimmed">
                {imported.description}
              </Text>
              <Group justify="space-between" mt="sm" align="center">
                <Text size="sm">Enable now</Text>
                <Switch
                  size="sm"
                  checked={enableAfterImport}
                  onChange={(e) =>
                    setEnableAfterImport(e.currentTarget.checked)
                  }
                />
              </Group>
              <Group justify="flex-end" mt="md">
                <Button
                  variant="default"
                  size="xs"
                  onClick={() => {
                    setImportOpen(false);
                    setImported(null);
                    setImportFile(null);
                    setEnableAfterImport(false);
                  }}
                >
                  Done
                </Button>
                <Button
                  size="xs"
                  disabled={!enableAfterImport}
                  onClick={async () => {
                    if (!imported) return;
                    let proceed = true;
                    if (!imported.ever_enabled) {
                      proceed = await requireTrust(imported);
                    }
                    if (proceed) {
                      const resp = await API.setPluginEnabled(
                        imported.key,
                        true
                      );
                      if (resp?.success) {
                        setPlugins((prev) =>
                          prev.map((p) =>
                            p.key === imported.key
                              ? { ...p, enabled: true, ever_enabled: true }
                              : p
                          )
                        );
                        notifications.show({
                          title: imported.name,
                          message: 'Plugin enabled',
                          color: 'green',
                        });
                      }
                      setImportOpen(false);
                      setImported(null);
                      setEnableAfterImport(false);
                    }
                  }}
                >
                  Enable
                </Button>
              </Group>
            </Box>
          )}
        </Stack>
      </Modal>

      {/* Trust Warning Modal */}
      <Modal
        opened={trustOpen}
        onClose={() => {
          setTrustOpen(false);
          trustResolve && trustResolve(false);
        }}
        title="Enable third-party plugins?"
        centered
      >
        <Stack>
          <Text size="sm">
            Plugins run server-side code with full access to your Dispatcharr
            instance and its data. Only enable plugins from developers you
            trust.
          </Text>
          <Text size="sm" c="dimmed">
            Why: Malicious plugins could read or modify data, call internal
            APIs, or perform unwanted actions. Review the source or trust the
            author before enabling.
          </Text>
          <Group justify="flex-end">
            <Button
              variant="default"
              size="xs"
              onClick={() => {
                setTrustOpen(false);
                trustResolve && trustResolve(false);
              }}
            >
              Cancel
            </Button>
            <Button
              size="xs"
              color="red"
              onClick={() => {
                setTrustOpen(false);
                trustResolve && trustResolve(true);
              }}
            >
              I understand, enable
            </Button>
          </Group>
        </Stack>
      </Modal>

      {/* Delete Plugin Modal */}
      <Modal
        opened={deleteOpen}
        onClose={() => {
          setDeleteOpen(false);
          setDeleteTarget(null);
        }}
        title={deleteTarget ? `Delete ${deleteTarget.name}?` : 'Delete Plugin'}
        centered
      >
        <Stack>
          <Text size="sm">
            This will remove the plugin files and its configuration. This action
            cannot be undone.
          </Text>
          <Group justify="flex-end">
            <Button
              variant="default"
              size="xs"
              onClick={() => {
                setDeleteOpen(false);
                setDeleteTarget(null);
              }}
            >
              Cancel
            </Button>
            <Button
              size="xs"
              color="red"
              loading={deleting}
              onClick={async () => {
                if (!deleteTarget) return;
                setDeleting(true);
                try {
                  const resp = await API.deletePlugin(deleteTarget.key);
                  if (resp?.success) {
                    setPlugins((prev) =>
                      prev.filter((p) => p.key !== deleteTarget.key)
                    );
                    notifications.show({
                      title: deleteTarget.name,
                      message: 'Plugin deleted',
                      color: 'green',
                    });
                  }
                  setDeleteOpen(false);
                  setDeleteTarget(null);
                } finally {
                  setDeleting(false);
                }
              }}
            >
              Delete
            </Button>
          </Group>
        </Stack>
      </Modal>
    </AppShell.Main>
  );
}
