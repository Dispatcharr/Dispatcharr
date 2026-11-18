import { afterEach, describe, expect, it, vi } from 'vitest';
import { getBasePath, withBasePath } from '../basePath';

afterEach(() => {
  vi.unstubAllEnvs();
});

describe('getBasePath', () => {
  it('is empty for a root deployment', () => {
    vi.stubEnv('BASE_URL', '/');
    expect(getBasePath()).toBe('');
  });

  it('drops the trailing slash of a sub-path base', () => {
    vi.stubEnv('BASE_URL', '/media/dispatcharr/');
    expect(getBasePath()).toBe('/media/dispatcharr');
  });
});

describe('withBasePath', () => {
  it('leaves root-relative paths unchanged at the root', () => {
    vi.stubEnv('BASE_URL', '/');
    expect(withBasePath('/api/channels/')).toBe('/api/channels/');
  });

  it('prefixes root-relative paths with the sub-path base', () => {
    vi.stubEnv('BASE_URL', '/media/dispatcharr/');
    expect(withBasePath('/proxy/ts/stream/abc')).toBe(
      '/media/dispatcharr/proxy/ts/stream/abc'
    );
    expect(withBasePath('/login')).toBe('/media/dispatcharr/login');
  });

  it('returns absolute, protocol-relative and relative URLs as they are', () => {
    vi.stubEnv('BASE_URL', '/media/dispatcharr/');
    expect(withBasePath('https://example.com/logo.png')).toBe(
      'https://example.com/logo.png'
    );
    expect(withBasePath('//cdn.example.com/a.png')).toBe(
      '//cdn.example.com/a.png'
    );
    expect(withBasePath('logo.png')).toBe('logo.png');
  });

  it('returns non-string input as it is', () => {
    expect(withBasePath(null)).toBe(null);
    expect(withBasePath(undefined)).toBe(undefined);
  });
});
