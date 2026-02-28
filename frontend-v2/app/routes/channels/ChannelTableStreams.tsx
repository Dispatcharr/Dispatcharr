import React, { useMemo, useState, useEffect } from 'react';
import API from '~/lib/api';
import { copyToClipboard } from '~/lib/utils';
import {
  GripHorizontal,
  SquareMinus,
  ChevronDown,
  ChevronRight,
  Eye,
} from 'lucide-react';
import {
  useReactTable,
  getCoreRowModel,
  flexRender,
} from '@tanstack/react-table';
// import './table.css';
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
import { USER_LEVELS } from '~/lib/constants';
import { Button } from '~/components/ui/button';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '~/components/ui/tooltip';
import { Badge } from '~/components/ui/badge';
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '~/components/ui/collapsible';
import { TableCell, TableRow } from '~/components/ui/table';

const RowDragHandleCell = ({ rowId }) => {
  const { attributes, listeners, setNodeRef } = useDraggable({
    id: rowId,
  });

  return (
    <div
      className="flex items-center justify-center"
      style={{ height: '100%' }}
    >
      <Button
        size="xs"
        variant="ghost"
        ref={setNodeRef}
        {...listeners}
        {...attributes}
      >
        <GripHorizontal color="white" />
      </Button>
    </div>
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
    <div
      ref={setNodeRef}
      key={row.id}
      className='flex'
    >
      {row.getVisibleCells().map((cell) => {
        const isStale = row.original.is_stale;
        return (
          <div
            key={cell.id}
            className={`flex flex-col flex-col- ${isStale ? 'bg-red-900/30' : ''}`}
            style={{
              flex: cell.column.columnDef.size ? '0 0 auto' : '1 1 0',
            //   width: cell.column.columnDef.size
            //     ? cell.column.getSize()
            //     : undefined,
            //   minWidth: 0,
            //   ...(isStale && {
            //     backgroundColor: 'rgba(239, 68, 68, 0.15)',
            //   }),
            }}
          >
            <div className="flex items-center" style={{ height: '100%' }}>
              <div>
                {flexRender(cell.column.columnDef.cell, cell.getContext())}
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
};

const ChannelStreams = ({ channel, isExpanded }) => {
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
      <div key={categoryName} mb="xs">
        <div className="text-xs font-semibold mb-1 uppercase text-gray-500">
          {categoryName}
        </div>
        <div className="flex flex-wrap gap-4 mb-2">
          {Object.entries(stats).map(([key, value]) => (
            <Tooltip>
              <TooltipTrigger asChild>
                <Badge className="bg-zinc-400 dark:bg-zinc-700 text-current uppercase text-xs/3">{key
                  .replace(/_/g, ' ')
                  .replace(/\b\w/g, (l) => l.toUpperCase())}
                : {formatStatValue(key, value)}</Badge>
              </TooltipTrigger>
              <TooltipContent>
                 {`${key}: ${formatStatValue(key, value)}`}
              </TooltipContent>
            </Tooltip>
          ))}
        </div>
      </div>
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
              <div>
                <div className="flex gap-2 items-center">
                  <div className="font-medium text-sm">{stream.name}</div>
                  <Badge className="bg-teal-900 text-teal-300 text-xs/3">
                    {accountName}
                  </Badge>
                  {stream.quality && (
                    <Badge className="bg-green-900 text-green-300 text-xs/3">
                      {stream.quality}
                    </Badge>
                  )}
                  {stream.url && (
                    <>
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <Badge
                            className="bg-indigo-500 text-indigo-200 cursor-pointer text-xs/3"
                            onClick={async (e) => {
                              e.stopPropagation();
                              await copyToClipboard(stream.url, {
                                successTitle: 'URL Copied',
                                successMessage:
                                  'Stream URL copied to clipboard',
                              });
                            }}
                          >
                            URL
                          </Badge>
                        </TooltipTrigger>
                        <TooltipContent>{stream.url}</TooltipContent>
                      </Tooltip>
                      <Tooltip label="Preview Stream">
                        <Button
                          variant="ghost"
                          onClick={() =>
                            handleWatchStream(stream.stream_hash || stream.id)
                          }
                        >
                          <Eye size={16} />
                        </Button>
                      </Tooltip>
                    </>
                  )}
                </div>

                {/* Basic Stream Stats (always shown) */}
                {stream.stream_stats && (
                  <div className="flex gap-2 items-center">
                    {/* Video Information */}
                    {(stream.stream_stats.video_codec ||
                      stream.stream_stats.resolution ||
                      stream.stream_stats.video_bitrate ||
                      stream.stream_stats.source_fps) && (
                      <>
                        <div className="text-xs text-gray-500 font-medium">
                          Video:
                        </div>
                        {stream.stream_stats.resolution && (
                          <Badge className="bg-red-900 text-red-300 text-xs/3">
                            {stream.stream_stats.resolution}
                          </Badge>
                        )}
                        {stream.stream_stats.video_bitrate && (
                          <Badge className="bg-orange-900 text-orange-300 text-xs/3">
                            {stream.stream_stats.video_bitrate} kbps
                          </Badge>
                        )}
                        {stream.stream_stats.source_fps && (
                          <Badge className="bg-orange-900 text-orange-300 text-xs/3">
                            {stream.stream_stats.source_fps} FPS
                          </Badge>
                        )}
                        {stream.stream_stats.video_codec && (
                          <Badge className="bg-blue-900 text-blue-300 text-xs/3">
                            {stream.stream_stats.video_codec.toUpperCase()}
                          </Badge>
                        )}
                      </>
                    )}

                    {/* Audio Information */}
                    {(stream.stream_stats.audio_codec ||
                      stream.stream_stats.audio_channels) && (
                      <>
                        <div className="text-xs text-gray-500 font-medium">
                          Audio:
                        </div>
                        {stream.stream_stats.audio_channels && (
                          <Badge className="bg-pink-900 text-pink-300 text-xs/3">
                            {stream.stream_stats.audio_channels}
                          </Badge>
                        )}
                        {stream.stream_stats.audio_codec && (
                          <Badge className="bg-pink-900 text-pink-300 text-xs/3">
                            {stream.stream_stats.audio_codec.toUpperCase()}
                          </Badge>
                        )}
                      </>
                    )}

                    {/* Output Bitrate */}
                    {stream.stream_stats.ffmpeg_output_bitrate && (
                      <>
                        <div className="text-xs text-gray-500 font-medium">
                          Output Bitrate:
                        </div>
                        {stream.stream_stats.ffmpeg_output_bitrate && (
                          <Badge className="bg-orange-900 text-orange-300 text-xs/3">
                            {stream.stream_stats.ffmpeg_output_bitrate} kbps
                          </Badge>
                        )}
                      </>
                    )}
                  </div>
                )}

                {/* Advanced Stats Toggle Button */}
                {hasAdvancedStats && (
                  <div className="flex gap-2 mt-2 items-center">
                    <Button
                        className="cursor-pointer"
                        variant="ghost"
                        size="xs"
                      onClick={() => toggleAdvancedStats(stream.id)}
                    >
                      {expandedAdvancedStats.has(stream.id) ? (
                        <ChevronDown size={12} />
                      ) : (
                        <ChevronRight size={12} />
                      )}
                      {expandedAdvancedStats.has(stream.id) ? 'Hide' : 'Show'}{' '}
                      Advanced Stats
                    </Button>
                  </div>
                )}

                {/* Advanced Stats (expandable) */}
                <Collapsible open={expandedAdvancedStats.has(stream.id)}>
                  <CollapsibleContent>
                    <div className="p-2"
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
                        <div className="text-sm text-gray-500">
                          Last updated:{' '}
                          {new Date(
                            stream.stream_stats_updated_at
                          ).toLocaleString()}
                        </div>
                      )}
                    </div>
                  </CollapsibleContent>
                </Collapsible>
              </div>
            );
          },
        },
        {
          id: 'actions',
          header: '',
          size: 30,
          cell: ({ row }) => (
            <div
              className="flex items-center justify-center"
              style={{ height: '100%' }}
            >
              <Button
                variant="ghost"
                onClick={() => removeStream(row.original)}
                disabled={authUser.user_level != USER_LEVELS.ADMIN}
              >
                <SquareMinus className="text-red-600" />
              </Button>
            </div>
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
    <div className="m-2 bg-secondary pr-1">
      <DndContext
        collisionDetection={closestCenter}
        modifiers={[restrictToVerticalAxis]}
        onDragEnd={handleDragEnd}
        sensors={sensors}
      >
        <div className="divTable table-striped flex flex-col">
          <div className="tbody">
            <SortableContext
              items={dataIds}
              strategy={verticalListSortingStrategy}
            >
              {rows.length === 0 && (
                <div className="flex items-center justify-center h-8">
                  <div className="text-xs">No Data</div>
                </div>
              )}
              {rows.length > 0 &&
                table
                  .getRowModel()
                  .rows.map((row) => <DraggableRow key={row.id} row={row} />)}
            </SortableContext>
          </div>
        </div>
      </DndContext>
    </div>
  );
};

export default ChannelStreams;
