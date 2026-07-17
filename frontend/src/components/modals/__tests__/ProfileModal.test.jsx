import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

// ── API mock ───────────────────────────────────────────────────────────────────
vi.mock('../../../api', () => ({
  default: {
    updateChannelProfile: vi.fn(),
    duplicateChannelProfile: vi.fn(),
  },
}));

// ── Notification mock ──────────────────────────────────────────────────────────
vi.mock('../../../utils/notificationUtils', () => ({
  showNotification: vi.fn(),
}));

// ── Store mock ─────────────────────────────────────────────────────────────────
vi.mock('../../../store/channels', () => ({
  default: vi.fn(),
}));

// ── Constants mock ─────────────────────────────────────────────────────────────
vi.mock('../../../constants', () => ({
  USER_LEVELS: { STREAMER: 0, STANDARD: 1, ADMIN: 10 },
}));

// ── lucide-react ───────────────────────────────────────────────────────────────
vi.mock('lucide-react', () => ({
  Copy: () => <svg data-testid="icon-copy" />,
  SquareMinus: () => <svg data-testid="icon-square-minus" />,
  SquarePen: () => <svg data-testid="icon-square-pen" />,
}));

// ── @mantine/core ──────────────────────────────────────────────────────────────
vi.mock('@mantine/core', () => ({
  ActionIcon: ({ children, onClick, disabled }) => (
    <button data-testid="action-icon" onClick={onClick} disabled={disabled}>
      {children}
    </button>
  ),
  Alert: ({ children, title, color }) => (
    <div data-testid="alert" data-color={color}>
      {title && <div data-testid="alert-title">{title}</div>}
      {children}
    </div>
  ),
  Box: ({ children }) => <div>{children}</div>,
  Button: ({ children, onClick, variant, size }) => (
    <button onClick={onClick} data-variant={variant} data-size={size}>
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
  Stack: ({ children }) => <div>{children}</div>,
  Text: ({ children, size }) => <span data-size={size}>{children}</span>,
  TextInput: ({ label, value, onChange, placeholder }) => (
    <div>
      {label && <label>{label}</label>}
      <input
        data-testid="profile-name-input"
        value={value ?? ''}
        onChange={onChange}
        placeholder={placeholder}
      />
    </div>
  ),
  Tooltip: ({ children, label }) => <div data-tooltip={label}>{children}</div>,
}));

// ── Imports after mocks ────────────────────────────────────────────────────────
import ProfileModal, { renderProfileOption } from '../ProfileModal';
import API from '../../../api';
import useChannelsStore from '../../../store/channels';
import { showNotification } from '../../../utils/notificationUtils';

// ── Shared helpers ─────────────────────────────────────────────────────────────
const makeProfile = (overrides = {}) => ({
  id: 1,
  name: 'My Profile',
  ...overrides,
});

const defaultProps = (overrides = {}) => ({
  opened: true,
  onClose: vi.fn(),
  mode: 'edit',
  profile: makeProfile(),
  ...overrides,
});

// ──────────────────────────────────────────────────────────────────────────────

describe('ProfileModal', () => {
  let mockSetSelectedProfileId;

  beforeEach(() => {
    vi.resetAllMocks();
    mockSetSelectedProfileId = vi.fn();
    vi.mocked(useChannelsStore).mockImplementation((sel) =>
      sel({ setSelectedProfileId: mockSetSelectedProfileId })
    );
    vi.mocked(API.updateChannelProfile).mockResolvedValue({
      id: 1,
      name: 'Updated',
    });
    vi.mocked(API.duplicateChannelProfile).mockResolvedValue({
      id: 2,
      name: 'My Profile Copy',
    });
  });

  // ── Visibility ─────────────────────────────────────────────────────────────

  describe('visibility', () => {
    it('renders the modal when opened is true', () => {
      render(<ProfileModal {...defaultProps()} />);
      expect(screen.getByTestId('modal')).toBeInTheDocument();
    });

    it('does not render the modal when opened is false', () => {
      render(<ProfileModal {...defaultProps({ opened: false })} />);
      expect(screen.queryByTestId('modal')).not.toBeInTheDocument();
    });
  });

  // ── Title ──────────────────────────────────────────────────────────────────

  describe('title', () => {
    it('shows "Rename Profile: {name}" title in edit mode', () => {
      render(
        <ProfileModal
          {...defaultProps({
            mode: 'edit',
            profile: makeProfile({ name: 'Work Profile' }),
          })}
        />
      );
      expect(screen.getByTestId('modal-title')).toHaveTextContent(
        'Rename Profile: Work Profile'
      );
    });

    it('shows "Duplicate Profile: {name}" title in duplicate mode', () => {
      render(
        <ProfileModal
          {...defaultProps({
            mode: 'duplicate',
            profile: makeProfile({ name: 'Work Profile' }),
          })}
        />
      );
      expect(screen.getByTestId('modal-title')).toHaveTextContent(
        'Duplicate Profile: Work Profile'
      );
    });
  });

  // ── Warning alert ──────────────────────────────────────────────────────────

  describe('warning alert', () => {
    it('shows the warning alert in edit mode', () => {
      render(<ProfileModal {...defaultProps({ mode: 'edit' })} />);
      expect(screen.getByTestId('alert')).toBeInTheDocument();
    });

    it('does not show the warning alert in duplicate mode', () => {
      render(<ProfileModal {...defaultProps({ mode: 'duplicate' })} />);
      expect(screen.queryByTestId('alert')).not.toBeInTheDocument();
    });
  });

  // ── Initial name value ─────────────────────────────────────────────────────

  describe('initial name value', () => {
    it('pre-fills the input with the profile name in edit mode', () => {
      render(
        <ProfileModal
          {...defaultProps({
            mode: 'edit',
            profile: makeProfile({ name: 'My Profile' }),
          })}
        />
      );
      expect(screen.getByTestId('profile-name-input')).toHaveValue(
        'My Profile'
      );
    });

    it('pre-fills the input with "{name} Copy" in duplicate mode', () => {
      render(
        <ProfileModal
          {...defaultProps({
            mode: 'duplicate',
            profile: makeProfile({ name: 'My Profile' }),
          })}
        />
      );
      expect(screen.getByTestId('profile-name-input')).toHaveValue(
        'My Profile Copy'
      );
    });
  });

  // ── Button labels ──────────────────────────────────────────────────────────

  describe('button labels', () => {
    it('shows "Save" button in edit mode', () => {
      render(<ProfileModal {...defaultProps({ mode: 'edit' })} />);
      expect(screen.getByText('Save')).toBeInTheDocument();
    });

    it('shows "Duplicate" button in duplicate mode', () => {
      render(<ProfileModal {...defaultProps({ mode: 'duplicate' })} />);
      expect(screen.getByText('Duplicate')).toBeInTheDocument();
    });
  });

  // ── Cancel / close ─────────────────────────────────────────────────────────

  describe('cancel / close', () => {
    it('calls onClose when Cancel is clicked', () => {
      const onClose = vi.fn();
      render(<ProfileModal {...defaultProps({ onClose })} />);
      fireEvent.click(screen.getByText('Cancel'));
      expect(onClose).toHaveBeenCalled();
    });

    it('calls onClose when the modal close button is clicked', () => {
      const onClose = vi.fn();
      render(<ProfileModal {...defaultProps({ onClose })} />);
      fireEvent.click(screen.getByTestId('modal-close'));
      expect(onClose).toHaveBeenCalled();
    });
  });

  // ── Submit validation ──────────────────────────────────────────────────────

  describe('submit validation', () => {
    it('shows notification when name is empty', () => {
      render(<ProfileModal {...defaultProps()} />);
      fireEvent.change(screen.getByTestId('profile-name-input'), {
        target: { value: '' },
      });
      fireEvent.click(screen.getByText('Save'));
      expect(showNotification).toHaveBeenCalledWith(
        expect.objectContaining({
          title: 'Profile name is required',
          color: 'red.5',
        })
      );
    });

    it('shows notification when name is only whitespace', () => {
      render(<ProfileModal {...defaultProps()} />);
      fireEvent.change(screen.getByTestId('profile-name-input'), {
        target: { value: '   ' },
      });
      fireEvent.click(screen.getByText('Save'));
      expect(showNotification).toHaveBeenCalledWith(
        expect.objectContaining({ title: 'Profile name is required' })
      );
    });

    it('does not call API when name is empty', () => {
      render(<ProfileModal {...defaultProps()} />);
      fireEvent.change(screen.getByTestId('profile-name-input'), {
        target: { value: '' },
      });
      fireEvent.click(screen.getByText('Save'));
      expect(API.updateChannelProfile).not.toHaveBeenCalled();
    });

    it('returns early without notification or API call when profile is undefined', () => {
      render(<ProfileModal {...defaultProps({ profile: undefined })} />);
      fireEvent.click(screen.getByText('Save'));
      expect(API.updateChannelProfile).not.toHaveBeenCalled();
      expect(showNotification).not.toHaveBeenCalled();
    });
  });

  // ── Edit mode submission ───────────────────────────────────────────────────

  describe('edit mode submission', () => {
    it('closes without calling API when name is unchanged', async () => {
      const onClose = vi.fn();
      render(
        <ProfileModal
          {...defaultProps({
            onClose,
            mode: 'edit',
            profile: makeProfile({ name: 'My Profile' }),
          })}
        />
      );
      fireEvent.click(screen.getByText('Save'));
      await waitFor(() => {
        expect(onClose).toHaveBeenCalled();
      });
      expect(API.updateChannelProfile).not.toHaveBeenCalled();
    });

    it('calls updateChannelProfile with id and new name when name changes', async () => {
      render(
        <ProfileModal
          {...defaultProps({
            mode: 'edit',
            profile: makeProfile({ id: 7, name: 'Old Name' }),
          })}
        />
      );
      fireEvent.change(screen.getByTestId('profile-name-input'), {
        target: { value: 'New Name' },
      });
      fireEvent.click(screen.getByText('Save'));
      await waitFor(() => {
        expect(API.updateChannelProfile).toHaveBeenCalledWith({
          id: 7,
          name: 'New Name',
        });
      });
    });

    it('trims whitespace from the name before submitting', async () => {
      render(
        <ProfileModal
          {...defaultProps({
            mode: 'edit',
            profile: makeProfile({ id: 1, name: 'Old' }),
          })}
        />
      );
      fireEvent.change(screen.getByTestId('profile-name-input'), {
        target: { value: '  Trimmed Name  ' },
      });
      fireEvent.click(screen.getByText('Save'));
      await waitFor(() => {
        expect(API.updateChannelProfile).toHaveBeenCalledWith({
          id: 1,
          name: 'Trimmed Name',
        });
      });
    });

    it('shows "Profile renamed" notification on success', async () => {
      render(
        <ProfileModal
          {...defaultProps({
            mode: 'edit',
            profile: makeProfile({ name: 'Old Name' }),
          })}
        />
      );
      fireEvent.change(screen.getByTestId('profile-name-input'), {
        target: { value: 'New Name' },
      });
      fireEvent.click(screen.getByText('Save'));
      await waitFor(() => {
        expect(showNotification).toHaveBeenCalledWith(
          expect.objectContaining({
            title: 'Profile renamed',
            color: 'green.5',
          })
        );
      });
    });

    it('calls onClose after a successful rename', async () => {
      const onClose = vi.fn();
      render(
        <ProfileModal
          {...defaultProps({
            onClose,
            mode: 'edit',
            profile: makeProfile({ name: 'Old' }),
          })}
        />
      );
      fireEvent.change(screen.getByTestId('profile-name-input'), {
        target: { value: 'New' },
      });
      fireEvent.click(screen.getByText('Save'));
      await waitFor(() => {
        expect(onClose).toHaveBeenCalled();
      });
    });

    it('does not notify or close when updateChannelProfile returns null', async () => {
      vi.mocked(API.updateChannelProfile).mockResolvedValue(null);
      const onClose = vi.fn();
      render(
        <ProfileModal
          {...defaultProps({
            onClose,
            mode: 'edit',
            profile: makeProfile({ name: 'Old' }),
          })}
        />
      );
      fireEvent.change(screen.getByTestId('profile-name-input'), {
        target: { value: 'New' },
      });
      fireEvent.click(screen.getByText('Save'));
      await waitFor(() => {
        expect(API.updateChannelProfile).toHaveBeenCalled();
      });
      expect(showNotification).not.toHaveBeenCalledWith(
        expect.objectContaining({ title: 'Profile renamed' })
      );
      expect(onClose).not.toHaveBeenCalled();
    });
  });

  // ── Duplicate mode submission ──────────────────────────────────────────────

  describe('duplicate mode submission', () => {
    it('calls duplicateChannelProfile with profile id and default copy name', async () => {
      render(
        <ProfileModal
          {...defaultProps({
            mode: 'duplicate',
            profile: makeProfile({ id: 5, name: 'My Profile' }),
          })}
        />
      );
      fireEvent.click(screen.getByText('Duplicate'));
      await waitFor(() => {
        expect(API.duplicateChannelProfile).toHaveBeenCalledWith(
          5,
          'My Profile Copy'
        );
      });
    });

    it('uses the custom name entered by the user', async () => {
      render(
        <ProfileModal
          {...defaultProps({
            mode: 'duplicate',
            profile: makeProfile({ id: 3, name: 'Base' }),
          })}
        />
      );
      fireEvent.change(screen.getByTestId('profile-name-input'), {
        target: { value: 'Custom Copy Name' },
      });
      fireEvent.click(screen.getByText('Duplicate'));
      await waitFor(() => {
        expect(API.duplicateChannelProfile).toHaveBeenCalledWith(
          3,
          'Custom Copy Name'
        );
      });
    });

    it('shows "Profile duplicated" notification on success', async () => {
      render(
        <ProfileModal
          {...defaultProps({ mode: 'duplicate', profile: makeProfile() })}
        />
      );
      fireEvent.click(screen.getByText('Duplicate'));
      await waitFor(() => {
        expect(showNotification).toHaveBeenCalledWith(
          expect.objectContaining({
            title: 'Profile duplicated',
            color: 'green.5',
          })
        );
      });
    });

    it('calls setSelectedProfileId with the string id of the duplicated profile', async () => {
      vi.mocked(API.duplicateChannelProfile).mockResolvedValue({
        id: 99,
        name: 'Copy',
      });
      render(
        <ProfileModal
          {...defaultProps({ mode: 'duplicate', profile: makeProfile() })}
        />
      );
      fireEvent.click(screen.getByText('Duplicate'));
      await waitFor(() => {
        expect(mockSetSelectedProfileId).toHaveBeenCalledWith('99');
      });
    });

    it('calls onClose after a successful duplication', async () => {
      const onClose = vi.fn();
      render(
        <ProfileModal
          {...defaultProps({
            onClose,
            mode: 'duplicate',
            profile: makeProfile(),
          })}
        />
      );
      fireEvent.click(screen.getByText('Duplicate'));
      await waitFor(() => {
        expect(onClose).toHaveBeenCalled();
      });
    });

    it('does not call setSelectedProfileId or close when duplicateChannelProfile returns null', async () => {
      vi.mocked(API.duplicateChannelProfile).mockResolvedValue(null);
      const onClose = vi.fn();
      render(
        <ProfileModal
          {...defaultProps({
            onClose,
            mode: 'duplicate',
            profile: makeProfile(),
          })}
        />
      );
      fireEvent.click(screen.getByText('Duplicate'));
      await waitFor(() => {
        expect(API.duplicateChannelProfile).toHaveBeenCalled();
      });
      expect(mockSetSelectedProfileId).not.toHaveBeenCalled();
      expect(onClose).not.toHaveBeenCalled();
    });
  });
});

// ──────────────────────────────────────────────────────────────────────────────

describe('renderProfileOption', () => {
  const mockTheme = {
    tailwind: {
      yellow: { 3: '#f59e0b' },
      green: { 5: '#22c55e' },
      red: { 6: '#dc2626' },
    },
  };

  const adminUser = { user_level: 10 };
  const nonAdminUser = { user_level: 1 };

  const makeRenderArgs = (overrides = {}) => ({
    theme: mockTheme,
    profiles: [],
    onEditProfile: vi.fn(),
    onDeleteProfile: vi.fn(),
    authUser: adminUser,
    ...overrides,
  });

  const renderOption = (optionValue, optionLabel, args) => {
    const renderFn = renderProfileOption(
      args.theme,
      args.profiles,
      args.onEditProfile,
      args.onDeleteProfile,
      args.authUser
    );
    const { container } = render(
      renderFn({ option: { value: optionValue, label: optionLabel } })
    );
    return container;
  };

  beforeEach(() => {
    vi.clearAllMocks();
  });

  // ── Rendering ──────────────────────────────────────────────────────────────

  describe('rendering', () => {
    it('renders the option label', () => {
      renderOption('1', 'Profile One', makeRenderArgs());
      expect(screen.getByText('Profile One')).toBeInTheDocument();
    });

    it('shows action icons when option value is not "0"', () => {
      renderOption('1', 'Profile One', makeRenderArgs());
      expect(screen.getByTestId('icon-square-pen')).toBeInTheDocument();
      expect(screen.getByTestId('icon-copy')).toBeInTheDocument();
      expect(screen.getByTestId('icon-square-minus')).toBeInTheDocument();
    });

    it('does not show action icons when option value is "0"', () => {
      renderOption('0', 'All Profiles', makeRenderArgs());
      expect(screen.queryByTestId('icon-square-pen')).not.toBeInTheDocument();
      expect(screen.queryByTestId('icon-copy')).not.toBeInTheDocument();
      expect(screen.queryByTestId('icon-square-minus')).not.toBeInTheDocument();
    });
  });

  // ── Rename action ──────────────────────────────────────────────────────────

  describe('rename action', () => {
    it('calls onEditProfile with "edit" and option value when rename is clicked', () => {
      const args = makeRenderArgs();
      renderOption('3', 'Profile Three', args);
      fireEvent.click(screen.getByTestId('icon-square-pen').closest('button'));
      expect(args.onEditProfile).toHaveBeenCalledWith('edit', '3');
    });

    it('rename button is enabled for admin user', () => {
      renderOption('1', 'Profile One', makeRenderArgs({ authUser: adminUser }));
      expect(
        screen.getByTestId('icon-square-pen').closest('button')
      ).not.toBeDisabled();
    });

    it('rename button is disabled for non-admin user', () => {
      renderOption(
        '1',
        'Profile One',
        makeRenderArgs({ authUser: nonAdminUser })
      );
      expect(
        screen.getByTestId('icon-square-pen').closest('button')
      ).toBeDisabled();
    });
  });

  // ── Duplicate action ───────────────────────────────────────────────────────

  describe('duplicate action', () => {
    it('calls onEditProfile with "duplicate" and option value when duplicate is clicked', () => {
      const args = makeRenderArgs();
      renderOption('5', 'Profile Five', args);
      fireEvent.click(screen.getByTestId('icon-copy').closest('button'));
      expect(args.onEditProfile).toHaveBeenCalledWith('duplicate', '5');
    });

    it('duplicate button is enabled for admin user', () => {
      renderOption('1', 'Profile One', makeRenderArgs({ authUser: adminUser }));
      expect(
        screen.getByTestId('icon-copy').closest('button')
      ).not.toBeDisabled();
    });

    it('duplicate button is disabled for non-admin user', () => {
      renderOption(
        '1',
        'Profile One',
        makeRenderArgs({ authUser: nonAdminUser })
      );
      expect(screen.getByTestId('icon-copy').closest('button')).toBeDisabled();
    });
  });

  // ── Delete action ──────────────────────────────────────────────────────────

  describe('delete action', () => {
    it('calls onDeleteProfile with option value when delete is clicked', () => {
      const args = makeRenderArgs();
      renderOption('7', 'Profile Seven', args);
      fireEvent.click(
        screen.getByTestId('icon-square-minus').closest('button')
      );
      expect(args.onDeleteProfile).toHaveBeenCalledWith('7');
    });

    it('delete button is disabled for non-admin user', () => {
      renderOption(
        '1',
        'Profile One',
        makeRenderArgs({ authUser: nonAdminUser })
      );
      expect(
        screen.getByTestId('icon-square-minus').closest('button')
      ).toBeDisabled();
    });
  });

  // ── Event propagation ──────────────────────────────────────────────────────

  describe('event propagation', () => {
    it('does not propagate click event when rename is clicked', () => {
      const args = makeRenderArgs();
      const parentClick = vi.fn();
      const renderFn = renderProfileOption(
        mockTheme,
        [],
        args.onEditProfile,
        args.onDeleteProfile,
        adminUser
      );
      render(
        <div onClick={parentClick}>
          {renderFn({ option: { value: '1', label: 'Profile' } })}
        </div>
      );
      fireEvent.click(screen.getByTestId('icon-square-pen').closest('button'));
      expect(parentClick).not.toHaveBeenCalled();
    });

    it('does not propagate click event when duplicate is clicked', () => {
      const args = makeRenderArgs();
      const parentClick = vi.fn();
      const renderFn = renderProfileOption(
        mockTheme,
        [],
        args.onEditProfile,
        args.onDeleteProfile,
        adminUser
      );
      render(
        <div onClick={parentClick}>
          {renderFn({ option: { value: '1', label: 'Profile' } })}
        </div>
      );
      fireEvent.click(screen.getByTestId('icon-copy').closest('button'));
      expect(parentClick).not.toHaveBeenCalled();
    });

    it('does not propagate click event when delete is clicked', () => {
      const args = makeRenderArgs();
      const parentClick = vi.fn();
      const renderFn = renderProfileOption(
        mockTheme,
        [],
        args.onEditProfile,
        args.onDeleteProfile,
        adminUser
      );
      render(
        <div onClick={parentClick}>
          {renderFn({ option: { value: '1', label: 'Profile' } })}
        </div>
      );
      fireEvent.click(
        screen.getByTestId('icon-square-minus').closest('button')
      );
      expect(parentClick).not.toHaveBeenCalled();
    });
  });
});
