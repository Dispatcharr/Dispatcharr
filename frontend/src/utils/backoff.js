/** Common defaults; callers should pass explicit policy when it matters. */
export const BACKOFF_DEFAULT_INITIAL_MS = 1000;
export const BACKOFF_DEFAULT_MAX_MS = 30000;
export const BACKOFF_DEFAULT_FACTOR = 2;
/** Half-jitter: delay is randomly chosen from 50%–100% of the exponential base. */
export const BACKOFF_DEFAULT_JITTER = 0.5;

/**
 * Exponential delay with optional jitter.
 *
 * @param {number} attempt Zero-based failed-attempt count (0 = first retry).
 * @param {{
 *   initialMs?: number,
 *   maxMs?: number,
 *   factor?: number,
 *   jitter?: number,
 *   random?: () => number,
 * }} [options]
 *   jitter 0: exact base delay.
 *   jitter 0.5: half-jitter (50%–100% of base). Prefer this for reconnect storms.
 *   jitter 1: full jitter (0%–100% of base). Avoid for reconnect; can be near zero.
 * @returns {number} Delay in milliseconds before the next attempt.
 */
export function computeBackoffDelay(attempt, options = {}) {
  const initialMs = options.initialMs ?? BACKOFF_DEFAULT_INITIAL_MS;
  const maxMs = options.maxMs ?? BACKOFF_DEFAULT_MAX_MS;
  const factor = options.factor ?? BACKOFF_DEFAULT_FACTOR;
  const jitter = options.jitter ?? BACKOFF_DEFAULT_JITTER;
  const random = options.random ?? Math.random;

  const safeAttempt = Math.max(0, Number(attempt) || 0);
  const base = Math.min(initialMs * factor ** safeAttempt, maxMs);
  const clampedJitter = Math.min(1, Math.max(0, Number(jitter) || 0));
  if (clampedJitter === 0) {
    return Math.floor(base);
  }
  // (1 - jitter) * base + jitter * base * random → [base*(1-jitter), base]
  return Math.floor(base * (1 - clampedJitter) + base * clampedJitter * random());
}
