import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MantineProvider } from '@mantine/core';
import ServerGroupsManagerModal from '../ServerGroupsManagerModal';

vi.mock('../../api', () => ({
  default: {
    deleteServerGroup: vi.fn(),
  },
}));

vi.mock('../../store/serverGroups', () => ({
  default: (selector) =>
    selector({
      serverGroups: [
        { id: 1, name: 'Pool A' },
        { id: 2, name: 'Pool B' },
      ],
      fetchServerGroups: vi.fn().mockResolvedValue(undefined),
    }),
}));

vi.mock('../../store/playlists', () => ({
  default: (selector) =>
    selector({
      playlists: [{ id: 10, server_group: 2 }],
    }),
}));

vi.mock('../forms/ServerGroup', () => ({
  default: () => null,
}));

vi.mock('../../hooks/useLocalStorage', () => ({
  default: () => ['default', vi.fn()],
}));

const renderModal = (props = {}) =>
  render(
    <MantineProvider>
      <ServerGroupsManagerModal isOpen onClose={vi.fn()} {...props} />
    </MantineProvider>
  );

describe('ServerGroupsManagerModal', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('opens without Mantine Tooltip errors', async () => {
    expect(() => renderModal()).not.toThrow();

    await waitFor(() => {
      expect(screen.getByText('Pool A')).toBeInTheDocument();
      expect(screen.getByText('Pool B')).toBeInTheDocument();
      expect(screen.getByText('Accounts')).toBeInTheDocument();
    });
  });
});
