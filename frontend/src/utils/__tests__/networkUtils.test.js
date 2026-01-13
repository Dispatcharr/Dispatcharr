import { describe, it, expect } from 'vitest';
import * as networkUtils from '../networkUtils';

describe('networkUtils', () => {
  describe('IPV4_CIDR_REGEX', () => {
    it('should match valid IPv4 CIDR notation', () => {
      expect(networkUtils.IPV4_CIDR_REGEX.test('192.168.1.0/24')).toBe(true);
      expect(networkUtils.IPV4_CIDR_REGEX.test('10.0.0.0/8')).toBe(true);
      expect(networkUtils.IPV4_CIDR_REGEX.test('172.16.0.0/12')).toBe(true);
      expect(networkUtils.IPV4_CIDR_REGEX.test('0.0.0.0/0')).toBe(true);
      expect(networkUtils.IPV4_CIDR_REGEX.test('255.255.255.255/32')).toBe(true);
    });

    it('should not match invalid IPv4 CIDR notation', () => {
      expect(networkUtils.IPV4_CIDR_REGEX.test('192.168.1.0')).toBe(false);
      expect(networkUtils.IPV4_CIDR_REGEX.test('192.168.1.0/33')).toBe(false);
      expect(networkUtils.IPV4_CIDR_REGEX.test('256.168.1.0/24')).toBe(false);
      expect(networkUtils.IPV4_CIDR_REGEX.test('192.168/24')).toBe(false);
      expect(networkUtils.IPV4_CIDR_REGEX.test('invalid')).toBe(false);
    });

    it('should not match IPv6 addresses', () => {
      expect(networkUtils.IPV4_CIDR_REGEX.test('2001:db8::/32')).toBe(false);
    });
  });

  describe('IPV6_CIDR_REGEX', () => {
    it('should match valid IPv6 CIDR notation', () => {
      expect(networkUtils.IPV6_CIDR_REGEX.test('2001:db8::/32')).toBe(true);
      expect(networkUtils.IPV6_CIDR_REGEX.test('fe80::/10')).toBe(true);
      expect(networkUtils.IPV6_CIDR_REGEX.test('::/0')).toBe(true);
      expect(networkUtils.IPV6_CIDR_REGEX.test('2001:0db8:85a3:0000:0000:8a2e:0370:7334/64')).toBe(true);
    });

    it('should match compressed IPv6 CIDR notation', () => {
      expect(networkUtils.IPV6_CIDR_REGEX.test('2001:db8::1/128')).toBe(true);
      expect(networkUtils.IPV6_CIDR_REGEX.test('::1/128')).toBe(true);
    });

    it('should match IPv6 with embedded IPv4', () => {
      expect(networkUtils.IPV6_CIDR_REGEX.test('::ffff:192.168.1.1/96')).toBe(true);
    });

    it('should not match invalid IPv6 CIDR notation', () => {
      expect(networkUtils.IPV6_CIDR_REGEX.test('2001:db8::')).toBe(false);
      expect(networkUtils.IPV6_CIDR_REGEX.test('2001:db8::/129')).toBe(false);
      expect(networkUtils.IPV6_CIDR_REGEX.test('invalid/64')).toBe(false);
    });

    it('should not match IPv4 addresses', () => {
      expect(networkUtils.IPV6_CIDR_REGEX.test('192.168.1.0/24')).toBe(false);
    });
  });

  describe('formatBytes', () => {
    it('should return "0 Bytes" for zero bytes', () => {
      expect(networkUtils.formatBytes(0)).toBe('0 Bytes');
    });

    it('should format bytes correctly', () => {
      expect(networkUtils.formatBytes(100)).toBe('100.00 Bytes');
      expect(networkUtils.formatBytes(500)).toBe('500.00 Bytes');
    });

    it('should format kilobytes correctly', () => {
      expect(networkUtils.formatBytes(1024)).toBe('1.00 KB');
      expect(networkUtils.formatBytes(2048)).toBe('2.00 KB');
      expect(networkUtils.formatBytes(1536)).toBe('1.50 KB');
    });

    it('should format megabytes correctly', () => {
      expect(networkUtils.formatBytes(1048576)).toBe('1.00 MB');
      expect(networkUtils.formatBytes(2097152)).toBe('2.00 MB');
      expect(networkUtils.formatBytes(5242880)).toBe('5.00 MB');
    });

    it('should format gigabytes correctly', () => {
      expect(networkUtils.formatBytes(1073741824)).toBe('1.00 GB');
      expect(networkUtils.formatBytes(2147483648)).toBe('2.00 GB');
    });

    it('should format terabytes correctly', () => {
      expect(networkUtils.formatBytes(1099511627776)).toBe('1.00 TB');
    });

    it('should format large numbers', () => {
      expect(networkUtils.formatBytes(1125899906842624)).toBe('1.00 PB');
    });

    it('should handle decimal values', () => {
      const result = networkUtils.formatBytes(1536);
      expect(result).toMatch(/1\.50 KB/);
    });

    it('should always show two decimal places', () => {
      const result = networkUtils.formatBytes(1024);
      expect(result).toBe('1.00 KB');
    });
  });

  describe('formatSpeed', () => {
    it('should return "0 Bytes" for zero speed', () => {
      expect(networkUtils.formatSpeed(0)).toBe('0 Bytes');
    });

    it('should format bits per second correctly', () => {
      expect(networkUtils.formatSpeed(100)).toBe('100.00 bps');
      expect(networkUtils.formatSpeed(500)).toBe('500.00 bps');
    });

    it('should format kilobits per second correctly', () => {
      expect(networkUtils.formatSpeed(1024)).toBe('1.00 Kbps');
      expect(networkUtils.formatSpeed(2048)).toBe('2.00 Kbps');
      expect(networkUtils.formatSpeed(1536)).toBe('1.50 Kbps');
    });

    it('should format megabits per second correctly', () => {
      expect(networkUtils.formatSpeed(1048576)).toBe('1.00 Mbps');
      expect(networkUtils.formatSpeed(2097152)).toBe('2.00 Mbps');
      expect(networkUtils.formatSpeed(10485760)).toBe('10.00 Mbps');
    });

    it('should format gigabits per second correctly', () => {
      expect(networkUtils.formatSpeed(1073741824)).toBe('1.00 Gbps');
      expect(networkUtils.formatSpeed(2147483648)).toBe('2.00 Gbps');
    });

    it('should handle decimal values', () => {
      const result = networkUtils.formatSpeed(1536);
      expect(result).toMatch(/1\.50 Kbps/);
    });

    it('should always show two decimal places', () => {
      const result = networkUtils.formatSpeed(1024);
      expect(result).toBe('1.00 Kbps');
    });

    it('should use speed units not byte units', () => {
      const result = networkUtils.formatSpeed(1024);
      expect(result).not.toContain('KB');
      expect(result).toContain('Kbps');
    });
  });
});
