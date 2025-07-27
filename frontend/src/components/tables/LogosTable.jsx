import React, { useMemo, useCallback, useState, useEffect } from 'react';
import API from '../../api';
import LogoForm from '../forms/Logo';
import useChannelsStore from '../../store/channels';
import useEPGsStore from '../../store/epgs';
import useLocalStorage from '../../hooks/useLocalStorage';
import {
    SquarePlus,
    SquareMinus,
    SquarePen,
    ExternalLink,
    Filter,
    Trash2,
    Trash,
    Download,
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

const LogoRowActions = ({ theme, row, editLogo, deleteLogo }) => {
    const [tableSize, _] = useLocalStorage('table-size', 'default');

    const onEdit = useCallback(() => {
        editLogo(row.original);
    }, [row.original, editLogo]);

    const onDelete = useCallback(() => {
        deleteLogo(row.original.id);
    }, [row.original.id, deleteLogo]);

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

const LogosTable = () => {
    const theme = useMantineTheme();

    /**
     * STORES
     */
    const { logos, fetchLogos } = useChannelsStore();
    const { epgs } = useEPGsStore();

    /**
     * useState
     */
    const [selectedLogo, setSelectedLogo] = useState(null);
    const [logoModalOpen, setLogoModalOpen] = useState(false);
    const [confirmDeleteOpen, setConfirmDeleteOpen] = useState(false);
    const [deleteTarget, setDeleteTarget] = useState(null);
    const [logoToDelete, setLogoToDelete] = useState(null);
    const [isLoading, setIsLoading] = useState(false);
    const [confirmCleanupOpen, setConfirmCleanupOpen] = useState(false);
    const [isBulkDelete, setIsBulkDelete] = useState(false);
    const [isCleaningUp, setIsCleaningUp] = useState(false);
    const [isDownloadingFromEPG, setIsDownloadingFromEPG] = useState(false);
    const [filters, setFilters] = useState({
        name: '',
        used: 'all'
    });
    const [debouncedNameFilter, setDebouncedNameFilter] = useState('');
    const [selectedRows, setSelectedRows] = useState(new Set());
    const [pageSize, setPageSize] = useLocalStorage('logos-page-size', 25);
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
        const logosArray = Object.values(logos || {});

        // Apply filters
        let filteredLogos = logosArray;

        if (debouncedNameFilter) {
            filteredLogos = filteredLogos.filter(logo =>
                logo.name.toLowerCase().includes(debouncedNameFilter.toLowerCase())
            );
        }

        if (filters.used === 'used') {
            filteredLogos = filteredLogos.filter(logo => logo.is_used);
        } else if (filters.used === 'unused') {
            filteredLogos = filteredLogos.filter(logo => !logo.is_used);
        }

        return filteredLogos.sort((a, b) => a.id - b.id);
    }, [logos, debouncedNameFilter, filters.used]);

    // Get paginated data
    const paginatedData = useMemo(() => {
        const startIndex = pagination.pageIndex * pagination.pageSize;
        const endIndex = startIndex + pagination.pageSize;
        return data.slice(startIndex, endIndex);
    }, [data, pagination.pageIndex, pagination.pageSize]);

    // Calculate unused logos count
    const unusedLogosCount = useMemo(() => {
        const allLogos = Object.values(logos || {});
        return allLogos.filter(logo => !logo.is_used).length;
    }, [logos]);

    // Check if any Schedules Direct EPG sources exist
    const hasSchedulesDirectSources = useMemo(() => {
        const epgSources = Object.values(epgs || {});
        return epgSources.some(epg => epg.source_type === 'schedules_direct');
    }, [epgs]);

    /**
     * Functions
     */
    const executeDeleteLogo = useCallback(async (id, deleteFile = false) => {
        setIsLoading(true);
        try {
            await API.deleteLogo(id, deleteFile);
            await fetchLogos();
            notifications.show({
                title: 'Success',
                message: 'Logo deleted successfully',
                color: 'green',
            });
        } catch (error) {
            notifications.show({
                title: 'Error',
                message: 'Failed to delete logo',
                color: 'red',
            });
        } finally {
            setIsLoading(false);
            setConfirmDeleteOpen(false);
            setDeleteTarget(null);
            setLogoToDelete(null);
            setIsBulkDelete(false);
            setSelectedRows(new Set()); // Clear selections
        }
    }, [fetchLogos]);

    const executeBulkDelete = useCallback(async (deleteFiles = false) => {
        if (selectedRows.size === 0) return;

        setIsLoading(true);
        try {
            await API.deleteLogos(Array.from(selectedRows), deleteFiles);
            await fetchLogos();

            notifications.show({
                title: 'Success',
                message: `${selectedRows.size} logos deleted successfully`,
                color: 'green',
            });
        } catch (error) {
            notifications.show({
                title: 'Error',
                message: 'Failed to delete logos',
                color: 'red',
            });
        } finally {
            setIsLoading(false);
            setConfirmDeleteOpen(false);
            setIsBulkDelete(false);
            setSelectedRows(new Set()); // Clear selections
        }
    }, [selectedRows, fetchLogos]);

    const executeCleanupUnused = useCallback(async (deleteFiles = false) => {
        setIsCleaningUp(true);
        try {
            const result = await API.cleanupUnusedLogos(deleteFiles);
            await fetchLogos(); // Refresh the logos list

            let message = `Successfully deleted ${result.deleted_count} unused logos`;
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
                message: 'Failed to cleanup unused logos',
                color: 'red',
            });
        } finally {
            setIsCleaningUp(false);
            setConfirmCleanupOpen(false);
            setSelectedRows(new Set()); // Clear selections after cleanup
        }
    }, [fetchLogos]);

    const editLogo = useCallback(async (logo = null) => {
        setSelectedLogo(logo);
        setLogoModalOpen(true);
    }, []);

    const deleteLogo = useCallback(async (id) => {
        const logosArray = Object.values(logos || {});
        const logo = logosArray.find((l) => l.id === id);
        setLogoToDelete(logo);
        setDeleteTarget(id);
        setIsBulkDelete(false);
        setConfirmDeleteOpen(true);
    }, [logos]);

    const handleSelectRow = useCallback((id, checked) => {
        setSelectedRows(prev => {
            const newSet = new Set(prev);
            if (checked) {
                newSet.add(id);
            } else {
                newSet.delete(id);
            }
            return newSet;
        });
    }, []);

    const handleSelectAll = useCallback((checked) => {
        if (checked) {
            setSelectedRows(new Set(data.map(logo => logo.id)));
        } else {
            setSelectedRows(new Set());
        }
    }, [data]);

    const deleteBulkLogos = useCallback(() => {
        if (selectedRows.size === 0) return;

        setIsBulkDelete(true);
        setLogoToDelete(null);
        setDeleteTarget(Array.from(selectedRows));
        setConfirmDeleteOpen(true);
    }, [selectedRows]);

    const handleCleanupUnused = useCallback(() => {
        setConfirmCleanupOpen(true);
    }, []);

    const downloadLogosFromEPG = useCallback(async () => {
        setIsDownloadingFromEPG(true);
        try {
            const result = await API.downloadLogosFromEPG();
            await fetchLogos(); // Refresh the logos list

            notifications.show({
                title: 'Download Complete',
                message: `Successfully downloaded ${result.downloaded_count || 0} logos from Schedules Direct`,
                color: 'green',
            });
        } catch (error) {
            notifications.show({
                title: 'Download Failed',
                message: 'Failed to download logos from Schedules Direct',
                color: 'red',
            });
        } finally {
            setIsDownloadingFromEPG(false);
        }
    }, [fetchLogos]);

    // Clear selections when logos data changes (e.g., after filtering)
    useEffect(() => {
        setSelectedRows(new Set());
    }, [data.length]);

    // Update pagination when pageSize changes
    useEffect(() => {
        setPagination(prev => ({
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
                        indeterminate={selectedRows.size > 0 && selectedRows.size < data.length}
                        onChange={(event) => handleSelectAll(event.currentTarget.checked)}
                        size="sm"
                    />
                ),
                cell: ({ row }) => (
                    <Checkbox
                        checked={selectedRows.has(row.original.id)}
                        onChange={(event) => handleSelectRow(row.original.id, event.currentTarget.checked)}
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
                size: 200,
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

                    return (
                        <Tooltip
                            label={
                                <div>
                                    <Text size="xs" fw={600}>Used by {count} channel{count !== 1 ? 's' : ''}:</Text>
                                    {channelNames.map((name, index) => (
                                        <Text key={index} size="xs">• {name}</Text>
                                    ))}
                                </div>
                            }
                            multiline
                            width={220}
                        >
                            <Badge size="sm" variant="light" color="blue">
                                {count} channel{count !== 1 ? 's' : ''}
                            </Badge>
                        </Tooltip>
                    );
                },
            },
            {
                header: 'URL',
                accessorKey: 'url',
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
                        editLogo={editLogo}
                        deleteLogo={deleteLogo}
                    />
                ),
            },
        ],
        [theme, editLogo, deleteLogo, selectedRows, handleSelectRow, handleSelectAll, data.length]
    );

    const closeLogoForm = () => {
        setSelectedLogo(null);
        setLogoModalOpen(false);
        fetchLogos(); // Refresh the logos list
    };

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
        setPagination(prev => ({
            ...prev,
            pageSize: newPageSize,
            pageIndex: 0, // Reset to first page
        }));
    };

    const onPageIndexChange = (pageIndex) => {
        if (!pageIndex || pageIndex > pageCount) {
            return;
        }

        setPagination(prev => ({
            ...prev,
            pageIndex: pageIndex - 1,
        }));
    };

    const table = useTable({
        columns,
        data: paginatedData,
        allRowIds: paginatedData.map((logo) => logo.id),
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
                            Logos
                        </Text>
                        <Text size="sm" c="dimmed">
                            ({data.length} logo{data.length !== 1 ? 's' : ''})
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
                                        setFilters(prev => ({
                                            ...prev,
                                            name: value
                                        }));
                                    }}
                                    size="xs"
                                    style={{ width: 200 }}
                                />
                                <Select
                                    placeholder="Usage filter"
                                    value={filters.used}
                                    onChange={(value) =>
                                        setFilters(prev => ({
                                            ...prev,
                                            used: value
                                        }))
                                    }
                                    data={[
                                        { value: 'all', label: 'All logos' },
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
                                    disabled={unusedLogosCount === 0}
                                >
                                    Cleanup Unused {unusedLogosCount > 0 ? `(${unusedLogosCount})` : ''}
                                </Button>

                                <Button
                                    leftSection={<SquareMinus size={18} />}
                                    variant="default"
                                    size="xs"
                                    onClick={deleteBulkLogos}
                                    disabled={selectedRows.size === 0}
                                >
                                    Delete {selectedRows.size > 0 ? `(${selectedRows.size})` : ''}
                                </Button>

                                {hasSchedulesDirectSources && (
                                    <Button
                                        leftSection={<Download size={16} />}
                                        variant="light"
                                        size="xs"
                                        color="blue"
                                        onClick={downloadLogosFromEPG}
                                        loading={isDownloadingFromEPG}
                                    >
                                        Download from Schedules Direct
                                    </Button>
                                )}

                                <Button
                                    leftSection={<SquarePlus size={18} />}
                                    variant="light"
                                    size="xs"
                                    onClick={() => editLogo()}
                                    p={5}
                                    color={theme.tailwind.green[5]}
                                    style={{
                                        borderWidth: '1px',
                                        borderColor: theme.tailwind.green[5],
                                        color: 'white',
                                    }}
                                >
                                    Add Logo
                                </Button>
                            </Group>
                        </Box>

                        {/* Table container */}
                        <Box
                            style={{
                                position: 'relative',
                                borderRadius: '0 0 var(--mantine-radius-md) var(--mantine-radius-md)',
                            }}
                        >
                            <Box
                                style={{
                                    overflow: 'auto',
                                    height: 'calc(100vh - 200px)',
                                }}
                            >
                                <div >
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

            <LogoForm
                logo={selectedLogo}
                isOpen={logoModalOpen}
                onClose={closeLogoForm}
            />

            <ConfirmationDialog
                opened={confirmDeleteOpen}
                onClose={() => setConfirmDeleteOpen(false)}
                onConfirm={(deleteFiles) => {
                    if (isBulkDelete) {
                        executeBulkDelete(deleteFiles);
                    } else {
                        executeDeleteLogo(deleteTarget, deleteFiles);
                    }
                }}
                title={isBulkDelete ? "Delete Multiple Logos" : "Delete Logo"}
                message={
                    isBulkDelete ? (
                        <div>
                            Are you sure you want to delete {selectedRows.size} selected logos?
                            <Text size="sm" c="dimmed" mt="xs">
                                Any channels using these logos will have their logo removed.
                            </Text>
                            <Text size="sm" c="dimmed" mt="xs">
                                This action cannot be undone.
                            </Text>
                        </div>
                    ) : logoToDelete ? (
                        <div>
                            Are you sure you want to delete the logo "{logoToDelete.name}"?
                            {logoToDelete.channel_count > 0 && (
                                <Text size="sm" c="orange" mt="xs">
                                    This logo is currently used by {logoToDelete.channel_count} channel{logoToDelete.channel_count !== 1 ? 's' : ''}. They will have their logo removed.
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
                    isBulkDelete
                        ? Array.from(selectedRows).some(id => {
                            const logo = Object.values(logos).find(l => l.id === id);
                            return logo && logo.url && logo.url.startsWith('/data/logos');
                        })
                        : logoToDelete && logoToDelete.url && logoToDelete.url.startsWith('/data/logos')
                }
                deleteFileLabel={
                    isBulkDelete
                        ? "Also delete local logo files from disk"
                        : "Also delete logo file from disk"
                }
            />

            <ConfirmationDialog
                opened={confirmCleanupOpen}
                onClose={() => setConfirmCleanupOpen(false)}
                onConfirm={executeCleanupUnused}
                title="Cleanup Unused Logos"
                message={
                    <div>
                        Are you sure you want to cleanup {unusedLogosCount} unused logo{unusedLogosCount !== 1 ? 's' : ''}?
                        <Text size="sm" c="dimmed" mt="xs">
                            This will permanently delete all logos that are not currently used by any channels.
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
        </>
    );
};

export default LogosTable;
