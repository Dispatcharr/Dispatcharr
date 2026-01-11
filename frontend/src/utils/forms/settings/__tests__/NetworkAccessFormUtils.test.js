import { describe, it, expect, vi, beforeEach } from 'vitest';
import * as NetworkAccessFormUtils from '../NetworkAccessFormUtils';
import * as constants from '../../../../constants.js';

vi.mock('../../../../constants.js', () => ({
  NETWORK_ACCESS_OPTIONS: {}
}));

vi.mock('../../../networkUtils.js', () => ({
  IPV4_CIDR_REGEX: /^(\d{1,3}\.){3}\d{1,3}\/\d{1,2}$/,
  IPV6_CIDR_REGEX: /^([0-9a-fA-F:]+)\/\d{1,3}$/
}));

describe('NetworkAccessFormUtils', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('getNetworkAccessFormInitialValues', () => {
    it('should return initial values for all network access options', () => {
      vi.mocked(constants).NETWORK_ACCESS_OPTIONS = {
        'network-access-admin': 'Admin Access',
        'network-access-api': 'API Access',
        'network-access-streaming': 'Streaming Access'
      };

      const result = NetworkAccessFormUtils.getNetworkAccessFormInitialValues();

      expect(result).toEqual({
        'network-access-admin': '0.0.0.0/0,::/0',
        'network-access-api': '0.0.0.0/0,::/0',
        'network-access-streaming': '0.0.0.0/0,::/0'
      });
    });

    it('should return empty object when NETWORK_ACCESS_OPTIONS is empty', () => {
      vi.mocked(constants).NETWORK_ACCESS_OPTIONS = {};

      const result = NetworkAccessFormUtils.getNetworkAccessFormInitialValues();

      expect(result).toEqual({});
    });

    it('should return a new object each time', () => {
      vi.mocked(constants).NETWORK_ACCESS_OPTIONS = {
        'network-access-admin': 'Admin Access'
      };

      const result1 = NetworkAccessFormUtils.getNetworkAccessFormInitialValues();
      const result2 = NetworkAccessFormUtils.getNetworkAccessFormInitialValues();

      expect(result1).toEqual(result2);
      expect(result1).not.toBe(result2);
    });
  });

  describe('getNetworkAccessFormValidation', () => {
    beforeEach(() => {
      vi.mocked(constants).NETWORK_ACCESS_OPTIONS = {
        'network-access-admin': 'Admin Access',
        'network-access-api': 'API Access'
      };
    });

    it('should return validation functions for all network access options', () => {
      const result = NetworkAccessFormUtils.getNetworkAccessFormValidation();

      expect(Object.keys(result)).toEqual(['network-access-admin', 'network-access-api']);
      expect(typeof result['network-access-admin']).toBe('function');
      expect(typeof result['network-access-api']).toBe('function');
    });

    it('should validate valid IPv4 CIDR ranges', () => {
      const validation = NetworkAccessFormUtils.getNetworkAccessFormValidation();
      const validator = validation['network-access-admin'];

      expect(validator('192.168.1.0/24')).toBeNull();
      expect(validator('10.0.0.0/8')).toBeNull();
      expect(validator('0.0.0.0/0')).toBeNull();
    });

    it('should validate valid IPv6 CIDR ranges', () => {
      const validation = NetworkAccessFormUtils.getNetworkAccessFormValidation();
      const validator = validation['network-access-admin'];

      expect(validator('2001:db8::/32')).toBeNull();
      expect(validator('::/0')).toBeNull();
    });

    it('should validate multiple CIDR ranges separated by commas', () => {
      const validation = NetworkAccessFormUtils.getNetworkAccessFormValidation();
      const validator = validation['network-access-admin'];

      expect(validator('192.168.1.0/24,10.0.0.0/8')).toBeNull();
      expect(validator('0.0.0.0/0,::/0')).toBeNull();
      expect(validator('192.168.1.0/24,2001:db8::/32')).toBeNull();
    });

    it('should return error for invalid IPv4 CIDR ranges', () => {
      const validation = NetworkAccessFormUtils.getNetworkAccessFormValidation();
      const validator = validation['network-access-admin'];

      expect(validator('192.168.1.256/24')).toBe('Invalid CIDR range');
      expect(validator('invalid')).toBe('Invalid CIDR range');
      expect(validator('192.168.1.0/33')).toBe('Invalid CIDR range');
    });

    it('should return error when any CIDR in comma-separated list is invalid', () => {
      const validation = NetworkAccessFormUtils.getNetworkAccessFormValidation();
      const validator = validation['network-access-admin'];

      expect(validator('192.168.1.0/24,invalid')).toBe('Invalid CIDR range');
      expect(validator('invalid,192.168.1.0/24')).toBe('Invalid CIDR range');
      expect(validator('192.168.1.0/24,10.0.0.0/8,invalid')).toBe('Invalid CIDR range');
    });

    it('should handle empty strings', () => {
      const validation = NetworkAccessFormUtils.getNetworkAccessFormValidation();
      const validator = validation['network-access-admin'];

      expect(validator('')).toBe('Invalid CIDR range');
    });

    it('should return empty object when NETWORK_ACCESS_OPTIONS is empty', () => {
      vi.mocked(constants).NETWORK_ACCESS_OPTIONS = {};

      const result = NetworkAccessFormUtils.getNetworkAccessFormValidation();

      expect(result).toEqual({});
    });
  });
});
