import React, {
  Suspense,
  useCallback,
  useEffect,
  useRef,
  useState,
} from 'react';
import {
  ActionIcon,
  Alert,
  AppShellMain,
  Box,
  Button,
  Divider,
  FileInput,
  Group,
  Loader,
  Modal,
  SimpleGrid,
  Stack,
  Switch,
  Text,
} from '@mantine/core';
import { Dropzone } from '@mantine/dropzone';
import {
  showNotification,
  updateNotification,
} from '../utils/notificationUtils.js';
import { usePluginStore } from '../store/plugins.jsx';
import {
  deletePluginByKey,
  importPlugin,
  reloadPlugins,
  runPluginAction,
  setPluginEnabled,
  updatePluginSettings,
} from '../utils/pages/PluginsUtils.js';
import { RefreshCcw } from 'lucide-react';
import ErrorBoundary from '../components/ErrorBoundary.jsx';
const PluginCard = React.lazy(
  () => import('../components/cards/PluginCard.jsx')
);

const PluginsList = ({ onRequestDelete, onRequireTrust, onRequestConfirm }) => {
  const plugins = usePluginStore((state) => state.plugins);
  const loading = usePluginStore((state) => state.loading);
  const hasFetchedRef = useRef(false);

  useEffect(() => {
    if (!hasFetchedRef.current) {
      hasFetchedRef.current = true;
      usePluginStore.getState().fetchPlugins();
    }
  }, []);

  const handleTogglePluginEnabled = async (key, next) => {
    const resp = await setPluginEnabled(key, next);

    if (resp?.success) {
      const updates = resp?.plugin || {
        enabled: next,
        ever_enabled: resp?.ever_enabled,
      };
      usePluginStore.getState().updatePlugin(key, updates);
    }
    return resp;
  };

  if (loading && plugins.length === 0) {
    return <Loader />;
  }

  return (
    <>
      {plugins.length > 0 && (
        <SimpleGrid
          cols={2}
          spacing="md"
          breakpoints={[{ maxWidth: '48em', cols: 1 }]}
        >
          <ErrorBoundary>
            <Suspense fallback={<Loader />}>
              {plugins.map((p) => (
                <PluginCard
                  key={p.key}
                  plugin={p}
                  onSaveSettings={updatePluginSettings}
                  onRunAction={runPluginAction}
                  onToggleEnabled={handleTogglePluginEnabled}
                  onRequireTrust={onRequireTrust}
                  onRequestDelete={onRequestDelete}
                  onRequestConfirm={onRequestConfirm}
                />
              ))}
            </Suspense>
          </ErrorBoundary>
        </SimpleGrid>
      )}

      {plugins.length === 0 && (
        <Box>
          <Text c="dimmed">
            No plugins found. Drop a plugin into <code>/data/plugins</code> and
            reload.
          </Text>
        </Box>
      )}
    </>
  );
};

export default function PluginsPage() {
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
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [confirmConfig, setConfirmConfig] = useState({
    title: '',
    message: '',
    resolve: null,
  });

  const handleReload = async () => {
    const { repos, refreshRepo, fetchAvailablePlugins } = usePluginStore.getState();
    for (const repo of repos) {
      try { await refreshRepo(repo.id); } catch {}
    }
    await fetchAvailablePlugins();
    await reloadPlugins();
    usePluginStore.getState().invalidatePlugins();
  };

  const handleRequestDelete = useCallback((pl) => {
    setDeleteTarget(pl);
    setDeleteOpen(true);
  }, []);

  const requireTrust = useCallback((plugin) => {
    return new Promise((resolve) => {
      setTrustResolve(() => resolve);
      setTrustOpen(true);
    });
  }, []);

  const showImportForm = useCallback(() => {
    setImportOpen(true);
    setImported(null);
    setImportFile(null);
    setEnableAfterImport(false);
  }, []);

  const requestConfirm = useCallback((title, message) => {
    return new Promise((resolve) => {
      setConfirmConfig({ title, message, resolve });
      setConfirmOpen(true);
    });
  }, []);

  const handleImportPlugin = () => {
    return async () => {
      const run = async (overwrite) => {
        setImporting(true);
        const notifId = showNotification({
          title: 'Uploading plugin',
          message: 'Backend may restart; please wait…',
          loading: true,
          autoClose: false,
          withCloseButton: false,
        });
        try {
          const resp = await importPlugin(importFile, overwrite, /* silent */ true);
          if (resp?.success && resp.plugin) {
            setImported({ ...resp.plugin, was_managed: resp.was_managed });
            usePluginStore.getState().invalidatePlugins();
            updateNotification({
              id: notifId,
              loading: false,
              color: 'green',
              title: 'Imported',
              message:
                'Plugin imported. If the app briefly disconnected, it should be back now.',
              autoClose: 3000,
            });
          } else {
            updateNotification({
              id: notifId,
              loading: false,
              color: 'red',
              title: 'Import failed',
              message: resp?.error || 'Unknown error',
              autoClose: 5000,
            });
          }
        } catch (e) {
          const msg =
            (e?.body && (e.body.error || e.body.detail)) || e?.message || '';
          if (!overwrite && /already exists/i.test(msg)) {
            // Dismiss the loading toast before showing the confirm dialog
            updateNotification({
              id: notifId,
              loading: false,
              autoClose: 100,
              withCloseButton: false,
            });
            const pluginName = msg.match(/'([^']+)'/)?.[1] || 'this plugin';
            const confirmed = await requestConfirm(
              'Plugin already exists',
              `'${pluginName}' is already installed. Do you want to replace it?`
            );
            if (confirmed) {
              await run(true);
            }
          } else {
            updateNotification({
              id: notifId,
              loading: false,
              color: 'red',
              title: 'Import failed',
              message: msg || 'Failed',
              autoClose: 5000,
            });
          }
        } finally {
          setImporting(false);
        }
      };
      await run(false);
    };
  };

  const handleEnablePlugin = () => {
    return async () => {
      if (!imported) return;

      const proceed = imported.ever_enabled || (await requireTrust(imported));
      if (proceed) {
        const resp = await setPluginEnabled(imported.key, true);
        if (resp?.success) {
          const updates = resp?.plugin || { enabled: true, ever_enabled: true };
          usePluginStore.getState().updatePlugin(imported.key, updates);

          showNotification({
            title: imported.name,
            message: 'Plugin enabled',
            color: 'green',
          });
        }
        setImportOpen(false);
        setImported(null);
        setEnableAfterImport(false);
      }
    };
  };

  const handleDeletePlugin = () => {
    return async () => {
      if (!deleteTarget) return;
      setDeleting(true);
      try {
        const resp = await deletePluginByKey(deleteTarget.key);
        if (resp?.success) {
          usePluginStore.getState().removePlugin(deleteTarget.key);

          showNotification({
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
    };
  };

  const handleConfirm = useCallback(
    (confirmed) => {
      const resolver = confirmConfig.resolve;
      setConfirmOpen(false);
      setConfirmConfig({ title: '', message: '', resolve: null });
      if (resolver) resolver(confirmed);
    },
    [confirmConfig.resolve]
  );

  return (
    <AppShellMain p={16}>
      <Group justify="space-between" mb="md">
        <Text fw={700} size="lg">
          My Plugins
        </Text>
        <Group>
          <Button size="xs" variant="light" onClick={showImportForm}>
            Import Plugin
          </Button>
          <ActionIcon variant="light" onClick={handleReload} title="Reload">
            <RefreshCcw size={18} />
          </ActionIcon>
        </Group>
      </Group>

      <PluginsList
        onRequestDelete={handleRequestDelete}
        onRequireTrust={requireTrust}
        onRequestConfirm={requestConfirm}
      />

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
              onClick={handleImportPlugin()}
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
              {imported.was_managed && (
                <Alert color="orange" variant="light" mt="xs">
                  This plugin was previously managed by a repo. Manual
                  installation removes it from repo management, so it will no
                  longer receive update checks or version tracking.
                </Alert>
              )}
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
                  onClick={handleEnablePlugin()}
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
              onClick={handleDeletePlugin()}
            >
              Delete
            </Button>
          </Group>
        </Stack>
      </Modal>

      {/* Confirmation modal */}
      <Modal
        opened={confirmOpen}
        onClose={() => handleConfirm(false)}
        title={confirmConfig.title}
        centered
      >
        <Stack>
          <Text size="sm">{confirmConfig.message}</Text>
          <Group justify="flex-end">
            <Button
              variant="default"
              size="xs"
              onClick={() => handleConfirm(false)}
            >
              Cancel
            </Button>
            <Button size="xs" onClick={() => handleConfirm(true)}>
              Confirm
            </Button>
          </Group>
        </Stack>
      </Modal>
    </AppShellMain>
  );
}
