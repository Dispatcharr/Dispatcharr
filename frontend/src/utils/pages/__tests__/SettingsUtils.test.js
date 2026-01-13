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

    it('should return API response', async () => {
      const values = { key: 'test-setting', value: 'test-value' };
      const mockResponse = { valid: true };

      API.checkSetting.mockResolvedValue(mockResponse);

      const result = await SettingsUtils.checkSetting(values);

      expect(result).toEqual(mockResponse);
    });

    it('should propagate API errors', async () => {
      const values = { key: 'test-setting', value: 'test-value' };
      const error = new Error('API error');

      API.checkSetting.mockRejectedValue(error);

      await expect(SettingsUtils.checkSetting(values)).rejects.toThrow('API error');
    });
  });

  describe('updateSetting', () => {
    it('should call API updateSetting with values', async () => {
      const values = { id: 1, key: 'test-setting', value: 'new-value' };

      await SettingsUtils.updateSetting(values);

      expect(API.updateSetting).toHaveBeenCalledWith(values);
      expect(API.updateSetting).toHaveBeenCalledTimes(1);
    });

    it('should return API response', async () => {
      const values = { id: 1, key: 'test-setting', value: 'new-value' };
      const mockResponse = { id: 1, value: 'new-value' };

      API.updateSetting.mockResolvedValue(mockResponse);

      const result = await SettingsUtils.updateSetting(values);

      expect(result).toEqual(mockResponse);
    });

    it('should propagate API errors', async () => {
      const values = { id: 1, key: 'test-setting', value: 'new-value' };
      const error = new Error('Update failed');

      API.updateSetting.mockRejectedValue(error);

      await expect(SettingsUtils.updateSetting(values)).rejects.toThrow('Update failed');
    });
  });

  describe('createSetting', () => {
    it('should call API createSetting with values', async () => {
      const values = { key: 'new-setting', name: 'New Setting', value: 'value' };

      await SettingsUtils.createSetting(values);

      expect(API.createSetting).toHaveBeenCalledWith(values);
      expect(API.createSetting).toHaveBeenCalledTimes(1);
    });

    it('should return API response', async () => {
      const values = { key: 'new-setting', name: 'New Setting', value: 'value' };
      const mockResponse = { id: 1, ...values };

      API.createSetting.mockResolvedValue(mockResponse);

      const result = await SettingsUtils.createSetting(values);

      expect(result).toEqual(mockResponse);
    });

    it('should propagate API errors', async () => {
      const values = { key: 'new-setting', name: 'New Setting', value: 'value' };
      const error = new Error('Create failed');

      API.createSetting.mockRejectedValue(error);

      await expect(SettingsUtils.createSetting(values)).rejects.toThrow('Create failed');
    });
  });

  describe('rehashStreams', () => {
    it('should call API rehashStreams', async () => {
      await SettingsUtils.rehashStreams();

      expect(API.rehashStreams).toHaveBeenCalledWith();
      expect(API.rehashStreams).toHaveBeenCalledTimes(1);
    });

    it('should return API response', async () => {
      const mockResponse = { success: true };

      API.rehashStreams.mockResolvedValue(mockResponse);

      const result = await SettingsUtils.rehashStreams();

      expect(result).toEqual(mockResponse);
    });

    it('should propagate API errors', async () => {
      const error = new Error('Rehash failed');

      API.rehashStreams.mockRejectedValue(error);

      await expect(SettingsUtils.rehashStreams()).rejects.toThrow('Rehash failed');
    });
  });

  describe('saveChangedSettings', () => {
    it('should update existing settings', async () => {
      const settings = {
        'setting-1': { id: 1, key: 'setting-1', value: 'old-value' }
      };
      const changedSettings = {
        'setting-1': 'new-value'
      };

      API.updateSetting.mockResolvedValue({ id: 1, value: 'new-value' });

      await SettingsUtils.saveChangedSettings(settings, changedSettings);

      expect(API.updateSetting).toHaveBeenCalledWith({
        id: 1,
        key: 'setting-1',
        value: 'new-value'
      });
    });

    it('should create new settings when not in settings object', async () => {
      const settings = {};
      const changedSettings = {
        'new-setting': 'value'
      };

      API.createSetting.mockResolvedValue({ id: 1, key: 'new-setting', value: 'value' });

      await SettingsUtils.saveChangedSettings(settings, changedSettings);

      expect(API.createSetting).toHaveBeenCalledWith({
        key: 'new-setting',
        name: 'new setting',
        value: 'value'
      });
    });

    it('should create new settings when existing has no id', async () => {
      const settings = {
        'setting-1': { key: 'setting-1', value: 'old-value' }
      };
      const changedSettings = {
        'setting-1': 'new-value'
      };

      API.createSetting.mockResolvedValue({ id: 1, key: 'setting-1', value: 'new-value' });

      await SettingsUtils.saveChangedSettings(settings, changedSettings);

      expect(API.createSetting).toHaveBeenCalledWith({
        key: 'setting-1',
        name: 'setting 1',
        value: 'new-value'
      });
    });

    it('should replace hyphens with spaces in name', async () => {
      const settings = {};
      const changedSettings = {
        'multi-word-setting': 'value'
      };

      API.createSetting.mockResolvedValue({ id: 1 });

      await SettingsUtils.saveChangedSettings(settings, changedSettings);

      expect(API.createSetting).toHaveBeenCalledWith({
        key: 'multi-word-setting',
        name: 'multi word setting',
        value: 'value'
      });
    });

    it('should throw error when update fails', async () => {
      const settings = {
        'setting-1': { id: 1, key: 'setting-1', value: 'old-value' }
      };
      const changedSettings = {
        'setting-1': 'new-value'
      };

      API.updateSetting.mockResolvedValue(undefined);

      await expect(
        SettingsUtils.saveChangedSettings(settings, changedSettings)
      ).rejects.toThrow('Failed to update setting');
    });

    it('should throw error when create fails', async () => {
      const settings = {};
      const changedSettings = {
        'new-setting': 'value'
      };

      API.createSetting.mockResolvedValue(undefined);

      await expect(
        SettingsUtils.saveChangedSettings(settings, changedSettings)
      ).rejects.toThrow('Failed to create setting');
    });

    it('should process multiple changed settings', async () => {
      const settings = {
        'setting-1': { id: 1, key: 'setting-1', value: 'old-value-1' },
        'setting-2': { id: 2, key: 'setting-2', value: 'old-value-2' }
      };
      const changedSettings = {
        'setting-1': 'new-value-1',
        'setting-2': 'new-value-2',
        'setting-3': 'new-value-3'
      };

      API.updateSetting.mockResolvedValue({ success: true });
      API.createSetting.mockResolvedValue({ success: true });

      await SettingsUtils.saveChangedSettings(settings, changedSettings);

      expect(API.updateSetting).toHaveBeenCalledTimes(2);
      expect(API.createSetting).toHaveBeenCalledTimes(1);
    });

    it('should handle empty changedSettings', async () => {
      const settings = {
        'setting-1': { id: 1, key: 'setting-1', value: 'value' }
      };
      const changedSettings = {};

      await SettingsUtils.saveChangedSettings(settings, changedSettings);

      expect(API.updateSetting).not.toHaveBeenCalled();
      expect(API.createSetting).not.toHaveBeenCalled();
    });
  });

  describe('getChangedSettings', () => {
    it('should detect changed values', () => {
      const values = {
        'setting-1': 'new-value'
      };
      const settings = {
        'setting-1': { id: 1, key: 'setting-1', value: 'old-value' }
      };

      const result = SettingsUtils.getChangedSettings(values, settings);

      expect(result).toEqual({
        'setting-1': 'new-value'
      });
    });

    it('should include new settings not in settings object', () => {
      const values = {
        'new-setting': 'value'
      };
      const settings = {};

      const result = SettingsUtils.getChangedSettings(values, settings);

      expect(result).toEqual({
        'new-setting': 'value'
      });
    });

    it('should skip unchanged values', () => {
      const values = {
        'setting-1': 'same-value'
      };
      const settings = {
        'setting-1': { id: 1, key: 'setting-1', value: 'same-value' }
      };

      const result = SettingsUtils.getChangedSettings(values, settings);

      expect(result).toEqual({});
    });

    it('should convert array values to comma-separated strings', () => {
      const values = {
        'm3u-hash-key': ['key1', 'key2', 'key3']
      };
      const settings = {
        'm3u-hash-key': { id: 1, key: 'm3u-hash-key', value: 'old-value' }
      };

      const result = SettingsUtils.getChangedSettings(values, settings);

      expect(result).toEqual({
        'm3u-hash-key': 'key1,key2,key3'
      });
    });

    it('should skip empty string values', () => {
      const values = {
        'setting-1': '',
        'setting-2': 'value'
      };
      const settings = {};

      const result = SettingsUtils.getChangedSettings(values, settings);

      expect(result).toEqual({
        'setting-2': 'value'
      });
    });

    it('should skip empty array values', () => {
      const values = {
        'setting-1': [],
        'setting-2': ['value']
      };
      const settings = {};

      const result = SettingsUtils.getChangedSettings(values, settings);

      expect(result).toEqual({
        'setting-2': 'value'
      });
    });

    it('should convert non-string values to strings', () => {
      const values = {
        'setting-1': 123,
        'setting-2': true,
        'setting-3': false
      };
      const settings = {};

      const result = SettingsUtils.getChangedSettings(values, settings);

      expect(result).toEqual({
        'setting-1': '123',
        'setting-2': 'true',
        'setting-3': 'false'
      });
    });

    it('should compare string values correctly', () => {
      const values = {
        'setting-1': 'value',
        'setting-2': 123
      };
      const settings = {
        'setting-1': { id: 1, key: 'setting-1', value: 'value' },
        'setting-2': { id: 2, key: 'setting-2', value: 123 }
      };

      const result = SettingsUtils.getChangedSettings(values, settings);

      expect(result).toEqual({});
    });
  });

  describe('parseSettings', () => {
    it('should convert string "true" to boolean true', () => {
      const settings = {
        'setting-1': { id: 1, key: 'setting-1', value: 'true' }
      };

      const result = SettingsUtils.parseSettings(settings);

      expect(result).toEqual({
        'setting-1': true
      });
    });

    it('should convert string "false" to boolean false', () => {
      const settings = {
        'setting-1': { id: 1, key: 'setting-1', value: 'false' }
      };

      const result = SettingsUtils.parseSettings(settings);

      expect(result).toEqual({
        'setting-1': false
      });
    });

    it('should parse m3u-hash-key as array', () => {
      const settings = {
        'm3u-hash-key': { id: 1, key: 'm3u-hash-key', value: 'key1,key2,key3' }
      };

      const result = SettingsUtils.parseSettings(settings);

      expect(result).toEqual({
        'm3u-hash-key': ['key1', 'key2', 'key3']
      });
    });

    it('should filter empty strings from m3u-hash-key array', () => {
      const settings = {
        'm3u-hash-key': { id: 1, key: 'm3u-hash-key', value: 'key1,,key2,' }
      };

      const result = SettingsUtils.parseSettings(settings);

      expect(result).toEqual({
        'm3u-hash-key': ['key1', 'key2']
      });
    });

    it('should return empty array for empty m3u-hash-key', () => {
      const settings = {
        'm3u-hash-key': { id: 1, key: 'm3u-hash-key', value: '' }
      };

      const result = SettingsUtils.parseSettings(settings);

      expect(result).toEqual({
        'm3u-hash-key': []
      });
    });

    it('should return empty array for null m3u-hash-key', () => {
      const settings = {
        'm3u-hash-key': { id: 1, key: 'm3u-hash-key', value: null }
      };

      const result = SettingsUtils.parseSettings(settings);

      expect(result).toEqual({
        'm3u-hash-key': []
      });
    });

    it('should parse dvr-pre-offset-minutes as integer', () => {
      const settings = {
        'dvr-pre-offset-minutes': { id: 1, key: 'dvr-pre-offset-minutes', value: '5' }
      };

      const result = SettingsUtils.parseSettings(settings);

      expect(result).toEqual({
        'dvr-pre-offset-minutes': 5
      });
    });

    it('should parse dvr-post-offset-minutes as integer', () => {
      const settings = {
        'dvr-post-offset-minutes': { id: 1, key: 'dvr-post-offset-minutes', value: '10' }
      };

      const result = SettingsUtils.parseSettings(settings);

      expect(result).toEqual({
        'dvr-post-offset-minutes': 10
      });
    });

    it('should default offset minutes to 0 for empty string', () => {
      const settings = {
        'dvr-pre-offset-minutes': { id: 1, key: 'dvr-pre-offset-minutes', value: '' },
        'dvr-post-offset-minutes': { id: 2, key: 'dvr-post-offset-minutes', value: '' }
      };

      const result = SettingsUtils.parseSettings(settings);

      expect(result).toEqual({
        'dvr-pre-offset-minutes': 0,
        'dvr-post-offset-minutes': 0
      });
    });

    it('should default offset minutes to 0 for NaN', () => {
      const settings = {
        'dvr-pre-offset-minutes': { id: 1, key: 'dvr-pre-offset-minutes', value: 'invalid' },
        'dvr-post-offset-minutes': { id: 2, key: 'dvr-post-offset-minutes', value: 'abc' }
      };

      const result = SettingsUtils.parseSettings(settings);

      expect(result).toEqual({
        'dvr-pre-offset-minutes': 0,
        'dvr-post-offset-minutes': 0
      });
    });

    it('should keep other values unchanged', () => {
      const settings = {
        'setting-1': { id: 1, key: 'setting-1', value: 'test-value' },
        'setting-2': { id: 2, key: 'setting-2', value: 123 }
      };

      const result = SettingsUtils.parseSettings(settings);

      expect(result).toEqual({
        'setting-1': 'test-value',
        'setting-2': 123
      });
    });

    it('should handle empty settings object', () => {
      const result = SettingsUtils.parseSettings({});

      expect(result).toEqual({});
    });

    it('should process multiple settings with mixed types', () => {
      const settings = {
        'enabled': { id: 1, key: 'enabled', value: 'true' },
        'disabled': { id: 2, key: 'disabled', value: 'false' },
        'm3u-hash-key': { id: 3, key: 'm3u-hash-key', value: 'key1,key2' },
        'dvr-pre-offset-minutes': { id: 4, key: 'dvr-pre-offset-minutes', value: '5' },
        'dvr-post-offset-minutes': { id: 5, key: 'dvr-post-offset-minutes', value: '10' },
        'other-setting': { id: 6, key: 'other-setting', value: 'value' }
      };

      const result = SettingsUtils.parseSettings(settings);

      expect(result).toEqual({
        'enabled': true,
        'disabled': false,
        'm3u-hash-key': ['key1', 'key2'],
        'dvr-pre-offset-minutes': 5,
        'dvr-post-offset-minutes': 10,
        'other-setting': 'value'
      });
    });
  });
});
