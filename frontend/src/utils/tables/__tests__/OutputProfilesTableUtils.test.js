import { describe, it, expect, vi, beforeEach } from 'vitest';
import * as OutputProfilesTableUtils from '../OutputProfilesTableUtils';

vi.mock('../../../api.js', () => ({
  default: {
    updateOutputProfile: vi.fn(),
    deleteOutputProfile: vi.fn(),
  },
}));

import API from '../../../api.js';

describe('OutputProfilesTableUtils', () => {
  beforeEach(() => vi.clearAllMocks());

  describe('updateOutputProfile', () => {
    it('calls API.updateOutputProfile with the provided values', () => {
      const mockReturn = Promise.resolve({ id: 1, name: 'Updated' });
      API.updateOutputProfile.mockReturnValue(mockReturn);
      const values = { id: 1, name: 'Updated', is_active: true };
      const result = OutputProfilesTableUtils.updateOutputProfile(values);
      expect(API.updateOutputProfile).toHaveBeenCalledWith(values);
      expect(result).toBe(mockReturn);
    });

    it('passes through the return value from the API', async () => {
      API.updateOutputProfile.mockResolvedValue({ id: 2, name: 'Profile' });
      const result = await OutputProfilesTableUtils.updateOutputProfile({
        id: 2,
      });
      expect(result).toEqual({ id: 2, name: 'Profile' });
    });
  });

  describe('deleteOutputProfile', () => {
    it('calls API.deleteOutputProfile with the correct id', async () => {
      API.deleteOutputProfile.mockResolvedValue(undefined);
      await OutputProfilesTableUtils.deleteOutputProfile(5);
      expect(API.deleteOutputProfile).toHaveBeenCalledWith(5);
    });

    it('resolves without a return value', async () => {
      API.deleteOutputProfile.mockResolvedValue(undefined);
      const result = await OutputProfilesTableUtils.deleteOutputProfile(3);
      expect(result).toBeUndefined();
    });

    it('propagates errors thrown by the API', async () => {
      API.deleteOutputProfile.mockRejectedValue(new Error('Not found'));
      await expect(
        OutputProfilesTableUtils.deleteOutputProfile(99)
      ).rejects.toThrow('Not found');
    });
  });
});
