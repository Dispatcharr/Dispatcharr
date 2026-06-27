import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

// ── API mock ───────────────────────────────────────────────────────────────────
vi.mock('../../../api', () => ({
  default: {
    deleteUser: vi.fn().mockResolvedValue(undefined),
  },
}));

// ── Store mocks ────────────────────────────────────────────────────────────────
vi.mock('../../../store/users', () => ({ default: vi.fn() }));
vi.mock('../../../store/channels', () => ({ default: vi.fn() }));
vi.mock('../../../store/auth', () => ({ default: vi.fn() }));
vi.mock('../../../store/warnings', () => ({ default: vi.fn() }));

// ── Hook mocks ─────────────────────────────────────────────────────────────────
vi.mock('../../../hooks/useLocalStorage', () => ({
  default: vi.fn(() => ['default', vi.fn()]),
}));

// ── Utility mocks ──────────────────────────────────────────────────────────────
vi.mock('../../../utils/dateTimeUtils.js', () => ({
  useDateTimeFormat: vi.fn(),
  format: vi.fn((val) => `formatted:${val}`),
}));

// ── Child component mocks ──────────────────────────────────────────────────────
vi.mock('../../forms/User', () => ({
  default: ({ isOpen, onClose, user }) =>
    isOpen ? (
      <div data-testid="user-form">
        <span data-testid="form-user-name">{user?.username ?? 'new'}</span>
        <button data-testid="form-close" onClick={onClose}>
          Close
        </button>
      </div>
    ) : null,
}));

vi.mock('../../ConfirmationDialog', () => ({
  default: ({ opened, onClose, onConfirm, title, loading, confirmLabel, cancelLabel }) =>
    opened ? (
      <div data-testid="confirm-dialog">
        <span data-testid="confirm-title">{title}</span>
        <button data-testid="confirm-ok" onClick={onConfirm} disabled={loading}>
          {confirmLabel}
        </button>
        <button data-testid="confirm-cancel" onClick={onClose}>
          {cancelLabel}
        </button>
      </div>
    ) : null,
}));

vi.mock('../CustomTable', () => ({
  CustomTable: () => <div data-testid="custom-table" />,
  useTable: vi.fn(),
}));

// ── Mantine core ───────────────────────────────────────────────────────────────
vi.mock('@mantine/core', () => ({
  ActionIcon: ({ children, onClick, disabled, color }) => (
    <button
      data-testid="action-icon"
      data-color={color}
      onClick={onClick}
      disabled={disabled}
    >
      {children}
    </button>
  ),
  Badge: ({ children, color }) => (
    <span data-testid="badge" data-color={color}>
      {children}
    </span>
  ),
  Box: ({ children, style }) => <div style={style}>{children}</div>,
  Button: ({ children, onClick, leftSection, disabled, loading }) => (
    <button data-testid="button" onClick={onClick} disabled={disabled || loading}>
      {leftSection}
      {children}
    </button>
  ),
  Flex: ({ children, style }) => <div style={style}>{children}</div>,
  Group: ({ children, style }) => (
    <div style={style}>{children}</div>
  ),
  LoadingOverlay: ({ visible }) => visible ? <div data-testid="loading-overlay" /> : null,
  Paper: ({ children, style }) => <div style={style}>{children}</div>,
  Stack: ({ children, style }) => <div style={style}>{children}</div>,
  Text: ({ children, style, name }) => (
    <span data-testid="text" data-name={name} style={style}>
      {children}
    </span>
  ),
  Tooltip: ({ children, label }) => (
    <div data-tooltip={label}>{children}</div>
  ),
  useMantineTheme: vi.fn(() => ({
    tailwind: {
      yellow: { 3: '#fde047' },
      red: { 6: '#dc2626' },
      green: { 5: '#22c55e' },
    },
  })),
}));

// ── lucide-react ───────────────────────────────────────────────────────────────
vi.mock('lucide-react', () => ({
  Eye: () => <svg data-testid="icon-eye" />,
  EyeOff: () => <svg data-testid="icon-eye-off" />,
  SquareMinus: () => <svg data-testid="icon-square-minus" />,
  SquarePen: () => <svg data-testid="icon-square-pen" />,
  SquarePlus: () => <svg data-testid="icon-square-plus" />,
}));

// ── Imports after mocks ────────────────────────────────────────────────────────
import useUsersStore from '../../../store/users';
import useChannelsStore from '../../../store/channels';
import useAuthStore from '../../../store/auth';
import useWarningsStore from '../../../store/warnings';
import { useDateTimeFormat, format } from '../../../utils/dateTimeUtils.js';
import { useTable } from '../CustomTable';
import API from '../../../api';
import { USER_LEVELS, USER_LEVEL_LABELS } from '../../../constants';
import UsersTable from '../UsersTable';

// ── Factories ──────────────────────────────────────────────────────────────────
const makeUser = (overrides = {}) => ({
  id: 1,
  username: 'testuser',
  first_name: 'Test',
  last_name: 'User',
  email: 'test@example.com',
  user_level: USER_LEVELS.STANDARD,
  date_joined: '2024-01-15T10:00:00Z',
  last_login: '2024-06-01T12:00:00Z',
  custom_properties: { xc_password: 'secret123' },
  channel_profiles: [],
  ...overrides,
});

const makeAdminUser = (overrides = {}) =>
  makeUser({ id: 99, username: 'admin', user_level: USER_LEVELS.ADMIN, ...overrides });

let capturedTableOptions = null;

const setupMocks = ({
  users = [makeUser()],
  authUser = makeAdminUser(),
  profiles = { 10: { id: 10, name: 'HD Profile' } },
  isWarningSuppressed = vi.fn(() => false),
  suppressWarning = vi.fn(),
} = {}) => {
  vi.mocked(useUsersStore).mockImplementation((sel) =>
    sel({ users })
  );

  vi.mocked(useChannelsStore).mockImplementation((sel) =>
    sel({ profiles })
  );

  vi.mocked(useAuthStore).mockImplementation((sel) =>
    sel({ user: authUser })
  );

  vi.mocked(useWarningsStore).mockImplementation((sel) =>
    sel({ isWarningSuppressed, suppressWarning })
  );

  vi.mocked(useDateTimeFormat).mockReturnValue({
    fullDateFormat: 'MM/DD/YYYY',
    fullDateTimeFormat: 'MM/DD/YYYY HH:mm',
  });

  vi.mocked(useTable).mockImplementation((opts) => {
    capturedTableOptions = opts;
    return {
      getRowModel: () => ({ rows: [] }),
      getHeaderGroups: () => [],
    };
  });
};

const getActionsCell = () =>
  capturedTableOptions.columns.find((c) => c.id === 'actions');

const getCol = (key) =>
  capturedTableOptions.columns.find(
    (c) => c.accessorKey === key || c.id === key
  );

// ══════════════════════════════════════════════════════════════════════════════
// Tests
// ══════════════════════════════════════════════════════════════════════════════

describe('UsersTable', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    capturedTableOptions = null;
    vi.mocked(API.deleteUser).mockResolvedValue(undefined);
  });

  // ── Rendering ──────────────────────────────────────────────────────────────

  describe('rendering', () => {
    it('renders the "Users" heading', () => {
      setupMocks();
      render(<UsersTable />);
      expect(screen.getByText('Users')).toBeInTheDocument();
    });

    it('renders the "Add User" button', () => {
      setupMocks();
      render(<UsersTable />);
      expect(screen.getByText('Add User')).toBeInTheDocument();
    });

    it('renders the custom table', () => {
      setupMocks();
      render(<UsersTable />);
      expect(screen.getByTestId('custom-table')).toBeInTheDocument();
    });

    it('does not render the user form on initial load', () => {
      setupMocks();
      render(<UsersTable />);
      expect(screen.queryByTestId('user-form')).not.toBeInTheDocument();
    });

    it('does not render the confirmation dialog on initial load', () => {
      setupMocks();
      render(<UsersTable />);
      expect(screen.queryByTestId('confirm-dialog')).not.toBeInTheDocument();
    });

    it('passes users sorted by id to useTable', () => {
      const users = [
        makeUser({ id: 3, username: 'c' }),
        makeUser({ id: 1, username: 'a' }),
        makeUser({ id: 2, username: 'b' }),
      ];
      setupMocks({ users });
      render(<UsersTable />);
      expect(capturedTableOptions.data.map((u) => u.id)).toEqual([1, 2, 3]);
    });

    it('passes allRowIds derived from user ids', () => {
      const users = [makeUser({ id: 1 }), makeUser({ id: 2 })];
      setupMocks({ users });
      render(<UsersTable />);
      expect(capturedTableOptions.allRowIds).toEqual([1, 2]);
    });
  });

  // ── "Add User" button state ────────────────────────────────────────────────

  describe('"Add User" button access control', () => {
    it('is enabled for admin users', () => {
      setupMocks({ authUser: makeAdminUser() });
      render(<UsersTable />);
      expect(screen.getByText('Add User').closest('button')).not.toBeDisabled();
    });

    it('is disabled for non-admin users', () => {
      setupMocks({ authUser: makeUser({ user_level: USER_LEVELS.STANDARD }) });
      render(<UsersTable />);
      expect(screen.getByText('Add User').closest('button')).toBeDisabled();
    });
  });

  // ── Add / Edit User form ───────────────────────────────────────────────────

  describe('Add User form', () => {
    it('opens the form with no user when "Add User" is clicked', () => {
      setupMocks();
      render(<UsersTable />);
      fireEvent.click(screen.getByText('Add User'));
      expect(screen.getByTestId('user-form')).toBeInTheDocument();
      expect(screen.getByTestId('form-user-name')).toHaveTextContent('new');
    });

    it('closes the form when onClose is called', () => {
      setupMocks();
      render(<UsersTable />);
      fireEvent.click(screen.getByText('Add User'));
      fireEvent.click(screen.getByTestId('form-close'));
      expect(screen.queryByTestId('user-form')).not.toBeInTheDocument();
    });
  });

  describe('Edit user via actions column', () => {
    it('opens the form populated with the user when edit icon is clicked', () => {
      const user = makeUser({ username: 'janedoe' });
      setupMocks({ users: [user] });
      render(<UsersTable />);

      const actionsCol = getActionsCell();
      const { getByTestId } = render(
        actionsCol.cell({ row: { original: user } })
      );
      fireEvent.click(getByTestId('icon-square-pen').closest('button'));

      expect(screen.getByTestId('user-form')).toBeInTheDocument();
      expect(screen.getByTestId('form-user-name')).toHaveTextContent('janedoe');
    });

    it('closes the form after editing when onClose is called', () => {
      const user = makeUser({ username: 'janedoe' });
      setupMocks({ users: [user] });
      render(<UsersTable />);

      const actionsCol = getActionsCell();
      const { getByTestId } = render(
        actionsCol.cell({ row: { original: user } })
      );
      fireEvent.click(getByTestId('icon-square-pen').closest('button'));
      fireEvent.click(screen.getByTestId('form-close'));

      expect(screen.queryByTestId('user-form')).not.toBeInTheDocument();
    });

    it('edit button is disabled for non-admin auth user', () => {
      const user = makeUser({ id: 5 });
      setupMocks({ users: [user], authUser: makeUser({ id: 99, user_level: USER_LEVELS.STANDARD }) });
      render(<UsersTable />);

      const actionsCol = getActionsCell();
      const { getByTestId } = render(
        actionsCol.cell({ row: { original: user } })
      );
      expect(getByTestId('icon-square-pen').closest('button')).toBeDisabled();
    });

    it('edit button is enabled for admin auth user', () => {
      const user = makeUser({ id: 5 });
      setupMocks({ users: [user], authUser: makeAdminUser() });
      render(<UsersTable />);

      const actionsCol = getActionsCell();
      const { getByTestId } = render(
        actionsCol.cell({ row: { original: user } })
      );
      expect(getByTestId('icon-square-pen').closest('button')).not.toBeDisabled();
    });
  });

  // ── Delete user ────────────────────────────────────────────────────────────

  describe('Delete user via actions column', () => {
    it('opens ConfirmationDialog when delete is clicked and warning is not suppressed', () => {
      const user = makeUser({ id: 5 });
      setupMocks({ users: [user], isWarningSuppressed: vi.fn(() => false) });
      render(<UsersTable />);

      const actionsCol = getActionsCell();
      const { getByTestId } = render(
        actionsCol.cell({ row: { original: user } })
      );
      fireEvent.click(getByTestId('icon-square-minus').closest('button'));

      expect(screen.getByTestId('confirm-dialog')).toBeInTheDocument();
      expect(screen.getByTestId('confirm-title')).toHaveTextContent('Confirm User Deletion');
    });

    it('calls API.deleteUser when confirmed via dialog', async () => {
      const user = makeUser({ id: 5 });
      setupMocks({ users: [user], isWarningSuppressed: vi.fn(() => false) });
      render(<UsersTable />);

      const actionsCol = getActionsCell();
      const { getByTestId } = render(
        actionsCol.cell({ row: { original: user } })
      );
      fireEvent.click(getByTestId('icon-square-minus').closest('button'));
      fireEvent.click(screen.getByTestId('confirm-ok'));

      await waitFor(() =>
        expect(API.deleteUser).toHaveBeenCalledWith(5)
      );
    });

    it('closes the dialog after confirming delete', async () => {
      const user = makeUser({ id: 5 });
      setupMocks({ users: [user], isWarningSuppressed: vi.fn(() => false) });
      render(<UsersTable />);

      const actionsCol = getActionsCell();
      const { getByTestId } = render(
        actionsCol.cell({ row: { original: user } })
      );
      fireEvent.click(getByTestId('icon-square-minus').closest('button'));
      fireEvent.click(screen.getByTestId('confirm-ok'));

      await waitFor(() =>
        expect(screen.queryByTestId('confirm-dialog')).not.toBeInTheDocument()
      );
    });

    it('closes the dialog when Cancel is clicked', () => {
      const user = makeUser({ id: 5 });
      setupMocks({ users: [user], isWarningSuppressed: vi.fn(() => false) });
      render(<UsersTable />);

      const actionsCol = getActionsCell();
      const { getByTestId } = render(
        actionsCol.cell({ row: { original: user } })
      );
      fireEvent.click(getByTestId('icon-square-minus').closest('button'));
      fireEvent.click(screen.getByTestId('confirm-cancel'));

      expect(screen.queryByTestId('confirm-dialog')).not.toBeInTheDocument();
    });

    it('skips dialog and calls API.deleteUser directly when warning is suppressed', async () => {
      const user = makeUser({ id: 7 });
      setupMocks({ users: [user], isWarningSuppressed: vi.fn(() => true) });
      render(<UsersTable />);

      const actionsCol = getActionsCell();
      const { getByTestId } = render(
        actionsCol.cell({ row: { original: user } })
      );
      fireEvent.click(getByTestId('icon-square-minus').closest('button'));

      await waitFor(() =>
        expect(API.deleteUser).toHaveBeenCalledWith(7)
      );
      expect(screen.queryByTestId('confirm-dialog')).not.toBeInTheDocument();
    });

    it('delete button is disabled for non-admin auth user', () => {
      const user = makeUser({ id: 5 });
      setupMocks({ users: [user], authUser: makeUser({ id: 99, user_level: USER_LEVELS.STANDARD }) });
      render(<UsersTable />);

      const actionsCol = getActionsCell();
      const { getByTestId } = render(
        actionsCol.cell({ row: { original: user } })
      );
      expect(getByTestId('icon-square-minus').closest('button')).toBeDisabled();
    });

    it('delete button is disabled when admin tries to delete themselves', () => {
      const admin = makeAdminUser({ id: 99 });
      setupMocks({ users: [admin], authUser: admin });
      render(<UsersTable />);

      const actionsCol = getActionsCell();
      const { getByTestId } = render(
        actionsCol.cell({ row: { original: admin } })
      );
      expect(getByTestId('icon-square-minus').closest('button')).toBeDisabled();
    });

    it('delete button is enabled for admin deleting a different user', () => {
      const user = makeUser({ id: 5 });
      setupMocks({ users: [user], authUser: makeAdminUser({ id: 99 }) });
      render(<UsersTable />);

      const actionsCol = getActionsCell();
      const { getByTestId } = render(
        actionsCol.cell({ row: { original: user } })
      );
      expect(getByTestId('icon-square-minus').closest('button')).not.toBeDisabled();
    });
  });

  // ── XCPasswordCell ─────────────────────────────────────────────────────────

  describe('XCPasswordCell', () => {
    const renderXCCell = (customProperties) => {
      const XCCell = getCol('custom_properties').cell;
      return render(<XCCell getValue={() => customProperties} />);
    };

    it('hides password by default (shows bullets)', () => {
      setupMocks();
      render(<UsersTable />);

      const { getByText } = renderXCCell({ xc_password: 'mypassword' });
      expect(getByText('••••••••')).toBeInTheDocument();
    });

    it('shows the password after clicking the eye toggle', () => {
      setupMocks();
      render(<UsersTable />);

      const { getByText, getByTestId } = renderXCCell({ xc_password: 'mypassword' });
      fireEvent.click(getByTestId('icon-eye').closest('button'));
      expect(getByText('mypassword')).toBeInTheDocument();
    });

    it('hides the password again after toggling twice', () => {
      setupMocks();
      render(<UsersTable />);

      const { getByText, getByTestId } = renderXCCell({ xc_password: 'mypassword' });
      const toggleBtn = getByTestId('icon-eye').closest('button');
      fireEvent.click(toggleBtn);
      fireEvent.click(getByTestId('icon-eye-off').closest('button'));
      expect(getByText('••••••••')).toBeInTheDocument();
    });

    it('shows "N/A" when no xc_password', () => {
      setupMocks();
      render(<UsersTable />);

      const { getByText } = renderXCCell({});
      expect(getByText('N/A')).toBeInTheDocument();
    });

    it('does not render the eye toggle when password is N/A', () => {
      setupMocks();
      render(<UsersTable />);

      const { queryByTestId } = renderXCCell({});
      expect(queryByTestId('icon-eye')).not.toBeInTheDocument();
    });

    it('shows "N/A" when custom_properties is null', () => {
      setupMocks();
      render(<UsersTable />);

      const { getByText } = renderXCCell(null);
      expect(getByText('N/A')).toBeInTheDocument();
    });
  });

  // ── Column cell renderers ──────────────────────────────────────────────────

  describe('user_level column', () => {
    it('renders the label for ADMIN level', () => {
      setupMocks();
      render(<UsersTable />);
      const col = getCol('user_level');
      const { getByText } = render(col.cell({ getValue: () => USER_LEVELS.ADMIN }));
      expect(getByText(USER_LEVEL_LABELS[USER_LEVELS.ADMIN])).toBeInTheDocument();
    });

    it('renders the label for STANDARD level', () => {
      setupMocks();
      render(<UsersTable />);
      const col = getCol('user_level');
      const { getByText } = render(col.cell({ getValue: () => USER_LEVELS.STANDARD }));
      expect(getByText(USER_LEVEL_LABELS[USER_LEVELS.STANDARD])).toBeInTheDocument();
    });
  });

  describe('name column (accessorFn)', () => {
    it('combines first_name and last_name', () => {
      setupMocks();
      render(<UsersTable />);
      const col = getCol('name');
      const value = col.accessorFn({ first_name: 'Jane', last_name: 'Doe' });
      expect(value).toBe('Jane Doe');
    });

    it('trims when only first_name is set', () => {
      setupMocks();
      render(<UsersTable />);
      const col = getCol('name');
      const value = col.accessorFn({ first_name: 'Jane', last_name: '' });
      expect(value).toBe('Jane');
    });

    it('cell renders "-" when value is empty', () => {
      setupMocks();
      render(<UsersTable />);
      const col = getCol('name');
      const { getByText } = render(col.cell({ getValue: () => '' }));
      expect(getByText('-')).toBeInTheDocument();
    });

    it('cell renders the full name when set', () => {
      setupMocks();
      render(<UsersTable />);
      const col = getCol('name');
      const { getByText } = render(col.cell({ getValue: () => 'Jane Doe' }));
      expect(getByText('Jane Doe')).toBeInTheDocument();
    });
  });

  describe('date_joined column', () => {
    it('calls format with fullDateFormat when date is present', () => {
      setupMocks();
      render(<UsersTable />);
      const col = getCol('date_joined');
      const { getByText } = render(col.cell({ getValue: () => '2024-01-15T10:00:00Z' }));
      expect(vi.mocked(format)).toHaveBeenCalledWith('2024-01-15T10:00:00Z', 'MM/DD/YYYY');
      expect(getByText('formatted:2024-01-15T10:00:00Z')).toBeInTheDocument();
    });

    it('renders "-" when date is null', () => {
      setupMocks();
      render(<UsersTable />);
      const col = getCol('date_joined');
      const { getByText } = render(col.cell({ getValue: () => null }));
      expect(getByText('-')).toBeInTheDocument();
    });
  });

  describe('last_login column', () => {
    it('calls format with fullDateTimeFormat when date is present', () => {
      setupMocks();
      render(<UsersTable />);
      const col = getCol('last_login');
      const { getByText } = render(col.cell({ getValue: () => '2024-06-01T12:00:00Z' }));
      expect(vi.mocked(format)).toHaveBeenCalledWith('2024-06-01T12:00:00Z', 'MM/DD/YYYY HH:mm');
      expect(getByText('formatted:2024-06-01T12:00:00Z')).toBeInTheDocument();
    });

    it('renders "Never" when last_login is null', () => {
      setupMocks();
      render(<UsersTable />);
      const col = getCol('last_login');
      const { getByText } = render(col.cell({ getValue: () => null }));
      expect(getByText('Never')).toBeInTheDocument();
    });
  });

  describe('channel_profiles column', () => {
    it('renders "All" badge when user has no profiles assigned', () => {
      setupMocks({ profiles: { 10: { id: 10, name: 'HD Profile' } } });
      render(<UsersTable />);
      const col = getCol('channel_profiles');
      const { getByText } = render(col.cell({ getValue: () => [] }));
      expect(getByText('All')).toBeInTheDocument();
    });

    it('renders a badge for each assigned profile', () => {
      setupMocks({
        profiles: { 10: { id: 10, name: 'HD Profile' }, 20: { id: 20, name: 'SD Profile' } },
      });
      render(<UsersTable />);
      const col = getCol('channel_profiles');
      const { getByText } = render(col.cell({ getValue: () => [10, 20] }));
      expect(getByText('HD Profile')).toBeInTheDocument();
      expect(getByText('SD Profile')).toBeInTheDocument();
    });

    it('renders "All" when profile ids do not match any profiles', () => {
      setupMocks({ profiles: {} });
      render(<UsersTable />);
      const col = getCol('channel_profiles');
      const { getByText } = render(col.cell({ getValue: () => [99] }));
      expect(getByText('All')).toBeInTheDocument();
    });
  });

  // ── useTable options ───────────────────────────────────────────────────────

  describe('useTable options', () => {
    it('passes enablePagination: false', () => {
      setupMocks();
      render(<UsersTable />);
      expect(capturedTableOptions.enablePagination).toBe(false);
    });

    it('passes enableRowSelection: false', () => {
      setupMocks();
      render(<UsersTable />);
      expect(capturedTableOptions.enableRowSelection).toBe(false);
    });

    it('passes manualSorting: false', () => {
      setupMocks();
      render(<UsersTable />);
      expect(capturedTableOptions.manualSorting).toBe(false);
    });
  });
});
