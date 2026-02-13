import React, { useMemo } from 'react';
import { Box, Button, Group, SimpleGrid, Stack, Text, Title } from '@mantine/core';
import { Plus } from 'lucide-react';
import { notifications } from '@mantine/notifications';
import { useNavigate } from 'react-router-dom';

import LibraryCard from '../components/library/LibraryCard';
import LibraryFormModal from '../components/library/LibraryFormModal';
import LibraryScanDrawer from '../components/library/LibraryScanDrawer';
import ConfirmationDialog from '../components/ConfirmationDialog';
import useLibraryManagement from '../hooks/useLibraryManagement';

const LibrariesPage = () => {
  const navigate = useNavigate();
  const {
    visibleLibraries,
    selectedLibraryId,
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
    notify: notifications.show,
  });

  const visibleLibraryIds = useMemo(
    () => visibleLibraries.map((library) => library.id),
    [visibleLibraries]
  );

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
                onSelect={() => handleBrowse(library)}
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
    </Box>
  );
};

export default LibrariesPage;
