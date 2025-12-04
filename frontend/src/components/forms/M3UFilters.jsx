import React, { useState, useEffect } from 'react';
import API from '../../api';
import usePlaylistsStore from '../../store/playlists';
import ConfirmationDialog from '../ConfirmationDialog';
import useWarningsStore from '../../store/warnings';
import {
  Flex,
  Modal,
  Button,
  Box,
  ActionIcon,
  Text,
  useMantineTheme,
  Center,
  Group,
  Alert,
} from '@mantine/core';
import { GripHorizontal, Info, SquareMinus, SquarePen } from 'lucide-react';
import M3UFilter from './M3UFilter';
import { M3U_FILTER_TYPES } from '../../constants';
import {
  closestCenter,
  DndContext,
  KeyboardSensor,
  MouseSensor,
  TouchSensor,
  useDraggable,
  useSensor,
  useSensors,
} from '@dnd-kit/core';
import {
  arrayMove,
  SortableContext,
  useSortable,
  verticalListSortingStrategy,
} from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import { restrictToVerticalAxis } from '@dnd-kit/modifiers';

const RowDragHandleCell = ({ rowId }) => {
  const { attributes, listeners, setNodeRef } = useDraggable({
    id: rowId,
  });

  return (
    <Center>
      <ActionIcon
        ref={setNodeRef}
        {...listeners}
        {...attributes}
        variant="transparent"
        size="xs"
        style={{
          cursor: 'grab', // this is enough
        }}
      >
        <GripHorizontal color="white" />
      </ActionIcon>
    </Center>
  );
};

// Row Component
const DraggableRow = ({ filter, editFilter, onDelete }) => {
  const theme = useMantineTheme();
  const { transform, transition, setNodeRef, isDragging } = useSortable({
    id: filter.id,
  });

  const style = {
    transform: CSS.Transform.toString(transform), //let dnd-kit do its thing
    transition: transition,
    opacity: isDragging ? 0.8 : 1,
    zIndex: isDragging ? 1 : 0,
    position: 'relative',
  };

  return (
    <Box
      ref={setNodeRef}
      key={filter.id}
      spacing="xs"
      style={{
        ...style,
        padding: '8px',
        paddingBottom: '8px',
        border: '1px solid #444',
        borderRadius: '8px',
        backgroundColor: '#2A2A2E',
        flexDirection: 'column',
        alignItems: 'stretch',
        marginBottom: 5,
      }}
    >
      <Flex gap="sm" justify="space-between" alignItems="middle">
        <Group justify="left">
          <RowDragHandleCell rowId={filter.id} />
          <Text
            size="sm"
            fw={700}
            style={{
              color: filter.exclude
                ? theme.tailwind.red[6]
                : theme.tailwind.green[5],
            }}
          >
            {filter.exclude ? 'Exclude' : 'Include'}
          </Text>
          <Text size="sm">
            {
              M3U_FILTER_TYPES.find((type) => type.value == filter.filter_type)
                .label
            }
          </Text>
          <Text size="sm">matching</Text>
          <Text size="sm">
            "<code>{filter.regex_pattern}</code>"
          </Text>
        </Group>

        <Group align="flex-end" gap="xs">
          <ActionIcon
            size="sm"
            variant="transparent"
            color={theme.tailwind.yellow[3]}
            onClick={() => editFilter(filter)}
          >
            <SquarePen size="20" />
          </ActionIcon>

          <ActionIcon
            color={theme.tailwind.red[6]}
            onClick={() => onDelete(filter.id)}
            size="small"
            variant="transparent"
          >
            <SquareMinus size="20" />
          </ActionIcon>
        </Group>
      </Flex>
    </Box>
  );
};

const M3UFilters = ({ playlist, isOpen, onClose }) => {
  const theme = useMantineTheme();

  const [editorOpen, setEditorOpen] = useState(false);
  const [filter, setFilter] = useState(null);
  const [confirmDeleteOpen, setConfirmDeleteOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [filterToDelete, setFilterToDelete] = useState(null);
  const [filters, setFilters] = useState([]);

  const isWarningSuppressed = useWarningsStore((s) => s.isWarningSuppressed);
  const suppressWarning = useWarningsStore((s) => s.suppressWarning);
  const fetchPlaylist = usePlaylistsStore((s) => s.fetchPlaylist);

  const sensors = useSensors(
    useSensor(MouseSensor, {}),
    useSensor(TouchSensor, {}),
    useSensor(KeyboardSensor, {})
  );

  useEffect(() => {
    setFilters(playlist.filters || []);
  }, [playlist]);

  const editFilter = (filter = null) => {
    if (filter) {
      setFilter(filter);
    }

    setEditorOpen(true);
  };

  const onDelete = async (id) => {
    if (!playlist || !playlist.id) return;

    // Get profile details for the confirmation dialog
    const filterObj = playlist.filters.find((p) => p.id === id);
    setFilterToDelete(filterObj);
    setDeleteTarget(id);

    // Skip warning if it's been suppressed
    if (isWarningSuppressed('delete-filter')) {
      return deleteFilter(id);
    }

    setConfirmDeleteOpen(true);
  };

  const deleteFilter = async (id) => {
    if (!playlist || !playlist.id) return;
    try {
      await API.deleteM3UFilter(playlist.id, id);
      setConfirmDeleteOpen(false);
    } catch (error) {
      console.error('Error deleting profile:', error);
      setConfirmDeleteOpen(false);
    }

    fetchPlaylist(playlist.id);
    setFilters(filters.filter((f) => f.id !== id));
  };

  const closeEditor = (updatedPlaylist = null) => {
    setFilter(null);
    setEditorOpen(false);

    if (updatedPlaylist) {
      setFilters(updatedPlaylist.filters);
    }
  };

  const handleDragEnd = async ({ active, over }) => {
    if (!over || active.id === over.id) return;

    const originalFilters = [...filters];

    const oldIndex = filters.findIndex((f) => f.id === active.id);
    const newIndex = filters.findIndex((f) => f.id === over.id);
    const newFilters = arrayMove(filters, oldIndex, newIndex);

    setFilters(newFilters);

    // Recalculate and compare order
    const updatedFilters = newFilters.map((filter, index) => ({
      ...filter,
      newOrder: index,
    }));

    // Filter only those whose order actually changed
    const changedFilters = updatedFilters.filter((f) => f.order !== f.newOrder);

    // Send updates
    try {
      await Promise.all(
        changedFilters.map((f) =>
          API.updateM3UFilter(playlist.id, f.id, { ...f, order: f.newOrder })
        )
      );
      await fetchPlaylist(playlist.id);
    } catch (e) {
      setFilters(originalFilters);
    }
  };

  // Don't render if modal is not open, or if playlist data is invalid
  if (!isOpen || !playlist || !playlist.id) {
    return <></>;
  }

  return (
    <>
      <Modal
        opened={isOpen}
        onClose={onClose}
        title="Filters"
        size="lg"
        scrollAreaComponent={Modal.NativeScrollArea}
        lockScroll={false}
        withinPortal={true}
        yOffset="2vh"
      >
        <Alert
          icon={<Info size={16} />}
          color="blue"
          variant="light"
          style={{ marginBottom: 5 }}
        >
          <Text size="sm">
            <strong>Order Matters!</strong> Rules are processed in the order
            below. Once a stream matches a given rule, no other rules are
            checked.
          </Text>
        </Alert>

        <DndContext
          collisionDetection={closestCenter}
          modifiers={[restrictToVerticalAxis]}
          onDragEnd={handleDragEnd}
          sensors={sensors}
        >
          <SortableContext
            items={filters.map(({ id }) => id)}
            strategy={verticalListSortingStrategy}
          >
            {filters.map((filter) => (
              <DraggableRow
                key={filter.id}
                filter={filter}
                editFilter={editFilter}
                onDelete={onDelete}
              />
            ))}
          </SortableContext>
        </DndContext>

        <Flex mih={50} gap="xs" justify="flex-end" align="flex-end">
          <Button
            variant="contained"
            color="primary"
            size="small"
            onClick={() => editFilter()}
            style={{ width: '100%' }}
          >
            New
          </Button>
        </Flex>
      </Modal>

      <M3UFilter
        m3u={playlist}
        filter={filter}
        isOpen={editorOpen}
        onClose={closeEditor}
      />

      <ConfirmationDialog
        opened={confirmDeleteOpen}
        onClose={() => setConfirmDeleteOpen(false)}
        onConfirm={() => deleteFilter(deleteTarget)}
        title="Confirm Filter Deletion"
        message={
          filterToDelete ? (
            <div style={{ whiteSpace: 'pre-line' }}>
              {`Are you sure you want to delete the following filter?

Type: ${filterToDelete.type}
Patter: ${filterToDelete.regex_pattern}

This action cannot be undone.`}
            </div>
          ) : (
            'Are you sure you want to delete this filter? This action cannot be undone.'
          )
        }
        confirmLabel="Delete"
        cancelLabel="Cancel"
        actionKey="delete-filter"
        onSuppressChange={suppressWarning}
        size="md"
      />
    </>
  );
};

export default M3UFilters;
