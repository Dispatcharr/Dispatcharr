import { describe, it, expect } from 'vitest';
import { isSafeHttpUrl } from '../url';

describe('isSafeHttpUrl', () => {
  it('accepts plain http(s) URLs', () => {
    expect(isSafeHttpUrl('https://example.com')).toBe(true);
    expect(isSafeHttpUrl('http://example.com')).toBe(true);
  });

  it('accepts mixed/upper-case schemes', () => {
    expect(isSafeHttpUrl('HTTPS://example.com')).toBe(true);
    expect(isSafeHttpUrl('HtTp://example.com')).toBe(true);
  });

  it('rejects javascript: URIs', () => {
    expect(isSafeHttpUrl('javascript:alert(1)')).toBe(false);
  });

  it('rejects data: URIs', () => {
    expect(isSafeHttpUrl('data:text/html,<script>alert(1)</script>')).toBe(
      false
    );
  });

  it('rejects protocol-relative URLs', () => {
    expect(isSafeHttpUrl('//evil.com')).toBe(false);
  });

  it('rejects relative paths and other schemes', () => {
    expect(isSafeHttpUrl('/plugins/my-plugin')).toBe(false);
    expect(isSafeHttpUrl('mailto:someone@example.com')).toBe(false);
    expect(isSafeHttpUrl('ftp://example.com')).toBe(false);
  });

  it('rejects leading whitespace', () => {
    expect(isSafeHttpUrl('  https://evil.com')).toBe(false);
  });

  it('rejects non-string values', () => {
    expect(isSafeHttpUrl(null)).toBe(false);
    expect(isSafeHttpUrl(undefined)).toBe(false);
    expect(isSafeHttpUrl(123)).toBe(false);
    expect(isSafeHttpUrl({})).toBe(false);
  });
});
