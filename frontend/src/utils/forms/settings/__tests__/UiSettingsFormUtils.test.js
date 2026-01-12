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
        'system-time-zone': {
          id: 123,
          key: 'system-time-zone',
          name: 'System Time Zone',
          value: 'UTC'
        }
      };

      await UiSettingsFormUtils.saveTimeZoneSetting(tzValue, settings);

      expect(SettingsUtils.updateSetting).toHaveBeenCalledTimes(1);
      expect(SettingsUtils.updateSetting).toHaveBeenCalledWith({
        id: 123,
        key: 'system-time-zone',
        name: 'System Time Zone',
        value: 'America/New_York'
      });
      expect(SettingsUtils.createSetting).not.toHaveBeenCalled();
    });

    it('should create new setting when existing setting has no id', async () => {
      const tzValue = 'Europe/London';
      const settings = {
        'system-time-zone': {
          key: 'system-time-zone',
          name: 'System Time Zone',
          value: 'UTC'
        }
      };

      await UiSettingsFormUtils.saveTimeZoneSetting(tzValue, settings);

      expect(SettingsUtils.createSetting).toHaveBeenCalledTimes(1);
      expect(SettingsUtils.createSetting).toHaveBeenCalledWith({
        key: 'system-time-zone',
        name: 'System Time Zone',
        value: 'Europe/London'
      });
      expect(SettingsUtils.updateSetting).not.toHaveBeenCalled();
    });

    it('should create new setting when system-time-zone does not exist', async () => {
      const tzValue = 'Asia/Tokyo';
      const settings = {};

      await UiSettingsFormUtils.saveTimeZoneSetting(tzValue, settings);

      expect(SettingsUtils.createSetting).toHaveBeenCalledTimes(1);
      expect(SettingsUtils.createSetting).toHaveBeenCalledWith({
        key: 'system-time-zone',
        name: 'System Time Zone',
        value: 'Asia/Tokyo'
      });
      expect(SettingsUtils.updateSetting).not.toHaveBeenCalled();
    });

    it('should create new setting when system-time-zone is null', async () => {
      const tzValue = 'Pacific/Auckland';
      const settings = {
        'system-time-zone': null
      };

      await UiSettingsFormUtils.saveTimeZoneSetting(tzValue, settings);

      expect(SettingsUtils.createSetting).toHaveBeenCalledTimes(1);
      expect(SettingsUtils.createSetting).toHaveBeenCalledWith({
        key: 'system-time-zone',
        name: 'System Time Zone',
        value: 'Pacific/Auckland'
      });
      expect(SettingsUtils.updateSetting).not.toHaveBeenCalled();
    });

    it('should create new setting when id is undefined', async () => {
      const tzValue = 'America/Los_Angeles';
      const settings = {
        'system-time-zone': {
          id: undefined,
          key: 'system-time-zone',
          value: 'UTC'
        }
      };

      await UiSettingsFormUtils.saveTimeZoneSetting(tzValue, settings);

      expect(SettingsUtils.createSetting).toHaveBeenCalledTimes(1);
      expect(SettingsUtils.updateSetting).not.toHaveBeenCalled();
    });

    it('should preserve existing properties when updating', async () => {
      const tzValue = 'UTC';
      const settings = {
        'system-time-zone': {
          id: 456,
          key: 'system-time-zone',
          name: 'System Time Zone',
          value: 'America/New_York',
          extraProp: 'should be preserved'
        }
      };

      await UiSettingsFormUtils.saveTimeZoneSetting(tzValue, settings);

      expect(SettingsUtils.updateSetting).toHaveBeenCalledWith({
        id: 456,
        key: 'system-time-zone',
        name: 'System Time Zone',
        value: 'UTC',
        extraProp: 'should be preserved'
      });
    });

    it('should handle empty string timezone value', async () => {
      const tzValue = '';
      const settings = {
        'system-time-zone': {
          id: 789
        }
      };

      await UiSettingsFormUtils.saveTimeZoneSetting(tzValue, settings);

      expect(SettingsUtils.updateSetting).toHaveBeenCalledWith({
        id: 789,
        value: ''
      });
    });
  });
});
