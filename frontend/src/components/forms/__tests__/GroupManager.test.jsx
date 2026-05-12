import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import GroupManager from '../GroupManager';

// ── Store mocks ────────────────────────────────────────────────────────────────
vi.mock('../../../store/channels', () => ({ default: vi.fn() }));
vi.mock('../../../store/warnings', () => ({ default: vi.fn() }));

// ── Utility mocks ──────────────────────────────────────────────────────────────
vi.mock('../../../utils/notificationUtils.js', () => ({
  showNotification: vi.fn(),
}));

vi.mock('../../../utils/forms/ChannelGroupUtils.js', () => ({
  addChannelGroup: vi.fn(),
  cleanupUnusedChannelGroups: vi.fn(),
  deleteChannelGroup: vi.fn(),
  updateChannelGroup: vi.fn(),
}));

// ── ConfirmationDialog mock ────────────────────────────────────────────────────
vi.mock('../../ConfirmationDialog', () => ({
  default: ({
    opened,
    onClose,
    onConfirm,
    title,
    confirmLabel,
    cancelLabel,
    loading,
  }) =>
    opened ? (
      <div data-testid="confirmation-dialog">
        <div data-testid="confirm-title">{title}</div>
        <button
          data-testid="confirm-btn"
          onClick={onConfirm}
          disabled={loading}
        >
          {confirmLabel}
        </button>
        <button data-testid="cancel-btn" onClick={onClose}>
          {cancelLabel}
        </button>
      </div>
    ) : null,
}));

// ── lucide-react ───────────────────────────────────────────────────────────────
vi.mock('lucide-react', () => ({
  AlertCircle: () => <svg data-testid="icon-alert-circle" />,
  Check: () => <svg data-testid="icon-check" />,
  Database: () => <svg data-testid="icon-database" />,
  Filter: () => <svg data-testid="icon-filter" />,
  SquareMinus: () => <svg data-testid="icon-square-minus" />,
  SquarePen: () => <svg data-testid="icon-square-pen" />,
  SquarePlus: () => <svg data-testid="icon-square-plus" />,
  Trash: () => <svg data-testid="icon-trash" />,
  Tv: () => <svg data-testid="icon-tv" />,
  X: () => <svg data-testid="icon-x" />,
}));

// ── Mantine core ───────────────────────────────────────────────────────────────
vi.mock('@mantine/core', async () => ({
  ActionIcon: ({ children, onClick, disabled }) => (
    <button data-testid="action-icon" onClick={onClick} disabled={disabled}>
      {children}
    </button>
  ),
  Alert: ({ children, title }) => (
    <div data-testid="alert">
      {title && <div>{title}</div>}
      {children}
    </div>
  ),
  Badge: ({ children, color }) => (
    <span data-testid="badge" data-color={color}>
      {children}
    </span>
  ),
  Box: ({ children, style }) => <div style={style}>{children}</div>,
  Button: ({ children, onClick, disabled, loading, leftSection }) => (
    <button
      onClick={onClick}
      disabled={disabled || loading}
      data-loading={loading}
    >
      {leftSection && (
        <span data-testid="button-left-section">{leftSection}</span>
      )}
      {children}
    </button>
  ),
  Chip: ({ children, checked, onChange }) => (
    <label>
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
      />
      {children}
    </label>
  ),
  Divider: () => <hr />,
  Flex: ({ children }) => <div>{children}</div>,
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
  ScrollArea: ({ children }) => <div data-testid="scroll-area">{children}</div>,
  Stack: ({ children }) => <div>{children}</div>,
  Text: ({ children }) => <span>{children}</span>,
  TextInput: ({ value, onChange, placeholder, label, onKeyDown }) => (
    <input
      data-testid={`text-input-${label ?? placeholder ?? 'field'}`}
      value={value}
      onChange={onChange}
      placeholder={placeholder}
      onKeyDown={onKeyDown}
    />
  ),
  useMantineTheme: () => ({
    tailwind: { yellow: ['#fefcbf'], red: ['#f56565'] },
  }),
}));

// ── Imports after mocks ────────────────────────────────────────────────────────
import useChannelsStore from '../../../store/channels';
import useWarningsStore from '../../../store/warnings';
import { showNotification } from '../../../utils/notificationUtils.js';
import * as ChannelGroupUtils from '../../../utils/forms/ChannelGroupUtils.js';

// ── Helpers ────────────────────────────────────────────────────────────────────
const makeGroup = (overrides = {}) => ({
  id: 1,
  name: 'Group A',
  hasChannels: true,
  hasM3UAccounts: false,
  canEdit: true,
  canDelete: true,
  ...overrides,
});

const setupMocks = ({ groups = {}, isWarningSuppressed = false } = {}) => {
  vi.mocked(useChannelsStore).mockImplementation((sel) =>
    sel({
      channelGroups: groups,
      canEditChannelGroup: vi.fn().mockReturnValue(true),
      canDeleteChannelGroup: vi.fn().mockReturnValue(true),
    })
  );

  const mockSuppressWarning = vi.fn();
  vi.mocked(useWarningsStore).mockImplementation((sel) =>
    sel({
      isWarningSuppressed: () => isWarningSuppressed,
      suppressWarning: mockSuppressWarning,
    })
  );

  return { mockSuppressWarning };
};

const renderGroupManager = (props = {}) =>
  render(<GroupManager isOpen={true} onClose={vi.fn()} {...props} />);

// ──────────────────────────────────────────────────────────────────────────────

describe('GroupManager', () => {
  beforeEach(() => vi.clearAllMocks());

  // ── Visibility ─────────────────────────────────────────────────────────────

  describe('visibility', () => {
    it('renders nothing when isOpen is false', () => {
      setupMocks();
      render(<GroupManager isOpen={false} onClose={vi.fn()} />);
      expect(screen.queryByTestId('modal')).not.toBeInTheDocument();
    });

    it('renders the modal when isOpen is true', () => {
      setupMocks();
      renderGroupManager();
      expect(screen.getByTestId('modal')).toBeInTheDocument();
    });

    it('calls onClose when modal close button is clicked', () => {
      setupMocks();
      const onClose = vi.fn();
      renderGroupManager({ onClose });
      fireEvent.click(screen.getByTestId('modal-close'));
      expect(onClose).toHaveBeenCalled();
    });
  });

  // ── Group rendering ────────────────────────────────────────────────────────

  describe('group list rendering', () => {
    it('renders a group name', () => {
      setupMocks({ groups: { 1: makeGroup() } });
      renderGroupManager();
      expect(screen.getByText('Group A')).toBeInTheDocument();
    });

    it('renders multiple groups sorted alphabetically', () => {
      setupMocks({
        groups: {
          2: makeGroup({ id: 2, name: 'Zebra' }),
          1: makeGroup({ id: 1, name: 'Alpha' }),
        },
      });
      renderGroupManager();
      const names = screen
        .getAllByText(/Alpha|Zebra/)
        .map((el) => el.textContent);
      expect(names.indexOf('Alpha')).toBeLessThan(names.indexOf('Zebra'));
    });

    it('renders channel badge for groups with channels', () => {
      setupMocks({ groups: { 1: makeGroup({ hasChannels: true }) } });
      renderGroupManager();
      expect(screen.getByTestId('icon-tv')).toBeInTheDocument();
    });

    it('renders M3U badge for groups with M3U accounts', () => {
      setupMocks({
        groups: { 1: makeGroup({ hasChannels: false, hasM3UAccounts: true }) },
      });
      renderGroupManager();
      expect(screen.getByTestId('icon-database')).toBeInTheDocument();
    });

    it('shows empty state when no groups match filter', () => {
      setupMocks({ groups: {} });
      renderGroupManager();
      // No groups rendered in scroll area
      expect(screen.queryByText('Group A')).not.toBeInTheDocument();
    });
  });

  // ── Search filtering ───────────────────────────────────────────────────────

  describe('search filtering', () => {
    it('filters groups by search term', () => {
      setupMocks({
        groups: {
          1: makeGroup({ id: 1, name: 'Sports' }),
          2: makeGroup({ id: 2, name: 'Movies' }),
        },
      });
      renderGroupManager();

      const searchInput = screen.getByPlaceholderText(/search/i);
      fireEvent.change(searchInput, { target: { value: 'Sports' } });

      expect(screen.getByText('Sports')).toBeInTheDocument();
      expect(screen.queryByText('Movies')).not.toBeInTheDocument();
    });

    it('shows all groups when search is cleared', () => {
      setupMocks({
        groups: {
          1: makeGroup({ id: 1, name: 'Sports' }),
          2: makeGroup({ id: 2, name: 'Movies' }),
        },
      });
      renderGroupManager();

      const searchInput = screen.getByPlaceholderText(/search/i);
      fireEvent.change(searchInput, { target: { value: 'Sports' } });
      fireEvent.change(searchInput, { target: { value: '' } });

      expect(screen.getByText('Sports')).toBeInTheDocument();
      expect(screen.getByText('Movies')).toBeInTheDocument();
    });

    it('is case-insensitive', () => {
      setupMocks({ groups: { 1: makeGroup({ name: 'Sports' }) } });
      renderGroupManager();

      const searchInput = screen.getByPlaceholderText(/search/i);
      fireEvent.change(searchInput, { target: { value: 'sports' } });

      expect(screen.getByText('Sports')).toBeInTheDocument();
    });
  });

  // ── Edit group ─────────────────────────────────────────────────────────────

  describe('edit group', () => {
    it('shows edit input when edit button is clicked', () => {
      setupMocks({ groups: { 1: makeGroup() } });
      renderGroupManager();

      fireEvent.click(screen.getByTestId('icon-square-pen').closest('button'));
      expect(screen.getByDisplayValue('Group A')).toBeInTheDocument();
    });

    it('calls updateChannelGroup with trimmed name on save', async () => {
      vi.mocked(ChannelGroupUtils.updateChannelGroup).mockResolvedValue(
        undefined
      );
      setupMocks({ groups: { 1: makeGroup() } });
      renderGroupManager();

      fireEvent.click(screen.getByTestId('icon-square-pen').closest('button'));
      const input = screen.getByDisplayValue('Group A');
      fireEvent.change(input, { target: { value: '  Updated Name  ' } });
      fireEvent.click(screen.getByTestId('icon-check').closest('button'));

      await waitFor(() => {
        expect(ChannelGroupUtils.updateChannelGroup).toHaveBeenCalledWith(
          makeGroup(),
          { name: 'Updated Name' }
        );
      });
    });

    it('shows success notification after save', async () => {
      vi.mocked(ChannelGroupUtils.updateChannelGroup).mockResolvedValue(
        undefined
      );
      setupMocks({ groups: { 1: makeGroup() } });
      renderGroupManager();

      fireEvent.click(screen.getByTestId('icon-square-pen').closest('button'));
      fireEvent.click(screen.getByTestId('icon-check').closest('button'));

      await waitFor(() => {
        expect(showNotification).toHaveBeenCalledWith(
          expect.objectContaining({ color: 'green', title: 'Success' })
        );
      });
    });

    it('shows error notification when name is empty on save', async () => {
      setupMocks({ groups: { 1: makeGroup() } });
      renderGroupManager();

      fireEvent.click(screen.getByTestId('icon-square-pen').closest('button'));
      const input = screen.getByDisplayValue('Group A');
      fireEvent.change(input, { target: { value: '' } });
      fireEvent.click(screen.getByTestId('icon-check').closest('button'));

      await waitFor(() => {
        expect(showNotification).toHaveBeenCalledWith(
          expect.objectContaining({ color: 'red' })
        );
      });
      expect(ChannelGroupUtils.updateChannelGroup).not.toHaveBeenCalled();
    });

    it('shows error notification when updateChannelGroup throws', async () => {
      vi.mocked(ChannelGroupUtils.updateChannelGroup).mockRejectedValue(
        new Error('fail')
      );
      setupMocks({ groups: { 1: makeGroup() } });
      renderGroupManager();

      fireEvent.click(screen.getByTestId('icon-square-pen').closest('button'));
      fireEvent.click(screen.getByTestId('icon-check').closest('button'));

      await waitFor(() => {
        expect(showNotification).toHaveBeenCalledWith(
          expect.objectContaining({ color: 'red', title: 'Error' })
        );
      });
    });

    it('cancels edit and restores group name', () => {
      setupMocks({ groups: { 1: makeGroup() } });
      renderGroupManager();

      fireEvent.click(screen.getByTestId('icon-square-pen').closest('button'));
      const input = screen.getByDisplayValue('Group A');
      fireEvent.change(input, { target: { value: 'Changed' } });

      fireEvent.click(screen.getByTestId('icon-x').closest('button'));

      expect(screen.queryByDisplayValue('Changed')).not.toBeInTheDocument();
      expect(screen.getByText('Group A')).toBeInTheDocument();
    });
  });

  // ── Create group ───────────────────────────────────────────────────────────

  describe('create group', () => {
    it('calls addChannelGroup with trimmed name', async () => {
      vi.mocked(ChannelGroupUtils.addChannelGroup).mockResolvedValue(undefined);
      setupMocks();
      renderGroupManager();

      fireEvent.click(screen.getByTestId('icon-square-plus').closest('button'));
      const input = screen.getByPlaceholderText(/Enter group name/i);
      fireEvent.change(input, { target: { value: '  New Group  ' } });
      fireEvent.click(screen.getByTestId('icon-check').closest('button'));

      await waitFor(() => {
        expect(ChannelGroupUtils.addChannelGroup).toHaveBeenCalledWith({
          name: 'New Group',
        });
      });
    });

    it('shows success notification after create', async () => {
      vi.mocked(ChannelGroupUtils.addChannelGroup).mockResolvedValue(undefined);
      setupMocks();
      renderGroupManager();

      fireEvent.click(screen.getByTestId('icon-square-plus').closest('button'));
      const input = screen.getByPlaceholderText(/Enter group name/i);
      fireEvent.change(input, { target: { value: 'New Group' } });
      fireEvent.click(screen.getByTestId('icon-check').closest('button'));

      await waitFor(() => {
        expect(showNotification).toHaveBeenCalledWith(
          expect.objectContaining({ color: 'green', title: 'Success' })
        );
      });
    });

    it('shows error notification when name is empty', async () => {
      setupMocks();
      renderGroupManager();

      fireEvent.click(screen.getByTestId('icon-square-plus').closest('button'));
      fireEvent.click(screen.getByTestId('icon-check').closest('button'));

      await waitFor(() => {
        expect(showNotification).toHaveBeenCalledWith(
          expect.objectContaining({ color: 'red' })
        );
      });
      expect(ChannelGroupUtils.addChannelGroup).not.toHaveBeenCalled();
    });

    it('shows error notification when addChannelGroup throws', async () => {
      vi.mocked(ChannelGroupUtils.addChannelGroup).mockRejectedValue(
        new Error('fail')
      );
      setupMocks();
      renderGroupManager();

      fireEvent.click(screen.getByTestId('icon-square-plus').closest('button'));
      const input = screen.getByPlaceholderText(/Enter group name/i);
      fireEvent.change(input, { target: { value: 'New Group' } });
      fireEvent.click(screen.getByTestId('icon-check').closest('button'));

      await waitFor(() => {
        expect(showNotification).toHaveBeenCalledWith(
          expect.objectContaining({ color: 'red', title: 'Error' })
        );
      });
    });

    it('clears new group name and hides form after successful create', async () => {
      vi.mocked(ChannelGroupUtils.addChannelGroup).mockResolvedValue(undefined);
      setupMocks();
      renderGroupManager();

      fireEvent.click(screen.getByTestId('icon-square-plus').closest('button'));
      const input = screen.getByPlaceholderText(/Enter group name/i);
      fireEvent.change(input, { target: { value: 'New Group' } });
      fireEvent.click(screen.getByTestId('icon-check').closest('button'));

      await waitFor(() => {
        expect(
          screen.queryByPlaceholderText(/Enter group name/i)
        ).not.toBeInTheDocument();
      });
    });

    it('cancels creation form with X button', () => {
      setupMocks();
      renderGroupManager();

      fireEvent.click(screen.getByTestId('icon-square-plus').closest('button'));
      expect(
        screen.getByPlaceholderText(/Enter group name/i)
      ).toBeInTheDocument();

      fireEvent.click(screen.getByTestId('icon-x').closest('button'));
      expect(
        screen.queryByPlaceholderText(/Enter group name/i)
      ).not.toBeInTheDocument();
    });
  });

  // ── Delete group ───────────────────────────────────────────────────────────

  describe('delete group', () => {
    it('opens confirmation dialog when delete is clicked', async () => {
      setupMocks({
        groups: {
          1: { ...makeGroup(), hasChannels: false, hasM3UAccounts: false },
        },
      });
      renderGroupManager();

      fireEvent.click(
        screen.getByTestId('icon-square-minus').closest('button')
      );
      await waitFor(() => {
        expect(screen.getByTestId('confirmation-dialog')).toBeInTheDocument();
        expect(screen.getByTestId('confirm-title')).toHaveTextContent(
          'Confirm Group Deletion'
        );
      });
    });

    it('calls deleteChannelGroup when confirmed', async () => {
      vi.mocked(ChannelGroupUtils.deleteChannelGroup).mockResolvedValue(
        undefined
      );
      const groupToDelete = {
        ...makeGroup(),
        hasChannels: false,
        hasM3UAccounts: false,
      };
      setupMocks({ groups: { 1: groupToDelete } });
      renderGroupManager();

      fireEvent.click(
        screen.getByTestId('icon-square-minus').closest('button')
      );
      fireEvent.click(screen.getByTestId('confirm-btn'));

      await waitFor(() => {
        expect(ChannelGroupUtils.deleteChannelGroup).toHaveBeenCalledWith(
          groupToDelete
        );
      });
    });

    it('shows success notification after delete', async () => {
      vi.mocked(ChannelGroupUtils.deleteChannelGroup).mockResolvedValue(
        undefined
      );
      setupMocks({
        groups: {
          1: { ...makeGroup(), hasChannels: false, hasM3UAccounts: false },
        },
      });
      renderGroupManager();

      fireEvent.click(
        screen.getByTestId('icon-square-minus').closest('button')
      );
      fireEvent.click(screen.getByTestId('confirm-btn'));

      await waitFor(() => {
        expect(showNotification).toHaveBeenCalledWith(
          expect.objectContaining({ color: 'green', title: 'Success' })
        );
      });
    });

    it('shows error notification when deleteChannelGroup throws', async () => {
      vi.mocked(ChannelGroupUtils.deleteChannelGroup).mockRejectedValue(
        new Error('fail')
      );
      setupMocks({
        groups: {
          1: { ...makeGroup(), hasChannels: false, hasM3UAccounts: false },
        },
      });
      renderGroupManager();

      fireEvent.click(
        screen.getByTestId('icon-square-minus').closest('button')
      );
      fireEvent.click(screen.getByTestId('confirm-btn'));

      await waitFor(() => {
        expect(showNotification).toHaveBeenCalledWith(
          expect.objectContaining({ color: 'red', title: 'Error' })
        );
      });
    });

    it('closes confirmation dialog on cancel', () => {
      setupMocks({
        groups: {
          1: { ...makeGroup(), hasChannels: false, hasM3UAccounts: false },
        },
      });
      renderGroupManager();

      fireEvent.click(
        screen.getByTestId('icon-square-minus').closest('button')
      );
      fireEvent.click(screen.getByTestId('cancel-btn'));

      expect(
        screen.queryByTestId('confirmation-dialog')
      ).not.toBeInTheDocument();
    });

    it('closes confirmation dialog after successful delete', async () => {
      vi.mocked(ChannelGroupUtils.deleteChannelGroup).mockResolvedValue(
        undefined
      );
      setupMocks({
        groups: {
          1: { ...makeGroup(), hasChannels: false, hasM3UAccounts: false },
        },
      });
      renderGroupManager();

      fireEvent.click(
        screen.getByTestId('icon-square-minus').closest('button')
      );
      fireEvent.click(screen.getByTestId('confirm-btn'));

      await waitFor(() => {
        expect(
          screen.queryByTestId('confirmation-dialog')
        ).not.toBeInTheDocument();
      });
    });
  });

  // ── Cleanup ────────────────────────────────────────────────────────────────

  describe('cleanup unused groups', () => {
    const successResponse = { deleted_count: 1 };

    it('opens cleanup confirmation dialog when warning not suppressed', () => {
      setupMocks({ isWarningSuppressed: false });
      renderGroupManager();

      fireEvent.click(screen.getByText(/cleanup/i));
      expect(screen.getByTestId('confirmation-dialog')).toBeInTheDocument();
      expect(screen.getByTestId('confirm-title')).toHaveTextContent('Cleanup');
    });

    it('calls cleanupUnusedChannelGroups directly when warning is suppressed', async () => {
      vi.mocked(ChannelGroupUtils.cleanupUnusedChannelGroups).mockResolvedValue(
        successResponse
      );
      setupMocks({ isWarningSuppressed: true });
      renderGroupManager();

      fireEvent.click(screen.getByText(/cleanup/i));

      await waitFor(() => {
        expect(ChannelGroupUtils.cleanupUnusedChannelGroups).toHaveBeenCalled();
      });
      expect(
        screen.queryByTestId('confirmation-dialog')
      ).not.toBeInTheDocument();
    });

    it('calls cleanupUnusedChannelGroups when cleanup confirmed', async () => {
      vi.mocked(ChannelGroupUtils.cleanupUnusedChannelGroups).mockResolvedValue(
        successResponse
      );
      setupMocks({ isWarningSuppressed: false });
      renderGroupManager();

      fireEvent.click(screen.getByText(/cleanup/i));
      fireEvent.click(screen.getByTestId('confirm-btn'));

      await waitFor(() => {
        expect(ChannelGroupUtils.cleanupUnusedChannelGroups).toHaveBeenCalled();
      });
    });

    it('shows success notification after cleanup', async () => {
      vi.mocked(ChannelGroupUtils.cleanupUnusedChannelGroups).mockResolvedValue(
        successResponse
      );
      setupMocks({ isWarningSuppressed: true });
      renderGroupManager();

      fireEvent.click(screen.getByText(/cleanup/i));

      await waitFor(() => {
        expect(showNotification).toHaveBeenCalledWith(
          expect.objectContaining({ color: 'green' })
        );
      });
    });

    it('shows error notification when cleanup throws', async () => {
      vi.mocked(ChannelGroupUtils.cleanupUnusedChannelGroups).mockRejectedValue(
        new Error('fail')
      );
      setupMocks({ isWarningSuppressed: true });
      renderGroupManager();

      fireEvent.click(screen.getByText(/cleanup/i));

      await waitFor(() => {
        expect(showNotification).toHaveBeenCalledWith(
          expect.objectContaining({ color: 'red' })
        );
      });
    });

    it('closes cleanup dialog on cancel', () => {
      setupMocks({ isWarningSuppressed: false });
      renderGroupManager();

      fireEvent.click(screen.getByText(/cleanup/i));
      fireEvent.click(screen.getByTestId('cancel-btn'));

      expect(
        screen.queryByTestId('confirmation-dialog')
      ).not.toBeInTheDocument();
    });
  });

  // ── Filter chips ───────────────────────────────────────────────────────────

  describe('filter chips', () => {
    const twoGroups = {
      1: makeGroup({
        id: 1,
        name: 'Channel Group',
        hasChannels: true,
        hasM3UAccounts: false,
      }),
      2: makeGroup({
        id: 2,
        name: 'M3U Group',
        hasChannels: false,
        hasM3UAccounts: true,
      }),
    };

    it('hides channel groups when Channels chip is unchecked', () => {
      setupMocks({ groups: twoGroups });
      renderGroupManager();

      const channelChip = screen.getByLabelText(/channel groups/i);
      fireEvent.click(channelChip);

      expect(screen.queryByText('Channel Group')).not.toBeInTheDocument();
      expect(screen.getByText('M3U Group')).toBeInTheDocument();
    });

    it('hides M3U groups when M3U chip is unchecked', () => {
      setupMocks({ groups: twoGroups });
      renderGroupManager();

      const m3uChip = screen.getByLabelText(/m3u groups/i);
      fireEvent.click(m3uChip);

      expect(screen.getByText('Channel Group')).toBeInTheDocument();
      expect(screen.queryByText('M3U Group')).not.toBeInTheDocument();
    });

    it('hides unused groups when Unused chip is unchecked', () => {
      setupMocks({
        groups: {
          1: makeGroup({
            id: 1,
            name: 'Unused Group',
            hasChannels: false,
            hasM3UAccounts: false,
          }),
          2: makeGroup({
            id: 2,
            name: 'Used Group',
            hasChannels: true,
            hasM3UAccounts: false,
          }),
        },
      });
      renderGroupManager();

      const unusedChip = screen.getByLabelText(/unused/i);
      fireEvent.click(unusedChip);

      expect(screen.queryByText('Unused Group')).not.toBeInTheDocument();
      expect(screen.getByText('Used Group')).toBeInTheDocument();
    });
  });

  // ── fetchGroupUsage ────────────────────────────────────────────────────────

  describe('fetchGroupUsage on open', () => {
    it('populates group usage from channelGroups flags when modal opens', () => {
      setupMocks({
        groups: {
          1: makeGroup({ hasChannels: true, hasM3UAccounts: false }),
        },
      });
      renderGroupManager();
      // Group is visible (usage was populated), badge is shown
      expect(screen.getByTestId('icon-tv')).toBeInTheDocument();
    });

    it('does not fetch when isOpen is false', () => {
      setupMocks({
        groups: { 1: makeGroup() },
      });
      render(<GroupManager isOpen={false} onClose={vi.fn()} />);
      // Nothing should render
      expect(screen.queryByTestId('modal')).not.toBeInTheDocument();
    });
  });
});
