import { describe, it, expect, vi, beforeEach } from 'vitest';
import * as ProxySettingsFormUtils from '../ProxySettingsFormUtils';
import * as constants from '../../../../constants.js';

vi.mock('../../../../constants.js', () => ({
  PROXY_SETTINGS_OPTIONS: {},
}));

describe('ProxySettingsFormUtils', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('getProxySettingsFormInitialValues', () => {
    it('should return initial values for all proxy settings options', () => {
      vi.mocked(constants).PROXY_SETTINGS_OPTIONS = {
        'proxy-buffering-timeout': 'Buffering Timeout',
        'proxy-buffering-speed': 'Buffering Speed',
        'proxy-redis-chunk-ttl': 'Redis Chunk TTL',
      };

      const result = ProxySettingsFormUtils.getProxySettingsFormInitialValues();

      expect(result).toEqual({
        'proxy-buffering-timeout': '',
        'proxy-buffering-speed': '',
        'proxy-redis-chunk-ttl': '',
      });
    });

    it('should return empty object when PROXY_SETTINGS_OPTIONS is empty', () => {
      vi.mocked(constants).PROXY_SETTINGS_OPTIONS = {};

      const result = ProxySettingsFormUtils.getProxySettingsFormInitialValues();

      expect(result).toEqual({});
    });

    it('should return a new object each time', () => {
      vi.mocked(constants).PROXY_SETTINGS_OPTIONS = {
        'proxy-setting': 'Proxy Setting',
      };

      const result1 =
        ProxySettingsFormUtils.getProxySettingsFormInitialValues();
      const result2 =
        ProxySettingsFormUtils.getProxySettingsFormInitialValues();

      expect(result1).toEqual(result2);
      expect(result1).not.toBe(result2);
    });
  });

  describe('getProxySettingDefaults', () => {
    it('should return default proxy settings', () => {
      const result = ProxySettingsFormUtils.getProxySettingDefaults();

      expect(result).toEqual({
        buffering_timeout: 15,
        buffering_speed: 1.0,
        redis_chunk_ttl: 60,
        channel_shutdown_delay: 0,
        channel_init_grace_period: 5,
      });
    });

    it('should return a new object each time', () => {
      const result1 = ProxySettingsFormUtils.getProxySettingDefaults();
      const result2 = ProxySettingsFormUtils.getProxySettingDefaults();

      expect(result1).toEqual(result2);
      expect(result1).not.toBe(result2);
    });

    it('should have correct default types', () => {
      const result = ProxySettingsFormUtils.getProxySettingDefaults();

      expect(typeof result.buffering_timeout).toBe('number');
      expect(typeof result.buffering_speed).toBe('number');
      expect(typeof result.redis_chunk_ttl).toBe('number');
      expect(typeof result.channel_shutdown_delay).toBe('number');
      expect(typeof result.channel_init_grace_period).toBe('number');
    });
  });
});
