import { describe, it, expect, vi, beforeEach } from 'vitest';
import * as SettingsUtils from '../SettingsUtils';
import API from '../../../api.js';

vi.mock('../../../api.js', () => ({
  default: {
    checkSetting: vi.fn(),
    updateSetting: vi.fn(),
    createSetting: vi.fn(),
    rehashStreams: vi.fn()
  }
}));

describe('SettingsUtils', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('checkSetting', () => {
    it('should call API checkSetting with values', async () => {
      const values = { key: 'test-setting', value: 'test-value' };
      await SettingsUtils.checkSetting(values);
      expect(API.checkSetting).toHaveBeenCalledWith(values);
      expect(API.checkSetting).toHaveBeenCalledTimes(1);
    });
  });

  describe('updateSetting', () => {
    it('should call API updateSetting with values', async () => {
      const values = { id: 1, key: 'test-setting', value: 'new-value' };
      await SettingsUtils.updateSetting(values);
      expect(API.updateSetting).toHaveBeenCalledWith(values);
      expect(API.updateSetting).toHaveBeenCalledTimes(1);
    });
  });

  describe('createSetting', () => {
    it('should call API createSetting with values', async () => {
      const values = { key: 'new-setting', name: 'New Setting', value: 'value' };
      await SettingsUtils.createSetting(values);
      expect(API.createSetting).toHaveBeenCalledWith(values);
      expect(API.createSetting).toHaveBeenCalledTimes(1);
    });
  });

  describe('rehashStreams', () => {
    it('should call API rehashStreams', async () => {
      await SettingsUtils.rehashStreams();
      expect(API.rehashStreams).toHaveBeenCalledWith();
      expect(API.rehashStreams).toHaveBeenCalledTimes(1);
    });
  });

  describe('saveChangedSettings', () => {
    it('should group stream settings correctly and update', async () => {
      const settings = {
        stream_settings: {
          id: 1,
          key: 'stream_settings',
          value: {
            default_user_agent: 5,
            m3u_hash_key: 'channel_name'
          }
        }
      };
      const changedSettings = {
        default_user_agent: 7,
        preferred_region: 'UK'
      };

      API.updateSetting.mockResolvedValue({});

      await SettingsUtils.saveChangedSettings(settings, changedSettings);

      expect(API.updateSetting).toHaveBeenCalledWith({
        id: 1,
        key: 'stream_settings',
        value: {
          default_user_agent: 7,
          m3u_hash_key: 'channel_name',
          preferred_region: 'UK'
        }
      });
    });

    it('should convert m3u_hash_key array to comma-separated string', async () => {
      const settings = {
        stream_settings: {
          id: 1,
          key: 'stream_settings',
          value: {}
        }
      };
      const changedSettings = {
        m3u_hash_key: ['channel_name', 'channel_number']
      };

      API.updateSetting.mockResolvedValue({});

      await SettingsUtils.saveChangedSettings(settings, changedSettings);

      expect(API.updateSetting).toHaveBeenCalledWith({
        id: 1,
        key: 'stream_settings',
        value: {
          m3u_hash_key: 'channel_name,channel_number'
        }
      });
    });

    it('should convert ID fields to integers', async () => {
      const settings = {
        stream_settings: {
          id: 1,
          key: 'stream_settings',
          value: {}
        }
      };
      const changedSettings = {
        default_user_agent: '5',
        default_stream_profile: '3'
      };

      API.updateSetting.mockResolvedValue({});

      await SettingsUtils.saveChangedSettings(settings, changedSettings);

      expect(API.updateSetting).toHaveBeenCalledWith({
        id: 1,
        key: 'stream_settings',
        value: {
          default_user_agent: 5,
          default_stream_profile: 3
        }
      });
    });

    it('should preserve boolean types', async () => {
      const settings = {
        dvr_settings: {
          id: 2,
          key: 'dvr_settings',
          value: {}
        },
        stream_settings: {
          id: 1,
          key: 'stream_settings',
          value: {}
        }
      };
      const changedSettings = {
        comskip_enabled: true,
        auto_import_mapped_files: false
      };

      API.updateSetting.mockResolvedValue({});

      await SettingsUtils.saveChangedSettings(settings, changedSettings);

      expect(API.updateSetting).toHaveBeenCalledTimes(2);
    });

    it('should handle proxy_settings specially', async () => {
      const settings = {
        proxy_settings: {
          id: 5,
          key: 'proxy_settings',
          value: {
            buffering_speed: 1.0
          }
        }
      };
      const changedSettings = {
        proxy_settings: {
          buffering_speed: 2.5,
          buffering_timeout: 15
        }
      };

      API.updateSetting.mockResolvedValue({});

      await SettingsUtils.saveChangedSettings(settings, changedSettings);

      expect(API.updateSetting).toHaveBeenCalledWith({
        id: 5,
        key: 'proxy_settings',
        value: {
          buffering_speed: 2.5,
          buffering_timeout: 15
        }
      });
    });

    it('should create proxy_settings if it does not exist', async () => {
      const settings = {};
      const changedSettings = {
        proxy_settings: {
          buffering_speed: 2.5
        }
      };

      API.createSetting.mockResolvedValue({});

      await SettingsUtils.saveChangedSettings(settings, changedSettings);

      expect(API.createSetting).toHaveBeenCalledWith({
        key: 'proxy_settings',
        name: 'Proxy Settings',
        value: {
          buffering_speed: 2.5
        }
      });
    });

    it('should handle network_access specially', async () => {
      const settings = {
        network_access: {
          id: 6,
          key: 'network_access',
          value: []
        }
      };
      const changedSettings = {
        network_access: ['192.168.1.0/24', '10.0.0.0/8']
      };

      API.updateSetting.mockResolvedValue({});

      await SettingsUtils.saveChangedSettings(settings, changedSettings);

      expect(API.updateSetting).toHaveBeenCalledWith({
        id: 6,
        key: 'network_access',
        value: ['192.168.1.0/24', '10.0.0.0/8']
      });
    });
  });

  describe('parseSettings', () => {
    it('should parse grouped settings correctly', () => {
      const mockSettings = {
        'stream_settings': {
          id: 1,
          key: 'stream_settings',
          value: {
            default_user_agent: 5,
            default_stream_profile: 3,
            m3u_hash_key: 'channel_name,channel_number',
            preferred_region: 'US',
            auto_import_mapped_files: true
          }
        },
        'dvr_settings': {
          id: 2,
          key: 'dvr_settings',
          value: {
            tv_template: '/media/tv/{show}/{season}/',
            comskip_enabled: false,
            pre_offset_minutes: 2,
            post_offset_minutes: 5
          }
        }
      };

      const result = SettingsUtils.parseSettings(mockSettings);

      // Check stream settings
      expect(result.default_user_agent).toBe('5');
      expect(result.default_stream_profile).toBe('3');
      expect(result.m3u_hash_key).toEqual(['channel_name', 'channel_number']);
      expect(result.preferred_region).toBe('US');
      expect(result.auto_import_mapped_files).toBe(true);

      // Check DVR settings
      expect(result.tv_template).toBe('/media/tv/{show}/{season}/');
      expect(result.comskip_enabled).toBe(false);
      expect(result.pre_offset_minutes).toBe(2);
      expect(result.post_offset_minutes).toBe(5);
    });

    it('should handle empty m3u_hash_key', () => {
      const mockSettings = {
        'stream_settings': {
          id: 1,
          key: 'stream_settings',
          value: {
            m3u_hash_key: ''
          }
        }
      };

      const result = SettingsUtils.parseSettings(mockSettings);
      expect(result.m3u_hash_key).toEqual([]);
    });

    it('should handle proxy_settings', () => {
      const mockSettings = {
        'proxy_settings': {
          id: 5,
          key: 'proxy_settings',
          value: {
            buffering_speed: 2.5,
            buffering_timeout: 15
          }
        }
      };

      const result = SettingsUtils.parseSettings(mockSettings);
      expect(result.proxy_settings).toEqual({
        buffering_speed: 2.5,
        buffering_timeout: 15
      });
    });

    it('should handle network_access', () => {
      const mockSettings = {
        'network_access': {
          id: 6,
          key: 'network_access',
          value: ['192.168.1.0/24', '10.0.0.0/8']
        }
      };

      const result = SettingsUtils.parseSettings(mockSettings);
      expect(result.network_access).toEqual(['192.168.1.0/24', '10.0.0.0/8']);
    });
  });

  describe('getChangedSettings', () => {
    it('should detect changes in primitive values', () => {
      const values = {
        time_zone: 'America/New_York',
        max_system_events: 2000,
        comskip_enabled: true
      };
      const settings = {
        time_zone: { value: 'UTC' },
        max_system_events: { value: 1000 },
        comskip_enabled: { value: false }
      };

      const changes = SettingsUtils.getChangedSettings(values, settings);

      expect(changes).toEqual({
        time_zone: 'America/New_York',
        max_system_events: 2000,
        comskip_enabled: true
      });
    });

    it('should not detect unchanged values', () => {
      const values = {
        time_zone: 'UTC',
        max_system_events: 1000
      };
      const settings = {
        time_zone: { value: 'UTC' },
        max_system_events: { value: 1000 }
      };

      const changes = SettingsUtils.getChangedSettings(values, settings);
      expect(changes).toEqual({});
    });

    it('should preserve type of numeric values', () => {
      const values = {
        max_system_events: 2000
      };
      const settings = {
        max_system_events: { value: 1000 }
      };

      const changes = SettingsUtils.getChangedSettings(values, settings);
      expect(typeof changes.max_system_events).toBe('number');
      expect(changes.max_system_events).toBe(2000);
    });

    it('should detect changes in array values', () => {
      const values = {
        m3u_hash_key: ['channel_name', 'channel_number']
      };
      const settings = {
        m3u_hash_key: { value: 'channel_name' }
      };

      const changes = SettingsUtils.getChangedSettings(values, settings);
      // Arrays are converted to comma-separated strings internally
      expect(changes).toEqual({
        m3u_hash_key: 'channel_name,channel_number'
      });
    });

    it('should skip proxy_settings and network_access', () => {
      const values = {
        time_zone: 'America/New_York',
        proxy_settings: {
          buffering_speed: 2.5
        },
        network_access: ['192.168.1.0/24']
      };
      const settings = {
        time_zone: { value: 'UTC' }
      };

      const changes = SettingsUtils.getChangedSettings(values, settings);
      expect(changes.proxy_settings).toBeUndefined();
      expect(changes.network_access).toBeUndefined();
      expect(changes.time_zone).toBe('America/New_York');
    });

    it('should always include epg_match_mode', () => {
      const values = {
        epg_match_mode: 'advanced',
        epg_match_ignore_prefixes: ['HD:'],
      };
      const settings = {};

      const changes = SettingsUtils.getChangedSettings(values, settings);
      expect(changes.epg_match_mode).toBe('advanced');
    });

    it('should default epg_match_mode to "default" if not provided', () => {
      const values = {
        epg_match_ignore_prefixes: ['HD:'],
      };
      const settings = {};

      const changes = SettingsUtils.getChangedSettings(values, settings);
      // epg_match_mode should not be included if not in values
      expect(changes.epg_match_mode).toBeUndefined();
    });

    it('should always include EPG array fields even if empty', () => {
      const values = {
        epg_match_ignore_prefixes: [],
        epg_match_ignore_suffixes: [],
        epg_match_ignore_custom: [],
      };
      const settings = {};

      const changes = SettingsUtils.getChangedSettings(values, settings);
      expect(changes.epg_match_ignore_prefixes).toEqual([]);
      expect(changes.epg_match_ignore_suffixes).toEqual([]);
      expect(changes.epg_match_ignore_custom).toEqual([]);
    });
  });

  describe('saveChangedSettings - EPG Mode', () => {
    it('should save epg_match_mode to epg_settings group', async () => {
      const settings = {
        epg_settings: {
          id: 3,
          key: 'epg_settings',
          value: {
            epg_match_mode: 'default',
            epg_match_ignore_prefixes: [],
            epg_match_ignore_suffixes: [],
            epg_match_ignore_custom: [],
          }
        }
      };
      const changedSettings = {
        epg_match_mode: 'advanced',
        epg_match_ignore_prefixes: ['HD:'],
      };

      API.updateSetting.mockResolvedValue({});

      await SettingsUtils.saveChangedSettings(settings, changedSettings);

      expect(API.updateSetting).toHaveBeenCalledWith({
        id: 3,
        key: 'epg_settings',
        value: {
          epg_match_mode: 'advanced',
          epg_match_ignore_prefixes: ['HD:'],
          epg_match_ignore_suffixes: [],
          epg_match_ignore_custom: [],
        }
      });
    });

    it('should create epg_settings if it does not exist', async () => {
      const settings = {};
      const changedSettings = {
        epg_match_mode: 'advanced',
        epg_match_ignore_prefixes: ['Sling:'],
      };

      API.createSetting.mockResolvedValue({});

      await SettingsUtils.saveChangedSettings(settings, changedSettings);

      expect(API.createSetting).toHaveBeenCalledWith({
        key: 'epg_settings',
        name: 'Epg Settings',
        value: {
          epg_match_mode: 'advanced',
          epg_match_ignore_prefixes: ['Sling:'],
        }
      });
    });

    it('should preserve existing EPG settings when updating mode', async () => {
      const settings = {
        epg_settings: {
          id: 3,
          key: 'epg_settings',
          value: {
            epg_match_mode: 'advanced',
            epg_match_ignore_prefixes: ['HD:'],
            epg_match_ignore_suffixes: [' 4K'],
            epg_match_ignore_custom: ['Plus'],
          }
        }
      };
      const changedSettings = {
        epg_match_mode: 'default',
      };

      API.updateSetting.mockResolvedValue({});

      await SettingsUtils.saveChangedSettings(settings, changedSettings);

      expect(API.updateSetting).toHaveBeenCalledWith({
        id: 3,
        key: 'epg_settings',
        value: {
          epg_match_mode: 'default',
          epg_match_ignore_prefixes: ['HD:'],
          epg_match_ignore_suffixes: [' 4K'],
          epg_match_ignore_custom: ['Plus'],
        }
      });
    });
  });
});
