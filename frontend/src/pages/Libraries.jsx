import React, { useEffect, useMemo, useState } from 'react';
import { Box, Button, Group, SimpleGrid, Stack, Text, Title } from '@mantine/core';
import { Plus } from 'lucide-react';
import { notifications } from '@mantine/notifications';
import { useNavigate } from 'react-router-dom';

import useLibraryStore from '../store/library';
import LibraryCard from '../components/library/LibraryCard';
import LibraryFormModal from '../components/library/LibraryFormModal';
import LibraryScanDrawer from '../components/library/LibraryScanDrawer';

const LibrariesPage = () => {
  const navigate = useNavigate();
  const libraries = useLibraryStore((s) => s.libraries);
  const fetchLibraries = useLibraryStore((s) => s.fetchLibraries);
  const createLibrary = useLibraryStore((s) => s.createLibrary);
  const updateLibrary = useLibraryStore((s) => s.updateLibrary);
  const deleteLibrary = useLibraryStore((s) => s.deleteLibrary);
  const triggerScan = useLibraryStore((s) => s.triggerScan);
  const fetchScans = useLibraryStore((s) => s.fetchScans);
  const upsertScan = useLibraryStore((s) => s.upsertScan);
  const removeScan = useLibraryStore((s) => s.removeScan);
  const cancelLibraryScan = useLibraryStore((s) => s.cancelLibraryScan);
  const deleteLibraryScan = useLibraryStore((s) => s.deleteLibraryScan);

  const [selectedLibraryId, setSelectedLibraryId] = useState(null);
  const [formOpen, setFormOpen] = useState(false);
  const [editingLibrary, setEditingLibrary] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [scanDrawerOpen, setScanDrawerOpen] = useState(false);
  const [scanLoadingId, setScanLoadingId] = useState(null);

  useEffect(() => {
    fetchLibraries();
  }, [fetchLibraries]);

  const selectedLibrary = useMemo(
    () => libraries.find((lib) => lib.id === selectedLibraryId) || null,
    [libraries, selectedLibraryId]
  );

  const openCreateModal = () => {
    setEditingLibrary(null);
    setFormOpen(true);
  };

  const openEditModal = (library) => {
    setEditingLibrary(library);
    setFormOpen(true);
  };

  const handleSubmit = async (payload) => {
    setSubmitting(true);
    try {
      if (editingLibrary) {
        const updated = await updateLibrary(editingLibrary.id, payload);
        if (updated) {
          notifications.show({
            title: 'Library updated',
            message: `${updated.name} saved successfully.`,
            color: 'green',
          });
        }
      } else {
        const created = await createLibrary(payload);
        if (created) {
          notifications.show({
            title: 'Library created',
            message: `${created.name} added.`,
            color: 'green',
          });
        }
      }
      setFormOpen(false);
    } catch (error) {
      console.error(error);
    } finally {
      setSubmitting(false);
    }
  };

  const handleDelete = async (library) => {
    if (!window.confirm(`Delete ${library.name}? This will remove the library and related VOD items.`)) {
      return;
    }
    const success = await deleteLibrary(library.id);
    if (success) {
      notifications.show({
        title: 'Library deleted',
        message: `${library.name} removed.`,
        color: 'red',
      });
      if (selectedLibraryId === library.id) {
        setSelectedLibraryId(null);
      }
    }
  };

  const handleScan = async (libraryId, full = false) => {
    setSelectedLibraryId(libraryId);
    setScanLoadingId(libraryId);
    try {
      const scan = await triggerScan(libraryId, { full });
      if (scan) {
        upsertScan(scan);
        setScanDrawerOpen(true);
        notifications.show({
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

  const handleCancelScan = async (scanId) => {
    try {
      const updated = await cancelLibraryScan(scanId);
      if (updated) {
        upsertScan(updated);
      }
    } catch (error) {
      console.error(error);
    }
  };

  const handleDeleteQueuedScan = async (scanId) => {
    try {
      const success = await deleteLibraryScan(scanId);
      if (success) {
        removeScan(scanId);
      }
    } catch (error) {
      console.error(error);
    }
  };

  const handleBrowse = (library) => {
    const target = library.library_type === 'shows' ? 'shows' : 'movies';
    navigate(`/library/${target}`);
  };

  return (
    <Box p="lg">
      <Stack spacing="xl">
        <Group justify="space-between" align="center">
          <Stack spacing={4}>
            <Title order={2}>Libraries</Title>
            <Text size="sm" c="dimmed">
              Manage your movie and TV show libraries.
            </Text>
          </Stack>
          <Button leftSection={<Plus size={16} />} onClick={openCreateModal}>
            Add Library
          </Button>
        </Group>

        {libraries.length === 0 ? (
          <Text c="dimmed">No libraries configured yet.</Text>
        ) : (
          <SimpleGrid cols={{ base: 1, md: 2, lg: 3 }} spacing="lg">
            {libraries.map((library) => (
              <LibraryCard
                key={library.id}
                library={library}
                selected={selectedLibraryId === library.id}
                onSelect={() => handleBrowse(library)}
                onEdit={openEditModal}
                onDelete={handleDelete}
                onScan={(id) => handleScan(id, false)}
                loadingScan={scanLoadingId === library.id}
              />
            ))}
          </SimpleGrid>
        )}
      </Stack>

      <LibraryFormModal
        opened={formOpen}
        onClose={() => setFormOpen(false)}
        library={editingLibrary}
        onSubmit={handleSubmit}
        submitting={submitting}
      />

      <LibraryScanDrawer
        opened={scanDrawerOpen && Boolean(selectedLibraryId)}
        onClose={() => setScanDrawerOpen(false)}
        libraryId={selectedLibraryId}
        onCancelJob={handleCancelScan}
        onDeleteQueuedJob={handleDeleteQueuedScan}
        onStartScan={() => handleScan(selectedLibraryId, false)}
        onStartFullScan={() => handleScan(selectedLibraryId, true)}
      />
    </Box>
  );
};

export default LibrariesPage;
