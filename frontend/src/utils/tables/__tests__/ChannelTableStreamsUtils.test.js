import { describe, it, expect, vi, beforeEach } from 'vitest';
import * as ChannelTableStreamsUtils from '../ChannelTableStreamsUtils';

// ── Dependency mocks ────────────────────────────────────────────────────────
vi.mock('../../../api.js', () => ({
  default: {
    getChannelStreamStats: vi.fn(),
    reorderChannelStreams: vi.fn(),
  },
}));

vi.mock('../../networkUtils.js', () => ({
  formatBytes: vi.fn((bytes) => `${bytes} B`),
}));

vi.mock('../../dateTimeUtils.js', () => ({
  formatDuration: vi.fn((seconds) => `duration-${seconds}`),
}));

import API from '../../../api.js';
import { formatBytes } from '../../networkUtils.js';
import { formatDuration } from '../../dateTimeUtils.js';

describe('ChannelTableStreamsUtils', () => {
  beforeEach(() => vi.clearAllMocks());

  // ── categorizeStreamStats ───────────────────────────────────────────────────
  describe('categorizeStreamStats', () => {
    it('returns empty categories for null input', () => {
      expect(ChannelTableStreamsUtils.categorizeStreamStats(null)).toEqual({
        basic: {},
        video: {},
        audio: {},
        technical: {},
        other: {},
      });
    });

    it('returns empty categories for undefined input', () => {
      expect(ChannelTableStreamsUtils.categorizeStreamStats(undefined)).toEqual(
        {
          basic: {},
          video: {},
          audio: {},
          technical: {},
          other: {},
        }
      );
    });

    it('categorizes basic fields correctly', () => {
      const stats = {
        resolution: '1920x1080',
        video_codec: 'h264',
        source_fps: 30,
        audio_codec: 'aac',
        audio_channels: 2,
      };
      const result = ChannelTableStreamsUtils.categorizeStreamStats(stats);
      expect(result.basic).toEqual(stats);
      expect(result.video).toEqual({});
      expect(result.audio).toEqual({});
      expect(result.technical).toEqual({});
      expect(result.other).toEqual({});
    });

    it('categorizes video fields correctly', () => {
      const stats = {
        video_bitrate: 5000,
        pixel_format: 'yuv420p',
        width: 1920,
        height: 1080,
        aspect_ratio: '16:9',
        frame_rate: 29.97,
      };
      const result = ChannelTableStreamsUtils.categorizeStreamStats(stats);
      expect(result.video).toEqual(stats);
      expect(result.basic).toEqual({});
    });

    it('categorizes audio fields correctly', () => {
      const stats = {
        audio_bitrate: 192,
        sample_rate: 48000,
        audio_format: 'flac',
        audio_channels_layout: 'stereo',
      };
      const result = ChannelTableStreamsUtils.categorizeStreamStats(stats);
      expect(result.audio).toEqual(stats);
    });

    it('categorizes technical fields correctly', () => {
      const stats = {
        stream_type: 'video',
        container_format: 'mpegts',
        duration: 3600,
        file_size: 1024000,
        ffmpeg_output_bitrate: 8000,
        input_bitrate: 7500,
      };
      const result = ChannelTableStreamsUtils.categorizeStreamStats(stats);
      expect(result.technical).toEqual(stats);
    });

    it('places unknown fields in other', () => {
      const stats = { custom_field: 'value', another_field: 42 };
      const result = ChannelTableStreamsUtils.categorizeStreamStats(stats);
      expect(result.other).toEqual(stats);
    });

    it('handles mixed fields across categories', () => {
      const stats = {
        resolution: '1080p',
        audio_bitrate: 192,
        duration: 7200,
        unknown_key: 'test',
      };
      const result = ChannelTableStreamsUtils.categorizeStreamStats(stats);
      expect(result.basic.resolution).toBe('1080p');
      expect(result.audio.audio_bitrate).toBe(192);
      expect(result.technical.duration).toBe(7200);
      expect(result.other.unknown_key).toBe('test');
    });

    it('returns empty categories for empty stats object', () => {
      const result = ChannelTableStreamsUtils.categorizeStreamStats({});
      expect(result).toEqual({
        basic: {},
        video: {},
        audio: {},
        technical: {},
        other: {},
      });
    });
  });

  // ── formatStatValue ─────────────────────────────────────────────────────────
  describe('formatStatValue', () => {
    it('returns "N/A" for null value', () => {
      expect(ChannelTableStreamsUtils.formatStatValue('resolution', null)).toBe(
        'N/A'
      );
    });

    it('returns "N/A" for undefined value', () => {
      expect(
        ChannelTableStreamsUtils.formatStatValue('resolution', undefined)
      ).toBe('N/A');
    });

    it('formats video_bitrate with kbps', () => {
      expect(
        ChannelTableStreamsUtils.formatStatValue('video_bitrate', 5000)
      ).toBe('5000 kbps');
    });

    it('formats audio_bitrate with kbps', () => {
      expect(
        ChannelTableStreamsUtils.formatStatValue('audio_bitrate', 192)
      ).toBe('192 kbps');
    });

    it('formats ffmpeg_output_bitrate with kbps', () => {
      expect(
        ChannelTableStreamsUtils.formatStatValue('ffmpeg_output_bitrate', 8000)
      ).toBe('8000 kbps');
    });

    it('formats source_fps with fps', () => {
      expect(ChannelTableStreamsUtils.formatStatValue('source_fps', 30)).toBe(
        '30 fps'
      );
    });

    it('formats frame_rate with fps', () => {
      expect(
        ChannelTableStreamsUtils.formatStatValue('frame_rate', 29.97)
      ).toBe('29.97 fps');
    });

    it('formats sample_rate with Hz', () => {
      expect(
        ChannelTableStreamsUtils.formatStatValue('sample_rate', 48000)
      ).toBe('48000 Hz');
    });

    it('formats file_size using formatBytes when numeric', () => {
      vi.mocked(formatBytes).mockReturnValue('1.0 MB');
      expect(
        ChannelTableStreamsUtils.formatStatValue('file_size', 1048576)
      ).toBe('1.0 MB');
      expect(formatBytes).toHaveBeenCalledWith(1048576);
    });

    it('returns raw value for file_size when not numeric', () => {
      expect(
        ChannelTableStreamsUtils.formatStatValue('file_size', 'unknown')
      ).toBe('unknown');
      expect(formatBytes).not.toHaveBeenCalled();
    });

    it('formats duration using formatDuration with alwaysShowHours when numeric', () => {
      vi.mocked(formatDuration).mockReturnValue('01:00:00');
      expect(ChannelTableStreamsUtils.formatStatValue('duration', 3600)).toBe(
        '01:00:00'
      );
      expect(formatDuration).toHaveBeenCalledWith(3600, {
        alwaysShowHours: true,
      });
    });

    it('returns raw value for duration when not numeric', () => {
      expect(ChannelTableStreamsUtils.formatStatValue('duration', 'live')).toBe(
        'live'
      );
      expect(formatDuration).not.toHaveBeenCalled();
    });

    it('converts default values to string', () => {
      expect(
        ChannelTableStreamsUtils.formatStatValue('resolution', '1920x1080')
      ).toBe('1920x1080');
    });

    it('converts numeric default values to string', () => {
      expect(ChannelTableStreamsUtils.formatStatValue('width', 1920)).toBe(
        '1920'
      );
    });
  });

  // ── formatStatKey ───────────────────────────────────────────────────────────
  describe('formatStatKey', () => {
    it('replaces underscores with spaces and title-cases each word', () => {
      expect(ChannelTableStreamsUtils.formatStatKey('video_bitrate')).toBe(
        'Video Bitrate'
      );
    });

    it('handles single word keys', () => {
      expect(ChannelTableStreamsUtils.formatStatKey('resolution')).toBe(
        'Resolution'
      );
    });

    it('handles multi-word keys', () => {
      expect(
        ChannelTableStreamsUtils.formatStatKey('audio_channels_layout')
      ).toBe('Audio Channels Layout');
    });

    it('handles already-capitalized keys', () => {
      expect(ChannelTableStreamsUtils.formatStatKey('FPS')).toBe('FPS');
    });
  });

  // ── API wrappers ────────────────────────────────────────────────────────────
  describe('getChannelStreamStats', () => {
    it('calls API.getChannelStreamStats with correct args', () => {
      const mockReturn = Promise.resolve({ data: [] });
      vi.mocked(API.getChannelStreamStats).mockReturnValue(mockReturn);
      const result = ChannelTableStreamsUtils.getChannelStreamStats(
        'ch-1',
        '2024-01-01',
        [1, 2]
      );
      expect(API.getChannelStreamStats).toHaveBeenCalledWith(
        'ch-1',
        '2024-01-01',
        [1, 2]
      );
      expect(result).toBe(mockReturn);
    });
  });

  describe('reorderChannelStreams', () => {
    it('calls API.reorderChannelStreams with correct args', () => {
      const mockReturn = Promise.resolve(undefined);
      vi.mocked(API.reorderChannelStreams).mockReturnValue(mockReturn);
      const result = ChannelTableStreamsUtils.reorderChannelStreams(
        'ch-1',
        [3, 1, 2]
      );
      expect(API.reorderChannelStreams).toHaveBeenCalledWith('ch-1', [3, 1, 2]);
      expect(result).toBe(mockReturn);
    });
  });
});
