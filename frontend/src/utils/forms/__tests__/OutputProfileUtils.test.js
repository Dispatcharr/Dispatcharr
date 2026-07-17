import { describe, it, expect, vi, beforeEach } from 'vitest';

// ── Mocks ──────────────────────────────────────────────────────────────────────

vi.mock('../../../api', () => ({
  default: {
    addOutputProfile: vi.fn(),
    updateOutputProfile: vi.fn(),
  },
}));

const mockResolver = vi.fn();
vi.mock('@hookform/resolvers/yup', () => ({
  yupResolver: vi.fn(() => mockResolver),
}));

// ── Imports after mocks ────────────────────────────────────────────────────────

import API from '../../../api';
import { yupResolver } from '@hookform/resolvers/yup';
import {
  BUILT_IN_COMMANDS,
  COMMAND_EXAMPLES,
  toCommandSelection,
  schema,
  addOutputProfile,
  updateOutputProfile,
  getResolver,
} from '../OutputProfileUtils';

// ──────────────────────────────────────────────────────────────────────────────

describe('OutputProfileUtils', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(yupResolver).mockReturnValue(mockResolver);
  });

  // ── Constants ──────────────────────────────────────────────────────────────

  describe('BUILT_IN_COMMANDS', () => {
    it('includes the ffmpeg entry', () => {
      expect(BUILT_IN_COMMANDS).toContainEqual({
        value: 'ffmpeg',
        label: 'FFmpeg',
      });
    });

    it('includes the custom entry', () => {
      expect(BUILT_IN_COMMANDS).toContainEqual({
        value: '__custom__',
        label: 'Custom…',
      });
    });
  });

  describe('COMMAND_EXAMPLES', () => {
    it('has a non-empty string example for ffmpeg', () => {
      expect(typeof COMMAND_EXAMPLES.ffmpeg).toBe('string');
      expect(COMMAND_EXAMPLES.ffmpeg.length).toBeGreaterThan(0);
    });
  });

  // ── toCommandSelection ─────────────────────────────────────────────────────

  describe('toCommandSelection', () => {
    it('returns the command value when it matches a non-custom built-in', () => {
      expect(toCommandSelection('ffmpeg')).toBe('ffmpeg');
    });

    it('returns "__custom__" when command is "__custom__"', () => {
      // __custom__ is in BUILT_IN_COMMANDS but excluded by the o.value !== '__custom__' guard
      expect(toCommandSelection('__custom__')).toBe('__custom__');
    });

    it('returns "__custom__" for an unrecognized command string', () => {
      expect(toCommandSelection('my-arbitrary-tool')).toBe('__custom__');
    });

    it('returns "__custom__" for an empty string', () => {
      expect(toCommandSelection('')).toBe('__custom__');
    });

    it('returns "__custom__" for undefined', () => {
      expect(toCommandSelection(undefined)).toBe('__custom__');
    });
  });

  // ── schema ─────────────────────────────────────────────────────────────────

  describe('schema', () => {
    it('validates a fully populated object', async () => {
      await expect(
        schema.validate({
          name: 'HD Profile',
          command: 'ffmpeg',
          parameters: '-c:v copy',
        })
      ).resolves.toMatchObject({
        name: 'HD Profile',
        command: 'ffmpeg',
        parameters: '-c:v copy',
      });
    });

    it('validates when parameters is omitted (optional)', async () => {
      await expect(
        schema.validate({ name: 'HD Profile', command: 'ffmpeg' })
      ).resolves.toMatchObject({ name: 'HD Profile', command: 'ffmpeg' });
    });

    it('rejects when name is missing', async () => {
      await expect(schema.validate({ command: 'ffmpeg' })).rejects.toThrow(
        'Name is required'
      );
    });

    it('rejects when name is an empty string', async () => {
      await expect(
        schema.validate({ name: '', command: 'ffmpeg' })
      ).rejects.toThrow('Name is required');
    });

    it('rejects when command is missing', async () => {
      await expect(schema.validate({ name: 'HD Profile' })).rejects.toThrow(
        'Command is required'
      );
    });

    it('rejects when command is an empty string', async () => {
      await expect(
        schema.validate({ name: 'HD Profile', command: '' })
      ).rejects.toThrow('Command is required');
    });
  });

  // ── addOutputProfile ───────────────────────────────────────────────────────

  describe('addOutputProfile', () => {
    it('calls API.addOutputProfile with the provided values', async () => {
      const values = { name: 'New Profile', command: 'ffmpeg', parameters: '' };
      vi.mocked(API.addOutputProfile).mockResolvedValue({ id: 1, ...values });

      await addOutputProfile(values);

      expect(API.addOutputProfile).toHaveBeenCalledWith(values);
      expect(API.addOutputProfile).toHaveBeenCalledTimes(1);
    });

    it('returns the API response', async () => {
      const values = { name: 'New Profile', command: 'ffmpeg' };
      const response = { id: 42, ...values };
      vi.mocked(API.addOutputProfile).mockResolvedValue(response);

      const result = await addOutputProfile(values);

      expect(result).toEqual(response);
    });

    it('propagates errors thrown by API.addOutputProfile', async () => {
      vi.mocked(API.addOutputProfile).mockRejectedValue(
        new Error('Network error')
      );

      await expect(addOutputProfile({})).rejects.toThrow('Network error');
    });
  });

  // ── updateOutputProfile ────────────────────────────────────────────────────

  describe('updateOutputProfile', () => {
    it('calls API.updateOutputProfile with the provided values', async () => {
      const values = { id: 1, name: 'Updated Profile', command: 'ffmpeg' };
      vi.mocked(API.updateOutputProfile).mockResolvedValue(values);

      await updateOutputProfile(values);

      expect(API.updateOutputProfile).toHaveBeenCalledWith(values);
      expect(API.updateOutputProfile).toHaveBeenCalledTimes(1);
    });

    it('returns the API response', async () => {
      const values = { id: 7, name: 'Updated Profile', command: 'ffmpeg' };
      vi.mocked(API.updateOutputProfile).mockResolvedValue(values);

      const result = await updateOutputProfile(values);

      expect(result).toEqual(values);
    });

    it('propagates errors thrown by API.updateOutputProfile', async () => {
      vi.mocked(API.updateOutputProfile).mockRejectedValue(
        new Error('Update failed')
      );

      await expect(updateOutputProfile({})).rejects.toThrow('Update failed');
    });
  });

  // ── getResolver ────────────────────────────────────────────────────────────

  describe('getResolver', () => {
    it('returns the result of yupResolver called with schema', () => {
      const resolver = getResolver();

      expect(yupResolver).toHaveBeenCalledWith(schema);
      expect(resolver).toBe(mockResolver);
    });
  });
});
