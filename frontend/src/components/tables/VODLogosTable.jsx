import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  ActionIcon,
  Badge,
  Box,
  Button,
  Center,
  Checkbox,
  Flex,
  Group,
  Image,
  LoadingOverlay,
  NativeSelect,
  Pagination,
  Paper,
  Select,
  Stack,
  Text,
  TextInput,
  Tooltip,
  useMantineTheme,
} from '@mantine/core';
import { ExternalLink, Search, Trash2, Trash, SquareMinus } from 'lucide-react';
import useVODLogosStore from '../../store/vodLogos';
import useLocalStorage from '../../hooks/useLocalStorage';
import { CustomTable, useTable } from './CustomTable';
import ConfirmationDialog from '../ConfirmationDialog';
import { notifications } from '@mantine/notifications';

const VODLogoRowActions = ({ theme, row, deleteLogo }) => {
  const [tableSize] = useLocalStorage('table-size', 'default');

  const onDelete = useCallback(() => {
    deleteLogo(row.original.id);
  }, [row.original.id, deleteLogo]);

  const iconSize =
    tableSize === 'default' ? 'sm' : tableSize === 'compact' ? 'xs' : 'md';

  return (
    <Box style={{ width: '100%', justifyContent: 'left' }}>
      <Group gap={2} justify="center">
        <ActionIcon
          size={iconSize}
          variant="transparent"
          color={theme.tailwind.red[6]}
          onClick={onDelete}
        >
          <SquareMinus size="18" />
        </ActionIcon>
      </Group>
    </Box>
  );
};

export default function VODLogosTable() {
  const theme = useMantineTheme();

  const {
    logos,
    totalCount,
    isLoading,
    fetchVODLogos,
    deleteVODLogo,
    deleteVODLogos,
    cleanupUnusedVODLogos,
  } = useVODLogosStore();

  const [currentPage, setCurrentPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);
  const [nameFilter, setNameFilter] = useState('');
  const [usageFilter, setUsageFilter] = useState('all');
  const [selectedRows, setSelectedRows] = useState(new Set());
  const [confirmDeleteOpen, setConfirmDeleteOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [confirmCleanupOpen, setConfirmCleanupOpen] = useState(false);
  const [paginationString, setPaginationString] = useState('');
  const [isCleaningUp, setIsCleaningUp] = useState(false);
  const tableRef = React.useRef(null);

  // Calculate unused logos count
  const unusedLogosCount = useMemo(() => {
    return logos.filter(
      (logo) => logo.movie_count === 0 && logo.series_count === 0
    ).length;
  }, [logos]);
  useEffect(() => {
    fetchVODLogos({
      page: currentPage,
      page_size: pageSize,
      name: nameFilter,
      usage: usageFilter === 'all' ? undefined : usageFilter,
    });
  }, [currentPage, pageSize, nameFilter, usageFilter, fetchVODLogos]);

  const handleSelectAll = useCallback(
    (checked) => {
      if (checked) {
        setSelectedRows(new Set(logos.map((logo) => logo.id)));
      } else {
        setSelectedRows(new Set());
      }
    },
    [logos]
  );

  const handleSelectRow = useCallback((id, checked) => {
    setSelectedRows((prev) => {
      const newSet = new Set(prev);
      if (checked) {
        newSet.add(id);
      } else {
        newSet.delete(id);
      }
      return newSet;
    });
  }, []);

  const deleteLogo = useCallback((id) => {
    setDeleteTarget([id]);
    setConfirmDeleteOpen(true);
  }, []);

  const handleDeleteSelected = useCallback(() => {
    setDeleteTarget(Array.from(selectedRows));
    setConfirmDeleteOpen(true);
  }, [selectedRows]);

  const onRowSelectionChange = useCallback((newSelection) => {
    setSelectedRows(new Set(newSelection));
  }, []);

  const clearSelections = useCallback(() => {
    setSelectedRows(new Set());
    // Clear table's internal selection state if table is initialized
    if (tableRef.current?.setSelectedTableIds) {
      tableRef.current.setSelectedTableIds([]);
    }
  }, []);

  const handleConfirmDelete = async () => {
    try {
      if (deleteTarget.length === 1) {
        await deleteVODLogo(deleteTarget[0]);
        notifications.show({
          title: 'Success',
          message: 'VOD logo deleted successfully',
          color: 'green',
        });
      } else {
        await deleteVODLogos(deleteTarget);
        notifications.show({
          title: 'Success',
          message: `${deleteTarget.length} VOD logos deleted successfully`,
          color: 'green',
        });
      }
    } catch (error) {
      notifications.show({
        title: 'Error',
        message: error.message || 'Failed to delete VOD logos',
        color: 'red',
      });
    } finally {
      // Always clear selections and close dialog, even on error
      clearSelections();
      setConfirmDeleteOpen(false);
      setDeleteTarget(null);
    }
  };

  const handleCleanupUnused = useCallback(() => {
    setConfirmCleanupOpen(true);
  }, []);

  const handleConfirmCleanup = async () => {
    setIsCleaningUp(true);
    try {
      const result = await cleanupUnusedVODLogos();
      notifications.show({
        title: 'Success',
        message: `Cleaned up ${result.deleted_count} unused VOD logos`,
        color: 'green',
      });
    } catch (error) {
      notifications.show({
        title: 'Error',
        message: error.message || 'Failed to cleanup unused VOD logos',
        color: 'red',
      });
    } finally {
      setIsCleaningUp(false);
      setConfirmCleanupOpen(false);
      clearSelections(); // Clear selections after cleanup
    }
  };

  // Clear selections only when filters change (not on every data fetch)
  useEffect(() => {
    clearSelections();
  }, [nameFilter, usageFilter, clearSelections]);

  useEffect(() => {
    const startItem = (currentPage - 1) * pageSize + 1;
    const endItem = Math.min(currentPage * pageSize, totalCount);
    setPaginationString(`${startItem} to ${endItem} of ${totalCount}`);
  }, [currentPage, pageSize, totalCount]);

  const pageCount = useMemo(() => {
    return Math.ceil(totalCount / pageSize);
  }, [totalCount, pageSize]);

  const columns = useMemo(
    () => [
      {
        id: 'select',
        header: () => (
          <Checkbox
            checked={
              selectedRows.size > 0 && selectedRows.size === logos.length
            }
            indeterminate={
              selectedRows.size > 0 && selectedRows.size < logos.length
            }
            onChange={(event) => handleSelectAll(event.currentTarget.checked)}
            size="sm"
          />
        ),
        cell: ({ row }) => (
          <Checkbox
            checked={selectedRows.has(row.original.id)}
            onChange={(event) =>
              handleSelectRow(row.original.id, event.currentTarget.checked)
            }
            size="sm"
          />
        ),
        size: 50,
        enableSorting: false,
      },
      {
        header: 'Preview',
        accessorKey: 'cache_url',
        size: 80,
        enableSorting: false,
        cell: ({ getValue, row }) => (
          <Center style={{ width: '100%', padding: '4px' }}>
            <Image
              src={getValue()}
              alt={row.original.name}
              width={40}
              height={30}
              fit="contain"
              fallbackSrc="/logo.png"
              style={{
                transition: 'transform 0.3s ease',
                cursor: 'pointer',
              }}
              onMouseEnter={(e) => {
                e.target.style.transform = 'scale(1.5)';
              }}
              onMouseLeave={(e) => {
                e.target.style.transform = 'scale(1)';
              }}
            />
          </Center>
        ),
      },
      {
        header: 'Name',
        accessorKey: 'name',
        size: 250,
        cell: ({ getValue }) => (
          <Text fw={500} size="sm">
            {getValue()}
          </Text>
        ),
      },
      {
        header: 'Usage',
        accessorKey: 'usage',
        size: 120,
        cell: ({ row }) => {
          const { movie_count, series_count, item_names } = row.original;
          const totalUsage = movie_count + series_count;

          if (totalUsage === 0) {
            return (
              <Badge size="sm" variant="light" color="gray">
                Unused
              </Badge>
            );
          }

          // Build usage description
          const usageParts = [];
          if (movie_count > 0) {
            usageParts.push(
              `${movie_count} movie${movie_count !== 1 ? 's' : ''}`
            );
          }
          if (series_count > 0) {
            usageParts.push(`${series_count} series`);
          }

          const label =
            usageParts.length === 1
              ? usageParts[0]
              : `${totalUsage} item${totalUsage !== 1 ? 's' : ''}`;

          return (
            <Tooltip
              label={
                <div>
                  <Text size="xs" fw={600}>
                    Used by {usageParts.join(' & ')}:
                  </Text>
                  {item_names &&
                    item_names.map((name, index) => (
                      <Text key={index} size="xs">
                        • {name}
                      </Text>
                    ))}
                </div>
              }
              multiline
              width={220}
            >
              <Badge size="sm" variant="light" color="blue">
                {label}
              </Badge>
            </Tooltip>
          );
        },
      },
      {
        header: 'URL',
        accessorKey: 'url',
        grow: true,
        cell: ({ getValue }) => (
          <Group gap={4} style={{ alignItems: 'center' }}>
            <Box
              style={{
                whiteSpace: 'nowrap',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                maxWidth: 300,
              }}
            >
              <Text size="sm" c="dimmed">
                {getValue()}
              </Text>
            </Box>
            {getValue()?.startsWith('http') && (
              <ActionIcon
                size="xs"
                variant="transparent"
                color="gray"
                onClick={() => window.open(getValue(), '_blank')}
              >
                <ExternalLink size={12} />
              </ActionIcon>
            )}
          </Group>
        ),
      },
      {
        id: 'actions',
        size: 80,
        header: 'Actions',
        enableSorting: false,
        cell: ({ row }) => (
          <VODLogoRowActions theme={theme} row={row} deleteLogo={deleteLogo} />
        ),
      },
    ],
    [theme, deleteLogo, selectedRows, handleSelectAll, handleSelectRow, logos]
  );

  const renderHeaderCell = (header) => {
    return (
      <Text size="sm" name={header.id}>
        {header.column.columnDef.header}
      </Text>
    );
  };

  const table = useTable({
    data: logos,
    columns,
    manualPagination: true,
    pageCount: pageCount,
    allRowIds: logos.map((logo) => logo.id),
    enablePagination: false,
    enableRowSelection: true,
    enableRowVirtualization: false,
    renderTopToolbar: false,
    manualSorting: false,
    manualFiltering: false,
    onRowSelectionChange: onRowSelectionChange,
    headerCellRenderFns: {
      actions: renderHeaderCell,
      cache_url: renderHeaderCell,
      name: renderHeaderCell,
      url: renderHeaderCell,
      usage: renderHeaderCell,
    },
  });

  // Store table reference for clearing selections
  React.useEffect(() => {
    tableRef.current = table;
  }, [table]);

  // Helper to get single logo when confirming single-delete
  const logoToDelete =
    deleteTarget && deleteTarget.length === 1
      ? logos.find((l) => l.id === deleteTarget[0])
      : null;
  return (
    <Box
      style={{
        display: 'flex',
        justifyContent: 'center',
        padding: '0px',
        minHeight: 'calc(100vh - 200px)',
        minWidth: '900px',
      }}
    >
      <Stack gap="md" style={{ maxWidth: '1200px', width: '100%' }}>
        <Paper
          style={{
            backgroundColor: '#27272A',
            border: '1px solid #3f3f46',
            borderRadius: 'var(--mantine-radius-md)',
          }}
        >
          {/* Top toolbar */}
          <Box
            style={{
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              padding: '16px',
              borderBottom: '1px solid #3f3f46',
            }}
          >
            <Group gap="sm">
              <TextInput
                placeholder="Filter by name..."
                value={nameFilter}
                onChange={(event) => {
                  const value = event.target.value;
                  setNameFilter(value);
                }}
                size="xs"
                style={{ width: 200 }}
              />
              <Select
                placeholder="All"
                value={usageFilter}
                onChange={(value) => setUsageFilter(value)}
                data={[
                  { value: 'all', label: 'All logos' },
                  { value: 'used', label: 'Used only' },
                  { value: 'unused', label: 'Unused only' },
                  { value: 'movies', label: 'Movies logos' },
                  { value: 'series', label: 'Series logos' },
                ]}
                size="xs"
                style={{ width: 120 }}
              />
            </Group>

            <Group gap="sm">
              <Button
                leftSection={<Trash size={16} />}
                variant="light"
                size="xs"
                color="orange"
                onClick={handleCleanupUnused}
                loading={isCleaningUp}
                disabled={unusedLogosCount === 0}
              >
                Cleanup Unused{' '}
                {unusedLogosCount > 0 ? `(${unusedLogosCount})` : ''}
              </Button>

              <Button
                leftSection={<SquareMinus size={18} />}
                variant="default"
                size="xs"
                onClick={handleDeleteSelected}
                disabled={selectedRows.size === 0}
              >
                Delete {selectedRows.size > 0 ? `(${selectedRows.size})` : ''}
              </Button>
            </Group>
          </Box>

          {/* Table container */}
          <Box
            style={{
              position: 'relative',
              borderRadius:
                '0 0 var(--mantine-radius-md) var(--mantine-radius-md)',
            }}
          >
            <Box
              style={{
                overflow: 'auto',
                height: 'calc(100vh - 200px)',
              }}
            >
              <div>
                <LoadingOverlay visible={isLoading} />
                <CustomTable table={table} />
              </div>
            </Box>

            {/* Pagination Controls */}
            <Box
              style={{
                position: 'sticky',
                bottom: 0,
                zIndex: 3,
                backgroundColor: '#27272A',
                borderTop: '1px solid #3f3f46',
              }}
            >
              <Group
                gap={5}
                justify="center"
                style={{
                  padding: 8,
                }}
              >
                <Text size="xs">Page Size</Text>
                <NativeSelect
                  size="xxs"
                  value={String(pageSize)}
                  data={['25', '50', '100', '250']}
                  onChange={(event) => {
                    setPageSize(Number(event.target.value));
                    setCurrentPage(1);
                  }}
                  style={{ paddingRight: 20 }}
                />
                <Pagination
                  total={pageCount}
                  value={currentPage}
                  onChange={setCurrentPage}
                  size="xs"
                  withEdges
                  style={{ paddingRight: 20 }}
                />
                <Text size="xs">{paginationString}</Text>
              </Group>
            </Box>
          </Box>
        </Paper>
      </Stack>

      <ConfirmationDialog
        opened={confirmDeleteOpen}
        onClose={() => {
          setConfirmDeleteOpen(false);
          setDeleteTarget(null);
        }}
        onConfirm={(deleteFiles) => {
          // pass deleteFiles option through
          handleConfirmDelete(deleteFiles);
        }}
        title={
          deleteTarget && deleteTarget.length > 1
            ? 'Delete Multiple Logos'
            : 'Delete Logo'
        }
        message={
          deleteTarget && deleteTarget.length > 1 ? (
            <div>
              Are you sure you want to delete {deleteTarget.length} selected
              logos?
              <Text size="sm" c="dimmed" mt="xs">
                Any movies or series using these logos will have their logo
                removed.
              </Text>
              <Text size="sm" c="dimmed" mt="xs">
                This action cannot be undone.
              </Text>
            </div>
          ) : logoToDelete ? (
            <div>
              Are you sure you want to delete the logo "{logoToDelete.name}"?
              {logoToDelete.movie_count + logoToDelete.series_count > 0 && (
                <Text size="sm" c="orange" mt="xs">
                  This logo is currently used by{' '}
                  {logoToDelete.movie_count + logoToDelete.series_count} item
                  {logoToDelete.movie_count + logoToDelete.series_count !== 1
                    ? 's'
                    : ''}
                  . They will have their logo removed.
                </Text>
              )}
              <Text size="sm" c="dimmed" mt="xs">
                This action cannot be undone.
              </Text>
            </div>
          ) : (
            'Are you sure you want to delete this logo?'
          )
        }
        confirmLabel="Delete"
        cancelLabel="Cancel"
        size="md"
        showDeleteFileOption={
          deleteTarget && deleteTarget.length > 1
            ? Array.from(deleteTarget).some((id) => {
                const logo = logos.find((l) => l.id === id);
                return logo && logo.url && logo.url.startsWith('/data/logos');
              })
            : logoToDelete &&
              logoToDelete.url &&
              logoToDelete.url.startsWith('/data/logos')
        }
        deleteFileLabel={
          deleteTarget && deleteTarget.length > 1
            ? 'Also delete local logo files from disk'
            : 'Also delete logo file from disk'
        }
      />

      <ConfirmationDialog
        opened={confirmCleanupOpen}
        onClose={() => setConfirmCleanupOpen(false)}
        onConfirm={handleConfirmCleanup}
        title="Cleanup Unused Logos"
        message={
          <div>
            Are you sure you want to cleanup {unusedLogosCount} unused logo
            {unusedLogosCount !== 1 ? 's' : ''}?
            <Text size="sm" c="dimmed" mt="xs">
              This will permanently delete all logos that are not currently used
              by any series or movies.
            </Text>
            <Text size="sm" c="dimmed" mt="xs">
              This action cannot be undone.
            </Text>
          </div>
        }
        confirmLabel="Cleanup"
        cancelLabel="Cancel"
        size="md"
        showDeleteFileOption={true}
        deleteFileLabel="Also delete local logo files from disk"
      />
    </Box>
  );
}
