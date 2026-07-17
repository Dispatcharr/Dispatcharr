import { describe, expect, it, vi } from 'vitest';

import { formatApiError } from '../utils';

const djangoHtml500 =
  '<!doctype html> <html lang="en"> <head> <title>Server Error (500)</title> </head> <body> <h1>Server Error (500)</h1><p> </p> </body> </html>';

const fakeResponse = (statusText, contentType) => ({
  statusText,
  headers: { get: (name) => (name === 'content-type' ? contentType : null) },
});

describe('formatApiError', () => {
  it('replaces a Django HTML 500 body with the response status line', () => {
    const msg = formatApiError({
      status: 500,
      body: djangoHtml500,
      response: fakeResponse('Internal Server Error', 'text/html'),
    });
    expect(msg).toBe('500 - Internal Server Error');
    expect(msg).not.toContain('<');
  });

  it('uses the reason phrase for nginx gateway HTML pages', () => {
    expect(
      formatApiError({
        status: 504,
        body: '<html><body><h1>504 Gateway Time-out</h1></body></html>',
        response: fakeResponse('Gateway Time-out', 'text/html'),
      })
    ).toBe('504 - Gateway Time-out');
    expect(
      formatApiError({
        status: 502,
        body: '<html></html>',
        response: fakeResponse('Bad Gateway', 'text/html'),
      })
    ).toBe('502 - Bad Gateway');
  });

  it('trusts the declared content type over body sniffing', () => {
    const msg = formatApiError({
      status: 503,
      body: 'upstream connect error <html>...</html>',
      response: fakeResponse('Service Unavailable', 'text/html; charset=utf-8'),
    });
    expect(msg).toBe('503 - Service Unavailable');
  });

  it('sniffs markup when no content type is available', () => {
    expect(formatApiError({ status: 500, body: djangoHtml500 })).toBe(
      '500 - Internal Server Error'
    );
  });

  it('does not sniff markup when content type is explicitly non-html', () => {
    expect(
      formatApiError({
        status: 400,
        body: '<name> is invalid',
        response: fakeResponse('Bad Request', 'text/plain'),
      })
    ).toBe('400 - <name> is invalid');
  });

  it('uses a status label when the reason phrase is absent (HTTP/2)', () => {
    expect(
      formatApiError({
        status: 502,
        body: '<html></html>',
        response: fakeResponse('', 'text/html'),
      })
    ).toBe('502 - Bad Gateway');
  });

  it('preserves the suppressed HTML body via console.debug', () => {
    const spy = vi.spyOn(console, 'debug').mockImplementation(() => {});
    formatApiError({
      status: 500,
      body: djangoHtml500,
      response: fakeResponse('Internal Server Error', 'text/html'),
    });
    expect(spy).toHaveBeenCalledWith(
      'API error 500 response body:',
      djangoHtml500
    );
    spy.mockRestore();
  });

  it('extracts detail from DRF-style JSON bodies', () => {
    expect(
      formatApiError({
        status: 401,
        body: {
          detail: 'No active account found with the given credentials',
        },
      })
    ).toBe('No active account found with the given credentials');
  });

  it('extracts error from custom API JSON bodies', () => {
    expect(
      formatApiError({ status: 500, body: { error: 'Redis not available' } })
    ).toBe('Redis not available');
  });

  it('extracts non_field_errors when detail/error are absent', () => {
    expect(
      formatApiError({
        status: 400,
        body: {
          non_field_errors: ['Unable to log in with provided credentials.'],
        },
      })
    ).toBe('Unable to log in with provided credentials.');
  });

  it('prefers detail over other JSON keys', () => {
    expect(
      formatApiError({
        status: 400,
        body: {
          detail: 'Primary message',
          error: 'Secondary',
          name: ['ignored when detail is present'],
        },
      })
    ).toBe('Primary message');
  });

  it('joins DRF field validation errors', () => {
    expect(
      formatApiError({
        status: 400,
        body: { name: ['This field is required.'] },
      })
    ).toBe('name: This field is required.');
    expect(
      formatApiError({
        status: 400,
        body: {
          name: ['This field is required.'],
          url: ['Enter a valid URL.'],
        },
      })
    ).toBe('name: This field is required.; url: Enter a valid URL.');
  });

  it('passes through short plain-text bodies with the status', () => {
    expect(
      formatApiError({
        status: 403,
        body: 'Forbidden by policy',
        response: fakeResponse('Forbidden', 'text/plain'),
      })
    ).toBe('403 - Forbidden by policy');
  });

  it('truncates long plain-text bodies', () => {
    const long = 'x'.repeat(500);
    const msg = formatApiError({
      status: 500,
      body: long,
      response: fakeResponse('Internal Server Error', 'text/plain'),
    });
    expect(msg.length).toBeLessThanOrEqual(210);
    expect(msg.endsWith('...')).toBe(true);
  });

  it('uses the status line when the body is empty', () => {
    expect(
      formatApiError({
        status: 503,
        body: '',
        response: fakeResponse('Service Unavailable', ''),
      })
    ).toBe('503 - Service Unavailable');
  });

  it('handles non-standard statuses via the server-provided reason phrase', () => {
    expect(
      formatApiError({
        status: 599,
        body: '<html></html>',
        response: fakeResponse('Network Connect Timeout Error', 'text/html'),
      })
    ).toBe('599 - Network Connect Timeout Error');
  });

  it('uses error.message for non-HTTP errors (fetch/network failures)', () => {
    expect(formatApiError(new TypeError('Failed to fetch'))).toBe(
      'Failed to fetch'
    );
    expect(formatApiError({})).toBe('Unknown error');
  });
});
