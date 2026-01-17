import { describe, it, expect, vi, beforeEach } from 'vitest';
import * as UiSettingsFormUtils from '../UiSettingsFormUtils';
import * as SettingsUtils from '../../../pages/SettingsUtils.js';

vi.mock('../../../pages/SettingsUtils.js', () => ({
  createSetting: vi.fn(),
  updateSetting: vi.fn()
}));

describe('UiSettingsFormUtils', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('saveTimeZoneSetting', () => {
    it('should update existing setting when id is present', async () => {
      const tzValue = 'America/New_York';
      const settings = {
        'system_settings': {
          id: 123,
          key: 'system_settings',
          name: 'System Settings',
          value: { time_zone: 'UTC' }
        }
      };

      await UiSettingsFormUtils.saveTimeZoneSetting(tzValue, settings);

      expect(SettingsUtils.updateSetting).toHaveBeenCalledTimes(1);
      expect(SettingsUtils.updateSetting).toHaveBeenCalledWith({
        id: 123,
        key: 'system_settings',
        name: 'System Settings',
        value: { time_zone: 'America/New_York' }
      });
      expect(SettingsUtils.createSetting).not.toHaveBeenCalled();
    });

    it('should create new setting when existing setting has no id', async () => {
      const tzValue = 'Europe/London';
      const settings = {
        'system_settings': {
          key: 'system_settings',
          name: 'System Settings',
          value: { time_zone: 'UTC' }
        }
      };

      await UiSettingsFormUtils.saveTimeZoneSetting(tzValue, settings);

      expect(SettingsUtils.createSetting).toHaveBeenCalledTimes(1);
      expect(SettingsUtils.createSetting).toHaveBeenCalledWith({
        key: 'system_settings',
        name: 'System Settings',
        value: { time_zone: 'Europe/London' }
      });
      expect(SettingsUtils.updateSetting).not.toHaveBeenCalled();
    });

    it('should create new setting when system_settings does not exist', async () => {
      const tzValue = 'Asia/Tokyo';
      const settings = {};

      await UiSettingsFormUtils.saveTimeZoneSetting(tzValue, settings);

      expect(SettingsUtils.createSetting).toHaveBeenCalledTimes(1);
      expect(SettingsUtils.createSetting).toHaveBeenCalledWith({
        key: 'system_settings',
        name: 'System Settings',
        value: { time_zone: 'Asia/Tokyo' }
      });
      expect(SettingsUtils.updateSetting).not.toHaveBeenCalled();
    });

    it('should create new setting when system_settings is null', async () => {
      const tzValue = 'Pacific/Auckland';
      const settings = {
        'system_settings': null
      };

      await UiSettingsFormUtils.saveTimeZoneSetting(tzValue, settings);

      expect(SettingsUtils.createSetting).toHaveBeenCalledTimes(1);
      expect(SettingsUtils.createSetting).toHaveBeenCalledWith({
        key: 'system_settings',
        name: 'System Settings',
        value: { time_zone: 'Pacific/Auckland' }
      });
      expect(SettingsUtils.updateSetting).not.toHaveBeenCalled();
    });

    it('should create new setting when id is undefined', async () => {
      const tzValue = 'America/Los_Angeles';
      const settings = {
        'system_settings': {
          id: undefined,
          key: 'system_settings',
          value: { time_zone: 'UTC' }
        }
      };

      await UiSettingsFormUtils.saveTimeZoneSetting(tzValue, settings);

      expect(SettingsUtils.createSetting).toHaveBeenCalledTimes(1);
      expect(SettingsUtils.updateSetting).not.toHaveBeenCalled();
    });

    it('should preserve existing properties when updating', async () => {
      const tzValue = 'UTC';
      const settings = {
        'system_settings': {
          id: 456,
          key: 'system_settings',
          name: 'System Settings',
          value: { time_zone: 'America/New_York', some_other_setting: 'value' },
          extraProp: 'should be preserved'
        }
      };

      await UiSettingsFormUtils.saveTimeZoneSetting(tzValue, settings);

      expect(SettingsUtils.updateSetting).toHaveBeenCalledWith({
        id: 456,
        key: 'system_settings',
        name: 'System Settings',
        value: { time_zone: 'UTC', some_other_setting: 'value' },
        extraProp: 'should be preserved'
      });
    });

    it('should handle empty string timezone value', async () => {
      const tzValue = '';
      const settings = {
        'system_settings': {
          id: 789,
          key: 'system_settings',
          name: 'System Settings',
          value: { time_zone: 'America/New_York' }
        }
      };

      await UiSettingsFormUtils.saveTimeZoneSetting(tzValue, settings);

      expect(SettingsUtils.updateSetting).toHaveBeenCalledWith({
        id: 789,
        key: 'system_settings',
        name: 'System Settings',
        value: { time_zone: '' }
      });
    });
  });
});
