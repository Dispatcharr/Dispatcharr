import { describe, it, expect, vi, beforeEach } from 'vitest';
import {
  getEpgSourceValue,
  getEpgSourceData,
  repackGroupChannels,
  formatPreviewSummary,
} from '../AutoSyncAdvancedUtils.js';

vi.mock('../../../api.js', () => ({
  default: {
    repackGroupChannels: vi.fn(),
  },
}));

import API from '../../../api.js';

const makeEpgSource = (overrides = {}) => ({
  id: 1,
  name: 'Source One',
  source_type: 'xmltv',
  ...overrides,
});

const makeResult = (overrides = {}) => ({
  match_count: 3,
  total_in_group: 100,
  total_scanned: 100,
  scan_limit_hit: false,
  ...overrides,
});

describe('AutoSyncAdvancedUtils', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // ── getEpgSourceValue ─────────────────────────────────────────────────────
  describe('getEpgSourceValue', () => {
    it('returns custom_epg_id as string when set', () => {
      expect(getEpgSourceValue({ custom_epg_id: 5 })).toBe('5');
    });

    it('returns custom_epg_id as string when set to 0', () => {
      expect(getEpgSourceValue({ custom_epg_id: 0 })).toBe('0');
    });

    it('returns "0" when force_dummy_epg is true and no custom_epg_id', () => {
      expect(getEpgSourceValue({ force_dummy_epg: true })).toBe('0');
    });

    it('prefers custom_epg_id over force_dummy_epg', () => {
      expect(
        getEpgSourceValue({ custom_epg_id: 7, force_dummy_epg: true })
      ).toBe('7');
    });

    it('returns null when custom_epg_id is null', () => {
      expect(getEpgSourceValue({ custom_epg_id: null })).toBe(null);
    });

    it('returns null when custom_epg_id is undefined and force_dummy_epg is false', () => {
      expect(
        getEpgSourceValue({ custom_epg_id: undefined, force_dummy_epg: false })
      ).toBe(null);
    });

    it('returns null for empty custom_properties object', () => {
      expect(getEpgSourceValue({})).toBe(null);
    });

    it('returns null for null custom_properties', () => {
      expect(getEpgSourceValue(null)).toBe(null);
    });

    it('returns null for undefined custom_properties', () => {
      expect(getEpgSourceValue(undefined)).toBe(null);
    });
  });

  // ── getEpgSourceData ──────────────────────────────────────────────────────
  describe('getEpgSourceData', () => {
    it('always includes "No EPG" as the first option', () => {
      const result = getEpgSourceData([]);
      expect(result[0]).toEqual({ value: '0', label: 'No EPG (Disabled)' });
    });

    it('returns only the No EPG option for an empty source list', () => {
      expect(getEpgSourceData([])).toHaveLength(1);
    });

    it('labels xmltv sources correctly', () => {
      const result = getEpgSourceData([
        makeEpgSource({ source_type: 'xmltv' }),
      ]);
      expect(result[1].label).toBe('Source One (XMLTV)');
    });

    it('labels dummy sources correctly', () => {
      const result = getEpgSourceData([
        makeEpgSource({ source_type: 'dummy' }),
      ]);
      expect(result[1].label).toBe('Source One (Dummy)');
    });

    it('labels schedules_direct sources correctly', () => {
      const result = getEpgSourceData([
        makeEpgSource({ source_type: 'schedules_direct' }),
      ]);
      expect(result[1].label).toBe('Source One (Schedules Direct)');
    });

    it('falls back to raw source_type for unknown types', () => {
      const result = getEpgSourceData([
        makeEpgSource({ source_type: 'custom_type' }),
      ]);
      expect(result[1].label).toBe('Source One (custom_type)');
    });

    it('maps id to string value', () => {
      const result = getEpgSourceData([makeEpgSource({ id: 42 })]);
      expect(result[1].value).toBe('42');
    });

    it('sorts sources alphabetically by name', () => {
      const sources = [
        makeEpgSource({ id: 1, name: 'Zebra' }),
        makeEpgSource({ id: 2, name: 'Alpha' }),
        makeEpgSource({ id: 3, name: 'Mango' }),
      ];
      const result = getEpgSourceData(sources);
      expect(result.map((r) => r.label)).toEqual([
        'No EPG (Disabled)',
        'Alpha (XMLTV)',
        'Mango (XMLTV)',
        'Zebra (XMLTV)',
      ]);
    });

    it('does not mutate the original array', () => {
      const sources = [
        makeEpgSource({ id: 1, name: 'Zebra' }),
        makeEpgSource({ id: 2, name: 'Alpha' }),
      ];
      const original = [...sources];
      getEpgSourceData(sources);
      expect(sources).toEqual(original);
    });
  });

  // ── repackGroupChannels ───────────────────────────────────────────────────
  describe('repackGroupChannels', () => {
    it('calls API.repackGroupChannels with playlist id and channel_group', () => {
      const playlist = { id: 10 };
      const group = { channel_group: 5 };
      vi.mocked(API.repackGroupChannels).mockResolvedValue({ ok: true });

      repackGroupChannels(playlist, group);

      expect(API.repackGroupChannels).toHaveBeenCalledWith(10, 5);
    });

    it('returns the API promise', async () => {
      const playlist = { id: 10 };
      const group = { channel_group: 5 };
      vi.mocked(API.repackGroupChannels).mockResolvedValue({ ok: true });

      await expect(repackGroupChannels(playlist, group)).resolves.toEqual({
        ok: true,
      });
    });
  });

  // ── formatPreviewSummary ──────────────────────────────────────────────────
  describe('formatPreviewSummary', () => {
    it('returns null when result is null', () => {
      expect(formatPreviewSummary('streams', null)).toBeNull();
    });

    it('returns null when result is undefined', () => {
      expect(formatPreviewSummary('streams', undefined)).toBeNull();
    });

    it('formats normal result with plural matches', () => {
      const result = makeResult({ match_count: 3, total_scanned: 50 });
      expect(formatPreviewSummary('streams', result)).toBe(
        '3 streams matches in 50 streams'
      );
    });

    it('formats normal result with singular match', () => {
      const result = makeResult({ match_count: 1, total_scanned: 50 });
      expect(formatPreviewSummary('streams', result)).toBe(
        '1 streams match in 50 streams'
      );
    });

    it('uses singular "stream" when total_scanned is 1', () => {
      const result = makeResult({ match_count: 1, total_scanned: 1 });
      expect(formatPreviewSummary('streams', result)).toBe(
        '1 streams match in 1 stream'
      );
    });

    it('formats scan_limit_hit result with plural matches', () => {
      const result = makeResult({
        match_count: 5,
        total_scanned: 200,
        total_in_group: 1000,
        scan_limit_hit: true,
      });
      expect(formatPreviewSummary('streams', result)).toBe(
        '5 matches in first 200 streams scanned (of 1,000 total)'
      );
    });

    it('formats scan_limit_hit result with singular match', () => {
      const result = makeResult({
        match_count: 1,
        total_scanned: 200,
        total_in_group: 1000,
        scan_limit_hit: true,
      });
      expect(formatPreviewSummary('streams', result)).toBe(
        '1 match in first 200 streams scanned (of 1,000 total)'
      );
    });

    it('uses toLocaleString formatting for large numbers in scan_limit_hit', () => {
      const result = makeResult({
        match_count: 2,
        total_scanned: 5000,
        total_in_group: 10000,
        scan_limit_hit: true,
      });
      expect(formatPreviewSummary('streams', result)).toBe(
        '2 matches in first 5,000 streams scanned (of 10,000 total)'
      );
    });

    it('includes the label in normal result output', () => {
      const result = makeResult({ match_count: 2, total_scanned: 10 });
      expect(formatPreviewSummary('channels', result)).toContain('channels');
    });

    it('does not include the label in scan_limit_hit output', () => {
      const result = makeResult({
        scan_limit_hit: true,
        match_count: 2,
        total_scanned: 10,
        total_in_group: 100,
      });
      expect(formatPreviewSummary('channels', result)).not.toContain(
        'channels'
      );
    });
  });
});
