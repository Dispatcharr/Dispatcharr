import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
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
  Divider,
  ActionIcon,
  SimpleGrid,
  Modal,
  FileInput,
  Image,
  Badge,
  ThemeIcon,
  Center,
} from '@mantine/core';
import { Dropzone } from '@mantine/dropzone';
import { RefreshCcw, Trash2, Settings, PlugZap } from 'lucide-react';
import API from '../api';
import { notifications } from '@mantine/notifications';

const PluginCard = ({
  plugin,
  onRunAction,
  onToggleEnabled,
  onRequireTrust,
  onRequestDelete,
}) => {
  const navigate = useNavigate();
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

  const missing = plugin.missing;
  return (
    <Card
      shadow="sm"
      radius="md"
      withBorder
      padding="lg"
      style={{ opacity: !missing && enabled ? 1 : 0.6 }}
    >
      <Card.Section>
        {/* Plugin logo or dark theme-compatible placeholder */}
        {plugin.logo ? (
          <Image
            src={plugin.logo}
            height={160}
            alt={`${plugin.name} logo`}
          />
        ) : (
          <Center
            style={{
              height: 160,
              background: 'linear-gradient(135deg, #1e293b 0%, #0f172a 100%)',
              borderBottom: '1px solid #2A2A2E',
            }}
          >
            <ThemeIcon
              size={80}
              radius="xl"
              variant="light"
              color="dark"
              style={{
                backgroundColor: 'rgba(100, 116, 139, 0.1)',
                border: '2px solid rgba(100, 116, 139, 0.2)',
              }}
            >
              <PlugZap size={48} color="#64748b" />
            </ThemeIcon>
          </Center>
        )}
      </Card.Section>

      <Stack gap="sm" mt="md">
        {/* Plugin name and version */}
        <Group justify="space-between" align="flex-start">
          <div style={{ flex: 1 }}>
            <Text fw={600} size="lg">{plugin.name}</Text>
            <Badge size="sm" variant="light" mt={4}>
              v{plugin.version || '1.0.0'}
            </Badge>
          </div>
          <Group gap="xs">
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
              size="sm"
              onLabel="On"
              offLabel="Off"
              disabled={missing}
            />
          </Group>
        </Group>

        {/* Plugin description */}
        <Text size="sm" c="dimmed">
          {plugin.description}
        </Text>

        {missing && (
          <Text size="sm" c="red" fw={500}>
            Missing plugin files. Re-import or delete this entry.
          </Text>
        )}

        {/* Action buttons */}
        <Group gap="xs" mt="xs">
          {/* Settings Button */}
          {!missing && enabled && plugin.fields && plugin.fields.length > 0 && (
            <Button
              variant="light"
              size="xs"
              leftSection={<Settings size={14} />}
              onClick={() => navigate('/settings')}
            >
              Settings
            </Button>
          )}

          {/* Delete Button */}
          <Button
            variant="subtle"
            color="red"
            size="xs"
            leftSection={<Trash2 size={14} />}
            onClick={() => onRequestDelete && onRequestDelete(plugin)}
          >
            Delete
          </Button>
        </Group>
      </Stack>

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
