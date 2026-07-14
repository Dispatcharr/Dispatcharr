import { describe, it, expect, vi, beforeEach } from 'vitest';

// ── Mocks ──────────────────────────────────────────────────────────────────────

vi.mock('../../../api', () => ({
  default: {
    addServerGroup: vi.fn(),
    updateServerGroup: vi.fn(),
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
  getResolver,
  addServerGroup,
  updateServerGroup,
} from '../ServerGroupUtils';

// ──────────────────────────────────────────────────────────────────────────────

describe('ServerGroupUtils', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(yupResolver).mockReturnValue(mockResolver);
  });

  // ── getResolver ────────────────────────────────────────────────────────────

  describe('getResolver', () => {
    it('calls yupResolver with a schema and returns the result', () => {
      const resolver = getResolver();

      expect(yupResolver).toHaveBeenCalledTimes(1);
      expect(yupResolver).toHaveBeenCalledWith(expect.any(Object));
      expect(resolver).toBe(mockResolver);
    });

    it('returns a new resolver on each call', () => {
      const resolverA = getResolver();
      const resolverB = getResolver();

      expect(yupResolver).toHaveBeenCalledTimes(2);
      expect(resolverA).toBe(mockResolver);
      expect(resolverB).toBe(mockResolver);
    });
  });

  // ── addServerGroup ─────────────────────────────────────────────────────────

  describe('addServerGroup', () => {
    it('calls API.addServerGroup with the provided values', async () => {
      const values = { name: 'US East' };
      vi.mocked(API.addServerGroup).mockResolvedValue({ id: 1, ...values });

      await addServerGroup(values);

      expect(API.addServerGroup).toHaveBeenCalledWith(values);
      expect(API.addServerGroup).toHaveBeenCalledTimes(1);
    });

    it('returns the API response', async () => {
      const values = { name: 'US East' };
      const response = { id: 1, ...values };
      vi.mocked(API.addServerGroup).mockResolvedValue(response);

      const result = await addServerGroup(values);

      expect(result).toEqual(response);
    });

    it('propagates errors thrown by API.addServerGroup', async () => {
      vi.mocked(API.addServerGroup).mockRejectedValue(new Error('Network error'));

      await expect(addServerGroup({ name: 'Test' })).rejects.toThrow('Network error');
    });
  });

  // ── updateServerGroup ──────────────────────────────────────────────────────

  describe('updateServerGroup', () => {
    it('calls API.updateServerGroup with the provided values', async () => {
      const values = { id: 5, name: 'EU West' };
      vi.mocked(API.updateServerGroup).mockResolvedValue(values);

      await updateServerGroup(values);

      expect(API.updateServerGroup).toHaveBeenCalledWith(values);
      expect(API.updateServerGroup).toHaveBeenCalledTimes(1);
    });

    it('returns the API response', async () => {
      const values = { id: 5, name: 'EU West' };
      vi.mocked(API.updateServerGroup).mockResolvedValue(values);

      const result = await updateServerGroup(values);

      expect(result).toEqual(values);
    });

    it('propagates errors thrown by API.updateServerGroup', async () => {
      vi.mocked(API.updateServerGroup).mockRejectedValue(new Error('Update failed'));

      await expect(updateServerGroup({ id: 1, name: 'Test' })).rejects.toThrow('Update failed');
    });
  });
});
