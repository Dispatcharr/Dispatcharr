import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MantineProvider } from '@mantine/core';
import ServerGroupsTable from '../ServerGroupsTable';

const renderTable = () =>
  render(
    <MantineProvider>
      <ServerGroupsTable />
    </MantineProvider>
  );

vi.mock('../../../api', () => ({
  default: {
    deleteServerGroup: vi.fn(),
  },
}));

vi.mock('../../../store/serverGroups', () => ({
  default: (selector) =>
    selector({
      serverGroups: [
        { id: 1, name: 'Pool A' },
        { id: 2, name: 'Pool B' },
      ],
      fetchServerGroups: vi.fn().mockResolvedValue(undefined),
    }),
}));

vi.mock('../../../store/playlists', () => ({
  default: (selector) =>
    selector({
      playlists: [
        { id: 10, server_group: 2 },
        { id: 11, server_group: 1 },
      ],
    }),
}));

vi.mock('../../forms/ServerGroup', () => ({
  default: () => null,
}));

describe('ServerGroupsTable', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders server groups without tooltip errors', async () => {
    expect(() => renderTable()).not.toThrow();

    await waitFor(() => {
      expect(screen.getByText('Pool A')).toBeInTheDocument();
      expect(screen.getByText('Pool B')).toBeInTheDocument();
      expect(screen.getByText('Accounts')).toBeInTheDocument();
    });
  });
});
