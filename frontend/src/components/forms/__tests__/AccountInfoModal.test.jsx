import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import AccountInfoModal from '../AccountInfoModal';

// ── Store mocks ────────────────────────────────────────────────────────────────
vi.mock('../../../store/playlists', () => ({ default: vi.fn() }));

// ── Utility mocks ──────────────────────────────────────────────────────────────
vi.mock('../../../utils/notificationUtils.js', () => ({
  showNotification: vi.fn(),
}));

vi.mock('../../../utils/forms/AccountInfoModalUtils.js', () => ({
  formatTimestamp: vi.fn(),
  getTimeRemaining: vi.fn(),
  refreshAccountInfo: vi.fn(),
}));

// ── Mantine core ───────────────────────────────────────────────────────────────
vi.mock('@mantine/core', () => ({
  ActionIcon: ({ children, onClick, loading, disabled }) => (
    <button
      data-testid="action-icon"
      onClick={onClick}
      disabled={disabled || loading}
      data-loading={loading}
    >
      {children}
    </button>
  ),
  Alert: ({ title, children, color }) => (
    <div data-testid="alert" data-color={color}>
      <span data-testid="alert-title">{title}</span>
      <span>{children}</span>
    </div>
  ),
  Badge: ({ children, color }) => (
    <span data-testid="badge" data-color={color}>
      {children}
    </span>
  ),
  Box: ({ children }) => <div>{children}</div>,
  Center: ({ children }) => <div>{children}</div>,
  Divider: () => <hr data-testid="divider" />,
  Group: ({ children }) => <div>{children}</div>,
  Modal: ({ children, opened, onClose, title }) =>
    opened ? (
      <div data-testid="modal">
        <div data-testid="modal-title">{title}</div>
        <button data-testid="modal-close" onClick={onClose}>
          ×
        </button>
        {children}
      </div>
    ) : null,
  Stack: ({ children }) => <div>{children}</div>,
  Table: ({ children }) => <table>{children}</table>,
  TableTbody: ({ children }) => <tbody>{children}</tbody>,
  TableTd: ({ children }) => <td>{children}</td>,
  TableTr: ({ children }) => <tr>{children}</tr>,
  Text: ({ children }) => <span>{children}</span>,
  Tooltip: ({ children, label }) => <div data-tooltip={label}>{children}</div>,
}));

// ── lucide-react ───────────────────────────────────────────────────────────────
vi.mock('lucide-react', () => ({
  AlertTriangle: () => <svg data-testid="icon-alert-triangle" />,
  CheckCircle: () => <svg data-testid="icon-check-circle" />,
  Clock: () => <svg data-testid="icon-clock" />,
  Info: () => <svg data-testid="icon-info" />,
  RefreshCw: () => <svg data-testid="icon-refresh-cw" />,
  Users: () => <svg data-testid="icon-users" />,
  XCircle: () => <svg data-testid="icon-x-circle" />,
}));

// ──────────────────────────────────────────────────────────────────────────────
// Imports after mocks
// ──────────────────────────────────────────────────────────────────────────────
import usePlaylistsStore from '../../../store/playlists';
import { showNotification } from '../../../utils/notificationUtils.js';
import {
  formatTimestamp,
  getTimeRemaining,
  refreshAccountInfo,
} from '../../../utils/forms/AccountInfoModalUtils.js';

// ──────────────────────────────────────────────────────────────────────────────
// Helpers
// ──────────────────────────────────────────────────────────────────────────────
const makeUserInfo = (overrides = {}) => ({
  username: 'testuser',
  status: 'Active',
  exp_date: '9999999999',
  max_connections: '2',
  active_cons: '1',
  created_at: '1700000000',
  ...overrides,
});

const makeProfile = (overrides = {}) => ({
  id: 'profile-1',
  account: { id: 'account-1', is_xtream_codes: true },
  custom_properties: {
    user_info: makeUserInfo(),
  },
  ...overrides,
});

const setupMocks = ({
  profiles = {},
  timeRemaining = '10 days 5 hours',
  formattedTimestamp = 'Nov 14, 2023',
} = {}) => {
  vi.mocked(usePlaylistsStore).mockImplementation((sel) => sel({ profiles }));
  vi.mocked(getTimeRemaining).mockReturnValue(timeRemaining);
  vi.mocked(formatTimestamp).mockReturnValue(formattedTimestamp);
  vi.mocked(refreshAccountInfo).mockResolvedValue({ success: true });
};

const defaultProps = (overrides = {}) => ({
  isOpen: true,
  onClose: vi.fn(),
  profile: makeProfile(),
  onRefresh: vi.fn(),
  ...overrides,
});

// ──────────────────────────────────────────────────────────────────────────────
// Tests
// ──────────────────────────────────────────────────────────────────────────────
describe('AccountInfoModal', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // ── Visibility ─────────────────────────────────────────────────────────────

  describe('visibility', () => {
    it('renders the modal when isOpen is true', () => {
      setupMocks();
      render(<AccountInfoModal {...defaultProps()} />);
      expect(screen.getByTestId('modal')).toBeInTheDocument();
    });

    it('does not render the modal when isOpen is false', () => {
      setupMocks();
      render(<AccountInfoModal {...defaultProps({ isOpen: false })} />);
      expect(screen.queryByTestId('modal')).not.toBeInTheDocument();
    });

    it('calls onClose when modal close button is clicked', () => {
      setupMocks();
      const onClose = vi.fn();
      render(<AccountInfoModal {...defaultProps({ onClose })} />);
      fireEvent.click(screen.getByTestId('modal-close'));
      expect(onClose).toHaveBeenCalled();
    });
  });

  // ── Rendering with profile data ────────────────────────────────────────────

  describe('rendering with profile data', () => {
    it('renders the username', () => {
      setupMocks();
      render(<AccountInfoModal {...defaultProps()} />);
      expect(screen.getByText('testuser')).toBeInTheDocument();
    });

    it('renders the connection info', () => {
      setupMocks();
      render(<AccountInfoModal {...defaultProps()} />);
      expect(screen.getByText('1 / 2')).toBeInTheDocument();
    });

    it('renders formatted created_at timestamp', () => {
      setupMocks({ formattedTimestamp: 'Nov 14, 2023' });
      render(<AccountInfoModal {...defaultProps()} />);
      expect(formatTimestamp).toHaveBeenCalledWith('1700000000');
      expect(screen.getAllByText('Nov 14, 2023').length).toBeGreaterThan(0);
    });

    it('renders time remaining', () => {
      setupMocks({ timeRemaining: '10 days 5 hours' });
      render(<AccountInfoModal {...defaultProps()} />);
      expect(screen.getByText(/10 days 5 hours/)).toBeInTheDocument();
    });

    it('renders the refresh action icon', () => {
      setupMocks();
      render(<AccountInfoModal {...defaultProps()} />);
      expect(screen.getByTestId('action-icon')).toBeInTheDocument();
    });

    it('renders the refresh icon inside the action icon', () => {
      setupMocks();
      render(<AccountInfoModal {...defaultProps()} />);
      expect(screen.getByTestId('icon-refresh-cw')).toBeInTheDocument();
    });
  });

  // ── Store-based profile resolution ────────────────────────────────────────

  describe('store-based profile resolution', () => {
    it('uses fresh profile from store when available', () => {
      const freshProfile = makeProfile({
        custom_properties: {
          user_info: makeUserInfo({ username: 'freshuser' }),
        },
      });
      setupMocks({
        profiles: { 'account-1': [freshProfile] },
      });
      render(<AccountInfoModal {...defaultProps()} />);
      expect(screen.getByText('freshuser')).toBeInTheDocument();
    });

    it('falls back to passed profile when not found in store', () => {
      setupMocks({ profiles: { 'account-1': [] } });
      render(<AccountInfoModal {...defaultProps()} />);
      expect(screen.getByText('testuser')).toBeInTheDocument();
    });

    it('falls back to passed profile when profiles is empty', () => {
      setupMocks({ profiles: {} });
      render(<AccountInfoModal {...defaultProps()} />);
      expect(screen.getByText('testuser')).toBeInTheDocument();
    });

    it('falls back to passed profile when profile has no id', () => {
      setupMocks();
      const profileNoId = makeProfile({ id: undefined });
      render(<AccountInfoModal {...defaultProps({ profile: profileNoId })} />);
      // Should not throw and should render without crash
      expect(screen.getByTestId('modal')).toBeInTheDocument();
    });

    it('falls back to passed profile when profile has no account id', () => {
      setupMocks();
      const profileNoAccountId = makeProfile({ account: {} });
      render(
        <AccountInfoModal {...defaultProps({ profile: profileNoAccountId })} />
      );
      expect(screen.getByTestId('modal')).toBeInTheDocument();
    });
  });

  // ── Status badge ───────────────────────────────────────────────────────────

  describe('status badge', () => {
    it('renders a badge for Active status', () => {
      setupMocks();
      render(<AccountInfoModal {...defaultProps()} />);
      const badges = screen.getAllByTestId('badge');
      const activeOrStatusBadge = badges.find((b) =>
        b.textContent.toLowerCase().includes('active')
      );
      expect(activeOrStatusBadge).toBeInTheDocument();
    });

    it('renders a badge for Banned status', () => {
      setupMocks();
      const profile = makeProfile({
        custom_properties: {
          user_info: makeUserInfo({ status: 'Banned' }),
        },
      });
      render(<AccountInfoModal {...defaultProps({ profile })} />);
      const badges = screen.getAllByTestId('badge');
      const bannedBadge = badges.find((b) =>
        b.textContent.toLowerCase().includes('banned')
      );
      expect(bannedBadge).toBeInTheDocument();
    });

    it('renders a badge for Disabled status', () => {
      setupMocks();
      const profile = makeProfile({
        custom_properties: {
          user_info: makeUserInfo({ status: 'Disabled' }),
        },
      });
      render(<AccountInfoModal {...defaultProps({ profile })} />);
      const badges = screen.getAllByTestId('badge');
      const disabledBadge = badges.find((b) =>
        b.textContent.toLowerCase().includes('disabled')
      );
      expect(disabledBadge).toBeInTheDocument();
    });
  });

  // ── Expiry / time remaining ────────────────────────────────────────────────

  describe('expiry display', () => {
    it('renders "Expired" when getTimeRemaining returns "Expired"', () => {
      setupMocks({ timeRemaining: 'Expired' });
      render(<AccountInfoModal {...defaultProps()} />);
      expect(screen.getByText('Expired')).toBeInTheDocument();
    });

    it('shows an alert when account is expired', () => {
      setupMocks({ timeRemaining: 'Expired' });
      render(<AccountInfoModal {...defaultProps()} />);
      expect(screen.getByTestId('alert')).toBeInTheDocument();
    });

    it('does not show an expiry alert when account is not expired', () => {
      setupMocks({ timeRemaining: '5 days 2 hours' });
      render(<AccountInfoModal {...defaultProps()} />);
      expect(screen.queryByTestId('alert')).not.toBeInTheDocument();
    });

    it('calls getTimeRemaining with exp_date', () => {
      setupMocks();
      render(<AccountInfoModal {...defaultProps()} />);
      expect(getTimeRemaining).toHaveBeenCalledWith('9999999999');
    });

    it('handles null exp_date gracefully', () => {
      setupMocks({ timeRemaining: null });
      const profile = makeProfile({
        custom_properties: {
          user_info: makeUserInfo({ exp_date: null }),
        },
      });
      render(<AccountInfoModal {...defaultProps({ profile })} />);
      expect(screen.getByTestId('modal')).toBeInTheDocument();
    });
  });

  // ── Refresh button ─────────────────────────────────────────────────────────

  describe('refresh button', () => {
    it('calls refreshAccountInfo when refresh button is clicked', async () => {
      setupMocks();
      render(<AccountInfoModal {...defaultProps()} />);
      fireEvent.click(screen.getByTestId('action-icon'));
      await waitFor(() => {
        expect(refreshAccountInfo).toHaveBeenCalled();
      });
    });

    it('shows success notification when refresh succeeds', async () => {
      setupMocks();
      vi.mocked(refreshAccountInfo).mockResolvedValue({ success: true });
      render(<AccountInfoModal {...defaultProps()} />);
      fireEvent.click(screen.getByTestId('action-icon'));
      await waitFor(() => {
        expect(showNotification).toHaveBeenCalledWith(
          expect.objectContaining({ color: 'green' })
        );
      });
    });

    it('shows error notification when refresh returns success: false', async () => {
      setupMocks();
      vi.mocked(refreshAccountInfo).mockResolvedValue({ success: false });
      render(<AccountInfoModal {...defaultProps()} />);
      fireEvent.click(screen.getByTestId('action-icon'));
      await waitFor(() => {
        expect(showNotification).toHaveBeenCalledWith(
          expect.objectContaining({ color: 'red' })
        );
      });
    });

    it('calls onRefresh after successful refresh', async () => {
      vi.useFakeTimers();
      setupMocks();
      const onRefresh = vi.fn();
      render(<AccountInfoModal {...defaultProps({ onRefresh })} />);
      fireEvent.click(screen.getByTestId('action-icon'));

      // Wait for the async handleRefresh to complete
      await vi.runAllTimersAsync();

      expect(onRefresh).toHaveBeenCalled();
      vi.useRealTimers();
    });

    it('shows error notification when profile id is missing', async () => {
      setupMocks();
      const profileNoId = makeProfile({ id: undefined });
      render(<AccountInfoModal {...defaultProps({ profile: profileNoId })} />);
      fireEvent.click(screen.getByTestId('action-icon'));
      await waitFor(() => {
        expect(showNotification).toHaveBeenCalledWith(
          expect.objectContaining({ color: 'red' })
        );
      });
      expect(refreshAccountInfo).not.toHaveBeenCalled();
    });

    it('disables the refresh button while refreshing', async () => {
      setupMocks();
      vi.mocked(refreshAccountInfo).mockImplementation(
        () =>
          new Promise((resolve) =>
            setTimeout(() => resolve({ success: true }), 200)
          )
      );
      render(<AccountInfoModal {...defaultProps()} />);
      fireEvent.click(screen.getByTestId('action-icon'));
      expect(screen.getByTestId('action-icon')).toBeDisabled();
      await waitFor(() => {
        expect(screen.getByTestId('action-icon')).not.toBeDisabled();
      });
    });

    it('re-enables the refresh button after refresh fails', async () => {
      setupMocks();
      const consoleSpy = vi
        .spyOn(console, 'error')
        .mockImplementation(() => {});
      vi.mocked(refreshAccountInfo).mockRejectedValue(new Error('fail'));
      render(<AccountInfoModal {...defaultProps()} />);
      fireEvent.click(screen.getByTestId('action-icon'));
      await waitFor(() => {
        expect(screen.getByTestId('action-icon')).not.toBeDisabled();
      });
      consoleSpy.mockRestore();
    });
  });

  // ── Null / missing profile ─────────────────────────────────────────────────

  describe('null or missing profile', () => {
    it('renders without crashing when profile is null', () => {
      setupMocks();
      render(<AccountInfoModal {...defaultProps({ profile: null })} />);
      expect(screen.getByTestId('modal')).toBeInTheDocument();
    });

    it('renders without crashing when user_info is missing', () => {
      setupMocks();
      const profile = makeProfile({ custom_properties: {} });
      render(<AccountInfoModal {...defaultProps({ profile })} />);
      expect(screen.getByTestId('modal')).toBeInTheDocument();
    });

    it('renders without crashing when custom_properties is missing', () => {
      setupMocks();
      const profile = makeProfile({ custom_properties: undefined });
      render(<AccountInfoModal {...defaultProps({ profile })} />);
      expect(screen.getByTestId('modal')).toBeInTheDocument();
    });
  });
});
