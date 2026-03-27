import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import {
  getTechnicalDetails,
  getMovieStreamUrl,
  formatVideoDetails,
  formatAudioDetails,
} from '../VODModalUtils';

describe('VODModalUtils', () => {
  describe('getTechnicalDetails', () => {
    const defaultVOD = {
      bitrate: '5000 kbps',
      video: 'H.264',
      audio: 'AAC',
    };

    it('should return defaultVOD details when no provider selected', () => {
      const result = getTechnicalDetails(null, defaultVOD);

      expect(result).toEqual({
        bitrate: '5000 kbps',
        video: 'H.264',
        audio: 'AAC',
      });
    });

    it('should extract details from movie content', () => {
      const provider = {
        movie: {
          bitrate: '8000 kbps',
          video: 'H.265',
          audio: 'AC3',
        },
      };

      const result = getTechnicalDetails(provider, defaultVOD);

      expect(result).toEqual({
        bitrate: '8000 kbps',
        video: 'H.265',
        audio: 'AC3',
      });
    });

    it('should extract details from episode content', () => {
      const provider = {
        episode: {
          bitrate: '6000 kbps',
          video: 'AVC',
          audio: 'DTS',
        },
      };

      const result = getTechnicalDetails(provider, defaultVOD);

      expect(result).toEqual({
        bitrate: '6000 kbps',
        video: 'AVC',
        audio: 'DTS',
      });
    });

    it('should extract details from provider object directly', () => {
      const provider = {
        bitrate: '7000 kbps',
        video: 'VP9',
        audio: 'Opus',
      };

      const result = getTechnicalDetails(provider, defaultVOD);

      expect(result).toEqual({
        bitrate: '7000 kbps',
        video: 'VP9',
        audio: 'Opus',
      });
    });

    it('should extract details from custom_properties.detailed_info', () => {
      const provider = {
        custom_properties: {
          detailed_info: {
            bitrate: '9000 kbps',
            video: 'AV1',
            audio: 'EAC3',
          },
        },
      };

      const result = getTechnicalDetails(provider, defaultVOD);

      expect(result).toEqual({
        bitrate: '9000 kbps',
        video: 'AV1',
        audio: 'EAC3',
      });
    });

    it('should fallback to defaultVOD when provider has no valid details', () => {
      const provider = {
        custom_properties: {},
      };

      const result = getTechnicalDetails(provider, defaultVOD);

      expect(result).toEqual({
        bitrate: '5000 kbps',
        video: 'H.264',
        audio: 'AAC',
      });
    });

    it('should prioritize movie content over provider object', () => {
      const provider = {
        movie: {
          bitrate: '8000 kbps',
        },
        bitrate: '7000 kbps',
      };

      const result = getTechnicalDetails(provider, defaultVOD);

      expect(result.bitrate).toBe('8000 kbps');
    });

    it('should handle undefined defaultVOD', () => {
      const result = getTechnicalDetails(null, undefined);

      expect(result).toEqual({
        bitrate: undefined,
        video: undefined,
        audio: undefined,
      });
    });
  });

  describe('getMovieStreamUrl', () => {
    const vod = { uuid: 'test-uuid-123' };
    const originalLocation = window.location;

    beforeEach(() => {
      delete window.location;
      window.location = {
        protocol: 'https:',
        hostname: 'example.com',
        origin: 'https://example.com',
      };
    });

    afterEach(() => {
      window.location = originalLocation;
    });

    it('should generate basic stream URL without provider', () => {
      const result = getMovieStreamUrl(vod, null, 'production');

      expect(result).toBe('https://example.com/proxy/vod/movie/test-uuid-123');
    });

    it('should include stream_id when available', () => {
      const provider = {
        stream_id: 'stream-123',
        m3u_account: { id: 'account-456' },
      };

      const result = getMovieStreamUrl(vod, provider, 'production');

      expect(result).toBe(
        'https://example.com/proxy/vod/movie/test-uuid-123?stream_id=stream-123'
      );
    });

    it('should include m3u_account_id when stream_id not available', () => {
      const provider = {
        m3u_account: { id: 'account-456' },
      };

      const result = getMovieStreamUrl(vod, provider, 'production');

      expect(result).toBe(
        'https://example.com/proxy/vod/movie/test-uuid-123?m3u_account_id=account-456'
      );
    });

    it('should use dev port in dev mode', () => {
      const result = getMovieStreamUrl(vod, null, 'dev');

      expect(result).toBe(
        'https://example.com:5656/proxy/vod/movie/test-uuid-123'
      );
    });

    it('should encode stream_id', () => {
      const provider = {
        stream_id: 'stream with spaces',
      };

      const result = getMovieStreamUrl(vod, provider, 'production');

      expect(result).toContain('stream_id=stream%20with%20spaces');
    });
  });

  describe('formatVideoDetails', () => {
    it('should format complete video details', () => {
      const video = {
        codec_name: 'h264',
        codec_long_name: 'H.264 / AVC / MPEG-4 AVC',
        profile: 'High',
        width: 1920,
        height: 1080,
        display_aspect_ratio: '16:9',
        bit_rate: '8000000',
        r_frame_rate: '23.98',
        tags: { encoder: 'x264' },
      };

      const result = formatVideoDetails(video);

      expect(result).toBe(
        'H.264 / AVC / MPEG-4 AVC, (High), 1920x1080, Aspect Ratio: ' +
        '16:9, Bitrate: 8000 kbps, Frame Rate: 23.98 fps, Encoder: x264'
      );
    });

    it('should use codec_name when codec_long_name is unknown', () => {
      const video = {
        codec_name: 'h264',
        codec_long_name: 'unknown',
      };

      const result = formatVideoDetails(video);

      expect(result).toBe('h264');
    });

    it('should use codec_name when codec_long_name is not available', () => {
      const video = {
        codec_name: 'h265',
      };

      const result = formatVideoDetails(video);

      expect(result).toBe('h265');
    });

    it('should handle minimal video details', () => {
      const video = {
        codec_name: 'vp9',
      };

      const result = formatVideoDetails(video);

      expect(result).toBe('vp9');
    });

    it('should format bitrate correctly', () => {
      const video = {
        codec_name: 'h264',
        bit_rate: '5500000',
      };

      const result = formatVideoDetails(video);

      expect(result).toContain('Bitrate: 5500 kbps');
    });
  });

  describe('formatAudioDetails', () => {
    it('should format complete audio details', () => {
      const audio = {
        codec_name: 'aac',
        codec_long_name: 'AAC (Advanced Audio Coding)',
        profile: 'LC',
        channel_layout: '5.1',
        sample_rate: '48000',
        bit_rate: '256000',
        tags: { handler_name: 'SoundHandler' },
      };

      const result = formatAudioDetails(audio);

      expect(result).toBe(
        'AAC (Advanced Audio Coding), (LC), Channels: 5.1, ' +
        'Sample Rate: 48000 Hz, Bitrate: 256 kbps, Handler: SoundHandler'
      );
    });

    it('should use codec_name when codec_long_name is unknown', () => {
      const audio = {
        codec_name: 'ac3',
        codec_long_name: 'unknown',
      };

      const result = formatAudioDetails(audio);

      expect(result).toBe('ac3');
    });

    it('should use channels count when channel_layout not available', () => {
      const audio = {
        codec_name: 'aac',
        channels: '2',
      };

      const result = formatAudioDetails(audio);

      expect(result).toBe('aac, Channels: 2');
    });

    it('should handle minimal audio details', () => {
      const audio = {
        codec_name: 'opus',
      };

      const result = formatAudioDetails(audio);

      expect(result).toBe('opus');
    });

    it('should format bitrate correctly', () => {
      const audio = {
        codec_name: 'aac',
        bit_rate: '192000',
      };

      const result = formatAudioDetails(audio);

      expect(result).toContain('Bitrate: 192 kbps');
    });

    it('should prefer channel_layout over channels', () => {
      const audio = {
        codec_name: 'dts',
        channel_layout: '7.1',
        channels: '8',
      };

      const result = formatAudioDetails(audio);

      expect(result).toContain('Channels: 7.1');
    });
  });
});
