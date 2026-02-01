import React, { useMemo, useState, useEffect } from 'react';
import API from '../../api';
import { copyToClipboard } from '../../utils';
import {
  GripHorizontal,
  SquareMinus,
  ChevronDown,
  ChevronRight,
  Eye,
} from 'lucide-react';
import {
  Box,
  ActionIcon,
  Flex,
  Text,
  useMantineTheme,
  Center,
  Badge,
  Group,
  Tooltip,
  Collapse,
  Button,
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import {
  useReactTable,
  getCoreRowModel,
  flexRender,
} from '@tanstack/react-table';
import './table.css';
import useChannelsTableStore from '../../store/channelsTable';
import usePlaylistsStore from '../../store/playlists';
import useVideoStore from '../../store/useVideoStore';
import useSettingsStore from '../../store/settings';
import {
  DndContext,
  KeyboardSensor,
  MouseSensor,
  TouchSensor,
  closestCenter,
  useDraggable,
  useSensor,
  useSensors,
} from '@dnd-kit/core';
import { restrictToVerticalAxis } from '@dnd-kit/modifiers';
import {
  arrayMove,
  SortableContext,
  verticalListSortingStrategy,
} from '@dnd-kit/sortable';
import { useSortable } from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import { shallow } from 'zustand/shallow';
import useAuthStore from '../../store/auth';
import { USER_LEVELS } from '../../constants';

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
const DraggableRow = ({ row, index }) => {
  const { transform, transition, setNodeRef, isDragging } = useSortable({
    id: row.original.id,
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
      key={row.id}
      className={`tr ${index % 2 == 0 ? 'tr-even' : 'tr-odd'}`}
      style={{
        ...style,
        display: 'flex',
        width: '100%',
        ...(row.getIsSelected() && {
          backgroundColor: '#163632',
        }),
      }}
    >
      {row.getVisibleCells().map((cell) => {
        const isStale = row.original.is_stale;
        return (
          <Box
            className="td"
            key={cell.id}
            style={{
              flex: cell.column.columnDef.size ? '0 0 auto' : '1 1 0',
              width: cell.column.columnDef.size
                ? cell.column.getSize()
                : undefined,
              minWidth: 0,
              ...(isStale && {
                backgroundColor: 'rgba(239, 68, 68, 0.15)',
              }),
            }}
          >
            <Flex align="center" style={{ height: '100%' }}>
              <Text component="div" size="xs">
                {flexRender(cell.column.columnDef.cell, cell.getContext())}
              </Text>
            </Flex>
          </Box>
        );
      })}
    </Box>
  );
};

const ChannelStreams = ({ channel, isExpanded }) => {
  const theme = useMantineTheme();

  const channelStreams = useChannelsTableStore(
    (state) => state.getChannelStreams(channel.id),
    shallow
  );
  const playlists = usePlaylistsStore((s) => s.playlists);
  const authUser = useAuthStore((s) => s.user);
  const showVideo = useVideoStore((s) => s.showVideo);
  const env_mode = useSettingsStore((s) => s.environment.env_mode);
  function handleWatchStream(streamHash) {
    let vidUrl = `/proxy/ts/stream/${streamHash}`;
    if (env_mode === 'dev') {
      vidUrl = `${window.location.protocol}//${window.location.hostname}:5656${vidUrl}`;
    }
    showVideo(vidUrl);
  }

  const [data, setData] = useState(channelStreams || []);

  useEffect(() => {
    setData(channelStreams);
  }, [channelStreams]);

  const dataIds = data?.map(({ id }) => id);

  const removeStream = async (stream) => {
    const newStreamList = data.filter((s) => s.id !== stream.id);
    await API.updateChannel({
      ...channel,
      streams: newStreamList.map((s) => s.id),
    });
    await API.requeryChannels();
    await API.requeryStreams();
  };

  // Create M3U account map for quick lookup
  const m3uAccountsMap = useMemo(() => {
    const map = {};
    if (playlists && Array.isArray(playlists)) {
      playlists.forEach((account) => {
        if (account.id) {
          map[account.id] = account.name;
        }
      });
    }
    return map;
  }, [playlists]);

  // Add state for tracking which streams have advanced stats expanded
  const [expandedAdvancedStats, setExpandedAdvancedStats] = useState(new Set());

  // Helper function to categorize stream stats
  const categorizeStreamStats = (stats) => {
    if (!stats)
      return { basic: {}, video: {}, audio: {}, technical: {}, other: {} };

    const categories = {
      basic: {},
      video: {},
      audio: {},
      technical: {},
      other: {},
    };

    // Define which stats go in which category
    const categoryMapping = {
      basic: [
        'resolution',
        'video_codec',
        'source_fps',
        'audio_codec',
        'audio_channels',
      ],
      video: [
        'video_bitrate',
        'pixel_format',
        'width',
        'height',
        'aspect_ratio',
        'frame_rate',
      ],
      audio: [
        'audio_bitrate',
        'sample_rate',
        'audio_format',
        'audio_channels_layout',
      ],
      technical: [
        'stream_type',
        'container_format',
        'duration',
        'file_size',
        'ffmpeg_output_bitrate',
        'input_bitrate',
      ],
      other: [], // Will catch anything not categorized above
    };

    // Categorize each stat
    Object.entries(stats).forEach(([key, value]) => {
      let categorized = false;

      for (const [category, keys] of Object.entries(categoryMapping)) {
        if (keys.includes(key)) {
          categories[category][key] = value;
          categorized = true;
          break;
        }
      }

      // If not categorized, put it in 'other'
      if (!categorized) {
        categories.other[key] = value;
      }
    });

    return categories;
  };

  // Function to format stat values for display
  const formatStatValue = (key, value) => {
    if (value === null || value === undefined) return 'N/A';

    // Handle specific formatting cases
    switch (key) {
      case 'video_bitrate':
      case 'audio_bitrate':
      case 'ffmpeg_output_bitrate':
        return `${value} kbps`;
      case 'source_fps':
      case 'frame_rate':
        return `${value} fps`;
      case 'sample_rate':
        return `${value} Hz`;
      case 'file_size':
        // Convert bytes to appropriate unit
        if (typeof value === 'number') {
          if (value < 1024) return `${value} B`;
          if (value < 1024 * 1024) return `${(value / 1024).toFixed(2)} KB`;
          if (value < 1024 * 1024 * 1024)
            return `${(value / (1024 * 1024)).toFixed(2)} MB`;
          return `${(value / (1024 * 1024 * 1024)).toFixed(2)} GB`;
        }
        return value;
      case 'duration':
        // Format duration if it's in seconds
        if (typeof value === 'number') {
          const hours = Math.floor(value / 3600);
          const minutes = Math.floor((value % 3600) / 60);
          const seconds = Math.floor(value % 60);
          return `${hours.toString().padStart(2, '0')}:${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;
        }
        return value;
      default:
        return value.toString();
    }
  };

  // Function to render a stats category
  const renderStatsCategory = (categoryName, stats) => {
    if (!stats || Object.keys(stats).length === 0) return null;

    return (
      <Box key={categoryName} mb="xs">
        <Text size="xs" fw={600} mb={4} tt="uppercase" c="dimmed">
          {categoryName}
        </Text>
        <Group gap={4} mb="xs">
          {Object.entries(stats).map(([key, value]) => (
            <Tooltip key={key} label={`${key}: ${formatStatValue(key, value)}`}>
              <Badge size="xs" variant="light" color="gray">
                {key
                  .replace(/_/g, ' ')
                  .replace(/\b\w/g, (l) => l.toUpperCase())}
                : {formatStatValue(key, value)}
              </Badge>
            </Tooltip>
          ))}
        </Group>
      </Box>
    );
  };

  // Function to toggle advanced stats for a stream
  const toggleAdvancedStats = (streamId) => {
    const newExpanded = new Set(expandedAdvancedStats);
    if (newExpanded.has(streamId)) {
      newExpanded.delete(streamId);
    } else {
      newExpanded.add(streamId);
    }
    setExpandedAdvancedStats(newExpanded);
  };

  const table = useReactTable({
    columns: useMemo(
      () => [
        {
          id: 'drag-handle',
          header: 'Move',
          cell: ({ row }) => <RowDragHandleCell rowId={row.id} />,
          size: 30,
        },
        {
          id: 'name',
          header: 'Stream Info',
          accessorKey: 'name',
          cell: ({ row }) => {
            const stream = row.original;
            const playlistName =
              playlists[stream.m3u_account]?.name || 'Unknown';
            const accountName =
              m3uAccountsMap[stream.m3u_account] || playlistName;

            // Categorize stream stats
            const categorizedStats = categorizeStreamStats(stream.stream_stats);
            const hasAdvancedStats = Object.values(categorizedStats).some(
              (category) => Object.keys(category).length > 0
            );

            return (
              <Box>
                <Group gap="xs" align="center">
                  <Text fw={500} size="sm">
                    {stream.name}
                  </Text>
                  <Badge size="xs" variant="light" color="teal">
                    {accountName}
                  </Badge>
                  {stream.quality && (
                    <Badge size="xs" variant="light" color="gray">
                      {stream.quality}
                    </Badge>
                  )}
                  {stream.url && (
                    <>
                      <Tooltip label={stream.url}>
                        <Badge
                          size="xs"
                          variant="light"
                          color="indigo"
                          style={{ cursor: 'pointer' }}
                          onClick={async (e) => {
                            e.stopPropagation();
                            await copyToClipboard(stream.url, {
                              successTitle: 'URL Copied',
                              successMessage: 'Stream URL copied to clipboard',
                            });
                          }}
                        >
                          URL
                        </Badge>
                      </Tooltip>
                      <Tooltip label="Preview Stream">
                        <ActionIcon
                          size="xs"
                          color="blue"
                          variant="light"
                          onClick={() =>
                            handleWatchStream(stream.stream_hash || stream.id)
                          }
                          style={{ marginLeft: 2 }}
                        >
                          <Eye size={16} />
                        </ActionIcon>
                      </Tooltip>
                    </>
                  )}
                </Group>

                {/* Basic Stream Stats (always shown) */}
                {stream.stream_stats && (
                  <Group gap="xs" mt={4} align="center">
                    {/* Video Information */}
                    {(stream.stream_stats.video_codec ||
                      stream.stream_stats.resolution ||
                      stream.stream_stats.video_bitrate ||
                      stream.stream_stats.source_fps) && (
                      <>
                        <Text size="xs" c="dimmed" fw={500}>
                          Video:
                        </Text>
                        {stream.stream_stats.resolution && (
                          <Badge size="xs" variant="light" color="red">
                            {stream.stream_stats.resolution}
                          </Badge>
                        )}
                        {stream.stream_stats.video_bitrate && (
                          <Badge
                            size="xs"
                            variant="light"
                            color="orange"
                            style={{ textTransform: 'none' }}
                          >
                            {stream.stream_stats.video_bitrate} kbps
                          </Badge>
                        )}
                        {stream.stream_stats.source_fps && (
                          <Badge size="xs" variant="light" color="orange">
                            {stream.stream_stats.source_fps} FPS
                          </Badge>
                        )}
                        {stream.stream_stats.video_codec && (
                          <Badge size="xs" variant="light" color="blue">
                            {stream.stream_stats.video_codec.toUpperCase()}
                          </Badge>
                        )}
                      </>
                    )}

                    {/* Audio Information */}
                    {(stream.stream_stats.audio_codec ||
                      stream.stream_stats.audio_channels) && (
                      <>
                        <Text size="xs" c="dimmed" fw={500}>
                          Audio:
                        </Text>
                        {stream.stream_stats.audio_channels && (
                          <Badge size="xs" variant="light" color="pink">
                            {stream.stream_stats.audio_channels}
                          </Badge>
                        )}
                        {stream.stream_stats.audio_codec && (
                          <Badge size="xs" variant="light" color="pink">
                            {stream.stream_stats.audio_codec.toUpperCase()}
                          </Badge>
                        )}
                      </>
                    )}

                    {/* Output Bitrate */}
                    {stream.stream_stats.ffmpeg_output_bitrate && (
                      <>
                        <Text size="xs" c="dimmed" fw={500}>
                          Output Bitrate:
                        </Text>
                        {stream.stream_stats.ffmpeg_output_bitrate && (
                          <Badge
                            size="xs"
                            variant="light"
                            color="orange"
                            style={{ textTransform: 'none' }}
                          >
                            {stream.stream_stats.ffmpeg_output_bitrate} kbps
                          </Badge>
                        )}
                      </>
                    )}
                  </Group>
                )}

                {/* Advanced Stats Toggle Button */}
                {hasAdvancedStats && (
                  <Group gap="xs" mt={6}>
                    <Button
                      variant="subtle"
                      size="xs"
                      leftSection={
                        expandedAdvancedStats.has(stream.id) ? (
                          <ChevronDown size={12} />
                        ) : (
                          <ChevronRight size={12} />
                        )
                      }
                      onClick={() => toggleAdvancedStats(stream.id)}
                      c="dimmed"
                    >
                      {expandedAdvancedStats.has(stream.id) ? 'Hide' : 'Show'}{' '}
                      Advanced Stats
                    </Button>
                  </Group>
                )}

                {/* Advanced Stats (expandable) */}
                <Collapse in={expandedAdvancedStats.has(stream.id)}>
                  <Box
                    mt="sm"
                    p="xs"
                    style={{
                      backgroundColor: 'rgba(0,0,0,0.1)',
                      borderRadius: '4px',
                    }}
                  >
                    {renderStatsCategory('Video', categorizedStats.video)}
                    {renderStatsCategory('Audio', categorizedStats.audio)}
                    {renderStatsCategory(
                      'Technical',
                      categorizedStats.technical
                    )}
                    {renderStatsCategory('Other', categorizedStats.other)}

                    {/* Show when stats were last updated */}
                    {stream.stream_stats_updated_at && (
                      <Text size="xs" c="dimmed" mt="xs">
                        Last updated:{' '}
                        {new Date(
                          stream.stream_stats_updated_at
                        ).toLocaleString()}
                      </Text>
                    )}
                  </Box>
                </Collapse>
              </Box>
            );
          },
        },
        {
          id: 'actions',
          header: '',
          size: 30,
          cell: ({ row }) => (
            <Center>
              <ActionIcon variant="transparent" size="xs">
                <SquareMinus
                  color={theme.tailwind.red[6]}
                  onClick={() => removeStream(row.original)}
                  disabled={authUser.user_level != USER_LEVELS.ADMIN}
                />
              </ActionIcon>
            </Center>
          ),
        },
      ],
      [data, playlists, m3uAccountsMap, expandedAdvancedStats]
    ),
    data,
    state: {
      data,
    },
    defaultColumn: {
      size: undefined,
      minSize: 0,
    },
    manualPagination: true,
    manualSorting: true,
    manualFiltering: true,
    enableRowSelection: true,
    getRowId: (row) => row.id,
    getCoreRowModel: getCoreRowModel(),
  });

  const handleDragEnd = (event) => {
    if (authUser.user_level != USER_LEVELS.ADMIN) {
      return;
    }

    const { active, over } = event;
    if (active && over && active.id !== over.id) {
      setData((data) => {
        const oldIndex = dataIds.indexOf(active.id);
        const newIndex = dataIds.indexOf(over.id);
        const retval = arrayMove(data, oldIndex, newIndex);

        const { streams: _, ...channelUpdate } = channel;
        API.updateChannel({
          ...channelUpdate,
          streams: retval.map((row) => row.id),
        }).then(() => {
          API.requeryChannels();
        });

        return retval; //this is just a splice util
      });
    }
  };

  const sensors = useSensors(
    useSensor(MouseSensor, {}),
    useSensor(TouchSensor, {}),
    useSensor(KeyboardSensor, {})
  );

  if (!isExpanded) {
    return <></>;
  }

  const rows = table.getRowModel().rows;

  return (
    <Box style={{ width: '100%', padding: 10, backgroundColor: '#163632' }}>
      <DndContext
        collisionDetection={closestCenter}
        modifiers={[restrictToVerticalAxis]}
        onDragEnd={handleDragEnd}
        sensors={sensors}
      >
        {' '}
        <Box
          className="divTable table-striped"
          style={{
            width: '100%',
            display: 'flex',
            flexDirection: 'column',
          }}
        >
          <Box className="tbody">
            <SortableContext
              items={dataIds}
              strategy={verticalListSortingStrategy}
            >
              {rows.length === 0 && (
                <Box
                  className="tr"
                  style={{
                    display: 'flex',
                    width: '100%',
                  }}
                >
                  <Box
                    className="td"
                    style={{
                      flex: '1 1 0',
                      minWidth: 0,
                    }}
                  >
                    <Flex
                      align="center"
                      justify="center"
                      style={{ height: '100%' }}
                    >
                      <Text size="xs">No Data</Text>
                    </Flex>
                  </Box>
                </Box>
              )}
              {rows.length > 0 &&
                table
                  .getRowModel()
                  .rows.map((row) => <DraggableRow key={row.id} row={row} />)}
            </SortableContext>
          </Box>
        </Box>
      </DndContext>
    </Box>
  );
};

export default ChannelStreams;
