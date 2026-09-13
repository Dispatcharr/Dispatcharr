import { describe, it, expect, vi, beforeEach } from 'vitest';
import * as SettingsUtils from '../SettingsUtils';
import API from '../../../api.js';

vi.mock('../../../api.js', () => ({
  default: {
    checkSetting: vi.fn(),
    updateSetting: vi.fn(),
    createSetting: vi.fn(),
    rehashStreams: vi.fn(),
  },
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
      const values = {
        key: 'new-setting',
        name: 'New Setting',
        value: 'value',
      };
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

  describe('parseGroupSettings', () => {
    it('parses only stream settings fields', () => {
      const settings = {
        stream_settings: {
          value: {
            default_user_agent: 5,
            default_stream_profile: 3,
            default_output_format: 'fmp4',
            hdhr_output_profile_id: 9,
            m3u_hash_key: 'name,url',
          },
        },
        dvr_settings: {
          value: { output_profile_id: 6, comskip_enabled: true },
        },
      };

      const result = SettingsUtils.parseGroupSettings(
        settings,
        'stream_settings'
      );

      expect(result).toEqual({
        default_user_agent: '5',
        default_stream_profile: '3',
        default_output_format: 'fmp4',
        hdhr_output_profile_id: '9',
        m3u_hash_key: ['name', 'url'],
      });
      expect(result).not.toHaveProperty('output_profile_id');
      expect(result).not.toHaveProperty('comskip_enabled');
    });

    it('parses dvr output_profile_id as a string and maps qsv to hwassist', () => {
      const settings = {
        dvr_settings: {
          value: {
            output_profile_id: 6,
            comskip_hw_accel: 'qsv',
            comskip_enabled: true,
            pre_offset_minutes: 2,
            post_offset_minutes: '3',
            series_rules: [{ id: 1 }],
          },
        },
      };

      const result = SettingsUtils.parseGroupSettings(settings, 'dvr_settings');

      expect(result.output_profile_id).toBe('6');
      expect(result.comskip_hw_accel).toBe('hwassist');
      expect(result.comskip_enabled).toBe(true);
      expect(result.pre_offset_minutes).toBe(2);
      expect(result.post_offset_minutes).toBe(3);
      expect(result.series_rules).toEqual([{ id: 1 }]);
    });

    it('returns epg defaults when the group is missing', () => {
      const result = SettingsUtils.parseGroupSettings({}, 'epg_settings');
      expect(result).toEqual({
        epg_match_mode: 'default',
        epg_match_ignore_prefixes: [],
        epg_match_ignore_suffixes: [],
        epg_match_ignore_custom: [],
      });
    });

    it('parses system settings with defaults for missing keys', () => {
      const settings = {
        system_settings: {
          value: {
            max_system_events: 200,
            preferred_region: 'US',
          },
        },
      };

      const result = SettingsUtils.parseGroupSettings(
        settings,
        'system_settings'
      );

      expect(result.max_system_events).toBe(200);
      expect(result.preferred_region).toBe('US');
      expect(result.log_persist).toBe(true);
      expect(result.catchup_enabled).toBe(true);
    });

    it('applies raw field defaults when keys are missing from an existing group', () => {
      const settings = {
        dvr_settings: {
          value: {
            comskip_enabled: true,
          },
        },
      };

      const result = SettingsUtils.parseGroupSettings(settings, 'dvr_settings');

      expect(result.tv_template).toBe('');
      expect(result.movie_template).toBe('');
      expect(result.comskip_custom_path).toBe('');
      expect(result.comskip_enabled).toBe(true);
    });

    it('does not overwrite an explicit empty raw string with the field default', () => {
      const settings = {
        dvr_settings: {
          value: {
            tv_template: '',
          },
        },
      };

      const result = SettingsUtils.parseGroupSettings(settings, 'dvr_settings');
      expect(result.tv_template).toBe('');
    });
  });

  describe('getChangedGroupSettings', () => {
    it('diffs against the nested group value, not top-level store keys', () => {
      const settings = {
        stream_settings: {
          id: 1,
          key: 'stream_settings',
          value: {
            default_user_agent: 5,
            default_stream_profile: 3,
            default_output_format: 'mpegts',
            hdhr_output_profile_id: null,
            m3u_hash_key: 'name',
          },
        },
      };

      const values = {
        default_user_agent: '5',
        default_stream_profile: '3',
        default_output_format: 'mpegts',
        hdhr_output_profile_id: null,
        m3u_hash_key: ['name'],
      };

      expect(
        SettingsUtils.getChangedGroupSettings(
          values,
          settings,
          'stream_settings'
        )
      ).toEqual({});
    });

    it('includes only changed fields for the group', () => {
      const settings = {
        dvr_settings: {
          value: {
            comskip_enabled: false,
            pre_offset_minutes: 0,
            output_profile_id: null,
          },
        },
      };

      const changes = SettingsUtils.getChangedGroupSettings(
        {
          comskip_enabled: true,
          pre_offset_minutes: 0,
          output_profile_id: null,
          tv_template: undefined,
        },
        settings,
        'dvr_settings'
      );

      expect(changes).toEqual({ comskip_enabled: true });
    });

    it('includes a cleared output_profile_id as null', () => {
      const settings = {
        dvr_settings: {
          value: { output_profile_id: 6 },
        },
      };

      const changes = SettingsUtils.getChangedGroupSettings(
        { output_profile_id: null },
        settings,
        'dvr_settings'
      );

      expect(changes).toEqual({ output_profile_id: null });
    });

    it('does not emit unchanged array fields', () => {
      const settings = {
        epg_settings: {
          value: {
            epg_match_mode: 'advanced',
            epg_match_ignore_prefixes: ['HD:'],
            epg_match_ignore_suffixes: [],
            epg_match_ignore_custom: [],
          },
        },
      };

      const changes = SettingsUtils.getChangedGroupSettings(
        {
          epg_match_mode: 'advanced',
          epg_match_ignore_prefixes: ['HD:'],
          epg_match_ignore_suffixes: [],
          epg_match_ignore_custom: [],
        },
        settings,
        'epg_settings'
      );

      expect(changes).toEqual({});
    });

    it('detects m3u_hash_key changes between array form and CSV store', () => {
      const settings = {
        stream_settings: {
          value: { m3u_hash_key: 'name' },
        },
      };

      const changes = SettingsUtils.getChangedGroupSettings(
        { m3u_hash_key: ['name', 'url'] },
        settings,
        'stream_settings'
      );

      expect(changes).toEqual({ m3u_hash_key: ['name', 'url'] });
    });
  });

  describe('saveGroupSettings', () => {
    it('updates only the requested group and preserves sibling keys', async () => {
      const settings = {
        stream_settings: {
          id: 1,
          key: 'stream_settings',
          value: {
            default_user_agent: 5,
            m3u_hash_key: 'channel_name',
          },
        },
        system_settings: {
          id: 2,
          key: 'system_settings',
          value: { preferred_region: 'US' },
        },
      };

      API.updateSetting.mockResolvedValue({});

      await SettingsUtils.saveGroupSettings(settings, 'stream_settings', {
        default_user_agent: 7,
      });

      expect(API.updateSetting).toHaveBeenCalledTimes(1);
      expect(API.updateSetting).toHaveBeenCalledWith({
        id: 1,
        key: 'stream_settings',
        value: {
          default_user_agent: 7,
          m3u_hash_key: 'channel_name',
        },
      });
      expect(API.createSetting).not.toHaveBeenCalled();
    });

    it('converts m3u_hash_key arrays to CSV and coerces id fields', async () => {
      const settings = {
        stream_settings: {
          id: 1,
          key: 'stream_settings',
          value: {},
        },
      };

      API.updateSetting.mockResolvedValue({});

      await SettingsUtils.saveGroupSettings(settings, 'stream_settings', {
        m3u_hash_key: ['name', 'url'],
        default_user_agent: '5',
        hdhr_output_profile_id: '9',
      });

      expect(API.updateSetting).toHaveBeenCalledWith({
        id: 1,
        key: 'stream_settings',
        value: {
          m3u_hash_key: 'name,url',
          default_user_agent: 5,
          hdhr_output_profile_id: 9,
        },
      });
    });

    it('stores a cleared output_profile_id as null on dvr_settings', async () => {
      const settings = {
        dvr_settings: {
          id: 2,
          key: 'dvr_settings',
          value: { output_profile_id: 6, comskip_enabled: true },
        },
      };

      API.updateSetting.mockResolvedValue({});

      await SettingsUtils.saveGroupSettings(settings, 'dvr_settings', {
        output_profile_id: null,
      });

      expect(API.updateSetting).toHaveBeenCalledWith({
        id: 2,
        key: 'dvr_settings',
        value: { output_profile_id: null, comskip_enabled: true },
      });
    });

    it('creates the group when it does not exist yet', async () => {
      API.createSetting.mockResolvedValue({});

      await SettingsUtils.saveGroupSettings({}, 'system_settings', {
        preferred_region: 'UK',
        catchup_enabled: 'true',
      });

      expect(API.createSetting).toHaveBeenCalledWith({
        key: 'system_settings',
        name: 'System Settings',
        value: {
          preferred_region: 'UK',
          catchup_enabled: true,
        },
      });
    });

    it('throws when updateSetting returns a falsy result', async () => {
      const settings = {
        dvr_settings: {
          id: 2,
          key: 'dvr_settings',
          value: {},
        },
      };
      API.updateSetting.mockResolvedValue(undefined);

      await expect(
        SettingsUtils.saveGroupSettings(settings, 'dvr_settings', {
          comskip_enabled: true,
        })
      ).rejects.toThrow('Failed to update dvr_settings');
    });

    it('ignores fields that do not belong to the group', async () => {
      const settings = {
        stream_settings: {
          id: 1,
          key: 'stream_settings',
          value: { default_user_agent: 1 },
        },
      };
      API.updateSetting.mockResolvedValue({});

      await SettingsUtils.saveGroupSettings(settings, 'stream_settings', {
        default_user_agent: 2,
        preferred_region: 'UK',
      });

      expect(API.updateSetting).toHaveBeenCalledWith({
        id: 1,
        key: 'stream_settings',
        value: { default_user_agent: 2 },
      });
    });

    it('no-ops when the patch is empty', async () => {
      await SettingsUtils.saveGroupSettings(
        { stream_settings: { id: 1, value: {} } },
        'stream_settings',
        {}
      );
      expect(API.updateSetting).not.toHaveBeenCalled();
      expect(API.createSetting).not.toHaveBeenCalled();
    });

    it('creates the group when settings is null', async () => {
      API.createSetting.mockResolvedValue({});

      await SettingsUtils.saveGroupSettings(null, 'dvr_settings', {
        comskip_enabled: true,
      });

      expect(API.createSetting).toHaveBeenCalledWith({
        key: 'dvr_settings',
        name: 'DVR Settings',
        value: { comskip_enabled: true },
      });
    });
  });
});
