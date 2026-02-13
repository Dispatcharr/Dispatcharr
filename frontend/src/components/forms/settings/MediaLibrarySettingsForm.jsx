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
import {
  parseSettings,
  saveChangedSettings,
} from '../../../utils/pages/SettingsUtils.js';
import { showNotification } from '../../../utils/notificationUtils.js';
import LibraryCard from '../../library/LibraryCard.jsx';
import LibraryFormModal from '../../library/LibraryFormModal.jsx';
import LibraryScanDrawer from '../../library/LibraryScanDrawer.jsx';
import ConfirmationDialog from '../../ConfirmationDialog.jsx';
import tmdbLogoUrl from '../../../assets/tmdb-logo-blue.svg?url';
import useLibraryManagement from '../../../hooks/useLibraryManagement.jsx';

const MediaLibrarySettingsForm = React.memo(({ active }) => {
  const settings = useSettingsStore((s) => s.settings);
  const navigate = useNavigate();
  const {
    visibleLibraries,
    selectedLibraryId,
    setSelectedLibraryId,
    libraryFormOpen,
    editingLibrary,
    librarySubmitting,
    scanDrawerOpen,
    setScanDrawerOpen,
    scanLoadingId,
    deleteDialogOpen,
    deleteTarget,
    openCreateLibraryModal,
    openEditLibraryModal,
    closeLibraryForm,
    handleLibrarySubmit,
    requestLibraryDelete,
    closeDeleteDialog,
    handleDeleteConfirm,
    handleLibraryScan,
    handleCancelLibraryScan,
    handleDeleteQueuedLibraryScan,
  } = useLibraryManagement({
    enabled: active,
    notify: showNotification,
  });

  const parsedSettings = useMemo(() => parseSettings(settings), [settings]);

  const [tmdbKey, setTmdbKey] = useState('');
  const [preferLocalMetadata, setPreferLocalMetadata] = useState(false);
  const [savingMetadataSettings, setSavingMetadataSettings] = useState(false);
  const [tmdbHelpOpen, setTmdbHelpOpen] = useState(false);

  useEffect(() => {
    const currentKey = parsedSettings.tmdb_api_key ?? '';
    setTmdbKey(currentKey);
    setPreferLocalMetadata(Boolean(parsedSettings.prefer_local_metadata));
  }, [parsedSettings.tmdb_api_key, parsedSettings.prefer_local_metadata]);

  const visibleLibraryIds = useMemo(
    () => visibleLibraries.map((library) => library.id),
    [visibleLibraries]
  );

  const handleSaveMetadataSettings = async () => {
    setSavingMetadataSettings(true);
    try {
      const trimmedKey = (tmdbKey || '').trim();
      await saveChangedSettings(settings, {
        prefer_local_metadata: preferLocalMetadata,
        tmdb_api_key: trimmedKey,
      });
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
                onDelete={requestLibraryDelete}
                onScan={(id) => handleLibraryScan(id, false)}
                loadingScan={scanLoadingId === library.id}
              />
            ))}
          </SimpleGrid>
        )}
      </Stack>

      <LibraryFormModal
        opened={libraryFormOpen}
        onClose={closeLibraryForm}
        library={editingLibrary}
        onSubmit={handleLibrarySubmit}
        submitting={librarySubmitting}
      />

      <LibraryScanDrawer
        opened={scanDrawerOpen && visibleLibraries.length > 0}
        onClose={() => setScanDrawerOpen(false)}
        libraryId={selectedLibraryId || visibleLibraries[0]?.id || null}
        libraryIds={visibleLibraryIds}
        onCancelJob={handleCancelLibraryScan}
        onDeleteQueuedJob={handleDeleteQueuedLibraryScan}
        onStartScan={(targetLibraryId, options) =>
          handleLibraryScan(targetLibraryId, false, options)
        }
        onStartFullScan={(targetLibraryId, options) =>
          handleLibraryScan(targetLibraryId, true, options)
        }
      />

      <ConfirmationDialog
        opened={deleteDialogOpen}
        onClose={closeDeleteDialog}
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
