import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

// ── API mock ───────────────────────────────────────────────────────────────────
vi.mock('../../../api', () => ({
  default: {
    deleteUserAgent: vi.fn().mockResolvedValue(undefined),
  },
}));

// ── Store mocks ────────────────────────────────────────────────────────────────
vi.mock('../../../store/userAgents', () => ({ default: vi.fn() }));
vi.mock('../../../store/settings', () => ({ default: vi.fn() }));

// ── Hook mocks ─────────────────────────────────────────────────────────────────
vi.mock('../../../hooks/useLocalStorage', () => ({
  default: vi.fn(() => ['default', vi.fn()]),
}));

// ── Utility mocks ──────────────────────────────────────────────────────────────
vi.mock('../../../utils/notificationUtils.js', () => ({
  showNotification: vi.fn(),
}));

// ── Child component mocks ──────────────────────────────────────────────────────
vi.mock('../../forms/UserAgent', () => ({
  default: ({ isOpen, onClose, userAgent }) =>
    isOpen ? (
      <div data-testid="user-agent-form">
        <span data-testid="form-ua-name">{userAgent?.name ?? 'new'}</span>
        <button data-testid="form-close" onClick={onClose}>
          Close
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
  Box: ({ children, style }) => <div style={style}>{children}</div>,
  Button: ({ children, onClick, leftSection, disabled, loading }) => (
    <button data-testid="button" onClick={onClick} disabled={disabled || loading}>
      {leftSection}
      {children}
    </button>
  ),
  Center: ({ children }) => <div>{children}</div>,
  Flex: ({ children }) => <div>{children}</div>,
  Paper: ({ children, style }) => <div style={style}>{children}</div>,
  Stack: ({ children, style }) => <div style={style}>{children}</div>,
  Text: ({ children, name }) => (
    <span data-testid="text" data-name={name}>
      {children}
    </span>
  ),
  Tooltip: ({ children, label }) => (
    <div data-tooltip={label}>{children}</div>
  ),
}));

// ── lucide-react ───────────────────────────────────────────────────────────────
vi.mock('lucide-react', () => ({
  Check: ({ color }) => <svg data-testid="icon-check" data-color={color} />,
  SquareMinus: () => <svg data-testid="icon-square-minus" />,
  SquarePen: () => <svg data-testid="icon-square-pen" />,
  SquarePlus: () => <svg data-testid="icon-square-plus" />,
  X: ({ color }) => <svg data-testid="icon-x" data-color={color} />,
}));

// ── Imports after mocks ────────────────────────────────────────────────────────
import useUserAgentsStore from '../../../store/userAgents';
import useSettingsStore from '../../../store/settings';
import { useTable } from '../CustomTable';
import { showNotification } from '../../../utils/notificationUtils.js';
import API from '../../../api';
import UserAgentsTable from '../UserAgentsTable';

// ── Factories ──────────────────────────────────────────────────────────────────
const makeUA = (overrides = {}) => ({
  id: 1,
  name: 'Chrome Default',
  user_agent: 'Mozilla/5.0 Chrome/120',
  description: 'Standard Chrome UA',
  is_active: true,
  ...overrides,
});

let capturedTableOptions = null;

const setupMocks = ({
  userAgents = [makeUA()],
  defaultUserAgentId = 99,
} = {}) => {
  vi.mocked(useUserAgentsStore).mockImplementation((sel) =>
    sel({ userAgents })
  );

  vi.mocked(useSettingsStore).mockImplementation((sel) =>
    sel({ settings: { default_user_agent: defaultUserAgentId } })
  );

  vi.mocked(useTable).mockImplementation((opts) => {
    capturedTableOptions = opts;
    return {
      getRowModel: () => ({ rows: [] }),
      getHeaderGroups: () => [],
    };
  });
};

const makeRowCtx = (ua) => ({
  row: { id: String(ua.id), original: ua },
  cell: {
    column: { id: 'actions', columnDef: {} },
    getValue: vi.fn(() => undefined),
  },
});

// ══════════════════════════════════════════════════════════════════════════════
// Tests
// ══════════════════════════════════════════════════════════════════════════════

describe('UserAgentsTable', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    capturedTableOptions = null;
    vi.mocked(API.deleteUserAgent).mockResolvedValue(undefined);
  });

  // ── Rendering ──────────────────────────────────────────────────────────────

  describe('rendering', () => {
    it('renders the "Add User-Agent" button', () => {
      setupMocks();
      render(<UserAgentsTable />);
      expect(screen.getByText('Add User-Agent')).toBeInTheDocument();
    });

    it('renders the custom table', () => {
      setupMocks();
      render(<UserAgentsTable />);
      expect(screen.getByTestId('custom-table')).toBeInTheDocument();
    });

    it('does not render the form on initial load', () => {
      setupMocks();
      render(<UserAgentsTable />);
      expect(screen.queryByTestId('user-agent-form')).not.toBeInTheDocument();
    });

    it('passes all userAgents to useTable as data', () => {
      const uas = [makeUA({ id: 1 }), makeUA({ id: 2 })];
      setupMocks({ userAgents: uas });
      render(<UserAgentsTable />);
      expect(capturedTableOptions.data).toHaveLength(2);
    });

    it('passes an empty array when no userAgents exist', () => {
      setupMocks({ userAgents: [] });
      render(<UserAgentsTable />);
      expect(capturedTableOptions.data).toHaveLength(0);
    });
  });

  // ── Add User-Agent ─────────────────────────────────────────────────────────

  describe('Add User-Agent', () => {
    it('opens the form with no user-agent when "Add User-Agent" is clicked', () => {
      setupMocks();
      render(<UserAgentsTable />);
      fireEvent.click(screen.getByText('Add User-Agent'));
      expect(screen.getByTestId('user-agent-form')).toBeInTheDocument();
      expect(screen.getByTestId('form-ua-name')).toHaveTextContent('new');
    });

    it('closes the form when onClose is called', () => {
      setupMocks();
      render(<UserAgentsTable />);
      fireEvent.click(screen.getByText('Add User-Agent'));
      fireEvent.click(screen.getByTestId('form-close'));
      expect(screen.queryByTestId('user-agent-form')).not.toBeInTheDocument();
    });
  });

  // ── Edit via RowActions ────────────────────────────────────────────────────

  describe('edit user-agent via RowActions', () => {
    it('opens the form populated with the user-agent when edit icon is clicked', () => {
      const ua = makeUA({ name: 'Firefox UA' });
      setupMocks({ userAgents: [ua] });
      render(<UserAgentsTable />);

      const { row, cell } = makeRowCtx(ua);
      const { getByTestId } = render(
        capturedTableOptions.bodyCellRenderFns.actions({ cell, row })
      );
      fireEvent.click(getByTestId('icon-square-pen').closest('button'));

      expect(screen.getByTestId('user-agent-form')).toBeInTheDocument();
      expect(screen.getByTestId('form-ua-name')).toHaveTextContent('Firefox UA');
    });

    it('closes the form after editing when onClose is called', () => {
      const ua = makeUA({ name: 'Firefox UA' });
      setupMocks({ userAgents: [ua] });
      render(<UserAgentsTable />);

      const { row, cell } = makeRowCtx(ua);
      const { getByTestId } = render(
        capturedTableOptions.bodyCellRenderFns.actions({ cell, row })
      );
      fireEvent.click(getByTestId('icon-square-pen').closest('button'));
      fireEvent.click(screen.getByTestId('form-close'));

      expect(screen.queryByTestId('user-agent-form')).not.toBeInTheDocument();
    });
  });

  // ── Delete via RowActions (single) ─────────────────────────────────────────

  describe('delete user-agent via RowActions (single id)', () => {
    it('calls API.deleteUserAgent with the user-agent id', async () => {
      const ua = makeUA({ id: 7 });
      setupMocks({ userAgents: [ua] });
      render(<UserAgentsTable />);

      const { row, cell } = makeRowCtx(ua);
      const { getByTestId } = render(
        capturedTableOptions.bodyCellRenderFns.actions({ cell, row })
      );
      fireEvent.click(getByTestId('icon-square-minus').closest('button'));

      await waitFor(() =>
        expect(API.deleteUserAgent).toHaveBeenCalledWith(7)
      );
    });

    it('shows a notification and does NOT call API when deleting the default user-agent', async () => {
      const ua = makeUA({ id: 5 });
      setupMocks({ userAgents: [ua], defaultUserAgentId: 5 });
      render(<UserAgentsTable />);

      const { row, cell } = makeRowCtx(ua);
      const { getByTestId } = render(
        capturedTableOptions.bodyCellRenderFns.actions({ cell, row })
      );
      fireEvent.click(getByTestId('icon-square-minus').closest('button'));

      await waitFor(() =>
        expect(showNotification).toHaveBeenCalledWith(
          expect.objectContaining({
            title: 'Cannot delete default user-agent',
            color: 'red.5',
          })
        )
      );
      expect(API.deleteUserAgent).not.toHaveBeenCalled();
    });
  });

  // ── Active column cell renderer ────────────────────────────────────────────

  describe('is_active column cell renderer', () => {
    const renderIsActiveCell = (value) => {
      const col = capturedTableOptions.columns.find(
        (c) => c.accessorKey === 'is_active'
      );
      return col.cell({ cell: { getValue: () => value } });
    };

    it('renders Check icon when is_active is true', () => {
      setupMocks();
      render(<UserAgentsTable />);

      const { getByTestId } = render(renderIsActiveCell(true));
      expect(getByTestId('icon-check')).toBeInTheDocument();
    });

    it('renders X icon when is_active is false', () => {
      setupMocks();
      render(<UserAgentsTable />);

      const { getByTestId } = render(renderIsActiveCell(false));
      expect(getByTestId('icon-x')).toBeInTheDocument();
    });
  });

  // ── user_agent column cell renderer ───────────────────────────────────────

  describe('user_agent column cell renderer', () => {
    it('renders the user_agent string', () => {
      setupMocks();
      render(<UserAgentsTable />);

      const col = capturedTableOptions.columns.find(
        (c) => c.accessorKey === 'user_agent'
      );
      const { getByText } = render(
        col.cell({ cell: { getValue: () => 'Mozilla/5.0 Safari/537' } })
      );
      expect(getByText('Mozilla/5.0 Safari/537')).toBeInTheDocument();
    });
  });

  // ── description column cell renderer ──────────────────────────────────────

  describe('description column cell renderer', () => {
    it('renders the description string', () => {
      setupMocks();
      render(<UserAgentsTable />);

      const col = capturedTableOptions.columns.find(
        (c) => c.accessorKey === 'description'
      );
      const { getByText } = render(
        col.cell({ cell: { getValue: () => 'A custom user agent' } })
      );
      expect(getByText('A custom user agent')).toBeInTheDocument();
    });
  });

  // ── store reactivity ───────────────────────────────────────────────────────

  describe('store reactivity', () => {
    it('passes allRowIds derived from userAgent ids to useTable', () => {
      const uas = [makeUA({ id: 10 }), makeUA({ id: 20 }), makeUA({ id: 30 })];
      setupMocks({ userAgents: uas });
      render(<UserAgentsTable />);
      expect(capturedTableOptions.allRowIds).toEqual([10, 20, 30]);
    });
  });
});
