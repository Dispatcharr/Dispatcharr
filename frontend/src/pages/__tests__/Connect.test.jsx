import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

// ── API mock ───────────────────────────────────────────────────────────────────
vi.mock('../../api', () => ({
  default: {
    deleteConnectIntegration: vi.fn(),
    updateConnectIntegration: vi.fn(),
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

// ── lucide-react ───────────────────────────────────────────────────────────────
vi.mock('lucide-react', () => ({
  SquarePlus: () => <svg data-testid="icon-square-plus" />,
  Webhook: () => <svg data-testid="icon-webhook" />,
  FileCode: () => <svg data-testid="icon-file-code" />,
  Logs: () => <svg data-testid="icon-logs" />,
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
  Text: ({ children, fw }) => <span data-fw={fw}>{children}</span>,
  Tooltip: ({ children, label }) => <div data-tooltip={label}>{children}</div>,
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

// ──────────────────────────────────────────────────────────────────────────────

describe('ConnectPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(API.deleteConnectIntegration).mockResolvedValue(undefined);
    vi.mocked(API.updateConnectIntegration).mockResolvedValue(undefined);
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
      expect(screen.getAllByTestId('card')).toHaveLength(2);
    });

    it('renders integration names', () => {
      setupStore({ integrations: [makeIntegration({ name: 'Plex Hook' })] });
      render(<ConnectPage />);
      expect(screen.getByText('Plex Hook')).toBeInTheDocument();
    });

    it('shows no cards when integrations list is empty', () => {
      setupStore({ integrations: [] });
      render(<ConnectPage />);
      expect(screen.queryByTestId('card')).not.toBeInTheDocument();
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
      expect(screen.getByTestId('icon-webhook')).toBeInTheDocument();
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
