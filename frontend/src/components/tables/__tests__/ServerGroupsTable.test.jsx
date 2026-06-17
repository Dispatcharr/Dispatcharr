import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MantineProvider } from '@mantine/core';
import ServerGroupsTable from '../ServerGroupsTable';

const mockServerGroupsState = vi.hoisted(() => ({
  serverGroups: [
    { id: 1, name: 'Pool A' },
    { id: 2, name: 'Pool B' },
  ],
  isLoading: false,
  error: null,
  fetchServerGroups: vi.fn().mockResolvedValue(undefined),
}));

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
  default: (selector) => selector(mockServerGroupsState),
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
    mockServerGroupsState.serverGroups = [
      { id: 1, name: 'Pool A' },
      { id: 2, name: 'Pool B' },
    ];
    mockServerGroupsState.isLoading = false;
    mockServerGroupsState.error = null;
    mockServerGroupsState.fetchServerGroups = vi
      .fn()
      .mockResolvedValue(undefined);
  });

  it('renders server groups without tooltip errors', async () => {
    expect(() => renderTable()).not.toThrow();

    await waitFor(() => {
      expect(screen.getByText('Pool A')).toBeInTheDocument();
      expect(screen.getByText('Pool B')).toBeInTheDocument();
      expect(screen.getByText('Accounts')).toBeInTheDocument();
    });
  });

  it('shows store error message when fetch fails', async () => {
    mockServerGroupsState.serverGroups = [];
    mockServerGroupsState.error = 'Failed to load server groups.';

    renderTable();

    await waitFor(() => {
      expect(
        screen.getByText('Failed to load server groups.')
      ).toBeInTheDocument();
    });
  });
});
