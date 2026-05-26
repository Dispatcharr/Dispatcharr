import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../../../api.js', () => ({
  default: {
    updateStream: vi.fn(),
    addStream: vi.fn(),
  },
}));

vi.mock('@hookform/resolvers/yup', () => ({
  yupResolver: vi.fn((schema) => ({ __schema: schema })),
}));

import API from '../../../api.js';
import { yupResolver } from '@hookform/resolvers/yup';
import { getResolver, updateStream, addStream } from '../StreamUtils.js';

describe('StreamUtils', () => {
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

// ─── updateStream ─────────────────────────────────────────────────────────────

  describe('updateStream', () => {
    beforeEach(() => {
      vi.clearAllMocks();
    });

    it('calls API.updateStream with id merged into payload', () => {
      API.updateStream.mockResolvedValueOnce({ id: 1, name: 'Test Stream' });
      updateStream(1, { name: 'Test Stream', url: 'http://example.com' });
      expect(API.updateStream).toHaveBeenCalledWith({
        id: 1,
        name: 'Test Stream',
        url: 'http://example.com',
      });
    });

    it('returns the promise from API.updateStream', () => {
      const resolved = Promise.resolve({ id: 1 });
      API.updateStream.mockReturnValueOnce(resolved);
      const result = updateStream(1, {});
      expect(result).toBe(resolved);
    });

    it('handles an empty payload without throwing', () => {
      API.updateStream.mockResolvedValueOnce({});
      expect(() => updateStream(5, {})).not.toThrow();
      expect(API.updateStream).toHaveBeenCalledWith({ id: 5 });
    });
  });

// ─── addStream ────────────────────────────────────────────────────────────────

  describe('addStream', () => {
    beforeEach(() => {
      vi.clearAllMocks();
    });

    it('calls API.addStream with the provided payload', () => {
      API.addStream.mockResolvedValueOnce({ id: 2 });
      addStream({ name: 'New Stream', url: 'http://example.com/stream' });
      expect(API.addStream).toHaveBeenCalledWith({
        name: 'New Stream',
        url: 'http://example.com/stream',
      });
    });

    it('returns the promise from API.addStream', () => {
      const resolved = Promise.resolve({ id: 2 });
      API.addStream.mockReturnValueOnce(resolved);
      const result = addStream({ name: 'test' });
      expect(result).toBe(resolved);
    });

    it('passes through an empty object without error', () => {
      API.addStream.mockResolvedValueOnce({});
      expect(() => addStream({})).not.toThrow();
      expect(API.addStream).toHaveBeenCalledWith({});
    });
  });
});