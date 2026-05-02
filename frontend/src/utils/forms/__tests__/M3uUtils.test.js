import { describe, it, expect, vi, beforeEach } from 'vitest';
import {
  updatePlaylist,
  addPlaylist,
  getPlaylist,
  refreshPlaylist,
  prepareSubmitValues,
} from '../M3uUtils.js';

vi.mock('../../../api.js', () => ({
  default: {
    updatePlaylist: vi.fn(),
    addPlaylist: vi.fn(),
    getPlaylist: vi.fn(),
    refreshPlaylist: vi.fn(),
  },
}));

import API from '../../../api.js';

describe('M3uUtils', () => {
  beforeEach(() => vi.clearAllMocks());

// ── updatePlaylist ─────────────────────────────────────────────────────────────

  describe('updatePlaylist', () => {
    it('calls API.updatePlaylist with merged id, values, and file', () => {
      const playlist = { id: 1 };
      const values = { name: 'Test' };
      const file = new File([''], 'test.m3u');
      updatePlaylist(playlist, values, file);
      expect(API.updatePlaylist).toHaveBeenCalledWith({ id: 1, name: 'Test', file });
    });

    it('returns the result of API.updatePlaylist', async () => {
      API.updatePlaylist.mockResolvedValue({ id: 1, name: 'Updated' });
      const result = await updatePlaylist({ id: 1 }, { name: 'Updated' }, null);
      expect(result).toEqual({ id: 1, name: 'Updated' });
    });

    it('passes null file when no file provided', () => {
      updatePlaylist({ id: 2 }, { name: 'No File' }, null);
      expect(API.updatePlaylist).toHaveBeenCalledWith({ id: 2, name: 'No File', file: null });
    });
  });

// ── addPlaylist ────────────────────────────────────────────────────────────────

  describe('addPlaylist', () => {
    it('calls API.addPlaylist with merged values and file', async () => {
      const file = new File([''], 'playlist.m3u');
      await addPlaylist({ name: 'New' }, file);
      expect(API.addPlaylist).toHaveBeenCalledWith({ name: 'New', file });
    });

    it('returns the result of API.addPlaylist', async () => {
      API.addPlaylist.mockResolvedValue({ id: 5, name: 'New' });
      const result = await addPlaylist({ name: 'New' }, null);
      expect(result).toEqual({ id: 5, name: 'New' });
    });

    it('passes null file when no file provided', async () => {
      await addPlaylist({ name: 'No File' }, null);
      expect(API.addPlaylist).toHaveBeenCalledWith({ name: 'No File', file: null });
    });
  });

// ── getPlaylist ────────────────────────────────────────────────────────────────

  describe('getPlaylist', () => {
    it('calls API.getPlaylist with the playlist id', async () => {
      API.getPlaylist.mockResolvedValue({ id: 3 });
      await getPlaylist({ id: 3 });
      expect(API.getPlaylist).toHaveBeenCalledWith(3);
    });

    it('returns the result of API.getPlaylist', async () => {
      API.getPlaylist.mockResolvedValue({ id: 3, name: 'Fetched' });
      const result = await getPlaylist({ id: 3 });
      expect(result).toEqual({ id: 3, name: 'Fetched' });
    });
  });

// ── refreshPlaylist ────────────────────────────────────────────────────────────

  describe('refreshPlaylist', () => {
    it('calls API.refreshPlaylist with the playlist id', async () => {
      API.refreshPlaylist.mockResolvedValue(undefined);
      await refreshPlaylist({ id: 7 });
      expect(API.refreshPlaylist).toHaveBeenCalledWith(7);
    });

    it('returns the result of API.refreshPlaylist', async () => {
      API.refreshPlaylist.mockResolvedValue(undefined);
      const result = await refreshPlaylist({ id: 7 });
      expect(result).toEqual(undefined);
    });
  });

// ── prepareSubmitValues ────────────────────────────────────────────────────────

  describe('prepareSubmitValues', () => {
    describe('exp_date handling', () => {
      it('deletes exp_date when account_type is XC', () => {
        const values = { account_type: 'XC', exp_date: '2025-01-01' };
        const result = prepareSubmitValues(values, null);
        expect(result.exp_date).toBeUndefined();
      });

      it('converts Date to ISO string when expDate is a Date instance', () => {
        const date = new Date('2025-06-15T00:00:00.000Z');
        const values = { account_type: 'M3U', exp_date: null };
        const result = prepareSubmitValues(values, date);
        expect(result.exp_date).toBe(date.toISOString());
      });

      it('sets exp_date to null when expDate is not a Date and not XC', () => {
        const values = { account_type: 'M3U', exp_date: '2025-01-01' };
        const result = prepareSubmitValues(values, null);
        expect(result.exp_date).toBeNull();
      });

      it('sets exp_date to null when expDate is a string', () => {
        const values = { account_type: 'M3U' };
        const result = prepareSubmitValues(values, '2025-01-01');
        expect(result.exp_date).toBeNull();
      });
    });

    describe('cron_expression / refresh_interval handling', () => {
      it('sets refresh_interval to 0 when cron_expression is non-empty', () => {
        const values = {
          account_type: 'M3U',
          cron_expression: '0 * * * *',
          refresh_interval: 30,
        };
        const result = prepareSubmitValues(values, null);
        expect(result.refresh_interval).toBe(0);
        expect(result.cron_expression).toBe('0 * * * *');
      });

      it('sets cron_expression to empty string when it is blank', () => {
        const values = {
          account_type: 'M3U',
          cron_expression: '   ',
          refresh_interval: 30,
        };
        const result = prepareSubmitValues(values, null);
        expect(result.cron_expression).toBe('');
        expect(result.refresh_interval).toBe(30);
      });

      it('sets cron_expression to empty string when it is empty', () => {
        const values = {
          account_type: 'M3U',
          cron_expression: '',
          refresh_interval: 60,
        };
        const result = prepareSubmitValues(values, null);
        expect(result.cron_expression).toBe('');
        expect(result.refresh_interval).toBe(60);
      });

      it('handles undefined cron_expression', () => {
        const values = { account_type: 'M3U', refresh_interval: 30 };
        const result = prepareSubmitValues(values, null);
        expect(result.cron_expression).toBe('');
        expect(result.refresh_interval).toBe(30);
      });
    });

    describe('password handling for XC', () => {
      it('deletes password when account_type is XC and password is empty string', () => {
        const values = { account_type: 'XC', password: '' };
        const result = prepareSubmitValues(values, null);
        expect(result.password).toBeUndefined();
      });

      it('keeps password when account_type is XC and password is non-empty', () => {
        const values = { account_type: 'XC', password: 'secret' };
        const result = prepareSubmitValues(values, null);
        expect(result.password).toBe('secret');
      });

      it('keeps password when account_type is not XC and password is empty', () => {
        const values = { account_type: 'M3U', password: '' };
        const result = prepareSubmitValues(values, null);
        expect(result.password).toBe('');
      });
    });

    describe('user_agent handling', () => {
      it('sets user_agent to null when value is "0"', () => {
        const values = { account_type: 'M3U', user_agent: '0' };
        const result = prepareSubmitValues(values, null);
        expect(result.user_agent).toBeNull();
      });

      it('keeps user_agent when it is not "0"', () => {
        const values = { account_type: 'M3U', user_agent: 'Mozilla/5.0' };
        const result = prepareSubmitValues(values, null);
        expect(result.user_agent).toBe('Mozilla/5.0');
      });

      it('keeps user_agent when it is undefined', () => {
        const values = { account_type: 'M3U' };
        const result = prepareSubmitValues(values, null);
        expect(result.user_agent).toBeUndefined();
      });
    });

    describe('does not mutate original values', () => {
      it('returns a new object and does not mutate the input', () => {
        const values = {
          account_type: 'M3U',
          cron_expression: '',
          refresh_interval: 30,
          user_agent: '0',
        };
        const original = { ...values };
        prepareSubmitValues(values, null);
        expect(values).toEqual(original);
      });
    });
  });
});
