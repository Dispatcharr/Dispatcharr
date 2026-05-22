// src/utils/forms/__tests__/ChannelGroupUtils.test.js
import { describe, it, expect, vi, beforeEach } from 'vitest';
import {
  updateChannelGroup,
  addChannelGroup,
  deleteChannelGroup,
  cleanupUnusedChannelGroups,
} from '../ChannelGroupUtils.js';

// ── API mock ───────────────────────────────────────────────────────────────────
vi.mock('../../../api.js', () => ({
  default: {
    updateChannelGroup: vi.fn(),
    addChannelGroup: vi.fn(),
    deleteChannelGroup: vi.fn(),
    cleanupUnusedChannelGroups: vi.fn(),
  },
}));

import API from '../../../api.js';

// ── Helpers ────────────────────────────────────────────────────────────────────
const makeChannelGroup = (overrides = {}) => ({
  id: 'group-1',
  name: 'Sports',
  ...overrides,
});

const makeValues = (overrides = {}) => ({
  name: 'Updated Sports',
  locked: false,
  ...overrides,
});

describe('ChannelGroupUtils', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // ── updateChannelGroup ─────────────────────────────────────────────────────

  describe('updateChannelGroup', () => {
    it('calls API.updateChannelGroup with merged id and values', () => {
      const group = makeChannelGroup();
      const values = makeValues();
      updateChannelGroup(group, values);
      expect(API.updateChannelGroup).toHaveBeenCalledWith({
        id: 'group-1',
        name: 'Updated Sports',
        locked: false,
      });
    });

    it('returns the result of API.updateChannelGroup', () => {
      const mockResult = { id: 'group-1', name: 'Updated Sports' };
      vi.mocked(API.updateChannelGroup).mockReturnValue(mockResult);
      const result = updateChannelGroup(makeChannelGroup(), makeValues());
      expect(result).toBe(mockResult);
    });

    it('calls API.updateChannelGroup exactly once', () => {
      updateChannelGroup(makeChannelGroup(), makeValues());
      expect(API.updateChannelGroup).toHaveBeenCalledTimes(1);
    });
  });

  // ── addChannelGroup ────────────────────────────────────────────────────────

  describe('addChannelGroup', () => {
    it('calls API.addChannelGroup with the provided values', () => {
      const values = makeValues();
      addChannelGroup(values);
      expect(API.addChannelGroup).toHaveBeenCalledWith(values);
    });

    it('returns the result of API.addChannelGroup', () => {
      const mockResult = { id: 'group-2', name: 'Updated Sports' };
      vi.mocked(API.addChannelGroup).mockReturnValue(mockResult);
      const result = addChannelGroup(makeValues());
      expect(result).toBe(mockResult);
    });

    it('calls API.addChannelGroup exactly once', () => {
      addChannelGroup(makeValues());
      expect(API.addChannelGroup).toHaveBeenCalledTimes(1);
    });

    it('passes values through unmodified', () => {
      const values = { name: 'News', locked: true, custom: 'data' };
      addChannelGroup(values);
      expect(API.addChannelGroup).toHaveBeenCalledWith(values);
    });
  });

  // ── deleteChannelGroup ─────────────────────────────────────────────────────

  describe('deleteChannelGroup', () => {
    it('calls API.deleteChannelGroup with the group id', () => {
      const group = makeChannelGroup();
      deleteChannelGroup(group);
      expect(API.deleteChannelGroup).toHaveBeenCalledWith('group-1');
    });

    it('returns the result of API.deleteChannelGroup', () => {
      const mockResult = { success: true };
      vi.mocked(API.deleteChannelGroup).mockReturnValue(mockResult);
      const result = deleteChannelGroup(makeChannelGroup());
      expect(result).toBe(mockResult);
    });

    it('calls API.deleteChannelGroup exactly once', () => {
      deleteChannelGroup(makeChannelGroup());
      expect(API.deleteChannelGroup).toHaveBeenCalledTimes(1);
    });

    it('uses only the id from the group object', () => {
      const group = makeChannelGroup({ id: 'group-42', name: 'Movies' });
      deleteChannelGroup(group);
      expect(API.deleteChannelGroup).toHaveBeenCalledWith('group-42');
    });
  });

  // ── cleanupUnusedChannelGroups ─────────────────────────────────────────────

  describe('cleanupUnusedChannelGroups', () => {
    it('calls API.cleanupUnusedChannelGroups', async () => {
      vi.mocked(API.cleanupUnusedChannelGroups).mockResolvedValue(undefined);
      await cleanupUnusedChannelGroups();
      expect(API.cleanupUnusedChannelGroups).toHaveBeenCalled();
    });

    it('calls API.cleanupUnusedChannelGroups exactly once', async () => {
      vi.mocked(API.cleanupUnusedChannelGroups).mockResolvedValue(undefined);
      await cleanupUnusedChannelGroups();
      expect(API.cleanupUnusedChannelGroups).toHaveBeenCalledTimes(1);
    });

    it('returns the resolved value from API.cleanupUnusedChannelGroups', async () => {
      const mockResult = { removed: 5 };
      vi.mocked(API.cleanupUnusedChannelGroups).mockResolvedValue(mockResult);
      const result = await cleanupUnusedChannelGroups();
      expect(result).toEqual(mockResult);
    });

    it('propagates rejection from API.cleanupUnusedChannelGroups', async () => {
      vi.mocked(API.cleanupUnusedChannelGroups).mockRejectedValue(
        new Error('Server error')
      );
      await expect(cleanupUnusedChannelGroups()).rejects.toThrow(
        'Server error'
      );
    });
  });
});
