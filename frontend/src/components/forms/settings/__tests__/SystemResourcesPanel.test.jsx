import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../../../../api', () => ({
  default: { getSystemResources: vi.fn() },
}));

vi.mock('lucide-react', () => ({ RefreshCw: () => null }));

vi.mock('@mantine/core', () => {
  const Wrapper = ({ children }) => <div>{children}</div>;
  return {
    Button: ({ children, onClick }) => (
      <button onClick={onClick}>{children}</button>
    ),
    Group: Wrapper,
    Paper: Wrapper,
    Progress: ({ value }) => <div data-testid="progress">{value}</div>,
    SimpleGrid: Wrapper,
    Stack: Wrapper,
    Text: Wrapper,
  };
});

import API from '../../../../api';
import SystemResourcesPanel from '../SystemResourcesPanel.jsx';

describe('SystemResourcesPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    API.getSystemResources.mockResolvedValue({
      process: {
        memory_bytes: 203.4 * 1024 ** 2,
        cpu_percent: 1.2,
        threads: 4,
        started_at: 1_789_497_600,
      },
      memory: {
        used_bytes: 1.264 * 1024 ** 3,
        total_bytes: 23.4 * 1024 ** 3,
        host_total_bytes: 23.4 * 1024 ** 3,
        limit_bytes: null,
        limited: false,
        percent: 5.4,
      },
      shared_memory: {
        used_bytes: 1.1 * 1024 ** 2,
        total_bytes: 256 * 1024 ** 2,
        percent: 0.4,
      },
      storage: {
        path: '/data',
        used_bytes: 19.2 * 1024 ** 3,
        total_bytes: 192.7 * 1024 ** 3,
        percent: 10,
      },
    });
  });

  it('separates container, process and shared-memory measurements', async () => {
    const { unmount } = render(<SystemResourcesPanel />);

    await waitFor(() => expect(API.getSystemResources).toHaveBeenCalled());
    expect(screen.getByText('Container memory')).toBeInTheDocument();
    expect(screen.getByText('Shared memory')).toBeInTheDocument();
    expect(screen.getByText('Web process')).toBeInTheDocument();
    expect(screen.getByText('Unlimited')).toBeInTheDocument();
    expect(screen.getByText(/203\.4 MB RSS/)).toBeInTheDocument();
    expect(screen.getByText(/1\.1 MB \/ 256\.0 MB/)).toBeInTheDocument();
    unmount();
  });
});
