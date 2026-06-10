import { describe, it, expect, vi, beforeEach } from 'vitest';

// ── Dependency mocks ───────────────────────────────────────────────────────────
vi.mock('../../../api.js', () => ({
  default: {
    previewSeriesRule: vi.fn(),
  },
}));

vi.mock('../RecordingUtils.js', () => ({
  numberedChannelLabel: vi.fn((item) =>
    item.channel_number
      ? `${item.channel_number} - ${item.name || `Channel ${item.id}`}`
      : item.name || `Channel ${item.id}`
  ),
  sortedChannelOptions: vi.fn((channels) =>
    (Array.isArray(channels) ? channels : []).map((c) => ({
      value: String(c.id),
      label: c.name || `Channel ${c.id}`,
    }))
  ),
}));

// ── Imports after mocks ────────────────────────────────────────────────────────
import API from '../../../api.js';
import {
  TITLE_MODES,
  DESCRIPTION_MODES,
  EPISODE_MODES,
  formatRange,
  getTvgOptions,
  getChannelOptions,
  previewSeriesRule,
} from '../SeriesRuleEditorModalUtils.js';
import {
  sortedChannelOptions,
  numberedChannelLabel,
} from '../RecordingUtils.js';

// ─────────────────────────────────────────────────────────────────────────────

describe('SeriesRuleEditorModalUtils', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // ── Constants ──────────────────────────────────────────────────────────────

  describe('TITLE_MODES', () => {
    it('exports an array of mode objects', () => {
      expect(Array.isArray(TITLE_MODES)).toBe(true);
      expect(TITLE_MODES.length).toBeGreaterThan(0);
    });

    it('every entry has a label and value', () => {
      TITLE_MODES.forEach((m) => {
        expect(m).toHaveProperty('label');
        expect(m).toHaveProperty('value');
      });
    });

    it('contains exact, contains, search and regex modes', () => {
      const values = TITLE_MODES.map((m) => m.value);
      expect(values).toContain('exact');
      expect(values).toContain('contains');
      expect(values).toContain('search');
      expect(values).toContain('regex');
    });
  });

  describe('DESCRIPTION_MODES', () => {
    it('exports an array of mode objects', () => {
      expect(Array.isArray(DESCRIPTION_MODES)).toBe(true);
      expect(DESCRIPTION_MODES.length).toBeGreaterThan(0);
    });

    it('every entry has a label and value', () => {
      DESCRIPTION_MODES.forEach((m) => {
        expect(m).toHaveProperty('label');
        expect(m).toHaveProperty('value');
      });
    });

    it('contains contains, search and regex modes', () => {
      const values = DESCRIPTION_MODES.map((m) => m.value);
      expect(values).toContain('contains');
      expect(values).toContain('search');
      expect(values).toContain('regex');
    });

    it('does not contain exact mode', () => {
      const values = DESCRIPTION_MODES.map((m) => m.value);
      expect(values).not.toContain('exact');
    });
  });

  describe('EPISODE_MODES', () => {
    it('exports an array with all and new modes', () => {
      const values = EPISODE_MODES.map((m) => m.value);
      expect(values).toContain('all');
      expect(values).toContain('new');
    });

    it('every entry has a label and value', () => {
      EPISODE_MODES.forEach((m) => {
        expect(m).toHaveProperty('label');
        expect(m).toHaveProperty('value');
      });
    });
  });

  // ── formatRange ────────────────────────────────────────────────────────────

  describe('formatRange', () => {
    it('formats same-day range as "date startTime - endTime"', () => {
      const start = '2024-06-01T10:00:00';
      const end = '2024-06-01T11:30:00';
      const result = formatRange(start, end);
      // Must include a dash separating start and end times (not "->")
      expect(result).toMatch(/-(?!>)/);
      expect(result).not.toMatch(/->/);
    });

    it('formats cross-day range with "->" separator', () => {
      const start = '2024-06-01T23:00:00';
      const end = '2024-06-02T01:00:00';
      const result = formatRange(start, end);
      expect(result).toMatch(/->/);
    });

    it('returns fallback string when dates are invalid', () => {
      const result = formatRange('not-a-date', 'also-not-a-date');
      expect(result).toBe('not-a-date - also-not-a-date');
    });

    it('includes a date string component in the output', () => {
      const start = '2024-06-01T10:00:00';
      const end = '2024-06-01T11:00:00';
      const result = formatRange(start, end);
      // toLocaleDateString produces something non-empty
      expect(result.length).toBeGreaterThan(5);
    });

    it('handles ISO strings with timezone offsets', () => {
      const start = '2024-06-01T10:00:00Z';
      const end = '2024-06-01T11:00:00Z';
      // Should not throw
      expect(() => formatRange(start, end)).not.toThrow();
    });
  });

  // ── getTvgOptions ──────────────────────────────────────────────────────────

  describe('getTvgOptions', () => {
    it('returns empty array for null input', () => {
      expect(getTvgOptions(null)).toEqual([]);
    });

    it('returns empty array for empty array input', () => {
      expect(getTvgOptions([])).toEqual([]);
    });

    it('maps tvgs to { value, label } options', () => {
      const tvgs = [{ tvg_id: 'tvg-1', name: 'Channel One' }];
      const result = getTvgOptions(tvgs);
      expect(result).toHaveLength(1);
      expect(result[0]).toEqual({
        value: 'tvg-1',
        label: 'Channel One (tvg-1)',
      });
    });

    it('uses tvg_id as label when name is missing', () => {
      const tvgs = [{ tvg_id: 'tvg-no-name' }];
      const result = getTvgOptions(tvgs);
      expect(result[0]).toEqual({
        value: 'tvg-no-name',
        label: 'tvg-no-name',
      });
    });

    it('deduplicates by tvg_id', () => {
      const tvgs = [
        { tvg_id: 'tvg-1', name: 'A' },
        { tvg_id: 'tvg-1', name: 'B' },
        { tvg_id: 'tvg-2', name: 'C' },
      ];
      const result = getTvgOptions(tvgs);
      expect(result).toHaveLength(2);
      const values = result.map((o) => o.value);
      expect(values).toContain('tvg-1');
      expect(values).toContain('tvg-2');
    });

    it('skips entries with no tvg_id', () => {
      const tvgs = [
        { tvg_id: null, name: 'No ID' },
        { tvg_id: '', name: 'Empty ID' },
        { tvg_id: 'tvg-1', name: 'Valid' },
      ];
      const result = getTvgOptions(tvgs);
      expect(result).toHaveLength(1);
      expect(result[0].value).toBe('tvg-1');
    });

    it('sorts options alphabetically by label', () => {
      const tvgs = [
        { tvg_id: 'tvg-z', name: 'Zebra' },
        { tvg_id: 'tvg-a', name: 'Apple' },
        { tvg_id: 'tvg-m', name: 'Mango' },
      ];
      const result = getTvgOptions(tvgs);
      const labels = result.map((o) => o.label);
      expect(labels).toEqual([...labels].sort());
    });

    it('sorts by label text including the tvg_id suffix', () => {
      const tvgs = [
        { tvg_id: 'z-id', name: 'Same' },
        { tvg_id: 'a-id', name: 'Same' },
      ];
      const result = getTvgOptions(tvgs);
      // "Same (a-id)" < "Same (z-id)"
      expect(result[0].value).toBe('a-id');
    });
  });

  // ── getChannelOptions ──────────────────────────────────────────────────────

  describe('getChannelOptions', () => {
    const makeChannels = () => [
      { id: 1, name: 'ESPN', channel_number: 5, epg_data_id: 'epg-1' },
      { id: 2, name: 'HBO', channel_number: 10, epg_data_id: 'epg-2' },
      { id: 3, name: 'CNN', channel_number: 20, epg_data_id: 'epg-3' },
    ];

    const makeTvgsById = () => ({
      'epg-1': { tvg_id: 'tvg-espn' },
      'epg-2': { tvg_id: 'tvg-hbo' },
      'epg-3': { tvg_id: 'tvg-cnn' },
    });

    it('calls sortedChannelOptions with allChannels and numberedChannelLabel', () => {
      const channels = makeChannels();
      getChannelOptions(channels, {}, null);
      expect(sortedChannelOptions).toHaveBeenCalledWith(
        channels,
        numberedChannelLabel
      );
    });

    it('returns all channels when tvgId is null', () => {
      const channels = makeChannels();
      const result = getChannelOptions(channels, makeTvgsById(), null);
      expect(result).toHaveLength(3);
    });

    it('returns all channels when tvgId is empty string', () => {
      const channels = makeChannels();
      const result = getChannelOptions(channels, makeTvgsById(), '');
      expect(result).toHaveLength(3);
    });

    it('places matching channels before non-matching when tvgId set', () => {
      // Override sortedChannelOptions to return deterministic output
      vi.mocked(sortedChannelOptions).mockReturnValueOnce([
        { value: '1', label: 'ESPN' },
        { value: '2', label: 'HBO' },
        { value: '3', label: 'CNN' },
      ]);

      const channels = makeChannels();
      const tvgsById = makeTvgsById();

      // tvgId matches ESPN (epg-1 → tvg-espn)
      const result = getChannelOptions(channels, tvgsById, 'tvg-espn');

      expect(result[0].value).toBe('1'); // ESPN first (matching)
      expect(result[1].value).toBe('2'); // HBO second (non-matching)
      expect(result[2].value).toBe('3'); // CNN third  (non-matching)
    });

    it('returns all in sorted order when no channel matches tvgId', () => {
      vi.mocked(sortedChannelOptions).mockReturnValueOnce([
        { value: '1', label: 'ESPN' },
        { value: '2', label: 'HBO' },
      ]);

      const channels = makeChannels();
      const result = getChannelOptions(channels, makeTvgsById(), 'tvg-unknown');

      // No matches → all in others, order preserved from sortedChannelOptions
      expect(result.map((r) => r.value)).toEqual(['1', '2']);
    });

    it('handles channel with no epg_data_id (cTvg is null)', () => {
      const channels = [
        { id: 9, name: 'NoEPG', channel_number: 1, epg_data_id: null },
      ];
      vi.mocked(sortedChannelOptions).mockReturnValueOnce([
        { value: '9', label: 'NoEPG' },
      ]);

      const result = getChannelOptions(channels, {}, 'tvg-1');

      // No epg match → goes to others
      expect(result).toHaveLength(1);
      expect(result[0].value).toBe('9');
    });

    it('handles missing epg_data_id entry in tvgsById', () => {
      const channels = [
        {
          id: 5,
          name: 'Unknown',
          channel_number: 1,
          epg_data_id: 'epg-missing',
        },
      ];
      vi.mocked(sortedChannelOptions).mockReturnValueOnce([
        { value: '5', label: 'Unknown' },
      ]);

      const result = getChannelOptions(channels, {}, 'tvg-1');

      expect(result).toHaveLength(1);
      expect(result[0].value).toBe('5');
    });

    it('handles null tvgsById gracefully', () => {
      const channels = makeChannels();
      vi.mocked(sortedChannelOptions).mockReturnValueOnce([
        { value: '1', label: 'ESPN' },
      ]);

      expect(() => getChannelOptions(channels, null, 'tvg-espn')).not.toThrow();
    });

    it('returns empty array for empty channels', () => {
      vi.mocked(sortedChannelOptions).mockReturnValueOnce([]);
      const result = getChannelOptions([], {}, 'tvg-1');
      expect(result).toEqual([]);
    });

    it('places multiple matching channels before non-matching', () => {
      vi.mocked(sortedChannelOptions).mockReturnValueOnce([
        { value: '1', label: 'ESPN' },
        { value: '2', label: 'ESPN2' },
        { value: '3', label: 'CNN' },
      ]);

      const channels = [
        { id: 1, name: 'ESPN', channel_number: 5, epg_data_id: 'epg-1' },
        { id: 2, name: 'ESPN2', channel_number: 6, epg_data_id: 'epg-4' },
        { id: 3, name: 'CNN', channel_number: 20, epg_data_id: 'epg-3' },
      ];
      const tvgsById = {
        'epg-1': { tvg_id: 'tvg-espn' },
        'epg-4': { tvg_id: 'tvg-espn' }, // both ESPN channels share tvg_id
        'epg-3': { tvg_id: 'tvg-cnn' },
      };

      const result = getChannelOptions(channels, tvgsById, 'tvg-espn');

      expect(result[0].value).toBe('1');
      expect(result[1].value).toBe('2');
      expect(result[2].value).toBe('3');
    });
  });

  // ── previewSeriesRule ──────────────────────────────────────────────────────

  describe('previewSeriesRule', () => {
    it('calls API.previewSeriesRule with the key and abort signal', async () => {
      const mockResult = { matches: [], total: 0 };
      vi.mocked(API.previewSeriesRule).mockResolvedValue(mockResult);

      const controller = new AbortController();
      const key = { title: 'Test Show', mode: 'all' };

      const result = await previewSeriesRule(key, controller);

      expect(API.previewSeriesRule).toHaveBeenCalledWith(key, {
        signal: controller.signal,
      });
      expect(result).toBe(mockResult);
    });

    it('passes the abort signal from the controller', async () => {
      vi.mocked(API.previewSeriesRule).mockResolvedValue({});
      const controller = new AbortController();
      await previewSeriesRule({ title: 'X' }, controller);

      const callArgs = vi.mocked(API.previewSeriesRule).mock.calls[0];
      expect(callArgs[1].signal).toBe(controller.signal);
    });

    it('propagates rejection from API.previewSeriesRule', async () => {
      vi.mocked(API.previewSeriesRule).mockRejectedValue(
        new Error('Network error')
      );
      const controller = new AbortController();
      await expect(previewSeriesRule({}, controller)).rejects.toThrow(
        'Network error'
      );
    });

    it('propagates AbortError when signal is aborted', async () => {
      const abortError = new DOMException('Aborted', 'AbortError');
      vi.mocked(API.previewSeriesRule).mockRejectedValue(abortError);

      const controller = new AbortController();
      controller.abort();

      await expect(previewSeriesRule({}, controller)).rejects.toThrow(
        'Aborted'
      );
    });

    it('passes through all fields of the preview key', async () => {
      vi.mocked(API.previewSeriesRule).mockResolvedValue({});
      const controller = new AbortController();
      const key = {
        title: 'My Show',
        title_mode: 'exact',
        description: 'drama',
        description_mode: 'contains',
        mode: 'new',
        tvg_id: 'tvg-1',
        channel_id: 5,
      };

      await previewSeriesRule(key, controller);

      expect(API.previewSeriesRule).toHaveBeenCalledWith(
        key,
        expect.objectContaining({ signal: controller.signal })
      );
    });
  });
});
