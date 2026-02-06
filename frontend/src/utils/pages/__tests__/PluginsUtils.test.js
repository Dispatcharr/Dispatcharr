import { describe, it, expect, vi, beforeEach } from 'vitest';
import * as PluginsUtils from '../PluginsUtils';
import API from '../../../api.js';

vi.mock('../../../api.js', () => ({
  default: {
    updatePluginSettings: vi.fn(),
    runPluginAction: vi.fn(),
    setPluginEnabled: vi.fn(),
    importPlugin: vi.fn(),
    reloadPlugins: vi.fn(),
    deletePlugin: vi.fn()
  }
}));

describe('PluginsUtils', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('updatePluginSettings', () => {
    it('should call API updatePluginSettings with key and settings', async () => {
      const key = 'test-plugin';
      const settings = { option1: 'value1', option2: true };

      await PluginsUtils.updatePluginSettings(key, settings);

      expect(API.updatePluginSettings).toHaveBeenCalledWith(key, settings);
      expect(API.updatePluginSettings).toHaveBeenCalledTimes(1);
    });

    it('should return API response', async () => {
      const key = 'test-plugin';
      const settings = { enabled: true };
      const mockResponse = { success: true };

      API.updatePluginSettings.mockResolvedValue(mockResponse);

      const result = await PluginsUtils.updatePluginSettings(key, settings);

      expect(result).toEqual(mockResponse);
    });

    it('should handle empty settings object', async () => {
      const key = 'test-plugin';
      const settings = {};

      await PluginsUtils.updatePluginSettings(key, settings);

      expect(API.updatePluginSettings).toHaveBeenCalledWith(key, {});
    });

    it('should handle null settings', async () => {
      const key = 'test-plugin';
      const settings = null;

      await PluginsUtils.updatePluginSettings(key, settings);

      expect(API.updatePluginSettings).toHaveBeenCalledWith(key, null);
    });

    it('should propagate API errors', async () => {
      const key = 'test-plugin';
      const settings = { enabled: true };
      const error = new Error('API error');

      API.updatePluginSettings.mockRejectedValue(error);

      await expect(PluginsUtils.updatePluginSettings(key, settings)).rejects.toThrow('API error');
    });
  });

  describe('runPluginAction', () => {
    it('should call API runPluginAction with key and actionId', async () => {
      const key = 'test-plugin';
      const actionId = 'refresh-data';

      await PluginsUtils.runPluginAction(key, actionId);

      expect(API.runPluginAction).toHaveBeenCalledWith(key, actionId);
      expect(API.runPluginAction).toHaveBeenCalledTimes(1);
    });

    it('should return API response', async () => {
      const key = 'test-plugin';
      const actionId = 'sync';
      const mockResponse = { status: 'completed' };

      API.runPluginAction.mockResolvedValue(mockResponse);

      const result = await PluginsUtils.runPluginAction(key, actionId);

      expect(result).toEqual(mockResponse);
    });

    it('should handle numeric actionId', async () => {
      const key = 'test-plugin';
      const actionId = 123;

      await PluginsUtils.runPluginAction(key, actionId);

      expect(API.runPluginAction).toHaveBeenCalledWith(key, 123);
    });

    it('should propagate API errors', async () => {
      const key = 'test-plugin';
      const actionId = 'invalid-action';
      const error = new Error('Action not found');

      API.runPluginAction.mockRejectedValue(error);

      await expect(PluginsUtils.runPluginAction(key, actionId)).rejects.toThrow('Action not found');
    });
  });

  describe('reloadPlugins', () => {
    it('should call API reloadPlugins', async () => {
      await PluginsUtils.reloadPlugins();

      expect(API.reloadPlugins).toHaveBeenCalledTimes(1);
    });

    it('should return API response', async () => {
      const mockResponse = { success: true };
      API.reloadPlugins.mockResolvedValue(mockResponse);

      const result = await PluginsUtils.reloadPlugins();

      expect(result).toEqual(mockResponse);
    });
  });

  describe('setPluginEnabled', () => {
    it('should call API setPluginEnabled with key and next value', async () => {
      const key = 'test-plugin';
      const next = true;

      await PluginsUtils.setPluginEnabled(key, next);

      expect(API.setPluginEnabled).toHaveBeenCalledWith(key, true);
      expect(API.setPluginEnabled).toHaveBeenCalledTimes(1);
    });

    it('should handle false value', async () => {
      const key = 'test-plugin';
      const next = false;

      await PluginsUtils.setPluginEnabled(key, next);

      expect(API.setPluginEnabled).toHaveBeenCalledWith(key, false);
    });

    it('should return API response', async () => {
      const key = 'test-plugin';
      const next = true;
      const mockResponse = { enabled: true };

      API.setPluginEnabled.mockResolvedValue(mockResponse);

      const result = await PluginsUtils.setPluginEnabled(key, next);

      expect(result).toEqual(mockResponse);
    });

    it('should handle truthy values', async () => {
      const key = 'test-plugin';
      const next = 'yes';

      await PluginsUtils.setPluginEnabled(key, next);

      expect(API.setPluginEnabled).toHaveBeenCalledWith(key, 'yes');
    });

    it('should handle falsy values', async () => {
      const key = 'test-plugin';
      const next = 0;

      await PluginsUtils.setPluginEnabled(key, next);

      expect(API.setPluginEnabled).toHaveBeenCalledWith(key, 0);
    });

    it('should propagate API errors', async () => {
      const key = 'test-plugin';
      const next = true;
      const error = new Error('Plugin not found');

      API.setPluginEnabled.mockRejectedValue(error);

      await expect(PluginsUtils.setPluginEnabled(key, next)).rejects.toThrow('Plugin not found');
    });
  });

  describe('importPlugin', () => {
    it('should call API importPlugin with importFile', async () => {
      const importFile = new File(['content'], 'plugin.zip', { type: 'application/zip' });

      await PluginsUtils.importPlugin(importFile);

      expect(API.importPlugin).toHaveBeenCalledWith(importFile);
      expect(API.importPlugin).toHaveBeenCalledTimes(1);
    });

    it('should return API response', async () => {
      const importFile = new File(['content'], 'plugin.zip', { type: 'application/zip' });
      const mockResponse = { key: 'imported-plugin', success: true };

      API.importPlugin.mockResolvedValue(mockResponse);

      const result = await PluginsUtils.importPlugin(importFile);

      expect(result).toEqual(mockResponse);
    });

    it('should handle string file path', async () => {
      const importFile = '/path/to/plugin.zip';

      await PluginsUtils.importPlugin(importFile);

      expect(API.importPlugin).toHaveBeenCalledWith(importFile);
    });

    it('should handle FormData', async () => {
      const formData = new FormData();
      formData.append('file', new File(['content'], 'plugin.zip'));

      await PluginsUtils.importPlugin(formData);

      expect(API.importPlugin).toHaveBeenCalledWith(formData);
    });

    it('should propagate API errors', async () => {
      const importFile = new File(['content'], 'plugin.zip', { type: 'application/zip' });
      const error = new Error('Invalid plugin format');

      API.importPlugin.mockRejectedValue(error);

      await expect(PluginsUtils.importPlugin(importFile)).rejects.toThrow('Invalid plugin format');
    });
  });

  describe('deletePluginByKey', () => {
    it('should call API deletePlugin with key', () => {
      const key = 'test-plugin';

      PluginsUtils.deletePluginByKey(key);

      expect(API.deletePlugin).toHaveBeenCalledWith(key);
      expect(API.deletePlugin).toHaveBeenCalledTimes(1);
    });

    it('should return API response', () => {
      const key = 'test-plugin';
      const mockResponse = { success: true };

      API.deletePlugin.mockReturnValue(mockResponse);

      const result = PluginsUtils.deletePluginByKey(key);

      expect(result).toEqual(mockResponse);
    });

    it('should handle numeric key', () => {
      const key = 123;

      PluginsUtils.deletePluginByKey(key);

      expect(API.deletePlugin).toHaveBeenCalledWith(123);
    });

    it('should handle empty string key', () => {
      const key = '';

      PluginsUtils.deletePluginByKey(key);

      expect(API.deletePlugin).toHaveBeenCalledWith('');
    });

    it('should handle null key', () => {
      const key = null;

      PluginsUtils.deletePluginByKey(key);

      expect(API.deletePlugin).toHaveBeenCalledWith(null);
    });
  });
});
