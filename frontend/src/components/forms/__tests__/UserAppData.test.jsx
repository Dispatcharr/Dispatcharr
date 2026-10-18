import { useState } from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../../../api', () => ({
  default: {
    getUserAppData: vi.fn(),
    getUserAppDataValue: vi.fn(),
    clearUserAppData: vi.fn(),
  },
}));

vi.mock('@mantine/notifications', () => ({
  notifications: { show: vi.fn() },
}));

vi.mock('../../ConfirmationDialog', () => ({
  default: ({
    opened,
    title,
    message,
    onConfirm,
    onClose,
    loading,
    actionKey,
  }) =>
    opened ? (
      <div data-testid="confirm-dialog" data-action-key={actionKey}>
        <div data-testid="confirm-title">{title}</div>
        <div data-testid="confirm-message">{message}</div>
        <button data-testid="confirm-ok" onClick={onConfirm} disabled={loading}>
          Clear
        </button>
        <button data-testid="confirm-cancel" onClick={onClose}>
          Cancel
        </button>
      </div>
    ) : null,
}));

vi.mock('lucide-react', () => ({
  Eye: () => <svg data-testid="icon-view" />,
  SquareMinus: () => <svg data-testid="icon-clear" />,
}));

vi.mock('../../tables/CustomTable', () => ({
  CustomTable: ({ table }) => (
    <div data-testid="custom-table">
      {table.data.map((row) => (
        <div key={row.id}>
          {table.columns.map((column) => {
            if (column.id === 'actions') {
              return (
                <span key="actions">
                  {table.bodyCellRenderFns.actions({
                    row: { original: row },
                  })}
                </span>
              );
            }
            const value = row[column.accessorKey];
            return (
              <span key={column.id}>
                {column.cell({
                  getValue: () => value,
                  row: { original: row },
                })}
              </span>
            );
          })}
        </div>
      ))}
    </div>
  ),
  useTable: (options) => options,
}));

vi.mock('@mantine/core', () => ({
  ActionIcon: ({ children, onClick, 'aria-label': ariaLabel }) => (
    <button aria-label={ariaLabel} onClick={onClick}>
      {children}
    </button>
  ),
  Button: ({ children, onClick, disabled, loading, leftSection }) => (
    <button onClick={onClick} disabled={disabled || loading}>
      {leftSection}
      {children}
    </button>
  ),
  Box: ({ children, style }) => (
    <div data-testid="table-scroll" style={style}>
      {children}
    </div>
  ),
  Center: ({ children }) => <div>{children}</div>,
  Group: ({ children }) => <div>{children}</div>,
  Loader: () => <div data-testid="loader" />,
  Stack: ({ children }) => <div>{children}</div>,
  Code: ({ children }) => <pre data-testid="view-json">{children}</pre>,
  Modal: ({ children, opened, title }) =>
    opened ? (
      <div data-testid="view-modal">
        <div data-testid="view-title">{title}</div>
        {children}
      </div>
    ) : null,
  Text: ({ children }) => <span>{children}</span>,
  useMantineTheme: () => ({
    tailwind: { red: { 6: '#e53e3e' } },
  }),
  Tooltip: ({ children, label }) => (
    <span data-testid="tooltip" data-label={label}>
      {children}
    </span>
  ),
}));

import API from '../../../api';
import { notifications } from '@mantine/notifications';
import useWarningsStore from '../../../store/warnings';
import UserAppData from '../UserAppData';

const summary = {
  limits: {
    max_value_bytes: 131072,
    max_total_bytes: 1048576,
    max_apps: 25,
  },
  total_bytes: 42,
  apps: [
    { key: 'com.example.one', bytes: 20 },
    { key: 'com.example.two', bytes: 22 },
  ],
};

describe('UserAppData', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useWarningsStore.setState({
      suppressedWarnings: {},
      actionPreferences: {},
    });
    vi.mocked(API.getUserAppData).mockResolvedValue(summary);
    vi.mocked(API.clearUserAppData).mockResolvedValue(null);
  });

  it('lists app keys and sizes', async () => {
    render(<UserAppData userId={7} username="viewer" />);

    await waitFor(() => {
      expect(API.getUserAppData).toHaveBeenCalledWith(7);
    });
    expect(await screen.findByText('com.example.one')).toBeInTheDocument();
    expect(screen.getByText('com.example.two')).toBeInTheDocument();
    expect(screen.getByTestId('table-scroll')).toHaveStyle({
      maxHeight: '320px',
      overflowY: 'auto',
    });
    expect(
      screen.getAllByTestId('tooltip').map((node) => node.getAttribute('data-label'))
    ).toEqual(['View', 'Clear', 'View', 'Clear']);
    expect(screen.getByText('20 B')).toBeInTheDocument();
    expect(screen.getByText('22 B')).toBeInTheDocument();
  });

  it('shows an empty state when nothing is stored', async () => {
    vi.mocked(API.getUserAppData).mockResolvedValue({
      limits: summary.limits,
      total_bytes: 0,
      apps: [],
    });

    render(<UserAppData userId={7} username="viewer" />);

    expect(
      await screen.findByText('No app data stored for this user.')
    ).toBeInTheDocument();
    expect(screen.queryByTestId('custom-table')).not.toBeInTheDocument();
  });

  it('shows the stored JSON for one app', async () => {
    vi.mocked(API.getUserAppDataValue).mockResolvedValue({
      theme: 'dark',
      lastChannel: 42,
    });

    render(<UserAppData userId={7} username="viewer" />);
    await screen.findByText('com.example.one');

    fireEvent.click(screen.getByRole('button', { name: 'View com.example.one' }));

    expect(await screen.findByTestId('view-title')).toHaveTextContent(
      'com.example.one'
    );
    expect(screen.getByTestId('view-json').textContent).toContain(
      '"theme": "dark"'
    );
    expect(API.getUserAppDataValue).toHaveBeenCalledWith(7, 'com.example.one');
  });

  it('clears one app after confirmation', async () => {
    render(<UserAppData userId={7} username="viewer" />);
    await screen.findByText('com.example.one');

    fireEvent.click(
      screen.getByRole('button', { name: 'Clear com.example.one' })
    );
    expect(screen.getByTestId('confirm-dialog')).toHaveAttribute(
      'data-action-key',
      'clear-app-data'
    );
    expect(screen.getByTestId('confirm-title')).toHaveTextContent(
      'Confirm App Data Clear'
    );
    expect(screen.getByTestId('confirm-message').textContent).toContain(
      'Username: viewer'
    );
    expect(screen.getByTestId('confirm-message').textContent).toContain(
      'com.example.one'
    );

    vi.mocked(API.getUserAppData).mockResolvedValue({
      ...summary,
      apps: [{ key: 'com.example.two', bytes: 22 }],
      total_bytes: 22,
    });

    fireEvent.click(screen.getByTestId('confirm-ok'));

    await waitFor(() => {
      expect(API.clearUserAppData).toHaveBeenCalledWith(7, 'com.example.one');
    });
    expect(notifications.show).toHaveBeenCalled();
    await waitFor(() => {
      expect(screen.queryByText('com.example.one')).not.toBeInTheDocument();
    });
  });

  it('clears all apps from the footer action after confirmation', async () => {
    const Harness = () => {
      const [clearAll, setClearAll] = useState(null);
      return (
        <>
          <UserAppData
            userId={7}
            username="viewer"
            onClearAllChange={setClearAll}
          />
          {clearAll && (
            <button type="button" onClick={clearAll.clear}>
              Clear all
            </button>
          )}
        </>
      );
    };

    render(<Harness />);
    await screen.findByText('com.example.one');
    fireEvent.click(await screen.findByRole('button', { name: 'Clear all' }));
    expect(screen.getByTestId('confirm-dialog')).toHaveAttribute(
      'data-action-key',
      'clear-all-app-data'
    );
    expect(screen.getByTestId('confirm-message').textContent).toContain(
      'Username: viewer'
    );
    fireEvent.click(screen.getByTestId('confirm-ok'));

    await waitFor(() => {
      expect(API.clearUserAppData).toHaveBeenCalledWith(7, null);
    });
  });

  it('skips the dialog when that warning is suppressed', async () => {
    useWarningsStore.setState({
      suppressedWarnings: { 'clear-app-data': true },
      actionPreferences: {},
    });

    render(<UserAppData userId={7} username="viewer" />);
    await screen.findByText('com.example.one');

    fireEvent.click(
      screen.getByRole('button', { name: 'Clear com.example.one' })
    );

    expect(screen.queryByTestId('confirm-dialog')).not.toBeInTheDocument();
    await waitFor(() => {
      expect(API.clearUserAppData).toHaveBeenCalledWith(7, 'com.example.one');
    });
  });

  it('shows an error state instead of empty when load fails', async () => {
    vi.mocked(API.getUserAppData).mockRejectedValue(new Error('forbidden'));

    render(<UserAppData userId={7} username="viewer" />);

    expect(
      await screen.findByText('Could not load app data for this user.')
    ).toBeInTheDocument();
    expect(
      screen.queryByText('No app data stored for this user.')
    ).not.toBeInTheDocument();
  });
});
