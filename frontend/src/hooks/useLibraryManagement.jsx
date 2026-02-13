import { useCallback, useEffect, useMemo, useState } from 'react';

import useLibraryStore from '../store/library';

const noop = () => {};

const useLibraryManagement = ({ enabled = true, notify = noop } = {}) => {
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
    if (!enabled) return;
    fetchLibraries();
  }, [enabled, fetchLibraries]);

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

  const openCreateLibraryModal = useCallback(() => {
    setEditingLibrary(null);
    setLibraryFormOpen(true);
  }, []);

  const openEditLibraryModal = useCallback((library) => {
    setEditingLibrary(library);
    setLibraryFormOpen(true);
  }, []);

  const closeLibraryForm = useCallback(() => {
    setLibraryFormOpen(false);
  }, []);

  const handleLibrarySubmit = useCallback(
    async (payload) => {
      setLibrarySubmitting(true);
      try {
        if (editingLibrary) {
          const updated = await updateLibrary(editingLibrary.id, payload);
          if (updated) {
            notify({
              title: 'Library updated',
              message: `${updated.name} saved successfully.`,
              color: 'green',
            });
          }
        } else {
          const created = await createLibrary(payload);
          if (created) {
            notify({
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
    },
    [createLibrary, editingLibrary, notify, updateLibrary]
  );

  const requestLibraryDelete = useCallback((library) => {
    setDeleteTarget(library);
    setDeleteDialogOpen(true);
  }, []);

  const closeDeleteDialog = useCallback(() => {
    setDeleteDialogOpen(false);
    setDeleteTarget(null);
  }, []);

  const handleDeleteConfirm = useCallback(async () => {
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
      notify({
        title: 'Library deleted',
        message: `${target.name} removed.`,
        color: 'red',
      });
      setPendingDeleteIds((prev) => {
        const next = new Set(prev);
        next.delete(target.id);
        return next;
      });
      return;
    }

    notify({
      title: 'Unable to delete library',
      message: `Failed to delete ${target.name}.`,
      color: 'red',
    });
    setPendingDeleteIds((prev) => {
      const next = new Set(prev);
      next.delete(target.id);
      return next;
    });
  }, [deleteLibrary, deleteTarget, notify, selectedLibraryId]);

  const handleLibraryScan = useCallback(
    async (libraryId, full = false, options = {}) => {
      if (!libraryId) {
        return null;
      }
      setSelectedLibraryId(libraryId);
      setScanLoadingId(libraryId);
      try {
        const scan = await triggerScan(libraryId, { full });
        if (!scan) {
          return null;
        }
        upsertScan(scan);
        setScanDrawerOpen(true);
        if (!options?.suppressNotification) {
          const libraryName =
            libraries.find((library) => library.id === libraryId)?.name ||
            'selected library';
          notify({
            title: full ? 'Full scan started' : 'Scan started',
            message: full
              ? `A full scan for ${libraryName} has been queued.`
              : `A quick scan for ${libraryName} has been queued.`,
            color: 'blue',
          });
        }
        return scan;
      } catch (error) {
        console.error(error);
        if (!options?.suppressNotification) {
          notify({
            title: 'Scan failed',
            message: 'Unable to start scan at this time.',
            color: 'red',
          });
        }
        return null;
      } finally {
        setScanLoadingId(null);
      }
    },
    [libraries, notify, triggerScan, upsertScan]
  );

  const handleCancelLibraryScan = useCallback(
    async (scanId) => {
      try {
        const updated = await cancelLibraryScan(scanId);
        if (updated) {
          upsertScan(updated);
        }
      } catch (error) {
        console.error(error);
      }
    },
    [cancelLibraryScan, upsertScan]
  );

  const handleDeleteQueuedLibraryScan = useCallback(
    async (scanId) => {
      try {
        const success = await deleteLibraryScan(scanId);
        if (success) {
          removeScan(scanId);
        }
      } catch (error) {
        console.error(error);
      }
    },
    [deleteLibraryScan, removeScan]
  );

  return {
    libraries,
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
  };
};

export default useLibraryManagement;
