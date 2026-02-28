import { useEffect, useState, useMemo } from 'react';
import {
  flexRender,
  getCoreRowModel,
  getExpandedRowModel,
  useReactTable,
  type ColumnDef,
  type SortingState,
  type ColumnFiltersState,
  type VisibilityState,
  type ExpandedState,
} from '@tanstack/react-table';
import { useTablePreferences } from '~/hooks/useTablePreferences';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '~/components/ui/table';
import { Button } from '~/components/ui/button';
import { Input } from '~/components/ui/input';
import { Badge } from '~/components/ui/badge';
import { Checkbox } from '~/components/ui/checkbox';
import { Skeleton } from '~/components/ui/skeleton';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '~/components/ui/select';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '~/components/ui/dropdown-menu';
import {
  ArrowUpDown,
  ArrowUp,
  ArrowDown,
  Plus,
  Edit,
  Trash2,
  MoreHorizontal,
  RefreshCw,
  AlignJustify,
  AlignLeft,
  AlignCenter,
  ChevronRight,
  ChevronDown,
  Tv2,
  SquarePen,
  SquareMinus,
  ScreenShare,
  EllipsisVertical,
  CirclePlay,
  Copy,
  Pin,
  PinOff,
  ArrowDown01,
  SquarePlus,
  Unlock,
  Lock,
} from 'lucide-react';
import useChannelsTableStore from '~/store/channelsTable';
import API from '~/lib/api';
import useWarningsStore from '~/store/warnings';
import ConfirmationDialog from '~/components/ConfirmationDialog';
import useSettingsStore from '~/store/settings';
import useVideoStore from '~/store/useVideoStore';
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '~/components/ui/popover';
import {
  InputGroup,
  InputGroupAddon,
  InputGroupInput,
} from '~/components/ui/input-group';
import { Field, FieldLabel } from '~/components/ui/field';
import { copyToClipboard } from '~/lib/utils';
import { Switch } from '~/components/ui/switch';
import { Label } from '~/components/ui/label';
import { Separator } from '~/components/ui/separator';
import useAuthStore from '~/store/auth';
import { USER_LEVELS } from '~/lib/constants';
import AssignChannelNumbersForm from './AssignChannelNumbersForm';
import EPGMatchForm from './EPGMatchForm';
import useChannelsStore from '~/store/channels';
import ChannelTableStreams from './ChannelTableStreams';
import {EditableTextCell} from './EditableCell'

type Channel = {
  id: number;
  channel_number: number;
  name: string;
  channel_group_id: number | null;
  enabled: boolean;
  streams: any[];
  logo_id: number | null;
  epg_data_id: number | null;
};

interface ChannelsTableProps {
  m3uUrlBase: string;
  epgUrlBase: string;
  hdhrUrlBase: string;
}

export default function ChannelsTable({
  m3uUrlBase,
  epgUrlBase,
  hdhrUrlBase,
}: ChannelsTableProps) {
  const channels = useChannelsTableStore((s) => s.channels);
  const pagination = useChannelsTableStore((s) => s.pagination);
  const sorting = useChannelsTableStore((s) => s.sorting);
  const totalCount = useChannelsTableStore((s) => s.totalCount);
  const pageCount = useChannelsTableStore((s) => s.pageCount);
  const selectedChannelIds = useChannelsTableStore((s) => s.selectedChannelIds);
  const setPagination = useChannelsTableStore((s) => s.setPagination);
  const setSorting = useChannelsTableStore((s) => s.setSorting);
  const setSelectedChannelIds = useChannelsTableStore(
    (s) => s.setSelectedChannelIds
  );
  const channelGroups = useChannelsTableStore((s) => s.channelGroups);
  const isUnlocked = useChannelsTableStore((s) => s.isUnlocked);
  const setIsUnlocked = useChannelsTableStore((s) => s.setIsUnlocked);

  const channelIds = useChannelsStore((s) => s.channelIds);

  const isWarningSuppressed = useWarningsStore((s) => s.isWarningSuppressed);
  const suppressWarning = useWarningsStore((s) => s.suppressWarning);
  const env_mode = useSettingsStore((s) => s.environment.env_mode);
  const showVideo = useVideoStore((s) => s.showVideo);
  const authUser = useAuthStore((s) => s.user);
  const selectedProfileId = useChannelsStore((s) => s.selectedProfileId);
  const setSelectedProfileId = useChannelsStore((s) => s.setSelectedProfileId);
  const profiles = useChannelsStore((s) => s.profiles);

  const { tableSize, setTableSize } = useTablePreferences();

  const [isLoading, setIsLoading] = useState(false);
  const [columnFilters, setColumnFilters] = useState<ColumnFiltersState>([]);
  const [columnSizing, setColumnSizing] = useState({});
  const [lastSelectedIndex, setLastSelectedIndex] = useState<number | null>(
    null
  );
  const [headerPinned, setHeaderPinned] = useState<boolean>(false);
  const [assignNumbersModalOpen, setAssignNumbersModalOpen] = useState(false);
  const [epgMatchModalOpen, setEpgMatchModalOpen] = useState(false);
  const [expanded, setExpanded] = useState<ExpandedState>({});

  const [hdhrUrl, setHDHRUrl] = useState(hdhrUrlBase);
  const [epgUrl, setEPGUrl] = useState(epgUrlBase);
  const [m3uUrl, setM3UUrl] = useState(m3uUrlBase);

  const [m3uParams, setM3uParams] = useState({
    cachedlogos: true,
    direct: false,
    tvg_id_source: 'channel_number',
  });
  const [epgParams, setEpgParams] = useState({
    cachedlogos: true,
    tvg_id_source: 'channel_number',
    days: 0,
  });

  const [deleting, setDeleting] = useState(false);
  const [isBulkDelete, setIsBulkDelete] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<number | null>(null);
  const [confirmDeleteOpen, setConfirmDeleteOpen] = useState(false);
  const [channelToDelete, setChannelToDelete] = useState<Channel | null>(null);
  const [rowSelection, setRowSelection] = useState<Record<string, boolean>>({});

  // Build initial row selection from selectedChannelIds
  useEffect(() => {
    const newRowSelection: Record<string, boolean> = {};
    selectedChannelIds.forEach((id: number) => {
      newRowSelection[String(id)] = true;
    });
    setRowSelection(newRowSelection);
  }, [selectedChannelIds]);

  // Fetch data when pagination, sorting, or filters change
  useEffect(() => {
    fetchChannels();
  }, [pagination.pageIndex, pagination.pageSize, sorting, columnFilters]);

  const fetchChannels = async () => {
    setIsLoading(true);
    try {
      const params = new URLSearchParams();
      params.append('page', String(pagination.pageIndex + 1));
      params.append('page_size', String(pagination.pageSize));
      params.append('include_streams', 'true');

      // Apply sorting
      if (sorting.length > 0) {
        const sortField = sorting[0].id;
        const sortDirection = sorting[0].desc ? '-' : '';
        params.append('ordering', `${sortDirection}${sortField}`);
      }

      // Apply filters
      columnFilters.forEach((filter) => {
        if (filter.value) {
          params.append(filter.id, String(filter.value));
        }
      });

      await API.queryChannels(params);
    } catch (error) {
      console.error('Error fetching channels:', error);
    } finally {
      setIsLoading(false);
    }
  };

  const deleteChannel = async (id) => {
    console.log(`Deleting channel with ID: ${id}`);

    const rows = table.getRowModel().rows;
    const knownChannel = rows.find((row) => row.original.id === id)?.original;

    table.resetRowSelection();

    if (selectedChannelIds.length > 0) {
      // Use bulk delete for multiple selections
      setIsBulkDelete(true);
      setChannelToDelete(null);

      if (isWarningSuppressed('delete-channels')) {
        // Skip warning if suppressed
        return executeDeleteChannels();
      }

      setConfirmDeleteOpen(true);
      return;
    }

    // Single channel delete
    setIsBulkDelete(false);
    setDeleteTarget(id);
    setChannelToDelete(knownChannel); // Store the channel object for displaying details

    if (isWarningSuppressed('delete-channel')) {
      // Skip warning if suppressed
      return executeDeleteChannel(id);
    }

    setConfirmDeleteOpen(true);
  };

  const executeDeleteChannel = async (id: number) => {
    setDeleting(true);
    try {
      await API.deleteChannel(id);
      API.requeryChannels();
    } finally {
      setDeleting(false);
      setConfirmDeleteOpen(false);
    }
  };

  const deleteChannels = async () => {
    if (isWarningSuppressed('delete-channels')) {
      // Skip warning if suppressed
      return executeDeleteChannels();
    }

    setIsBulkDelete(true);
    setConfirmDeleteOpen(true);
  };

  const executeDeleteChannels = async () => {
    setIsLoading(true);
    setDeleting(true);
    try {
      await API.deleteChannels(selectedChannelIds);
      await API.requeryChannels();
      setSelectedChannelIds([]);
      table.resetRowSelection();
    } finally {
      setDeleting(false);
      setIsLoading(false);
      setConfirmDeleteOpen(false);
    }
  };

  const getChannelURL = (channel) => {
    // Make sure we're using the channel UUID consistently
    if (!channel || !channel.uuid) {
      console.error('Invalid channel object or missing UUID:', channel);
      return '';
    }

    const uri = `/proxy/ts/stream/${channel.uuid}`;
    let channelUrl = `${window.location.protocol}//${window.location.host}${uri}`;
    if (env_mode == 'dev') {
      channelUrl = `${window.location.protocol}//${window.location.hostname}:5656${uri}`;
    }

    return channelUrl;
  };

  const handleWatchStream = (channel) => {
    // Add additional logging to help debug issues
    console.log(
      `Watching stream for channel: ${channel.name} (${channel.id}), UUID: ${channel.uuid}`
    );
    const url = getChannelURL(channel);
    console.log(`Stream URL: ${url}`);
    showVideo(url);
  };

  // Build URLs with parameters
  const buildM3UUrl = () => {
    const params = new URLSearchParams();
    if (!m3uParams.cachedlogos) params.append('cachedlogos', 'false');
    if (m3uParams.direct) params.append('direct', 'true');
    if (m3uParams.tvg_id_source !== 'channel_number')
      params.append('tvg_id_source', m3uParams.tvg_id_source);

    const baseUrl = m3uUrl;
    return params.toString() ? `${baseUrl}?${params.toString()}` : baseUrl;
  };

  const buildEPGUrl = () => {
    const params = new URLSearchParams();
    if (!epgParams.cachedlogos) params.append('cachedlogos', 'false');
    if (epgParams.tvg_id_source !== 'channel_number')
      params.append('tvg_id_source', epgParams.tvg_id_source);
    if (epgParams.days > 0) params.append('days', epgParams.days.toString());

    const baseUrl = epgUrl;
    return params.toString() ? `${baseUrl}?${params.toString()}` : baseUrl;
  };

  const copyM3UUrl = async () => {
    await copyToClipboard(buildM3UUrl(), {
      successTitle: 'M3U URL Copied!',
      successMessage: 'The M3U URL has been copied to your clipboard.',
    });
  };

  const copyEPGUrl = async () => {
    await copyToClipboard(buildEPGUrl(), {
      successTitle: 'EPG URL Copied!',
      successMessage: 'The EPG URL has been copied to your clipboard.',
    });
  };

  const copyHDHRUrl = async () => {
    await copyToClipboard(hdhrUrl, {
      successTitle: 'HDHR URL Copied!',
      successMessage: 'The HDHR URL has been copied to your clipboard.',
    });
  };

  const columns = useMemo<ColumnDef<Channel>[]>(
    () => [
      {
        id: 'expand',
        size: 20,
        enableResizing: false,
        cell: ({ row }) => (
          <Button
            variant="ghost"
            size="sm"
            className="h-4 w-4 p-0"
            onClick={() => row.toggleExpanded()}
          >
            {row.getIsExpanded() ? (
              <ChevronDown className="h-4 w-4" />
            ) : (
              <ChevronRight className="h-4 w-4" />
            )}
          </Button>
        ),
      },
      {
        id: 'select',
        size: 10,
        header: ({ table }) => (
          <Checkbox
            className="!h-4"
            checked={
              selectedChannelIds.length === channelIds.length ||
              (selectedChannelIds.length > 0 && 'indeterminate')
            }
            onCheckedChange={(value) => {
              table.toggleAllPageRowsSelected(!!value);
              setLastSelectedIndex(null);
              setSelectedChannelIds(value ? channelIds : []);
            }}
            aria-label="Select all"
          />
        ),
        cell: ({ row, table }) => (
          <Checkbox
            className="!h-4"
            checked={row.getIsSelected()}
            onCheckedChange={(value) => {
              row.toggleSelected(!!value);
              setLastSelectedIndex(row.index);
            }}
            onClick={(e: React.MouseEvent) => {
              const currentIndex = row.index;

              if (e.shiftKey && lastSelectedIndex !== null) {
                e.preventDefault();
                e.stopPropagation();

                // Shift+click: select range
                const start = Math.min(lastSelectedIndex, currentIndex);
                const end = Math.max(lastSelectedIndex, currentIndex);
                const rows = table.getRowModel().rows;

                // Determine if we're selecting or deselecting based on the target row
                const shouldSelect = !rows[currentIndex]?.getIsSelected();

                // Select/deselect all rows in range
                for (let i = start; i <= end; i++) {
                  if (rows[i]) {
                    rows[i].toggleSelected(shouldSelect);
                  }
                }

                setLastSelectedIndex(currentIndex);
              }
            }}
            aria-label="Select row"
          />
        ),
        enableSorting: false,
        enableHiding: false,
      },
      {
        accessorKey: 'channel_number',
        size: 40,
        header: ({ column }) => {
          return (
            <div className="flex items-center justify-end space-y-2">
              #
              <Button
                variant="ghost"
                size="sm"
                className="-ml-3 h-8"
                onClick={() =>
                  column.toggleSorting(column.getIsSorted() === 'asc')
                }
              >
                {column.getIsSorted() === 'asc' ? (
                  <ArrowUp className="ml-2 h-3 w-3" />
                ) : column.getIsSorted() === 'desc' ? (
                  <ArrowDown className="ml-2 h-3 w-3" />
                ) : (
                  <ArrowUpDown className="ml-2 h-3 w-3" />
                )}
              </Button>
            </div>
          );
        },
        cell: ({ row }) => (
          <div className="text-right overflow-hidden text-ellipsis whitespace-nowrap">
            {row.getValue('channel_number')}
          </div>
        ),
      },
      {
        accessorKey: 'name',
        enableResizing: true,
        header: ({ column }) => {
          return (
            <div className="space-y-2 flex">
              <Input
                placeholder="Name"
                value={(column.getFilterValue() as string) ?? ''}
                onChange={(e) => column.setFilterValue(e.target.value)}
                className="h-8"
              />
              <Button
                variant="ghost"
                size="sm"
                className="-ml-3 h-8"
                onClick={() =>
                  column.toggleSorting(column.getIsSorted() === 'asc')
                }
              >
                {column.getIsSorted() === 'asc' ? (
                  <ArrowUp className="ml-2 h-3 w-3" />
                ) : column.getIsSorted() === 'desc' ? (
                  <ArrowDown className="ml-2 h-3 w-3" />
                ) : (
                  <ArrowUpDown className="ml-2 h-3 w-3" />
                )}
              </Button>
            </div>
          );
        },
        cell: (props) => (
          <div className="font-medium overflow-hidden text-ellipsis whitespace-nowrap">
            <EditableTextCell {...props} />
          </div>
        ),
      },
      {
        id: 'epg',
        accessorKey: 'epg_data_id',
        size: 80,
        enableResizing: true,
        header: ({ column }) => {
          return (
            <div className="space-y-2 flex items-center mb-1">
              EPG
              <Button
                variant="ghost"
                size="sm"
                className="-ml-3 h-8"
                onClick={() =>
                  column.toggleSorting(column.getIsSorted() === 'asc')
                }
              >
                {column.getIsSorted() === 'asc' ? (
                  <ArrowUp className="ml-2 h-3 w-3" />
                ) : column.getIsSorted() === 'desc' ? (
                  <ArrowDown className="ml-2 h-3 w-3" />
                ) : (
                  <ArrowUpDown className="ml-2 h-3 w-3" />
                )}
              </Button>
            </div>
          );
        },
        cell: ({ row }) => (
          <div className="font-medium overflow-hidden text-ellipsis whitespace-nowrap">
            {row.getValue('name')}
          </div>
        ),
      },
      {
        id: 'channel_group',
        enableResizing: true,
        accessorFn: (row) =>
          row.channel_group_id && channelGroups[row.channel_group_id]
            ? channelGroups[row.channel_group_id].name
            : '',
        header: ({ column }) => {
          return (
            <div className="space-y-2 flex">
              <Input
                placeholder="Group"
                value={(column.getFilterValue() as string) ?? ''}
                onChange={(e) => column.setFilterValue(e.target.value)}
                className="h-8"
              />
              <Button
                variant="ghost"
                size="sm"
                className="-ml-3 h-8"
                onClick={() =>
                  column.toggleSorting(column.getIsSorted() === 'asc')
                }
              >
                {column.getIsSorted() === 'asc' ? (
                  <ArrowUp className="ml-2 h-3 w-3" />
                ) : column.getIsSorted() === 'desc' ? (
                  <ArrowDown className="ml-2 h-3 w-3" />
                ) : (
                  <ArrowUpDown className="ml-2 h-3 w-3" />
                )}
              </Button>
            </div>
          );
        },
        cell: ({ row }) => (
          <div className="font-medium overflow-hidden text-ellipsis whitespace-nowrap">
            {row.getValue('name')}
          </div>
        ),
      },
      {
        id: 'logo',
        accessorFn: (row) => {
          // Just pass the logo_id directly, not the full logo object
          return row.logo_id;
        },
        header: '',
        size: 75,
        minSize: 50,
        maxSize: 120,
        enableResizing: false,
        cell: ({ row }) => (
          <div className="font-medium overflow-hidden text-ellipsis whitespace-nowrap">
            {row.getValue('name')}
          </div>
        ),
      },
      {
        id: 'actions',
        size: 70,
        enableResizing: false,
        cell: ({ row }) => {
          return (
            <div className="flex">
              <Button
                variant="ghost"
                size="sm"
                className="text-yellow-500 dark:text-yellow-300 h-4 w-4 p-0 cursor-pointer"
              >
                <Edit />
              </Button>
              <Button
                variant="ghost"
                size="sm"
                className="text-red-500 dark:text-red-500 h-4 w-4 p-0 cursor-pointer"
                onClick={() => deleteChannel(row.original.id)}
              >
                <Trash2 />
              </Button>
              <Button
                variant="ghost"
                size="sm"
                className="text-green-600 dark:text-green-500 h-4 w-4 p-0 cursor-pointer"
                onClick={() => handleWatchStream(row.original)}
              >
                <CirclePlay />
              </Button>
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="text-blue-500 h-4 w-4 p-0 cursor-pointer"
                  >
                    <EllipsisVertical />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent>
                  <DropdownMenuItem
                    className="cursor-pointer"
                    onClick={() => {
                      copyToClipboard(getChannelURL(row.original), {
                        successTitle: 'Channel URL Copied!',
                        successMessage:
                          'The channel stream URL has been copied to your clipboard.',
                      });
                    }}
                  >
                    Copy URL
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
          );
        },
      },
    ],
    [
      lastSelectedIndex,
      setLastSelectedIndex,
      channelGroups,
      channelIds,
      selectedChannelIds,
    ]
  );

  const table = useReactTable({
    data: channels,
    columns,
    pageCount: pageCount,
    enableColumnResizing: true,
    columnResizeMode: 'onChange',
    getRowId: (row) => String(row.id), // Use channel ID as row ID
    state: {
      pagination,
      sorting,
      columnFilters,
      columnSizing,
      rowSelection: rowSelection,
      expanded,
    },
    enableRowSelection: true,
    onExpandedChange: (updater) => {
      const newExpanded =
        typeof updater === 'function' ? updater(expanded) : updater;
      // Only allow one row to be expanded at a time
      const expandedKeys = Object.keys(newExpanded).filter(
        (key) => newExpanded[key as keyof typeof newExpanded]
      );
      const diff = Object.keys(newExpanded).filter(
        (item) => !Object.keys(expanded).includes(item)
      );
      setExpanded({ [diff[0]]: true });
    },
    onRowSelectionChange: (updater) => {
      const newSelection =
        typeof updater === 'function' ? updater(rowSelection) : updater;
      setRowSelection(newSelection);

      // Extract channel IDs from selection object and sync to store
      const selectedIds = Object.keys(newSelection)
        .filter((key) => newSelection[key])
        .map((id) => Number(id));
      setSelectedChannelIds(selectedIds);
    },
    onPaginationChange: setPagination,
    onSortingChange: setSorting,
    onColumnFiltersChange: setColumnFilters,
    onColumnSizingChange: setColumnSizing,
    getCoreRowModel: getCoreRowModel(),
    getExpandedRowModel: getExpandedRowModel(),
    manualPagination: true,
    manualSorting: true,
    manualFiltering: true,
  });

  return (
    <div className="flex h-full flex-col gap-2">
      {/* Header */}
      <div className="flex flex-shrink-0 items-center justify-between">
        <div className="flex items-center">
          <h1 className="text-2xl tracking-tight">Channels</h1>
          <div className="flex px-2 items-center gap-2">
            <h3 className="text-sm text-muted-foreground">Links:</h3>

            <Popover>
              <PopoverTrigger asChild>
                <div className="cursor-pointer flex rounded-sm text-sm gap-2 border-1 px-2 py-0.5 items-center dark:text-lime-500 dark:border-lime-500 text-lime-700 border-lime-700 bg-lime-100 dark:bg-inherit">
                  <Tv2 size={16} />
                  HDHR
                </div>
              </PopoverTrigger>
              <PopoverContent>
                <InputGroup>
                  <InputGroupInput placeholder={hdhrUrl} disabled />
                  <InputGroupAddon align="inline-end">
                    <Button variant="ghost" onClick={copyHDHRUrl}>
                      <Copy />
                    </Button>
                  </InputGroupAddon>
                </InputGroup>
              </PopoverContent>
            </Popover>

            <Popover>
              <PopoverTrigger asChild>
                <div className="cursor-pointer flex rounded-sm text-sm gap-2 border-1 px-2 py-0.5 items-center text-indigo-500 border-indigo-500 dark:bg-inherit bg-indigo-100">
                  <ScreenShare size={16} />
                  M3U
                </div>
              </PopoverTrigger>
              <PopoverContent className="flex flex-col gap-4">
                <Field>
                  <FieldLabel htmlFor="m3u-url" className="font-light">
                    Generated URL
                  </FieldLabel>
                  <InputGroup>
                    <InputGroupInput
                      id="m3u-url"
                      placeholder={m3uUrl}
                      disabled
                    />
                    <InputGroupAddon align="inline-end">
                      <Button variant="ghost" onClick={copyM3UUrl}>
                        <Copy />
                      </Button>
                    </InputGroupAddon>
                  </InputGroup>
                </Field>

                <div className="flex items-center justify-between space-x-2">
                  <Label htmlFor="use-cached-logos" className="font-light">
                    Use Cached Logos
                  </Label>
                  <Switch
                    id="use-cached-logos"
                    checked={m3uParams.cachedlogos}
                    onCheckedChange={(val) =>
                      setM3uParams((prev) => ({
                        ...prev,
                        cachedlogos: val,
                      }))
                    }
                  />
                </div>

                <div className="flex items-center justify-between space-x-2">
                  <Label htmlFor="direct-stream-urls" className="font-light">
                    Direct Stream URLs
                  </Label>
                  <Switch
                    id="direct-stream-urls"
                    checked={m3uParams.direct}
                    onCheckedChange={(val) =>
                      setM3uParams((prev) => ({
                        ...prev,
                        direct: val,
                      }))
                    }
                  />
                </div>

                <div className="space-y-2">
                  <Label htmlFor="tvg-id-source" className="font-light">
                    TVG-ID Source
                  </Label>
                  <Select
                    value={m3uParams.tvg_id_source}
                    onValueChange={(value) =>
                      setM3uParams((prev) => ({
                        ...prev,
                        tvg_id_source: value,
                      }))
                    }
                  >
                    <SelectTrigger id="tvg-id-source" className="w-full">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {[
                        { value: 'channel_number', label: 'Channel Number' },
                        { value: 'tvg_id', label: 'TVG-ID' },
                        { value: 'gracenote', label: 'Gracenote Station ID' },
                      ].map((option) => (
                        <SelectItem key={option.value} value={option.value}>
                          {option.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              </PopoverContent>
            </Popover>

            <Popover>
              <PopoverTrigger asChild>
                <div className="cursor-pointer flex rounded-sm text-sm gap-2 border-1 px-2 py-0.5 items-center text-zinc-500 border-zinc-500 dark:bg-inherit bg-zinc-100">
                  <ScreenShare size={16} />
                  EPG
                </div>
              </PopoverTrigger>
              <PopoverContent className="flex flex-col gap-4">
                <Field>
                  <FieldLabel htmlFor="epg-url" className="font-light">
                    Generated URL
                  </FieldLabel>
                  <InputGroup>
                    <InputGroupInput
                      id="epg-url"
                      placeholder={epgUrl}
                      disabled
                    />
                    <InputGroupAddon align="inline-end">
                      <Button variant="ghost" onClick={copyEPGUrl}>
                        <Copy />
                      </Button>
                    </InputGroupAddon>
                  </InputGroup>
                </Field>

                <div className="flex items-center justify-between space-x-2">
                  <Label htmlFor="use-cached-logos" className="font-light">
                    Use Cached Logos
                  </Label>
                  <Switch
                    id="use-cached-logos"
                    checked={epgParams.cachedlogos}
                    onCheckedChange={(val) =>
                      setEpgParams((prev) => ({
                        ...prev,
                        cachedlogos: val,
                      }))
                    }
                  />
                </div>

                <div className="space-y-2">
                  <Label htmlFor="tvg-id-source" className="font-light">
                    TVG-ID Source
                  </Label>
                  <Select
                    value={epgParams.tvg_id_source}
                    onValueChange={(value) =>
                      setEpgParams((prev) => ({
                        ...prev,
                        tvg_id_source: value,
                      }))
                    }
                  >
                    <SelectTrigger id="tvg-id-source" className="w-full">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {[
                        { value: 'channel_number', label: 'Channel Number' },
                        { value: 'tvg_id', label: 'TVG-ID' },
                        { value: 'gracenote', label: 'Gracenote Station ID' },
                      ].map((option) => (
                        <SelectItem key={option.value} value={option.value}>
                          {option.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>

                <div className="space-y-2">
                  <Label htmlFor="days" className="font-light">
                    Days (0 = all data)
                  </Label>
                  <Input
                    type="number"
                    min={0}
                    value={epgParams.days}
                    onChange={(e) =>
                      setEpgParams((prev) => ({
                        ...prev,
                        days: e.target.value || 0,
                      }))
                    }
                  />
                </div>
              </PopoverContent>
            </Popover>
          </div>
        </div>
      </div>

      {/* Data Table */}
      <div className="flex justify-between">
        <div className="flex items-center gap-1">
          <Select
            value={selectedProfileId}
            onValueChange={setSelectedProfileId}
          >
            <SelectTrigger className="w-[190px]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {Object.values(profiles).map((profile) => (
                <SelectItem value={profile.id}>{profile.name}</SelectItem>
              ))}
            </SelectContent>
          </Select>

          <div className="cursor-pointer text-green-500">
            <SquarePlus size={24} />
          </div>

          {isUnlocked && (
            <div className="flex text-sm gap-1 pl-4 items-center text-yellow-500">
              <Unlock size={16} />
              Editing Mode
            </div>
          )}
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={fetchChannels}>
            <SquarePen className="h-4 w-4 rounded-sm" />
            Edit
          </Button>
          <Button variant="outline" size="sm" onClick={fetchChannels}>
            <SquareMinus className={`h-4 w-4`} />
            Delete
          </Button>
          <Button
            variant="ghost"
            size="sm"
            className="rounded-sm border-1 border-green-500 bg-green-200 dark:bg-green-950"
          >
            <Plus />
            Add
          </Button>

          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="outline" size="sm" className="w-8">
                <EllipsisVertical />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem onClick={() => setHeaderPinned(!headerPinned)}>
                {headerPinned ? (
                  <Pin className="mr-2 h-4 w-4" />
                ) : (
                  <PinOff className="mr-2 h-4 w-4" />
                )}
                {headerPinned ? 'Unpin Header' : 'Pin Header'}
              </DropdownMenuItem>

<DropdownMenuItem onClick={() => setIsUnlocked(!isUnlocked)}>
                {isUnlocked ? (
                  <Unlock className="mr-2 h-4 w-4" />
                ) : (
                  <Lock className="mr-2 h-4 w-4" />
                )}
                {isUnlocked ? 'Lock Table' : 'Unlock for Editing'}
              </DropdownMenuItem>

              <Separator />
              <DropdownMenuItem
                disabled={
                  selectedChannelIds.length === 0 ||
                  authUser.user_level != USER_LEVELS.ADMIN
                }
                onClick={() => setAssignNumbersModalOpen(true)}
              >
                <ArrowDown01 className="mr-2 h-4 w-4" />
                Assign #s
              </DropdownMenuItem>

              <DropdownMenuItem
                disabled={authUser.user_level != USER_LEVELS.ADMIN}
                onClick={() => setEpgMatchModalOpen(true)}
              >
                <AlignJustify className="mr-2 h-4 w-4" />
                {selectedChannelIds.length > 0
                  ? `Auto-Match (${selectedChannelIds.length} selected)`
                  : 'Auto-Match EPG'}
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>
      <div className="relative scrollbar-overlay min-h-0 flex-1 overflow-auto rounded-md border">
        <table
          style={{
            minWidth: '100%',
            width: table.getTotalSize(),
            tableLayout: 'fixed',
          }}
          className={`${
            tableSize === 'compact'
              ? 'table-compact'
              : tableSize === 'large'
                ? 'table-large'
                : ''
          }`}
        >
          <TableHeader
            className={`top-0 z-10 !bg-background ${headerPinned ? 'sticky' : ''}`}
          >
            {table.getHeaderGroups().map((headerGroup) => (
              <TableRow key={headerGroup.id}>
                {headerGroup.headers.map((header) => (
                  <TableHead
                    key={header.id}
                    style={{
                      width: `${header.getSize()}px`,
                      position: 'relative',
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                    }}
                  >
                    {header.isPlaceholder
                      ? null
                      : flexRender(
                          header.column.columnDef.header,
                          header.getContext()
                        )}
                    {header.column.getCanResize() && (
                      <div
                        onMouseDown={header.getResizeHandler()}
                        onTouchStart={header.getResizeHandler()}
                        className={`resizer ${
                          header.column.getIsResizing() ? 'isResizing' : ''
                        }`}
                      />
                    )}
                  </TableHead>
                ))}
              </TableRow>
            ))}
          </TableHeader>
          <TableBody>
            {isLoading ? (
              Array.from({ length: pagination.pageSize }).map((_, i) => (
                <TableRow key={i}>
                  {table.getAllColumns().map((column) => (
                    <TableCell
                      key={column.id}
                      style={{
                        width: `${column.getSize()}px`,
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                      }}
                    >
                      <Skeleton className="my-1 h-6 w-full" />
                    </TableCell>
                  ))}
                </TableRow>
              ))
            ) : table.getRowModel().rows?.length ? (
              table.getRowModel().rows.map((row) => (
                <>
                  <TableRow
                    key={row.id}
                    data-state={row.getIsSelected() && 'selected'}
                    className={`${row.original.streams && row.original.streams.length > 0 ? '' : 'bg-red-900/30'}`}
                  >
                    {row.getVisibleCells().map((cell) => (
                      <TableCell
                        key={cell.id}
                        style={{
                          width: `${cell.column.getSize()}px`,
                          overflow: 'hidden',
                          textOverflow: 'ellipsis',
                        }}
                      >
                        {flexRender(
                          cell.column.columnDef.cell,
                          cell.getContext()
                        )}
                      </TableCell>
                    ))}
                  </TableRow>
                  {row.getIsExpanded() && (
                    <TableRow className="bg-primary/25">
                      <TableCell colSpan={row.getVisibleCells().length}>
                        <ChannelTableStreams
                          channel={row.original}
                          isExpanded={true}
                        />
                      </TableCell>
                    </TableRow>
                  )}
                </>
              ))
            ) : (
              <TableRow>
                <TableCell
                  colSpan={columns.length}
                  className="h-24 text-center"
                >
                  No channels found
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </table>
      </div>

      {/* Pagination */}
      <div className="flex flex-shrink-0 items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-sm text-muted-foreground">Page Size</span>
          <Select
            value={String(pagination.pageSize)}
            onValueChange={(value) => {
              setPagination({
                ...pagination,
                pageSize: Number(value),
                pageIndex: 0,
              });
            }}
          >
            <SelectTrigger className="h-8 w-[70px]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {[5, 10, 25, 50, 100].map((size) => (
                <SelectItem key={size} value={String(size)}>
                  {size}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() =>
              setPagination({
                ...pagination,
                pageIndex: pagination.pageIndex - 1,
              })
            }
            disabled={!table.getCanPreviousPage() || isLoading}
          >
            Previous
          </Button>
          <span className="text-sm text-muted-foreground">
            Page {pagination.pageIndex + 1} of {pageCount}
          </span>
          <Button
            variant="outline"
            size="sm"
            onClick={() =>
              setPagination({
                ...pagination,
                pageIndex: pagination.pageIndex + 1,
              })
            }
            disabled={!table.getCanNextPage() || isLoading}
          >
            Next
          </Button>
        </div>
      </div>

      <AssignChannelNumbersForm
        channelIds={selectedChannelIds}
        isOpen={assignNumbersModalOpen}
        onClose={() => setAssignNumbersModalOpen(false)}
      />

      <EPGMatchForm
        isOpen={epgMatchModalOpen}
        onClose={() => setEpgMatchModalOpen(false)}
        channelIds={selectedChannelIds}
      />

      <ConfirmationDialog
        open={confirmDeleteOpen}
        onOpenChange={setConfirmDeleteOpen}
        onConfirm={() =>
          isBulkDelete
            ? executeDeleteChannels()
            : executeDeleteChannel(deleteTarget)
        }
        loading={deleting}
        title={`Confirm ${isBulkDelete ? 'Bulk ' : ''}Channel Deletion`}
        message={
          isBulkDelete ? (
            `Are you sure you want to delete ${table.selectedTableIds.length} channels? This action cannot be undone.`
          ) : channelToDelete ? (
            <div style={{ whiteSpace: 'pre-line' }}>
              {`Are you sure you want to delete the following channel?

Name: ${channelToDelete.name}
Channel Number: ${channelToDelete.channel_number}

This action cannot be undone.`}
            </div>
          ) : (
            'Are you sure you want to delete this channel? This action cannot be undone.'
          )
        }
        confirmLabel="Delete"
        cancelLabel="Cancel"
        actionKey={isBulkDelete ? 'delete-channels' : 'delete-channel'}
        onSuppressChange={suppressWarning}
        size="md"
      />
    </div>
  );
}
