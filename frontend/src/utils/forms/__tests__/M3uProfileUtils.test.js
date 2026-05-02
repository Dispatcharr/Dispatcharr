import { describe, it, expect, vi, beforeEach } from 'vitest';
import * as Yup from 'yup';
import {
  updateM3UProfile,
  addM3UProfile,
  deleteM3UProfile,
  getDetectedMode,
  applyRegex,
  buildProfileSchema,
  fetchFirstStreamUrl,
  validateXcSimple,
  prepareExpDate,
  applyXcSimplePatterns,
  buildSubmitValues,
  splitByPattern,
} from '../M3uProfileUtils.js';

vi.mock('../../../api.js', () => ({
  default: {
    updateM3UProfile: vi.fn(),
    addM3UProfile: vi.fn(),
    deleteM3UProfile: vi.fn(),
    queryStreams: vi.fn(),
  },
}));

import API from '../../../api.js';

// ── Helpers ────────────────────────────────────────────────────────────────────
const makeM3U = (overrides = {}) => ({
  id: 'm3u-1',
  name: 'My Playlist',
  ...overrides,
});
const makeSubmitValues = (overrides = {}) => ({
  name: 'Profile A',
  xcMode: false,
  ...overrides,
});

describe('M3uProfileUtils', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // ── updateM3UProfile ───────────────────────────────────────────────────────

  describe('updateM3UProfile', () => {
    it('calls API.updateM3UProfile with the m3u id and submitValues', async () => {
      vi.mocked(API.updateM3UProfile).mockResolvedValue(undefined);
      const m3u = makeM3U();
      const values = makeSubmitValues();

      await updateM3UProfile(m3u, values);

      expect(API.updateM3UProfile).toHaveBeenCalledWith('m3u-1', values);
    });

    it('calls API.updateM3UProfile exactly once', async () => {
      vi.mocked(API.updateM3UProfile).mockResolvedValue(undefined);

      await updateM3UProfile(makeM3U(), makeSubmitValues());

      expect(API.updateM3UProfile).toHaveBeenCalledTimes(1);
    });

    it('uses only the id from the m3u object', async () => {
      vi.mocked(API.updateM3UProfile).mockResolvedValue(undefined);
      const m3u = makeM3U({ id: 'playlist-99', name: 'Irrelevant' });

      await updateM3UProfile(m3u, makeSubmitValues());

      expect(API.updateM3UProfile).toHaveBeenCalledWith(
        'playlist-99',
        expect.anything()
      );
    });

    it('passes submitValues through unmodified', async () => {
      vi.mocked(API.updateM3UProfile).mockResolvedValue(undefined);
      const values = makeSubmitValues({ xcMode: true, extra: 'data' });

      await updateM3UProfile(makeM3U(), values);

      expect(API.updateM3UProfile).toHaveBeenCalledWith(
        expect.anything(),
        values
      );
    });

    it('propagates rejection from API.updateM3UProfile', async () => {
      vi.mocked(API.updateM3UProfile).mockRejectedValue(
        new Error('Update failed')
      );

      await expect(
        updateM3UProfile(makeM3U(), makeSubmitValues())
      ).rejects.toThrow('Update failed');
    });

    it('resolves without returning a value', async () => {
      vi.mocked(API.updateM3UProfile).mockResolvedValue({ success: true });

      const result = await updateM3UProfile(makeM3U(), makeSubmitValues());

      expect(result).toBeUndefined();
    });
  });

  // ── addM3UProfile ──────────────────────────────────────────────────────────

  describe('addM3UProfile', () => {
    it('calls API.addM3UProfile with the m3u id and submitValues', async () => {
      vi.mocked(API.addM3UProfile).mockResolvedValue(undefined);
      const m3u = makeM3U();
      const values = makeSubmitValues();

      await addM3UProfile(m3u, values);

      expect(API.addM3UProfile).toHaveBeenCalledWith('m3u-1', values);
    });

    it('calls API.addM3UProfile exactly once', async () => {
      vi.mocked(API.addM3UProfile).mockResolvedValue(undefined);

      await addM3UProfile(makeM3U(), makeSubmitValues());

      expect(API.addM3UProfile).toHaveBeenCalledTimes(1);
    });

    it('uses only the id from the m3u object', async () => {
      vi.mocked(API.addM3UProfile).mockResolvedValue(undefined);
      const m3u = makeM3U({ id: 'playlist-42', name: 'Irrelevant' });

      await addM3UProfile(m3u, makeSubmitValues());

      expect(API.addM3UProfile).toHaveBeenCalledWith(
        'playlist-42',
        expect.anything()
      );
    });

    it('passes submitValues through unmodified', async () => {
      vi.mocked(API.addM3UProfile).mockResolvedValue(undefined);
      const values = makeSubmitValues({ xcMode: true, extra: 'data' });

      await addM3UProfile(makeM3U(), values);

      expect(API.addM3UProfile).toHaveBeenCalledWith(expect.anything(), values);
    });

    it('propagates rejection from API.addM3UProfile', async () => {
      vi.mocked(API.addM3UProfile).mockRejectedValue(new Error('Add failed'));

      await expect(
        addM3UProfile(makeM3U(), makeSubmitValues())
      ).rejects.toThrow('Add failed');
    });

    it('resolves without returning a value', async () => {
      vi.mocked(API.addM3UProfile).mockResolvedValue({ id: 'new-profile' });

      const result = await addM3UProfile(makeM3U(), makeSubmitValues());

      expect(result).toBeUndefined();
    });
  });

  // ── deleteM3UProfile ───────────────────────────────────────────────────────

  describe('deleteM3UProfile', () => {
    it('calls API.deleteM3UProfile with the playlist id and profile id', async () => {
      vi.mocked(API.deleteM3UProfile).mockResolvedValue(undefined);

      await deleteM3UProfile(makeM3U(), 'profile-1');

      expect(API.deleteM3UProfile).toHaveBeenCalledWith('m3u-1', 'profile-1');
    });

    it('calls API.deleteM3UProfile exactly once', async () => {
      vi.mocked(API.deleteM3UProfile).mockResolvedValue(undefined);

      await deleteM3UProfile(makeM3U(), 'profile-1');

      expect(API.deleteM3UProfile).toHaveBeenCalledTimes(1);
    });

    it('uses only the id from the playlist object', async () => {
      vi.mocked(API.deleteM3UProfile).mockResolvedValue(undefined);
      const playlist = makeM3U({ id: 'playlist-99', name: 'Irrelevant' });

      await deleteM3UProfile(playlist, 'profile-1');

      expect(API.deleteM3UProfile).toHaveBeenCalledWith(
        'playlist-99',
        expect.anything()
      );
    });

    it('passes the profile id through unmodified', async () => {
      vi.mocked(API.deleteM3UProfile).mockResolvedValue(undefined);

      await deleteM3UProfile(makeM3U(), 'profile-42');

      expect(API.deleteM3UProfile).toHaveBeenCalledWith(
        expect.anything(),
        'profile-42'
      );
    });

    it('propagates rejection from API.deleteM3UProfile', async () => {
      vi.mocked(API.deleteM3UProfile).mockRejectedValue(
        new Error('Delete failed')
      );

      await expect(deleteM3UProfile(makeM3U(), 'profile-1')).rejects.toThrow(
        'Delete failed'
      );
    });

    it('resolves without returning a value', async () => {
      vi.mocked(API.deleteM3UProfile).mockResolvedValue({ success: true });

      const result = await deleteM3UProfile(makeM3U(), 'profile-1');

      expect(result).toBeUndefined();
    });
  });

  // ── getDetectedMode ───────────────────────────────────────────────────────

  describe('getDetectedMode', () => {
    it('returns storedMode when provided', () => {
      expect(getDetectedMode('advanced', null, null)).toBe('advanced');
    });

    it('returns "simple" when search_pattern matches username/password', () => {
      const m3u = { username: 'user', password: 'pass' };
      const profile = { search_pattern: 'user/pass' };
      expect(getDetectedMode(null, profile, m3u)).toBe('simple');
    });

    it('returns "advanced" when search_pattern exists but does not match username/password', () => {
      const m3u = { username: 'user', password: 'pass' };
      const profile = { search_pattern: 'other/pattern' };
      expect(getDetectedMode(null, profile, m3u)).toBe('advanced');
    });

    it('returns "simple" when no storedMode and no profile', () => {
      expect(getDetectedMode(null, null, null)).toBe('simple');
    });

    it('returns "simple" when profile has no search_pattern', () => {
      const profile = {};
      expect(
        getDetectedMode(null, profile, { username: 'u', password: 'p' })
      ).toBe('simple');
    });
  });

  // ── applyRegex ───────────────────────────────────────────────────────────

  describe('applyRegex', () => {
    it('returns input when pattern is empty', () => {
      expect(applyRegex('hello world', '', 'X')).toBe('hello world');
    });

    it('returns input when input is empty/null', () => {
      expect(applyRegex(null, 'pattern', 'X')).toBeNull();
      expect(applyRegex('', 'pattern', 'X')).toBe('');
    });

    it('applies regex replacement globally', () => {
      expect(applyRegex('aabaa', 'a', 'X')).toBe('XXbXX');
    });

    it('returns input when regex is invalid', () => {
      expect(applyRegex('hello', '[invalid', 'X')).toBe('hello');
    });

    it('replaces matched groups', () => {
      expect(applyRegex('foo/bar', '(foo)', 'baz')).toBe('baz/bar');
    });
  });

  // ── buildProfileSchema ─────────────────────────────────────────────────

  describe('buildProfileSchema', () => {
    it('requires search_pattern and replace_pattern when not default and not XC', async () => {
      const schema = buildProfileSchema(false, false);
      await expect(
        schema.validate({ name: 'Test' }, { abortEarly: false })
      ).rejects.toThrow();
      const error = await schema
        .validate({ name: 'Test' }, { abortEarly: false })
        .catch((e) => e);
      expect(error.errors).toContain('Search pattern is required');
      expect(error.errors).toContain('Replace pattern is required');
    });

    it('does not require search_pattern and replace_pattern for default profile', async () => {
      const schema = buildProfileSchema(true, false);
      await expect(schema.validate({ name: 'Test' })).resolves.toBeTruthy();
    });

    it('does not require search_pattern and replace_pattern when isXC is true', async () => {
      const schema = buildProfileSchema(false, true);
      await expect(schema.validate({ name: 'Test' })).resolves.toBeTruthy();
    });

    it('requires name in all cases', async () => {
      const schema = buildProfileSchema(true, true);
      const error = await schema
        .validate({}, { abortEarly: false })
        .catch((e) => e);
      expect(error.errors).toContain('Name is required');
    });

    it('validates successfully with all required fields', async () => {
      const schema = buildProfileSchema(false, false);
      await expect(
        schema.validate({
          name: 'Test',
          search_pattern: 'foo',
          replace_pattern: 'bar',
        })
      ).resolves.toBeTruthy();
    });
  });

  // ── fetchFirstStreamUrl ─────────────────────────────────────────────────

  describe('fetchFirstStreamUrl', () => {
    beforeEach(() => vi.clearAllMocks());

    it('returns url from first result', async () => {
      API.queryStreams.mockResolvedValue({
        results: [{ url: 'http://stream.url' }],
      });
      const url = await fetchFirstStreamUrl(5);
      expect(url).toBe('http://stream.url');
      const params = API.queryStreams.mock.calls[0][0];
      expect(params.get('page')).toBe('1');
      expect(params.get('page_size')).toBe('1');
      expect(params.get('m3u_account')).toBe('5');
    });

    it('returns null when results are empty', async () => {
      API.queryStreams.mockResolvedValue({ results: [] });
      const url = await fetchFirstStreamUrl(5);
      expect(url).toBeNull();
    });

    it('returns null when response is null', async () => {
      API.queryStreams.mockResolvedValue(null);
      const url = await fetchFirstStreamUrl(5);
      expect(url).toBeNull();
    });
  });

  // ── validateXcSimple ─────────────────────────────────────────────────

  describe('validateXcSimple', () => {
    it('returns errors when both fields are empty', () => {
      const errs = validateXcSimple('', '');
      expect(errs.newUsername).toBe('New username is required');
      expect(errs.newPassword).toBe('New password is required');
    });

    it('returns error only for empty username', () => {
      const errs = validateXcSimple('', 'pass');
      expect(errs.newUsername).toBe('New username is required');
      expect(errs.newPassword).toBeUndefined();
    });

    it('returns error only for empty password', () => {
      const errs = validateXcSimple('user', '');
      expect(errs.newUsername).toBeUndefined();
      expect(errs.newPassword).toBe('New password is required');
    });

    it('returns no errors when both fields are valid', () => {
      const errs = validateXcSimple('user', 'pass');
      expect(errs).toEqual({});
    });

    it('treats whitespace-only values as empty', () => {
      const errs = validateXcSimple('   ', '   ');
      expect(errs.newUsername).toBe('New username is required');
      expect(errs.newPassword).toBe('New password is required');
    });
  });

  // ── prepareExpDate ─────────────────────────────────────────────────

  describe('prepareExpDate', () => {
    it('returns undefined when isXC is true', () => {
      expect(prepareExpDate('2025-01-01', true)).toBeUndefined();
    });

    it('returns ISO string when value is a Date', () => {
      const date = new Date('2025-06-15T00:00:00.000Z');
      expect(prepareExpDate(date, false)).toBe(date.toISOString());
    });

    it('returns the value as-is when it is a string', () => {
      expect(prepareExpDate('2025-06-15', false)).toBe('2025-06-15');
    });

    it('returns null when value is falsy and not XC', () => {
      expect(prepareExpDate(null, false)).toBeNull();
      expect(prepareExpDate('', false)).toBeNull();
      expect(prepareExpDate(undefined, false)).toBeNull();
    });
  });

  // ── applyXcSimplePatterns ───────────────────────────────────────────────

  describe('applyXcSimplePatterns', () => {
    it('sets search_pattern and replace_pattern from m3u credentials and new credentials', () => {
      const m3u = { username: 'oldUser', password: 'oldPass' };
      const values = { name: 'Test', notes: 'some note' };
      const result = applyXcSimplePatterns(values, m3u, 'newUser', 'newPass');
      expect(result.search_pattern).toBe('oldUser/oldPass');
      expect(result.replace_pattern).toBe('newUser/newPass');
      expect(result.name).toBe('Test');
    });

    it('handles missing m3u username and password gracefully', () => {
      const result = applyXcSimplePatterns({}, null, 'newUser', 'newPass');
      expect(result.search_pattern).toBe('/');
      expect(result.replace_pattern).toBe('newUser/newPass');
    });

    it('trims whitespace from newUsername and newPassword', () => {
      const m3u = { username: 'u', password: 'p' };
      const result = applyXcSimplePatterns(
        {},
        m3u,
        '  newUser  ',
        '  newPass  '
      );
      expect(result.replace_pattern).toBe('newUser/newPass');
    });
  });

  // ── buildSubmitValues ─────────────────────────────────────────────────

  describe('buildSubmitValues', () => {
    const baseValues = {
      name: 'Profile Name',
      max_streams: 5,
      search_pattern: 'foo',
      replace_pattern: 'bar',
      notes: 'some notes',
    };

    it('returns name, search_pattern, replace_pattern and custom_properties for default profile', () => {
      const profile = { custom_properties: { existing: 'prop' } };
      const result = buildSubmitValues(baseValues, profile, true, false, null);
      expect(result).toEqual({
        name: 'Profile Name',
        search_pattern: 'foo',
        replace_pattern: 'bar',
        custom_properties: { existing: 'prop', notes: 'some notes' },
      });
      expect(result.max_streams).toBeUndefined();
    });

    it('returns full values for non-default, non-XC profile', () => {
      const profile = { custom_properties: {} };
      const result = buildSubmitValues(baseValues, profile, false, false, null);
      expect(result).toEqual({
        name: 'Profile Name',
        max_streams: 5,
        search_pattern: 'foo',
        replace_pattern: 'bar',
        custom_properties: { notes: 'some notes' },
      });
    });

    it('includes xcMode in custom_properties when isXC is true', () => {
      const profile = { custom_properties: {} };
      const result = buildSubmitValues(
        baseValues,
        profile,
        false,
        true,
        'simple'
      );
      expect(result.custom_properties.xcMode).toBe('simple');
    });

    it('does not include xcMode when isXC is false', () => {
      const profile = { custom_properties: {} };
      const result = buildSubmitValues(
        baseValues,
        profile,
        false,
        false,
        'simple'
      );
      expect(result.custom_properties.xcMode).toBeUndefined();
    });

    it('handles null or undefined profile custom_properties', () => {
      const result = buildSubmitValues(baseValues, null, true, false, null);
      expect(result.custom_properties).toEqual({ notes: 'some notes' });
    });

    it('uses empty string for notes when notes is not provided', () => {
      const values = { ...baseValues, notes: undefined };
      const result = buildSubmitValues(values, null, true, false, null);
      expect(result.custom_properties.notes).toBe('');
    });
  });

  // ── splitByPattern ─────────────────────────────────────────────────────────

  describe('splitByPattern', () => {
    it('returns null when pattern is empty', () => {
      expect(splitByPattern('hello world', '')).toBeNull();
    });

    it('returns null when input is empty', () => {
      expect(splitByPattern('', 'hello')).toBeNull();
    });

    it('returns null when input is null', () => {
      expect(splitByPattern(null, 'hello')).toBeNull();
    });

    it('returns null when pattern is null', () => {
      expect(splitByPattern('hello', null)).toBeNull();
    });

    it('returns null for an invalid regex pattern', () => {
      expect(splitByPattern('hello', '[invalid')).toBeNull();
    });

    it('returns a single unmatched segment when pattern does not match', () => {
      expect(splitByPattern('hello world', 'xyz')).toEqual([
        { text: 'hello world', matched: false },
      ]);
    });

    it('returns a single matched segment when entire input matches', () => {
      expect(splitByPattern('hello', 'hello')).toEqual([
        { text: 'hello', matched: true },
      ]);
    });

    it('splits into unmatched/matched/unmatched segments', () => {
      expect(splitByPattern('say hello there', 'hello')).toEqual([
        { text: 'say ', matched: false },
        { text: 'hello', matched: true },
        { text: ' there', matched: false },
      ]);
    });

    it('handles multiple matches in the input', () => {
      expect(splitByPattern('aXbXc', 'X')).toEqual([
        { text: 'a', matched: false },
        { text: 'X', matched: true },
        { text: 'b', matched: false },
        { text: 'X', matched: true },
        { text: 'c', matched: false },
      ]);
    });

    it('handles a match at the start of the input', () => {
      expect(splitByPattern('helloworld', 'hello')).toEqual([
        { text: 'hello', matched: true },
        { text: 'world', matched: false },
      ]);
    });

    it('handles a match at the end of the input', () => {
      expect(splitByPattern('worldhello', 'hello')).toEqual([
        { text: 'world', matched: false },
        { text: 'hello', matched: true },
      ]);
    });

    it('handles capture-group patterns', () => {
      const result = splitByPattern('foo/bar', '(foo)');
      expect(result).toEqual([
        { text: 'foo', matched: true },
        { text: '/bar', matched: false },
      ]);
    });

    it('handles case-insensitive flag in pattern', () => {
      const result = splitByPattern('Hello World', '(?i)hello');
      // invalid flag combo — regex throws — should return null
      expect(result).toBeNull();
    });

    it('does not loop infinitely on zero-length matches', () => {
      // zero-length match: pattern matches between every character
      const result = splitByPattern('abc', 'x*');
      expect(Array.isArray(result)).toBe(true);
    });
  });
});
