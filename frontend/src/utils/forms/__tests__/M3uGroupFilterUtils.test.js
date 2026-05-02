import { describe, it, expect, vi, beforeEach } from 'vitest';
import {
  buildGroupStates,
  saveAndRefreshPlaylist,
} from '../M3uGroupFilterUtils.js';

// ── API mock ───────────────────────────────────────────────────────────────────
vi.mock('../../../api.js', () => ({
  default: {
    updateM3UGroupSettings: vi.fn(),
  },
}));

// ── M3uUtils mock ──────────────────────────────────────────────────────────────
vi.mock('../M3uUtils.js', () => ({
  refreshPlaylist: vi.fn(),
  updatePlaylist: vi.fn(),
}));

import API from '../../../api.js';
import { refreshPlaylist, updatePlaylist } from '../M3uUtils.js';

// ── Helpers ────────────────────────────────────────────────────────────────────
const makePlaylist = (overrides = {}) => ({ id: 'playlist-1', name: 'My Playlist', ...overrides });

const makeChannelGroups = () => ({
  'group-1': { name: 'Sports' },
  'group-2': { name: 'News' },
  'group-3': { name: 'Movies' },
});

const makePlaylistChannelGroup = (overrides = {}) => ({
  channel_group: 'group-1',
  enabled: true,
  original_enabled: false,
  auto_channel_sync: false,
  auto_sync_channel_start: 1.0,
  custom_properties: null,
  ...overrides,
});

const makeCategoryState = (overrides = {}) => ({
  id: 'cat-1',
  enabled: true,
  original_enabled: false,
  custom_properties: null,
  ...overrides,
});

const makeAutoEnableSettings = () => ({ auto_enable: true });

describe('M3uGroupFilterUtils', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(updatePlaylist).mockResolvedValue(undefined);
    vi.mocked(API.updateM3UGroupSettings).mockResolvedValue(undefined);
    vi.mocked(refreshPlaylist).mockResolvedValue(undefined);
  });

  // ── buildGroupStates ───────────────────────────────────────────────────────

  describe('buildGroupStates', () => {
    it('maps playlistChannelGroups to group states with channel group names', () => {
      const channelGroups = makeChannelGroups();
      const playlistChannelGroups = [makePlaylistChannelGroup()];

      const result = buildGroupStates(channelGroups, playlistChannelGroups);

      expect(result).toHaveLength(1);
      expect(result[0].name).toBe('Sports');
    });

    it('filters out groups whose channel_group key is not in channelGroups', () => {
      const channelGroups = makeChannelGroups();
      const playlistChannelGroups = [
        makePlaylistChannelGroup({ channel_group: 'group-1' }),
        makePlaylistChannelGroup({ channel_group: 'group-unknown' }),
      ];

      const result = buildGroupStates(channelGroups, playlistChannelGroups);

      expect(result).toHaveLength(1);
      expect(result[0].channel_group).toBe('group-1');
    });

    it('returns an empty array when playlistChannelGroups is empty', () => {
      const result = buildGroupStates(makeChannelGroups(), []);
      expect(result).toEqual([]);
    });

    it('returns an empty array when no groups match channelGroups', () => {
      const result = buildGroupStates(makeChannelGroups(), [
        makePlaylistChannelGroup({ channel_group: 'group-unknown' }),
      ]);
      expect(result).toEqual([]);
    });

    it('defaults auto_channel_sync to false when not set', () => {
      const result = buildGroupStates(makeChannelGroups(), [
        makePlaylistChannelGroup({ auto_channel_sync: undefined }),
      ]);
      expect(result[0].auto_channel_sync).toBe(false);
    });

    it('preserves auto_channel_sync when set to true', () => {
      const result = buildGroupStates(makeChannelGroups(), [
        makePlaylistChannelGroup({ auto_channel_sync: true }),
      ]);
      expect(result[0].auto_channel_sync).toBe(true);
    });

    it('defaults auto_sync_channel_start to 1.0 when not set', () => {
      const result = buildGroupStates(makeChannelGroups(), [
        makePlaylistChannelGroup({ auto_sync_channel_start: undefined }),
      ]);
      expect(result[0].auto_sync_channel_start).toBe(1.0);
    });

    it('preserves auto_sync_channel_start when set', () => {
      const result = buildGroupStates(makeChannelGroups(), [
        makePlaylistChannelGroup({ auto_sync_channel_start: 5.0 }),
      ]);
      expect(result[0].auto_sync_channel_start).toBe(5.0);
    });

    it('spreads all original group properties into the result', () => {
      const group = makePlaylistChannelGroup({ enabled: true, extra_prop: 'value' });
      const result = buildGroupStates(makeChannelGroups(), [group]);
      expect(result[0].enabled).toBe(true);
      expect(result[0].extra_prop).toBe('value');
    });

    it('maps multiple groups correctly', () => {
      const channelGroups = makeChannelGroups();
      const playlistChannelGroups = [
        makePlaylistChannelGroup({ channel_group: 'group-1' }),
        makePlaylistChannelGroup({ channel_group: 'group-2' }),
        makePlaylistChannelGroup({ channel_group: 'group-3' }),
      ];

      const result = buildGroupStates(channelGroups, playlistChannelGroups);

      expect(result).toHaveLength(3);
      expect(result.map((r) => r.name)).toEqual(['Sports', 'News', 'Movies']);
    });

    // ── parseCustomProperties (via buildGroupStates) ─────────────────────────

    describe('parseCustomProperties (via custom_properties field)', () => {
      it('returns {} when custom_properties is null', () => {
        const result = buildGroupStates(makeChannelGroups(), [
          makePlaylistChannelGroup({ custom_properties: null }),
        ]);
        expect(result[0].custom_properties).toEqual({});
      });

      it('returns {} when custom_properties is undefined', () => {
        const result = buildGroupStates(makeChannelGroups(), [
          makePlaylistChannelGroup({ custom_properties: undefined }),
        ]);
        expect(result[0].custom_properties).toEqual({});
      });

      it('parses a valid JSON string into an object', () => {
        const result = buildGroupStates(makeChannelGroups(), [
          makePlaylistChannelGroup({ custom_properties: '{"key":"value"}' }),
        ]);
        expect(result[0].custom_properties).toEqual({ key: 'value' });
      });

      it('returns an already-parsed object as-is', () => {
        const result = buildGroupStates(makeChannelGroups(), [
          makePlaylistChannelGroup({ custom_properties: { key: 'value' } }),
        ]);
        expect(result[0].custom_properties).toEqual({ key: 'value' });
      });

      it('returns {} for invalid JSON string', () => {
        const result = buildGroupStates(makeChannelGroups(), [
          makePlaylistChannelGroup({ custom_properties: '{invalid-json}' }),
        ]);
        expect(result[0].custom_properties).toEqual({});
      });
    });
  });

  // ── saveAndRefreshPlaylist ─────────────────────────────────────────────────

  describe('saveAndRefreshPlaylist', () => {
    it('calls updatePlaylist with playlist and autoEnableSettings', async () => {
      const playlist = makePlaylist();
      const autoEnableSettings = makeAutoEnableSettings();

      await saveAndRefreshPlaylist(playlist, [], [], [], autoEnableSettings);

      expect(updatePlaylist).toHaveBeenCalledWith(playlist, autoEnableSettings);
    });

    it('calls API.updateM3UGroupSettings with playlist id, groupSettings, and categorySettings', async () => {
      const playlist = makePlaylist();

      await saveAndRefreshPlaylist(playlist, [], [], [], makeAutoEnableSettings());

      expect(API.updateM3UGroupSettings).toHaveBeenCalledWith(
        'playlist-1',
        expect.anything(),
        expect.anything()
      );
    });

    it('calls refreshPlaylist with playlist', async () => {
      const playlist = makePlaylist();

      await saveAndRefreshPlaylist(playlist, [], [], [], makeAutoEnableSettings());

      expect(refreshPlaylist).toHaveBeenCalledWith(playlist);
    });

    it('calls updatePlaylist, updateM3UGroupSettings, and refreshPlaylist exactly once each', async () => {
      await saveAndRefreshPlaylist(makePlaylist(), [], [], [], makeAutoEnableSettings());

      expect(updatePlaylist).toHaveBeenCalledTimes(1);
      expect(API.updateM3UGroupSettings).toHaveBeenCalledTimes(1);
      expect(refreshPlaylist).toHaveBeenCalledTimes(1);
    });

    it('calls updatePlaylist before updateM3UGroupSettings', async () => {
      const callOrder = [];
      vi.mocked(updatePlaylist).mockImplementation(async () => { callOrder.push('updatePlaylist'); });
      vi.mocked(API.updateM3UGroupSettings).mockImplementation(async () => { callOrder.push('updateM3UGroupSettings'); });
      vi.mocked(refreshPlaylist).mockImplementation(async () => { callOrder.push('refreshPlaylist'); });

      await saveAndRefreshPlaylist(makePlaylist(), [], [], [], makeAutoEnableSettings());

      expect(callOrder.indexOf('updatePlaylist')).toBeLessThan(
        callOrder.indexOf('updateM3UGroupSettings')
      );
    });

    it('calls updateM3UGroupSettings before refreshPlaylist', async () => {
      const callOrder = [];
      vi.mocked(updatePlaylist).mockImplementation(async () => { callOrder.push('updatePlaylist'); });
      vi.mocked(API.updateM3UGroupSettings).mockImplementation(async () => { callOrder.push('updateM3UGroupSettings'); });
      vi.mocked(refreshPlaylist).mockImplementation(async () => { callOrder.push('refreshPlaylist'); });

      await saveAndRefreshPlaylist(makePlaylist(), [], [], [], makeAutoEnableSettings());

      expect(callOrder.indexOf('updateM3UGroupSettings')).toBeLessThan(
        callOrder.indexOf('refreshPlaylist')
      );
    });

    it('propagates rejection from updatePlaylist', async () => {
      vi.mocked(updatePlaylist).mockRejectedValue(new Error('Update failed'));

      await expect(
        saveAndRefreshPlaylist(makePlaylist(), [], [], [], makeAutoEnableSettings())
      ).rejects.toThrow('Update failed');
    });

    it('propagates rejection from API.updateM3UGroupSettings', async () => {
      vi.mocked(API.updateM3UGroupSettings).mockRejectedValue(new Error('Settings failed'));

      await expect(
        saveAndRefreshPlaylist(makePlaylist(), [], [], [], makeAutoEnableSettings())
      ).rejects.toThrow('Settings failed');
    });

    it('propagates rejection from refreshPlaylist', async () => {
      vi.mocked(refreshPlaylist).mockRejectedValue(new Error('Refresh failed'));

      await expect(
        saveAndRefreshPlaylist(makePlaylist(), [], [], [], makeAutoEnableSettings())
      ).rejects.toThrow('Refresh failed');
    });

    it('does not call refreshPlaylist when updateM3UGroupSettings rejects', async () => {
      vi.mocked(API.updateM3UGroupSettings).mockRejectedValue(new Error('fail'));

      await saveAndRefreshPlaylist(makePlaylist(), [], [], [], makeAutoEnableSettings()).catch(() => {});

      expect(refreshPlaylist).not.toHaveBeenCalled();
    });

    // ── prepareCategorySettings (via categorySettings arg) ───────────────────

    describe('prepareCategorySettings (via API.updateM3UGroupSettings call)', () => {
      it('includes category states where enabled differs from original_enabled', async () => {
        const changedMovie = makeCategoryState({ enabled: true, original_enabled: false });
        const unchangedMovie = makeCategoryState({ id: 'cat-2', enabled: false, original_enabled: false });

        await saveAndRefreshPlaylist(
          makePlaylist(), [], [changedMovie], [unchangedMovie], makeAutoEnableSettings()
        );

        const [, , categorySettings] = vi.mocked(API.updateM3UGroupSettings).mock.calls[0];
        expect(categorySettings).toHaveLength(1);
        expect(categorySettings[0].id).toBe('cat-1');
      });

      it('excludes category states where enabled equals original_enabled', async () => {
        const unchanged = makeCategoryState({ enabled: true, original_enabled: true });

        await saveAndRefreshPlaylist(
          makePlaylist(), [], [unchanged], [], makeAutoEnableSettings()
        );

        const [, , categorySettings] = vi.mocked(API.updateM3UGroupSettings).mock.calls[0];
        expect(categorySettings).toHaveLength(0);
      });

      it('merges movie and series category states together', async () => {
        const movieCat = makeCategoryState({ id: 'movie-1', enabled: true, original_enabled: false });
        const seriesCat = makeCategoryState({ id: 'series-1', enabled: false, original_enabled: true });

        await saveAndRefreshPlaylist(
          makePlaylist(), [], [movieCat], [seriesCat], makeAutoEnableSettings()
        );

        const [, , categorySettings] = vi.mocked(API.updateM3UGroupSettings).mock.calls[0];
        expect(categorySettings).toHaveLength(2);
        expect(categorySettings.map((c) => c.id)).toEqual(['movie-1', 'series-1']);
      });

      it('sets custom_properties to undefined when null', async () => {
        const cat = makeCategoryState({ custom_properties: null, enabled: true, original_enabled: false });

        await saveAndRefreshPlaylist(
          makePlaylist(), [], [cat], [], makeAutoEnableSettings()
        );

        const [, , categorySettings] = vi.mocked(API.updateM3UGroupSettings).mock.calls[0];
        expect(categorySettings[0].custom_properties).toBeUndefined();
      });

      it('preserves custom_properties when present', async () => {
        const cat = makeCategoryState({
          custom_properties: { key: 'value' },
          enabled: true,
          original_enabled: false,
        });

        await saveAndRefreshPlaylist(
          makePlaylist(), [], [cat], [], makeAutoEnableSettings()
        );

        const [, , categorySettings] = vi.mocked(API.updateM3UGroupSettings).mock.calls[0];
        expect(categorySettings[0].custom_properties).toEqual({ key: 'value' });
      });
    });
  });
});