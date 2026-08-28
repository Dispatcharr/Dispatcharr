import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

// ── Utils mock ─────────────────────────────────────────────────────────────────
vi.mock('../../../utils/tables/ChannelsTableUtils.js', () => ({
  updateProfileChannels: vi.fn(),
}));

// ── Notification mock ──────────────────────────────────────────────────────────
vi.mock('../../../utils/notificationUtils', () => ({
  showNotification: vi.fn(),
}));

// ── @mantine/core ──────────────────────────────────────────────────────────────
vi.mock('@mantine/core', () => ({
  Button: ({ children, onClick, disabled, loading }) => (
    <button onClick={onClick} disabled={disabled || loading}>
      {children}
    </button>
  ),
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
  Select: ({ value, onChange, data, placeholder }) => (
    <select
      data-testid="target-profile-select"
      value={value ?? ''}
      onChange={(e) => onChange(e.target.value || null)}
    >
      <option value="">{placeholder}</option>
      {(data || []).map((opt) => (
        <option key={opt.value} value={opt.value}>
          {opt.label}
        </option>
      ))}
    </select>
  ),
  Stack: ({ children }) => <div>{children}</div>,
  Text: ({ children }) => <span>{children}</span>,
}));

// ── Imports after mocks ────────────────────────────────────────────────────────
import AddToProfileModal from '../AddToProfileModal';
import { updateProfileChannels } from '../../../utils/tables/ChannelsTableUtils.js';
import { showNotification } from '../../../utils/notificationUtils';

// ── Shared helpers ─────────────────────────────────────────────────────────────
const makeProfiles = () => ({
  0: { id: '0', name: 'All', channels: new Set() },
  1: { id: 1, name: 'All Channels', channels: new Set([1, 2, 3]) },
  2: { id: 2, name: 'Bo', channels: new Set() },
});

const defaultProps = (overrides = {}) => ({
  opened: true,
  onClose: vi.fn(),
  channelIds: [10, 20],
  profiles: makeProfiles(),
  excludeProfileId: '1',
  ...overrides,
});

// ──────────────────────────────────────────────────────────────────────────────

describe('AddToProfileModal', () => {
  beforeEach(() => {
    vi.resetAllMocks();
    vi.mocked(updateProfileChannels).mockResolvedValue(undefined);
  });

  // ── Visibility ─────────────────────────────────────────────────────────────

  describe('visibility', () => {
    it('renders the modal when opened is true', () => {
      render(<AddToProfileModal {...defaultProps()} />);
      expect(screen.getByTestId('modal')).toBeInTheDocument();
    });

    it('does not render the modal when opened is false', () => {
      render(<AddToProfileModal {...defaultProps({ opened: false })} />);
      expect(screen.queryByTestId('modal')).not.toBeInTheDocument();
    });
  });

  // ── Target profile options ────────────────────────────────────────────────

  describe('target profile options', () => {
    it('excludes the "0" pseudo "All Channels" profile from the options', () => {
      render(<AddToProfileModal {...defaultProps()} />);
      expect(screen.queryByText('All')).not.toBeInTheDocument();
    });

    it('excludes the currently active profile from the options', () => {
      render(
        <AddToProfileModal {...defaultProps({ excludeProfileId: '1' })} />
      );
      expect(screen.queryByText('All Channels')).not.toBeInTheDocument();
      expect(screen.getByText('Bo')).toBeInTheDocument();
    });

    it('includes other real profiles as options', () => {
      render(
        <AddToProfileModal {...defaultProps({ excludeProfileId: '2' })} />
      );
      expect(screen.getByText('All Channels')).toBeInTheDocument();
      expect(screen.queryByText('Bo')).not.toBeInTheDocument();
    });
  });

  // ── Submit button state ───────────────────────────────────────────────────

  describe('submit button state', () => {
    it('disables the Add button until a target profile is selected', () => {
      render(<AddToProfileModal {...defaultProps()} />);
      expect(screen.getByText('Add')).toBeDisabled();
    });

    it('enables the Add button once a target profile is selected', () => {
      render(<AddToProfileModal {...defaultProps()} />);
      fireEvent.change(screen.getByTestId('target-profile-select'), {
        target: { value: '2' },
      });
      expect(screen.getByText('Add')).not.toBeDisabled();
    });
  });

  // ── Submission ─────────────────────────────────────────────────────────────

  describe('submission', () => {
    it('calls updateProfileChannels with the selected channel ids, target profile, and enabled=true', async () => {
      render(
        <AddToProfileModal
          {...defaultProps({ channelIds: [10, 20], excludeProfileId: '1' })}
        />
      );
      fireEvent.change(screen.getByTestId('target-profile-select'), {
        target: { value: '2' },
      });
      fireEvent.click(screen.getByText('Add'));

      await waitFor(() => {
        expect(updateProfileChannels).toHaveBeenCalledWith([10, 20], '2', true);
      });
    });

    it('does not call updateProfileChannels when no target profile is selected', () => {
      render(<AddToProfileModal {...defaultProps()} />);
      fireEvent.click(screen.getByText('Add'));
      expect(updateProfileChannels).not.toHaveBeenCalled();
    });

    it('shows a success notification naming the target profile and channel count', async () => {
      render(
        <AddToProfileModal
          {...defaultProps({ channelIds: [10, 20], excludeProfileId: '1' })}
        />
      );
      fireEvent.change(screen.getByTestId('target-profile-select'), {
        target: { value: '2' },
      });
      fireEvent.click(screen.getByText('Add'));

      await waitFor(() => {
        expect(showNotification).toHaveBeenCalledWith(
          expect.objectContaining({
            title: 'Channels added',
            message: '2 channels added to Bo',
            color: 'green.5',
          })
        );
      });
    });

    it('closes the modal after a successful add', async () => {
      const onClose = vi.fn();
      render(
        <AddToProfileModal
          {...defaultProps({ onClose, excludeProfileId: '1' })}
        />
      );
      fireEvent.change(screen.getByTestId('target-profile-select'), {
        target: { value: '2' },
      });
      fireEvent.click(screen.getByText('Add'));

      await waitFor(() => {
        expect(onClose).toHaveBeenCalled();
      });
    });
  });

  // ── Cancel / close ─────────────────────────────────────────────────────────

  describe('cancel / close', () => {
    it('calls onClose when Cancel is clicked', () => {
      const onClose = vi.fn();
      render(<AddToProfileModal {...defaultProps({ onClose })} />);
      fireEvent.click(screen.getByText('Cancel'));
      expect(onClose).toHaveBeenCalled();
    });

    it('calls onClose when the modal close button is clicked', () => {
      const onClose = vi.fn();
      render(<AddToProfileModal {...defaultProps({ onClose })} />);
      fireEvent.click(screen.getByTestId('modal-close'));
      expect(onClose).toHaveBeenCalled();
    });
  });
});
