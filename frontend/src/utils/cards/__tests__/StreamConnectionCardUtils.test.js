import { describe, it, expect, vi, beforeEach } from 'vitest';
import * as StreamConnectionCardUtils from '../StreamConnectionCardUtils';
import API from '../../../api.js';
import * as dateTimeUtils from '../../dateTimeUtils.js';

vi.mock('../../../api.js');
vi.mock('../../dateTimeUtils.js');

describe('StreamConnectionCardUtils', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('getBufferingSpeedThreshold', () => {
    it('should return parsed buffering_speed from proxy settings', () => {
      const proxySetting = { value: { buffering_speed: 0.8 } };
      expect(
        StreamConnectionCardUtils.getBufferingSpeedThreshold(proxySetting)
      ).toBe(0.8);
    });

    it('should return 1.0 when proxySetting is null', () => {
      expect(StreamConnectionCardUtils.getBufferingSpeedThreshold(null)).toBe(
        1.0
      );
    });
  });

  describe('getNewClientBehindSeconds', () => {
    it('reads new_client_behind_seconds from proxy settings', () => {
      expect(
        StreamConnectionCardUtils.getNewClientBehindSeconds({
          value: { new_client_behind_seconds: 8 },
        })
      ).toBe(8);
    });

    it('defaults to 5 when missing', () => {
      expect(StreamConnectionCardUtils.getNewClientBehindSeconds(null)).toBe(5);
    });
  });

  describe('getBufferBudgetColor', () => {
    it('is green above half, orange from half down to empty, red at 0', () => {
      expect(StreamConnectionCardUtils.getBufferBudgetColor(5, 5)).toBe('green');
      expect(StreamConnectionCardUtils.getBufferBudgetColor(2.6, 5)).toBe(
        'green'
      );
      expect(StreamConnectionCardUtils.getBufferBudgetColor(2.5, 5)).toBe(
        'orange'
      );
      expect(StreamConnectionCardUtils.getBufferBudgetColor(0.1, 5)).toBe(
        'orange'
      );
      expect(StreamConnectionCardUtils.getBufferBudgetColor(0, 5)).toBe('red');
    });
  });

  describe('isSpeedHealthy', () => {
    const defaultMode = { value: { buffering_speed: 1.0 } };
    const ingestMode = {
      value: { buffering_speed: 1.0, experimental_ingest_buffer: true },
    };

    it('uses Buffering Speed as the healthy line in both modes', () => {
      expect(StreamConnectionCardUtils.isSpeedHealthy(1.0, defaultMode)).toBe(
        true
      );
      expect(StreamConnectionCardUtils.isSpeedHealthy(0.99, defaultMode)).toBe(
        false
      );
      expect(StreamConnectionCardUtils.isSpeedHealthy(0.99, ingestMode)).toBe(
        false
      );
      expect(StreamConnectionCardUtils.isSpeedHealthy(0.9, ingestMode)).toBe(
        false
      );
    });

    it('scales with a custom buffering speed', () => {
      const setting = {
        value: { buffering_speed: 2.0, experimental_ingest_buffer: true },
      };
      expect(StreamConnectionCardUtils.isSpeedHealthy(2.0, setting)).toBe(true);
      expect(StreamConnectionCardUtils.isSpeedHealthy(1.9, setting)).toBe(
        false
      );
    });

    it('falls back to 1.0 when settings are missing', () => {
      expect(StreamConnectionCardUtils.isSpeedHealthy(1.0, null)).toBe(true);
      expect(StreamConnectionCardUtils.isSpeedHealthy(0.5, null)).toBe(false);
    });
  });

  describe('getStartDate', () => {
    it('should calculate start date from uptime in seconds', () => {
      const uptime = 3600; // 1 hour
      const result = StreamConnectionCardUtils.getStartDate(uptime);
      expect(typeof result).toBe('string');
      expect(result.length).toBeGreaterThan(0);
    });

    it('should handle zero uptime', () => {
      const result = StreamConnectionCardUtils.getStartDate(0);
      expect(typeof result).toBe('string');
    });
  });

  describe('getM3uAccountsMap', () => {
    it('should create map from m3u accounts array', () => {
      const m3uAccounts = [
        { id: 1, name: 'Account 1' },
        { id: 2, name: 'Account 2' },
      ];
      const result = StreamConnectionCardUtils.getM3uAccountsMap(m3uAccounts);
      expect(result).toEqual({ 1: 'Account 1', 2: 'Account 2' });
    });

    it('should handle accounts without id', () => {
      const m3uAccounts = [{ name: 'Account 1' }, { id: 2, name: 'Account 2' }];
      const result = StreamConnectionCardUtils.getM3uAccountsMap(m3uAccounts);
      expect(result).toEqual({ 2: 'Account 2' });
    });

    it('should return empty object for null input', () => {
      expect(StreamConnectionCardUtils.getM3uAccountsMap(null)).toEqual({});
    });

    it('should return empty object for non-array input', () => {
      expect(StreamConnectionCardUtils.getM3uAccountsMap({})).toEqual({});
    });
  });

  describe('getChannelStreams', () => {
    it('should call API.getChannelStreams with channelId', async () => {
      const mockStreams = [{ id: 1, name: 'Stream 1' }];
      API.getChannelStreams.mockResolvedValue(mockStreams);

      const result = await StreamConnectionCardUtils.getChannelStreams(123);

      expect(API.getChannelStreams).toHaveBeenCalledWith(123);
      expect(result).toEqual(mockStreams);
    });
  });

  describe('getMatchingStreamByUrl', () => {
    it('should find stream when channelUrl includes stream url', () => {
      const streamData = [
        { id: 1, url: 'http://example.com/stream1' },
        { id: 2, url: 'http://example.com/stream2' },
      ];
      const result = StreamConnectionCardUtils.getMatchingStreamByUrl(
        streamData,
        'http://example.com/stream1/playlist.m3u8'
      );
      expect(result).toEqual(streamData[0]);
    });

    it('should find stream when stream url includes channelUrl', () => {
      const streamData = [
        { id: 1, url: 'http://example.com/stream1/playlist.m3u8' },
      ];
      const result = StreamConnectionCardUtils.getMatchingStreamByUrl(
        streamData,
        'http://example.com/stream1'
      );
      expect(result).toEqual(streamData[0]);
    });

    it('should return undefined when no match found', () => {
      const streamData = [{ id: 1, url: 'http://example.com/stream1' }];
      const result = StreamConnectionCardUtils.getMatchingStreamByUrl(
        streamData,
        'http://different.com/stream'
      );
      expect(result).toBeUndefined();
    });
  });

  describe('getSelectedStream', () => {
    it('should find stream by id as string', () => {
      const streams = [
        { id: 1, name: 'Stream 1' },
        { id: 2, name: 'Stream 2' },
      ];
      const result = StreamConnectionCardUtils.getSelectedStream(streams, '2');
      expect(result).toEqual(streams[1]);
    });

    it('should return undefined when stream not found', () => {
      const streams = [{ id: 1, name: 'Stream 1' }];
      const result = StreamConnectionCardUtils.getSelectedStream(streams, '99');
      expect(result).toBeUndefined();
    });
  });

  describe('switchStream', () => {
    it('should call API.switchStream with channel_id and streamId', () => {
      const channel = { channel_id: 123 };
      API.switchStream.mockResolvedValue({ success: true });

      StreamConnectionCardUtils.switchStream(channel, 456);

      expect(API.switchStream).toHaveBeenCalledWith(123, 456);
    });
  });

  describe('connectedAccessor', () => {
    it('should format connected_at correctly', () => {
      const mockTime = new Date('2024-01-01T10:00:00');

      dateTimeUtils.initializeTime.mockReturnValue(mockTime);
      dateTimeUtils.format.mockReturnValue('01/01/2024 10:00:00');

      const accessor = StreamConnectionCardUtils.connectedAccessor(
        'MM/DD/YYYY, HH:mm:ss'
      );
      const result = accessor({ connected_at: 1704103200 });

      expect(dateTimeUtils.initializeTime).toHaveBeenCalledWith(1704103200000);
      expect(dateTimeUtils.format).toHaveBeenCalledWith(
        mockTime,
        'MM/DD/YYYY, HH:mm:ss'
      );
      expect(result).toBe('01/01/2024 10:00:00');
    });

    it('should return Unknown when no time data available', () => {
      const accessor =
        StreamConnectionCardUtils.connectedAccessor('MM/DD/YYYY');
      const result = accessor({});
      expect(result).toBe('Unknown');
    });
  });

  describe('durationAccessor', () => {
    it('should compute duration from connected_at', () => {
      dateTimeUtils.toFriendlyDuration.mockReturnValue('2h 30m');

      const accessor = StreamConnectionCardUtils.durationAccessor();
      // connected_at 9000 seconds before "now" (Date.now() / 1000)
      const connectedAt = Date.now() / 1000 - 9000;
      const result = accessor({ connected_at: connectedAt });

      expect(dateTimeUtils.toFriendlyDuration).toHaveBeenCalledWith(
        expect.closeTo(9000, 1),
        'seconds'
      );
      expect(result).toBe('2h 30m');
    });

    it('should return - when no connected_at available', () => {
      const accessor = StreamConnectionCardUtils.durationAccessor();
      const result = accessor({});
      expect(result).toBe('-');
    });
  });

  describe('getLogoUrl', () => {
    it('should return cache_url from logos map when logoId exists', () => {
      const logos = {
        'logo-123': { cache_url: '/api/logos/logo-123/cache/' },
      };
      const result = StreamConnectionCardUtils.getLogoUrl(
        'logo-123',
        logos,
        null
      );
      expect(result).toBe('/api/logos/logo-123/cache/');
    });

    it('should fallback to previewedStream logo_url when logoId not in map', () => {
      const previewedStream = { logo_url: 'http://example.com/logo.png' };
      const result = StreamConnectionCardUtils.getLogoUrl(
        'logo-456',
        {},
        previewedStream
      );
      expect(result).toBe('http://example.com/logo.png');
    });

    it('should return null when no logo available', () => {
      const result = StreamConnectionCardUtils.getLogoUrl(null, {}, null);
      expect(result).toBeNull();
    });
  });

  describe('getStreamsByIds', () => {
    it('should call API.getStreamsByIds with array containing streamId', async () => {
      const mockStreams = [{ id: 123, name: 'Stream' }];
      API.getStreamsByIds.mockResolvedValue(mockStreams);

      const result = await StreamConnectionCardUtils.getStreamsByIds(123);

      expect(API.getStreamsByIds).toHaveBeenCalledWith([123]);
      expect(result).toEqual(mockStreams);
    });
  });

  describe('getStreamOptions', () => {
    it('should format stream options with account names from map', () => {
      const streams = [
        { id: 1, name: 'Stream 1', m3u_account: 100 },
        { id: 2, name: 'Stream 2', m3u_account: 200 },
      ];
      const accountsMap = { 100: 'Premium Account', 200: 'Basic Account' };

      const result = StreamConnectionCardUtils.getStreamOptions(
        streams,
        accountsMap
      );

      expect(result).toEqual([
        { value: '1', label: 'Stream 1 [Premium Account]' },
        { value: '2', label: 'Stream 2 [Basic Account]' },
      ]);
    });

    it('should use default M3U label when account not in map', () => {
      const streams = [{ id: 1, name: 'Stream 1', m3u_account: 999 }];

      const result = StreamConnectionCardUtils.getStreamOptions(streams, {});

      expect(result[0].label).toBe('Stream 1 [M3U #999]');
    });

    it('should handle streams without name', () => {
      const streams = [{ id: 5, m3u_account: 100 }];
      const accountsMap = { 100: 'Account' };

      const result = StreamConnectionCardUtils.getStreamOptions(
        streams,
        accountsMap
      );

      expect(result[0].label).toBe('Stream #5 [Account]');
    });

    it('should handle streams without m3u_account', () => {
      const streams = [{ id: 1, name: 'Stream 1' }];

      const result = StreamConnectionCardUtils.getStreamOptions(streams, {});

      expect(result[0].label).toBe('Stream 1 [Unknown M3U]');
    });
  });
});
