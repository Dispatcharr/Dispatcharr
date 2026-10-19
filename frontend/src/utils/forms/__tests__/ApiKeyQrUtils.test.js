import { describe, it, expect } from 'vitest';

import {
  API_KEY_QR_MAX_BYTES,
  API_KEY_QR_TYPE,
  API_KEY_QR_VERSION,
  buildUserApiKeyQrPayload,
  buildUserApiKeyQrValue,
} from '../ApiKeyQrUtils.js';

// Same length and alphabet as secrets.token_urlsafe(40).
const API_KEY = 'k'.repeat(54);
const BASE_URL = 'https://dispatcharr.example.com';

const utf8Length = (text) => new TextEncoder().encode(text).length;

const identity = {
  username: 'user1',
  firstName: 'Ada',
  lastName: 'Lovelace',
  email: 'ada@example.com',
};

describe('ApiKeyQrUtils', () => {
  describe('buildUserApiKeyQrPayload', () => {
    it('builds a versioned user_api_key payload', () => {
      expect(
        buildUserApiKeyQrPayload({
          apiKey: API_KEY,
          baseUrl: BASE_URL,
          ...identity,
        })
      ).toEqual({
        v: API_KEY_QR_VERSION,
        type: API_KEY_QR_TYPE,
        api_key: API_KEY,
        base_url: BASE_URL,
        username: 'user1',
        first_name: 'Ada',
        last_name: 'Lovelace',
        email: 'ada@example.com',
      });
    });

    it('pins the wire contract that clients depend on', () => {
      expect(API_KEY_QR_VERSION).toBe(1);
      expect(API_KEY_QR_TYPE).toBe('user_api_key');
    });

    it.each([undefined, null, ''])(
      'always emits the identity keys, blank for %p',
      (blank) => {
        expect(
          buildUserApiKeyQrPayload({
            apiKey: API_KEY,
            baseUrl: BASE_URL,
            username: blank,
            firstName: blank,
            lastName: blank,
            email: blank,
          })
        ).toMatchObject({
          username: '',
          first_name: '',
          last_name: '',
          email: '',
        });
      }
    );
  });

  describe('buildUserApiKeyQrValue', () => {
    it('returns the full payload as JSON when it fits', () => {
      const value = buildUserApiKeyQrValue({
        apiKey: API_KEY,
        baseUrl: BASE_URL,
        ...identity,
      });

      expect(utf8Length(value)).toBeLessThanOrEqual(API_KEY_QR_MAX_BYTES);
      expect(JSON.parse(value)).toEqual({
        v: 1,
        type: 'user_api_key',
        api_key: API_KEY,
        base_url: BASE_URL,
        username: 'user1',
        first_name: 'Ada',
        last_name: 'Lovelace',
        email: 'ada@example.com',
      });
    });

    it('stays within the budget for a typical user', () => {
      const value = buildUserApiKeyQrValue({
        apiKey: API_KEY,
        baseUrl: BASE_URL,
        ...identity,
      });
      // Leaves plenty of headroom so ordinary users never hit the fallback.
      expect(utf8Length(value)).toBeLessThan(API_KEY_QR_MAX_BYTES * 0.75);
    });

    it('blanks identity fields but keeps the credentials when too large', () => {
      const value = buildUserApiKeyQrValue({
        apiKey: API_KEY,
        baseUrl: BASE_URL,
        username: 'u'.repeat(150),
        firstName: 'A'.repeat(150),
        lastName: 'B'.repeat(150),
        email: `${'e'.repeat(240)}@example.com`,
      });

      expect(utf8Length(value)).toBeLessThanOrEqual(API_KEY_QR_MAX_BYTES);
      expect(JSON.parse(value)).toEqual({
        v: 1,
        type: 'user_api_key',
        api_key: API_KEY,
        base_url: BASE_URL,
        username: '',
        first_name: '',
        last_name: '',
        email: '',
      });
    });

    it('measures UTF-8 bytes, not characters', () => {
      // 60 CJK characters is well under the character budget but 180 bytes.
      const fields = {
        apiKey: API_KEY,
        baseUrl: BASE_URL,
        username: 'user1',
        firstName: '名'.repeat(60),
        lastName: '姓'.repeat(60),
        email: 'ada@example.com',
      };
      const value = buildUserApiKeyQrValue(fields);

      expect(utf8Length(value)).toBeLessThanOrEqual(API_KEY_QR_MAX_BYTES);
      expect(JSON.parse(value).first_name).toBe('');
    });

    it('round-trips special characters through JSON', () => {
      const parsed = JSON.parse(
        buildUserApiKeyQrValue({
          apiKey: API_KEY,
          baseUrl: BASE_URL,
          username: 'a"b\\c',
          firstName: 'Zoë',
          lastName: "O'Brien",
          email: 'x@example.com',
        })
      );
      expect(parsed.username).toBe('a"b\\c');
      expect(parsed.first_name).toBe('Zoë');
      expect(parsed.last_name).toBe("O'Brien");
    });
  });
});
