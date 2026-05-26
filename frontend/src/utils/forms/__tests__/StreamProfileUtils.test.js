import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../../../api.js', () => ({
  default: {
    updateStreamProfile: vi.fn(),
    addStreamProfile: vi.fn(),
  },
}));

vi.mock('@hookform/resolvers/yup', () => ({
  yupResolver: vi.fn((schema) => ({ __schema: schema })),
}));

import API from '../../../api.js';
import { yupResolver } from '@hookform/resolvers/yup';
import {
  BUILT_IN_COMMANDS,
  COMMAND_EXAMPLES,
  toCommandSelection,
  getResolver,
  updateStreamProfile,
  addStreamProfile,
} from '../StreamProfileUtils.js';

describe('StreamProfileUtils', () => {
  // ─── BUILT_IN_COMMANDS ────────────────────────────────────────────────────────

  describe('BUILT_IN_COMMANDS', () => {
    it('includes ffmpeg, streamlink, cvlc, yt-dlp, and __custom__', () => {
      const values = BUILT_IN_COMMANDS.map((c) => c.value);
      expect(values).toContain('ffmpeg');
      expect(values).toContain('streamlink');
      expect(values).toContain('cvlc');
      expect(values).toContain('yt-dlp');
      expect(values).toContain('__custom__');
    });

    it('each entry has a value and a label', () => {
      for (const cmd of BUILT_IN_COMMANDS) {
        expect(cmd).toHaveProperty('value');
        expect(cmd).toHaveProperty('label');
        expect(typeof cmd.value).toBe('string');
        expect(typeof cmd.label).toBe('string');
      }
    });

    it('labels the custom entry "Custom…"', () => {
      const custom = BUILT_IN_COMMANDS.find((c) => c.value === '__custom__');
      expect(custom?.label).toBe('Custom…');
    });
  });

  // ─── COMMAND_EXAMPLES ─────────────────────────────────────────────────────────

  describe('COMMAND_EXAMPLES', () => {
    it('has an entry for each non-custom built-in command', () => {
      const nonCustom = BUILT_IN_COMMANDS.filter((c) => c.value !== '__custom__');
      for (const cmd of nonCustom) {
        expect(COMMAND_EXAMPLES).toHaveProperty(cmd.value);
        expect(typeof COMMAND_EXAMPLES[cmd.value]).toBe('string');
        expect(COMMAND_EXAMPLES[cmd.value].length).toBeGreaterThan(0);
      }
    });

    it('does not have an entry for __custom__', () => {
      expect(COMMAND_EXAMPLES).not.toHaveProperty('__custom__');
    });

    it('ffmpeg example contains {streamUrl}', () => {
      expect(COMMAND_EXAMPLES.ffmpeg).toContain('{streamUrl}');
    });

    it('streamlink example contains {streamUrl}', () => {
      expect(COMMAND_EXAMPLES.streamlink).toContain('{streamUrl}');
    });

    it('cvlc example contains {streamUrl}', () => {
      expect(COMMAND_EXAMPLES.cvlc).toContain('{streamUrl}');
    });

    it('yt-dlp example contains {streamUrl}', () => {
      expect(COMMAND_EXAMPLES['yt-dlp']).toContain('{streamUrl}');
    });
  });

  // ─── toCommandSelection ───────────────────────────────────────────────────────

  describe('toCommandSelection', () => {
    it('returns "ffmpeg" for "ffmpeg"', () => {
      expect(toCommandSelection('ffmpeg')).toBe('ffmpeg');
    });

    it('returns "streamlink" for "streamlink"', () => {
      expect(toCommandSelection('streamlink')).toBe('streamlink');
    });

    it('returns "cvlc" for "cvlc"', () => {
      expect(toCommandSelection('cvlc')).toBe('cvlc');
    });

    it('returns "yt-dlp" for "yt-dlp"', () => {
      expect(toCommandSelection('yt-dlp')).toBe('yt-dlp');
    });

    it('returns "__custom__" for "__custom__"', () => {
      expect(toCommandSelection('__custom__')).toBe('__custom__');
    });

    it('returns "__custom__" for an unrecognized command', () => {
      expect(toCommandSelection('myspecialtool')).toBe('__custom__');
    });

    it('returns "__custom__" for an empty string', () => {
      expect(toCommandSelection('')).toBe('__custom__');
    });

    it('returns "__custom__" for null', () => {
      expect(toCommandSelection(null)).toBe('__custom__');
    });

    it('returns "__custom__" for undefined', () => {
      expect(toCommandSelection(undefined)).toBe('__custom__');
    });
  });

  // ─── getResolver ──────────────────────────────────────────────────────────────

  describe('getResolver', () => {
    it('calls yupResolver and returns its result', () => {
      const result = getResolver();
      expect(yupResolver).toHaveBeenCalledTimes(1);
      expect(result).toBeDefined();
    });

    it('returns the same resolver on subsequent calls', () => {
      const r1 = getResolver();
      const r2 = getResolver();
      expect(r1).toEqual(r2);
    });
  });

  // ─── updateStreamProfile ──────────────────────────────────────────────────────

  describe('updateStreamProfile', () => {
    beforeEach(() => {
      vi.clearAllMocks();
    });

    it('calls API.updateStreamProfile with id merged into values', () => {
      API.updateStreamProfile.mockResolvedValueOnce({ id: 3, name: 'HD' });
      updateStreamProfile(3, { name: 'HD', command: 'ffmpeg' });
      expect(API.updateStreamProfile).toHaveBeenCalledWith({
        id: 3,
        name: 'HD',
        command: 'ffmpeg',
      });
    });

    it('returns the promise from API.updateStreamProfile', () => {
      const resolved = Promise.resolve({ id: 1 });
      API.updateStreamProfile.mockReturnValueOnce(resolved);
      const result = updateStreamProfile(1, {});
      expect(result).toBe(resolved);
    });
  });

  // ─── addStreamProfile ─────────────────────────────────────────────────────────

  describe('addStreamProfile', () => {
    beforeEach(() => {
      vi.clearAllMocks();
    });

    it('calls API.addStreamProfile with the provided values', () => {
      API.addStreamProfile.mockResolvedValueOnce({ id: 5 });
      addStreamProfile({ name: 'New', command: 'streamlink', parameters: '' });
      expect(API.addStreamProfile).toHaveBeenCalledWith({
        name: 'New',
        command: 'streamlink',
        parameters: '',
      });
    });

    it('returns the promise from API.addStreamProfile', () => {
      const resolved = Promise.resolve({ id: 5 });
      API.addStreamProfile.mockReturnValueOnce(resolved);
      const result = addStreamProfile({});
      expect(result).toBe(resolved);
    });

    it('passes through an empty object without error', () => {
      API.addStreamProfile.mockResolvedValueOnce({});
      expect(() => addStreamProfile({})).not.toThrow();
      expect(API.addStreamProfile).toHaveBeenCalledWith({});
    });
  });
});