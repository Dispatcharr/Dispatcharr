import { describe, expect, it } from 'vitest';
import { M3U_HASH_KEY_OPTIONS } from '../m3uHashKey';

describe('M3U_HASH_KEY_OPTIONS', () => {
  it('exposes the hash key fields shared by global and account forms', () => {
    expect(M3U_HASH_KEY_OPTIONS.map((option) => option.value)).toEqual([
      'name',
      'url',
      'tvg_id',
      'm3u_id',
      'group',
    ]);
  });

  it('includes labels for each Multiselect option', () => {
    for (const option of M3U_HASH_KEY_OPTIONS) {
      expect(option.label).toBeTruthy();
    }
  });
});
