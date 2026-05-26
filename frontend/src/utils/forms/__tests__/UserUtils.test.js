import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../../../api.js', () => ({
  default: {
    createUser: vi.fn(),
    updateUser: vi.fn(),
    generateApiKey: vi.fn(),
    revokeApiKey: vi.fn(),
  },
}));

vi.mock('../../../constants.js', () => ({
  USER_LEVELS: {
    ADMIN: 0,
    STREAMER: 2,
  },
  NETWORK_ACCESS_OPTIONS: {
    m3u: 'M3U',
    xc: 'XC',
    mpegts: 'MPEG-TS',
  },
}));

vi.mock('../../networkUtils.js', () => ({
  IPV4_CIDR_REGEX: /^(\d{1,3}\.){3}\d{1,3}\/\d{1,2}$/,
  IPV6_CIDR_REGEX: /^([0-9a-fA-F:]+)\/\d{1,3}$/,
}));

import API from '../../../api.js';
import {
  createUser,
  updateUser,
  generateApiKey,
  revokeApiKey,
  userToFormValues,
  formValuesToPayload,
  getFormInitialValues,
  getFormValidators,
} from '../UserUtils.js';

describe('UserUtils', () => {
  // ─── createUser ───────────────────────────────────────────────────────────────

  describe('createUser', () => {
    beforeEach(() => vi.clearAllMocks());

    it('calls API.createUser with the provided values', () => {
      API.createUser.mockResolvedValueOnce({ id: 1 });
      createUser({ username: 'alice', password: 'pass' });
      expect(API.createUser).toHaveBeenCalledWith({ username: 'alice', password: 'pass' });
    });

    it('returns the promise from API.createUser', () => {
      const resolved = Promise.resolve({ id: 1 });
      API.createUser.mockReturnValueOnce(resolved);
      expect(createUser({})).toBe(resolved);
    });
  });

// ─── updateUser ───────────────────────────────────────────────────────────────

  describe('updateUser', () => {
    beforeEach(() => vi.clearAllMocks());

    it('calls API.updateUser with selfEdit=false when isAdmin is true', () => {
      API.updateUser.mockResolvedValueOnce({});
      updateUser(1, { username: 'bob' }, true, { id: 1 });
      expect(API.updateUser).toHaveBeenCalledWith(1, { username: 'bob' }, false);
    });

    it('calls API.updateUser with selfEdit=true when not admin and userId matches authUser', () => {
      API.updateUser.mockResolvedValueOnce({});
      updateUser(5, { username: 'carol' }, false, { id: 5 });
      expect(API.updateUser).toHaveBeenCalledWith(5, { username: 'carol' }, true);
    });

    it('calls API.updateUser with selfEdit=false when not admin and userId does not match authUser', () => {
      API.updateUser.mockResolvedValueOnce({});
      updateUser(5, { username: 'dave' }, false, { id: 99 });
      expect(API.updateUser).toHaveBeenCalledWith(5, { username: 'dave' }, false);
    });

    it('returns the promise from API.updateUser', () => {
      const resolved = Promise.resolve({});
      API.updateUser.mockReturnValueOnce(resolved);
      expect(updateUser(1, {}, true, { id: 1 })).toBe(resolved);
    });
  });

// ─── generateApiKey ───────────────────────────────────────────────────────────

  describe('generateApiKey', () => {
    beforeEach(() => vi.clearAllMocks());

    it('calls API.generateApiKey with the payload', () => {
      API.generateApiKey.mockResolvedValueOnce({ key: 'abc123' });
      generateApiKey({ user_id: 1 });
      expect(API.generateApiKey).toHaveBeenCalledWith({ user_id: 1 });
    });

    it('returns the promise from API.generateApiKey', () => {
      const resolved = Promise.resolve({ key: 'abc' });
      API.generateApiKey.mockReturnValueOnce(resolved);
      expect(generateApiKey({})).toBe(resolved);
    });
  });

// ─── revokeApiKey ─────────────────────────────────────────────────────────────

  describe('revokeApiKey', () => {
    beforeEach(() => vi.clearAllMocks());

    it('calls API.revokeApiKey with the payload', () => {
      API.revokeApiKey.mockResolvedValueOnce({});
      revokeApiKey({ key: 'abc123' });
      expect(API.revokeApiKey).toHaveBeenCalledWith({ key: 'abc123' });
    });

    it('returns the promise from API.revokeApiKey', () => {
      const resolved = Promise.resolve({});
      API.revokeApiKey.mockReturnValueOnce(resolved);
      expect(revokeApiKey({})).toBe(resolved);
    });
  });

// ─── userToFormValues ─────────────────────────────────────────────────────────

  describe('userToFormValues', () => {
    const makeUser = (overrides = {}) => ({
      username: 'alice',
      first_name: 'Alice',
      last_name: 'Smith',
      email: 'alice@example.com',
      user_level: 1,
      stream_limit: 2,
      channel_profiles: ['1', '2'],
      custom_properties: {},
      ...overrides,
    });

    it('maps basic user fields to form values', () => {
      const result = userToFormValues(makeUser());
      expect(result.username).toBe('alice');
      expect(result.first_name).toBe('Alice');
      expect(result.last_name).toBe('Smith');
      expect(result.email).toBe('alice@example.com');
      expect(result.user_level).toBe('1');
      expect(result.stream_limit).toBe(2);
    });

    it('defaults first_name and last_name to empty string when absent', () => {
      const result = userToFormValues(makeUser({ first_name: null, last_name: null }));
      expect(result.first_name).toBe('');
      expect(result.last_name).toBe('');
    });

    it('defaults stream_limit to 0 when absent', () => {
      const result = userToFormValues(makeUser({ stream_limit: null }));
      expect(result.stream_limit).toBe(0);
    });

    it('uses channel_profiles when non-empty', () => {
      const result = userToFormValues(makeUser({ channel_profiles: ['3', '4'] }));
      expect(result.channel_profiles).toEqual(['3', '4']);
    });

    it('maps custom_properties fields with defaults', () => {
      const result = userToFormValues(makeUser({ custom_properties: {} }));
      expect(result.xc_password).toBe('');
      expect(result.output_format).toBe('');
      expect(result.output_profile).toBe('');
      expect(result.hide_adult_content).toBe(false);
      expect(result.epg_days).toBe(0);
      expect(result.epg_prev_days).toBe(0);
    });

    it('maps custom_properties when present', () => {
      const user = makeUser({
        custom_properties: {
          xc_password: 'xpass',
          output_format: 'ts',
          output_profile: 5,
          hide_adult_content: true,
          epg_days: 7,
          epg_prev_days: 2,
          allowed_networks: {
            m3u: '192.168.1.0/24,10.0.0.1/32',
            xc: '192.168.1.0/24,10.0.0.1/32',
          },
        },
      });
      const result = userToFormValues(user);
      expect(result.xc_password).toBe('xpass');
      expect(result.output_format).toBe('ts');
      expect(result.output_profile).toBe('5');
      expect(result.hide_adult_content).toBe(true);
      expect(result.epg_days).toBe(7);
      expect(result.epg_prev_days).toBe(2);
    });

    it('deduplicates allowed_ips from allowed_networks', () => {
      const user = makeUser({
        custom_properties: {
          allowed_networks: {
            m3u: '192.168.1.0/24,10.0.0.1/32',
            xc: '192.168.1.0/24,10.0.0.1/32',
          },
        },
      });
      const result = userToFormValues(user);
      expect(result.allowed_ips).toEqual(['192.168.1.0/24', '10.0.0.1/32']);
    });

    it('returns empty allowed_ips when no allowed_networks', () => {
      const result = userToFormValues(makeUser({ custom_properties: {} }));
      expect(result.allowed_ips).toEqual([]);
    });
  });

// ─── formValuesToPayload ──────────────────────────────────────────────────────

  describe('formValuesToPayload', () => {
    const makeValues = (overrides = {}) => ({
      username: 'alice',
      email: 'alice@example.com',
      xc_password: 'mypass',
      output_format: 'ts',
      output_profile: '3',
      hide_adult_content: true,
      epg_days: 7,
      epg_prev_days: 2,
      allowed_ips: ['192.168.1.0/24'],
      channel_profiles: ['1', '2'],
      ...overrides,
    });

    it('moves xc_password into custom_properties and removes it from payload', () => {
      const result = formValuesToPayload(makeValues(), null);
      expect(result.xc_password).toBeUndefined();
      expect(result.custom_properties.xc_password).toBe('mypass');
    });

    it('moves output_format into custom_properties', () => {
      const result = formValuesToPayload(makeValues(), null);
      expect(result.output_format).toBeUndefined();
      expect(result.custom_properties.output_format).toBe('ts');
    });

    it('parses output_profile as int in custom_properties', () => {
      const result = formValuesToPayload(makeValues(), null);
      expect(result.output_profile).toBeUndefined();
      expect(result.custom_properties.output_profile).toBe(3);
    });

    it('sets output_profile to null when empty string', () => {
      const result = formValuesToPayload(makeValues({ output_profile: '' }), null);
      expect(result.custom_properties.output_profile).toBeNull();
    });

    it('moves hide_adult_content into custom_properties', () => {
      const result = formValuesToPayload(makeValues(), null);
      expect(result.hide_adult_content).toBeUndefined();
      expect(result.custom_properties.hide_adult_content).toBe(true);
    });

    it('moves epg_days and epg_prev_days into custom_properties', () => {
      const result = formValuesToPayload(makeValues(), null);
      expect(result.epg_days).toBeUndefined();
      expect(result.epg_prev_days).toBeUndefined();
      expect(result.custom_properties.epg_days).toBe(7);
      expect(result.custom_properties.epg_prev_days).toBe(2);
    });

    it('populates allowed_networks for all NETWORK_KEYS when allowed_ips present', () => {
      const result = formValuesToPayload(makeValues({ allowed_ips: ['192.168.1.0/24', '10.0.0.1/32'] }), null);
      expect(result.allowed_ips).toBeUndefined();
      expect(result.custom_properties.allowed_networks.m3u).toBe('192.168.1.0/24,10.0.0.1/32');
      expect(result.custom_properties.allowed_networks.xc).toBe('192.168.1.0/24,10.0.0.1/32');
      expect(result.custom_properties.allowed_networks.mpegts).toBe('192.168.1.0/24,10.0.0.1/32');
    });

    it('sets empty allowed_networks when allowed_ips is empty', () => {
      const result = formValuesToPayload(makeValues({ allowed_ips: [] }), null);
      expect(result.custom_properties.allowed_networks).toEqual({});
    });

    it('sets channel_profiles to empty array when it includes "0"', () => {
      const result = formValuesToPayload(makeValues({ channel_profiles: ['0'] }), null);
      expect(result.channel_profiles).toEqual([]);
    });

    it('preserves channel_profiles when it does not include "0"', () => {
      const result = formValuesToPayload(makeValues({ channel_profiles: ['1', '2'] }), null);
      expect(result.channel_profiles).toEqual(['1', '2']);
    });

    it('merges existing custom_properties from existingUser', () => {
      const existingUser = { custom_properties: { some_other_prop: 'keep_me' } };
      const result = formValuesToPayload(makeValues(), existingUser);
      expect(result.custom_properties.some_other_prop).toBe('keep_me');
    });

    it('handles null existingUser gracefully', () => {
      expect(() => formValuesToPayload(makeValues(), null)).not.toThrow();
    });
  });

// ─── getFormInitialValues ─────────────────────────────────────────────────────

  describe('getFormInitialValues', () => {
    it('returns the expected default structure', () => {
      const result = getFormInitialValues();
      expect(result).toEqual({
        username: '',
        first_name: '',
        last_name: '',
        email: '',
        user_level: '0',
        stream_limit: 0,
        password: '',
        xc_password: '',
        output_format: '',
        output_profile: '',
        channel_profiles: [],
        hide_adult_content: false,
        epg_days: 0,
        epg_prev_days: 0,
        allowed_ips: [],
      });
    });

    it('returns a new object on each call', () => {
      const a = getFormInitialValues();
      const b = getFormInitialValues();
      expect(a).not.toBe(b);
    });
  });

// ─── getFormValidators ────────────────────────────────────────────────────────

  describe('getFormValidators', () => {
    const validate = (user, values) => getFormValidators(user)(values);

    describe('username', () => {
      it('returns error when username is empty', () => {
        const result = validate(null, { ...getFormInitialValues(), username: '' });
        expect(result.username).toBe('Username is required');
      });

      it('returns null for a valid non-streamer username', () => {
        const result = validate(null, { ...getFormInitialValues(), username: 'alice', user_level: '0' });
        expect(result.username).toBeNull();
      });

      it('returns null for a valid alphanumeric streamer username', () => {
        const result = validate(null, { ...getFormInitialValues(), username: 'alice123', user_level: '2' });
        expect(result.username).toBeNull();
      });

      it('returns error for streamer username with non-alphanumeric characters', () => {
        const result = validate(null, { ...getFormInitialValues(), username: 'alice_123', user_level: '2' });
        expect(result.username).toBe('Streamer username must be alphanumeric');
      });
    });

    describe('password', () => {
      it('returns error when creating a non-streamer user without a password', () => {
        const result = validate(null, { ...getFormInitialValues(), user_level: '0', password: '' });
        expect(result.password).toBe('Password is required');
      });

      it('returns null when creating a streamer user without a password', () => {
        const result = validate(null, { ...getFormInitialValues(), user_level: '2', password: '' });
        expect(result.password).toBeNull();
      });

      it('returns null when editing an existing user without a password', () => {
        const result = validate({ id: 1 }, { ...getFormInitialValues(), user_level: '0', password: '' });
        expect(result.password).toBeNull();
      });

      it('returns null when password is provided for new user', () => {
        const result = validate(null, { ...getFormInitialValues(), user_level: '0', password: 'secret' });
        expect(result.password).toBeNull();
      });
    });

    describe('xc_password', () => {
      it('returns null when xc_password is empty', () => {
        const result = validate(null, { ...getFormInitialValues(), xc_password: '' });
        expect(result.xc_password).toBeNull();
      });

      it('returns null for a valid alphanumeric xc_password', () => {
        const result = validate(null, { ...getFormInitialValues(), xc_password: 'abc123' });
        expect(result.xc_password).toBeNull();
      });

      it('returns error for xc_password with non-alphanumeric characters', () => {
        const result = validate(null, { ...getFormInitialValues(), xc_password: 'abc!@#' });
        expect(result.xc_password).toBe('XC password must be alphanumeric');
      });
    });

    describe('allowed_ips', () => {
      it('returns null for an empty allowed_ips array', () => {
        const result = validate(null, { ...getFormInitialValues(), allowed_ips: [] });
        expect(result.allowed_ips).toBeNull();
      });

      it('returns null for a valid IPv4 CIDR', () => {
        const result = validate(null, { ...getFormInitialValues(), allowed_ips: ['192.168.1.0/24'] });
        expect(result.allowed_ips).toBeNull();
      });

      it('returns null for a bare IPv4 address (auto-appends /32)', () => {
        const result = validate(null, { ...getFormInitialValues(), allowed_ips: ['10.0.0.1'] });
        expect(result.allowed_ips).toBeNull();
      });

      it('returns error for an invalid IP entry', () => {
        const result = validate(null, { ...getFormInitialValues(), allowed_ips: ['not-an-ip'] });
        expect(result.allowed_ips).toBe('Invalid IP address or CIDR range');
      });

      it('returns error when any entry in the list is invalid', () => {
        const result = validate(null, { ...getFormInitialValues(), allowed_ips: ['192.168.1.0/24', 'bad-entry'] });
        expect(result.allowed_ips).toBe('Invalid IP address or CIDR range');
      });
    });
  });
});