import { describe, it, expect, vi, beforeEach } from 'vitest';
import * as DvrSettingsFormUtils from '../DvrSettingsFormUtils';
import API from '../../../../api.js';

vi.mock('../../../../api.js');

describe('DvrSettingsFormUtils', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('getComskipConfig', () => {
    it('should call API.getComskipConfig and return result', async () => {
      const mockConfig = {
        enabled: true,
        custom_path: '/path/to/comskip'
      };
      API.getComskipConfig.mockResolvedValue(mockConfig);

      const result = await DvrSettingsFormUtils.getComskipConfig();

      expect(API.getComskipConfig).toHaveBeenCalledWith();
      expect(result).toEqual(mockConfig);
    });

    it('should handle API errors', async () => {
      const error = new Error('API Error');
      API.getComskipConfig.mockRejectedValue(error);

      await expect(DvrSettingsFormUtils.getComskipConfig()).rejects.toThrow('API Error');
    });
  });

  describe('uploadComskipIni', () => {
    it('should call API.uploadComskipIni with file and return result', async () => {
      const mockFile = new File(['content'], 'comskip.ini', { type: 'text/plain' });
      const mockResponse = { success: true };
      API.uploadComskipIni.mockResolvedValue(mockResponse);

      const result = await DvrSettingsFormUtils.uploadComskipIni(mockFile);

      expect(API.uploadComskipIni).toHaveBeenCalledWith(mockFile);
      expect(result).toEqual(mockResponse);
    });

    it('should handle API errors', async () => {
      const mockFile = new File(['content'], 'comskip.ini', { type: 'text/plain' });
      const error = new Error('Upload failed');
      API.uploadComskipIni.mockRejectedValue(error);

      await expect(DvrSettingsFormUtils.uploadComskipIni(mockFile)).rejects.toThrow('Upload failed');
    });
  });

  describe('getDvrSettingsFormInitialValues', () => {
    it('should return initial values with all DVR settings', () => {
      const result = DvrSettingsFormUtils.getDvrSettingsFormInitialValues();

      expect(result).toEqual({
        'tv_template': '',
        'movie_template': '',
        'tv_fallback_template': '',
        'movie_fallback_template': '',
        'comskip_enabled': false,
        'comskip_custom_path': '',
        'pre_offset_minutes': 0,
        'post_offset_minutes': 0,
      });
    });

    it('should return a new object each time', () => {
      const result1 = DvrSettingsFormUtils.getDvrSettingsFormInitialValues();
      const result2 = DvrSettingsFormUtils.getDvrSettingsFormInitialValues();

      expect(result1).toEqual(result2);
      expect(result1).not.toBe(result2);
    });

    it('should have correct default types', () => {
      const result = DvrSettingsFormUtils.getDvrSettingsFormInitialValues();

      expect(typeof result['tv_template']).toBe('string');
      expect(typeof result['movie_template']).toBe('string');
      expect(typeof result['tv_fallback_template']).toBe('string');
      expect(typeof result['movie_fallback_template']).toBe('string');
      expect(typeof result['comskip_enabled']).toBe('boolean');
      expect(typeof result['comskip_custom_path']).toBe('string');
      expect(typeof result['pre_offset_minutes']).toBe('number');
      expect(typeof result['post_offset_minutes']).toBe('number');
    });
  });
});
