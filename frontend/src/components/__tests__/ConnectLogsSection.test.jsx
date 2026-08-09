import {
  render,
  screen,
  fireEvent,
  waitFor,
  within,
} from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

// ── API mock ───────────────────────────────────────────────────────────────────
vi.mock('../../api', () => ({
  default: {
    getConnectLogs: vi.fn(),
  },
}));

// ── Constants mock ─────────────────────────────────────────────────────────────
vi.mock('../../constants', () => ({
  SUBSCRIPTION_EVENTS: {
    channel_start: 'Channel Started',
    channel_stop: 'Channel Stopped',
    recording_start: 'Recording Started',
  },
}));

// ── CustomTable mock ───────────────────────────────────────────────────────────
vi.mock('../tables/CustomTable', () => ({
  CustomTable: () => <div data-testid="custom-table" />,
  useTable: vi.fn(() => ({})),
}));

// ── Utils mock ─────────────────────────────────────────────────────────────────
vi.mock('../../utils', () => ({
  copyToClipboard: vi.fn(),
}));

// ── lucide-react ───────────────────────────────────────────────────────────────
vi.mock('lucide-react', () => ({
  Webhook: () => <svg data-testid="icon-webhook" />,
  FileCode: () => <svg data-testid="icon-file-code" />,
  Logs: () => <svg data-testid="icon-logs" />,
  ChevronDown: () => <svg data-testid="icon-chevron-down" />,
}));

// ── @mantine/core ──────────────────────────────────────────────────────────────
vi.mock('@mantine/core', () => ({
  Badge: ({ children, color, variant, size }) => (
    <span
      data-testid="badge"
      data-color={color}
      data-variant={variant}
      data-size={size}
    >
      {children}
    </span>
  ),
  Box: ({ children, style }) => <div style={style}>{children}</div>,
  Card: ({ children }) => <div data-testid="card">{children}</div>,
  Group: ({ children }) => <div>{children}</div>,
  Stack: ({ children }) => <div>{children}</div>,
  Text: ({ children, fw, size }) => (
    <span data-fw={fw} data-size={size}>
      {children}
    </span>
  ),
  Title: ({ children, order }) => <h4 data-order={order}>{children}</h4>,
  ActionIcon: ({ children, onClick }) => (
    <button data-testid="logs-toggle" onClick={onClick}>
      {children}
    </button>
  ),
  LoadingOverlay: ({ visible }) =>
    visible ? <div data-testid="loading-overlay" /> : null,
  NativeSelect: ({ value, onChange, data }) => (
    <select data-testid="page-size-select" value={value} onChange={onChange}>
      {data?.map((d) => (
        <option key={d} value={d}>
          {d}
        </option>
      ))}
    </select>
  ),
  Pagination: ({ total, value, onChange }) => (
    <div data-testid="pagination">
      <span data-testid="pagination-total">{total}</span>
      <button
        data-testid="next-page"
        onClick={() => onChange(value + 1)}
        disabled={value >= total}
      >
        Next
      </button>
    </div>
  ),
  // Distinguish type filter (has 'webhook' option) from integration filter
  Select: ({ data, value, onChange }) => {
    const isTypeFilter = data?.some((d) => d.value === 'webhook');
    return (
      <select
        data-testid={isTypeFilter ? 'select-type' : 'select-integration'}
        value={value ?? ''}
        onChange={(e) => onChange(e.target.value)}
      >
        {data?.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>
    );
  },
}));

// ── Imports after mocks ────────────────────────────────────────────────────────
import ConnectLogsSection from '../ConnectLogsSection';
import API from '../../api';

// ── Shared helpers ─────────────────────────────────────────────────────────────
const makeIntegration = (overrides = {}) => ({
  id: 1,
  name: 'My Webhook',
  type: 'webhook',
  enabled: true,
  config: { url: 'https://example.com/hook' },
  subscriptions: [
    { event: 'channel_start', enabled: true },
    { event: 'channel_stop', enabled: false },
  ],
  ...overrides,
});

const setupApiResponse = (overrides = {}) => {
  vi.mocked(API.getConnectLogs).mockResolvedValue({
    results: [],
    count: 0,
    ...overrides,
  });
};

const expandLogs = () => {
  fireEvent.click(screen.getByTestId('logs-toggle'));
};

// ──────────────────────────────────────────────────────────────────────────────

describe('ConnectLogsSection', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    setupApiResponse();
  });

  // ── Collapsed by default ───────────────────────────────────────────────────

  describe('collapsed state', () => {
    it('renders the Logs section header', () => {
      render(<ConnectLogsSection integrations={[]} />);
      expect(screen.getByText('Logs')).toBeInTheDocument();
    });

    it('does not render the log table when collapsed', () => {
      render(<ConnectLogsSection integrations={[]} />);
      expect(screen.queryByTestId('custom-table')).not.toBeInTheDocument();
    });

    it('does not fetch logs when collapsed', () => {
      render(<ConnectLogsSection integrations={[]} />);
      expect(API.getConnectLogs).not.toHaveBeenCalled();
    });
  });

  // ── Expanding the section ──────────────────────────────────────────────────

  describe('expanding the section', () => {
    it('renders the log table and filters once expanded', async () => {
      render(<ConnectLogsSection integrations={[]} />);
      expandLogs();
      await waitFor(() => {
        expect(screen.getByTestId('custom-table')).toBeInTheDocument();
      });
      expect(screen.getByTestId('select-type')).toBeInTheDocument();
      expect(screen.getByTestId('select-integration')).toBeInTheDocument();
    });

    it('fetches logs once expanded', async () => {
      render(<ConnectLogsSection integrations={[]} />);
      expandLogs();
      await waitFor(() => {
        expect(API.getConnectLogs).toHaveBeenCalledWith(
          expect.objectContaining({ page: 1, page_size: 50 })
        );
      });
    });

    it('collapses again when toggled a second time', async () => {
      render(<ConnectLogsSection integrations={[]} />);
      expandLogs();
      await waitFor(() => {
        expect(screen.getByTestId('custom-table')).toBeInTheDocument();
      });
      expandLogs();
      expect(screen.queryByTestId('custom-table')).not.toBeInTheDocument();
    });
  });

  // ── Filters ─────────────────────────────────────────────────────────────────

  describe('filters', () => {
    it('populates the integration filter from the store', async () => {
      render(
        <ConnectLogsSection
          integrations={[makeIntegration({ id: 3, name: 'Plex Hook' })]}
        />
      );
      expandLogs();
      await waitFor(() => {
        expect(
          within(screen.getByTestId('select-integration')).getByRole(
            'option',
            { name: 'Plex Hook' }
          )
        ).toBeInTheDocument();
      });
    });

    it('refetches with type param when type filter changes', async () => {
      render(<ConnectLogsSection integrations={[]} />);
      expandLogs();
      await waitFor(() => expect(API.getConnectLogs).toHaveBeenCalledTimes(1));

      fireEvent.change(screen.getByTestId('select-type'), {
        target: { value: 'webhook' },
      });

      await waitFor(() => {
        expect(API.getConnectLogs).toHaveBeenCalledWith(
          expect.objectContaining({ type: 'webhook' })
        );
      });
    });
  });

  // ── Pagination ─────────────────────────────────────────────────────────────

  describe('pagination', () => {
    it('refetches with page 2 when the next page button is clicked', async () => {
      vi.mocked(API.getConnectLogs).mockResolvedValue({
        results: [],
        count: 100,
      });
      render(<ConnectLogsSection integrations={[]} />);
      expandLogs();
      await waitFor(() => expect(API.getConnectLogs).toHaveBeenCalledTimes(1));

      fireEvent.click(screen.getByTestId('next-page'));

      await waitFor(() => {
        expect(API.getConnectLogs).toHaveBeenCalledWith(
          expect.objectContaining({ page: 2 })
        );
      });
    });
  });
});
