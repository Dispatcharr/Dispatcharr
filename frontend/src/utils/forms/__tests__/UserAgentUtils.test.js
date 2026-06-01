import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../../../api.js', () => ({
  default: {
    updateUserAgent: vi.fn(),
    addUserAgent: vi.fn(),
  },
}));

vi.mock('@hookform/resolvers/yup', () => ({
  yupResolver: vi.fn((schema) => ({ __schema: schema })),
}));

import API from '../../../api.js';
import { yupResolver } from '@hookform/resolvers/yup';
import {
  getResolver,
  updateUserAgent,
  addUserAgent,
} from '../UserAgentUtils.js';

describe('UserAgentUtils', () => {
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

  // ─── updateUserAgent ──────────────────────────────────────────────────────────

  describe('updateUserAgent', () => {
    beforeEach(() => {
      vi.clearAllMocks();
    });

    it('calls API.updateUserAgent with id merged into values', () => {
      API.updateUserAgent.mockResolvedValueOnce({ id: 1, name: 'Chrome' });
      updateUserAgent(1, { name: 'Chrome', user_agent: 'Mozilla/5.0' });
      expect(API.updateUserAgent).toHaveBeenCalledWith({
        id: 1,
        name: 'Chrome',
        user_agent: 'Mozilla/5.0',
      });
    });

    it('returns the promise from API.updateUserAgent', () => {
      const resolved = Promise.resolve({ id: 1 });
      API.updateUserAgent.mockReturnValueOnce(resolved);
      const result = updateUserAgent(1, {});
      expect(result).toBe(resolved);
    });

    it('handles an empty values object without throwing', () => {
      API.updateUserAgent.mockResolvedValueOnce({});
      expect(() => updateUserAgent(5, {})).not.toThrow();
      expect(API.updateUserAgent).toHaveBeenCalledWith({ id: 5 });
    });
  });

  // ─── addUserAgent ─────────────────────────────────────────────────────────────

  describe('addUserAgent', () => {
    beforeEach(() => {
      vi.clearAllMocks();
    });

    it('calls API.addUserAgent with the provided values', () => {
      API.addUserAgent.mockResolvedValueOnce({ id: 2 });
      addUserAgent({ name: 'Firefox', user_agent: 'Mozilla/5.0 (Firefox)' });
      expect(API.addUserAgent).toHaveBeenCalledWith({
        name: 'Firefox',
        user_agent: 'Mozilla/5.0 (Firefox)',
      });
    });

    it('returns the promise from API.addUserAgent', () => {
      const resolved = Promise.resolve({ id: 2 });
      API.addUserAgent.mockReturnValueOnce(resolved);
      const result = addUserAgent({ name: 'test' });
      expect(result).toBe(resolved);
    });

    it('passes through an empty object without error', () => {
      API.addUserAgent.mockResolvedValueOnce({});
      expect(() => addUserAgent({})).not.toThrow();
      expect(API.addUserAgent).toHaveBeenCalledWith({});
    });
  });
});
