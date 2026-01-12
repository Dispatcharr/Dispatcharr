import { describe, it, expect, vi, beforeEach } from 'vitest';
import * as StreamSettingsFormUtils from '../StreamSettingsFormUtils';
import { isNotEmpty } from '@mantine/form';

vi.mock('@mantine/form', () => ({
  isNotEmpty: vi.fn((message) => message)
}));

describe('StreamSettingsFormUtils', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('getStreamSettingsFormInitialValues', () => {
    it('should return initial values with correct defaults', () => {
      const result = StreamSettingsFormUtils.getStreamSettingsFormInitialValues();

      expect(result).toEqual({
        'default-user-agent': '',
        'default-stream-profile': '',
        'preferred-region': '',
        'auto-import-mapped-files': true,
        'm3u-hash-key': []
      });
    });

    it('should return boolean true for auto-import-mapped-files', () => {
      const result = StreamSettingsFormUtils.getStreamSettingsFormInitialValues();

      expect(result['auto-import-mapped-files']).toBe(true);
      expect(typeof result['auto-import-mapped-files']).toBe('boolean');
    });

    it('should return empty array for m3u-hash-key', () => {
      const result = StreamSettingsFormUtils.getStreamSettingsFormInitialValues();

      expect(result['m3u-hash-key']).toEqual([]);
      expect(Array.isArray(result['m3u-hash-key'])).toBe(true);
    });

    it('should return a new object each time', () => {
      const result1 = StreamSettingsFormUtils.getStreamSettingsFormInitialValues();
      const result2 = StreamSettingsFormUtils.getStreamSettingsFormInitialValues();

      expect(result1).toEqual(result2);
      expect(result1).not.toBe(result2);
    });

    it('should return a new array instance for m3u-hash-key each time', () => {
      const result1 = StreamSettingsFormUtils.getStreamSettingsFormInitialValues();
      const result2 = StreamSettingsFormUtils.getStreamSettingsFormInitialValues();

      expect(result1['m3u-hash-key']).not.toBe(result2['m3u-hash-key']);
    });
  });

  describe('getStreamSettingsFormValidation', () => {
    it('should return validation functions for required fields', () => {
      const result = StreamSettingsFormUtils.getStreamSettingsFormValidation();

      expect(Object.keys(result)).toEqual([
        'default-user-agent',
        'default-stream-profile',
        'preferred-region'
      ]);
    });

    it('should use isNotEmpty validator for default-user-agent', () => {
      StreamSettingsFormUtils.getStreamSettingsFormValidation();

      expect(isNotEmpty).toHaveBeenCalledWith('Select a user agent');
    });

    it('should use isNotEmpty validator for default-stream-profile', () => {
      StreamSettingsFormUtils.getStreamSettingsFormValidation();

      expect(isNotEmpty).toHaveBeenCalledWith('Select a stream profile');
    });

    it('should use isNotEmpty validator for preferred-region', () => {
      StreamSettingsFormUtils.getStreamSettingsFormValidation();

      expect(isNotEmpty).toHaveBeenCalledWith('Select a region');
    });

    it('should not include validation for auto-import-mapped-files', () => {
      const result = StreamSettingsFormUtils.getStreamSettingsFormValidation();

      expect(result).not.toHaveProperty('auto-import-mapped-files');
    });

    it('should not include validation for m3u-hash-key', () => {
      const result = StreamSettingsFormUtils.getStreamSettingsFormValidation();

      expect(result).not.toHaveProperty('m3u-hash-key');
    });

    it('should return correct validation error messages', () => {
      const result = StreamSettingsFormUtils.getStreamSettingsFormValidation();

      expect(result['default-user-agent']).toBe('Select a user agent');
      expect(result['default-stream-profile']).toBe('Select a stream profile');
      expect(result['preferred-region']).toBe('Select a region');
    });
  });
});
