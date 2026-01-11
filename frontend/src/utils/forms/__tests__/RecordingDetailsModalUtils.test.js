import { describe, it, expect, vi, beforeEach } from 'vitest';
import * as RecordingDetailsModalUtils from '../RecordingDetailsModalUtils';
import dayjs from 'dayjs';

describe('RecordingDetailsModalUtils', () => {
  describe('getStatRows', () => {
    it('should return all stats when all values are present', () => {
      const stats = {
        video_codec: 'H.264',
        resolution: '1920x1080',
        width: 1920,
        height: 1080,
        source_fps: 30,
        video_bitrate: 5000,
        audio_codec: 'AAC',
        audio_channels: 2,
        sample_rate: 48000,
        audio_bitrate: 128
      };

      const result = RecordingDetailsModalUtils.getStatRows(stats);

      expect(result).toEqual([
        ['Video Codec', 'H.264'],
        ['Resolution', '1920x1080'],
        ['FPS', 30],
        ['Video Bitrate', '5000 kb/s'],
        ['Audio Codec', 'AAC'],
        ['Audio Channels', 2],
        ['Sample Rate', '48000 Hz'],
        ['Audio Bitrate', '128 kb/s']
      ]);
    });

    it('should use width x height when resolution is not present', () => {
      const stats = {
        width: 1280,
        height: 720
      };

      const result = RecordingDetailsModalUtils.getStatRows(stats);

      expect(result).toEqual([
        ['Resolution', '1280x720']
      ]);
    });

    it('should prefer resolution over width/height', () => {
      const stats = {
        resolution: '1920x1080',
        width: 1280,
        height: 720
      };

      const result = RecordingDetailsModalUtils.getStatRows(stats);

      expect(result).toEqual([
        ['Resolution', '1920x1080']
      ]);
    });

    it('should filter out null values', () => {
      const stats = {
        video_codec: 'H.264',
        resolution: null,
        source_fps: 30
      };

      const result = RecordingDetailsModalUtils.getStatRows(stats);

      expect(result).toEqual([
        ['Video Codec', 'H.264'],
        ['FPS', 30]
      ]);
    });

    it('should filter out undefined values', () => {
      const stats = {
        video_codec: 'H.264',
        source_fps: undefined,
        audio_codec: 'AAC'
      };

      const result = RecordingDetailsModalUtils.getStatRows(stats);

      expect(result).toEqual([
        ['Video Codec', 'H.264'],
        ['Audio Codec', 'AAC']
      ]);
    });

    it('should filter out empty strings', () => {
      const stats = {
        video_codec: '',
        audio_codec: 'AAC'
      };

      const result = RecordingDetailsModalUtils.getStatRows(stats);

      expect(result).toEqual([
        ['Audio Codec', 'AAC']
      ]);
    });

    it('should handle missing width or height gracefully', () => {
      const stats = {
        width: 1920,
        video_codec: 'H.264'
      };

      const result = RecordingDetailsModalUtils.getStatRows(stats);

      expect(result).toEqual([
        ['Video Codec', 'H.264']
      ]);
    });

    it('should format bitrates correctly', () => {
      const stats = {
        video_bitrate: 2500,
        audio_bitrate: 192
      };

      const result = RecordingDetailsModalUtils.getStatRows(stats);

      expect(result).toEqual([
        ['Video Bitrate', '2500 kb/s'],
        ['Audio Bitrate', '192 kb/s']
      ]);
    });

    it('should format sample rate correctly', () => {
      const stats = {
        sample_rate: 44100
      };

      const result = RecordingDetailsModalUtils.getStatRows(stats);

      expect(result).toEqual([
        ['Sample Rate', '44100 Hz']
      ]);
    });

    it('should return empty array when no valid stats', () => {
      const stats = {
        video_codec: null,
        resolution: undefined,
        source_fps: ''
      };

      const result = RecordingDetailsModalUtils.getStatRows(stats);

      expect(result).toEqual([]);
    });

    it('should handle empty stats object', () => {
      const stats = {};

      const result = RecordingDetailsModalUtils.getStatRows(stats);

      expect(result).toEqual([]);
    });
  });

  describe('getRating', () => {
    it('should return rating from customProps', () => {
      const customProps = { rating: 'TV-MA' };
      const program = null;

      const result = RecordingDetailsModalUtils.getRating(customProps, program);

      expect(result).toBe('TV-MA');
    });

    it('should return rating_value when rating is not present', () => {
      const customProps = { rating_value: 'PG-13' };
      const program = null;

      const result = RecordingDetailsModalUtils.getRating(customProps, program);

      expect(result).toBe('PG-13');
    });

    it('should prefer rating over rating_value', () => {
      const customProps = { rating: 'TV-MA', rating_value: 'PG-13' };
      const program = null;

      const result = RecordingDetailsModalUtils.getRating(customProps, program);

      expect(result).toBe('TV-MA');
    });

    it('should return rating from program custom_properties', () => {
      const customProps = {};
      const program = {
        custom_properties: { rating: 'TV-14' }
      };

      const result = RecordingDetailsModalUtils.getRating(customProps, program);

      expect(result).toBe('TV-14');
    });

    it('should prefer customProps rating over program rating', () => {
      const customProps = { rating: 'TV-MA' };
      const program = {
        custom_properties: { rating: 'TV-14' }
      };

      const result = RecordingDetailsModalUtils.getRating(customProps, program);

      expect(result).toBe('TV-MA');
    });

    it('should prefer rating_value over program rating', () => {
      const customProps = { rating_value: 'PG-13' };
      const program = {
        custom_properties: { rating: 'TV-14' }
      };

      const result = RecordingDetailsModalUtils.getRating(customProps, program);

      expect(result).toBe('PG-13');
    });

    it('should return undefined when no rating is available', () => {
      const customProps = {};
      const program = { custom_properties: {} };

      const result = RecordingDetailsModalUtils.getRating(customProps, program);

      expect(result).toBeUndefined();
    });

    it('should handle null program', () => {
      const customProps = {};
      const program = null;

      const result = RecordingDetailsModalUtils.getRating(customProps, program);

      expect(result).toBeNull();
    });

    it('should handle program without custom_properties', () => {
      const customProps = {};
      const program = { title: 'Test' };

      const result = RecordingDetailsModalUtils.getRating(customProps, program);

      expect(result).toBeUndefined();
    });
  });

  describe('getUpcomingEpisodes', () => {
    let toUserTime;
    let userNow;

    beforeEach(() => {
      const baseTime = dayjs('2024-01-01T12:00:00');
      toUserTime = vi.fn((time) => dayjs(time));
      userNow = vi.fn(() => baseTime);
    });

    it('should return empty array when not a series group', () => {
      const result = RecordingDetailsModalUtils.getUpcomingEpisodes(
        false,
        [],
        {},
        toUserTime,
        userNow
      );

      expect(result).toEqual([]);
    });

    it('should return empty array when allRecordings is empty', () => {
      const program = { tvg_id: 'test', title: 'Test Show' };

      const result = RecordingDetailsModalUtils.getUpcomingEpisodes(
        true,
        [],
        program,
        toUserTime,
        userNow
      );

      expect(result).toEqual([]);
    });

    it('should filter recordings by tvg_id and title', () => {
      const program = { tvg_id: 'show1', title: 'Test Show' };
      const recordings = [
        {
          start_time: '2024-01-02T12:00:00',
          channel: 'ch1',
          custom_properties: {
            program: { tvg_id: 'show1', title: 'Test Show' }
          }
        },
        {
          start_time: '2024-01-02T13:00:00',
          channel: 'ch1',
          custom_properties: {
            program: { tvg_id: 'show2', title: 'Other Show' }
          }
        }
      ];

      const result = RecordingDetailsModalUtils.getUpcomingEpisodes(
        true,
        recordings,
        program,
        toUserTime,
        userNow
      );

      expect(result).toHaveLength(1);
      expect(result[0].custom_properties.program.tvg_id).toBe('show1');
    });

    it('should filter out past recordings', () => {
      const program = { tvg_id: 'show1', title: 'Test Show' };
      const recordings = [
        {
          start_time: '2023-12-31T12:00:00',
          channel: 'ch1',
          custom_properties: {
            program: { tvg_id: 'show1', title: 'Test Show' }
          }
        },
        {
          start_time: '2024-01-02T12:00:00',
          channel: 'ch1',
          custom_properties: {
            program: { tvg_id: 'show1', title: 'Test Show' }
          }
        }
      ];

      const result = RecordingDetailsModalUtils.getUpcomingEpisodes(
        true,
        recordings,
        program,
        toUserTime,
        userNow
      );

      expect(result).toHaveLength(1);
      expect(result[0].start_time).toBe('2024-01-02T12:00:00');
    });

    it('should deduplicate by season and episode', () => {
      const program = { tvg_id: 'show1', title: 'Test Show' };
      const recordings = [
        {
          start_time: '2024-01-02T12:00:00',
          channel: 'ch1',
          custom_properties: {
            season: 1,
            episode: 5,
            program: { tvg_id: 'show1', title: 'Test Show' }
          }
        },
        {
          start_time: '2024-01-02T18:00:00',
          channel: 'ch2',
          custom_properties: {
            season: 1,
            episode: 5,
            program: { tvg_id: 'show1', title: 'Test Show' }
          }
        }
      ];

      const result = RecordingDetailsModalUtils.getUpcomingEpisodes(
        true,
        recordings,
        program,
        toUserTime,
        userNow
      );

      expect(result).toHaveLength(1);
    });

    it('should deduplicate by onscreen episode', () => {
      const program = { tvg_id: 'show1', title: 'Test Show' };
      const recordings = [
        {
          start_time: '2024-01-02T12:00:00',
          channel: 'ch1',
          custom_properties: {
            onscreen_episode: 'S01E05',
            program: { tvg_id: 'show1', title: 'Test Show' }
          }
        },
        {
          start_time: '2024-01-02T18:00:00',
          channel: 'ch2',
          custom_properties: {
            onscreen_episode: 's01e05',
            program: { tvg_id: 'show1', title: 'Test Show' }
          }
        }
      ];

      const result = RecordingDetailsModalUtils.getUpcomingEpisodes(
        true,
        recordings,
        program,
        toUserTime,
        userNow
      );

      expect(result).toHaveLength(1);
    });

    it('should deduplicate by program sub_title', () => {
      const program = { tvg_id: 'show1', title: 'Test Show' };
      const recordings = [
        {
          start_time: '2024-01-02T12:00:00',
          channel: 'ch1',
          custom_properties: {
            program: {
              tvg_id: 'show1',
              title: 'Test Show',
              sub_title: 'The Beginning'
            }
          }
        },
        {
          start_time: '2024-01-02T18:00:00',
          channel: 'ch2',
          custom_properties: {
            program: {
              tvg_id: 'show1',
              title: 'Test Show',
              sub_title: 'The Beginning'
            }
          }
        }
      ];

      const result = RecordingDetailsModalUtils.getUpcomingEpisodes(
        true,
        recordings,
        program,
        toUserTime,
        userNow
      );

      expect(result).toHaveLength(1);
    });

    it('should deduplicate by program id', () => {
      const program = { tvg_id: 'show1', title: 'Test Show' };
      const recordings = [
        {
          start_time: '2024-01-02T12:00:00',
          channel: 'ch1',
          custom_properties: {
            program: { tvg_id: 'show1', title: 'Test Show', id: 123 }
          }
        },
        {
          start_time: '2024-01-02T18:00:00',
          channel: 'ch2',
          custom_properties: {
            program: { tvg_id: 'show1', title: 'Test Show', id: 123 }
          }
        }
      ];

      const result = RecordingDetailsModalUtils.getUpcomingEpisodes(
        true,
        recordings,
        program,
        toUserTime,
        userNow
      );

      expect(result).toHaveLength(1);
    });

    it('should sort by start time ascending', () => {
      const program = { tvg_id: 'show1', title: 'Test Show' };
      const recordings = [
        {
          start_time: '2024-01-03T12:00:00',
          end_time: '2024-01-03T13:00:00',
          channel: 'ch1',
          custom_properties: {
            program: { tvg_id: 'show1', title: 'Test Show', id: 3 }
          }
        },
        {
          start_time: '2024-01-02T12:00:00',
          end_time: '2024-01-02T13:00:00',
          channel: 'ch1',
          custom_properties: {
            program: { tvg_id: 'show1', title: 'Test Show', id: 1 }
          }
        },
        {
          start_time: '2024-01-04T12:00:00',
          end_time: '2024-01-04T13:00:00',
          channel: 'ch1',
          custom_properties: {
            program: { tvg_id: 'show1', title: 'Test Show', id: 4 }
          }
        }
      ];

      const result = RecordingDetailsModalUtils.getUpcomingEpisodes(
        true,
        recordings,
        program,
        toUserTime,
        userNow
      );

      expect(result).toHaveLength(3);
      expect(result[0].start_time).toBe('2024-01-02T12:00:00');
      expect(result[1].start_time).toBe('2024-01-03T12:00:00');
      expect(result[2].start_time).toBe('2024-01-04T12:00:00');
    });

    it('should handle allRecordings as object', () => {
      const program = { tvg_id: 'show1', title: 'Test Show' };
      const recordings = {
        rec1: {
          start_time: '2024-01-02T12:00:00',
          channel: 'ch1',
          custom_properties: {
            program: { tvg_id: 'show1', title: 'Test Show', id: 1 }
          }
        }
      };

      const result = RecordingDetailsModalUtils.getUpcomingEpisodes(
        true,
        recordings,
        program,
        toUserTime,
        userNow
      );

      expect(result).toHaveLength(1);
    });

    it('should handle case-insensitive title matching', () => {
      const program = { tvg_id: 'show1', title: 'Test Show' };
      const recordings = [
        {
          start_time: '2024-01-02T12:00:00',
          channel: 'ch1',
          custom_properties: {
            program: { tvg_id: 'show1', title: 'test show' }
          }
        }
      ];

      const result = RecordingDetailsModalUtils.getUpcomingEpisodes(
        true,
        recordings,
        program,
        toUserTime,
        userNow
      );

      expect(result).toHaveLength(1);
    });

    it('should prefer season/episode from program custom_properties', () => {
      const program = { tvg_id: 'show1', title: 'Test Show' };
      const recordings = [
        {
          start_time: '2024-01-02T12:00:00',
          channel: 'ch1',
          custom_properties: {
            program: {
              tvg_id: 'show1',
              title: 'Test Show',
              custom_properties: { season: 2, episode: 3 }
            }
          }
        },
        {
          start_time: '2024-01-02T18:00:00',
          channel: 'ch2',
          custom_properties: {
            program: {
              tvg_id: 'show1',
              title: 'Test Show',
              custom_properties: { season: 2, episode: 3 }
            }
          }
        }
      ];

      const result = RecordingDetailsModalUtils.getUpcomingEpisodes(
        true,
        recordings,
        program,
        toUserTime,
        userNow
      );

      expect(result).toHaveLength(1);
    });

    it('should handle missing custom_properties', () => {
      const program = { tvg_id: 'show1', title: 'Test Show' };
      const recordings = [
        {
          start_time: '2024-01-02T12:00:00',
          channel: 'ch1'
        }
      ];

      const result = RecordingDetailsModalUtils.getUpcomingEpisodes(
        true,
        recordings,
        program,
        toUserTime,
        userNow
      );

      expect(result).toEqual([]);
    });
  });
});
