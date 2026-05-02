import { describe, it, expect, vi } from 'vitest';
import {
  getEPGs,
  getSelectedAdvancedOptions,
  applyAdvancedOptionsChange,
  getEpgSourceValue,
  getEpgSourceData,
} from '../LiveGroupFilterUtils.js';

// ── API mock ─────────────────────────────────────────────────────────────────
vi.mock('../../../api.js', () => ({
  default: { getEPGs: vi.fn() },
}));

import API from '../../../api.js';

// ── Helpers ──────────────────────────────────────────────────────────────────
const makeEpgSource = (overrides = {}) => ({
  id: 1,
  name: 'Source One',
  source_type: 'xmltv',
  ...overrides,
});

describe('LiveGroupFilterUtils', () => {
  // ── getEPGs ────────────────────────────────────────────────────────────────

  describe('getEPGs', () => {
    it('delegates to API.getEPGs', () => {
      const result = [makeEpgSource()];
      vi.mocked(API.getEPGs).mockResolvedValue(result);
      expect(getEPGs()).resolves.toEqual(result);
      expect(API.getEPGs).toHaveBeenCalledOnce();
    });
  });

// ── getSelectedAdvancedOptions ───────────────────────────────────────────────

  describe('getSelectedAdvancedOptions', () => {
    it('returns empty array when custom_properties is empty', () => {
      expect(getSelectedAdvancedOptions({})).toEqual([]);
    });

    it('returns empty array when custom_properties is nullish', () => {
      expect(getSelectedAdvancedOptions(null)).toEqual([]);
      expect(getSelectedAdvancedOptions(undefined)).toEqual([]);
    });

    it('detects force_epg via custom_epg_id', () => {
      expect(getSelectedAdvancedOptions({ custom_epg_id: 5 })).toContain('force_epg');
    });

    it('detects force_epg via force_dummy_epg', () => {
      expect(getSelectedAdvancedOptions({ force_dummy_epg: true })).toContain('force_epg');
    });

    it('detects force_epg via force_epg_selected', () => {
      expect(getSelectedAdvancedOptions({ force_epg_selected: true })).toContain('force_epg');
    });

    it('detects group_override', () => {
      expect(getSelectedAdvancedOptions({ group_override: null })).toContain('group_override');
    });

    it('detects name_regex via name_regex_pattern', () => {
      expect(getSelectedAdvancedOptions({ name_regex_pattern: '' })).toContain('name_regex');
    });

    it('detects name_regex via name_replace_pattern', () => {
      expect(getSelectedAdvancedOptions({ name_replace_pattern: '' })).toContain('name_regex');
    });

    it('detects name_match_regex', () => {
      expect(getSelectedAdvancedOptions({ name_match_regex: '' })).toContain('name_match_regex');
    });

    it('detects profile_assignment via channel_profile_ids', () => {
      expect(getSelectedAdvancedOptions({ channel_profile_ids: [] })).toContain('profile_assignment');
    });

    it('detects channel_sort_order', () => {
      expect(getSelectedAdvancedOptions({ channel_sort_order: 'name' })).toContain('channel_sort_order');
    });

    it('detects stream_profile_assignment', () => {
      expect(getSelectedAdvancedOptions({ stream_profile_id: null })).toContain('stream_profile_assignment');
    });

    it('detects custom_logo', () => {
      expect(getSelectedAdvancedOptions({ custom_logo_id: null })).toContain('custom_logo');
    });

    it('returns multiple active options', () => {
      const result = getSelectedAdvancedOptions({
        name_match_regex: '',
        channel_sort_order: 'name',
      });
      expect(result).toContain('name_match_regex');
      expect(result).toContain('channel_sort_order');
      expect(result).toHaveLength(2);
    });
  });

// ── applyAdvancedOptionsChange ───────────────────────────────────────────────

  describe('applyAdvancedOptionsChange', () => {
    describe('adding options', () => {
      it('adds force_epg defaults when newly selected', () => {
        const result = applyAdvancedOptionsChange({}, ['force_epg']);
        expect(result).toMatchObject({ force_dummy_epg: true });
      });

      it('adds name_regex defaults when newly selected', () => {
        const result = applyAdvancedOptionsChange({}, ['name_regex']);
        expect(result).toMatchObject({ name_regex_pattern: '', name_replace_pattern: '' });
      });

      it('adds channel_sort_order defaults including channel_sort_reverse', () => {
        const result = applyAdvancedOptionsChange({}, ['channel_sort_order']);
        expect(result).toMatchObject({ channel_sort_order: '', channel_sort_reverse: false });
      });

      it('adds profile_assignment defaults', () => {
        const result = applyAdvancedOptionsChange({}, ['profile_assignment']);
        expect(result).toMatchObject({ channel_profile_ids: [] });
      });

      it('adds custom_logo defaults', () => {
        const result = applyAdvancedOptionsChange({}, ['custom_logo']);
        expect(result).toMatchObject({ custom_logo_id: null });
      });

      it('does not overwrite existing keys when option is already active', () => {
        const prev = { name_match_regex: 'existing' };
        const result = applyAdvancedOptionsChange(prev, ['name_match_regex']);
        expect(result.name_match_regex).toBe('existing');
      });

      it('adds defaults for multiple options at once', () => {
        const result = applyAdvancedOptionsChange({}, ['name_match_regex', 'custom_logo']);
        expect(result).toMatchObject({ name_match_regex: '', custom_logo_id: null });
      });
    });

    describe('removing options', () => {
      it('removes force_epg keys when deselected', () => {
        const prev = { force_dummy_epg: true, custom_epg_id: 3, force_epg_selected: true };
        const result = applyAdvancedOptionsChange(prev, []);
        expect(result).not.toHaveProperty('force_dummy_epg');
        expect(result).not.toHaveProperty('custom_epg_id');
        expect(result).not.toHaveProperty('force_epg_selected');
      });

      it('removes name_regex keys when deselected', () => {
        const prev = { name_regex_pattern: 'foo', name_replace_pattern: 'bar' };
        const result = applyAdvancedOptionsChange(prev, []);
        expect(result).not.toHaveProperty('name_regex_pattern');
        expect(result).not.toHaveProperty('name_replace_pattern');
      });

      it('removes channel_sort_order and channel_sort_reverse when deselected', () => {
        const prev = { channel_sort_order: 'name', channel_sort_reverse: true };
        const result = applyAdvancedOptionsChange(prev, []);
        expect(result).not.toHaveProperty('channel_sort_order');
        expect(result).not.toHaveProperty('channel_sort_reverse');
      });

      it('removes custom_logo_id when deselected', () => {
        const prev = { custom_logo_id: 42 };
        const result = applyAdvancedOptionsChange(prev, []);
        expect(result).not.toHaveProperty('custom_logo_id');
      });

      it('does not remove keys for options that are still selected', () => {
        const prev = { name_match_regex: 'foo', custom_logo_id: 1 };
        const result = applyAdvancedOptionsChange(prev, ['name_match_regex']);
        expect(result).toHaveProperty('name_match_regex', 'foo');
        expect(result).not.toHaveProperty('custom_logo_id');
      });
    });

    it('does not mutate the original object', () => {
      const prev = { name_match_regex: 'foo' };
      applyAdvancedOptionsChange(prev, []);
      expect(prev).toHaveProperty('name_match_regex', 'foo');
    });
  });

// ── getEpgSourceValue ────────────────────────────────────────────────────────

  describe('getEpgSourceValue', () => {
    it('returns custom_epg_id as string when set', () => {
      const group = { custom_properties: { custom_epg_id: 7 } };
      expect(getEpgSourceValue(group)).toBe('7');
    });

    it('returns "0" when force_dummy_epg is true and no custom_epg_id', () => {
      const group = { custom_properties: { force_dummy_epg: true } };
      expect(getEpgSourceValue(group)).toBe('0');
    });

    it('returns null when neither custom_epg_id nor force_dummy_epg is set', () => {
      const group = { custom_properties: {} };
      expect(getEpgSourceValue(group)).toBeNull();
    });

    it('prefers custom_epg_id over force_dummy_epg', () => {
      const group = { custom_properties: { custom_epg_id: 3, force_dummy_epg: true } };
      expect(getEpgSourceValue(group)).toBe('3');
    });

    it('returns null when custom_epg_id is explicitly null', () => {
      const group = { custom_properties: { custom_epg_id: null } };
      expect(getEpgSourceValue(group)).toBeNull();
    });
  });

// ── getEpgSourceData ─────────────────────────────────────────────────────────

  describe('getEpgSourceData', () => {
    it('always includes "No EPG (Disabled)" as the first entry', () => {
      const result = getEpgSourceData([]);
      expect(result[0]).toEqual({ value: '0', label: 'No EPG (Disabled)' });
    });

    it('maps an xmltv source correctly', () => {
      const result = getEpgSourceData([makeEpgSource({ id: 1, name: 'My XMLTV', source_type: 'xmltv' })]);
      expect(result).toContainEqual({ value: '1', label: 'My XMLTV (XMLTV)' });
    });

    it('maps a dummy source correctly', () => {
      const result = getEpgSourceData([makeEpgSource({ id: 2, name: 'Dummy', source_type: 'dummy' })]);
      expect(result).toContainEqual({ value: '2', label: 'Dummy (Dummy)' });
    });

    it('maps a schedules_direct source correctly', () => {
      const result = getEpgSourceData([
        makeEpgSource({ id: 3, name: 'SD', source_type: 'schedules_direct' }),
      ]);
      expect(result).toContainEqual({ value: '3', label: 'SD (Schedules Direct)' });
    });

    it('falls back to raw source_type for unknown types', () => {
      const result = getEpgSourceData([makeEpgSource({ id: 4, name: 'Other', source_type: 'iptv' })]);
      expect(result).toContainEqual({ value: '4', label: 'Other (iptv)' });
    });

    it('sorts sources alphabetically by name', () => {
      const sources = [
        makeEpgSource({ id: 1, name: 'Zebra' }),
        makeEpgSource({ id: 2, name: 'Apple' }),
        makeEpgSource({ id: 3, name: 'Mango' }),
      ];
      const result = getEpgSourceData(sources);
      const labels = result.slice(1).map((r) => r.label.split(' (')[0]);
      expect(labels).toEqual(['Apple', 'Mango', 'Zebra']);
    });

    it('does not mutate the original sources array', () => {
      const sources = [
        makeEpgSource({ id: 1, name: 'Zebra' }),
        makeEpgSource({ id: 2, name: 'Apple' }),
      ];
      const original = [...sources];
      getEpgSourceData(sources);
      expect(sources).toEqual(original);
    });

    it('returns only the "No EPG" entry when sources array is empty', () => {
      expect(getEpgSourceData([])).toHaveLength(1);
    });
  });
});
