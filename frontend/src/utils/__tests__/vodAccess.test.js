import { describe, it, expect } from 'vitest';
import {
  canViewVod,
  isVodMoviesEnabled,
  isVodSeriesEnabled,
} from '../vodAccess';
import { USER_LEVELS } from '../../constants';

describe('vodAccess', () => {
  it('denies missing users', () => {
    expect(isVodMoviesEnabled(null)).toBe(false);
    expect(isVodSeriesEnabled(undefined)).toBe(false);
    expect(canViewVod(null)).toBe(false);
  });

  it('allows admins even when flags are false', () => {
    const admin = {
      user_level: USER_LEVELS.ADMIN,
      custom_properties: {
        vod_movies_enabled: false,
        vod_series_enabled: false,
      },
    };
    expect(isVodMoviesEnabled(admin)).toBe(true);
    expect(isVodSeriesEnabled(admin)).toBe(true);
    expect(canViewVod(admin)).toBe(true);
  });

  it('defaults standard users to both movies and series enabled', () => {
    const user = { user_level: USER_LEVELS.STANDARD, custom_properties: {} };
    expect(isVodMoviesEnabled(user)).toBe(true);
    expect(isVodSeriesEnabled(user)).toBe(true);
    expect(canViewVod(user)).toBe(true);
  });

  it('respects explicit false for movies only', () => {
    const user = {
      user_level: USER_LEVELS.STANDARD,
      custom_properties: { vod_movies_enabled: false },
    };
    expect(isVodMoviesEnabled(user)).toBe(false);
    expect(isVodSeriesEnabled(user)).toBe(true);
    expect(canViewVod(user)).toBe(true);
  });

  it('respects explicit false for series only', () => {
    const user = {
      user_level: USER_LEVELS.STANDARD,
      custom_properties: { vod_series_enabled: false },
    };
    expect(isVodMoviesEnabled(user)).toBe(true);
    expect(isVodSeriesEnabled(user)).toBe(false);
    expect(canViewVod(user)).toBe(true);
  });

  it('denies when both flags are false', () => {
    const user = {
      user_level: USER_LEVELS.STANDARD,
      custom_properties: {
        vod_movies_enabled: false,
        vod_series_enabled: false,
      },
    };
    expect(isVodMoviesEnabled(user)).toBe(false);
    expect(isVodSeriesEnabled(user)).toBe(false);
    expect(canViewVod(user)).toBe(false);
  });

  it('denies streamers even when flags are true', () => {
    const user = {
      user_level: USER_LEVELS.STREAMER,
      custom_properties: {
        vod_movies_enabled: true,
        vod_series_enabled: true,
      },
    };
    expect(isVodMoviesEnabled(user)).toBe(false);
    expect(isVodSeriesEnabled(user)).toBe(false);
    expect(canViewVod(user)).toBe(false);
  });
});
