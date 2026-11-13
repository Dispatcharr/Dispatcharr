import { describe, it, expect } from 'vitest';
import {
  computeBackoffDelay,
  BACKOFF_DEFAULT_INITIAL_MS,
  BACKOFF_DEFAULT_MAX_MS,
} from '../backoff';

describe('computeBackoffDelay', () => {
  it('returns half of the base delay for half-jitter when random is 0', () => {
    expect(
      computeBackoffDelay(0, {
        initialMs: 1000,
        factor: 1.5,
        jitter: 0.5,
        random: () => 0,
      })
    ).toBe(500);
  });

  it('returns the full base delay for half-jitter when random is 1', () => {
    expect(
      computeBackoffDelay(0, {
        initialMs: 1000,
        factor: 1.5,
        jitter: 0.5,
        random: () => 1,
      })
    ).toBe(1000);
  });

  it('returns the exact base when jitter is 0', () => {
    expect(
      computeBackoffDelay(0, {
        initialMs: 1000,
        factor: 2,
        jitter: 0,
        random: () => 0,
      })
    ).toBe(1000);
    expect(
      computeBackoffDelay(2, {
        initialMs: 1000,
        factor: 2,
        jitter: 0,
      })
    ).toBe(4000);
  });

  it('grows exponentially across attempts before the cap', () => {
    const opts = { initialMs: 1000, factor: 1.5, jitter: 0.5, random: () => 1 };
    expect(computeBackoffDelay(0, opts)).toBe(1000);
    expect(computeBackoffDelay(1, opts)).toBe(1500);
    expect(computeBackoffDelay(2, opts)).toBe(2250);
  });

  it('never returns 0 with default half-jitter', () => {
    expect(
      computeBackoffDelay(0, {
        initialMs: BACKOFF_DEFAULT_INITIAL_MS,
        jitter: 0.5,
        random: () => 0,
      })
    ).toBeGreaterThan(0);
  });

  it('caps at maxMs', () => {
    expect(
      computeBackoffDelay(100, {
        initialMs: 1000,
        maxMs: BACKOFF_DEFAULT_MAX_MS,
        factor: 2,
        jitter: 0,
      })
    ).toBe(BACKOFF_DEFAULT_MAX_MS);
    expect(
      computeBackoffDelay(100, {
        initialMs: 1000,
        maxMs: BACKOFF_DEFAULT_MAX_MS,
        factor: 2,
        jitter: 0.5,
        random: () => 0,
      })
    ).toBe(Math.floor(BACKOFF_DEFAULT_MAX_MS * 0.5));
  });

  it('matches prior live-player delays (factor 2, no jitter, 1-based attempt)', () => {
    // FloatingVideo used BASE * 2 ** (attempt - 1) with attempt starting at 1.
    const opts = { initialMs: 1000, maxMs: 10000, factor: 2, jitter: 0 };
    expect(computeBackoffDelay(0, opts)).toBe(1000);
    expect(computeBackoffDelay(1, opts)).toBe(2000);
    expect(computeBackoffDelay(2, opts)).toBe(4000);
    expect(computeBackoffDelay(3, opts)).toBe(8000);
    expect(computeBackoffDelay(4, opts)).toBe(10000);
  });

  it('treats invalid attempt values as 0', () => {
    expect(
      computeBackoffDelay(NaN, { initialMs: 1000, jitter: 0 })
    ).toBe(1000);
    expect(
      computeBackoffDelay(-3, { initialMs: 1000, jitter: 0 })
    ).toBe(1000);
  });
});
