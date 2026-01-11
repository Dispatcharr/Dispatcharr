import { describe, it, expect } from 'vitest';
import * as SystemSettingsFormUtils from '../SystemSettingsFormUtils';

describe('SystemSettingsFormUtils', () => {
  describe('getSystemSettingsFormInitialValues', () => {
    it('should return initial values with correct defaults', () => {
      const result = SystemSettingsFormUtils.getSystemSettingsFormInitialValues();

      expect(result).toEqual({
        'max-system-events': 100
      });
    });

    it('should return number value for max-system-events', () => {
      const result = SystemSettingsFormUtils.getSystemSettingsFormInitialValues();

      expect(result['max-system-events']).toBe(100);
      expect(typeof result['max-system-events']).toBe('number');
    });

    it('should return a new object each time', () => {
      const result1 = SystemSettingsFormUtils.getSystemSettingsFormInitialValues();
      const result2 = SystemSettingsFormUtils.getSystemSettingsFormInitialValues();

      expect(result1).toEqual(result2);
      expect(result1).not.toBe(result2);
    });

    it('should have max-system-events property', () => {
      const result = SystemSettingsFormUtils.getSystemSettingsFormInitialValues();

      expect(result).toHaveProperty('max-system-events');
    });
  });
});
