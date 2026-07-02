import { describe, it, expect, vi, beforeEach } from 'vitest';
import * as EPGsTableUtils from '../EPGsTableUtils';

// ── Dependency mocks ────────────────────────────────────────────────────────
vi.mock('../../../api.js', () => ({
  default: {
    updateEPG: vi.fn(),
    deleteEPG: vi.fn(),
    refreshEPG: vi.fn(),
  },
}));

import API from '../../../api.js';

describe('EPGsTableUtils', () => {
  beforeEach(() => vi.clearAllMocks());

  // ── formatStatusText ────────────────────────────────────────────────────────
  describe('formatStatusText', () => {
    it('returns "Unknown" for null', () => {
      expect(EPGsTableUtils.formatStatusText(null)).toBe('Unknown');
    });

    it('returns "Unknown" for undefined', () => {
      expect(EPGsTableUtils.formatStatusText(undefined)).toBe('Unknown');
    });

    it('returns "Unknown" for empty string', () => {
      expect(EPGsTableUtils.formatStatusText('')).toBe('Unknown');
    });

    it('capitalizes first letter and lowercases the rest', () => {
      expect(EPGsTableUtils.formatStatusText('idle')).toBe('Idle');
      expect(EPGsTableUtils.formatStatusText('success')).toBe('Success');
      expect(EPGsTableUtils.formatStatusText('error')).toBe('Error');
    });

    it('handles already-uppercase input', () => {
      expect(EPGsTableUtils.formatStatusText('FETCHING')).toBe('Fetching');
    });

    it('handles mixed case input', () => {
      expect(EPGsTableUtils.formatStatusText('pArSiNg')).toBe('Parsing');
    });
  });

  // ── updateEpg ───────────────────────────────────────────────────────────────
  describe('updateEpg', () => {
    it('calls API.updateEPG with merged values and id', async () => {
      API.updateEPG.mockResolvedValue({ id: 1 });
      const epg = { id: 1, name: 'Old Name' };
      await EPGsTableUtils.updateEpg({ is_active: false }, epg, false);
      expect(API.updateEPG).toHaveBeenCalledWith(
        { is_active: false, id: 1 },
        false
      );
    });

    it('passes isToggle=true to API.updateEPG', async () => {
      API.updateEPG.mockResolvedValue({ id: 2 });
      const epg = { id: 2 };
      await EPGsTableUtils.updateEpg({ is_active: true }, epg, true);
      expect(API.updateEPG).toHaveBeenCalledWith(
        { is_active: true, id: 2 },
        true
      );
    });

    it('returns the API response', async () => {
      const mockResponse = { id: 3, name: 'Updated' };
      API.updateEPG.mockResolvedValue(mockResponse);
      const result = await EPGsTableUtils.updateEpg({}, { id: 3 }, false);
      expect(result).toBe(mockResponse);
    });

    it('propagates API errors', async () => {
      API.updateEPG.mockRejectedValue(new Error('Network error'));
      await expect(
        EPGsTableUtils.updateEpg({}, { id: 1 }, false)
      ).rejects.toThrow('Network error');
    });
  });

  // ── deleteEpg ───────────────────────────────────────────────────────────────
  describe('deleteEpg', () => {
    it('calls API.deleteEPG with the correct id', () => {
      const mockReturn = Promise.resolve(undefined);
      API.deleteEPG.mockReturnValue(mockReturn);
      const result = EPGsTableUtils.deleteEpg(5);
      expect(API.deleteEPG).toHaveBeenCalledWith(5);
      expect(result).toBe(mockReturn);
    });
  });

  // ── refreshEpg ──────────────────────────────────────────────────────────────
  describe('refreshEpg', () => {
    it('calls API.refreshEPG with the correct id', () => {
      const mockReturn = Promise.resolve(undefined);
      API.refreshEPG.mockReturnValue(mockReturn);
      const result = EPGsTableUtils.refreshEpg(7);
      expect(API.refreshEPG).toHaveBeenCalledWith(7, expect.anything());
      expect(result).toBe(mockReturn);
    });
  });

  // ── getProgressLabel ────────────────────────────────────────────────────────
  describe('getProgressLabel', () => {
    it('returns "Downloading" for downloading action', () => {
      expect(EPGsTableUtils.getProgressLabel('downloading')).toBe(
        'Downloading'
      );
    });

    it('returns "Extracting" for extracting action', () => {
      expect(EPGsTableUtils.getProgressLabel('extracting')).toBe('Extracting');
    });

    it('returns "Parsing Channels" for parsing_channels action', () => {
      expect(EPGsTableUtils.getProgressLabel('parsing_channels')).toBe(
        'Parsing Channels'
      );
    });

    it('returns "Parsing Programs" for parsing_programs action', () => {
      expect(EPGsTableUtils.getProgressLabel('parsing_programs')).toBe(
        'Parsing Programs'
      );
    });

    it('returns null for unknown action', () => {
      expect(EPGsTableUtils.getProgressLabel('unknown_action')).toBeNull();
    });

    it('returns null for null action', () => {
      expect(EPGsTableUtils.getProgressLabel(null)).toBeNull();
    });

    it('returns null for undefined action', () => {
      expect(EPGsTableUtils.getProgressLabel(undefined)).toBeNull();
    });
  });

  // ── getProgressInfo ─────────────────────────────────────────────────────────
  describe('getProgressInfo', () => {
    it('returns message when progress.message is set', () => {
      expect(
        EPGsTableUtils.getProgressInfo({ message: 'Loading data...' })
      ).toBe('Loading data...');
    });

    it('returns programs/channels string when processed and channels are set', () => {
      expect(
        EPGsTableUtils.getProgressInfo({ processed: 1500, channels: 42 })
      ).toBe('1,500 programs for 42 channels');
    });

    it('prefers message over processed/channels', () => {
      expect(
        EPGsTableUtils.getProgressInfo({
          message: 'Custom message',
          processed: 100,
          channels: 5,
        })
      ).toBe('Custom message');
    });

    it('returns processed/total string when processed and total are set without channels', () => {
      expect(
        EPGsTableUtils.getProgressInfo({ processed: 250, total: 1000 })
      ).toBe('250 / 1,000');
    });

    it('returns null when no relevant fields are present', () => {
      expect(EPGsTableUtils.getProgressInfo({})).toBeNull();
    });

    it('returns null when only processed is set without channels or total', () => {
      expect(EPGsTableUtils.getProgressInfo({ processed: 100 })).toBeNull();
    });

    it('formats large numbers with locale separators', () => {
      const result = EPGsTableUtils.getProgressInfo({
        processed: 1000000,
        total: 5000000,
      });
      expect(result).toBe('1,000,000 / 5,000,000');
    });
  });

  // ── getSortedEpgs ───────────────────────────────────────────────────────────
  describe('getSortedEpgs', () => {
    const epgs = [
      { id: 1, name: 'Zebra EPG', is_active: true },
      { id: 2, name: 'Alpha EPG', is_active: false },
      { id: 3, name: 'Middle EPG', is_active: true },
    ];

    it('sorts ascending when compareDesc is false', () => {
      const result = EPGsTableUtils.getSortedEpgs(
        [...epgs],
        'is_active',
        false
      );
      // active=false comes first in ascending (false < true)
      expect(result[0].id).toBe(2);
    });

    it('sorts descending when compareDesc is true', () => {
      const result = EPGsTableUtils.getSortedEpgs([...epgs], 'is_active', true);
      // active=true comes first in descending
      expect(result[0].is_active).toBe(true);
    });

    it('returns items in original relative order when values are equal', () => {
      const items = [
        { id: 1, name: 'Same', is_active: true },
        { id: 2, name: 'Same', is_active: true },
      ];
      const result = EPGsTableUtils.getSortedEpgs([...items], 'name', false);
      expect(result[0].id).toBe(1);
      expect(result[1].id).toBe(2);
    });

    it('sorts by name field ascending', () => {
      const result = EPGsTableUtils.getSortedEpgs([...epgs], 'name', false);
      expect(result[0].name).toBe('Alpha EPG');
    });

    it('sorts by name field descending', () => {
      const result = EPGsTableUtils.getSortedEpgs([...epgs], 'name', true);
      expect(result[0].name).toBe('Zebra EPG');
    });

    it('returns an empty array for empty input', () => {
      expect(EPGsTableUtils.getSortedEpgs([], 'name', false)).toEqual([]);
    });
  });
});
