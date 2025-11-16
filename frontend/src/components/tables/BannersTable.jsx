import React, { useMemo, useCallback, useState, useEffect } from 'react';
import API from '../../api';
import BannerForm from '../forms/Banner';
import useBannersStore from '../../store/banners';
import useLocalStorage from '../../hooks/useLocalStorage';
import {
  SquarePlus,
  SquareMinus,
  SquarePen,
  ExternalLink,
  Filter,
  Trash2,
  Trash,
} from 'lucide-react';
import {
  ActionIcon,
  Box,
  Text,
  Paper,
  Button,
  Flex,
  Group,
  useMantineTheme,
  LoadingOverlay,
  Stack,
  Image,
  Center,
  Badge,
  Tooltip,
  Select,
  TextInput,
  Menu,
  Checkbox,
  Pagination,
  NativeSelect,
} from '@mantine/core';
import { CustomTable, useTable } from './CustomTable';
import ConfirmationDialog from '../ConfirmationDialog';
import { notifications } from '@mantine/notifications';

const BannerRowActions = ({ theme, row, editBanner, deleteBanner }) => {
  const [tableSize, _] = useLocalStorage('table-size', 'default');

  const onEdit = useCallback(() => {
    editBanner(row.original);
  }, [row.original, editBanner]);

  const onDelete = useCallback(() => {
    deleteBanner(row.original.id);
  }, [row.original.id, deleteBanner]);

  const iconSize =
    tableSize == 'default' ? 'sm' : tableSize == 'compact' ? 'xs' : 'md';

  return (
    <Box style={{ width: '100%', justifyContent: 'left' }}>
      <Group gap={2} justify="center">
        <ActionIcon
          size={iconSize}
          variant="transparent"
          color={theme.tailwind.yellow[3]}
          onClick={onEdit}
        >
          <SquarePen size="18" />
        </ActionIcon>

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

const BannersTable = () => {
  const theme = useMantineTheme();

  /**
   * STORES
   */
  const {
    banners,
    fetchAllBanners,
    updateBanner,
    addBanner,
    isLoading: storeLoading,
  } = useBannersStore();

  /**
   * useState
   */
  const [selectedBanner, setSelectedBanner] = useState(null);
  const [bannerModalOpen, setBannerModalOpen] = useState(false);
  const [confirmDeleteOpen, setConfirmDeleteOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [bannerToDelete, setBannerToDelete] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const [confirmCleanupOpen, setConfirmCleanupOpen] = useState(false);
  const [isBulkDelete, setIsBulkDelete] = useState(false);
  const [isCleaningUp, setIsCleaningUp] = useState(false);
  const [filters, setFilters] = useState({
    name: '',
    used: 'all',
  });
  const [debouncedNameFilter, setDebouncedNameFilter] = useState('');
  const [selectedRows, setSelectedRows] = useState(new Set());
  const [pageSize, setPageSize] = useLocalStorage('banners-page-size', 25);
  const [pagination, setPagination] = useState({
    pageIndex: 0,
    pageSize: pageSize,
  });
  const [paginationString, setPaginationString] = useState('');

  // Debounce the name filter
  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedNameFilter(filters.name);
    }, 300); // 300ms delay

    return () => clearTimeout(timer);
  }, [filters.name]);

  const data = useMemo(() => {
    const bannersArray = Object.values(banners || {});

    // Apply filters
    let filteredBanners = bannersArray;

    if (debouncedNameFilter) {
      filteredBanners = filteredBanners.filter((banner) =>
        banner.name.toLowerCase().includes(debouncedNameFilter.toLowerCase())
      );
    }

    if (filters.used === 'used') {
      filteredBanners = filteredBanners.filter((banner) => banner.is_used);
    } else if (filters.used === 'unused') {
      filteredBanners = filteredBanners.filter((banner) => !banner.is_used);
    }

    return filteredBanners.sort((a, b) => a.id - b.id);
  }, [banners, debouncedNameFilter, filters.used]);

  // Get paginated data
  const paginatedData = useMemo(() => {
    const startIndex = pagination.pageIndex * pagination.pageSize;
    const endIndex = startIndex + pagination.pageSize;
    return data.slice(startIndex, endIndex);
  }, [data, pagination.pageIndex, pagination.pageSize]);

  // Calculate unused banners count
  const unusedBannersCount = useMemo(() => {
    const allBanners = Object.values(banners || {});
    return allBanners.filter((banner) => !banner.is_used).length;
  }, [banners]);

  /**
   * Functions
   */
  const executeDeleteBanner = useCallback(
    async (id, deleteFile = false) => {
      setIsLoading(true);
      try {
        await API.deleteBanner(id, deleteFile);
        await fetchAllBanners(); // Refresh all banners to maintain full view
        notifications.show({
          title: 'Success',
          message: 'Banner deleted successfully',
          color: 'green',
        });
      } catch (error) {
        notifications.show({
          title: 'Error',
          message: 'Failed to delete banner',
          color: 'red',
        });
      } finally {
        setIsLoading(false);
        setConfirmDeleteOpen(false);
        setDeleteTarget(null);
        setBannerToDelete(null);
        setIsBulkDelete(false);
        setSelectedRows(new Set()); // Clear selections
      }
    },
    [fetchAllBanners]
  );

  const executeBulkDelete = useCallback(
    async (deleteFiles = false) => {
      if (selectedRows.size === 0) return;

      setIsLoading(true);
      try {
        await API.deleteBanners(Array.from(selectedRows), deleteFiles);
        await fetchAllBanners(); // Refresh all banners to maintain full view

        notifications.show({
          title: 'Success',
          message: `${selectedRows.size} banners deleted successfully`,
          color: 'green',
        });
      } catch (error) {
        notifications.show({
          title: 'Error',
          message: 'Failed to delete banners',
          color: 'red',
        });
      } finally {
        setIsLoading(false);
        setConfirmDeleteOpen(false);
        setIsBulkDelete(false);
        setSelectedRows(new Set()); // Clear selections
      }
    },
    [selectedRows, fetchAllBanners]
  );

  const executeCleanupUnused = useCallback(
    async (deleteFiles = false) => {
      setIsCleaningUp(true);
      try {
        const result = await API.cleanupUnusedBanners(deleteFiles);
        await fetchAllBanners(); // Refresh all banners to maintain full view

        let message = `Successfully deleted ${result.deleted_count} unused banners`;
        if (result.local_files_deleted > 0) {
          message += ` and deleted ${result.local_files_deleted} local files`;
        }

        notifications.show({
          title: 'Cleanup Complete',
          message: message,
          color: 'green',
        });
      } catch (error) {
        notifications.show({
          title: 'Cleanup Failed',
          message: 'Failed to cleanup unused banners',
          color: 'red',
        });
      } finally {
        setIsCleaningUp(false);
        setConfirmCleanupOpen(false);
        setSelectedRows(new Set()); // Clear selections after cleanup
      }
    },
    [fetchAllBanners]
  );

  const editBanner = useCallback(async (banner = null) => {
    setSelectedBanner(banner);
    setBannerModalOpen(true);
  }, []);

  const deleteBanner = useCallback(
    async (id) => {
      const bannersArray = Object.values(banners || {});
      const banner = bannersArray.find((l) => l.id === id);
      setBannerToDelete(banner);
      setDeleteTarget(id);
      setIsBulkDelete(false);
      setConfirmDeleteOpen(true);
    },
    [banners]
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

  const handleSelectAll = useCallback(
    (checked) => {
      if (checked) {
        setSelectedRows(new Set(data.map((banner) => banner.id)));
      } else {
        setSelectedRows(new Set());
      }
    },
    [data]
  );

  const deleteBulkBanners = useCallback(() => {
    if (selectedRows.size === 0) return;

    setIsBulkDelete(true);
    setBannerToDelete(null);
    setDeleteTarget(Array.from(selectedRows));
    setConfirmDeleteOpen(true);
  }, [selectedRows]);

  const handleCleanupUnused = useCallback(() => {
    setConfirmCleanupOpen(true);
  }, []);

  // Clear selections when banners data changes (e.g., after filtering)
  useEffect(() => {
    setSelectedRows(new Set());
  }, [data.length]);

  // Update pagination when pageSize changes
  useEffect(() => {
    setPagination((prev) => ({
      ...prev,
      pageSize: pageSize,
    }));
  }, [pageSize]);

  // Calculate pagination string
  useEffect(() => {
    const startItem = pagination.pageIndex * pagination.pageSize + 1;
    const endItem = Math.min(
      (pagination.pageIndex + 1) * pagination.pageSize,
      data.length
    );
    setPaginationString(`${startItem} to ${endItem} of ${data.length}`);
  }, [pagination.pageIndex, pagination.pageSize, data.length]);

  // Calculate page count
  const pageCount = useMemo(() => {
    return Math.ceil(data.length / pagination.pageSize);
  }, [data.length, pagination.pageSize]);

  /**
   * useMemo
   */
  const columns = useMemo(
    () => [
      {
        id: 'select',
        header: ({ table }) => (
          <Checkbox
            checked={selectedRows.size > 0 && selectedRows.size === data.length}
            indeterminate={
              selectedRows.size > 0 && selectedRows.size < data.length
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
              fallbackSrc="/banner.png"
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
        accessorKey: 'channel_count',
        size: 120,
        cell: ({ getValue, row }) => {
          const count = getValue();
          const channelNames = row.original.channel_names || [];

          if (count === 0) {
            return (
              <Badge size="sm" variant="light" color="gray">
                Unused
              </Badge>
            );
          }

          // Analyze channel_names to categorize types
          const categorizeUsage = (names) => {
            const types = { channels: 0, movies: 0, series: 0 };

            names.forEach((name) => {
              if (name.startsWith('Channel:')) types.channels++;
              else if (name.startsWith('Movie:')) types.movies++;
              else if (name.startsWith('Series:')) types.series++;
            });

            return types;
          };

          const types = categorizeUsage(channelNames);
          const typeCount = Object.values(types).filter(
            (count) => count > 0
          ).length;

          // Generate smart label based on usage
          const generateLabel = () => {
            if (typeCount === 1) {
              // Only one type - be specific
              if (types.channels > 0)
                return `${types.channels} channel${types.channels !== 1 ? 's' : ''}`;
              if (types.movies > 0)
                return `${types.movies} movie${types.movies !== 1 ? 's' : ''}`;
              if (types.series > 0) return `${types.series} series`;
            } else {
              // Multiple types - use generic "items"
              return `${count} item${count !== 1 ? 's' : ''}`;
            }
          };

          const label = generateLabel();

          return (
            <Tooltip
              label={
                <div>
                  <Text size="xs" fw={600}>
                    Used by {label}:
                  </Text>
                  {channelNames.map((name, index) => (
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
          <LogoRowActions
            theme={theme}
            row={row}
            editBanner={editBanner}
            deleteBanner={deleteBanner}
          />
        ),
      },
    ],
    [
      theme,
      editBanner,
      deleteBanner,
      selectedRows,
      handleSelectRow,
      handleSelectAll,
      data.length,
    ]
  );

  const closeBannerForm = () => {
    setSelectedBanner(null);
    setBannerModalOpen(false);
    // Don't automatically refresh - only refresh if data was actually changed via onBannerSuccess
  };

  const onBannerSuccess = useCallback(
    async (result) => {
      if (!result) return;

      const { type, banner } = result;

      if (type === 'update' && banner) {
        // For updates, just update the specific banner in the store
        updateBanner(banner);
      } else if ((type === 'create' || type === 'upload') && banner) {
        // For creates, add the new banner to the store
        // Note: uploads are handled automatically by API.uploadLogo, so this path is rarely used
        addBanner(banner);
      } else {
        // Fallback: if we don't have banner data for some reason, refresh all
        await fetchAllBanners(); // Use fetchAllBanners to maintain full view
      }
    },
    [updateBanner, addBanner, fetchAllBanners]
  );

  const renderHeaderCell = (header) => {
    return (
      <Text size="sm" name={header.id}>
        {header.column.columnDef.header}
      </Text>
    );
  };

  const onRowSelectionChange = useCallback((newSelection) => {
    setSelectedRows(new Set(newSelection));
  }, []);

  const onPageSizeChange = (e) => {
    const newPageSize = parseInt(e.target.value);
    setPageSize(newPageSize);
    setPagination((prev) => ({
      ...prev,
      pageSize: newPageSize,
      pageIndex: 0, // Reset to first page
    }));
  };

  const onPageIndexChange = (pageIndex) => {
    if (!pageIndex || pageIndex > pageCount) {
      return;
    }

    setPagination((prev) => ({
      ...prev,
      pageIndex: pageIndex - 1,
    }));
  };

  const table = useTable({
    columns,
    data: paginatedData,
    allRowIds: paginatedData.map((banner) => banner.id),
    enablePagination: false, // Disable internal pagination since we're handling it manually
    enableRowSelection: true,
    enableRowVirtualization: false,
    renderTopToolbar: false,
    manualSorting: false,
    manualFiltering: false,
    manualPagination: true, // Enable manual pagination
    onRowSelectionChange: onRowSelectionChange,
    headerCellRenderFns: {
      actions: renderHeaderCell,
      cache_url: renderHeaderCell,
      name: renderHeaderCell,
      url: renderHeaderCell,
      channel_count: renderHeaderCell,
    },
  });

  return (
    <>
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
          <Flex style={{ alignItems: 'center', paddingBottom: 10 }} gap={15}>
            <Text
              style={{
                fontFamily: 'Inter, sans-serif',
                fontWeight: 500,
                fontSize: '20px',
                lineHeight: 1,
                letterSpacing: '-0.3px',
                color: 'gray.6',
                marginBottom: 0,
              }}
            >
              Banners
            </Text>
            <Text size="sm" c="dimmed">
              ({data.length} banner{data.length !== 1 ? 's' : ''})
            </Text>
          </Flex>

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
                  value={filters.name}
                  onChange={(event) => {
                    const value = event.target.value;
                    setFilters((prev) => ({
                      ...prev,
                      name: value,
                    }));
                  }}
                  size="xs"
                  style={{ width: 200 }}
                />
                <Select
                  placeholder="Usage filter"
                  value={filters.used}
                  onChange={(value) =>
                    setFilters((prev) => ({
                      ...prev,
                      used: value,
                    }))
                  }
                  data={[
                    { value: 'all', label: 'All banners' },
                    { value: 'used', label: 'Used only' },
                    { value: 'unused', label: 'Unused only' },
                  ]}
                  size="xs"
                  style={{ width: 140 }}
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
                  disabled={unusedBannersCount === 0}
                >
                  Cleanup Unused{' '}
                  {unusedBannersCount > 0 ? `(${unusedBannersCount})` : ''}
                </Button>

                <Button
                  leftSection={<SquareMinus size={18} />}
                  variant="default"
                  size="xs"
                  onClick={deleteBulkBanners}
                  disabled={selectedRows.size === 0}
                >
                  Delete {selectedRows.size > 0 ? `(${selectedRows.size})` : ''}
                </Button>

                <Button
                  leftSection={<SquarePlus size={18} />}
                  variant="light"
                  size="xs"
                  onClick={() => editBanner()}
                  p={5}
                  color={theme.tailwind.green[5]}
                  style={{
                    borderWidth: '1px',
                    borderColor: theme.tailwind.green[5],
                    color: 'white',
                  }}
                >
                  Add Banner
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
                  <LoadingOverlay visible={isLoading || storeLoading} />
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
                    value={pagination.pageSize}
                    data={['25', '50', '100', '250']}
                    onChange={onPageSizeChange}
                    style={{ paddingRight: 20 }}
                  />
                  <Pagination
                    total={pageCount}
                    value={pagination.pageIndex + 1}
                    onChange={onPageIndexChange}
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
      </Box>

      <BannerForm
        banner={selectedBanner}
        isOpen={bannerModalOpen}
        onClose={closeBannerForm}
        onSuccess={onBannerSuccess}
      />

      <ConfirmationDialog
        opened={confirmDeleteOpen}
        onClose={() => setConfirmDeleteOpen(false)}
        onConfirm={(deleteFiles) => {
          if (isBulkDelete) {
            executeBulkDelete(deleteFiles);
          } else {
            executeDeleteBanner(deleteTarget, deleteFiles);
          }
        }}
        title={isBulkDelete ? 'Delete Multiple Banners' : 'Delete Banner'}
        message={
          isBulkDelete ? (
            <div>
              Are you sure you want to delete {selectedRows.size} selected
              banners?
              <Text size="sm" c="dimmed" mt="xs">
                Any channels, movies, or series using these banners will have
                their banner removed.
              </Text>
              <Text size="sm" c="dimmed" mt="xs">
                This action cannot be undone.
              </Text>
            </div>
          ) : bannerToDelete ? (
            <div>
              Are you sure you want to delete the banner "{bannerToDelete.name}"?
              {bannerToDelete.channel_count > 0 && (
                <Text size="sm" c="orange" mt="xs">
                  This banner is currently used by {bannerToDelete.channel_count}{' '}
                  item{bannerToDelete.channel_count !== 1 ? 's' : ''}. They will
                  have their banner removed.
                </Text>
              )}
              <Text size="sm" c="dimmed" mt="xs">
                This action cannot be undone.
              </Text>
            </div>
          ) : (
            'Are you sure you want to delete this banner?'
          )
        }
        confirmLabel="Delete"
        cancelLabel="Cancel"
        size="md"
        showDeleteFileOption={
          isBulkDelete
            ? Array.from(selectedRows).some((id) => {
                const banner = Object.values(banners).find((l) => l.id === id);
                return banner && banner.url && banner.url.startsWith('/data/banners');
              })
            : bannerToDelete &&
              bannerToDelete.url &&
              bannerToDelete.url.startsWith('/data/banners')
        }
        deleteFileLabel={
          isBulkDelete
            ? 'Also delete local banner files from disk'
            : 'Also delete banner file from disk'
        }
      />

      <ConfirmationDialog
        opened={confirmCleanupOpen}
        onClose={() => setConfirmCleanupOpen(false)}
        onConfirm={executeCleanupUnused}
        title="Cleanup Unused Banners"
        message={
          <div>
            Are you sure you want to cleanup {unusedBannersCount} unused banner
            {unusedBannersCount !== 1 ? 's' : ''}?
            <Text size="sm" c="dimmed" mt="xs">
              This will permanently delete all banners that are not currently used
              by any channels, series, or movies.
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
        deleteFileLabel="Also delete local banner files from disk"
      />
    </>
  );
};

export default BannersTable;
