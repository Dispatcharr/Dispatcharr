import { describe, it, expect } from 'vitest';
import * as VODCardUtils from '../VODCardUtils';

describe('VODCardUtils', () => {
  describe('formatDuration', () => {
    it('should format duration with hours and minutes', () => {
      const result = VODCardUtils.formatDuration(3661); // 1h 1m 1s
      expect(result).toBe('1h 1m');
    });

    it('should format duration with minutes and seconds when less than an hour', () => {
      const result = VODCardUtils.formatDuration(125); // 2m 5s
      expect(result).toBe('2m 5s');
    });

    it('should format duration with only minutes when seconds are zero', () => {
      const result = VODCardUtils.formatDuration(120); // 2m 0s
      expect(result).toBe('2m 0s');
    });

    it('should format duration with only seconds when less than a minute', () => {
      const result = VODCardUtils.formatDuration(45);
      expect(result).toBe('0m 45s');
    });

    it('should handle multiple hours correctly', () => {
      const result = VODCardUtils.formatDuration(7325); // 2h 2m 5s
      expect(result).toBe('2h 2m');
    });

    it('should return empty string for zero seconds', () => {
      const result = VODCardUtils.formatDuration(0);
      expect(result).toBe('');
    });

    it('should return empty string for null', () => {
      const result = VODCardUtils.formatDuration(null);
      expect(result).toBe('');
    });

    it('should return empty string for undefined', () => {
      const result = VODCardUtils.formatDuration(undefined);
      expect(result).toBe('');
    });
  });

  describe('getSeasonLabel', () => {
    it('should format season and episode numbers with padding', () => {
      const vod = { season_number: 1, episode_number: 5 };
      const result = VODCardUtils.getSeasonLabel(vod);
      expect(result).toBe('S01E05');
    });

    it('should format double-digit season and episode numbers', () => {
      const vod = { season_number: 12, episode_number: 23 };
      const result = VODCardUtils.getSeasonLabel(vod);
      expect(result).toBe('S12E23');
    });

    it('should return empty string when season_number is missing', () => {
      const vod = { episode_number: 5 };
      const result = VODCardUtils.getSeasonLabel(vod);
      expect(result).toBe('');
    });

    it('should return empty string when episode_number is missing', () => {
      const vod = { season_number: 1 };
      const result = VODCardUtils.getSeasonLabel(vod);
      expect(result).toBe('');
    });

    it('should return empty string when both are missing', () => {
      const vod = {};
      const result = VODCardUtils.getSeasonLabel(vod);
      expect(result).toBe('');
    });

    it('should handle season_number of zero', () => {
      const vod = { season_number: 0, episode_number: 1 };
      const result = VODCardUtils.getSeasonLabel(vod);
      expect(result).toBe('');
    });

    it('should handle episode_number of zero', () => {
      const vod = { season_number: 1, episode_number: 0 };
      const result = VODCardUtils.getSeasonLabel(vod);
      expect(result).toBe('');
    });
  });
});
