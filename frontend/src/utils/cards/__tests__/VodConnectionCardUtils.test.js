import { describe, it, expect, vi, beforeEach } from 'vitest';
import * as VodConnectionCardUtils from '../VodConnectionCardUtils';
import * as dateTimeUtils from '../../dateTimeUtils.js';

vi.mock('../../dateTimeUtils.js', () => ({
  getNowMs: vi.fn(),
  format: vi.fn(),
  toFriendlyDuration: vi.fn(),
}));

describe('VodConnectionCardUtils', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('getMovieDisplayTitle', () => {
    it('should return content_name from vodContent', () => {
      const vodContent = { content_name: 'The Matrix' };
      const result = VodConnectionCardUtils.getMovieDisplayTitle(vodContent);
      expect(result).toBe('The Matrix');
    });
  });

  describe('getEpisodeDisplayTitle', () => {
    it('should format title with season and episode numbers', () => {
      const metadata = {
        series_name: 'Breaking Bad',
        season_number: 1,
        episode_number: 5,
      };
      const result = VodConnectionCardUtils.getEpisodeDisplayTitle(metadata);
      expect(result).toBe('Breaking Bad - S01E05');
    });

    it('should pad single-digit season and episode numbers', () => {
      const metadata = {
        series_name: 'The Office',
        season_number: 3,
        episode_number: 9,
      };
      const result = VodConnectionCardUtils.getEpisodeDisplayTitle(metadata);
      expect(result).toBe('The Office - S03E09');
    });

    it('should use S?? when season_number is missing', () => {
      const metadata = {
        series_name: 'Lost',
        episode_number: 5,
      };
      const result = VodConnectionCardUtils.getEpisodeDisplayTitle(metadata);
      expect(result).toBe('Lost - S??E05');
    });

    it('should use E?? when episode_number is missing', () => {
      const metadata = {
        series_name: 'Friends',
        season_number: 2,
      };
      const result = VodConnectionCardUtils.getEpisodeDisplayTitle(metadata);
      expect(result).toBe('Friends - S02E??');
    });
  });

  describe('getMovieSubtitle', () => {
    it('should return array with genre when present', () => {
      const metadata = { genre: 'Action' };
      const result = VodConnectionCardUtils.getMovieSubtitle(metadata);
      expect(result).toEqual(['Action']);
    });

    it('should return empty array when genre is missing', () => {
      const metadata = {};
      const result = VodConnectionCardUtils.getMovieSubtitle(metadata);
      expect(result).toEqual([]);
    });
  });

  describe('getEpisodeSubtitle', () => {
    it('should return array with episode_name when present', () => {
      const metadata = { episode_name: 'Pilot' };
      const result = VodConnectionCardUtils.getEpisodeSubtitle(metadata);
      expect(result).toEqual(['Pilot']);
    });

    it('should return array with Episode when episode_name is missing', () => {
      const metadata = {};
      const result = VodConnectionCardUtils.getEpisodeSubtitle(metadata);
      expect(result).toEqual(['Episode']);
    });
  });

  describe('calculateProgress', () => {
    beforeEach(() => {
      dateTimeUtils.getNowMs.mockReturnValue(1000000); // 1000 seconds
    });

    it('should calculate progress from last_seek_percentage', () => {
      const connection = {
        last_seek_percentage: 50,
        last_seek_timestamp: 990, // 10 seconds ago
      };
      const result = VodConnectionCardUtils.calculateProgress(connection, 200);

      expect(result.currentTime).toBe(110); // 50% of 200 = 100, plus 10 elapsed
      expect(result.percentage).toBeCloseTo(55);
      expect(result.totalTime).toBe(200);
    });

    it('should cap currentTime at duration when seeking', () => {
      const connection = {
        last_seek_percentage: 95,
        last_seek_timestamp: 900, // 100 seconds ago
      };
      const result = VodConnectionCardUtils.calculateProgress(connection, 200);

      expect(result.currentTime).toBe(200); // Capped at duration
      expect(result.percentage).toBe(100);
    });

    it('should fallback to position_seconds when seek data unavailable', () => {
      const connection = {
        position_seconds: 75,
      };
      const result = VodConnectionCardUtils.calculateProgress(connection, 200);

      expect(result.currentTime).toBe(75);
      expect(result.percentage).toBe(37.5);
      expect(result.totalTime).toBe(200);
    });

    it('should return zero progress when no connection data', () => {
      const result = VodConnectionCardUtils.calculateProgress(null, 200);

      expect(result.currentTime).toBe(0);
      expect(result.percentage).toBe(0);
      expect(result.totalTime).toBe(200);
    });

    it('should return zero progress when duration is missing', () => {
      const connection = { position_seconds: 50 };
      const result = VodConnectionCardUtils.calculateProgress(connection, null);

      expect(result.currentTime).toBe(0);
      expect(result.percentage).toBe(0);
      expect(result.totalTime).toBe(0);
    });

    it('should ensure currentTime is not negative', () => {
      const connection = {
        last_seek_percentage: 10,
        last_seek_timestamp: 2000, // In the future somehow
      };
      const result = VodConnectionCardUtils.calculateProgress(connection, 200);

      expect(result.currentTime).toBeGreaterThanOrEqual(0);
    });
  });

  describe('calculateConnectionDuration', () => {
    it('should use duration from connection when available', () => {
      dateTimeUtils.toFriendlyDuration.mockReturnValue('1h 30m');
      const connection = { duration: 5400 };

      const result =
        VodConnectionCardUtils.calculateConnectionDuration(connection);

      expect(dateTimeUtils.toFriendlyDuration).toHaveBeenCalledWith(
        5400,
        'seconds'
      );
      expect(result).toBe('1h 30m');
    });

    it('should calculate duration from client_id timestamp when duration missing', () => {
      dateTimeUtils.getNowMs.mockReturnValue(1000000);
      dateTimeUtils.toFriendlyDuration.mockReturnValue('45m');

      const connection = { client_id: 'vod_900000_abc' };
      const result =
        VodConnectionCardUtils.calculateConnectionDuration(connection);

      expect(dateTimeUtils.toFriendlyDuration).toHaveBeenCalledWith(
        100,
        'seconds'
      );
      expect(result).toBe('45m');
    });

    it('should return Unknown duration when no data available', () => {
      const connection = {};
      const result =
        VodConnectionCardUtils.calculateConnectionDuration(connection);

      expect(result).toBe('Unknown duration');
    });

    it('should return Unknown duration when client_id is invalid format', () => {
      const connection = { client_id: 'invalid_format' };
      const result =
        VodConnectionCardUtils.calculateConnectionDuration(connection);

      expect(result).toBe('Unknown duration');
    });

    it('should handle parsing errors gracefully', () => {
      dateTimeUtils.getNowMs.mockReturnValue(1000000);
      dateTimeUtils.toFriendlyDuration.mockReturnValue('45m');

      const connection = { client_id: 'vod_invalid_abc' };
      const result =
        VodConnectionCardUtils.calculateConnectionDuration(connection);

      // If parseInt fails, the code should still handle it
      expect(result).toBe('45m'); // or 'Unknown duration' depending on implementation
    });
  });

  describe('calculateConnectionStartTime', () => {
    it('should format connected_at timestamp when available', () => {
      dateTimeUtils.format.mockReturnValue('01/15/2024 14:30:00');

      const connection = { connected_at: 1705329000 };
      const result = VodConnectionCardUtils.calculateConnectionStartTime(
        connection,
        'MM/DD/YYYY, HH:mm:ss'
      );

      expect(dateTimeUtils.format).toHaveBeenCalledWith(
        1705329000000,
        'MM/DD/YYYY, HH:mm:ss'
      );
      expect(result).toBe('01/15/2024 14:30:00');
    });

    it('should calculate start time from client_id when connected_at missing', () => {
      dateTimeUtils.format.mockReturnValue('01/15/2024 13:00:00');

      const connection = { client_id: 'vod_1705323600000_abc' };
      const result = VodConnectionCardUtils.calculateConnectionStartTime(
        connection,
        'MM/DD/YYYY, HH:mm:ss'
      );

      expect(dateTimeUtils.format).toHaveBeenCalledWith(
        1705323600000,
        'MM/DD/YYYY, HH:mm:ss'
      );
      expect(result).toBe('01/15/2024 13:00:00');
    });

    it('should return Unknown when no timestamp data available', () => {
      const connection = {};
      const result = VodConnectionCardUtils.calculateConnectionStartTime(
        connection,
        'MM/DD/YYYY, HH:mm:ss'
      );

      expect(result).toBe('Unknown');
    });

    it('should return Unknown when client_id is invalid format', () => {
      const connection = { client_id: 'invalid_format' };
      const result = VodConnectionCardUtils.calculateConnectionStartTime(
        connection,
        'MM/DD/YYYY'
      );

      expect(result).toBe('Unknown');
    });

    it('should handle parsing errors gracefully', () => {
      dateTimeUtils.format.mockReturnValue('01/15/2024 13:00:00');

      const connection = { client_id: 'vod_notanumber_abc' };
      const result = VodConnectionCardUtils.calculateConnectionStartTime(
        connection,
        'MM/DD/YYYY'
      );

      // If parseInt succeeds on any number, format will be called
      expect(result).toBe('01/15/2024 13:00:00'); // or 'Unknown' depending on implementation
    });
  });
});
