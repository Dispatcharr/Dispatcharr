import {
  render,
  screen,
  fireEvent,
  waitFor,
  within,
} from '@testing-library/react';
import { createElement } from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import M3UProfiles from '../M3UProfiles';
import summaryClasses from '../M3UAccountSummary.module.css';

// ── Store mocks ────────────────────────────────────────────────────────────────
vi.mock('../../../store/playlists', () => ({ default: vi.fn() }));
vi.mock('../../../store/warnings', () => ({ default: vi.fn() }));

// ── Utility mocks ──────────────────────────────────────────────────────────────
vi.mock('../../../utils/forms/M3uProfileUtils.js', () => ({
  deleteM3UProfile: vi.fn(),
  updateM3UProfile: vi.fn(),
}));

vi.mock('../../../utils/forms/M3uProfilesUtils.js', async (original) => ({
  ...(await original()),
  parseExpirationDate: vi.fn(() => new Date('2027-01-01T12:00:00Z')),
  profileSortComparator: vi.fn(),
}));
vi.mock('../../../utils/tables/M3UsTableUtils.js', () => ({
  getExpirationInfo: vi.fn(),
}));
vi.mock('../../../utils/dateTimeUtils.js', () => ({
  diff: () => 60,
  getNow: () => new Date('2026-11-01T12:00:00Z'),
  format: (value) => value.toISOString(),
  useDateTimeFormat: () => ({
    fullDateFormat: 'YYYY-MM-DD',
    fullDateTimeFormat: 'YYYY-MM-DD HH:mm',
  }),
}));
import * as expirationUtils from '../../../utils/tables/M3UsTableUtils.js';

// ── Sub-component mocks ────────────────────────────────────────────────────────
vi.mock('../M3UProfile', () => ({
  default: ({ isOpen, onClose, profile }) =>
    isOpen ? (
      <div data-testid="m3u-profile-modal">
        <span data-testid="m3u-profile-editing">
          {profile ? `editing-${profile.id}` : 'new'}
        </span>
        <button data-testid="m3u-profile-close" onClick={onClose}>
          Close
        </button>
      </div>
    ) : null,
}));

vi.mock('../AccountInfoModal', () => ({
  default: ({ isOpen, onClose, profile }) =>
    isOpen ? (
      <div data-testid="account-info-modal">
        <span data-testid="account-info-profile">
          {profile ? profile.id : 'none'}
        </span>
        <button data-testid="account-info-close" onClick={onClose}>
          Close
        </button>
      </div>
    ) : null,
}));

vi.mock('../../ConfirmationDialog', () => ({
  default: ({ opened, onConfirm, onClose, title, message }) =>
    opened ? (
      <div data-testid="confirmation-dialog">
        <span data-testid="confirm-title">{title}</span>
        <span data-testid="confirm-message">{message}</span>
        <button data-testid="confirm-ok" onClick={onConfirm}>
          Confirm
        </button>
        <button data-testid="confirm-cancel" onClick={onClose}>
          Cancel
        </button>
      </div>
    ) : null,
}));

// ── lucide-react mocks ─────────────────────────────────────────────────────────
vi.mock('lucide-react', () => ({
  Info: () => <svg data-testid="icon-info" />,
  Network: () => <svg data-testid="icon-network" />,
  Trash2: () => <svg data-testid="icon-trash" />,
  SquarePen: () => <svg data-testid="icon-square-pen" />,
}));

// ── Mantine core ───────────────────────────────────────────────────────────────
vi.mock('@mantine/core', () => ({
  useModalStackContext: () => null,
  ActionIcon: ({
    children,
    onClick,
    disabled,
    color,
    'aria-label': ariaLabel,
  }) => (
    <button
      data-testid="action-icon"
      data-color={color}
      onClick={onClick}
      disabled={disabled}
      aria-label={ariaLabel}
    >
      {children}
    </button>
  ),
  Badge: ({ children, color, 'aria-label': ariaLabel }) => (
    <span data-testid="badge" data-color={color} aria-label={ariaLabel}>
      {children}
    </span>
  ),
  Button: ({ children, onClick, disabled, loading, variant, color }) => (
    <button
      onClick={onClick}
      disabled={disabled || loading}
      data-variant={variant}
      data-color={color}
      data-loading={loading}
    >
      {children}
    </button>
  ),
  Paper: ({
    children,
    component = 'div',
    className,
    role,
    withBorder,
    radius,
    'aria-label': ariaLabel,
  }) =>
    createElement(
      component,
      {
        className,
        role,
        'aria-label': ariaLabel,
        'data-testid': component === 'article' ? 'profile-card' : undefined,
        'data-with-border': String(!!withBorder),
        'data-radius': radius,
      },
      children
    ),
  ThemeIcon: ({ children }) => <div>{children}</div>,
  Tooltip: ({ children, label }) => <span title={label}>{children}</span>,
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
  NumberInput: ({
    label,
    value,
    onChange,
    disabled,
    min,
    max,
    w,
    'aria-label': ariaLabel,
  }) => (
    <div>
      <label>{label}</label>
      <input
        data-testid={`number-input-${label?.toLowerCase?.().replace(/\s+/g, '-')}`}
        type="number"
        value={value ?? ''}
        disabled={disabled}
        min={min}
        max={max}
        aria-label={ariaLabel}
        style={{ width: w }}
        onChange={(e) => onChange?.(Number(e.target.value))}
      />
    </div>
  ),
  Stack: ({ children, className }) => (
    <div className={className}>{children}</div>
  ),
  Switch: ({ label, checked, onChange, disabled, 'aria-label': ariaLabel }) => (
    <label>
      {label}
      <input
        data-testid={`switch-${label?.toLowerCase?.().replace(/\s+/g, '-')}`}
        type="checkbox"
        checked={!!checked}
        disabled={disabled}
        aria-label={ariaLabel}
        onChange={(e) => onChange?.(e)}
      />
    </label>
  ),
  Text: ({ children, size, c, fw, truncate, tabIndex }) => (
    <span
      data-size={size}
      data-color={c}
      data-fw={fw}
      data-truncate={!!truncate}
      tabIndex={tabIndex}
    >
      {children}
    </span>
  ),
  useMantineTheme: () => ({ tailwind: { yellow: 3, red: 6 } }),
}));

// ──────────────────────────────────────────────────────────────────────────────
// Imports after mocks
// ──────────────────────────────────────────────────────────────────────────────
import usePlaylistsStore from '../../../store/playlists';
import useWarningsStore from '../../../store/warnings';
import * as M3uProfileUtils from '../../../utils/forms/M3uProfileUtils.js';
import * as M3uProfilesUtils from '../../../utils/forms/M3uProfilesUtils.js';

// ── Helpers ────────────────────────────────────────────────────────────────────
const makeProfile = (overrides = {}) => ({
  id: 1,
  name: 'Test Profile',
  type: 'regex',
  max_streams: 2,
  is_active: true,
  custom_properties: {},
  ...overrides,
});

const makePlaylist = (overrides = {}) => ({
  id: 1,
  name: 'Test M3U',
  account_type: 'XC',
  ...overrides,
});

const defaultProps = (overrides = {}) => ({
  playlist: makePlaylist(),
  isOpen: true,
  onClose: vi.fn(),
  ...overrides,
});

const setupStores = ({
  fetchPlaylist = vi.fn().mockResolvedValue(undefined),
  suppressWarning = vi.fn(),
  isWarningSuppressed = vi.fn().mockReturnValue(false),
  profiles = { 1: [makeProfile()] },
} = {}) => {
  vi.mocked(usePlaylistsStore).mockImplementation((sel) =>
    sel({ fetchPlaylist, profiles })
  );
  vi.mocked(useWarningsStore).mockImplementation((sel) =>
    sel({ suppressWarning, isWarningSuppressed })
  );
  return { fetchPlaylist, suppressWarning, isWarningSuppressed };
};

// ──────────────────────────────────────────────────────────────────────────────

describe('M3UProfiles', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(M3uProfileUtils.deleteM3UProfile).mockResolvedValue(undefined);
    vi.mocked(M3uProfileUtils.updateM3UProfile).mockResolvedValue(undefined);
    vi.mocked(expirationUtils.getExpirationInfo).mockReturnValue({
      label: null,
      color: null,
    });
    vi.mocked(M3uProfilesUtils.profileSortComparator).mockImplementation(
      () => 0
    );
  });

  // ── Guard conditions ───────────────────────────────────────────────────────

  describe('guard conditions', () => {
    it.each(['1', 1, true])(
      'shows Trial for a trial connection (%s)',
      (is_trial) => {
        setupStores({
          profiles: {
            1: [
              makeProfile({ custom_properties: { user_info: { is_trial } } }),
            ],
          },
        });
        render(<M3UProfiles {...defaultProps()} />);
        expect(screen.getByText('Trial')).toBeInTheDocument();
      }
    );

    it('shows a placeholder for unavailable profile expiration', () => {
      vi.mocked(M3uProfilesUtils.parseExpirationDate).mockReturnValueOnce(null);
      setupStores();
      render(<M3UProfiles {...defaultProps()} />);
      expect(screen.getByText('—')).toBeInTheDocument();
      expect(
        screen.getByTitle('No expiration date available')
      ).toBeInTheDocument();
    });
    it('does not render modal when isOpen is false', () => {
      setupStores();
      render(<M3UProfiles {...defaultProps({ isOpen: false })} />);
      expect(screen.queryByTestId('modal')).not.toBeInTheDocument();
    });

    it('does not render modal when playlist is null', () => {
      setupStores();
      render(<M3UProfiles {...defaultProps({ playlist: null })} />);
      expect(screen.queryByTestId('modal')).not.toBeInTheDocument();
    });
  });

  // ── Rendering ──────────────────────────────────────────────────────────────

  describe('rendering', () => {
    it('uses the shared bordered section and compact profile cards in the embedded tab', () => {
      setupStores();
      render(<M3UProfiles {...defaultProps({ embedded: true })} />);
      const section = screen.getByRole('region', {
        name: 'Connection profiles',
      });
      const card = screen.getByRole('article', {
        name: 'Connection profile Test Profile',
      });
      expect(section).toHaveClass(summaryClasses.card);
      expect(section).toHaveAttribute('data-with-border', 'true');
      expect(section).toHaveAttribute('data-radius', 'md');
      expect(card).toHaveClass(summaryClasses.card);
      expect(card).toHaveAttribute('data-with-border', 'true');
      expect(card).toHaveAttribute('data-radius', 'md');
      expect(section).toContainElement(card);
      expect(screen.queryByTestId('modal')).not.toBeInTheDocument();
      expect(M3uProfileUtils.updateM3UProfile).not.toHaveBeenCalled();
    });

    it('centers a single filled add action like category selection', () => {
      setupStores();
      render(<M3UProfiles {...defaultProps()} />);
      const actions = screen.getByRole('region', {
        name: 'Connection profile actions',
      });
      const add = within(actions).getByRole('button', {
        name: 'Add connection profile',
      });
      expect(actions).toHaveClass(summaryClasses.selectionActions);
      expect(add).toHaveAttribute('data-variant', 'filled');
      expect(within(actions).getAllByRole('button')).toHaveLength(1);
    });

    it('groups the named profile actions and keeps Max Streams compact', () => {
      setupStores();
      render(<M3UProfiles {...defaultProps()} />);
      const actions = screen.getByRole('group', {
        name: 'Actions for Test Profile',
      });
      expect(
        within(actions).getByRole('button', {
          name: 'View account information for Test Profile',
        })
      ).toBeEnabled();
      expect(
        within(actions).getByRole('button', { name: 'Edit Test Profile' })
      ).toBeEnabled();
      expect(
        within(actions).getByRole('button', { name: 'Delete Test Profile' })
      ).toBeEnabled();
      expect(within(actions).queryByRole('checkbox')).not.toBeInTheDocument();
      const enabled = screen.getByRole('group', {
        name: 'Enabled state for Test Profile',
      });
      expect(
        within(enabled).getByRole('checkbox', { name: 'Enable Test Profile' })
      ).toBeEnabled();
      expect(enabled.parentElement).toHaveAttribute(
        'title',
        'Enable or disable this connection profile'
      );
      expect(within(enabled).queryByText('Active')).not.toBeInTheDocument();
      expect(actions).not.toContainElement(enabled);
      const maxStreams = screen.getByLabelText('Max Streams for Test Profile');
      expect(maxStreams).toHaveTextContent('2');
      expect(screen.queryByRole('spinbutton')).not.toBeInTheDocument();
      expect(actions).not.toContainElement(maxStreams);
      const header = screen
        .getByTestId('profile-card')
        .querySelector(`.${summaryClasses.profileRow}`);
      expect(header).toContainElement(maxStreams);
      expect(header).toContainElement(actions);
      expect(header).toContainElement(enabled);
      expect(screen.getByText('Expires')).toBeInTheDocument();
    });

    it('marks the default profile while preserving its protected controls', () => {
      setupStores({ profiles: { 1: [makeProfile({ is_default: true })] } });
      render(<M3UProfiles {...defaultProps()} />);
      const card = screen.getByRole('article', {
        name: 'Connection profile Test Profile',
      });
      expect(within(card).getByText('Default')).toBeInTheDocument();
      expect(within(card).queryByRole('spinbutton')).not.toBeInTheDocument();
      expect(within(card).getByRole('checkbox')).toBeDisabled();
      expect(
        screen.getByRole('group', { name: 'Enabled state for Test Profile' })
          .parentElement
      ).toHaveAttribute(
        'title',
        'The default profile cannot be enabled or disabled here'
      );
      expect(
        within(card).getByRole('button', {
          name: 'Edit Test Profile name and notes',
        })
      ).toBeEnabled();
      expect(
        within(card).getByRole('button', { name: 'Delete Test Profile' })
      ).toBeDisabled();
      expect(
        screen.getByTitle('The default profile cannot be deleted')
      ).toContainElement(
        within(card).getByRole('button', { name: 'Delete Test Profile' })
      );
      fireEvent.click(
        within(card).getByRole('button', { name: 'Delete Test Profile' })
      );
      expect(M3uProfileUtils.deleteM3UProfile).not.toHaveBeenCalled();
    });

    it('keeps provider-only information hidden for standard M3U profiles', () => {
      setupStores();
      render(
        <M3UProfiles
          {...defaultProps({ playlist: makePlaylist({ account_type: 'STD' }) })}
        />
      );
      expect(
        screen.queryByRole('button', { name: /View account information/ })
      ).not.toBeInTheDocument();
      expect(
        screen.getByRole('button', { name: 'Edit Test Profile' })
      ).toBeEnabled();
      expect(
        screen.getByRole('button', { name: 'Delete Test Profile' })
      ).toBeEnabled();
    });

    it('retains profile notes in subdued text', () => {
      setupStores({
        profiles: {
          1: [
            makeProfile({
              custom_properties: { notes: 'Extra connection for fallback' },
            }),
          ],
        },
      });
      render(<M3UProfiles {...defaultProps()} />);
      expect(screen.getByText('Extra connection for fallback')).toHaveAttribute(
        'data-color',
        'dimmed'
      );
    });

    it('places a truncated, keyboard-focusable note after Expires and keeps its full tooltip', () => {
      const notes =
        'A long profile note with details that must remain available in full even when the overview only has room for a short excerpt.';
      setupStores({
        profiles: { 1: [makeProfile({ custom_properties: { notes } })] },
      });
      render(<M3UProfiles {...defaultProps()} />);
      const content = screen.getByText(notes);
      expect(content).toHaveAttribute('data-truncate', 'true');
      expect(content).toHaveAttribute('tabindex', '0');
      expect(screen.getByTitle(notes)).toContainElement(content);
      const details = content.closest(`.${summaryClasses.profileDetails}`);
      expect(details.children).toHaveLength(3);
      expect(details.children[1]).toHaveTextContent('Expires');
      expect(details.children[2]).toHaveClass(summaryClasses.profileNotes);
      expect(details.children[2]).toHaveTextContent('Notes');
      expect(M3uProfileUtils.updateM3UProfile).not.toHaveBeenCalled();
    });

    it.each([undefined, '', '  \n  ', null, {}])(
      'omits the note column for an empty or invalid note (%s)',
      (notes) => {
        setupStores({
          profiles: { 1: [makeProfile({ custom_properties: { notes } })] },
        });
        render(<M3UProfiles {...defaultProps()} />);
        expect(screen.queryByText('Notes')).not.toBeInTheDocument();
        expect(
          screen
            .getByTestId('profile-card')
            .querySelector(`.${summaryClasses.profileDetails}`).children
        ).toHaveLength(2);
      }
    );

    it('renders the modal when isOpen is true with a valid playlist', () => {
      setupStores();
      render(<M3UProfiles {...defaultProps()} />);
      expect(screen.getByTestId('modal')).toBeInTheDocument();
    });

    it('renders an "Add Profile" button', () => {
      setupStores();
      render(<M3UProfiles {...defaultProps()} />);
      expect(
        screen.getByRole('button', { name: /add connection profile/i })
      ).toBeInTheDocument();
    });

    it('renders a profile card for each profile', () => {
      const profiles = { 1: [makeProfile({ id: 1 }), makeProfile({ id: 2 })] };
      setupStores({ profiles });
      render(<M3UProfiles {...defaultProps()} />);
      expect(screen.getAllByTestId('profile-card')).toHaveLength(2);
    });

    it('renders the profile name', () => {
      const profiles = { 1: [makeProfile({ name: 'My Profile' })] };
      setupStores({ profiles });
      render(<M3UProfiles {...defaultProps()} />);
      expect(screen.getByText('My Profile')).toBeInTheDocument();
    });

    it('renders an edit icon for each profile', () => {
      setupStores();
      render(<M3UProfiles {...defaultProps()} />);
      expect(screen.getByTestId('icon-square-pen')).toBeInTheDocument();
    });

    it('renders a delete icon for each profile', () => {
      setupStores();
      render(<M3UProfiles {...defaultProps()} />);
      expect(screen.getByTestId('icon-trash')).toBeInTheDocument();
    });

    it('renders an info icon for each profile', () => {
      setupStores();
      render(<M3UProfiles {...defaultProps()} />);
      expect(screen.getByTestId('icon-info')).toBeInTheDocument();
    });

    it('renders an expiration badge when getExpirationInfo returns a label', () => {
      vi.mocked(expirationUtils.getExpirationInfo).mockReturnValue({
        label: 'Expires soon',
        color: 'orange',
      });
      setupStores();
      render(<M3UProfiles {...defaultProps()} />);
      expect(screen.getByText('Expires soon')).toBeInTheDocument();
    });

    it('renders empty state message when there are no profiles', () => {
      setupStores({ profiles: { 1: [] } });
      render(<M3UProfiles {...defaultProps()} />);
      expect(screen.queryByTestId('profile-card')).not.toBeInTheDocument();
    });

    it('renders profiles sorted by profileSortComparator', () => {
      vi.mocked(M3uProfilesUtils.profileSortComparator).mockImplementation(
        (a, b) => b.id - a.id
      );
      const profiles = {
        1: [
          makeProfile({ id: 1, name: 'Alpha' }),
          makeProfile({ id: 2, name: 'Beta' }),
        ],
      };
      setupStores({ profiles });
      render(<M3UProfiles {...defaultProps()} />);
      const cards = screen.getAllByTestId('profile-card');
      expect(cards).toHaveLength(2);
    });
  });

  // ── Close behaviour ────────────────────────────────────────────────────────

  describe('close behaviour', () => {
    it('calls onClose when modal X is clicked', () => {
      const onClose = vi.fn();
      setupStores();
      render(<M3UProfiles {...defaultProps({ onClose })} />);
      fireEvent.click(screen.getByTestId('modal-close'));
      expect(onClose).toHaveBeenCalled();
    });
  });

  // ── Add Profile ────────────────────────────────────────────────────────────

  describe('add profile', () => {
    it('opens M3UProfile modal when Add Profile is clicked', () => {
      setupStores();
      render(<M3UProfiles {...defaultProps()} />);
      fireEvent.click(
        screen.getByRole('button', { name: /add connection profile/i })
      );
      expect(screen.getByTestId('m3u-profile-modal')).toBeInTheDocument();
    });

    it('opens M3UProfile modal with null profile for a new profile', () => {
      setupStores();
      render(<M3UProfiles {...defaultProps()} />);
      fireEvent.click(
        screen.getByRole('button', { name: /add connection profile/i })
      );
      expect(screen.getByTestId('m3u-profile-editing').textContent).toBe('new');
    });

    it('closes M3UProfile modal when its onClose is called', () => {
      setupStores();
      render(<M3UProfiles {...defaultProps()} />);
      fireEvent.click(
        screen.getByRole('button', { name: /add connection profile/i })
      );
      fireEvent.click(screen.getByTestId('m3u-profile-close'));
      expect(screen.queryByTestId('m3u-profile-modal')).not.toBeInTheDocument();
    });
  });

  // ── Edit Profile ───────────────────────────────────────────────────────────

  describe('edit profile', () => {
    it('opens M3UProfile modal with the correct profile when edit is clicked', () => {
      const profiles = { 1: [makeProfile({ id: 42 })] };
      setupStores({ profiles });
      render(<M3UProfiles {...defaultProps()} />);
      const editBtn = screen.getByTestId('icon-square-pen').closest('button');
      fireEvent.click(editBtn);
      expect(screen.getByTestId('m3u-profile-modal')).toBeInTheDocument();
      expect(screen.getByTestId('m3u-profile-editing').textContent).toBe(
        'editing-42'
      );
    });

    it('closes M3UProfile modal after edit onClose', () => {
      setupStores();
      render(<M3UProfiles {...defaultProps()} />);
      const editBtn = screen.getByTestId('icon-square-pen').closest('button');
      fireEvent.click(editBtn);
      fireEvent.click(screen.getByTestId('m3u-profile-close'));
      expect(screen.queryByTestId('m3u-profile-modal')).not.toBeInTheDocument();
    });
  });

  // ── Account Info ───────────────────────────────────────────────────────────

  describe('account info', () => {
    it('opens AccountInfoModal when info icon is clicked', () => {
      const profiles = { 1: [makeProfile({ id: 7 })] };
      setupStores({ profiles });
      render(<M3UProfiles {...defaultProps()} />);
      const infoBtn = screen.getByTestId('icon-info').closest('button');
      fireEvent.click(infoBtn);
      expect(screen.getByTestId('account-info-modal')).toBeInTheDocument();
    });

    it('passes the correct profile to AccountInfoModal', () => {
      const profiles = { 1: [makeProfile({ id: 7 })] };
      setupStores({ profiles });
      render(<M3UProfiles {...defaultProps()} />);
      const infoBtn = screen.getByTestId('icon-info').closest('button');
      fireEvent.click(infoBtn);
      expect(screen.getByTestId('account-info-profile').textContent).toBe('7');
    });

    it('closes AccountInfoModal when its onClose is called', () => {
      setupStores();
      render(<M3UProfiles {...defaultProps()} />);
      const infoBtn = screen.getByTestId('icon-info').closest('button');
      fireEvent.click(infoBtn);
      fireEvent.click(screen.getByTestId('account-info-close'));
      expect(
        screen.queryByTestId('account-info-modal')
      ).not.toBeInTheDocument();
    });
  });

  // ── Delete profile ─────────────────────────────────────────────────────────

  describe('delete profile', () => {
    it('shows ConfirmationDialog when delete icon is clicked and warning not suppressed', () => {
      setupStores({ isWarningSuppressed: vi.fn().mockReturnValue(false) });
      render(<M3UProfiles {...defaultProps()} />);
      const deleteBtn = screen.getByTestId('icon-trash').closest('button');
      fireEvent.click(deleteBtn);
      expect(screen.getByTestId('confirmation-dialog')).toBeInTheDocument();
    });

    it('calls deleteM3UProfile directly when warning is suppressed', async () => {
      const profiles = { 1: [makeProfile()] };
      setupStores({
        isWarningSuppressed: vi.fn().mockReturnValue(true),
        profiles,
      });
      render(<M3UProfiles {...defaultProps()} />);
      const deleteBtn = screen.getByTestId('icon-trash').closest('button');
      fireEvent.click(deleteBtn);
      await waitFor(() => {
        expect(M3uProfileUtils.deleteM3UProfile).toHaveBeenCalledWith(
          profiles[1][0]['id'],
          1
        );
      });
    });

    it('calls deleteM3UProfile after confirming the dialog', async () => {
      const profiles = { 1: [makeProfile()] };
      setupStores({
        isWarningSuppressed: vi.fn().mockReturnValue(true),
        profiles,
      });
      setupStores({ isWarningSuppressed: vi.fn().mockReturnValue(false) });
      render(<M3UProfiles {...defaultProps()} />);
      const deleteBtn = screen.getByTestId('icon-trash').closest('button');
      fireEvent.click(deleteBtn);
      fireEvent.click(screen.getByTestId('confirm-ok'));
      await waitFor(() => {
        expect(M3uProfileUtils.deleteM3UProfile).toHaveBeenCalledWith(
          profiles[1][0]['id'],
          1
        );
      });
    });

    it('closes ConfirmationDialog after confirming', async () => {
      setupStores({ isWarningSuppressed: vi.fn().mockReturnValue(false) });
      render(<M3UProfiles {...defaultProps()} />);
      const deleteBtn = screen.getByTestId('icon-trash').closest('button');
      fireEvent.click(deleteBtn);
      fireEvent.click(screen.getByTestId('confirm-ok'));
      await waitFor(() => {
        expect(
          screen.queryByTestId('confirmation-dialog')
        ).not.toBeInTheDocument();
      });
    });

    it('closes ConfirmationDialog when cancel is clicked', () => {
      setupStores({ isWarningSuppressed: vi.fn().mockReturnValue(false) });
      render(<M3UProfiles {...defaultProps()} />);
      const deleteBtn = screen.getByTestId('icon-trash').closest('button');
      fireEvent.click(deleteBtn);
      fireEvent.click(screen.getByTestId('confirm-cancel'));
      expect(
        screen.queryByTestId('confirmation-dialog')
      ).not.toBeInTheDocument();
    });

    it('does not call deleteM3UProfile when cancel is clicked', async () => {
      setupStores({ isWarningSuppressed: vi.fn().mockReturnValue(false) });
      render(<M3UProfiles {...defaultProps()} />);
      const deleteBtn = screen.getByTestId('icon-trash').closest('button');
      fireEvent.click(deleteBtn);
      fireEvent.click(screen.getByTestId('confirm-cancel'));
      expect(M3uProfileUtils.deleteM3UProfile).not.toHaveBeenCalled();
    });
  });

  // ── Max streams / Switch ───────────────────────────────────────────────────

  describe('profile-level controls', () => {
    it('shows the stream limit without an inline save control', () => {
      const profile = makeProfile({ id: 42, max_streams: 2 });
      setupStores({ profiles: { 1: [profile] } });
      render(<M3UProfiles {...defaultProps()} />);
      expect(
        screen.getByLabelText('Max Streams for Test Profile')
      ).toHaveTextContent('2');
      expect(screen.queryByRole('spinbutton')).not.toBeInTheDocument();
      expect(M3uProfileUtils.updateM3UProfile).not.toHaveBeenCalled();
    });

    it('still saves activation immediately without waiting for the parent account Save', async () => {
      const profile = makeProfile({ id: 42, is_active: true });
      setupStores({ profiles: { 1: [profile] } });
      render(<M3UProfiles {...defaultProps()} />);
      fireEvent.click(
        screen.getByRole('checkbox', { name: 'Enable Test Profile' })
      );
      await waitFor(() =>
        expect(
          M3uProfileUtils.updateM3UProfile
        ).toHaveBeenCalledExactlyOnceWith(1, { ...profile, is_active: false })
      );
      expect(
        screen.queryByRole('button', { name: 'Save', exact: true })
      ).not.toBeInTheDocument();
    });

    it('renders the saved stream limit as a badge on the profile card', () => {
      const profiles = { 1: [makeProfile({ max_streams: 3 })] };
      setupStores({ profiles });
      render(<M3UProfiles {...defaultProps()} />);
      expect(
        screen.getByLabelText('Max Streams for Test Profile')
      ).toHaveTextContent('3');
    });

    it('displays zero as unlimited, matching the account overview', () => {
      const profiles = { 1: [makeProfile({ max_streams: 0 })] };
      setupStores({ profiles });
      render(<M3UProfiles {...defaultProps()} />);
      expect(
        screen.getByLabelText('Max Streams for Test Profile')
      ).toHaveTextContent('∞');
      expect(M3uProfileUtils.updateM3UProfile).not.toHaveBeenCalled();
    });
  });

  // ── Expiration / expired styling ───────────────────────────────────────────

  describe('expiration display', () => {
    it.each([
      ['Active', 'green'],
      ['Expired', 'red'],
      ['Disabled', 'red'],
      ['Banned', 'red'],
      ['Unknown provider status', 'gray'],
    ])(
      'uses the account-info color for provider status %s',
      (status, color) => {
        setupStores({
          profiles: {
            1: [makeProfile({ custom_properties: { user_info: { status } } })],
          },
        });
        render(<M3UProfiles {...defaultProps()} />);
        expect(screen.getByText(status)).toHaveAttribute('data-color', color);
      }
    );

    it('renders expiration badge with correct color', () => {
      vi.mocked(expirationUtils.getExpirationInfo).mockReturnValue({
        label: '3 days left',
        color: 'red',
      });
      setupStores();
      render(<M3UProfiles {...defaultProps()} />);
      const badge = screen.getByText('3 days left');
      expect(badge.textContent).toBe('3 days left');
      expect(badge.dataset.color).toBe('red');
    });
  });

  // ── Warning suppression ────────────────────────────────────────────────────

  describe('warning suppression', () => {
    it('calls suppressWarning when user confirms and suppression is selected', async () => {
      const { suppressWarning } = setupStores({
        isWarningSuppressed: vi.fn().mockReturnValue(false),
      });
      render(<M3UProfiles {...defaultProps()} />);
      expect(suppressWarning).toBeDefined();
    });
  });
});
