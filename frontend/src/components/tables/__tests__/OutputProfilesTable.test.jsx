import React from 'react';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

// ── Store mocks ────────────────────────────────────────────────────────────────
vi.mock('../../../store/outputProfiles', () => ({ default: vi.fn() }));

// ── Hook mocks ─────────────────────────────────────────────────────────────────
vi.mock('../../../hooks/useLocalStorage', () => ({
  default: vi.fn(() => ['default', vi.fn()]),
}));

// ── Utility mocks ──────────────────────────────────────────────────────────────
vi.mock('../../../utils/tables/OutputProfilesTableUtils.js', () => ({
  deleteOutputProfile: vi.fn().mockResolvedValue(undefined),
  updateOutputProfile: vi.fn().mockResolvedValue(undefined),
}));

// ── Child component mocks ──────────────────────────────────────────────────────
vi.mock('../../forms/OutputProfile', () => ({
  default: ({ isOpen, onClose, profile }) =>
    isOpen ? (
      <div data-testid="output-profile-form">
        <span data-testid="form-profile-name">{profile?.name ?? 'new'}</span>
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
  Switch: ({ checked, onChange, disabled }) => (
    <input
      data-testid="active-switch"
      type="checkbox"
      checked={checked ?? false}
      onChange={onChange}
      disabled={disabled}
    />
  ),
  Text: ({ children, size, style }) => (
    <span data-testid="text" data-size={size} style={style}>
      {children}
    </span>
  ),
  Tooltip: ({ children, label }) => (
    <div data-tooltip={label}>{children}</div>
  ),
  useMantineTheme: vi.fn(() => ({
    palette: { background: { paper: '#1a1a1a' } },
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
import useOutputProfilesStore from '../../../store/outputProfiles';
import useLocalStorage from '../../../hooks/useLocalStorage';
import * as OutputProfilesTableUtils from '../../../utils/tables/OutputProfilesTableUtils.js';
import { useTable } from '../CustomTable';
import OutputProfiles from '../OutputProfilesTable';

// ── Factories ──────────────────────────────────────────────────────────────────
const makeProfile = (overrides = {}) => ({
  id: 1,
  name: 'Test Profile',
  command: 'ffmpeg',
  parameters: '-c:v copy',
  is_active: true,
  locked: false,
  ...overrides,
});

let capturedTableOptions = null;

const setupMocks = ({
  profiles = [makeProfile()],
  tableSize = 'default',
} = {}) => {
  vi.mocked(useOutputProfilesStore).mockImplementation((sel) =>
    sel({ profiles })
  );

  vi.mocked(useLocalStorage).mockReturnValue([tableSize, vi.fn()]);

  vi.mocked(useTable).mockImplementation((opts) => {
    capturedTableOptions = opts;
    return {
      getRowModel: () => ({ rows: [] }),
      getHeaderGroups: () => [],
    };
  });
};

const getCol = (keyOrId) =>
  capturedTableOptions.columns.find(
    (c) => c.accessorKey === keyOrId || c.id === keyOrId
  );

const makeRowCtx = (profile) => ({
  row: { id: String(profile.id), original: profile },
  cell: { column: { id: 'actions', columnDef: {} }, getValue: vi.fn(() => undefined) },
});

// ══════════════════════════════════════════════════════════════════════════════
// Tests
// ══════════════════════════════════════════════════════════════════════════════

describe('OutputProfiles', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    capturedTableOptions = null;
    vi.mocked(OutputProfilesTableUtils.deleteOutputProfile).mockResolvedValue(undefined);
    vi.mocked(OutputProfilesTableUtils.updateOutputProfile).mockResolvedValue(undefined);
  });

  // ── Rendering ──────────────────────────────────────────────────────────────

  describe('rendering', () => {
    it('renders the "Add Output Profile" button', () => {
      setupMocks();
      render(<OutputProfiles />);
      expect(screen.getByText('Add Output Profile')).toBeInTheDocument();
    });

    it('renders the hide/show inactive toggle button', () => {
      setupMocks();
      render(<OutputProfiles />);
      expect(screen.getByTestId('icon-eye')).toBeInTheDocument();
    });

    it('renders the custom table', () => {
      setupMocks();
      render(<OutputProfiles />);
      expect(screen.getByTestId('custom-table')).toBeInTheDocument();
    });

    it('does not render the form on initial load', () => {
      setupMocks();
      render(<OutputProfiles />);
      expect(screen.queryByTestId('output-profile-form')).not.toBeInTheDocument();
    });

    it('passes all unlocked+active profiles to useTable when hideInactive is false', () => {
      setupMocks({
        profiles: [
          makeProfile({ id: 1, name: 'Active', is_active: true }),
          makeProfile({ id: 2, name: 'Inactive', is_active: false }),
        ],
      });
      render(<OutputProfiles />);
      expect(capturedTableOptions.data).toHaveLength(2);
    });
  });

  // ── Add Output Profile ─────────────────────────────────────────────────────

  describe('Add Output Profile', () => {
    it('opens the form with no profile when "Add Output Profile" is clicked', () => {
      setupMocks();
      render(<OutputProfiles />);
      fireEvent.click(screen.getByText('Add Output Profile'));
      expect(screen.getByTestId('output-profile-form')).toBeInTheDocument();
      expect(screen.getByTestId('form-profile-name')).toHaveTextContent('new');
    });

    it('closes the form when onClose is called', () => {
      setupMocks();
      render(<OutputProfiles />);
      fireEvent.click(screen.getByText('Add Output Profile'));
      fireEvent.click(screen.getByTestId('form-close'));
      expect(screen.queryByTestId('output-profile-form')).not.toBeInTheDocument();
    });
  });

  // ── Edit Output Profile (RowActions) ───────────────────────────────────────

  describe('edit profile via RowActions', () => {
    it('opens the form populated with the profile when edit icon is clicked', () => {
      const profile = makeProfile({ name: 'My Profile' });
      setupMocks({ profiles: [profile] });
      render(<OutputProfiles />);

      const { row, cell } = makeRowCtx(profile);
      const { getByTestId } = render(
        capturedTableOptions.bodyCellRenderFns.actions({ cell, row })
      );
      fireEvent.click(getByTestId('icon-square-pen').closest('button'));

      expect(screen.getByTestId('output-profile-form')).toBeInTheDocument();
      expect(screen.getByTestId('form-profile-name')).toHaveTextContent('My Profile');
    });

    it('closes the form after editing when onClose is called', () => {
      const profile = makeProfile({ name: 'My Profile' });
      setupMocks({ profiles: [profile] });
      render(<OutputProfiles />);

      const { row, cell } = makeRowCtx(profile);
      const { getByTestId } = render(
        capturedTableOptions.bodyCellRenderFns.actions({ cell, row })
      );
      fireEvent.click(getByTestId('icon-square-pen').closest('button'));
      fireEvent.click(screen.getByTestId('form-close'));

      expect(screen.queryByTestId('output-profile-form')).not.toBeInTheDocument();
    });

    it('edit button is disabled when profile is locked', () => {
      const profile = makeProfile({ locked: true });
      setupMocks({ profiles: [profile] });
      render(<OutputProfiles />);

      const { row, cell } = makeRowCtx(profile);
      const { getByTestId } = render(
        capturedTableOptions.bodyCellRenderFns.actions({ cell, row })
      );
      expect(getByTestId('icon-square-pen').closest('button')).toBeDisabled();
    });

    it('edit button is enabled when profile is not locked', () => {
      const profile = makeProfile({ locked: false });
      setupMocks({ profiles: [profile] });
      render(<OutputProfiles />);

      const { row, cell } = makeRowCtx(profile);
      const { getByTestId } = render(
        capturedTableOptions.bodyCellRenderFns.actions({ cell, row })
      );
      expect(getByTestId('icon-square-pen').closest('button')).not.toBeDisabled();
    });
  });

  // ── Delete Output Profile (RowActions) ────────────────────────────────────

  describe('delete profile via RowActions', () => {
    it('calls deleteOutputProfile with the profile id when delete icon is clicked', async () => {
      const profile = makeProfile({ id: 7 });
      setupMocks({ profiles: [profile] });
      render(<OutputProfiles />);

      const { row, cell } = makeRowCtx(profile);
      const { getByTestId } = render(
        capturedTableOptions.bodyCellRenderFns.actions({ cell, row })
      );
      fireEvent.click(getByTestId('icon-square-minus').closest('button'));

      await waitFor(() =>
        expect(OutputProfilesTableUtils.deleteOutputProfile).toHaveBeenCalledWith(7)
      );
    });

    it('delete button is disabled when profile is locked', () => {
      const profile = makeProfile({ locked: true });
      setupMocks({ profiles: [profile] });
      render(<OutputProfiles />);

      const { row, cell } = makeRowCtx(profile);
      const { getByTestId } = render(
        capturedTableOptions.bodyCellRenderFns.actions({ cell, row })
      );
      expect(getByTestId('icon-square-minus').closest('button')).toBeDisabled();
    });

    it('delete button is enabled when profile is not locked', () => {
      const profile = makeProfile({ locked: false });
      setupMocks({ profiles: [profile] });
      render(<OutputProfiles />);

      const { row, cell } = makeRowCtx(profile);
      const { getByTestId } = render(
        capturedTableOptions.bodyCellRenderFns.actions({ cell, row })
      );
      expect(getByTestId('icon-square-minus').closest('button')).not.toBeDisabled();
    });

    it('does not throw when deleteOutputProfile rejects', async () => {
      vi.mocked(OutputProfilesTableUtils.deleteOutputProfile).mockRejectedValue(
        new Error('server error')
      );
      const profile = makeProfile({ id: 1 });
      setupMocks({ profiles: [profile] });
      render(<OutputProfiles />);

      const { row, cell } = makeRowCtx(profile);
      const { getByTestId } = render(
        capturedTableOptions.bodyCellRenderFns.actions({ cell, row })
      );
      await expect(
        act(async () => fireEvent.click(getByTestId('icon-square-minus').closest('button')))
      ).resolves.not.toThrow();
    });
  });

  // ── Toggle active (is_active Switch) ──────────────────────────────────────

  describe('toggle profile is_active', () => {
    const renderSwitch = (profile) => {
      const col = getCol('is_active');
      return col.cell({
        cell: { getValue: () => profile.is_active },
        row: { original: profile },
      });
    };

    it('calls updateOutputProfile with is_active toggled to false', async () => {
      const profile = makeProfile({ is_active: true });
      setupMocks({ profiles: [profile] });
      render(<OutputProfiles />);

      const { getByTestId } = render(renderSwitch(profile));
      fireEvent.click(getByTestId('active-switch'));

      await waitFor(() =>
        expect(OutputProfilesTableUtils.updateOutputProfile).toHaveBeenCalledWith(
          expect.objectContaining({ id: profile.id, is_active: false })
        )
      );
    });

    it('calls updateOutputProfile with is_active toggled to true', async () => {
      const profile = makeProfile({ is_active: false });
      setupMocks({ profiles: [profile] });
      render(<OutputProfiles />);

      const { getByTestId } = render(renderSwitch(profile));
      fireEvent.click(getByTestId('active-switch'));

      await waitFor(() =>
        expect(OutputProfilesTableUtils.updateOutputProfile).toHaveBeenCalledWith(
          expect.objectContaining({ id: profile.id, is_active: true })
        )
      );
    });

    it('switch is disabled when profile is locked', () => {
      const profile = makeProfile({ locked: true });
      setupMocks({ profiles: [profile] });
      render(<OutputProfiles />);

      const { getByTestId } = render(renderSwitch(profile));
      expect(getByTestId('active-switch')).toBeDisabled();
    });

    it('switch is enabled when profile is not locked', () => {
      const profile = makeProfile({ locked: false });
      setupMocks({ profiles: [profile] });
      render(<OutputProfiles />);

      const { getByTestId } = render(renderSwitch(profile));
      expect(getByTestId('active-switch')).not.toBeDisabled();
    });
  });

  // ── Hide inactive toggle ───────────────────────────────────────────────────

  describe('hide inactive toggle', () => {
    it('shows Eye icon when hideInactive is false (default)', () => {
      setupMocks();
      render(<OutputProfiles />);
      expect(screen.getByTestId('icon-eye')).toBeInTheDocument();
      expect(screen.queryByTestId('icon-eye-off')).not.toBeInTheDocument();
    });

    it('shows EyeOff icon after the toggle is clicked', () => {
      setupMocks();
      render(<OutputProfiles />);
      const toggleBtn = screen.getByTestId('icon-eye').closest('button');
      fireEvent.click(toggleBtn);
      expect(screen.getByTestId('icon-eye-off')).toBeInTheDocument();
      expect(screen.queryByTestId('icon-eye')).not.toBeInTheDocument();
    });

    it('shows Eye icon again after toggling twice', () => {
      setupMocks();
      render(<OutputProfiles />);
      const toggleBtn = screen.getByTestId('icon-eye').closest('button');
      fireEvent.click(toggleBtn);
      fireEvent.click(screen.getByTestId('icon-eye-off').closest('button'));
      expect(screen.getByTestId('icon-eye')).toBeInTheDocument();
    });

    it('excludes inactive profiles from table data when hideInactive is true', () => {
      setupMocks({
        profiles: [
          makeProfile({ id: 1, name: 'Active', is_active: true }),
          makeProfile({ id: 2, name: 'Inactive', is_active: false }),
        ],
      });
      render(<OutputProfiles />);

      fireEvent.click(screen.getByTestId('icon-eye').closest('button'));

      expect(capturedTableOptions.data).toHaveLength(1);
      expect(capturedTableOptions.data[0].name).toBe('Active');
    });

    it('restores all profiles when hideInactive is turned back off', () => {
      setupMocks({
        profiles: [
          makeProfile({ id: 1, name: 'Active', is_active: true }),
          makeProfile({ id: 2, name: 'Inactive', is_active: false }),
        ],
      });
      render(<OutputProfiles />);

      const toggleBtn = screen.getByTestId('icon-eye').closest('button');
      fireEvent.click(toggleBtn); // hide inactive
      fireEvent.click(screen.getByTestId('icon-eye-off').closest('button')); // show all

      expect(capturedTableOptions.data).toHaveLength(2);
    });

    it('does not filter already-active profiles when hideInactive is true', () => {
      setupMocks({
        profiles: [
          makeProfile({ id: 1, is_active: true }),
          makeProfile({ id: 2, is_active: true }),
        ],
      });
      render(<OutputProfiles />);
      fireEvent.click(screen.getByTestId('icon-eye').closest('button'));
      expect(capturedTableOptions.data).toHaveLength(2);
    });
  });

  // ── Column: Name ───────────────────────────────────────────────────────────

  describe('Name column', () => {
    it('renders the profile name', () => {
      setupMocks();
      render(<OutputProfiles />);
      const col = getCol('name');
      const { getByText } = render(
        col.cell({ cell: { getValue: () => 'My Profile' } })
      );
      expect(getByText('My Profile')).toBeInTheDocument();
    });
  });

  // ── Column: Command ────────────────────────────────────────────────────────

  describe('Command column', () => {
    it('renders the command value', () => {
      setupMocks();
      render(<OutputProfiles />);
      const col = getCol('command');
      const { getByText } = render(
        col.cell({ cell: { getValue: () => 'ffmpeg' } })
      );
      expect(getByText('ffmpeg')).toBeInTheDocument();
    });
  });

  // ── Column: Parameters ─────────────────────────────────────────────────────

  describe('Parameters column', () => {
    it('renders the parameters value', () => {
      setupMocks();
      render(<OutputProfiles />);
      const col = getCol('parameters');
      const { getByText } = render(
        col.cell({ cell: { getValue: () => '-c:v copy -preset fast' } })
      );
      expect(getByText('-c:v copy -preset fast')).toBeInTheDocument();
    });
  });

  // ── Store reactivity ───────────────────────────────────────────────────────

  describe('store reactivity', () => {
    it('passes store profiles directly to the table data', () => {
      const profiles = [
        makeProfile({ id: 1, name: 'Alpha' }),
        makeProfile({ id: 2, name: 'Beta' }),
      ];
      setupMocks({ profiles });
      render(<OutputProfiles />);
      expect(capturedTableOptions.data).toHaveLength(2);
      expect(capturedTableOptions.data.map((p) => p.name)).toEqual(['Alpha', 'Beta']);
    });

    it('passes an empty array to the table when no profiles exist', () => {
      setupMocks({ profiles: [] });
      render(<OutputProfiles />);
      expect(capturedTableOptions.data).toHaveLength(0);
    });
  });
});
