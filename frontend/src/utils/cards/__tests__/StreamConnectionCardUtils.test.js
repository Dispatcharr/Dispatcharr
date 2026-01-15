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
      const proxySetting = {
        value: { buffering_speed: 2.5 }
      };
      expect(StreamConnectionCardUtils.getBufferingSpeedThreshold(proxySetting)).toBe(2.5);
    });

    it('should return 1.0 for invalid JSON', () => {
      const proxySetting = { value: { buffering_speed: 'invalid' } };
      const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
      expect(StreamConnectionCardUtils.getBufferingSpeedThreshold(proxySetting)).toBe(1.0);
      consoleSpy.mockRestore();
    });

    it('should return 1.0 when buffering_speed is not a number', () => {
      const proxySetting = {
        value: JSON.stringify({ buffering_speed: 'not a number' })
      };
      expect(StreamConnectionCardUtils.getBufferingSpeedThreshold(proxySetting)).toBe(1.0);
    });

    it('should return 1.0 when proxySetting is null', () => {
      expect(StreamConnectionCardUtils.getBufferingSpeedThreshold(null)).toBe(1.0);
    });

    it('should return 1.0 when value is missing', () => {
      expect(StreamConnectionCardUtils.getBufferingSpeedThreshold({})).toBe(1.0);
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
        { id: 2, name: 'Account 2' }
      ];
      const result = StreamConnectionCardUtils.getM3uAccountsMap(m3uAccounts);
      expect(result).toEqual({ 1: 'Account 1', 2: 'Account 2' });
    });

    it('should handle accounts without id', () => {
      const m3uAccounts = [
        { name: 'Account 1' },
        { id: 2, name: 'Account 2' }
      ];
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
        { id: 2, url: 'http://example.com/stream2' }
      ];
      const result = StreamConnectionCardUtils.getMatchingStreamByUrl(
        streamData,
        'http://example.com/stream1/playlist.m3u8'
      );
      expect(result).toEqual(streamData[0]);
    });

    it('should find stream when stream url includes channelUrl', () => {
      const streamData = [
        { id: 1, url: 'http://example.com/stream1/playlist.m3u8' }
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
        { id: 2, name: 'Stream 2' }
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
    it('should format connected_since correctly', () => {
      const mockNow = new Date('2024-01-01T12:00:00');
      const mockConnectedTime = new Date('2024-01-01T10:00:00');

      dateTimeUtils.getNow.mockReturnValue(mockNow);
      dateTimeUtils.subtract.mockReturnValue(mockConnectedTime);
      dateTimeUtils.format.mockReturnValue('01/01/2024 10:00:00');

      const accessor = StreamConnectionCardUtils.connectedAccessor('MM/DD/YYYY');
      const result = accessor({ connected_since: 7200 });

      expect(dateTimeUtils.subtract).toHaveBeenCalledWith(mockNow, 7200, 'second');
      expect(dateTimeUtils.format).toHaveBeenCalledWith(mockConnectedTime, 'MM/DD/YYYY HH:mm:ss');
      expect(result).toBe('01/01/2024 10:00:00');
    });

    it('should fallback to connected_at when connected_since is missing', () => {
      const mockTime = new Date('2024-01-01T10:00:00');

      dateTimeUtils.initializeTime.mockReturnValue(mockTime);
      dateTimeUtils.format.mockReturnValue('01/01/2024 10:00:00');

      const accessor = StreamConnectionCardUtils.connectedAccessor('MM/DD/YYYY');
      const result = accessor({ connected_at: 1704103200 });

      expect(dateTimeUtils.initializeTime).toHaveBeenCalledWith(1704103200000);
      expect(result).toBe('01/01/2024 10:00:00');
    });

    it('should return Unknown when no time data available', () => {
      const accessor = StreamConnectionCardUtils.connectedAccessor('MM/DD/YYYY');
      const result = accessor({});
      expect(result).toBe('Unknown');
    });
  });

  describe('durationAccessor', () => {
    it('should format connected_since duration', () => {
      dateTimeUtils.toFriendlyDuration.mockReturnValue('2h 30m');

      const accessor = StreamConnectionCardUtils.durationAccessor();
      const result = accessor({ connected_since: 9000 });

      expect(dateTimeUtils.toFriendlyDuration).toHaveBeenCalledWith(9000, 'seconds');
      expect(result).toBe('2h 30m');
    });

    it('should fallback to connection_duration', () => {
      dateTimeUtils.toFriendlyDuration.mockReturnValue('1h 15m');

      const accessor = StreamConnectionCardUtils.durationAccessor();
      const result = accessor({ connection_duration: 4500 });

      expect(dateTimeUtils.toFriendlyDuration).toHaveBeenCalledWith(4500, 'seconds');
      expect(result).toBe('1h 15m');
    });

    it('should return - when no duration data available', () => {
      const accessor = StreamConnectionCardUtils.durationAccessor();
      const result = accessor({});
      expect(result).toBe('-');
    });
  });

  describe('getLogoUrl', () => {
    it('should return cache_url from logos map when logoId exists', () => {
      const logos = {
        'logo-123': { cache_url: '/api/logos/logo-123/cache/' }
      };
      const result = StreamConnectionCardUtils.getLogoUrl('logo-123', logos, null);
      expect(result).toBe('/api/logos/logo-123/cache/');
    });

    it('should fallback to previewedStream logo_url when logoId not in map', () => {
      const previewedStream = { logo_url: 'http://example.com/logo.png' };
      const result = StreamConnectionCardUtils.getLogoUrl('logo-456', {}, previewedStream);
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
        { id: 2, name: 'Stream 2', m3u_account: 200 }
      ];
      const accountsMap = { 100: 'Premium Account', 200: 'Basic Account' };

      const result = StreamConnectionCardUtils.getStreamOptions(streams, accountsMap);

      expect(result).toEqual([
        { value: '1', label: 'Stream 1 [Premium Account]' },
        { value: '2', label: 'Stream 2 [Basic Account]' }
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

      const result = StreamConnectionCardUtils.getStreamOptions(streams, accountsMap);

      expect(result[0].label).toBe('Stream #5 [Account]');
    });

    it('should handle streams without m3u_account', () => {
      const streams = [{ id: 1, name: 'Stream 1' }];

      const result = StreamConnectionCardUtils.getStreamOptions(streams, {});

      expect(result[0].label).toBe('Stream 1 [Unknown M3U]');
    });
  });
});
