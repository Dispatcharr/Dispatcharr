import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import {
  getLivePlayerErrorMessage,
  getVODPlayerErrorMessage,
  getClientCoordinates,
  calculateNewDimensions,
  applyConstraints,
  PLAYER_PREFS_KEY,
  getPlayerPrefs,
  savePlayerPrefs,
} from '../FloatingVideoUtils';

describe('FloatingVideoUtils', () => {
  describe('getLivePlayerErrorMessage', () => {
    it('should return formatted error for non-MediaError types', () => {
      expect(
        getLivePlayerErrorMessage('NetworkError', 'Connection failed')
      ).toBe('Error: NetworkError - Connection failed');
    });

    it('should return error type only when no detail provided', () => {
      expect(getLivePlayerErrorMessage('NetworkError')).toBe(
        'Error: NetworkError'
      );
    });

    it('should return audio codec message for audio-related errors', () => {
      const result = getLivePlayerErrorMessage(
        'MediaError',
        'audio codec not supported'
      );
      expect(result).toBe(
        'Audio codec not supported by your browser. Try Chrome or Edge for better audio codec support.'
      );
    });

    it('should return audio codec message for AC3 errors', () => {
      const result = getLivePlayerErrorMessage('MediaError', 'AC3 codec issue');
      expect(result).toContain('Audio codec not supported');
    });

    it('should return video codec message for video-related errors', () => {
      const result = getLivePlayerErrorMessage(
        'MediaError',
        'video codec h264 failed'
      );
      expect(result).toBe(
        'Video codec not supported by your browser. Try Chrome or Edge for better video codec support.'
      );
    });

    it('should return MSE message for MSE-related errors', () => {
      const result = getLivePlayerErrorMessage(
        'MediaError',
        'MSE not supported'
      );
      expect(result).toBe(
        "Your browser doesn't support the codecs used in this stream. Try Chrome or Edge for better compatibility."
      );
    });

    it('should return generic codec message for other MediaError cases', () => {
      const result = getLivePlayerErrorMessage(
        'MediaError',
        'unknown codec issue'
      );
      expect(result).toBe(
        'Media codec not supported by your browser. This may be due to unsupported audio (AC3) or video codecs. Try Chrome or Edge.'
      );
    });

    it('should handle null errorDetail for MediaError', () => {
      const result = getLivePlayerErrorMessage('MediaError', null);
      expect(result).toBe(
        'Media codec not supported by your browser. This may be due to unsupported audio (AC3) or video codecs. Try Chrome or Edge.'
      );
    });
  });

  describe('getVODPlayerErrorMessage', () => {
    it('should return default message when error is null', () => {
      expect(getVODPlayerErrorMessage(null)).toBe('Video playback error');
    });

    it('should return aborted message for MEDIA_ERR_ABORTED', () => {
      const error = { code: 1, MEDIA_ERR_ABORTED: 1 };
      expect(getVODPlayerErrorMessage(error)).toBe(
        'Video playback was aborted'
      );
    });

    it('should return network message for MEDIA_ERR_NETWORK', () => {
      const error = { code: 2, MEDIA_ERR_NETWORK: 2 };
      expect(getVODPlayerErrorMessage(error)).toBe(
        'Network error while loading video'
      );
    });

    it('should return codec message for MEDIA_ERR_DECODE', () => {
      const error = { code: 3, MEDIA_ERR_DECODE: 3 };
      expect(getVODPlayerErrorMessage(error)).toBe(
        'Video codec not supported by your browser'
      );
    });

    it('should return format message for MEDIA_ERR_SRC_NOT_SUPPORTED', () => {
      const error = { code: 4, MEDIA_ERR_SRC_NOT_SUPPORTED: 4 };
      expect(getVODPlayerErrorMessage(error)).toBe(
        'Video format not supported by your browser'
      );
    });

    it('should return error message for unknown error codes', () => {
      const error = { code: 99, message: 'Custom error message' };
      expect(getVODPlayerErrorMessage(error)).toBe('Custom error message');
    });

    it('should return default message for unknown error without message', () => {
      const error = { code: 99 };
      expect(getVODPlayerErrorMessage(error)).toBe('Unknown video error');
    });
  });

  describe('getClientCoordinates', () => {
    it('should extract coordinates from mouse event', () => {
      const event = { clientX: 100, clientY: 200 };
      expect(getClientCoordinates(event)).toEqual({
        clientX: 100,
        clientY: 200,
      });
    });

    it('should extract coordinates from touch event', () => {
      const event = { touches: [{ clientX: 150, clientY: 250 }] };
      expect(getClientCoordinates(event)).toEqual({
        clientX: 150,
        clientY: 250,
      });
    });

    it('should prioritize touch coordinates over mouse coordinates', () => {
      const event = {
        touches: [{ clientX: 150, clientY: 250 }],
        clientX: 100,
        clientY: 200,
      };
      expect(getClientCoordinates(event)).toEqual({
        clientX: 150,
        clientY: 250,
      });
    });

    it('should handle undefined coordinates', () => {
      const event = {};
      expect(getClientCoordinates(event)).toEqual({
        clientX: undefined,
        clientY: undefined,
      });
    });
  });

  describe('calculateNewDimensions', () => {
    const ratio = 16 / 9;

    it('should calculate dimensions based on horizontal drag', () => {
      const handle = { xDir: 1, yDir: 0, isLeft: false, isTop: false };
      const result = calculateNewDimensions(100, 10, 400, 225, handle, ratio);

      expect(result.width).toBe(500);
      expect(result.height).toBeCloseTo(281.25, 1);
    });

    it('should calculate dimensions based on vertical drag', () => {
      const handle = { xDir: 0, yDir: 1, isLeft: false, isTop: false };
      const result = calculateNewDimensions(10, 100, 400, 225, handle, ratio);

      expect(result.height).toBe(325);
      expect(result.width).toBeCloseTo(577.78, 1);
    });

    it('should use vertical-driven resize when vertical delta is larger', () => {
      const handle = { xDir: 1, yDir: 1, isLeft: false, isTop: false };
      const result = calculateNewDimensions(20, 100, 400, 225, handle, ratio);

      expect(result.height).toBe(325);
      expect(result.width).toBeCloseTo(577.78, 1);
    });

    it('should handle negative deltas', () => {
      const handle = { xDir: -1, yDir: 0, isLeft: true, isTop: false };
      const result = calculateNewDimensions(-50, 0, 400, 225, handle, ratio);

      expect(result.width).toBe(450);
      expect(result.height).toBeCloseTo(253.13, 1);
    });
  });

  describe('applyConstraints', () => {
    const ratio = 16 / 9;
    const minWidth = 200;
    const minHeight = 112.5;
    const visibleMargin = 50;

    beforeEach(() => {
      Object.defineProperty(window, 'innerWidth', {
        writable: true,
        value: 1920,
      });
      Object.defineProperty(window, 'innerHeight', {
        writable: true,
        value: 1080,
      });
    });

    it('should apply minimum width constraint', () => {
      const handle = { isLeft: false, isTop: false };
      const result = applyConstraints(
        100,
        50,
        ratio,
        { x: 0, y: 0 },
        handle,
        minWidth,
        minHeight,
        visibleMargin
      );

      expect(result.width).toBe(minWidth);
      expect(result.height).toBeCloseTo(minWidth / ratio, 1);
    });

    it('should apply minimum height constraint', () => {
      const handle = { isLeft: false, isTop: false };
      const result = applyConstraints(
        300,
        100,
        ratio,
        { x: 0, y: 0 },
        handle,
        minWidth,
        minHeight,
        visibleMargin
      );

      expect(result.height).toBe(minHeight);
      expect(result.width).toBeCloseTo(minHeight * ratio, 1);
    });

    it('should apply maximum width constraint based on viewport', () => {
      const handle = { isLeft: false, isTop: false };
      const startPos = { x: 1200, y: 100 };
      const result = applyConstraints(
        800,
        450,
        ratio,
        startPos,
        handle,
        minWidth,
        minHeight,
        visibleMargin
      );

      const maxWidth = 1920 - 1200 - 50; // 670
      expect(result.width).toBe(maxWidth);
      expect(result.height).toBeCloseTo(maxWidth / ratio, 1);
    });

    it('should apply maximum height constraint based on viewport', () => {
      const handle = { isLeft: false, isTop: false };
      const startPos = { x: 100, y: 700 };
      const result = applyConstraints(
        500,
        400,
        ratio,
        startPos,
        handle,
        minWidth,
        minHeight,
        visibleMargin
      );

      const maxHeight = 1080 - 700 - 50; // 330
      expect(result.height).toBe(maxHeight);
      expect(result.width).toBeCloseTo(maxHeight * ratio, 1);
    });

    it('should not apply max width constraint for left handle', () => {
      const handle = { isLeft: true, isTop: false };
      const startPos = { x: 1800, y: 100 };
      const result = applyConstraints(
        500,
        281.25,
        ratio,
        startPos,
        handle,
        minWidth,
        minHeight,
        visibleMargin
      );

      expect(result.width).toBe(500);
      expect(result.height).toBeCloseTo(281.25, 1);
    });

    it('should not apply max height constraint for top handle', () => {
      const handle = { isLeft: false, isTop: true };
      const startPos = { x: 100, y: 1000 };
      const result = applyConstraints(
        500,
        400,
        ratio,
        startPos,
        handle,
        minWidth,
        minHeight,
        visibleMargin
      );

      expect(result.width).toBe(500);
      expect(result.height).toBe(400);
    });

    it('should handle null startPos', () => {
      const handle = { isLeft: false, isTop: false };
      const result = applyConstraints(
        300,
        168.75,
        ratio,
        null,
        handle,
        minWidth,
        minHeight,
        visibleMargin
      );

      expect(result.width).toBe(300);
      expect(result.height).toBeCloseTo(168.75, 1);
    });
  });

  describe('getPlayerPrefs / savePlayerPrefs', () => {
    beforeEach(() => localStorage.clear());
    afterEach(() => localStorage.clear());

    it('should return an empty object when nothing is stored', () => {
      expect(getPlayerPrefs()).toEqual({});
    });

    it('should return an empty object when stored value is invalid JSON', () => {
      localStorage.setItem(PLAYER_PREFS_KEY, 'not-json');
      expect(getPlayerPrefs()).toEqual({});
    });

    it('should save and retrieve a volume value', () => {
      savePlayerPrefs({ volume: 0.5 });
      expect(getPlayerPrefs().volume).toBe(0.5);
    });

    it('should save and retrieve a muted value', () => {
      savePlayerPrefs({ muted: true });
      expect(getPlayerPrefs().muted).toBe(true);
    });

    it('should save and retrieve size', () => {
      savePlayerPrefs({ size: { width: 640, height: 360 } });
      expect(getPlayerPrefs().size).toEqual({ width: 640, height: 360 });
    });

    it('should save and retrieve position', () => {
      savePlayerPrefs({ position: { x: 100, y: 200 } });
      expect(getPlayerPrefs().position).toEqual({ x: 100, y: 200 });
    });

    it('should merge updates without losing existing keys', () => {
      savePlayerPrefs({ volume: 0.8, muted: false });
      savePlayerPrefs({ size: { width: 320, height: 180 } });
      const prefs = getPlayerPrefs();
      expect(prefs.volume).toBe(0.8);
      expect(prefs.muted).toBe(false);
      expect(prefs.size).toEqual({ width: 320, height: 180 });
    });

    it('should overwrite an existing key on update', () => {
      savePlayerPrefs({ volume: 0.5 });
      savePlayerPrefs({ volume: 1.0 });
      expect(getPlayerPrefs().volume).toBe(1.0);
    });

    it('should use PLAYER_PREFS_KEY as the storage key', () => {
      savePlayerPrefs({ volume: 0.7 });
      expect(localStorage.getItem(PLAYER_PREFS_KEY)).not.toBeNull();
    });
  });
});
