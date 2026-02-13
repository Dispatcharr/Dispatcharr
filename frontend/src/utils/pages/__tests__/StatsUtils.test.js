import { describe, it, expect, vi, beforeEach } from 'vitest';
import * as StatsUtils from '../StatsUtils';
import API from '../../../api.js';

vi.mock('../../../api.js', () => ({
  default: {
    stopChannel: vi.fn(),
    stopClient: vi.fn(),
    stopVODClient: vi.fn(),
    fetchActiveChannelStats: vi.fn(),
    getVODStats: vi.fn(),
  },
}));

describe('StatsUtils', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('stopChannel', () => {
    it('should call API stopChannel with id', async () => {
      const id = 'channel-123';

      await StatsUtils.stopChannel(id);

      expect(API.stopChannel).toHaveBeenCalledWith('channel-123');
      expect(API.stopChannel).toHaveBeenCalledTimes(1);
    });

    it('should handle numeric id', async () => {
      const id = 123;

      await StatsUtils.stopChannel(id);

      expect(API.stopChannel).toHaveBeenCalledWith(123);
    });

    it('should propagate API errors', async () => {
      const id = 'channel-123';
      const error = new Error('Failed to stop channel');

      API.stopChannel.mockRejectedValue(error);

      await expect(StatsUtils.stopChannel(id)).rejects.toThrow(
        'Failed to stop channel'
      );
    });
  });

  describe('stopClient', () => {
    it('should call API stopClient with channelId and clientId', async () => {
      const channelId = 'channel-123';
      const clientId = 'client-456';

      await StatsUtils.stopClient(channelId, clientId);

      expect(API.stopClient).toHaveBeenCalledWith('channel-123', 'client-456');
      expect(API.stopClient).toHaveBeenCalledTimes(1);
    });

    it('should handle numeric ids', async () => {
      const channelId = 123;
      const clientId = 456;

      await StatsUtils.stopClient(channelId, clientId);

      expect(API.stopClient).toHaveBeenCalledWith(123, 456);
    });

    it('should propagate API errors', async () => {
      const channelId = 'channel-123';
      const clientId = 'client-456';
      const error = new Error('Failed to stop client');

      API.stopClient.mockRejectedValue(error);

      await expect(StatsUtils.stopClient(channelId, clientId)).rejects.toThrow(
        'Failed to stop client'
      );
    });
  });

  describe('stopVODClient', () => {
    it('should call API stopVODClient with clientId', async () => {
      const clientId = 'vod-client-123';

      await StatsUtils.stopVODClient(clientId);

      expect(API.stopVODClient).toHaveBeenCalledWith('vod-client-123');
      expect(API.stopVODClient).toHaveBeenCalledTimes(1);
    });

    it('should handle numeric clientId', async () => {
      const clientId = 123;

      await StatsUtils.stopVODClient(clientId);

      expect(API.stopVODClient).toHaveBeenCalledWith(123);
    });

    it('should propagate API errors', async () => {
      const clientId = 'vod-client-123';
      const error = new Error('Failed to stop VOD client');

      API.stopVODClient.mockRejectedValue(error);

      await expect(StatsUtils.stopVODClient(clientId)).rejects.toThrow(
        'Failed to stop VOD client'
      );
    });
  });

  describe('fetchActiveChannelStats', () => {
    it('should call API fetchActiveChannelStats', async () => {
      const mockStats = { channels: [] };

      API.fetchActiveChannelStats.mockResolvedValue(mockStats);

      const result = await StatsUtils.fetchActiveChannelStats();

      expect(API.fetchActiveChannelStats).toHaveBeenCalledWith();
      expect(API.fetchActiveChannelStats).toHaveBeenCalledTimes(1);
      expect(result).toEqual(mockStats);
    });

    it('should propagate API errors', async () => {
      const error = new Error('Failed to fetch stats');

      API.fetchActiveChannelStats.mockRejectedValue(error);

      await expect(StatsUtils.fetchActiveChannelStats()).rejects.toThrow(
        'Failed to fetch stats'
      );
    });
  });

  describe('getVODStats', () => {
    it('should call API getVODStats', async () => {
      const mockStats = [{ content_type: 'movie', connections: [] }];

      API.getVODStats.mockResolvedValue(mockStats);

      const result = await StatsUtils.getVODStats();

      expect(API.getVODStats).toHaveBeenCalledWith();
      expect(API.getVODStats).toHaveBeenCalledTimes(1);
      expect(result).toEqual(mockStats);
    });

    it('should propagate API errors', async () => {
      const error = new Error('Failed to fetch VOD stats');

      API.getVODStats.mockRejectedValue(error);

      await expect(StatsUtils.getVODStats()).rejects.toThrow(
        'Failed to fetch VOD stats'
      );
    });
  });

  describe('getCombinedConnections', () => {
    it('should combine channel history and VOD connections', () => {
      const channelHistory = {
        ch1: { channel_id: 'ch1', uptime: 100 },
      };
      const vodConnections = [
        {
          content_type: 'movie',
          content_uuid: 'uuid1',
          connections: [{ client_id: 'client1', connected_at: 50 }],
        },
      ];

      const result = StatsUtils.getCombinedConnections(
        channelHistory,
        vodConnections
      );

      expect(result).toHaveLength(2);
      expect(result[0].type).toBe('stream');
      expect(result[1].type).toBe('vod');
    });

    it('should sort by sortKey descending (newest first)', () => {
      const channelHistory = {
        ch1: { channel_id: 'ch1', uptime: 50 },
      };
      const vodConnections = [
        {
          content_type: 'movie',
          content_uuid: 'uuid1',
          connections: [{ client_id: 'client1', connected_at: 100 }],
        },
      ];

      const result = StatsUtils.getCombinedConnections(
        channelHistory,
        vodConnections
      );

      expect(result[0].sortKey).toBe(100);
      expect(result[1].sortKey).toBe(50);
    });

    it('should flatten VOD connections to individual cards', () => {
      const vodConnections = [
        {
          content_type: 'movie',
          content_uuid: 'uuid1',
          connections: [
            { client_id: 'client1', connected_at: 100 },
            { client_id: 'client2', connected_at: 200 },
          ],
        },
      ];

      const result = StatsUtils.getCombinedConnections({}, vodConnections);

      expect(result).toHaveLength(2);
      expect(result[0].data.connections).toHaveLength(1);
      expect(result[0].data.connection_count).toBe(1);
      expect(result[0].data.individual_connection.client_id).toBe('client2');
      expect(result[1].data.individual_connection.client_id).toBe('client1');
    });

    it('should create unique IDs for VOD items', () => {
      const vodConnections = [
        {
          content_type: 'movie',
          content_uuid: 'uuid1',
          connections: [
            { client_id: 'client1', connected_at: 100 },
            { client_id: 'client2', connected_at: 200 },
          ],
        },
      ];

      const result = StatsUtils.getCombinedConnections({}, vodConnections);

      expect(result[0].id).toBe('movie-uuid1-client2-1');
      expect(result[1].id).toBe('movie-uuid1-client1-0');
    });

    it('should use uptime for stream sortKey', () => {
      const channelHistory = {
        ch1: { channel_id: 'ch1', uptime: 150 },
      };

      const result = StatsUtils.getCombinedConnections(channelHistory, []);

      expect(result[0].sortKey).toBe(150);
    });

    it('should default to 0 for missing uptime', () => {
      const channelHistory = {
        ch1: { channel_id: 'ch1' },
      };

      const result = StatsUtils.getCombinedConnections(channelHistory, []);

      expect(result[0].sortKey).toBe(0);
    });

    it('should use connected_at for VOD sortKey', () => {
      const vodConnections = [
        {
          content_type: 'movie',
          content_uuid: 'uuid1',
          connections: [{ client_id: 'client1', connected_at: 250 }],
        },
      ];

      const result = StatsUtils.getCombinedConnections({}, vodConnections);

      expect(result[0].sortKey).toBe(250);
    });

    it('should handle empty connections array', () => {
      const vodConnections = [
        {
          content_type: 'movie',
          content_uuid: 'uuid1',
          connections: [],
        },
      ];

      const result = StatsUtils.getCombinedConnections({}, vodConnections);

      expect(result).toHaveLength(0);
    });

    it('should handle empty inputs', () => {
      const result = StatsUtils.getCombinedConnections({}, []);

      expect(result).toEqual([]);
    });

    it('should handle null connections', () => {
      const vodConnections = [
        {
          content_type: 'movie',
          content_uuid: 'uuid1',
          connections: null,
        },
      ];

      const result = StatsUtils.getCombinedConnections({}, vodConnections);

      expect(result).toHaveLength(0);
    });
  });

  describe('getClientStats', () => {
    it('should extract clients from channel stats', () => {
      const stats = {
        ch1: {
          channel_id: 'ch1',
          clients: [{ client_id: 'client1' }, { client_id: 'client2' }],
        },
      };

      const result = StatsUtils.getClientStats(stats);

      expect(result).toHaveLength(2);
      expect(result[0].client_id).toBe('client1');
      expect(result[0].channel.channel_id).toBe('ch1');
    });

    it('should attach channel reference to each client', () => {
      const stats = {
        ch1: {
          channel_id: 'ch1',
          name: 'Channel 1',
          clients: [{ client_id: 'client1' }],
        },
      };

      const result = StatsUtils.getClientStats(stats);

      expect(result[0].channel).toEqual({
        channel_id: 'ch1',
        name: 'Channel 1',
        clients: [{ client_id: 'client1' }],
      });
    });

    it('should handle channels without clients array', () => {
      const stats = {
        ch1: { channel_id: 'ch1' },
        ch2: { channel_id: 'ch2', clients: null },
      };

      const result = StatsUtils.getClientStats(stats);

      expect(result).toEqual([]);
    });

    it('should handle empty clients array', () => {
      const stats = {
        ch1: {
          channel_id: 'ch1',
          clients: [],
        },
      };

      const result = StatsUtils.getClientStats(stats);

      expect(result).toEqual([]);
    });

    it('should combine clients from multiple channels', () => {
      const stats = {
        ch1: {
          channel_id: 'ch1',
          clients: [{ client_id: 'client1' }],
        },
        ch2: {
          channel_id: 'ch2',
          clients: [{ client_id: 'client2' }],
        },
      };

      const result = StatsUtils.getClientStats(stats);

      expect(result).toHaveLength(2);
      expect(result[0].channel.channel_id).toBe('ch1');
      expect(result[1].channel.channel_id).toBe('ch2');
    });

    it('should handle empty stats object', () => {
      const result = StatsUtils.getClientStats({});

      expect(result).toEqual([]);
    });
  });

  describe('getStatsByChannelId', () => {
    it('should create stats indexed by channel_id', () => {
      const channelStats = {
        channels: [{ channel_id: 'ch1', total_bytes: 1000 }],
      };
      const prevChannelHistory = {};
      const channelsByUUID = {};
      const channels = {};
      const streamProfiles = [];

      const result = StatsUtils.getStatsByChannelId(
        channelStats,
        prevChannelHistory,
        channelsByUUID,
        channels,
        streamProfiles
      );

      expect(result).toHaveProperty('ch1');
      expect(result.ch1.channel_id).toBe('ch1');
    });

    it('should calculate bitrates from previous history', () => {
      const channelStats = {
        channels: [{ channel_id: 'ch1', total_bytes: 2000 }],
      };
      const prevChannelHistory = {
        ch1: {
          total_bytes: 1000,
          bitrates: [500],
        },
      };

      const result = StatsUtils.getStatsByChannelId(
        channelStats,
        prevChannelHistory,
        {},
        {},
        []
      );

      expect(result.ch1.bitrates).toEqual([500, 1000]);
    });

    it('should limit bitrates array to 15 entries', () => {
      const prevBitrates = new Array(15).fill(100);
      const channelStats = {
        channels: [{ channel_id: 'ch1', total_bytes: 2000 }],
      };
      const prevChannelHistory = {
        ch1: {
          total_bytes: 1000,
          bitrates: prevBitrates,
        },
      };

      const result = StatsUtils.getStatsByChannelId(
        channelStats,
        prevChannelHistory,
        {},
        {},
        []
      );

      expect(result.ch1.bitrates).toHaveLength(15);
      expect(result.ch1.bitrates[0]).toBe(100);
      expect(result.ch1.bitrates[14]).toBe(1000);
    });

    it('should skip negative bitrates', () => {
      const channelStats = {
        channels: [{ channel_id: 'ch1', total_bytes: 500 }],
      };
      const prevChannelHistory = {
        ch1: {
          total_bytes: 1000,
          bitrates: [],
        },
      };

      const result = StatsUtils.getStatsByChannelId(
        channelStats,
        prevChannelHistory,
        {},
        {},
        []
      );

      expect(result.ch1.bitrates).toEqual([]);
    });

    it('should merge channel data from channelsByUUID', () => {
      const channelStats = {
        channels: [{ channel_id: 'uuid1', total_bytes: 1000 }],
      };
      const channelsByUUID = {
        uuid1: 'channel-key-1',
      };
      const channels = {
        'channel-key-1': {
          name: 'Channel 1',
          logo: 'logo.png',
        },
      };

      const result = StatsUtils.getStatsByChannelId(
        channelStats,
        {},
        channelsByUUID,
        channels,
        []
      );

      expect(result.uuid1.name).toBe('Channel 1');
      expect(result.uuid1.logo).toBe('logo.png');
    });

    it('should find and attach stream profile', () => {
      const channelStats = {
        channels: [{ channel_id: 'ch1', stream_profile: '1' }],
      };
      const streamProfiles = [
        { id: 1, name: 'HD Profile' },
        { id: 2, name: 'SD Profile' },
      ];

      const result = StatsUtils.getStatsByChannelId(
        channelStats,
        {},
        {},
        {},
        streamProfiles
      );

      expect(result.ch1.stream_profile.name).toBe('HD Profile');
    });

    it('should default to Unknown for missing stream profile', () => {
      const channelStats = {
        channels: [{ channel_id: 'ch1', stream_profile: '999' }],
      };
      const streamProfiles = [{ id: 1, name: 'HD Profile' }];

      const result = StatsUtils.getStatsByChannelId(
        channelStats,
        {},
        {},
        {},
        streamProfiles
      );

      expect(result.ch1.stream_profile.name).toBe('Unknown');
    });

    it('should preserve stream_id from channel stats', () => {
      const channelStats = {
        channels: [{ channel_id: 'ch1', stream_id: 'stream-123' }],
      };

      const result = StatsUtils.getStatsByChannelId(
        channelStats,
        {},
        {},
        {},
        []
      );

      expect(result.ch1.stream_id).toBe('stream-123');
    });

    it('should set stream_id to null if missing', () => {
      const channelStats = {
        channels: [{ channel_id: 'ch1' }],
      };

      const result = StatsUtils.getStatsByChannelId(
        channelStats,
        {},
        {},
        {},
        []
      );

      expect(result.ch1.stream_id).toBeNull();
    });

    it('should skip channels without channel_id', () => {
      const consoleSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
      const channelStats = {
        channels: [
          { total_bytes: 1000 },
          { channel_id: 'ch1', total_bytes: 2000 },
        ],
      };

      const result = StatsUtils.getStatsByChannelId(
        channelStats,
        {},
        {},
        {},
        []
      );

      expect(result).not.toHaveProperty('undefined');
      expect(result).toHaveProperty('ch1');
      expect(consoleSpy).toHaveBeenCalledWith(
        'Found channel without channel_id:',
        { total_bytes: 1000 }
      );

      consoleSpy.mockRestore();
    });

    it('should handle empty channels array', () => {
      const channelStats = { channels: [] };

      const result = StatsUtils.getStatsByChannelId(
        channelStats,
        {},
        {},
        {},
        []
      );

      expect(result).toEqual({});
    });

    it('should initialize empty bitrates array for new channels', () => {
      const channelStats = {
        channels: [{ channel_id: 'ch1', total_bytes: 1000 }],
      };

      const result = StatsUtils.getStatsByChannelId(
        channelStats,
        {},
        {},
        {},
        []
      );

      expect(result.ch1.bitrates).toEqual([]);
    });
  });
});
