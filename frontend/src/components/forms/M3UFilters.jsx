import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  ActionIcon,
  Alert,
  Button,
  Checkbox,
  Group,
  Modal,
  ScrollArea,
  Select,
  Stack,
  Table,
  TableTbody,
  TableTd,
  TableTh,
  TableThead,
  TableTr,
  Text,
  TextInput,
} from '@mantine/core';
import {
  closestCenter,
  DndContext,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
} from '@dnd-kit/core';
import {
  arrayMove,
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import { restrictToVerticalAxis } from '@dnd-kit/modifiers';
import { Eye, GripVertical, Info, Plus, Save, Trash2 } from 'lucide-react';
import API from '../../api.js';
import ConfirmationDialog from '../ConfirmationDialog';
import useWarningsStore from '../../store/warnings';
import { M3U_FILTER_TYPES } from '../../constants';
import {
  addM3UFilter,
  deleteM3UFilter,
  updateM3UFilter,
} from '../../utils/forms/M3uFilterUtils.js';
import { showNotification } from '../../utils/notificationUtils.js';

const SortableFilterRow = ({ filterId, error, children }) => {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: filterId });

  return (
    <TableTr
      ref={setNodeRef}
      data-invalid={error ? 'true' : undefined}
      title={error || undefined}
      style={{
        transform: CSS.Transform.toString(transform),
        transition,
        opacity: isDragging ? 0.65 : 1,
        position: 'relative',
        zIndex: isDragging ? 2 : 0,
        backgroundColor: error ? 'rgba(250, 82, 82, 0.18)' : undefined,
        boxShadow: error ? 'inset 3px 0 var(--mantine-color-red-6)' : undefined,
      }}
    >
      <TableTd>
        <ActionIcon
          aria-label="Move stream filter"
          variant="subtle"
          color="gray"
          style={{ cursor: isDragging ? 'grabbing' : 'grab' }}
          {...attributes}
          {...listeners}
        >
          <GripVertical size={16} />
        </ActionIcon>
      </TableTd>
      {children}
    </TableTr>
  );
};

const M3UFilters = ({ playlist, isOpen, onClose }) => {
  const [filters, setFilters] = useState([]);
  const [savingIds, setSavingIds] = useState(new Set());
  const [confirmDeleteOpen, setConfirmDeleteOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [deleting, setDeleting] = useState(false);
  const [loading, setLoading] = useState(false);
  const [preview, setPreview] = useState(null);
  const [previewFilter, setPreviewFilter] = useState(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [filterErrors, setFilterErrors] = useState({});
  const isWarningSuppressed = useWarningsStore(
    (state) => state.isWarningSuppressed
  );
  const suppressWarning = useWarningsStore((state) => state.suppressWarning);
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates })
  );

  const loadFilters = useCallback(async () => {
    if (!playlist?.id) return;
    setLoading(true);
    try {
      setFilters((await API.getM3UFilters(playlist.id)) || []);
      setFilterErrors({});
    } finally {
      setLoading(false);
    }
  }, [playlist?.id]);

  useEffect(() => {
    if (isOpen) loadFilters();
  }, [isOpen, loadFilters]);

  const filterTypeOptions = useMemo(
    () => M3U_FILTER_TYPES.filter((option) => option.value !== 'group'),
    []
  );

  const updateLocal = (id, values) => {
    setFilters((current) =>
      current.map((filter) =>
        filter.id === id ? { ...filter, ...values } : filter
      )
    );
    setFilterErrors({});
  };

  const addFilter = () => {
    const id = `new-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
    setFilters((current) => [
      ...current,
      {
        id,
        isNew: true,
        filter_type: 'name',
        regex_pattern: '',
        exclude: true,
        order: current.length,
        custom_properties: { case_sensitive: false },
      },
    ]);
  };

  const payloadFor = (filter) => ({
    filter_type: filter.filter_type,
    regex_pattern: filter.regex_pattern,
    exclude: !!filter.exclude,
    order: filter.order,
    custom_properties: {
      ...(filter.custom_properties || {}),
      case_sensitive: !!filter.custom_properties?.case_sensitive,
    },
  });

  const getValidationErrors = () => {
    const errors = {};
    const identities = new Map();

    filters.forEach((filter) => {
      const pattern = filter.regex_pattern || '';
      if (!pattern.trim()) {
        errors[filter.id] = 'Enter a regular expression.';
        return;
      }
      try {
        new RegExp(pattern);
      } catch (error) {
        errors[filter.id] = `Invalid regular expression: ${error.message}`;
        return;
      }

      const identity = JSON.stringify([
        filter.filter_type,
        pattern,
        Boolean(filter.custom_properties?.case_sensitive),
      ]);
      const duplicateId = identities.get(identity);
      if (duplicateId !== undefined) {
        const message = 'An identical stream filter already exists.';
        errors[duplicateId] = message;
        errors[filter.id] = message;
      } else {
        identities.set(identity, filter.id);
      }
    });

    return errors;
  };

  const saveFilter = async (filter) => {
    const errors = getValidationErrors();
    setFilterErrors(errors);
    if (errors[filter.id]) {
      showNotification({
        title: 'Stream filter was not saved',
        message: errors[filter.id],
        color: 'red',
      });
      return;
    }

    setSavingIds((current) => new Set(current).add(filter.id));
    try {
      const saved = filter.isNew
        ? await addM3UFilter(playlist, payloadFor(filter))
        : await updateM3UFilter(playlist, filter, payloadFor(filter));
      if (saved) {
        setFilters((current) =>
          current.map((item) =>
            item.id === filter.id ? { ...saved, isNew: false } : item
          )
        );
      }
      await loadFilters();
      showNotification({
        title: 'Stream filter saved',
        message: 'The ordered filter is used during future Live TV scans.',
        color: 'green',
      });
    } catch (error) {
      setFilterErrors((current) => ({
        ...current,
        [filter.id]: error?.message || 'The stream filter could not be saved.',
      }));
    } finally {
      setSavingIds((current) => {
        const next = new Set(current);
        next.delete(filter.id);
        return next;
      });
    }
  };

  const deleteFilter = async (id) => {
    const filter = filters.find((item) => item.id === id);
    if (filter?.isNew) {
      setFilters((current) => current.filter((item) => item.id !== id));
      setFilterErrors({});
      setConfirmDeleteOpen(false);
      return;
    }
    setDeleting(true);
    try {
      await deleteM3UFilter(playlist, id);
      setFilters((current) => current.filter((item) => item.id !== id));
      await loadFilters();
    } finally {
      setDeleting(false);
      setConfirmDeleteOpen(false);
      setDeleteTarget(null);
    }
  };

  const requestDelete = (id) => {
    if (isWarningSuppressed('delete-filter')) {
      deleteFilter(id);
      return;
    }
    setDeleteTarget(id);
    setConfirmDeleteOpen(true);
  };

  const reorderFilters = async ({ active, over }) => {
    if (!over || active.id === over.id) return;
    const oldIndex = filters.findIndex((filter) => filter.id === active.id);
    const newIndex = filters.findIndex((filter) => filter.id === over.id);
    if (oldIndex < 0 || newIndex < 0) return;
    const previous = filters;
    const reordered = arrayMove(filters, oldIndex, newIndex).map(
      (filter, index) => ({ ...filter, order: index })
    );
    setFilters(reordered);
    try {
      await Promise.all(
        reordered
          .filter((filter) => !filter.isNew)
          .filter(
            (filter) =>
              previous.find((item) => item.id === filter.id)?.order !==
              filter.order
          )
          .map((filter) =>
            updateM3UFilter(playlist, filter, payloadFor(filter))
          )
      );
      await loadFilters();
    } catch {
      setFilters(previous);
    }
  };

  const openPreview = async (filter) => {
    setPreviewFilter(filter);
    setPreviewLoading(true);
    try {
      setPreview(
        await API.previewM3UFilter(
          playlist.id,
          filter.isNew ? null : filter.id,
          payloadFor(filter)
        )
      );
    } finally {
      setPreviewLoading(false);
    }
  };

  if (!isOpen || !playlist?.id) return null;

  return (
    <>
      <Modal
        opened={isOpen}
        onClose={onClose}
        title="Stream filters"
        size="95vw"
        scrollAreaComponent={Modal.NativeScrollArea}
        lockScroll={false}
        withinPortal
        yOffset="2vh"
      >
        <Stack pt="md">
          <Group justify="space-between" align="flex-start">
            <Alert icon={<Info size={16} />} color="blue" variant="light">
              <Text size="sm">
                <strong>Order matters.</strong> The first matching rule wins.
                Stream filters decide whether individual Live TV streams are
                imported; category import rules remain separate.
              </Text>
            </Alert>
            <Button
              variant="default"
              size="xs"
              leftSection={<Plus size={14} />}
              onClick={addFilter}
              loading={loading}
            >
              Add filter
            </Button>
          </Group>

          {filters.length === 0 ? (
            <Alert color="gray">No stream filters configured.</Alert>
          ) : (
            <DndContext
              sensors={sensors}
              collisionDetection={closestCenter}
              modifiers={[restrictToVerticalAxis]}
              onDragEnd={reorderFilters}
            >
              <SortableContext
                items={filters.map((filter) => filter.id)}
                strategy={verticalListSortingStrategy}
              >
                <ScrollArea type="auto">
                  <Table striped withTableBorder miw={900} verticalSpacing="xs">
                    <TableThead>
                      <TableTr>
                        <TableTh w={48} aria-label="Filter order" />
                        <TableTh w={170}>Field</TableTh>
                        <TableTh>Regular expression</TableTh>
                        <TableTh w={120}>Result</TableTh>
                        <TableTh w={90}>Case</TableTh>
                        <TableTh w={90}>Actions</TableTh>
                      </TableTr>
                    </TableThead>
                    <TableTbody>
                      {filters.map((filter) => (
                        <SortableFilterRow
                          key={filter.id}
                          filterId={filter.id}
                          error={filterErrors[filter.id]}
                        >
                          <TableTd>
                            <Select
                              size="xs"
                              aria-label="Stream filter field"
                              data={
                                filter.filter_type === 'group'
                                  ? M3U_FILTER_TYPES
                                  : filterTypeOptions
                              }
                              value={filter.filter_type}
                              onChange={(value) =>
                                updateLocal(filter.id, { filter_type: value })
                              }
                            />
                          </TableTd>
                          <TableTd>
                            <TextInput
                              size="xs"
                              aria-label="Stream filter regular expression"
                              value={filter.regex_pattern}
                              error={filterErrors[filter.id] || null}
                              onChange={(event) =>
                                updateLocal(filter.id, {
                                  regex_pattern: event.currentTarget.value,
                                })
                              }
                            />
                          </TableTd>
                          <TableTd>
                            <Select
                              size="xs"
                              aria-label="Stream filter result"
                              data={[
                                { value: 'include', label: 'Include' },
                                { value: 'exclude', label: 'Exclude' },
                              ]}
                              value={filter.exclude ? 'exclude' : 'include'}
                              onChange={(value) =>
                                updateLocal(filter.id, {
                                  exclude: value === 'exclude',
                                })
                              }
                            />
                          </TableTd>
                          <TableTd>
                            <Checkbox
                              aria-label="Case sensitive"
                              checked={
                                filter.custom_properties?.case_sensitive ?? true
                              }
                              onChange={(event) =>
                                updateLocal(filter.id, {
                                  custom_properties: {
                                    ...(filter.custom_properties || {}),
                                    case_sensitive: event.currentTarget.checked,
                                  },
                                })
                              }
                            />
                          </TableTd>
                          <TableTd>
                            <Group gap={4} wrap="nowrap">
                              <ActionIcon
                                aria-label="Save stream filter"
                                color="blue"
                                variant="subtle"
                                loading={savingIds.has(filter.id)}
                                onClick={() => saveFilter(filter)}
                              >
                                <Save size={15} />
                              </ActionIcon>
                              <ActionIcon
                                aria-label="Preview stream filter"
                                color="green"
                                variant="subtle"
                                disabled={!filter.regex_pattern.trim()}
                                onClick={() => openPreview(filter)}
                              >
                                <Eye size={15} />
                              </ActionIcon>
                              <ActionIcon
                                aria-label="Delete stream filter"
                                color="red"
                                variant="subtle"
                                onClick={() => requestDelete(filter.id)}
                              >
                                <Trash2 size={15} />
                              </ActionIcon>
                            </Group>
                          </TableTd>
                        </SortableFilterRow>
                      ))}
                    </TableTbody>
                  </Table>
                </ScrollArea>
              </SortableContext>
            </DndContext>
          )}
        </Stack>
      </Modal>

      <ConfirmationDialog
        opened={confirmDeleteOpen}
        onClose={() => setConfirmDeleteOpen(false)}
        onConfirm={() => deleteFilter(deleteTarget)}
        loading={deleting}
        title="Confirm Filter Deletion"
        message="Are you sure you want to delete this stream filter? This action cannot be undone."
        confirmLabel="Delete"
        cancelLabel="Cancel"
        actionKey="delete-filter"
        onSuppressChange={suppressWarning}
        size="md"
      />

      <Modal
        opened={Boolean(previewFilter)}
        onClose={() => {
          setPreviewFilter(null);
          setPreview(null);
        }}
        title="Stream filter preview"
        size="xl"
      >
        <Stack>
          <Text size="sm" c="dimmed">
            The complete ordered filter list is evaluated. The preview uses the
            enabled groups from the last Live TV refresh, before stream filters
            are applied, and shows only rows for which this filter is the first
            match.
          </Text>
          {!previewLoading && preview && !preview.catalog_complete && (
            <Alert color="yellow">
              The complete pre-filter catalog is not available yet. Refresh this
              M3U account once, then open the preview again. Until then, only
              currently imported streams can be checked.
            </Alert>
          )}
          <Text fw={600}>
            {previewLoading
              ? 'Evaluating…'
              : `${preview?.count || 0} matching streams from ${preview?.inventory_count || 0} candidates`}
          </Text>
          <ScrollArea h="45vh">
            <Table striped withTableBorder stickyHeader>
              <TableThead>
                <TableTr>
                  <TableTh>Name</TableTh>
                  <TableTh>Group</TableTh>
                  <TableTh w={100}>Result</TableTh>
                </TableTr>
              </TableThead>
              <TableTbody>
                {(preview?.results || []).map((row) => (
                  <TableTr key={row.id}>
                    <TableTd>{row.name}</TableTd>
                    <TableTd>{row.group || '—'}</TableTd>
                    <TableTd>{row.result}</TableTd>
                  </TableTr>
                ))}
              </TableTbody>
            </Table>
          </ScrollArea>
          {preview?.truncated && (
            <Text size="xs" c="dimmed">
              Showing the first 200 matches.
            </Text>
          )}
          <Group justify="flex-end">
            <Button
              variant="default"
              onClick={() => {
                setPreviewFilter(null);
                setPreview(null);
              }}
            >
              Close
            </Button>
          </Group>
        </Stack>
      </Modal>
    </>
  );
};

export default M3UFilters;
