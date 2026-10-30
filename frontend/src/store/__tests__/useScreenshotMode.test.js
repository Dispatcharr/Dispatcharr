import { beforeEach, describe, expect, it } from 'vitest';
import useScreenshotMode from '../useScreenshotMode.js';

describe('screenshot mode', () => {
  beforeEach(() => {
    sessionStorage.clear();
    useScreenshotMode.setState({ enabled: false });
  });

  it('starts disabled and toggles without storing sensitive values', () => {
    expect(useScreenshotMode.getState().enabled).toBe(false);
    useScreenshotMode.getState().toggle();
    expect(useScreenshotMode.getState().enabled).toBe(true);
    expect(
      JSON.parse(sessionStorage.getItem('dispatcharr-screenshot-mode'))
    ).toEqual({
      state: { enabled: true },
      version: 0,
    });
    expect(localStorage.getItem('dispatcharr-screenshot-mode')).toBeNull();
    useScreenshotMode.getState().toggle();
    expect(useScreenshotMode.getState().enabled).toBe(false);
  });

  it('restores only the session-scoped boolean preference', async () => {
    sessionStorage.setItem(
      'dispatcharr-screenshot-mode',
      JSON.stringify({
        state: { enabled: true, url: 'not-restored' },
        version: 0,
      })
    );
    await useScreenshotMode.persist.rehydrate();
    expect(useScreenshotMode.getState().enabled).toBe(true);
    expect(useScreenshotMode.getState()).not.toHaveProperty('url');
  });

  it.each([null, 'true', 1])(
    'does not enable from an invalid saved value: %s',
    async (enabled) => {
      sessionStorage.setItem(
        'dispatcharr-screenshot-mode',
        JSON.stringify({ state: { enabled }, version: 0 })
      );
      await useScreenshotMode.persist.rehydrate();
      expect(useScreenshotMode.getState().enabled).toBe(false);
    }
  );
});
