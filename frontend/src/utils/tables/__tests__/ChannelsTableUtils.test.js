import { describe, it, expect, vi, beforeEach } from 'vitest';
import * as ChannelsTableUtils from '../ChannelsTableUtils';

// ── Dependency mocks ────────────────────────────────────────────────────────
vi.mock('../../forms/ChannelUtils.js', () => ({
  normalizeFieldValue: vi.fn((field, value) => {
    if (value === '' || value === null || value === undefined) return null;
    if (field === 'channel_number') return parseFloat(value);
    if (['channel_group_id', 'logo_id', 'epg_data_id', 'stream_profile_id'].includes(field)) {
      return parseInt(value, 10);
    }
    return value;
  }),
  OVERRIDABLE_FIELDS: [
    'name',
    'channel_number',
    'channel_group_id',
    'logo_id',
    'tvg_id',
    'tvc_guide_stationid',
    'epg_data_id',
    'stream_profile_id',
  ],
}));

vi.mock('../../../api.js', () => ({
  default: {
    reorderChannel: vi.fn(),
    deleteChannel: vi.fn(),
    deleteChannels: vi.fn(),
    queryChannels: vi.fn(),
    getAllChannelIds: vi.fn(),
    updateProfileChannels: vi.fn(),
    updateProfileChannel: vi.fn(),
    addChannelProfile: vi.fn(),
    deleteChannelProfile: vi.fn(),
  },
}));

import API from '../../../api.js';

describe('ChannelsTableUtils', () => {
  // ── buildInlinePatch ────────────────────────────────────────────────────────
  describe('buildInlinePatch', () => {
    describe('manual channel (auto_created = false)', () => {
      const row = { id: 1, auto_created: false, name: 'CNN' };

      it('returns direct patch for a string field', () => {
        expect(ChannelsTableUtils.buildInlinePatch(row, 'name', 'BBC')).toEqual(
          {
            id: 1,
            name: 'BBC',
          }
        );
      });

      it('normalizes empty string to null', () => {
        expect(ChannelsTableUtils.buildInlinePatch(row, 'name', '')).toEqual({
          id: 1,
          name: null,
        });
      });

      it('normalizes undefined to null', () => {
        expect(
          ChannelsTableUtils.buildInlinePatch(row, 'name', undefined)
        ).toEqual({
          id: 1,
          name: null,
        });
      });

      it('passes through numeric values', () => {
        expect(
          ChannelsTableUtils.buildInlinePatch(row, 'channel_number', 5)
        ).toEqual({
          id: 1,
          channel_number: 5,
        });
      });
    });

    describe('auto-synced channel (auto_created = true)', () => {
      const row = {
        id: 2,
        auto_created: true,
        name: 'ESPN',
        channel_number: 10,
        epg_data_id: 99,
      };

      it('returns override patch when value differs from provider', () => {
        const result = ChannelsTableUtils.buildInlinePatch(
          row,
          'name',
          'ESPN HD'
        );
        expect(result).toEqual({
          id: 2,
          override: { name: 'ESPN HD' },
        });
      });

      it('clears override when new value matches provider value', () => {
        const result = ChannelsTableUtils.buildInlinePatch(row, 'name', 'ESPN');
        expect(result).toEqual({
          id: 2,
          override: { name: null },
        });
      });

      it('returns override patch for channel_number field', () => {
        const result = ChannelsTableUtils.buildInlinePatch(
          row,
          'channel_number',
          20
        );
        expect(result).toEqual({
          id: 2,
          override: { channel_number: 20 },
        });
      });

      it('clears override for channel_number when value matches provider', () => {
        const result = ChannelsTableUtils.buildInlinePatch(
          row,
          'channel_number',
          10
        );
        expect(result).toEqual({
          id: 2,
          override: { channel_number: null },
        });
      });

      it('uses direct patch for non-overridable field on auto-synced channel', () => {
        const result = ChannelsTableUtils.buildInlinePatch(
          row,
          'some_other_field',
          'value'
        );
        expect(result).toEqual({
          id: 2,
          some_other_field: 'value',
        });
      });
    });
  });

  // ── getEpgOptions ───────────────────────────────────────────────────────────
  describe('getEpgOptions', () => {
    const epgs = {
      1: { id: 1, name: 'EPG Alpha' },
      2: { id: 2, name: 'EPG Beta' },
    };

    const tvgsById = {
      10: { id: 10, tvg_id: 'cnn', name: 'CNN', epg_source: 1 },
      11: { id: 11, tvg_id: 'bbc', name: 'BBC', epg_source: 2 },
      12: { id: 12, tvg_id: 'espn', name: 'ESPN', epg_source: 1 },
    };

    it('includes "Not Assigned" as the first option', () => {
      const options = ChannelsTableUtils.getEpgOptions(tvgsById, epgs);
      expect(options[0]).toEqual({ value: 'null', label: 'Not Assigned' });
    });

    it('returns an option for each tvg entry', () => {
      const options = ChannelsTableUtils.getEpgOptions(tvgsById, epgs);
      expect(options).toHaveLength(4); // 1 null + 3 tvgs
    });

    it('formats label as "EPG Name | tvg_id | tvg name" when all present and name differs from tvg_id', () => {
      const options = ChannelsTableUtils.getEpgOptions(tvgsById, epgs);
      const cnn = options.find((o) => o.value === '10');
      expect(cnn?.label).toBe('EPG Alpha | cnn | CNN');
    });

    it('omits tvg name from label when name equals tvg_id', () => {
      const tvgs = {
        10: { id: 10, tvg_id: 'CNN', name: 'CNN', epg_source: 1 },
      };
      const options = ChannelsTableUtils.getEpgOptions(tvgs, epgs);
      const opt = options.find((o) => o.value === '10');
      expect(opt?.label).toBe('EPG Alpha | CNN');
    });

    it('uses tvg name as label when no epg_source and no tvg_id', () => {
      const tvgs = {
        20: { id: 20, tvg_id: null, name: 'Standalone', epg_source: null },
      };
      const options = ChannelsTableUtils.getEpgOptions(tvgs, {});
      const opt = options.find((o) => o.value === '20');
      expect(opt?.label).toBe('Standalone');
    });

    it('falls back to "ID: {id}" when no name and no tvg_id', () => {
      const tvgs = {
        30: { id: 30, tvg_id: null, name: null, epg_source: null },
      };
      const options = ChannelsTableUtils.getEpgOptions(tvgs, {});
      const opt = options.find((o) => o.value === '30');
      expect(opt?.label).toBe('ID: 30');
    });

    it('sorts options by EPG source name then tvg_id', () => {
      const options = ChannelsTableUtils.getEpgOptions(tvgsById, epgs);
      // EPG Alpha entries (cnn, espn) should come before EPG Beta (bbc)
      const labels = options.slice(1).map((o) => o.label);
      const alphaCnn = labels.findIndex((l) => l.includes('cnn'));
      const alphaEspn = labels.findIndex((l) => l.includes('espn'));
      const betaBbc = labels.findIndex((l) => l.includes('bbc'));
      expect(alphaCnn).toBeLessThan(betaBbc);
      expect(alphaEspn).toBeLessThan(betaBbc);
    });

    it('returns only the null option for empty tvgsById', () => {
      const options = ChannelsTableUtils.getEpgOptions({}, epgs);
      expect(options).toHaveLength(1);
      expect(options[0].value).toBe('null');
    });
  });

  // ── getLogoOptions ──────────────────────────────────────────────────────────
  describe('getLogoOptions', () => {
    const logos = {
      1: { id: 1, name: 'ABC Logo' },
      2: { id: 2, name: 'NBC Logo' },
      3: { id: 3, name: null },
    };

    it('includes "Default" as the first option', () => {
      const options = ChannelsTableUtils.getLogoOptions(logos);
      expect(options[0]).toEqual({
        value: 'null',
        label: 'Default',
        logo: null,
      });
    });

    it('returns an option for each logo', () => {
      const options = ChannelsTableUtils.getLogoOptions(logos);
      expect(options).toHaveLength(4); // 1 default + 3 logos
    });

    it('uses logo name as label', () => {
      const options = ChannelsTableUtils.getLogoOptions(logos);
      const abc = options.find((o) => o.value === '1');
      expect(abc?.label).toBe('ABC Logo');
      expect(abc?.logo).toEqual({ id: 1, name: 'ABC Logo' });
    });

    it('falls back to "Logo {id}" when name is null', () => {
      const options = ChannelsTableUtils.getLogoOptions(logos);
      const noName = options.find((o) => o.value === '3');
      expect(noName?.label).toBe('Logo 3');
    });

    it('sorts logos by name', () => {
      const options = ChannelsTableUtils.getLogoOptions(logos);
      const names = options.slice(2).map((o) => o.label);
      expect(names[0]).toBe('ABC Logo');
      expect(names[1]).toBe('NBC Logo');
    });

    it('returns only the default option for empty logos', () => {
      const options = ChannelsTableUtils.getLogoOptions({});
      expect(options).toHaveLength(1);
    });
  });

  // ── buildM3UUrl ─────────────────────────────────────────────────────────────
  describe('buildM3UUrl', () => {
    const baseUrl = 'http://localhost/output/m3u';
    const defaults = {
      cachedlogos: true,
      direct: false,
      tvg_id_source: 'channel_number',
      output_format: '',
      output_profile: '',
    };

    it('returns base URL with no params when all defaults', () => {
      expect(ChannelsTableUtils.buildM3UUrl(defaults, baseUrl)).toBe(baseUrl);
    });

    it('appends cachedlogos=false when disabled', () => {
      const result = ChannelsTableUtils.buildM3UUrl(
        { ...defaults, cachedlogos: false },
        baseUrl
      );
      expect(result).toContain('cachedlogos=false');
    });

    it('appends direct=true when enabled', () => {
      const result = ChannelsTableUtils.buildM3UUrl(
        { ...defaults, direct: true },
        baseUrl
      );
      expect(result).toContain('direct=true');
    });

    it('appends tvg_id_source when not channel_number', () => {
      const result = ChannelsTableUtils.buildM3UUrl(
        { ...defaults, tvg_id_source: 'tvg_id' },
        baseUrl
      );
      expect(result).toContain('tvg_id_source=tvg_id');
    });

    it('does not append tvg_id_source when channel_number', () => {
      const result = ChannelsTableUtils.buildM3UUrl(defaults, baseUrl);
      expect(result).not.toContain('tvg_id_source');
    });

    it('appends output_format when set', () => {
      const result = ChannelsTableUtils.buildM3UUrl(
        { ...defaults, output_format: 'mpegts' },
        baseUrl
      );
      expect(result).toContain('output_format=mpegts');
    });

    it('appends output_profile when set', () => {
      const result = ChannelsTableUtils.buildM3UUrl(
        { ...defaults, output_profile: '3' },
        baseUrl
      );
      expect(result).toContain('output_profile=3');
    });
  });

  // ── buildEPGUrl ─────────────────────────────────────────────────────────────
  describe('buildEPGUrl', () => {
    const baseUrl = 'http://localhost/output/epg';
    const defaults = {
      cachedlogos: true,
      tvg_id_source: 'channel_number',
      days: 0,
      prev_days: 0,
    };

    it('returns base URL with no params when all defaults', () => {
      expect(ChannelsTableUtils.buildEPGUrl(defaults, baseUrl)).toBe(baseUrl);
    });

    it('appends cachedlogos=false when disabled', () => {
      const result = ChannelsTableUtils.buildEPGUrl(
        { ...defaults, cachedlogos: false },
        baseUrl
      );
      expect(result).toContain('cachedlogos=false');
    });

    it('appends tvg_id_source when not channel_number', () => {
      const result = ChannelsTableUtils.buildEPGUrl(
        { ...defaults, tvg_id_source: 'gracenote' },
        baseUrl
      );
      expect(result).toContain('tvg_id_source=gracenote');
    });

    it('appends days when > 0', () => {
      const result = ChannelsTableUtils.buildEPGUrl(
        { ...defaults, days: 7 },
        baseUrl
      );
      expect(result).toContain('days=7');
    });

    it('does not append days when 0', () => {
      const result = ChannelsTableUtils.buildEPGUrl(defaults, baseUrl);
      expect(result).not.toContain('days');
    });

    it('appends prev_days when > 0', () => {
      const result = ChannelsTableUtils.buildEPGUrl(
        { ...defaults, prev_days: 3 },
        baseUrl
      );
      expect(result).toContain('prev_days=3');
    });
  });

  // ── buildHDHRUrl ────────────────────────────────────────────────────────────
  describe('buildHDHRUrl', () => {
    it('returns hdhrUrl unchanged when no output profile', () => {
      expect(ChannelsTableUtils.buildHDHRUrl('', 'http://localhost/hdhr')).toBe(
        'http://localhost/hdhr'
      );
    });

    it('appends output_profile segment when profile id provided', () => {
      expect(
        ChannelsTableUtils.buildHDHRUrl('2', 'http://localhost/hdhr')
      ).toBe('http://localhost/hdhr/output_profile/2');
    });

    it('strips trailing slash before appending', () => {
      expect(
        ChannelsTableUtils.buildHDHRUrl('1', 'http://localhost/hdhr/')
      ).toBe('http://localhost/hdhr/output_profile/1');
    });
  });

  // ── buildFetchParams ────────────────────────────────────────────────────────
  describe('buildFetchParams', () => {
    const defaults = {
      pagination: { pageIndex: 0, pageSize: 50 },
      sorting: [],
      debouncedFilters: {},
      selectedProfileId: '0',
      showDisabled: false,
      showOnlyStreamlessChannels: false,
      showOnlyStaleChannels: false,
      showOnlyOverriddenChannels: false,
      showOnlyCatchupChannels: false,
      visibilityFilter: 'active',
    };

    it('always includes page, page_size, and include_streams', () => {
      const params = ChannelsTableUtils.buildFetchParams(defaults);
      expect(params.get('page')).toBe('1');
      expect(params.get('page_size')).toBe('50');
      expect(params.get('include_streams')).toBe('true');
    });

    it('increments page by 1 from pageIndex', () => {
      const params = ChannelsTableUtils.buildFetchParams({
        ...defaults,
        pagination: { pageIndex: 2, pageSize: 25 },
      });
      expect(params.get('page')).toBe('3');
      expect(params.get('page_size')).toBe('25');
    });

    it('does not include channel_profile_id when selectedProfileId is "0"', () => {
      const params = ChannelsTableUtils.buildFetchParams(defaults);
      expect(params.get('channel_profile_id')).toBeNull();
    });

    it('includes channel_profile_id when selectedProfileId is not "0"', () => {
      const params = ChannelsTableUtils.buildFetchParams({
        ...defaults,
        selectedProfileId: '3',
      });
      expect(params.get('channel_profile_id')).toBe('3');
    });

    it('includes show_disabled when true', () => {
      const params = ChannelsTableUtils.buildFetchParams({
        ...defaults,
        showDisabled: true,
      });
      expect(params.get('show_disabled')).toBe('true');
    });

    it('includes only_streamless when true', () => {
      const params = ChannelsTableUtils.buildFetchParams({
        ...defaults,
        showOnlyStreamlessChannels: true,
      });
      expect(params.get('only_streamless')).toBe('true');
    });

    it('includes only_stale when true', () => {
      const params = ChannelsTableUtils.buildFetchParams({
        ...defaults,
        showOnlyStaleChannels: true,
      });
      expect(params.get('only_stale')).toBe('true');
    });

    it('includes only_has_overrides when true', () => {
      const params = ChannelsTableUtils.buildFetchParams({
        ...defaults,
        showOnlyOverriddenChannels: true,
      });
      expect(params.get('only_has_overrides')).toBe('true');
    });

    it('includes only_catchup when true', () => {
      const params = ChannelsTableUtils.buildFetchParams({
        ...defaults,
        showOnlyCatchupChannels: true,
      });
      expect(params.get('only_catchup')).toBe('true');
    });

    it('does not include visibility_filter when "active"', () => {
      const params = ChannelsTableUtils.buildFetchParams(defaults);
      expect(params.get('visibility_filter')).toBeNull();
    });

    it('includes visibility_filter when not "active"', () => {
      const params = ChannelsTableUtils.buildFetchParams({
        ...defaults,
        visibilityFilter: 'hidden',
      });
      expect(params.get('visibility_filter')).toBe('hidden');
    });

    it('includes ordering with ascending sort', () => {
      const params = ChannelsTableUtils.buildFetchParams({
        ...defaults,
        sorting: [{ id: 'name', desc: false }],
      });
      expect(params.get('ordering')).toBe('name');
    });

    it('includes ordering with descending sort', () => {
      const params = ChannelsTableUtils.buildFetchParams({
        ...defaults,
        sorting: [{ id: 'name', desc: true }],
      });
      expect(params.get('ordering')).toBe('-name');
    });

    it('maps channel_group sort field to channel_group__name', () => {
      const params = ChannelsTableUtils.buildFetchParams({
        ...defaults,
        sorting: [{ id: 'channel_group', desc: false }],
      });
      expect(params.get('ordering')).toBe('channel_group__name');
    });

    it('maps epg sort field to epg_data__name', () => {
      const params = ChannelsTableUtils.buildFetchParams({
        ...defaults,
        sorting: [{ id: 'epg', desc: false }],
      });
      expect(params.get('ordering')).toBe('epg_data__name');
    });

    it('applies string debounced filters', () => {
      const params = ChannelsTableUtils.buildFetchParams({
        ...defaults,
        debouncedFilters: { name: 'CNN' },
      });
      expect(params.get('name')).toBe('CNN');
    });

    it('applies array debounced filters joined by comma', () => {
      const params = ChannelsTableUtils.buildFetchParams({
        ...defaults,
        debouncedFilters: { channel_group: ['News', 'Sports'] },
      });
      expect(params.get('channel_group')).toBe('News,Sports');
    });

    it('converts null values in array filters to "null" string', () => {
      const params = ChannelsTableUtils.buildFetchParams({
        ...defaults,
        debouncedFilters: { epg: [null, 'SomeEPG'] },
      });
      expect(params.get('epg')).toBe('null,SomeEPG');
    });

    it('skips falsy debounced filter values', () => {
      const params = ChannelsTableUtils.buildFetchParams({
        ...defaults,
        debouncedFilters: { name: '' },
      });
      expect(params.get('name')).toBeNull();
    });
  });

  // ── API wrapper functions ───────────────────────────────────────────────────
  describe('API wrappers', () => {
    beforeEach(() => vi.clearAllMocks());

    it('reorderChannel calls API.reorderChannel', () => {
      ChannelsTableUtils.reorderChannel(1, 2);
      expect(API.reorderChannel).toHaveBeenCalledWith(1, 2);
    });

    it('deleteChannel calls API.deleteChannel', () => {
      ChannelsTableUtils.deleteChannel(5);
      expect(API.deleteChannel).toHaveBeenCalledWith(5, {});
    });

    it('deleteChannel forwards stopStream option', () => {
      ChannelsTableUtils.deleteChannel(5, { stopStream: true });
      expect(API.deleteChannel).toHaveBeenCalledWith(5, { stopStream: true });
    });

    it('deleteChannels calls API.deleteChannels', () => {
      ChannelsTableUtils.deleteChannels([1, 2, 3]);
      expect(API.deleteChannels).toHaveBeenCalledWith([1, 2, 3], {});
    });

    it('deleteChannels forwards stopStream option', () => {
      ChannelsTableUtils.deleteChannels([1, 2], { stopStream: true });
      expect(API.deleteChannels).toHaveBeenCalledWith([1, 2], {
        stopStream: true,
      });
    });

    it('queryChannels calls API.queryChannels', () => {
      const params = new URLSearchParams();
      ChannelsTableUtils.queryChannels(params);
      expect(API.queryChannels).toHaveBeenCalledWith(params);
    });

    it('getAllChannelIds calls API.getAllChannelIds', () => {
      const params = new URLSearchParams();
      ChannelsTableUtils.getAllChannelIds(params);
      expect(API.getAllChannelIds).toHaveBeenCalledWith(params);
    });

    it('updateProfileChannels calls API.updateProfileChannels', () => {
      ChannelsTableUtils.updateProfileChannels([1, 2], '3', true);
      expect(API.updateProfileChannels).toHaveBeenCalledWith([1, 2], '3', true);
    });

    it('updateProfileChannel calls API.updateProfileChannel', () => {
      ChannelsTableUtils.updateProfileChannel(1, '3', false);
      expect(API.updateProfileChannel).toHaveBeenCalledWith(1, '3', false);
    });

    it('addChannelProfile calls API.addChannelProfile', () => {
      const values = { name: 'Test Profile' };
      ChannelsTableUtils.addChannelProfile(values);
      expect(API.addChannelProfile).toHaveBeenCalledWith(values);
    });

    it('deleteChannelProfile calls API.deleteChannelProfile', () => {
      ChannelsTableUtils.deleteChannelProfile(4);
      expect(API.deleteChannelProfile).toHaveBeenCalledWith(4);
    });
  });
});
