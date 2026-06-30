import { describe, it, expect, vi, beforeEach } from 'vitest';
import * as M3UsTableUtils from '../M3UsTableUtils';

// ── Dependency mocks ────────────────────────────────────────────────────────
vi.mock('../../../api.js', () => ({
  default: {
    refreshPlaylist: vi.fn(),
    getPlaylistAutoCreatedChannelsCount: vi.fn(),
    deletePlaylist: vi.fn(),
    updatePlaylist: vi.fn(),
  },
}));

vi.mock('../../dateTimeUtils.js', () => ({
  format: vi.fn((val, fmt) => `formatted:${fmt}`),
  formatDuration: vi.fn((seconds) => `duration:${seconds}`),
}));

vi.mock('../../networkUtils.js', () => ({
  formatSpeed: vi.fn((speed) => `speed:${speed}`),
}));

import API from '../../../api.js';
import { format, formatDuration } from '../../dateTimeUtils.js';
import { formatSpeed } from '../../networkUtils.js';

describe('M3UsTableUtils', () => {
  beforeEach(() => vi.clearAllMocks());

  // ── API wrappers ────────────────────────────────────────────────────────────
  describe('refreshPlaylist', () => {
    it('calls API.refreshPlaylist with the correct id', () => {
      const mockReturn = Promise.resolve(undefined);
      API.refreshPlaylist.mockReturnValue(mockReturn);
      const result = M3UsTableUtils.refreshPlaylist(3);
      expect(API.refreshPlaylist).toHaveBeenCalledWith(3);
      expect(result).toBe(mockReturn);
    });
  });

  describe('getPlaylistAutoCreatedChannelsCount', () => {
    it('calls API.getPlaylistAutoCreatedChannelsCount with the correct id', () => {
      const mockReturn = Promise.resolve({ count: 5 });
      API.getPlaylistAutoCreatedChannelsCount.mockReturnValue(mockReturn);
      const result = M3UsTableUtils.getPlaylistAutoCreatedChannelsCount(7);
      expect(API.getPlaylistAutoCreatedChannelsCount).toHaveBeenCalledWith(7);
      expect(result).toBe(mockReturn);
    });
  });

  describe('deletePlaylist', () => {
    it('calls API.deletePlaylist with the correct id', () => {
      const mockReturn = Promise.resolve(undefined);
      API.deletePlaylist.mockReturnValue(mockReturn);
      const result = M3UsTableUtils.deletePlaylist(2);
      expect(API.deletePlaylist).toHaveBeenCalledWith(2);
      expect(result).toBe(mockReturn);
    });
  });

  describe('updatePlaylist', () => {
    it('merges values with playlist id and passes isToggle', () => {
      const mockReturn = Promise.resolve({});
      API.updatePlaylist.mockReturnValue(mockReturn);
      const result = M3UsTableUtils.updatePlaylist(
        { is_active: false },
        { id: 10, name: 'Test' },
        true
      );
      expect(API.updatePlaylist).toHaveBeenCalledWith(
        { is_active: false, id: 10 },
        true
      );
      expect(result).toBe(mockReturn);
    });

    it('defaults isToggle to false when not provided', () => {
      API.updatePlaylist.mockReturnValue(Promise.resolve({}));
      M3UsTableUtils.updatePlaylist({ name: 'New' }, { id: 5 });
      expect(API.updatePlaylist).toHaveBeenCalledWith(
        { name: 'New', id: 5 },
        false
      );
    });
  });

  // ── formatStatusText ────────────────────────────────────────────────────────
  describe('formatStatusText', () => {
    it.each([
      ['idle', 'Idle'],
      ['fetching', 'Fetching'],
      ['parsing', 'Parsing'],
      ['error', 'Error'],
      ['success', 'Success'],
      ['pending_setup', 'Pending Setup'],
    ])('returns "%s" for status "%s"', (status, expected) => {
      expect(M3UsTableUtils.formatStatusText(status)).toBe(expected);
    });

    it('capitalizes first letter for unknown status', () => {
      expect(M3UsTableUtils.formatStatusText('loading')).toBe('Loading');
    });

    it('returns "Unknown" for null', () => {
      expect(M3UsTableUtils.formatStatusText(null)).toBe('Unknown');
    });

    it('returns "Unknown" for undefined', () => {
      expect(M3UsTableUtils.formatStatusText(undefined)).toBe('Unknown');
    });

    it('returns "Unknown" for empty string', () => {
      expect(M3UsTableUtils.formatStatusText('')).toBe('Unknown');
    });
  });

  // ── getStatusColor ──────────────────────────────────────────────────────────
  describe('getStatusColor', () => {
    it.each([
      ['idle', 'gray.5'],
      ['fetching', 'blue.5'],
      ['parsing', 'indigo.5'],
      ['error', 'red.5'],
      ['success', 'green.5'],
      ['pending_setup', 'orange.5'],
    ])('returns "%s" for status "%s"', (status, expected) => {
      expect(M3UsTableUtils.getStatusColor(status)).toBe(expected);
    });

    it('returns "gray.5" for unknown status', () => {
      expect(M3UsTableUtils.getStatusColor('unknown')).toBe('gray.5');
    });

    it('returns "gray.5" for null', () => {
      expect(M3UsTableUtils.getStatusColor(null)).toBe('gray.5');
    });
  });

  // ── getExpirationInfo ───────────────────────────────────────────────────────
  describe('getExpirationInfo', () => {
    it('returns red.7 and "Expired" when daysLeft < 0', () => {
      const result = M3UsTableUtils.getExpirationInfo(
        -1,
        '2024-01-01',
        'MM/DD/YYYY'
      );
      expect(result).toEqual({ color: 'red.7', label: 'Expired' });
    });

    it('returns red.5 and "Expires today" when daysLeft === 0', () => {
      const result = M3UsTableUtils.getExpirationInfo(
        0,
        '2024-06-01',
        'MM/DD/YYYY'
      );
      expect(result).toEqual({ color: 'red.5', label: 'Expires today' });
    });

    it('returns orange.5 and "{n}d left" when daysLeft is 1–7', () => {
      expect(M3UsTableUtils.getExpirationInfo(1, null, 'MM/DD/YYYY')).toEqual({
        color: 'orange.5',
        label: '1d left',
      });
      expect(M3UsTableUtils.getExpirationInfo(7, null, 'MM/DD/YYYY')).toEqual({
        color: 'orange.5',
        label: '7d left',
      });
    });

    it('returns yellow.5 and "{n}d left" when daysLeft is 8–30', () => {
      expect(M3UsTableUtils.getExpirationInfo(8, null, 'MM/DD/YYYY')).toEqual({
        color: 'yellow.5',
        label: '8d left',
      });
      expect(M3UsTableUtils.getExpirationInfo(30, null, 'MM/DD/YYYY')).toEqual({
        color: 'yellow.5',
        label: '30d left',
      });
    });

    it('returns formatted date label with no color when daysLeft > 30', () => {
      format.mockReturnValue('12/31/2024');
      const result = M3UsTableUtils.getExpirationInfo(
        60,
        '2024-12-31',
        'MM/DD/YYYY'
      );
      expect(format).toHaveBeenCalledWith('2024-12-31', 'MM/DD/YYYY');
      expect(result.label).toBe('12/31/2024');
      expect(result.color).toBeUndefined();
    });
  });

  // ── getExpirationTooltip ────────────────────────────────────────────────────
  describe('getExpirationTooltip', () => {
    it('returns the fallback label when allExpirations is empty', () => {
      const result = M3UsTableUtils.getExpirationTooltip(
        [],
        'MM/DD/YYYY HH:mm',
        '7d left'
      );
      expect(result).toBe('7d left');
    });

    it('formats each expiration entry with profile name and date', () => {
      format.mockImplementation(() => `2024-12-31`);
      const expirations = [
        { profile_name: 'Profile A', exp_date: '2024-12-31', is_active: true },
        { profile_name: 'Profile B', exp_date: '2024-11-30', is_active: false },
      ];
      const result = M3UsTableUtils.getExpirationTooltip(
        expirations,
        'MM/DD/YYYY HH:mm',
        'fallback'
      );
      expect(result).toContain('Profile A: 2024-12-31');
      expect(result).toContain('Profile B: 2024-12-31 (inactive)');
    });

    it('does not append "(inactive)" for active profiles', () => {
      format.mockReturnValue('2024-12-31');
      const expirations = [
        { profile_name: 'Active', exp_date: '2024-12-31', is_active: true },
      ];
      const result = M3UsTableUtils.getExpirationTooltip(
        expirations,
        'MM/DD/YYYY',
        'fallback'
      );
      expect(result).not.toContain('(inactive)');
    });

    it('joins multiple entries with newline', () => {
      format.mockReturnValue('2024-12-31');
      const expirations = [
        { profile_name: 'A', exp_date: '2024-12-31', is_active: true },
        { profile_name: 'B', exp_date: '2024-12-31', is_active: true },
      ];
      const result = M3UsTableUtils.getExpirationTooltip(
        expirations,
        'MM/DD/YYYY',
        'fallback'
      );
      expect(result.split('\n')).toHaveLength(2);
    });
  });

  // ── getSortedPlaylists ──────────────────────────────────────────────────────
  describe('getSortedPlaylists', () => {
    const playlists = [
      { id: 1, name: 'Zebra', locked: false, max_streams: 5 },
      { id: 2, name: 'Alpha', locked: false, max_streams: 10 },
      { id: 3, name: 'Middle', locked: true, max_streams: 1 },
      { id: 4, name: 'Beta', locked: false, max_streams: 3 },
    ];

    it('excludes locked playlists', () => {
      const result = M3UsTableUtils.getSortedPlaylists(
        playlists,
        'name',
        false
      );
      expect(result.find((p) => p.id === 3)).toBeUndefined();
      expect(result).toHaveLength(3);
    });

    it('sorts by string column ascending', () => {
      const result = M3UsTableUtils.getSortedPlaylists(
        playlists,
        'name',
        false
      );
      expect(result.map((p) => p.name)).toEqual(['Alpha', 'Beta', 'Zebra']);
    });

    it('sorts by string column descending', () => {
      const result = M3UsTableUtils.getSortedPlaylists(playlists, 'name', true);
      expect(result.map((p) => p.name)).toEqual(['Zebra', 'Beta', 'Alpha']);
    });

    it('sorts by numeric column ascending', () => {
      const result = M3UsTableUtils.getSortedPlaylists(
        playlists,
        'max_streams',
        false
      );
      expect(result.map((p) => p.max_streams)).toEqual([3, 5, 10]);
    });

    it('sorts by numeric column descending', () => {
      const result = M3UsTableUtils.getSortedPlaylists(
        playlists,
        'max_streams',
        true
      );
      expect(result.map((p) => p.max_streams)).toEqual([10, 5, 3]);
    });

    it('sorts nulls to the end regardless of direction', () => {
      const withNulls = [
        { id: 1, name: null, locked: false },
        { id: 2, name: 'Alpha', locked: false },
        { id: 3, name: null, locked: false },
      ];
      const asc = M3UsTableUtils.getSortedPlaylists(withNulls, 'name', false);
      expect(asc[asc.length - 1].name).toBeNull();
      expect(asc[asc.length - 2].name).toBeNull();

      const desc = M3UsTableUtils.getSortedPlaylists(withNulls, 'name', true);
      expect(desc[desc.length - 1].name).toBeNull();
    });

    it('returns empty array when all playlists are locked', () => {
      const locked = [{ id: 1, name: 'Locked', locked: true }];
      expect(M3UsTableUtils.getSortedPlaylists(locked, 'name', false)).toEqual(
        []
      );
    });
  });

  // ── getStatusContent ────────────────────────────────────────────────────────
  describe('getStatusContent', () => {
    it('returns null when progress is 100', () => {
      expect(
        M3UsTableUtils.getStatusContent({ progress: 100, action: 'parsing' })
      ).toBeNull();
    });

    it('returns initializing type for initializing action', () => {
      expect(
        M3UsTableUtils.getStatusContent({
          progress: 50,
          action: 'initializing',
        })
      ).toEqual({ type: 'initializing' });
    });

    describe('downloading', () => {
      it('returns simple label when progress is 0', () => {
        expect(
          M3UsTableUtils.getStatusContent({
            progress: 0,
            action: 'downloading',
          })
        ).toEqual({ type: 'simple', label: 'Downloading...' });
      });

      it('returns downloading object with formatted fields when progress > 0', () => {
        formatSpeed.mockReturnValue('speed:512');
        formatDuration.mockReturnValue('duration:30');
        const result = M3UsTableUtils.getStatusContent({
          action: 'downloading',
          progress: 50,
          speed: 512,
          time_remaining: 30,
        });
        expect(result).toEqual({
          type: 'downloading',
          progress: 50,
          speed: 'speed:512',
          timeRemaining: 'duration:30',
        });
        expect(formatSpeed).toHaveBeenCalledWith(512);
        expect(formatDuration).toHaveBeenCalledWith(30);
      });

      it('returns "calculating..." when time_remaining is absent', () => {
        formatSpeed.mockReturnValue('speed:512');
        const result = M3UsTableUtils.getStatusContent({
          action: 'downloading',
          progress: 25,
          speed: 512,
        });
        expect(result.timeRemaining).toBe('calculating...');
      });
    });

    describe('processing_groups', () => {
      it('returns simple label when progress is 0', () => {
        expect(
          M3UsTableUtils.getStatusContent({
            progress: 0,
            action: 'processing_groups',
          })
        ).toEqual({ type: 'simple', label: 'Processing groups...' });
      });

      it('returns groups object with formatted elapsed time', () => {
        formatDuration.mockReturnValue('duration:120');
        const result = M3UsTableUtils.getStatusContent({
          action: 'processing_groups',
          progress: 40,
          elapsed_time: 120,
          groups_processed: 15,
        });
        expect(result).toEqual({
          type: 'groups',
          progress: 40,
          elapsedTime: 'duration:120',
          groupsProcessed: 15,
        });
        expect(formatDuration).toHaveBeenCalledWith(120);
      });
    });

    describe('parsing', () => {
      it('returns simple label when progress is 0', () => {
        expect(
          M3UsTableUtils.getStatusContent({ progress: 0, action: 'parsing' })
        ).toEqual({ type: 'simple', label: 'Parsing...' });
      });

      it('returns parsing object with all fields', () => {
        formatDuration.mockReturnValue('duration:60');
        const result = M3UsTableUtils.getStatusContent({
          action: 'parsing',
          progress: 75,
          elapsed_time: 60,
          time_remaining: 20,
          streams_processed: 1000,
        });
        expect(result).toEqual({
          type: 'parsing',
          progress: 75,
          elapsedTime: 'duration:60',
          timeRemaining: 'duration:60',
          streamsProcessed: 1000,
        });
      });

      it('returns "calculating..." when time_remaining is absent', () => {
        formatDuration.mockReturnValue('duration:60');
        const result = M3UsTableUtils.getStatusContent({
          action: 'parsing',
          progress: 50,
          elapsed_time: 60,
        });
        expect(result.timeRemaining).toBe('calculating...');
      });
    });

    describe('default / error', () => {
      it('returns error type when status is error', () => {
        const result = M3UsTableUtils.getStatusContent({
          action: 'unknown',
          progress: 50,
          status: 'error',
          error: 'Something went wrong',
        });
        expect(result).toEqual({
          type: 'error',
          error: 'Something went wrong',
        });
      });

      it('returns simple label with action name for unknown non-error action', () => {
        const result = M3UsTableUtils.getStatusContent({
          action: 'custom_action',
          progress: 50,
          status: 'running',
        });
        expect(result).toEqual({ type: 'simple', label: 'custom_action...' });
      });

      it('returns "Processing..." label when action is undefined', () => {
        const result = M3UsTableUtils.getStatusContent({
          progress: 30,
          status: 'running',
        });
        expect(result).toEqual({ type: 'simple', label: 'Processing...' });
      });
    });
  });
});
