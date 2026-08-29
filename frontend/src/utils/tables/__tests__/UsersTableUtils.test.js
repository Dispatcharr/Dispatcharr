import { describe, it, expect } from 'vitest';
import {
  getFilteredUsers,
  getSortedUsers,
  getUserFullName,
} from '../UsersTableUtils';
import { USER_LEVELS } from '../../../constants';

// ── Factory ─────────────────────────────────────────────────────────────────
const makeUser = (overrides = {}) => ({
  id: 1,
  username: 'testuser',
  first_name: 'Test',
  last_name: 'User',
  email: 'test@example.com',
  user_level: USER_LEVELS.STANDARD,
  date_joined: '2024-01-15T10:00:00Z',
  last_login: '2024-06-01T12:00:00Z',
  ...overrides,
});

const usernames = (users) => users.map((u) => u.username);

// ══════════════════════════════════════════════════════════════════════════════

describe('getUserFullName', () => {
  it('joins first and last name', () => {
    expect(
      getUserFullName(makeUser({ first_name: 'Ada', last_name: 'Lovelace' }))
    ).toBe('Ada Lovelace');
  });

  it('returns an empty string when both names are missing', () => {
    expect(
      getUserFullName(makeUser({ first_name: null, last_name: null }))
    ).toBe('');
  });

  it('does not leave a stray space when only one name is set', () => {
    expect(
      getUserFullName(makeUser({ first_name: 'Ada', last_name: '' }))
    ).toBe('Ada');
    expect(
      getUserFullName(makeUser({ first_name: '', last_name: 'Lovelace' }))
    ).toBe('Lovelace');
  });
});

describe('getSortedUsers', () => {
  const users = [
    makeUser({ id: 1, username: 'charlie' }),
    makeUser({ id: 2, username: 'alice' }),
    makeUser({ id: 3, username: 'bob' }),
  ];

  it('sorts strings ascending', () => {
    expect(usernames(getSortedUsers(users, 'username', false))).toEqual([
      'alice',
      'bob',
      'charlie',
    ]);
  });

  it('sorts strings descending', () => {
    expect(usernames(getSortedUsers(users, 'username', true))).toEqual([
      'charlie',
      'bob',
      'alice',
    ]);
  });

  it('does not mutate the array it is given', () => {
    const input = [...users];
    getSortedUsers(input, 'username', false);
    expect(usernames(input)).toEqual(['charlie', 'alice', 'bob']);
  });

  it('sorts the virtual name column on the combined first and last name', () => {
    const named = [
      makeUser({ id: 1, username: 'a', first_name: 'Zoe', last_name: 'Adams' }),
      makeUser({ id: 2, username: 'b', first_name: 'Ada', last_name: 'Zeta' }),
    ];
    expect(usernames(getSortedUsers(named, 'name', false))).toEqual(['b', 'a']);
  });

  it('compares case-insensitively', () => {
    const mixed = [
      makeUser({ id: 1, username: 'beta' }),
      makeUser({ id: 2, username: 'Alpha' }),
    ];
    expect(usernames(getSortedUsers(mixed, 'username', false))).toEqual([
      'Alpha',
      'beta',
    ]);
  });

  it('sorts user_level numerically by privilege, not by label', () => {
    // Numeric order is Streamer (0) → Standard (1) → Admin (10). Sorting the
    // labels alphabetically would give Admin → Standard User → Streamer.
    const levels = [
      makeUser({ id: 1, username: 'admin', user_level: USER_LEVELS.ADMIN }),
      makeUser({
        id: 2,
        username: 'streamer',
        user_level: USER_LEVELS.STREAMER,
      }),
      makeUser({
        id: 3,
        username: 'standard',
        user_level: USER_LEVELS.STANDARD,
      }),
    ];
    expect(usernames(getSortedUsers(levels, 'user_level', false))).toEqual([
      'streamer',
      'standard',
      'admin',
    ]);
  });

  it('sorts ISO date strings chronologically', () => {
    const dated = [
      makeUser({
        id: 1,
        username: 'newer',
        last_login: '2024-06-01T12:00:00Z',
      }),
      makeUser({
        id: 2,
        username: 'older',
        last_login: '2023-01-01T12:00:00Z',
      }),
    ];
    expect(usernames(getSortedUsers(dated, 'last_login', false))).toEqual([
      'older',
      'newer',
    ]);
  });

  it('puts users with no value last in both directions', () => {
    const partial = [
      makeUser({ id: 1, username: 'never', last_login: null }),
      makeUser({
        id: 2,
        username: 'older',
        last_login: '2023-01-01T12:00:00Z',
      }),
      makeUser({
        id: 3,
        username: 'newer',
        last_login: '2024-06-01T12:00:00Z',
      }),
    ];
    expect(usernames(getSortedUsers(partial, 'last_login', false))).toEqual([
      'older',
      'newer',
      'never',
    ]);
    expect(usernames(getSortedUsers(partial, 'last_login', true))).toEqual([
      'newer',
      'older',
      'never',
    ]);
  });

  it('treats a blank name as no value', () => {
    const partial = [
      makeUser({ id: 1, username: 'blank', first_name: '', last_name: '' }),
      makeUser({ id: 2, username: 'named', first_name: 'Ada', last_name: 'L' }),
    ];
    expect(usernames(getSortedUsers(partial, 'name', false))).toEqual([
      'named',
      'blank',
    ]);
  });
});

describe('getFilteredUsers', () => {
  const users = [
    makeUser({
      id: 1,
      username: 'alice',
      first_name: 'Alice',
      last_name: 'Smith',
      email: 'alice@example.com',
      user_level: USER_LEVELS.ADMIN,
    }),
    makeUser({
      id: 2,
      username: 'bob',
      first_name: 'Bob',
      last_name: 'Jones',
      email: 'bob@other.org',
      user_level: USER_LEVELS.STREAMER,
    }),
  ];

  it('returns every user when the search is empty', () => {
    expect(getFilteredUsers(users, '')).toHaveLength(2);
    expect(getFilteredUsers(users, '   ')).toHaveLength(2);
    expect(getFilteredUsers(users, null)).toHaveLength(2);
  });

  it('matches on username', () => {
    expect(usernames(getFilteredUsers(users, 'ali'))).toEqual(['alice']);
  });

  it('matches on email', () => {
    expect(usernames(getFilteredUsers(users, 'other.org'))).toEqual(['bob']);
  });

  it('matches on last name, which is not a column of its own', () => {
    expect(usernames(getFilteredUsers(users, 'jones'))).toEqual(['bob']);
  });

  it('matches on the user level label shown in the table', () => {
    expect(usernames(getFilteredUsers(users, 'streamer'))).toEqual(['bob']);
  });

  it('is case-insensitive and ignores surrounding whitespace', () => {
    expect(usernames(getFilteredUsers(users, '  ALICE  '))).toEqual(['alice']);
  });

  it('never matches on the XC password, which the table masks', () => {
    const withPassword = [
      makeUser({
        id: 1,
        username: 'alice',
        custom_properties: { xc_password: 'hunter2' },
      }),
    ];
    expect(getFilteredUsers(withPassword, 'hunter2')).toEqual([]);
  });

  it('returns an empty array when nothing matches', () => {
    expect(getFilteredUsers(users, 'nobody')).toEqual([]);
  });

  it('tolerates users with missing name and email fields', () => {
    const sparse = [
      makeUser({
        id: 1,
        username: 'ghost',
        first_name: null,
        last_name: null,
        email: null,
      }),
    ];
    expect(usernames(getFilteredUsers(sparse, 'ghost'))).toEqual(['ghost']);
  });
});
