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
    deleteConnectIntegration: vi.fn(),
    updateConnectIntegration: vi.fn(),
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
    recording_start: 'Recording Started',
  },
}));

// ── ConnectionForm mock ────────────────────────────────────────────────────────
vi.mock('../../components/forms/Connection', () => ({
  default: ({ connection, isOpen, onClose }) =>
    isOpen ? (
      <div data-testid="connection-form">
        <div data-testid="connection-form-id">{connection?.id ?? 'new'}</div>
        <button data-testid="connection-form-close" onClick={onClose}>
          Close
        </button>
      </div>
    ) : null,
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
  SquarePlus: () => <svg data-testid="icon-square-plus" />,
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
  Box: ({ children, display, style }) => (
    <div data-display={display} style={style}>
      {children}
    </div>
  ),
  Button: ({ children, onClick, variant, color, size, leftSection }) => (
    <button
      onClick={onClick}
      data-variant={variant}
      data-color={color}
      data-size={size}
    >
      {leftSection}
      {children}
    </button>
  ),
  Card: ({ children }) => <div data-testid="card">{children}</div>,
  Flex: ({ children }) => <div>{children}</div>,
  Group: ({ children }) => <div>{children}</div>,
  Stack: ({ children }) => <div>{children}</div>,
  Switch: ({ label, checked, onChange }) => (
    <label>
      <input
        type="checkbox"
        data-testid="toggle-switch"
        checked={checked ?? false}
        onChange={onChange}
      />
      {label}
    </label>
  ),
  Text: ({ children, fw, size }) => (
    <span data-fw={fw} data-size={size}>
      {children}
    </span>
  ),
  Tooltip: ({ children, label }) => <div data-tooltip={label}>{children}</div>,
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
  useMantineTheme: () => ({
    tailwind: { green: { 5: '#22c55e' } },
  }),
}));

// ── Imports after mocks ────────────────────────────────────────────────────────
import ConnectPage from '../Connect';
import API from '../../api';
import useConnectStore from '../../store/connect';

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

const setupStore = (overrides = {}) => {
  const fetchIntegrations = vi.fn();
  vi.mocked(useConnectStore).mockReturnValue({
    integrations: [],
    isLoading: false,
    fetchIntegrations,
    ...overrides,
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

const expandLogs = () => {
  fireEvent.click(screen.getByTestId('logs-toggle'));
};

// ──────────────────────────────────────────────────────────────────────────────

describe('ConnectPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(API.deleteConnectIntegration).mockResolvedValue(undefined);
    vi.mocked(API.updateConnectIntegration).mockResolvedValue(undefined);
    setupApiResponse();
  });

  // ── Initialization ─────────────────────────────────────────────────────────

  describe('initialization', () => {
    it('calls fetchIntegrations on mount', () => {
      const { fetchIntegrations } = setupStore();
      render(<ConnectPage />);
      expect(fetchIntegrations).toHaveBeenCalledTimes(1);
    });
  });

  // ── Loading state ──────────────────────────────────────────────────────────

  describe('loading state', () => {
    it('shows loading indicator when isLoading is true', () => {
      setupStore({ isLoading: true });
      render(<ConnectPage />);
      expect(screen.getByText('Loading...')).toBeInTheDocument();
    });

    it('does not show loading indicator when isLoading is false', () => {
      setupStore({ isLoading: false });
      render(<ConnectPage />);
      expect(screen.queryByText('Loading...')).not.toBeInTheDocument();
    });
  });

  // ── Integration list ───────────────────────────────────────────────────────

  describe('integration list', () => {
    it('renders a card for each integration', () => {
      setupStore({
        integrations: [
          makeIntegration({ id: 1 }),
          makeIntegration({ id: 2, name: 'Other' }),
        ],
      });
      render(<ConnectPage />);
      // Two integration cards + one logs section card
      expect(screen.getAllByTestId('card')).toHaveLength(3);
    });

    it('renders integration names', () => {
      setupStore({ integrations: [makeIntegration({ name: 'Plex Hook' })] });
      render(<ConnectPage />);
      expect(screen.getByText('Plex Hook')).toBeInTheDocument();
    });

    it('shows no integration cards when integrations list is empty', () => {
      setupStore({ integrations: [] });
      render(<ConnectPage />);
      // Only the logs section card remains
      expect(screen.getAllByTestId('card')).toHaveLength(1);
    });
  });

  // ── New Connection button ──────────────────────────────────────────────────

  describe('"New Connection" button', () => {
    it('renders the New Connection button', () => {
      setupStore();
      render(<ConnectPage />);
      expect(screen.getByText('New Connection')).toBeInTheDocument();
    });

    it('ConnectionForm is not visible initially', () => {
      setupStore();
      render(<ConnectPage />);
      expect(screen.queryByTestId('connection-form')).not.toBeInTheDocument();
    });

    it('opens ConnectionForm with no connection when New Connection is clicked', () => {
      setupStore();
      render(<ConnectPage />);
      fireEvent.click(screen.getByText('New Connection'));
      expect(screen.getByTestId('connection-form')).toBeInTheDocument();
      expect(screen.getByTestId('connection-form-id')).toHaveTextContent('new');
    });

    it('closes ConnectionForm when its close button is clicked', () => {
      setupStore();
      render(<ConnectPage />);
      fireEvent.click(screen.getByText('New Connection'));
      fireEvent.click(screen.getByTestId('connection-form-close'));
      expect(screen.queryByTestId('connection-form')).not.toBeInTheDocument();
    });
  });

  // ── Edit connection ────────────────────────────────────────────────────────

  describe('edit connection', () => {
    it('opens ConnectionForm with the integration when Edit is clicked', () => {
      const integration = makeIntegration({ id: 7, name: 'My Hook' });
      setupStore({ integrations: [integration] });
      render(<ConnectPage />);
      fireEvent.click(screen.getByText('Edit'));
      expect(screen.getByTestId('connection-form')).toBeInTheDocument();
      expect(screen.getByTestId('connection-form-id')).toHaveTextContent('7');
    });
  });

  // ── Delete connection ──────────────────────────────────────────────────────

  describe('delete connection', () => {
    it('calls deleteConnectIntegration with the integration id when Delete is clicked', async () => {
      setupStore({ integrations: [makeIntegration({ id: 3 })] });
      render(<ConnectPage />);
      fireEvent.click(screen.getByText('Delete'));
      await waitFor(() => {
        expect(API.deleteConnectIntegration).toHaveBeenCalledWith(3);
      });
    });
  });
});

// ──────────────────────────────────────────────────────────────────────────────

describe('IntegrationRow', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(API.updateConnectIntegration).mockResolvedValue(undefined);
    vi.mocked(API.deleteConnectIntegration).mockResolvedValue(undefined);
    setupApiResponse();
  });

  const renderRow = (integrationOverrides = {}) => {
    const integration = makeIntegration(integrationOverrides);
    const { fetchIntegrations } = setupStore({ integrations: [integration] });
    render(<ConnectPage />);
    return { integration, fetchIntegrations };
  };

  // ── Type icons ─────────────────────────────────────────────────────────────

  describe('type icons', () => {
    it('shows webhook icon for webhook type', () => {
      renderRow({ type: 'webhook' });
      expect(screen.getAllByTestId('icon-webhook').length).toBeGreaterThan(0);
    });

    it('shows file code icon for non-webhook type', () => {
      renderRow({ type: 'script' });
      expect(screen.getByTestId('icon-file-code')).toBeInTheDocument();
    });
  });

  // ── Target display ─────────────────────────────────────────────────────────

  describe('target display', () => {
    it('shows webhook URL for webhook type', () => {
      renderRow({
        type: 'webhook',
        config: { url: 'https://hooks.example.com' },
      });
      expect(screen.getByText('https://hooks.example.com')).toBeInTheDocument();
    });

    it('shows script path for non-webhook type', () => {
      renderRow({ type: 'script', config: { path: '/scripts/my-script.sh' } });
      expect(screen.getByText('/scripts/my-script.sh')).toBeInTheDocument();
    });
  });

  // ── Enabled switch ─────────────────────────────────────────────────────────

  describe('enabled switch', () => {
    it('renders checked when integration.enabled is true', () => {
      renderRow({ enabled: true });
      expect(screen.getByTestId('toggle-switch')).toBeChecked();
    });

    it('renders unchecked when integration.enabled is false', () => {
      renderRow({ enabled: false });
      expect(screen.getByTestId('toggle-switch')).not.toBeChecked();
    });

    it('calls updateConnectIntegration with toggled enabled value on toggle', async () => {
      renderRow({ id: 5, enabled: true });
      fireEvent.click(screen.getByTestId('toggle-switch'));
      await waitFor(() => {
        expect(API.updateConnectIntegration).toHaveBeenCalledWith(
          5,
          expect.objectContaining({ enabled: false })
        );
      });
    });

    it('toggles from false to true', async () => {
      renderRow({ id: 5, enabled: false });
      fireEvent.click(screen.getByTestId('toggle-switch'));
      await waitFor(() => {
        expect(API.updateConnectIntegration).toHaveBeenCalledWith(
          5,
          expect.objectContaining({ enabled: true })
        );
      });
    });

    it('does not throw when updateConnectIntegration fails', async () => {
      vi.mocked(API.updateConnectIntegration).mockRejectedValue(
        new Error('fail')
      );
      vi.spyOn(console, 'error').mockImplementation(() => {});
      renderRow({ enabled: true });

      await expect(
        waitFor(() => fireEvent.click(screen.getByTestId('toggle-switch')))
      ).resolves.not.toThrow();
    });
  });

  // ── Subscription badges ────────────────────────────────────────────────────

  describe('subscription badges', () => {
    it('renders a badge for each enabled subscription', () => {
      renderRow({
        subscriptions: [
          { event: 'channel_start', enabled: true },
          { event: 'recording_start', enabled: true },
        ],
      });
      expect(screen.getByText('Channel Started')).toBeInTheDocument();
      expect(screen.getByText('Recording Started')).toBeInTheDocument();
    });

    it('does not render badges for disabled subscriptions', () => {
      renderRow({
        subscriptions: [
          { event: 'channel_start', enabled: true },
          { event: 'channel_stop', enabled: false },
        ],
      });
      expect(screen.getByText('Channel Started')).toBeInTheDocument();
      expect(screen.queryByText('Channel Stopped')).not.toBeInTheDocument();
    });

    it('falls back to the raw event name when not in SUBSCRIPTION_EVENTS', () => {
      renderRow({
        subscriptions: [{ event: 'custom_event', enabled: true }],
      });
      expect(screen.getByText('custom_event')).toBeInTheDocument();
    });
  });

  // ── Action buttons ─────────────────────────────────────────────────────────

  describe('action buttons', () => {
    it('opens ConnectionForm with the integration when Edit is clicked', () => {
      const integration = makeIntegration({ id: 9, name: 'Test Hook' });
      setupStore({ integrations: [integration] });
      render(<ConnectPage />);
      fireEvent.click(screen.getByText('Edit'));
      expect(screen.getByTestId('connection-form-id')).toHaveTextContent('9');
    });

    it('calls deleteConnectIntegration with the correct id when Delete is clicked', async () => {
      renderRow({ id: 11 });
      fireEvent.click(screen.getByText('Delete'));
      await waitFor(() => {
        expect(API.deleteConnectIntegration).toHaveBeenCalledWith(11);
      });
    });
  });
});

// ──────────────────────────────────────────────────────────────────────────────

describe('ConnectLogsSection', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(API.deleteConnectIntegration).mockResolvedValue(undefined);
    vi.mocked(API.updateConnectIntegration).mockResolvedValue(undefined);
    setupApiResponse();
    setupStore();
  });

  // ── Collapsed by default ───────────────────────────────────────────────────

  describe('collapsed state', () => {
    it('renders the Logs section header', () => {
      render(<ConnectPage />);
      expect(screen.getByText('Logs')).toBeInTheDocument();
    });

    it('does not render the log table when collapsed', () => {
      render(<ConnectPage />);
      expect(screen.queryByTestId('custom-table')).not.toBeInTheDocument();
    });

    it('does not fetch logs when collapsed', () => {
      render(<ConnectPage />);
      expect(API.getConnectLogs).not.toHaveBeenCalled();
    });
  });

  // ── Expanding the section ──────────────────────────────────────────────────

  describe('expanding the section', () => {
    it('renders the log table and filters once expanded', async () => {
      render(<ConnectPage />);
      expandLogs();
      await waitFor(() => {
        expect(screen.getByTestId('custom-table')).toBeInTheDocument();
      });
      expect(screen.getByTestId('select-type')).toBeInTheDocument();
      expect(screen.getByTestId('select-integration')).toBeInTheDocument();
    });

    it('fetches logs once expanded', async () => {
      render(<ConnectPage />);
      expandLogs();
      await waitFor(() => {
        expect(API.getConnectLogs).toHaveBeenCalledWith(
          expect.objectContaining({ page: 1, page_size: 50 })
        );
      });
    });

    it('collapses again when toggled a second time', async () => {
      render(<ConnectPage />);
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
      setupStore({
        integrations: [makeIntegration({ id: 3, name: 'Plex Hook' })],
      });
      render(<ConnectPage />);
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
      render(<ConnectPage />);
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
      render(<ConnectPage />);
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
