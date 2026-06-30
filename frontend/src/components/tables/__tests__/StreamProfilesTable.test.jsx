import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

// ── API mock ───────────────────────────────────────────────────────────────────
vi.mock('../../../api', () => ({
  default: {
    deleteStreamProfile: vi.fn().mockResolvedValue(undefined),
  },
}));

// ── Store mocks ────────────────────────────────────────────────────────────────
vi.mock('../../../store/streamProfiles', () => ({ default: vi.fn() }));
vi.mock('../../../store/settings', () => ({ default: vi.fn() }));

// ── Hook mocks ─────────────────────────────────────────────────────────────────
vi.mock('../../../hooks/useLocalStorage', () => ({
  default: vi.fn(() => ['default', vi.fn()]),
}));

// ── Utility mocks ──────────────────────────────────────────────────────────────
vi.mock('../../../utils/notificationUtils.js', () => ({
  showNotification: vi.fn(),
}));

vi.mock('../../../utils/forms/StreamProfileUtils.js', () => ({
  updateStreamProfile: vi.fn().mockResolvedValue(undefined),
}));

// ── Child component mocks ──────────────────────────────────────────────────────
vi.mock('../../forms/StreamProfile', () => ({
  default: ({ isOpen, onClose, profile }) =>
    isOpen ? (
      <div data-testid="stream-profile-form">
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
  Text: ({ children, name }) => (
    <span data-testid="text" data-name={name}>
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
import useStreamProfilesStore from '../../../store/streamProfiles';
import useSettingsStore from '../../../store/settings';
import { useTable } from '../CustomTable';
import { showNotification } from '../../../utils/notificationUtils.js';
import { updateStreamProfile } from '../../../utils/forms/StreamProfileUtils.js';
import API from '../../../api';
import StreamProfiles from '../StreamProfilesTable';

// ── Factories ──────────────────────────────────────────────────────────────────
const makeProfile = (overrides = {}) => ({
  id: 1,
  name: 'Test Profile',
  command: 'ffmpeg',
  parameters: '-c copy',
  is_active: true,
  locked: false,
  ...overrides,
});

let capturedTableOptions = null;

const setupMocks = ({
  profiles = [makeProfile()],
  defaultProfileId = 99,
} = {}) => {
  vi.mocked(useStreamProfilesStore).mockImplementation((sel) =>
    sel({ profiles })
  );

  vi.mocked(useSettingsStore).mockImplementation((sel) =>
    sel({ settings: { default_stream_profile: defaultProfileId } })
  );

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
  cell: {
    column: { id: 'actions', columnDef: {} },
    getValue: vi.fn(() => undefined),
  },
});

// ══════════════════════════════════════════════════════════════════════════════
// Tests
// ══════════════════════════════════════════════════════════════════════════════

describe('StreamProfiles', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    capturedTableOptions = null;
    vi.mocked(API.deleteStreamProfile).mockResolvedValue(undefined);
    vi.mocked(updateStreamProfile).mockResolvedValue(undefined);
  });

  // ── Rendering ──────────────────────────────────────────────────────────────

  describe('rendering', () => {
    it('renders the "Add Stream Profile" button', () => {
      setupMocks();
      render(<StreamProfiles />);
      expect(screen.getByText('Add Stream Profile')).toBeInTheDocument();
    });

    it('renders the hide/show inactive toggle button', () => {
      setupMocks();
      render(<StreamProfiles />);
      expect(screen.getByTestId('icon-eye')).toBeInTheDocument();
    });

    it('renders the custom table', () => {
      setupMocks();
      render(<StreamProfiles />);
      expect(screen.getByTestId('custom-table')).toBeInTheDocument();
    });

    it('does not render the form on initial load', () => {
      setupMocks();
      render(<StreamProfiles />);
      expect(screen.queryByTestId('stream-profile-form')).not.toBeInTheDocument();
    });

    it('passes all profiles to useTable when hideInactive is false', () => {
      setupMocks({
        profiles: [
          makeProfile({ id: 1, name: 'Active', is_active: true }),
          makeProfile({ id: 2, name: 'Inactive', is_active: false }),
        ],
      });
      render(<StreamProfiles />);
      expect(capturedTableOptions.data).toHaveLength(2);
    });
  });

  // ── Add Stream Profile ─────────────────────────────────────────────────────

  describe('Add Stream Profile', () => {
    it('opens the form with no profile when "Add Stream Profile" is clicked', () => {
      setupMocks();
      render(<StreamProfiles />);
      fireEvent.click(screen.getByText('Add Stream Profile'));
      expect(screen.getByTestId('stream-profile-form')).toBeInTheDocument();
      expect(screen.getByTestId('form-profile-name')).toHaveTextContent('new');
    });

    it('closes the form when onClose is called', () => {
      setupMocks();
      render(<StreamProfiles />);
      fireEvent.click(screen.getByText('Add Stream Profile'));
      fireEvent.click(screen.getByTestId('form-close'));
      expect(screen.queryByTestId('stream-profile-form')).not.toBeInTheDocument();
    });
  });

  // ── Edit profile via RowActions ────────────────────────────────────────────

  describe('edit profile via RowActions', () => {
    it('opens the form populated with the profile when edit icon is clicked', () => {
      const profile = makeProfile({ name: 'My Profile' });
      setupMocks({ profiles: [profile] });
      render(<StreamProfiles />);

      const { row, cell } = makeRowCtx(profile);
      const { getByTestId } = render(
        capturedTableOptions.bodyCellRenderFns.actions({ cell, row })
      );
      fireEvent.click(getByTestId('icon-square-pen').closest('button'));

      expect(screen.getByTestId('stream-profile-form')).toBeInTheDocument();
      expect(screen.getByTestId('form-profile-name')).toHaveTextContent('My Profile');
    });

    it('closes the form after editing when onClose is called', () => {
      const profile = makeProfile({ name: 'My Profile' });
      setupMocks({ profiles: [profile] });
      render(<StreamProfiles />);

      const { row, cell } = makeRowCtx(profile);
      const { getByTestId } = render(
        capturedTableOptions.bodyCellRenderFns.actions({ cell, row })
      );
      fireEvent.click(getByTestId('icon-square-pen').closest('button'));
      fireEvent.click(screen.getByTestId('form-close'));

      expect(screen.queryByTestId('stream-profile-form')).not.toBeInTheDocument();
    });

    it('edit button is disabled when profile is locked', () => {
      const profile = makeProfile({ locked: true });
      setupMocks({ profiles: [profile] });
      render(<StreamProfiles />);

      const { row, cell } = makeRowCtx(profile);
      const { getByTestId } = render(
        capturedTableOptions.bodyCellRenderFns.actions({ cell, row })
      );
      expect(getByTestId('icon-square-pen').closest('button')).toBeDisabled();
    });

    it('edit button is enabled when profile is not locked', () => {
      const profile = makeProfile({ locked: false });
      setupMocks({ profiles: [profile] });
      render(<StreamProfiles />);

      const { row, cell } = makeRowCtx(profile);
      const { getByTestId } = render(
        capturedTableOptions.bodyCellRenderFns.actions({ cell, row })
      );
      expect(getByTestId('icon-square-pen').closest('button')).not.toBeDisabled();
    });
  });

  // ── Delete profile via RowActions ──────────────────────────────────────────

  describe('delete profile via RowActions', () => {
    it('calls API.deleteStreamProfile with the profile id when delete icon is clicked', async () => {
      const profile = makeProfile({ id: 7 });
      setupMocks({ profiles: [profile] });
      render(<StreamProfiles />);

      const { row, cell } = makeRowCtx(profile);
      const { getByTestId } = render(
        capturedTableOptions.bodyCellRenderFns.actions({ cell, row })
      );
      fireEvent.click(getByTestId('icon-square-minus').closest('button'));

      await waitFor(() =>
        expect(API.deleteStreamProfile).toHaveBeenCalledWith(7)
      );
    });

    it('shows a notification and does NOT call API when deleting the default profile', async () => {
      const profile = makeProfile({ id: 5 });
      setupMocks({ profiles: [profile], defaultProfileId: 5 });
      render(<StreamProfiles />);

      const { row, cell } = makeRowCtx(profile);
      const { getByTestId } = render(
        capturedTableOptions.bodyCellRenderFns.actions({ cell, row })
      );
      fireEvent.click(getByTestId('icon-square-minus').closest('button'));

      await waitFor(() =>
        expect(showNotification).toHaveBeenCalledWith(
          expect.objectContaining({
            title: 'Cannot delete default stream-profile',
            color: 'red.5',
          })
        )
      );
      expect(API.deleteStreamProfile).not.toHaveBeenCalled();
    });

    it('delete button is disabled when profile is locked', () => {
      const profile = makeProfile({ locked: true });
      setupMocks({ profiles: [profile] });
      render(<StreamProfiles />);

      const { row, cell } = makeRowCtx(profile);
      const { getByTestId } = render(
        capturedTableOptions.bodyCellRenderFns.actions({ cell, row })
      );
      expect(getByTestId('icon-square-minus').closest('button')).toBeDisabled();
    });

    it('delete button is enabled when profile is not locked', () => {
      const profile = makeProfile({ locked: false });
      setupMocks({ profiles: [profile] });
      render(<StreamProfiles />);

      const { row, cell } = makeRowCtx(profile);
      const { getByTestId } = render(
        capturedTableOptions.bodyCellRenderFns.actions({ cell, row })
      );
      expect(getByTestId('icon-square-minus').closest('button')).not.toBeDisabled();
    });
  });

  // ── Toggle profile is_active ───────────────────────────────────────────────

  describe('toggle profile is_active', () => {
    const renderSwitch = (profile) => {
      const col = getCol('is_active');
      return col.cell({
        cell: { getValue: () => profile.is_active },
        row: { original: profile },
      });
    };

    it('calls updateStreamProfile with is_active toggled to false', async () => {
      const profile = makeProfile({ is_active: true });
      setupMocks({ profiles: [profile] });
      render(<StreamProfiles />);

      const { getByTestId } = render(renderSwitch(profile));
      fireEvent.click(getByTestId('active-switch'));

      await waitFor(() =>
        expect(updateStreamProfile).toHaveBeenCalledWith(
          profile.id,
          expect.objectContaining({ id: profile.id, is_active: false })
        )
      );
    });

    it('calls updateStreamProfile with is_active toggled to true', async () => {
      const profile = makeProfile({ is_active: false });
      setupMocks({ profiles: [profile] });
      render(<StreamProfiles />);

      const { getByTestId } = render(renderSwitch(profile));
      fireEvent.click(getByTestId('active-switch'));

      await waitFor(() =>
        expect(updateStreamProfile).toHaveBeenCalledWith(
          profile.id,
          expect.objectContaining({ id: profile.id, is_active: true })
        )
      );
    });

    it('switch is disabled when profile is locked', () => {
      const profile = makeProfile({ locked: true });
      setupMocks({ profiles: [profile] });
      render(<StreamProfiles />);

      const { getByTestId } = render(renderSwitch(profile));
      expect(getByTestId('active-switch')).toBeDisabled();
    });

    it('switch is enabled when profile is not locked', () => {
      const profile = makeProfile({ locked: false });
      setupMocks({ profiles: [profile] });
      render(<StreamProfiles />);

      const { getByTestId } = render(renderSwitch(profile));
      expect(getByTestId('active-switch')).not.toBeDisabled();
    });
  });

  // ── Hide inactive toggle ───────────────────────────────────────────────────

  describe('hide inactive toggle', () => {
    it('shows Eye icon when hideInactive is false (default)', () => {
      setupMocks();
      render(<StreamProfiles />);
      expect(screen.getByTestId('icon-eye')).toBeInTheDocument();
      expect(screen.queryByTestId('icon-eye-off')).not.toBeInTheDocument();
    });

    it('shows EyeOff icon after the toggle is clicked', () => {
      setupMocks();
      render(<StreamProfiles />);
      fireEvent.click(screen.getByTestId('icon-eye').closest('button'));
      expect(screen.getByTestId('icon-eye-off')).toBeInTheDocument();
      expect(screen.queryByTestId('icon-eye')).not.toBeInTheDocument();
    });

    it('shows Eye icon again after toggling twice', () => {
      setupMocks();
      render(<StreamProfiles />);
      const btn = screen.getByTestId('icon-eye').closest('button');
      fireEvent.click(btn);
      fireEvent.click(screen.getByTestId('icon-eye-off').closest('button'));
      expect(screen.getByTestId('icon-eye')).toBeInTheDocument();
    });

    it('excludes inactive profiles from table data when hideInactive is true', () => {
      setupMocks({
        profiles: [
          makeProfile({ id: 1, is_active: true }),
          makeProfile({ id: 2, is_active: false }),
        ],
      });
      render(<StreamProfiles />);
      fireEvent.click(screen.getByTestId('icon-eye').closest('button'));
      expect(capturedTableOptions.data).toHaveLength(1);
      expect(capturedTableOptions.data[0].id).toBe(1);
    });

    it('restores all profiles when hideInactive is turned back off', () => {
      setupMocks({
        profiles: [
          makeProfile({ id: 1, is_active: true }),
          makeProfile({ id: 2, is_active: false }),
        ],
      });
      render(<StreamProfiles />);
      fireEvent.click(screen.getByTestId('icon-eye').closest('button'));
      expect(capturedTableOptions.data).toHaveLength(1);
      fireEvent.click(screen.getByTestId('icon-eye-off').closest('button'));
      expect(capturedTableOptions.data).toHaveLength(2);
    });

    it('does not filter already-active profiles when hideInactive is true', () => {
      setupMocks({
        profiles: [
          makeProfile({ id: 1, is_active: true }),
          makeProfile({ id: 2, is_active: true }),
        ],
      });
      render(<StreamProfiles />);
      fireEvent.click(screen.getByTestId('icon-eye').closest('button'));
      expect(capturedTableOptions.data).toHaveLength(2);
    });
  });

  // ── Column cell renderers ──────────────────────────────────────────────────

  describe('Name column', () => {
    it('renders the profile name', () => {
      setupMocks();
      render(<StreamProfiles />);
      const col = getCol('name');
      const { getByText } = render(
        col.cell({ cell: { getValue: () => 'My Encoder' } })
      );
      expect(getByText('My Encoder')).toBeInTheDocument();
    });
  });

  describe('Command column', () => {
    it('renders the command value', () => {
      setupMocks();
      render(<StreamProfiles />);
      const col = getCol('command');
      const { getByText } = render(
        col.cell({ cell: { getValue: () => 'ffmpeg' } })
      );
      expect(getByText('ffmpeg')).toBeInTheDocument();
    });
  });

  describe('Parameters column', () => {
    it('renders the parameters value inside a Tooltip', () => {
      setupMocks();
      render(<StreamProfiles />);
      const col = getCol('parameters');
      const { getByText } = render(
        col.cell({ cell: { getValue: () => '-c copy -f mpegts' } })
      );
      expect(getByText('-c copy -f mpegts')).toBeInTheDocument();
    });
  });

  // ── Store reactivity ───────────────────────────────────────────────────────

  describe('store reactivity', () => {
    it('passes store profiles directly to the table data', () => {
      const profiles = [
        makeProfile({ id: 1, name: 'P1' }),
        makeProfile({ id: 2, name: 'P2' }),
        makeProfile({ id: 3, name: 'P3' }),
      ];
      setupMocks({ profiles });
      render(<StreamProfiles />);
      expect(capturedTableOptions.data).toHaveLength(3);
    });

    it('passes an empty array to the table when no profiles exist', () => {
      setupMocks({ profiles: [] });
      render(<StreamProfiles />);
      expect(capturedTableOptions.data).toHaveLength(0);
    });
  });
});
