import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

// ── Constants ──────────────────────────────────────────────────────────────────
vi.mock('../../../constants', () => ({
  USER_LEVELS: { ADMIN: 1, STREAMER: 2, USER: 3 },
  USER_LEVEL_LABELS: { 1: 'Admin', 2: 'Streamer', 3: 'User' },
}));

// ── Store mocks ────────────────────────────────────────────────────────────────
vi.mock('../../../store/channels', () => ({ default: vi.fn() }));
vi.mock('../../../store/outputProfiles', () => ({ default: vi.fn() }));
vi.mock('../../../store/auth', () => ({ default: vi.fn() }));

// ── Utility mocks ──────────────────────────────────────────────────────────────
vi.mock('../../../utils', () => ({ copyToClipboard: vi.fn() }));

vi.mock('../../../utils/forms/UserUtils.js', () => ({
  createUser: vi.fn(),
  updateUser: vi.fn(),
  generateApiKey: vi.fn(),
  revokeApiKey: vi.fn(),
  formValuesToPayload: vi.fn(),
  getFormInitialValues: vi.fn(() => ({})),
  getFormValidators: vi.fn(() => ({})),
  userToFormValues: vi.fn(() => ({})),
}));

// ── Mantine form ───────────────────────────────────────────────────────────────
const mockForm = {
  getInputProps: vi.fn(() => ({})),
  key: vi.fn((k) => k),
  setValues: vi.fn(),
  setFieldValue: vi.fn(),
  reset: vi.fn(),
  getValues: vi.fn(() => ({ user_level: '3' })),
  onSubmit: vi.fn((fn) => (e) => {
    e?.preventDefault?.();
    return fn();
  }),
  submitting: false,
};

vi.mock('@mantine/form', () => ({
  useForm: vi.fn(() => mockForm),
}));

// ── lucide-react ───────────────────────────────────────────────────────────────
vi.mock('lucide-react', () => ({
  Copy: () => <svg data-testid="icon-copy" />,
  Key: () => <svg data-testid="icon-key" />,
  RotateCcwKey: () => <svg data-testid="icon-rotate-ccw-key" />,
  X: () => <svg data-testid="icon-x" />,
}));

// ── Mantine core ───────────────────────────────────────────────────────────────
vi.mock('@mantine/core', () => ({
  ActionIcon: ({ children, onClick, disabled }) => (
    <button data-testid="action-icon" onClick={onClick} disabled={disabled}>
      {children}
    </button>
  ),
  Button: ({ children, onClick, disabled, loading, type, leftSection }) => (
    <button
      type={type || 'button'}
      onClick={onClick}
      disabled={disabled || loading}
      data-loading={String(loading)}
    >
      {leftSection}
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
  MultiSelect: ({ label, onChange }) => (
    <div>
      <label>{label}</label>
      <input
        data-testid={`multiselect-${label}`}
        onChange={(e) =>
          onChange?.(e.target.value ? e.target.value.split(',') : [])
        }
      />
    </div>
  ),
  NumberInput: ({ label }) => (
    <div>
      <label>{label}</label>
      <input />
    </div>
  ),
  PasswordInput: ({ label, disabled }) => (
    <div>
      <label>{label}</label>
      <input type="password" disabled={disabled} />
    </div>
  ),
  Select: ({ label, disabled }) => (
    <div>
      <label>{label}</label>
      <select disabled={disabled} />
    </div>
  ),
  Stack: ({ children }) => <div>{children}</div>,
  Switch: ({ label }) => (
    <div>
      <label>{label}</label>
      <input type="checkbox" />
    </div>
  ),
  Tabs: ({ children }) => <div>{children}</div>,
  TabsList: ({ children }) => <div>{children}</div>,
  TabsPanel: ({ children, value }) => (
    <div data-testid={`panel-${value}`}>{children}</div>
  ),
  TabsTab: ({ children, value }) => (
    <button data-testid={`tab-${value}`}>{children}</button>
  ),
  TagsInput: ({ label }) => (
    <div>
      <label>{label}</label>
      <input />
    </div>
  ),
  Text: ({ children }) => <span>{children}</span>,
  TextInput: ({ label, value, disabled, rightSection }) => (
    <div>
      <label>{label}</label>
      <input
        data-testid={`textinput-${label}`}
        defaultValue={value}
        disabled={disabled}
      />
      {rightSection}
    </div>
  ),
  useMantineTheme: () => ({
    colors: { red: Array(10).fill('#ff0000') },
  }),
}));

// ── Imports after mocks ────────────────────────────────────────────────────────
import useChannelsStore from '../../../store/channels';
import useOutputProfilesStore from '../../../store/outputProfiles';
import useAuthStore from '../../../store/auth';
import * as UserUtils from '../../../utils/forms/UserUtils.js';
import { copyToClipboard } from '../../../utils';
import User from '../User';

// ── Factories ──────────────────────────────────────────────────────────────────
const makeAdminUser = (overrides = {}) => ({
  id: 1,
  username: 'admin',
  user_level: 1,
  api_key: null,
  ...overrides,
});

const makeRegularUser = (overrides = {}) => ({
  id: 2,
  username: 'user1',
  user_level: 3,
  api_key: null,
  ...overrides,
});

const setupMocks = ({
  authUser = makeAdminUser(),
  profiles = {},
  outputProfiles = [],
} = {}) => {
  const mockSetUser = vi.fn();

  vi.mocked(useChannelsStore).mockImplementation((sel) => sel({ profiles }));
  vi.mocked(useOutputProfilesStore).mockImplementation((sel) =>
    sel({ profiles: outputProfiles })
  );
  vi.mocked(useAuthStore).mockImplementation((sel) =>
    sel({ user: authUser, setUser: mockSetUser })
  );

  // Reset form state
  mockForm.getValues.mockReturnValue({ user_level: '3' });
  mockForm.onSubmit.mockImplementation((fn) => (e) => {
    e?.preventDefault?.();
    return fn();
  });

  return { mockSetUser };
};

// ──────────────────────────────────────────────────────────────────────────────

describe('User', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(UserUtils.createUser).mockResolvedValue({});
    vi.mocked(UserUtils.updateUser).mockResolvedValue({});
    vi.mocked(UserUtils.generateApiKey).mockResolvedValue({
      key: 'new-api-key',
    });
    vi.mocked(UserUtils.revokeApiKey).mockResolvedValue({ success: true });
    vi.mocked(UserUtils.formValuesToPayload).mockReturnValue({ user_level: 3 });
    vi.mocked(UserUtils.getFormInitialValues).mockReturnValue({});
    vi.mocked(UserUtils.getFormValidators).mockReturnValue({});
    vi.mocked(UserUtils.userToFormValues).mockReturnValue({});
  });

  // ── Visibility ───────────────────────────────────────────────────────────────

  describe('visibility', () => {
    it('renders nothing when isOpen is false', () => {
      setupMocks();
      render(<User isOpen={false} onClose={vi.fn()} />);
      expect(screen.queryByTestId('modal')).not.toBeInTheDocument();
    });

    it('renders the modal when isOpen is true', () => {
      setupMocks();
      render(<User isOpen={true} onClose={vi.fn()} />);
      expect(screen.getByTestId('modal')).toBeInTheDocument();
    });

    it('calls onClose when the modal close button is clicked', () => {
      setupMocks();
      const onClose = vi.fn();
      render(<User isOpen={true} onClose={onClose} />);
      fireEvent.click(screen.getByTestId('modal-close'));
      expect(onClose).toHaveBeenCalled();
    });
  });

  // ── Tabs ─────────────────────────────────────────────────────────────────────

  describe('tabs', () => {
    it('always renders Account, EPG, and API tabs', () => {
      setupMocks();
      render(<User isOpen={true} onClose={vi.fn()} />);
      expect(screen.getByTestId('tab-account')).toBeInTheDocument();
      expect(screen.getByTestId('tab-epg')).toBeInTheDocument();
      expect(screen.getByTestId('tab-api')).toBeInTheDocument();
    });

    it('shows Permissions tab when admin edits another user', () => {
      setupMocks({ authUser: makeAdminUser() });
      render(<User isOpen={true} onClose={vi.fn()} user={makeRegularUser()} />);
      expect(screen.getByTestId('tab-permissions')).toBeInTheDocument();
    });

    it('hides Permissions tab when admin edits themselves', () => {
      const admin = makeAdminUser();
      setupMocks({ authUser: admin });
      render(<User isOpen={true} onClose={vi.fn()} user={admin} />);
      expect(screen.queryByTestId('tab-permissions')).not.toBeInTheDocument();
    });

    it('hides Permissions tab for non-admin user', () => {
      setupMocks({ authUser: makeRegularUser() });
      render(
        <User
          isOpen={true}
          onClose={vi.fn()}
          user={makeRegularUser({ id: 99 })}
        />
      );
      expect(screen.queryByTestId('tab-permissions')).not.toBeInTheDocument();
    });
  });

  // ── Admin-only fields ────────────────────────────────────────────────────────

  describe('admin-only fields', () => {
    it('shows Output Format Override for admin', () => {
      setupMocks({ authUser: makeAdminUser() });
      render(
        <User
          isOpen={true}
          onClose={vi.fn()}
          user={makeRegularUser({ id: 2 })}
        />
      );
      expect(screen.getByText('Output Format Override')).toBeInTheDocument();
    });

    it('hides Output Format Override for non-admin', () => {
      setupMocks({ authUser: makeRegularUser() });
      render(
        <User
          isOpen={true}
          onClose={vi.fn()}
          user={makeRegularUser({ id: 5 })}
        />
      );
      expect(
        screen.queryByText('Output Format Override')
      ).not.toBeInTheDocument();
    });

    it('shows Output Profile Override for admin', () => {
      setupMocks({ authUser: makeAdminUser() });
      render(
        <User
          isOpen={true}
          onClose={vi.fn()}
          user={makeRegularUser({ id: 2 })}
        />
      );
      expect(screen.getByText('Output Profile Override')).toBeInTheDocument();
    });

    it('shows Allowed IPs for admin', () => {
      setupMocks({ authUser: makeAdminUser() });
      render(
        <User
          isOpen={true}
          onClose={vi.fn()}
          user={makeRegularUser({ id: 2 })}
        />
      );
      expect(screen.getByText('Allowed IPs')).toBeInTheDocument();
    });

    it('hides Allowed IPs for non-admin', () => {
      setupMocks({ authUser: makeRegularUser() });
      render(
        <User
          isOpen={true}
          onClose={vi.fn()}
          user={makeRegularUser({ id: 5 })}
        />
      );
      expect(screen.queryByText('Allowed IPs')).not.toBeInTheDocument();
    });
  });

  // ── API key generation ────────────────────────────────────────────────────────

  describe('API key generation', () => {
    it('shows "Generate API Key" when no key exists', () => {
      setupMocks({ authUser: makeAdminUser() });
      render(
        <User
          isOpen={true}
          onClose={vi.fn()}
          user={makeRegularUser({ id: 2 })}
        />
      );
      expect(screen.getByText('Generate API Key')).toBeInTheDocument();
    });

    it('shows "Regenerate API Key" when user already has an api_key', () => {
      setupMocks({ authUser: makeAdminUser() });
      render(
        <User
          isOpen={true}
          onClose={vi.fn()}
          user={makeRegularUser({ id: 2, api_key: 'existing-key' })}
        />
      );
      expect(screen.getByText('Regenerate API Key')).toBeInTheDocument();
    });

    it('calls generateApiKey and switches button to "Regenerate API Key"', async () => {
      setupMocks({ authUser: makeAdminUser() });
      vi.mocked(UserUtils.generateApiKey).mockResolvedValue({
        key: 'brand-new-key',
      });

      render(
        <User
          isOpen={true}
          onClose={vi.fn()}
          user={makeRegularUser({ id: 2 })}
        />
      );

      expect(screen.getByText('Generate API Key')).toBeInTheDocument();
      fireEvent.click(screen.getByText('Generate API Key'));

      await waitFor(() => {
        expect(UserUtils.generateApiKey).toHaveBeenCalledWith({ user_id: 2 });
        expect(screen.getByText('Regenerate API Key')).toBeInTheDocument();
      });
    });

    it('also sets the key when response contains raw_key instead of key', async () => {
      setupMocks({ authUser: makeAdminUser() });
      vi.mocked(UserUtils.generateApiKey).mockResolvedValue({
        raw_key: 'raw-value',
      });

      render(
        <User
          isOpen={true}
          onClose={vi.fn()}
          user={makeRegularUser({ id: 2 })}
        />
      );

      fireEvent.click(screen.getByText('Generate API Key'));

      await waitFor(() => {
        expect(screen.getByText('Regenerate API Key')).toBeInTheDocument();
      });
    });

    it('does not call generateApiKey when canGenerateKey is false', async () => {
      // non-admin editing someone else
      setupMocks({ authUser: makeRegularUser({ id: 5 }) });
      render(
        <User
          isOpen={true}
          onClose={vi.fn()}
          user={makeRegularUser({ id: 2 })}
        />
      );
      // No button visible since canGenerateKey is false
      expect(screen.queryByText('Generate API Key')).not.toBeInTheDocument();
      expect(UserUtils.generateApiKey).not.toHaveBeenCalled();
    });

    it('does not update key when generateApiKey returns a response without key/raw_key', async () => {
      setupMocks({ authUser: makeAdminUser() });
      vi.mocked(UserUtils.generateApiKey).mockResolvedValue({});

      render(
        <User
          isOpen={true}
          onClose={vi.fn()}
          user={makeRegularUser({ id: 2 })}
        />
      );

      fireEvent.click(screen.getByText('Generate API Key'));

      await waitFor(() => {
        // button text should NOT change since no key was received
        expect(screen.getByText('Generate API Key')).toBeInTheDocument();
      });
    });

    it('shows the generated API key in a text input', async () => {
      setupMocks({ authUser: makeAdminUser() });
      vi.mocked(UserUtils.generateApiKey).mockResolvedValue({ key: 'show-me' });

      render(
        <User
          isOpen={true}
          onClose={vi.fn()}
          user={makeRegularUser({ id: 2 })}
        />
      );

      fireEvent.click(screen.getByText('Generate API Key'));

      await waitFor(() => {
        const keyInput = screen.getByTestId('textinput-API Key');
        expect(keyInput).toHaveValue('show-me');
      });
    });
  });

  // ── API key revocation ───────────────────────────────────────────────────────

  describe('API key revocation', () => {
    it('shows "Revoke API Key" when a key exists', () => {
      setupMocks({ authUser: makeAdminUser() });
      render(
        <User
          isOpen={true}
          onClose={vi.fn()}
          user={makeRegularUser({ id: 2, api_key: 'some-key' })}
        />
      );
      expect(screen.getByText('Revoke API Key')).toBeInTheDocument();
    });

    it('hides "Revoke API Key" when no key exists', () => {
      setupMocks({ authUser: makeAdminUser() });
      render(
        <User
          isOpen={true}
          onClose={vi.fn()}
          user={makeRegularUser({ id: 2 })}
        />
      );
      expect(screen.queryByText('Revoke API Key')).not.toBeInTheDocument();
    });

    it('calls revokeApiKey with user_id and clears the key on success', async () => {
      setupMocks({ authUser: makeAdminUser() });

      render(
        <User
          isOpen={true}
          onClose={vi.fn()}
          user={makeRegularUser({ id: 2, api_key: 'some-key' })}
        />
      );

      fireEvent.click(screen.getByText('Revoke API Key'));

      await waitFor(() => {
        expect(UserUtils.revokeApiKey).toHaveBeenCalledWith({ user_id: 2 });
        expect(screen.queryByText('Revoke API Key')).not.toBeInTheDocument();
        expect(screen.getByText('Generate API Key')).toBeInTheDocument();
      });
    });

    it('updates auth store when admin revokes their own key', async () => {
      const admin = makeAdminUser({ id: 1, api_key: 'my-key' });
      const { mockSetUser } = setupMocks({ authUser: admin });

      render(<User isOpen={true} onClose={vi.fn()} user={admin} />);
      fireEvent.click(screen.getByText('Revoke API Key'));

      await waitFor(() => {
        expect(mockSetUser).toHaveBeenCalledWith(
          expect.objectContaining({ api_key: null })
        );
      });
    });

    it('does not clear key when revokeApiKey returns success: false', async () => {
      setupMocks({ authUser: makeAdminUser() });
      vi.mocked(UserUtils.revokeApiKey).mockResolvedValue({ success: false });

      render(
        <User
          isOpen={true}
          onClose={vi.fn()}
          user={makeRegularUser({ id: 2, api_key: 'still-here' })}
        />
      );

      fireEvent.click(screen.getByText('Revoke API Key'));

      await waitFor(() => {
        expect(screen.getByText('Revoke API Key')).toBeInTheDocument();
      });
    });

    it("does not update auth store when revoking another user's key", async () => {
      const admin = makeAdminUser({ id: 1 });
      const { mockSetUser } = setupMocks({ authUser: admin });

      render(
        <User
          isOpen={true}
          onClose={vi.fn()}
          user={makeRegularUser({ id: 2, api_key: 'other-key' })}
        />
      );

      fireEvent.click(screen.getByText('Revoke API Key'));

      await waitFor(() => {
        expect(mockSetUser).not.toHaveBeenCalled();
      });
    });
  });

  // ── Copy to clipboard ────────────────────────────────────────────────────────

  describe('copy API key to clipboard', () => {
    it('calls copyToClipboard with the current key', () => {
      setupMocks({ authUser: makeAdminUser() });
      render(
        <User
          isOpen={true}
          onClose={vi.fn()}
          user={makeRegularUser({ id: 2, api_key: 'copy-me' })}
        />
      );

      const copyButton = screen.getByTestId('icon-copy').closest('button');
      fireEvent.click(copyButton);

      expect(copyToClipboard).toHaveBeenCalledWith(
        'copy-me',
        expect.objectContaining({ successTitle: 'API Key Copied!' })
      );
    });
  });

  // ── Form submission ──────────────────────────────────────────────────────────

  describe('form submission', () => {
    it('calls createUser when no user prop is given', async () => {
      setupMocks({ authUser: makeAdminUser() });

      render(<User isOpen={true} onClose={vi.fn()} />);
      fireEvent.click(screen.getByText('Save'));

      await waitFor(() => {
        expect(UserUtils.createUser).toHaveBeenCalled();
      });
    });

    it('calls updateUser when editing an existing user', async () => {
      const admin = makeAdminUser();
      setupMocks({ authUser: admin });
      vi.mocked(UserUtils.updateUser).mockResolvedValue({ id: 2 });

      render(
        <User
          isOpen={true}
          onClose={vi.fn()}
          user={makeRegularUser({ id: 2 })}
        />
      );
      fireEvent.click(screen.getByText('Save'));

      await waitFor(() => {
        expect(UserUtils.updateUser).toHaveBeenCalledWith(
          2,
          expect.any(Object),
          true, // isAdmin
          admin
        );
      });
    });

    it('updates auth store when admin saves their own profile', async () => {
      const admin = makeAdminUser({ id: 1 });
      const updatedAdmin = { ...admin, email: 'new@example.com' };
      const { mockSetUser } = setupMocks({ authUser: admin });
      vi.mocked(UserUtils.updateUser).mockResolvedValue(updatedAdmin);

      render(<User isOpen={true} onClose={vi.fn()} user={admin} />);
      fireEvent.click(screen.getByText('Save'));

      await waitFor(() => {
        expect(mockSetUser).toHaveBeenCalledWith(updatedAdmin);
      });
    });

    it('resets form and calls onClose after successful submission', async () => {
      setupMocks({ authUser: makeAdminUser() });
      const onClose = vi.fn();

      render(<User isOpen={true} onClose={onClose} />);
      fireEvent.click(screen.getByText('Save'));

      await waitFor(() => {
        expect(mockForm.reset).toHaveBeenCalled();
        expect(onClose).toHaveBeenCalled();
      });
    });

    it('removes password from payload when updating and payload.password is falsy', async () => {
      const admin = makeAdminUser();
      setupMocks({ authUser: admin });
      vi.mocked(UserUtils.formValuesToPayload).mockReturnValue({
        user_level: 3,
        password: '',
      });
      vi.mocked(UserUtils.updateUser).mockResolvedValue({ id: 2 });

      render(
        <User
          isOpen={true}
          onClose={vi.fn()}
          user={makeRegularUser({ id: 2 })}
        />
      );
      fireEvent.click(screen.getByText('Save'));

      await waitFor(() => {
        const payload = vi.mocked(UserUtils.updateUser).mock.calls[0][1];
        expect(payload).not.toHaveProperty('password');
      });
    });
  });

  // ── useEffect ────────────────────────────────────────────────────────────────

  describe('useEffect on user prop', () => {
    it('calls userToFormValues and sets form values when user has an id', () => {
      const user = makeRegularUser({ id: 2 });
      vi.mocked(UserUtils.userToFormValues).mockReturnValue({
        username: 'user1',
      });
      setupMocks({ authUser: makeAdminUser() });

      render(<User isOpen={true} onClose={vi.fn()} user={user} />);

      expect(UserUtils.userToFormValues).toHaveBeenCalledWith(user);
      expect(mockForm.setValues).toHaveBeenCalledWith({ username: 'user1' });
    });

    it('resets form when no user is provided', () => {
      setupMocks({ authUser: makeAdminUser() });
      render(<User isOpen={true} onClose={vi.fn()} />);
      expect(mockForm.reset).toHaveBeenCalled();
    });
  });

  // ── XC password generation ───────────────────────────────────────────────────

  describe('XC password generation', () => {
    it('calls setValues with a generated xc_password when rotate icon is clicked', () => {
      setupMocks({ authUser: makeAdminUser() });
      render(
        <User
          isOpen={true}
          onClose={vi.fn()}
          user={makeRegularUser({ id: 2 })}
        />
      );

      const rotateButton = screen
        .getByTestId('icon-rotate-ccw-key')
        .closest('button');
      fireEvent.click(rotateButton);

      expect(mockForm.setValues).toHaveBeenCalledWith(
        expect.objectContaining({ xc_password: expect.any(String) })
      );
    });

    it('disables the XC password rotate button for non-admin', () => {
      setupMocks({ authUser: makeRegularUser() });
      render(
        <User
          isOpen={true}
          onClose={vi.fn()}
          user={makeRegularUser({ id: 5 })}
        />
      );

      const rotateButton = screen
        .getByTestId('icon-rotate-ccw-key')
        .closest('button');
      expect(rotateButton).toBeDisabled();
    });
  });

  // ── Channel profiles logic ───────────────────────────────────────────────────

  describe('channel profiles logic', () => {
    const profiles = { 1: { id: 1, name: 'HD' }, 2: { id: 2, name: 'SD' } };

    it('excludes "All" (0) when other profiles are selected alongside it', () => {
      setupMocks({ authUser: makeAdminUser(), profiles });
      render(
        <User
          isOpen={true}
          onClose={vi.fn()}
          user={makeRegularUser({ id: 2 })}
        />
      );

      const multiSelect = screen.getByTestId('multiselect-Channel Profiles');
      fireEvent.change(multiSelect, { target: { value: '1,2' } });

      expect(mockForm.setFieldValue).toHaveBeenCalledWith(
        'channel_profiles',
        expect.not.arrayContaining(['0'])
      );
    });

    it('sets only ["0"] when "All" is newly selected', () => {
      setupMocks({ authUser: makeAdminUser(), profiles });
      render(
        <User
          isOpen={true}
          onClose={vi.fn()}
          user={makeRegularUser({ id: 2 })}
        />
      );

      const multiSelect = screen.getByTestId('multiselect-Channel Profiles');
      fireEvent.change(multiSelect, { target: { value: '0' } });

      expect(mockForm.setFieldValue).toHaveBeenCalledWith('channel_profiles', [
        '0',
      ]);
    });

    it('allows multiple non-all profiles together', () => {
      setupMocks({ authUser: makeAdminUser(), profiles });
      render(
        <User
          isOpen={true}
          onClose={vi.fn()}
          user={makeRegularUser({ id: 2 })}
        />
      );

      const multiSelect = screen.getByTestId('multiselect-Channel Profiles');
      fireEvent.change(multiSelect, { target: { value: '1,2' } });

      expect(mockForm.setFieldValue).toHaveBeenCalledWith('channel_profiles', [
        '1',
        '2',
      ]);
    });
  });
});
