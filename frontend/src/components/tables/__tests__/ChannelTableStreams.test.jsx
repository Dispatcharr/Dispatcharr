import React from 'react';
import {
  render,
  screen,
  fireEvent,
  waitFor,
  act,
} from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import ChannelStreams from '../ChannelTableStreams';

// ── Store mocks ────────────────────────────────────────────────────────────────
vi.mock('../../../store/channelsTable', () => ({ default: vi.fn() }));
vi.mock('../../../store/playlists', () => ({ default: vi.fn() }));
vi.mock('../../../store/useVideoStore', () => ({ default: vi.fn() }));
vi.mock('../../../store/settings', () => ({ default: vi.fn() }));
vi.mock('../../../store/auth', () => ({ default: vi.fn() }));

// ── Utility mocks ──────────────────────────────────────────────────────────────
vi.mock('../../../utils', () => ({
  copyToClipboard: vi.fn().mockResolvedValue(true),
}));

vi.mock('../../../utils/components/FloatingVideoUtils.js', () => ({
  buildLiveStreamUrl: vi.fn((path) => `${path}?output_format=mpegts`),
}));

vi.mock('../../../utils/tables/ChannelTableStreamsUtils.js', () => ({
  categorizeStreamStats: vi.fn(() => ({
    basic: {},
    video: {},
    audio: {},
    technical: {},
    other: {},
  })),
  formatStatKey: vi.fn((key) => key),
  formatStatValue: vi.fn((key, value) => String(value)),
  getChannelStreamStats: vi.fn().mockResolvedValue([]),
  reorderChannelStreams: vi.fn().mockResolvedValue(undefined),
}));

// ── @dnd-kit mocks ─────────────────────────────────────────────────────────────
vi.mock('@dnd-kit/core', () => ({
  closestCenter: vi.fn(),
  DndContext: vi.fn(({ children, onDragEnd }) => (
  <div data-testid="dnd-context" data-ondragend={typeof onDragEnd}>
    {children}
  </div>
  )),
  KeyboardSensor: vi.fn(),
  MouseSensor: vi.fn(),
  TouchSensor: vi.fn(),
  useDraggable: vi.fn(() => ({
    attributes: {},
    listeners: {},
    setNodeRef: vi.fn(),
  })),
  useSensor: vi.fn((sensor) => sensor),
  useSensors: vi.fn((...sensors) => sensors),
}));

vi.mock('@dnd-kit/modifiers', () => ({
  restrictToVerticalAxis: vi.fn(),
}));

vi.mock('@dnd-kit/sortable', () => ({
  arrayMove: vi.fn((arr, from, to) => {
    const next = [...arr];
    const [item] = next.splice(from, 1);
    next.splice(to, 0, item);
    return next;
  }),
  SortableContext: ({ children }) => (
    <div data-testid="sortable-context">{children}</div>
  ),
  useSortable: vi.fn(() => ({
    transform: null,
    transition: null,
    setNodeRef: vi.fn(),
    isDragging: false,
  })),
  verticalListSortingStrategy: vi.fn(),
}));

vi.mock('@dnd-kit/utilities', () => ({
  CSS: { Transform: { toString: vi.fn(() => '') } },
}));

// ── zustand/shallow ────────────────────────────────────────────────────────────
vi.mock('zustand/shallow', () => ({
  shallow: (a, b) => a === b,
}));

// ── Mantine core ───────────────────────────────────────────────────────────────
vi.mock('@mantine/core', () => ({
  ActionIcon: ({ children, onClick, ...rest }) => (
    <button data-testid="action-icon" onClick={onClick} {...rest}>
      {children}
    </button>
  ),
  Badge: ({ children, color, onClick, style }) => (
    <span
      data-testid="badge"
      data-color={color}
      onClick={onClick}
      style={style}
    >
      {children}
    </span>
  ),
  Box: ({ children, style, className, ...rest }) => (
    <div style={style} className={className} {...rest}>
      {children}
    </div>
  ),
  Button: ({ children, onClick, leftSection }) => (
    <button data-testid="button" onClick={onClick}>
      {leftSection}
      {children}
    </button>
  ),
  Center: ({ children }) => <div data-testid="center">{children}</div>,
  Collapse: ({ children, in: open }) =>
    open ? <div data-testid="collapse-open">{children}</div> : null,
  Flex: ({ children, style }) => (
    <div style={style}>{children}</div>
  ),
  Group: ({ children }) => <div>{children}</div>,
  Text: ({ children, size }) => (
    <span data-testid="text" data-size={size}>
      {children}
    </span>
  ),
  Tooltip: ({ children, label }) => <div data-tooltip={label}>{children}</div>,
  useMantineTheme: vi.fn(() => ({
    tailwind: { red: { 6: '#fa5252' } },
  })),
}));

// ── lucide-react ───────────────────────────────────────────────────────────────
vi.mock('lucide-react', () => ({
  ChevronDown: () => <svg data-testid="icon-chevron-down" />,
  ChevronRight: () => <svg data-testid="icon-chevron-right" />,
  Eye: () => <svg data-testid="icon-eye" />,
  GripHorizontal: () => <svg data-testid="icon-grip" />,
  SquareMinus: ({ onClick, disabled, color }) => (
    <svg
      data-testid="icon-square-minus"
      onClick={onClick}
      data-disabled={disabled}
      data-color={color}
    />
  ),
}));

// ── Imports after mocks ────────────────────────────────────────────────────────
import useChannelsTableStore from '../../../store/channelsTable';
import usePlaylistsStore from '../../../store/playlists';
import useVideoStore from '../../../store/useVideoStore';
import useSettingsStore from '../../../store/settings';
import useAuthStore from '../../../store/auth';
import { buildLiveStreamUrl } from '../../../utils/components/FloatingVideoUtils.js';
import * as ChannelTableStreamsUtils from '../../../utils/tables/ChannelTableStreamsUtils.js';
import { copyToClipboard } from '../../../utils';
import { DndContext } from '@dnd-kit/core';
import { arrayMove } from '@dnd-kit/sortable';

// ── Factories ──────────────────────────────────────────────────────────────────

const makeStream = (overrides = {}) => ({
  id: 's-1',
  name: 'Stream One',
  m3u_account: 'acc-1',
  url: 'http://example.com/stream',
  stream_hash: 'hash-abc',
  quality: '1080p',
  stream_stats: null,
  stream_stats_updated_at: null,
  is_stale: false,
  ...overrides,
});

const makeChannel = (streams = [makeStream()]) => ({
  id: 'ch-1',
  name: 'HBO',
  streams,
});

const makePlaylists = () => [{ id: 'acc-1', name: 'My M3U' }];

/** Wire all store mocks with sensible defaults */
const setupMocks = ({
  streams = [makeStream()],
  playlists = makePlaylists(),
  isAdmin = true,
  isVideoVisible = false,
  envMode = 'production',
} = {}) => {
  const mockPatchChannelStreamStats = vi.fn();

  vi.mocked(useChannelsTableStore).mockImplementation((sel) => {
    if (typeof sel === 'function') {
      const storeState = {
        getChannelStreams: () => streams,
        patchChannelStreamStats: mockPatchChannelStreamStats,
      };
      return sel(storeState);
    }
  });

  vi.mocked(usePlaylistsStore).mockImplementation((sel) => sel({ playlists }));

  const mockShowVideo = vi.fn();
  vi.mocked(useVideoStore).mockImplementation((sel) => {
    const state = { showVideo: mockShowVideo, isVisible: isVideoVisible };
    return sel(state);
  });
  // Also expose getState for the ref-based metadata read
  useVideoStore.getState = vi.fn(() => ({ metadata: null }));

  vi.mocked(useSettingsStore).mockImplementation((sel) =>
    sel({ environment: { env_mode: envMode } })
  );

  vi.mocked(useAuthStore).mockImplementation((sel) =>
    sel({ user: { user_level: isAdmin ? 10 : 1 } })
  );

  return { mockShowVideo, mockPatchChannelStreamStats };
};

// ══════════════════════════════════════════════════════════════════════════════
// Tests
// ══════════════════════════════════════════════════════════════════════════════

describe('ChannelStreams', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(ChannelTableStreamsUtils.getChannelStreamStats).mockResolvedValue(
      []
    );
    vi.mocked(ChannelTableStreamsUtils.reorderChannelStreams).mockResolvedValue(
      undefined
    );
    vi.mocked(ChannelTableStreamsUtils.categorizeStreamStats).mockReturnValue({
      basic: {},
      video: {},
      audio: {},
      technical: {},
      other: {},
    });
  });

  // ── Rendering ────────────────────────────────────────────────────────────

  describe('rendering', () => {
    it('renders stream name', () => {
      setupMocks();
      render(<ChannelStreams channel={makeChannel()} />);
      expect(screen.getByText('Stream One')).toBeInTheDocument();
    });

    it('renders the M3U account name badge', () => {
      setupMocks();
      render(<ChannelStreams channel={makeChannel()} />);
      expect(screen.getByText('My M3U')).toBeInTheDocument();
    });

    it('renders "Unknown" account badge when m3u_account has no matching playlist', () => {
      setupMocks({ playlists: [] });
      render(<ChannelStreams channel={makeChannel()} />);
      expect(screen.getByText('Unknown')).toBeInTheDocument();
    });

    it('renders the quality badge when stream has quality', () => {
      setupMocks();
      render(<ChannelStreams channel={makeChannel()} />);
      expect(screen.getByText('1080p')).toBeInTheDocument();
    });

    it('does not render quality badge when stream has no quality', () => {
      const streams = [makeStream({ quality: null })];
      setupMocks({ streams });
      render(<ChannelStreams channel={makeChannel(streams)} />);
      expect(screen.queryByText('1080p')).not.toBeInTheDocument();
    });

    it('renders the URL badge when stream has a url', () => {
      setupMocks();
      render(<ChannelStreams channel={makeChannel()} />);
      expect(screen.getByText('URL')).toBeInTheDocument();
    });

    it('does not render URL badge when stream has no url', () => {
      const streams = [makeStream({ url: null })];
      setupMocks({ streams });
      render(<ChannelStreams channel={makeChannel(streams)} />);
      expect(screen.queryByText('URL')).not.toBeInTheDocument();
    });

    it('renders "No Data" when there are no streams', () => {
      setupMocks({ streams: [] });
      render(<ChannelStreams channel={makeChannel([])} />);
      expect(screen.getByText('No Data')).toBeInTheDocument();
    });

    it('renders the preview Eye action icon when stream has a url', () => {
      setupMocks();
      render(<ChannelStreams channel={makeChannel()} />);
      expect(screen.getByTestId('icon-eye')).toBeInTheDocument();
    });

    it('renders the drag handle grip icon', () => {
      setupMocks();
      render(<ChannelStreams channel={makeChannel()} />);
      expect(screen.getByTestId('icon-grip')).toBeInTheDocument();
    });

    it('renders the remove stream icon', () => {
      setupMocks();
      render(<ChannelStreams channel={makeChannel()} />);
      expect(screen.getByTestId('icon-square-minus')).toBeInTheDocument();
    });

    it('renders multiple streams when channel has multiple', () => {
      const streams = [
        makeStream({ id: 's-1', name: 'Stream One' }),
        makeStream({ id: 's-2', name: 'Stream Two' }),
      ];
      setupMocks({ streams });
      render(<ChannelStreams channel={makeChannel(streams)} />);
      expect(screen.getByText('Stream One')).toBeInTheDocument();
      expect(screen.getByText('Stream Two')).toBeInTheDocument();
    });
  });

  // ── Stats fetching on mount ───────────────────────────────────────────────

  describe('stats fetching', () => {
    it('calls getChannelStreamStats on mount', async () => {
      setupMocks();
      render(<ChannelStreams channel={makeChannel()} />);
      await waitFor(() => {
        expect(
          ChannelTableStreamsUtils.getChannelStreamStats
        ).toHaveBeenCalledWith('ch-1', null, undefined);
      });
    });

    it('passes the latest stream_stats_updated_at as the "since" cursor', async () => {
      const streams = [
        makeStream({ stream_stats_updated_at: '2024-01-01T00:00:00Z' }),
      ];
      setupMocks({ streams });
      render(<ChannelStreams channel={makeChannel(streams)} />);
      await waitFor(() => {
        expect(
          ChannelTableStreamsUtils.getChannelStreamStats
        ).toHaveBeenCalledWith('ch-1', '2024-01-01T00:00:00Z', undefined);
      });
    });

    it('calls patchChannelStreamStats when getChannelStreamStats returns updates', async () => {
      const updates = [
        {
          id: 's-1',
          stream_stats: { resolution: '1080p' },
          stream_stats_updated_at: 't2',
        },
      ];
      vi.mocked(
        ChannelTableStreamsUtils.getChannelStreamStats
      ).mockResolvedValue(updates);
      const { mockPatchChannelStreamStats } = setupMocks();
      render(<ChannelStreams channel={makeChannel()} />);
      await waitFor(() => {
        expect(mockPatchChannelStreamStats).toHaveBeenCalledWith(
          'ch-1',
          updates
        );
      });
    });

    it('does not call patchChannelStreamStats when getChannelStreamStats returns empty', async () => {
      vi.mocked(
        ChannelTableStreamsUtils.getChannelStreamStats
      ).mockResolvedValue([]);
      const { mockPatchChannelStreamStats } = setupMocks();
      render(<ChannelStreams channel={makeChannel()} />);
      await waitFor(() => {
        expect(
          ChannelTableStreamsUtils.getChannelStreamStats
        ).toHaveBeenCalled();
      });
      expect(mockPatchChannelStreamStats).not.toHaveBeenCalled();
    });

    it('does not call patchChannelStreamStats when getChannelStreamStats returns null', async () => {
      vi.mocked(
        ChannelTableStreamsUtils.getChannelStreamStats
      ).mockResolvedValue(null);
      const { mockPatchChannelStreamStats } = setupMocks();
      render(<ChannelStreams channel={makeChannel()} />);
      await waitFor(() => {
        expect(
          ChannelTableStreamsUtils.getChannelStreamStats
        ).toHaveBeenCalled();
      });
      expect(mockPatchChannelStreamStats).not.toHaveBeenCalled();
    });
  });

  // ── Preview stream (Eye button) ───────────────────────────────────────────

  describe('preview stream', () => {
    it('calls showVideo with correct url when Eye button is clicked', () => {
      const { mockShowVideo } = setupMocks();
      render(<ChannelStreams channel={makeChannel()} />);
      fireEvent.click(screen.getByTestId('icon-eye').closest('button'));
      expect(buildLiveStreamUrl).toHaveBeenCalledWith(
        '/proxy/ts/stream/hash-abc'
      );
      expect(mockShowVideo).toHaveBeenCalledWith(
        '/proxy/ts/stream/hash-abc?output_format=mpegts',
        'live',
        expect.objectContaining({ name: 'Stream One', streamId: 's-1' })
      );
    });

    it('uses stream_hash over id in the video url', () => {
      const streams = [makeStream({ id: 's-99', stream_hash: 'special-hash' })];
      setupMocks({ streams });
      render(<ChannelStreams channel={makeChannel(streams)} />);
      fireEvent.click(screen.getByTestId('icon-eye').closest('button'));
      expect(buildLiveStreamUrl).toHaveBeenCalledWith(
        '/proxy/ts/stream/special-hash'
      );
    });

    it('uses stream id when stream_hash is absent', () => {
      const streams = [makeStream({ id: 's-1', stream_hash: null })];
      setupMocks({ streams });
      render(<ChannelStreams channel={makeChannel(streams)} />);
      fireEvent.click(screen.getByTestId('icon-eye').closest('button'));
      expect(buildLiveStreamUrl).toHaveBeenCalledWith('/proxy/ts/stream/s-1');
    });

    it('prefixes hostname in dev mode', () => {
      const { mockShowVideo } = setupMocks({ envMode: 'dev' });
      render(<ChannelStreams channel={makeChannel()} />);
      fireEvent.click(screen.getByTestId('icon-eye').closest('button'));
      const calledUrl = mockShowVideo.mock.calls[0][0];
      expect(calledUrl).toContain(':5656');
    });

    it('does not prefix hostname in production mode', () => {
      const { mockShowVideo } = setupMocks({ envMode: 'production' });
      render(<ChannelStreams channel={makeChannel()} />);
      fireEvent.click(screen.getByTestId('icon-eye').closest('button'));
      const calledUrl = mockShowVideo.mock.calls[0][0];
      expect(calledUrl).not.toContain(':5656');
    });
  });

  // ── URL badge copy-to-clipboard ───────────────────────────────────────────

  describe('URL badge copy to clipboard', () => {
    it('calls copyToClipboard with the stream url when URL badge is clicked', async () => {
      setupMocks();
      render(<ChannelStreams channel={makeChannel()} />);
      fireEvent.click(screen.getByText('URL'));
      await waitFor(() => {
        expect(copyToClipboard).toHaveBeenCalledWith(
          'http://example.com/stream',
          expect.objectContaining({ successTitle: 'URL Copied' })
        );
      });
    });
  });

  // ── Remove stream ─────────────────────────────────────────────────────────

  describe('remove stream', () => {
    it('removes stream from the list when remove icon is clicked', async () => {
      const streams = [
        makeStream({ id: 's-1', name: 'Stream One' }),
        makeStream({ id: 's-2', name: 'Stream Two' }),
      ];
      setupMocks({ streams });
      render(<ChannelStreams channel={makeChannel(streams)} />);

      expect(screen.getByText('Stream One')).toBeInTheDocument();

      fireEvent.click(screen.getAllByTestId('icon-square-minus')[0]);

      await waitFor(() => {
        expect(
          ChannelTableStreamsUtils.reorderChannelStreams
        ).toHaveBeenCalledWith('ch-1', ['s-2']);
      });
    });

    it('calls reorderChannelStreams with an empty array when last stream is removed', async () => {
      setupMocks();
      render(<ChannelStreams channel={makeChannel()} />);
      fireEvent.click(screen.getByTestId('icon-square-minus'));
      await waitFor(() => {
        expect(
          ChannelTableStreamsUtils.reorderChannelStreams
        ).toHaveBeenCalledWith('ch-1', []);
      });
    });
  });

  // ── Stream stats display ──────────────────────────────────────────────────

  describe('basic stream stats', () => {
    it('renders video stats section when video_codec is present', () => {
      const streams = [
        makeStream({
          stream_stats: { video_codec: 'h264', resolution: '1920x1080' },
        }),
      ];
      setupMocks({ streams });
      render(<ChannelStreams channel={makeChannel(streams)} />);
      expect(screen.getByText('Video:')).toBeInTheDocument();
    });

    it('renders resolution badge', () => {
      const streams = [
        makeStream({ stream_stats: { resolution: '1920x1080' } }),
      ];
      setupMocks({ streams });
      render(<ChannelStreams channel={makeChannel(streams)} />);
      expect(screen.getByText('1920x1080')).toBeInTheDocument();
    });

    it('renders video_bitrate badge with kbps suffix', () => {
      const streams = [makeStream({ stream_stats: { video_bitrate: 5000 } })];
      setupMocks({ streams });
      render(<ChannelStreams channel={makeChannel(streams)} />);
      expect(screen.getByText('5000 kbps')).toBeInTheDocument();
    });

    it('renders fps badge', () => {
      const streams = [makeStream({ stream_stats: { source_fps: 29.97 } })];
      setupMocks({ streams });
      render(<ChannelStreams channel={makeChannel(streams)} />);
      expect(screen.getByText('29.97 FPS')).toBeInTheDocument();
    });

    it('renders codec badge uppercased', () => {
      const streams = [makeStream({ stream_stats: { video_codec: 'h264' } })];
      setupMocks({ streams });
      render(<ChannelStreams channel={makeChannel(streams)} />);
      expect(screen.getByText('H264')).toBeInTheDocument();
    });

    it('renders audio section when audio_codec is present', () => {
      const streams = [makeStream({ stream_stats: { audio_codec: 'aac' } })];
      setupMocks({ streams });
      render(<ChannelStreams channel={makeChannel(streams)} />);
      expect(screen.getByText('Audio:')).toBeInTheDocument();
      expect(screen.getByText('AAC')).toBeInTheDocument();
    });

    it('renders audio channels badge', () => {
      const streams = [makeStream({ stream_stats: { audio_channels: 2 } })];
      setupMocks({ streams });
      render(<ChannelStreams channel={makeChannel(streams)} />);
      expect(screen.getByText('2')).toBeInTheDocument();
    });

    it('renders output bitrate section when ffmpeg_output_bitrate is present', () => {
      const streams = [
        makeStream({ stream_stats: { ffmpeg_output_bitrate: 3000 } }),
      ];
      setupMocks({ streams });
      render(<ChannelStreams channel={makeChannel(streams)} />);
      expect(screen.getByText('Output Bitrate:')).toBeInTheDocument();
      expect(screen.getByText('3000 kbps')).toBeInTheDocument();
    });

    it('renders last updated timestamp when stream_stats_updated_at is set', () => {
      vi.mocked(ChannelTableStreamsUtils.categorizeStreamStats).mockReturnValue(
        {
          basic: {},
          video: { video_bitrate: 5000 },
          audio: {},
          technical: {},
          other: {},
        }
      );
      const streams = [
        makeStream({
          stream_stats: { video_bitrate: 5000 },
          stream_stats_updated_at: '2024-01-15T10:30:00Z',
        }),
      ];
      setupMocks({ streams });
      render(<ChannelStreams channel={makeChannel(streams)} />);
      // Expand advanced stats first so the timestamp is visible
      fireEvent.click(screen.getByText('Show Advanced Stats'));
      expect(screen.getByText(/Last updated:/)).toBeInTheDocument();
    });
  });

  // ── Advanced stats toggle ─────────────────────────────────────────────────

  describe('advanced stats toggle', () => {
    const makeStreamWithAdvancedStats = () =>
      makeStream({
        stream_stats: { video_bitrate: 4000 },
      });

    beforeEach(() => {
      vi.mocked(ChannelTableStreamsUtils.categorizeStreamStats).mockReturnValue(
        {
          basic: {},
          video: { video_bitrate: 4000 },
          audio: {},
          technical: {},
          other: {},
        }
      );
    });

    it('shows "Show Advanced Stats" button when advanced stats exist', () => {
      const streams = [makeStreamWithAdvancedStats()];
      setupMocks({ streams });
      render(<ChannelStreams channel={makeChannel(streams)} />);
      expect(screen.getByText('Show Advanced Stats')).toBeInTheDocument();
    });

    it('does not show advanced stats toggle when no advanced stats exist', () => {
      vi.mocked(ChannelTableStreamsUtils.categorizeStreamStats).mockReturnValue(
        {
          basic: {},
          video: {},
          audio: {},
          technical: {},
          other: {},
        }
      );
      const streams = [makeStream({ stream_stats: null })];
      setupMocks({ streams });
      render(<ChannelStreams channel={makeChannel(streams)} />);
      expect(screen.queryByText('Show Advanced Stats')).not.toBeInTheDocument();
    });

    it('toggles to "Hide Advanced Stats" after clicking Show', () => {
      const streams = [makeStreamWithAdvancedStats()];
      setupMocks({ streams });
      render(<ChannelStreams channel={makeChannel(streams)} />);
      fireEvent.click(screen.getByText('Show Advanced Stats'));
      expect(screen.getByText('Hide Advanced Stats')).toBeInTheDocument();
    });

    it('opens the Collapse panel when Show Advanced Stats is clicked', () => {
      const streams = [makeStreamWithAdvancedStats()];
      setupMocks({ streams });
      render(<ChannelStreams channel={makeChannel(streams)} />);
      expect(screen.queryByTestId('collapse-open')).not.toBeInTheDocument();
      fireEvent.click(screen.getByText('Show Advanced Stats'));
      expect(screen.getByTestId('collapse-open')).toBeInTheDocument();
    });

    it('closes the Collapse panel when Hide Advanced Stats is clicked', () => {
      const streams = [makeStreamWithAdvancedStats()];
      setupMocks({ streams });
      render(<ChannelStreams channel={makeChannel(streams)} />);
      fireEvent.click(screen.getByText('Show Advanced Stats'));
      fireEvent.click(screen.getByText('Hide Advanced Stats'));
      expect(screen.queryByTestId('collapse-open')).not.toBeInTheDocument();
    });
  });

  // ── DnD reorder ───────────────────────────────────────────────────────────

  describe('drag and drop reorder', () => {
    it('calls reorderChannelStreams with new order after drag end', async () => {
      const streams = [
        makeStream({ id: 's-1', name: 'First' }),
        makeStream({ id: 's-2', name: 'Second' }),
      ];
      vi.mocked(arrayMove).mockImplementation((arr, from, to) => {
        const next = [...arr];
        const [item] = next.splice(from, 1);
        next.splice(to, 0, item);
        return next;
      });
      setupMocks({ streams });

      // Capture the onDragEnd handler from DndContext
      let capturedOnDragEnd;
      vi.mocked(DndContext).mockImplementation(({ children, onDragEnd }) => {
        capturedOnDragEnd = onDragEnd;
        return <div data-testid="dnd-context">{children}</div>;
      });

      render(<ChannelStreams channel={makeChannel(streams)} />);

      await act(async () => {
        capturedOnDragEnd({ active: { id: 's-1' }, over: { id: 's-2' } });
      });

      await waitFor(() => {
        expect(
          ChannelTableStreamsUtils.reorderChannelStreams
        ).toHaveBeenCalledWith('ch-1', expect.any(Array));
      });
    });

    it('does not reorder when active and over are the same', async () => {
      const streams = [makeStream({ id: 's-1' }), makeStream({ id: 's-2' })];
      setupMocks({ streams });

      let capturedOnDragEnd;
      vi.mocked(DndContext).mockImplementation(({ children, onDragEnd }) => {
        capturedOnDragEnd = onDragEnd;
        return <div data-testid="dnd-context">{children}</div>;
      });

      render(<ChannelStreams channel={makeChannel(streams)} />);

      await act(async () => {
        capturedOnDragEnd({ active: { id: 's-1' }, over: { id: 's-1' } });
      });

      expect(
        ChannelTableStreamsUtils.reorderChannelStreams
      ).not.toHaveBeenCalled();
    });

    it('does not reorder when user is not an admin', async () => {
      const streams = [makeStream({ id: 's-1' }), makeStream({ id: 's-2' })];
      setupMocks({ streams, isAdmin: false });

      let capturedOnDragEnd;
      vi.mocked(DndContext).mockImplementation(({ children, onDragEnd }) => {
        capturedOnDragEnd = onDragEnd;
        return <div data-testid="dnd-context">{children}</div>;
      });

      render(<ChannelStreams channel={makeChannel(streams)} />);

      await act(async () => {
        capturedOnDragEnd({ active: { id: 's-1' }, over: { id: 's-2' } });
      });

      expect(
        ChannelTableStreamsUtils.reorderChannelStreams
      ).not.toHaveBeenCalled();
    });
  });

  // ── m3u account map ───────────────────────────────────────────────────────

  describe('m3u account map', () => {
    it('handles null playlists gracefully', () => {
      setupMocks({ playlists: null });
      expect(() =>
        render(<ChannelStreams channel={makeChannel()} />)
      ).not.toThrow();
    });

    it('handles playlists with missing ids gracefully', () => {
      setupMocks({ playlists: [{ name: 'No ID Playlist' }] });
      expect(() =>
        render(<ChannelStreams channel={makeChannel()} />)
      ).not.toThrow();
      expect(screen.getByText('Unknown')).toBeInTheDocument();
    });
  });

  // ── stale row ─────────────────────────────────────────────────────────────

  describe('stale stream row', () => {
    it('applies stale-stream-row class when is_stale is true', () => {
      const streams = [makeStream({ is_stale: true })];
      setupMocks({ streams });
      const { container } = render(
        <ChannelStreams channel={makeChannel(streams)} />
      );
      expect(container.querySelector('.stale-stream-row')).toBeInTheDocument();
    });

    it('does not apply stale-stream-row class when is_stale is false', () => {
      setupMocks();
      const { container } = render(<ChannelStreams channel={makeChannel()} />);
      expect(
        container.querySelector('.stale-stream-row')
      ).not.toBeInTheDocument();
    });
  });
});
