import {
  render,
  screen,
  fireEvent,
  waitFor,
  act,
  within,
} from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

// ── API mock ───────────────────────────────────────────────────────────────────
vi.mock('../../api', () => ({
  default: {
    getConnectLogs: vi.fn(),
  },
}));

// ── Store mock ─────────────────────────────────────────────────────────────────
vi.mock('../../store/connect', () => ({
  default: vi.fn(),
}));

// ── Constants mock ─────────────────────────────────────────────────────────────
vi.mock('../../constants', () => ({
  SUBSCRIPTION_EVENTS: {
    channel_start: 'Channel Started',
    channel_stop: 'Channel Stopped',
  },
}));

// ── CustomTable mock ───────────────────────────────────────────────────────────
vi.mock('../../components/tables/CustomTable', () => ({
  CustomTable: () => <div data-testid="custom-table" />,
  useTable: vi.fn(() => ({})),
}));

// ── Utils mock ─────────────────────────────────────────────────────────────────
vi.mock('../../utils', () => ({
  copyToClipboard: vi.fn(),
}));

// ── lucide-react ───────────────────────────────────────────────────────────────
vi.mock('lucide-react', () => ({
  FileCode: () => <svg data-testid="icon-file-code" />,
  Webhook: () => <svg data-testid="icon-webhook" />,
}));

// ── @mantine/core ──────────────────────────────────────────────────────────────
vi.mock('@mantine/core', () => ({
  Badge: ({ children, color, variant }) => (
    <span data-testid="badge" data-color={color} data-variant={variant}>
      {children}
    </span>
  ),
  Box: ({ children }) => <div>{children}</div>,
  Group: ({ children }) => <div>{children}</div>,
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
  Paper: ({ children }) => <div>{children}</div>,
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
  Text: ({ children, size }) => <span data-size={size}>{children}</span>,
  Title: ({ children, order }) => <h3 data-order={order}>{children}</h3>,
}));

// ── Imports after mocks ────────────────────────────────────────────────────────
import ConnectLogsPage from '../ConnectLogs';
import API from '../../api';
import useConnectStore from '../../store/connect';

// ── Shared helpers ─────────────────────────────────────────────────────────────
const makeIntegration = (overrides = {}) => ({
  id: 1,
  name: 'My Webhook',
  type: 'webhook',
  ...overrides,
});

const setupStore = ({
  integrations = [],
  fetchIntegrations = vi.fn(),
} = {}) => {
  vi.mocked(useConnectStore).mockReturnValue({
    integrations,
    fetchIntegrations,
  });
  return { fetchIntegrations };
};

const setupApiResponse = (overrides = {}) => {
  vi.mocked(API.getConnectLogs).mockResolvedValue({
    results: [],
    count: 0,
    ...overrides,
  });
};

// ──────────────────────────────────────────────────────────────────────────────

describe('ConnectLogsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    setupApiResponse();
    setupStore();
  });

  // ── Rendering ──────────────────────────────────────────────────────────────

  describe('rendering', () => {
    it('renders the "Connect Logs" title', () => {
      render(<ConnectLogsPage />);
      expect(screen.getByText('Connect Logs')).toBeInTheDocument();
    });

    it('renders the type filter select', () => {
      render(<ConnectLogsPage />);
      expect(screen.getByTestId('select-type')).toBeInTheDocument();
    });

    it('renders the integration filter select', () => {
      render(<ConnectLogsPage />);
      expect(screen.getByTestId('select-integration')).toBeInTheDocument();
    });

    it('renders the table', () => {
      render(<ConnectLogsPage />);
      expect(screen.getByTestId('custom-table')).toBeInTheDocument();
    });

    it('renders the page size select and pagination', () => {
      render(<ConnectLogsPage />);
      expect(screen.getByTestId('page-size-select')).toBeInTheDocument();
      expect(screen.getByTestId('pagination')).toBeInTheDocument();
    });
  });

  // ── Integration initialization ─────────────────────────────────────────────

  describe('integration initialization', () => {
    it('calls fetchIntegrations on mount when integrations list is empty', async () => {
      const { fetchIntegrations } = setupStore({ integrations: [] });
      render(<ConnectLogsPage />);
      await waitFor(() => {
        expect(fetchIntegrations).toHaveBeenCalled();
      });
    });

    it('does not call fetchIntegrations when integrations are already loaded', async () => {
      const { fetchIntegrations } = setupStore({
        integrations: [makeIntegration()],
      });
      render(<ConnectLogsPage />);
      await waitFor(() => {
        expect(API.getConnectLogs).toHaveBeenCalled();
      });
      expect(fetchIntegrations).not.toHaveBeenCalled();
    });
  });

  // ── API calls ──────────────────────────────────────────────────────────────

  describe('API calls', () => {
    it('calls getConnectLogs on mount with page=1 and page_size=50', async () => {
      render(<ConnectLogsPage />);
      await waitFor(() => {
        expect(API.getConnectLogs).toHaveBeenCalledWith(
          expect.objectContaining({ page: 1, page_size: 50 })
        );
      });
    });

    it('does not include type in params when type filter is empty', async () => {
      render(<ConnectLogsPage />);
      await waitFor(() => {
        expect(API.getConnectLogs).toHaveBeenCalled();
      });
      const callArgs = vi.mocked(API.getConnectLogs).mock.calls[0][0];
      expect(callArgs).not.toHaveProperty('type');
    });

    it('does not include integration in params when integration filter is empty', async () => {
      render(<ConnectLogsPage />);
      await waitFor(() => {
        expect(API.getConnectLogs).toHaveBeenCalled();
      });
      const callArgs = vi.mocked(API.getConnectLogs).mock.calls[0][0];
      expect(callArgs).not.toHaveProperty('integration');
    });

    it('handles an array API response', async () => {
      vi.mocked(API.getConnectLogs).mockResolvedValue([]);
      render(<ConnectLogsPage />);
      await waitFor(() => {
        expect(API.getConnectLogs).toHaveBeenCalled();
        expect(screen.queryByTestId('loading-overlay')).not.toBeInTheDocument();
      });
    });

    it('extracts count from a paginated API response', async () => {
      vi.mocked(API.getConnectLogs).mockResolvedValue({
        results: [],
        count: 77,
      });
      render(<ConnectLogsPage />);
      await waitFor(() => {
        expect(screen.getByText(/77/)).toBeInTheDocument();
      });
    });
  });

  // ── Loading state ──────────────────────────────────────────────────────────

  describe('loading state', () => {
    it('shows LoadingOverlay while the fetch is in progress', async () => {
      let resolve;
      vi.mocked(API.getConnectLogs).mockReturnValue(
        new Promise((r) => {
          resolve = r;
        })
      );
      render(<ConnectLogsPage />);
      await waitFor(() => {
        expect(screen.getByTestId('loading-overlay')).toBeInTheDocument();
      });
      await act(async () => {
        resolve({ results: [], count: 0 });
      });
    });

    it('hides LoadingOverlay after the fetch completes', async () => {
      render(<ConnectLogsPage />);
      await waitFor(() => {
        expect(screen.queryByTestId('loading-overlay')).not.toBeInTheDocument();
      });
    });
  });

  // ── Pagination string ──────────────────────────────────────────────────────

  describe('pagination string', () => {
    it('shows the correct range and total when results are returned', async () => {
      vi.mocked(API.getConnectLogs).mockResolvedValue({
        results: [],
        count: 120,
      });
      render(<ConnectLogsPage />);
      await waitFor(() => {
        expect(screen.getByText('Showing 1-50 of 120')).toBeInTheDocument();
      });
    });

    it('shows "Showing 1-0 of 0" when there are no logs', async () => {
      render(<ConnectLogsPage />);
      await waitFor(() => {
        expect(screen.getByText('Showing 1-0 of 0')).toBeInTheDocument();
      });
    });
  });

  // ── Page count ─────────────────────────────────────────────────────────────

  describe('page count', () => {
    it('computes pageCount as ceil(count / pageSize)', async () => {
      vi.mocked(API.getConnectLogs).mockResolvedValue({
        results: [],
        count: 110,
      });
      render(<ConnectLogsPage />);
      await waitFor(() => {
        // ceil(110 / 50) = 3
        expect(screen.getByTestId('pagination-total')).toHaveTextContent('3');
      });
    });

    it('shows at least 1 page when count is 0', async () => {
      render(<ConnectLogsPage />);
      await waitFor(() => {
        expect(screen.getByTestId('pagination-total')).toHaveTextContent('1');
      });
    });
  });

  // ── Type filter ────────────────────────────────────────────────────────────

  describe('type filter', () => {
    it('populates type filter with All, Webhooks, Scripts options', () => {
      render(<ConnectLogsPage />);
      const typeSelect = screen.getByTestId('select-type');
      expect(
        within(typeSelect).getByRole('option', { name: 'All' })
      ).toBeInTheDocument();
      expect(
        within(typeSelect).getByRole('option', { name: 'Webhooks' })
      ).toBeInTheDocument();
      expect(
        within(typeSelect).getByRole('option', { name: 'Scripts' })
      ).toBeInTheDocument();
    });

    it('refetches with type param when type filter changes', async () => {
      render(<ConnectLogsPage />);
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

    it('omits type from params when filter is reset to empty', async () => {
      render(<ConnectLogsPage />);
      fireEvent.change(screen.getByTestId('select-type'), {
        target: { value: 'webhook' },
      });
      await waitFor(() => {
        expect(API.getConnectLogs).toHaveBeenCalledWith(
          expect.objectContaining({ type: 'webhook' })
        );
      });

      vi.mocked(API.getConnectLogs).mockClear();
      fireEvent.change(screen.getByTestId('select-type'), {
        target: { value: '' },
      });
      await waitFor(() => {
        expect(API.getConnectLogs).toHaveBeenCalled();
        const args = vi.mocked(API.getConnectLogs).mock.calls[0][0];
        expect(args).not.toHaveProperty('type');
      });
    });
  });

  // ── Integration filter ─────────────────────────────────────────────────────

  describe('integration filter', () => {
    it('populates integration select from store integrations', async () => {
      setupStore({
        integrations: [makeIntegration({ id: 3, name: 'Plex Hook' })],
      });
      render(<ConnectLogsPage />);
      await waitFor(() => {
        expect(
          screen.getByRole('option', { name: 'Plex Hook' })
        ).toBeInTheDocument();
      });
    });

    it('refetches with integration param when integration filter changes', async () => {
      setupStore({
        integrations: [makeIntegration({ id: 5, name: 'Hook 5' })],
      });
      render(<ConnectLogsPage />);
      await waitFor(() => expect(API.getConnectLogs).toHaveBeenCalledTimes(1));

      fireEvent.change(screen.getByTestId('select-integration'), {
        target: { value: '5' },
      });

      await waitFor(() => {
        expect(API.getConnectLogs).toHaveBeenCalledWith(
          expect.objectContaining({ integration: '5' })
        );
      });
    });
  });

  // ── Page size change ───────────────────────────────────────────────────────

  describe('page size change', () => {
    it('refetches with new page_size when page size is changed', async () => {
      render(<ConnectLogsPage />);
      await waitFor(() => expect(API.getConnectLogs).toHaveBeenCalledTimes(1));

      fireEvent.change(screen.getByTestId('page-size-select'), {
        target: { value: '100' },
      });

      await waitFor(() => {
        expect(API.getConnectLogs).toHaveBeenCalledWith(
          expect.objectContaining({ page_size: 100 })
        );
      });
    });

    it('resets to page 1 when page size changes', async () => {
      render(<ConnectLogsPage />);
      await waitFor(() => expect(API.getConnectLogs).toHaveBeenCalledTimes(1));

      fireEvent.change(screen.getByTestId('page-size-select'), {
        target: { value: '25' },
      });

      await waitFor(() => {
        expect(API.getConnectLogs).toHaveBeenCalledWith(
          expect.objectContaining({ page: 1 })
        );
      });
    });
  });

  // ── Page navigation ────────────────────────────────────────────────────────

  describe('page navigation', () => {
    it('refetches with page 2 when the next page button is clicked', async () => {
      vi.mocked(API.getConnectLogs).mockResolvedValue({
        results: [],
        count: 100,
      });
      render(<ConnectLogsPage />);
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
