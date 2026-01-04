import React, { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Anchor,
  Button,
  Center,
  Divider,
  Group,
  List,
  Modal,
  SimpleGrid,
  Stack,
  Switch,
  Text,
  TextInput,
  Title,
} from '@mantine/core';
import { Plus } from 'lucide-react';

import useSettingsStore from '../../../store/settings.jsx';
import useLibraryStore from '../../../store/library.jsx';
import {
  createSetting,
  updateSetting,
} from '../../../utils/pages/SettingsUtils.js';
import { showNotification } from '../../../utils/notificationUtils.js';
import LibraryCard from '../../library/LibraryCard.jsx';
import LibraryFormModal from '../../library/LibraryFormModal.jsx';
import LibraryScanDrawer from '../../library/LibraryScanDrawer.jsx';
import ConfirmationDialog from '../../ConfirmationDialog.jsx';
import tmdbLogoUrl from '../../../assets/tmdb-logo-blue.svg?url';

const MediaLibrarySettingsForm = React.memo(({ active }) => {
  const settings = useSettingsStore((s) => s.settings);
  const navigate = useNavigate();
  const libraries = useLibraryStore((s) => s.libraries);
  const fetchLibraries = useLibraryStore((s) => s.fetchLibraries);
  const createLibrary = useLibraryStore((s) => s.createLibrary);
  const updateLibrary = useLibraryStore((s) => s.updateLibrary);
  const deleteLibrary = useLibraryStore((s) => s.deleteLibrary);
  const triggerScan = useLibraryStore((s) => s.triggerScan);
  const upsertScan = useLibraryStore((s) => s.upsertScan);
  const removeScan = useLibraryStore((s) => s.removeScan);
  const cancelLibraryScan = useLibraryStore((s) => s.cancelLibraryScan);
  const deleteLibraryScan = useLibraryStore((s) => s.deleteLibraryScan);

  const tmdbSetting = settings['tmdb-api-key'];
  const preferLocalSetting = settings['prefer-local-metadata'];

  const [tmdbKey, setTmdbKey] = useState('');
  const [preferLocalMetadata, setPreferLocalMetadata] = useState(false);
  const [savingMetadataSettings, setSavingMetadataSettings] = useState(false);
  const [tmdbHelpOpen, setTmdbHelpOpen] = useState(false);

  const [selectedLibraryId, setSelectedLibraryId] = useState(null);
  const [libraryFormOpen, setLibraryFormOpen] = useState(false);
  const [editingLibrary, setEditingLibrary] = useState(null);
  const [librarySubmitting, setLibrarySubmitting] = useState(false);
  const [scanDrawerOpen, setScanDrawerOpen] = useState(false);
  const [scanLoadingId, setScanLoadingId] = useState(null);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [pendingDeleteIds, setPendingDeleteIds] = useState(() => new Set());

  useEffect(() => {
    if (active) {
      fetchLibraries();
    }
  }, [active, fetchLibraries]);

  useEffect(() => {
    const currentKey = tmdbSetting?.value ?? '';
    setTmdbKey(currentKey);
    const preferValue = preferLocalSetting?.value;
    const normalized = String(preferValue ?? '').toLowerCase();
    setPreferLocalMetadata(['1', 'true', 'yes', 'on'].includes(normalized));
  }, [tmdbSetting?.value, preferLocalSetting?.value]);

  useEffect(() => {
    setPendingDeleteIds((prev) => {
      if (!prev.size) return prev;
      const activeIds = new Set(libraries.map((library) => library.id));
      let changed = false;
      const next = new Set();
      prev.forEach((id) => {
        if (activeIds.has(id)) {
          next.add(id);
        } else {
          changed = true;
        }
      });
      return changed ? next : prev;
    });
  }, [libraries]);

  const visibleLibraries = useMemo(
    () => libraries.filter((library) => !pendingDeleteIds.has(library.id)),
    [libraries, pendingDeleteIds]
  );

  const handleSaveMetadataSettings = async () => {
    setSavingMetadataSettings(true);
    try {
      const tasks = [];
      const preferValue = preferLocalMetadata ? 'true' : 'false';
      if (preferLocalSetting?.id) {
        tasks.push(
          updateSetting({ ...preferLocalSetting, value: preferValue })
        );
      } else {
        tasks.push(
          createSetting({
            key: 'prefer-local-metadata',
            name: 'Prefer Local Metadata',
            value: preferValue,
          })
        );
      }

      const trimmedKey = (tmdbKey || '').trim();
      if (tmdbSetting?.id) {
        tasks.push(updateSetting({ ...tmdbSetting, value: trimmedKey }));
      } else if (trimmedKey) {
        tasks.push(
          createSetting({
            key: 'tmdb-api-key',
            name: 'TMDB API Key',
            value: trimmedKey,
          })
        );
      }

      const results = await Promise.all(tasks);
      if (results.some((result) => !result)) {
        throw new Error('Failed to save metadata settings');
      }
      showNotification({
        title: 'Metadata settings saved',
        message: 'Metadata preferences updated successfully.',
        color: 'green',
      });
    } catch (error) {
      console.error('Failed to save metadata settings', error);
      showNotification({
        title: 'Error',
        message: 'Unable to save metadata settings.',
        color: 'red',
      });
    } finally {
      setSavingMetadataSettings(false);
    }
  };

  const openCreateLibraryModal = () => {
    setEditingLibrary(null);
    setLibraryFormOpen(true);
  };

  const openEditLibraryModal = (library) => {
    setEditingLibrary(library);
    setLibraryFormOpen(true);
  };

  const handleLibrarySubmit = async (payload) => {
    setLibrarySubmitting(true);
    try {
      if (editingLibrary) {
        const updated = await updateLibrary(editingLibrary.id, payload);
        if (updated) {
          showNotification({
            title: 'Library updated',
            message: `${updated.name} saved successfully.`,
            color: 'green',
          });
        }
      } else {
        const created = await createLibrary(payload);
        if (created) {
          showNotification({
            title: 'Library created',
            message: `${created.name} added.`,
            color: 'green',
          });
        }
      }
      setLibraryFormOpen(false);
    } catch (error) {
      console.error(error);
    } finally {
      setLibrarySubmitting(false);
    }
  };

  const handleLibraryDelete = async (library) => {
    setDeleteTarget(library);
    setDeleteDialogOpen(true);
  };

  const handleDeleteConfirm = async () => {
    if (!deleteTarget) return;
    const target = deleteTarget;
    setDeleteDialogOpen(false);
    setDeleteTarget(null);
    setPendingDeleteIds((prev) => {
      const next = new Set(prev);
      next.add(target.id);
      return next;
    });
    if (selectedLibraryId === target.id) {
      setSelectedLibraryId(null);
      setScanDrawerOpen(false);
    }

    const success = await deleteLibrary(target.id);
    if (success) {
      showNotification({
        title: 'Library deleted',
        message: `${target.name} removed.`,
        color: 'red',
      });
      setPendingDeleteIds((prev) => {
        const next = new Set(prev);
        next.delete(target.id);
        return next;
      });
    } else {
      showNotification({
        title: 'Unable to delete library',
        message: `Failed to delete ${target.name}.`,
        color: 'red',
      });
      setPendingDeleteIds((prev) => {
        const next = new Set(prev);
        next.delete(target.id);
        return next;
      });
    }
  };

  const handleLibraryScan = async (libraryId, full = false) => {
    setSelectedLibraryId(libraryId);
    setScanLoadingId(libraryId);
    try {
      const scan = await triggerScan(libraryId, { full });
      if (scan) {
        upsertScan(scan);
        setScanDrawerOpen(true);
        showNotification({
          title: full ? 'Full scan started' : 'Scan started',
          message: 'The library scan has been queued.',
          color: 'blue',
        });
      }
    } catch (error) {
      console.error(error);
    } finally {
      setScanLoadingId(null);
    }
  };

  const handleCancelLibraryScan = async (scanId) => {
    try {
      const updated = await cancelLibraryScan(scanId);
      if (updated) {
        upsertScan(updated);
      }
    } catch (error) {
      console.error(error);
    }
  };

  const handleDeleteQueuedLibraryScan = async (scanId) => {
    try {
      const success = await deleteLibraryScan(scanId);
      if (success) {
        removeScan(scanId);
      }
    } catch (error) {
      console.error(error);
    }
  };

  const handleBrowseLibrary = (library) => {
    const target = library.library_type === 'shows' ? 'shows' : 'movies';
    setSelectedLibraryId(library.id);
    navigate(`/library/${target}`);
  };

  return (
    <>
      <Stack gap="xl">
        <Stack gap="sm">
          <Group justify="space-between" align="flex-start">
            <Stack gap={4}>
              <Title order={4}>Metadata Sources</Title>
              <Text size="sm" c="dimmed">
                Prefer local NFO metadata, then fill missing fields from TMDB.
              </Text>
            </Stack>
          </Group>
          <Switch
            label="Prefer local metadata (.nfo files)"
            description="Use NFO data first and fill missing fields from TMDB."
            checked={preferLocalMetadata}
            onChange={(event) =>
              setPreferLocalMetadata(event.currentTarget.checked)
            }
          />
          <TextInput
            label="TMDB API Key"
            placeholder="Enter TMDB API key"
            value={tmdbKey}
            onChange={(event) => setTmdbKey(event.currentTarget.value)}
            description="Used for metadata and artwork lookups."
          />
          <Group justify="space-between" align="center">
            <Button
              variant="subtle"
              size="xs"
              onClick={() => setTmdbHelpOpen(true)}
            >
              Where do I get this?
            </Button>
            <Button
              size="xs"
              variant="light"
              onClick={handleSaveMetadataSettings}
              loading={savingMetadataSettings}
            >
              Save Metadata Settings
            </Button>
          </Group>
          <Center>
            <Anchor
              href="https://www.themoviedb.org/"
              target="_blank"
              rel="noopener noreferrer"
            >
              <img
                src={tmdbLogoUrl}
                alt="TMDB logo"
                style={{
                  width: 140,
                  height: 'auto',
                  display: 'block',
                }}
              />
            </Anchor>
          </Center>
        </Stack>

        <Divider />

        <Group justify="space-between" align="center">
          <Stack gap={4}>
            <Title order={4}>Libraries</Title>
            <Text size="sm" c="dimmed">
              Manage your movie and TV show libraries.
            </Text>
          </Stack>
          <Button leftSection={<Plus size={16} />} onClick={openCreateLibraryModal}>
            Add Library
          </Button>
        </Group>

        {visibleLibraries.length === 0 ? (
          <Text c="dimmed">No libraries configured yet.</Text>
        ) : (
          <SimpleGrid cols={{ base: 1, md: 2, lg: 3 }} spacing="lg">
            {visibleLibraries.map((library) => (
              <LibraryCard
                key={library.id}
                library={library}
                selected={selectedLibraryId === library.id}
                onSelect={() => handleBrowseLibrary(library)}
                onEdit={openEditLibraryModal}
                onDelete={handleLibraryDelete}
                onScan={(id) => handleLibraryScan(id, false)}
                loadingScan={scanLoadingId === library.id}
              />
            ))}
          </SimpleGrid>
        )}
      </Stack>

      <LibraryFormModal
        opened={libraryFormOpen}
        onClose={() => setLibraryFormOpen(false)}
        library={editingLibrary}
        onSubmit={handleLibrarySubmit}
        submitting={librarySubmitting}
      />

      <LibraryScanDrawer
        opened={scanDrawerOpen && Boolean(selectedLibraryId)}
        onClose={() => setScanDrawerOpen(false)}
        libraryId={selectedLibraryId}
        onCancelJob={handleCancelLibraryScan}
        onDeleteQueuedJob={handleDeleteQueuedLibraryScan}
        onStartScan={() => handleLibraryScan(selectedLibraryId, false)}
        onStartFullScan={() => handleLibraryScan(selectedLibraryId, true)}
      />

      <ConfirmationDialog
        opened={deleteDialogOpen}
        onClose={() => {
          setDeleteDialogOpen(false);
          setDeleteTarget(null);
        }}
        onConfirm={handleDeleteConfirm}
        title="Delete library"
        message={
          deleteTarget ? (
            <div style={{ whiteSpace: 'pre-line' }}>
              {`Delete ${deleteTarget.name}?

This will remove the library and related VOD items.`}
            </div>
          ) : (
            'Delete this library? This will remove the library and related VOD items.'
          )
        }
        confirmLabel="Delete"
        cancelLabel="Cancel"
        size="md"
      />

      <Modal
        opened={tmdbHelpOpen}
        onClose={() => setTmdbHelpOpen(false)}
        title="How to get a TMDB API key"
        size="lg"
        overlayProps={{ backgroundOpacity: 0.55, blur: 2 }}
      >
        <Stack gap="sm">
          <Text size="sm">
            Dispatcharr uses TMDB (The Movie Database) for artwork and metadata.
            You can create a key in a few minutes:
          </Text>
          <List size="sm" spacing="xs">
            <List.Item>
              Visit{' '}
              <Anchor
                href="https://www.themoviedb.org/"
                target="_blank"
                rel="noopener noreferrer"
              >
                themoviedb.org
              </Anchor>{' '}
              and sign in or create a free account.
            </List.Item>
            <List.Item>
              Open your{' '}
              <Anchor
                href="https://www.themoviedb.org/settings/api"
                target="_blank"
                rel="noopener noreferrer"
              >
                TMDB account settings
              </Anchor>{' '}
              and choose <Text component="span" fw={500}>API</Text>.
            </List.Item>
            <List.Item>
              Complete the short API application and copy the v3 API key into
              the field above.
            </List.Item>
          </List>
          <Text size="sm" c="dimmed">
            TMDB issues separate v3 and v4 keys. Dispatcharr only needs the v3
            API key for metadata lookups.
          </Text>
        </Stack>
      </Modal>
    </>
  );
});

export default MediaLibrarySettingsForm;
