import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import LoginForm from '../LoginForm';

// ── Router mock ────────────────────────────────────────────────────────────────
const mockNavigate = vi.fn();
vi.mock('react-router-dom', () => ({
  useNavigate: () => mockNavigate,
}));

// Mock localStorage
const localStorageMock = (() => {
  let store = {};

  return {
    getItem: vi.fn((key) => store[key] || null),
    setItem: vi.fn((key, value) => {
      store[key] = value.toString();
    }),
    clear: vi.fn(() => {
      store = {};
    }),
    removeItem: vi.fn((key) => {
      delete store[key];
    }),
  };
})();

global.localStorage = localStorageMock;

// ── Store mocks ────────────────────────────────────────────────────────────────
vi.mock('../../../store/auth', () => ({ default: vi.fn() }));
vi.mock('../../../store/settings', () => ({ default: vi.fn() }));

// ── Utility mocks ──────────────────────────────────────────────────────────────
vi.mock('../../../utils/notificationUtils.js', () => ({
  showNotification: vi.fn(),
}));

// ── Asset mock ─────────────────────────────────────────────────────────────────
vi.mock('../../../assets/logo.png', () => ({ default: 'logo.png' }));

// ── Mantine core ───────────────────────────────────────────────────────────────
vi.mock('@mantine/core', async () => ({
  Paper: ({ children }) => <div data-testid="paper">{children}</div>,
  Title: ({ children }) => <h1>{children}</h1>,
  TextInput: ({ label, name, value, onChange, placeholder, type, disabled }) => (
    <input
      aria-label={label}
      name={name}
      value={value}
      onChange={onChange}
      placeholder={placeholder}
      type={type ?? 'text'}
      disabled={disabled}
      data-testid={`input-${label}`}
    />
  ),
  Button: ({ children, onClick, loading, disabled, type, variant }) => (
    <button
      onClick={onClick}
      disabled={disabled || loading}
      data-loading={loading}
      type={type}
      data-variant={variant}
    >
      {children}
    </button>
  ),
  Center: ({ children }) => <div>{children}</div>,
  Stack: ({ children }) => <div>{children}</div>,
  Text: ({ children, c, size }) => (
    <span data-color={c} data-size={size}>
      {children}
    </span>
  ),
  Image: ({ src, alt }) => <img src={src} alt={alt} />,
  Group: ({ children }) => <div>{children}</div>,
  Divider: () => <hr />,
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
  Anchor: ({ children, onClick }) => (
    <a data-testid="anchor" onClick={onClick} href="#">
      {children}
    </a>
  ),
  Code: ({ children }) => <code>{children}</code>,
  Checkbox: ({ label, checked, onChange }) => (
    <label>
      <input
        type="checkbox"
        aria-label={label}
        checked={checked}
        onChange={(e) => onChange(e)}
      />
      {label}
    </label>
  ),
}));

// ── Imports after mocks ────────────────────────────────────────────────────────
import useAuthStore from '../../../store/auth';
import useSettingsStore from '../../../store/settings';

// ── Helpers ────────────────────────────────────────────────────────────────────
const setupMocks = ({
                      isAuthenticated = false,
                      loginResult = Promise.resolve(true),
                      version = '1.0.0',
                    } = {}) => {
  const mockLogin = vi.fn().mockReturnValue(loginResult);
  const mockLogout = vi.fn();
  const mockInitData = vi.fn().mockResolvedValue(undefined);
  const mockFetchVersion = vi.fn().mockResolvedValue(undefined);

  vi.mocked(useAuthStore).mockImplementation((sel) =>
    sel({
      login: mockLogin,
      logout: mockLogout,
      isAuthenticated,
      initData: mockInitData,
    })
  );

  vi.mocked(useSettingsStore).mockImplementation((sel) =>
    sel({
      fetchVersion: mockFetchVersion,
      version: { version },
    })
  );

  return { mockLogin, mockLogout, mockInitData, mockFetchVersion };
};

const renderLoginForm = () => render(<LoginForm />);

const getUsername = () => screen.getByTestId('input-Username');
const getPassword = () => screen.getByTestId('input-Password');
const getLoginButton = () => screen.getByRole('button', { type: 'submit' });

// ──────────────────────────────────────────────────────────────────────────────

describe('LoginForm', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
  });

  // ── Rendering ──────────────────────────────────────────────────────────────

  describe('rendering', () => {
    it('renders the login form', () => {
      setupMocks();
      renderLoginForm();
      expect(screen.getByTestId('paper')).toBeInTheDocument();
    });

    it('renders the logo', () => {
      setupMocks();
      renderLoginForm();
      expect(screen.getByRole('img')).toHaveAttribute('src', 'logo.png');
    });

    it('renders username and password inputs', () => {
      setupMocks();
      renderLoginForm();
      expect(getUsername()).toBeInTheDocument();
      expect(getPassword()).toBeInTheDocument();
    });

    it('renders the login button', () => {
      setupMocks();
      renderLoginForm();
      expect(getLoginButton()).toBeInTheDocument();
    });

    it('renders "Remember Me" checkbox', () => {
      setupMocks();
      renderLoginForm();
      expect(screen.getByLabelText(/remember me/i)).toBeInTheDocument();
    });

    it('renders "Save Password" checkbox', async () => {
      setupMocks();
      renderLoginForm();
      await waitFor(() => {
        fireEvent.click(screen.getByLabelText(/remember me/i));
        expect(screen.getByLabelText(/save password/i)).toBeInTheDocument();
      });
    });

    it('renders version info when version is available', () => {
      setupMocks({ version: '2.3.4' });
      renderLoginForm();
        expect(screen.getByText(/2.3.4/i)).toBeInTheDocument();
    });

    it('renders forgot password anchor', () => {
      setupMocks();
      renderLoginForm();
      expect(screen.getByText(/forgot password/i)).toBeInTheDocument();
    });
  });

  // ── fetchVersion on mount ──────────────────────────────────────────────────

  describe('on mount', () => {
    it('calls fetchVersion on mount', () => {
      const { mockFetchVersion } = setupMocks();
      renderLoginForm();
      expect(mockFetchVersion).toHaveBeenCalled();
    });
  });

  // ── Form input ─────────────────────────────────────────────────────────────

  describe('form input', () => {
    it('updates username field on change', () => {
      setupMocks();
      renderLoginForm();
      fireEvent.change(getUsername(), { target: { value: 'testuser' } });
      expect(getUsername()).toHaveValue('testuser');
    });

    it('updates password field on change', () => {
      setupMocks();
      renderLoginForm();
      fireEvent.change(getPassword(), { target: { value: 'secret' } });
      expect(getPassword()).toHaveValue('secret');
    });

    it('password input has type="password"', () => {
      setupMocks();
      renderLoginForm();
      expect(getPassword()).toHaveAttribute('type', 'password');
    });
  });

  // ── Successful login ───────────────────────────────────────────────────────

  describe('successful login', () => {
    it('calls login with username and password', async () => {
      const { mockLogin } = setupMocks({ loginResult: Promise.resolve(true) });
      renderLoginForm();

      fireEvent.change(getUsername(), { target: { value: 'admin' } });
      fireEvent.change(getPassword(), { target: { value: 'pass123' } });
      fireEvent.click(getLoginButton());

      await waitFor(() => {
        expect(mockLogin).toHaveBeenCalledWith({ username: 'admin', password: 'pass123' });
      });
    });

    it('calls initData after successful login', async () => {
      const { mockInitData } = setupMocks({ loginResult: Promise.resolve(true) });
      renderLoginForm();

      fireEvent.change(getUsername(), { target: { value: 'admin' } });
      fireEvent.change(getPassword(), { target: { value: 'pass123' } });
      fireEvent.click(getLoginButton());

      await waitFor(() => {
        expect(mockInitData).toHaveBeenCalled();
      });
    });

    it('navigates to "/channels" when authenticated', async () => {
      setupMocks({ isAuthenticated: true });
      renderLoginForm();

      fireEvent.change(getUsername(), { target: { value: 'admin' } });
      fireEvent.change(getPassword(), { target: { value: 'pass123' } });
      fireEvent.click(getLoginButton());

      await waitFor(() => {
        expect(mockNavigate).toHaveBeenCalledWith('/channels');
      });
    });
  });

  // ── Failed login ───────────────────────────────────────────────────────────

  describe('failed login', () => {
    it('does not navigate when login fails', async () => {
      setupMocks({ loginResult: Promise.resolve(false) });
      renderLoginForm();

      fireEvent.change(getUsername(), { target: { value: 'admin' } });
      fireEvent.change(getPassword(), { target: { value: 'wrong' } });
      fireEvent.click(getLoginButton());

      await waitFor(() => {
        expect(mockNavigate).not.toHaveBeenCalled();
      });
    });

    it('does not navigate when login throws', async () => {
      setupMocks({ loginResult: Promise.reject(new Error('fail')) });
      renderLoginForm();

      fireEvent.click(getLoginButton());

      await waitFor(() => {
        expect(mockNavigate).not.toHaveBeenCalled();
      });
    });
  });

  // ── Loading state ──────────────────────────────────────────────────────────

  describe('loading state', () => {
    it('disables the login button while loading', async () => {
      let resolveLogin;
      const loginResult = new Promise((res) => { resolveLogin = res; });
      setupMocks({ loginResult });
      renderLoginForm();

      fireEvent.click(getLoginButton());

      await waitFor(() => {
        expect(getLoginButton()).toBeDisabled();
      });

      resolveLogin(true);
    });

    it('re-enables the login button after login completes', async () => {
      setupMocks({ loginResult: Promise.resolve(false) });
      renderLoginForm();

      fireEvent.click(getLoginButton());

      await waitFor(() => {
        expect(getLoginButton()).not.toBeDisabled();
      });
    });
  });

  // ── Remember Me ───────────────────────────────────────────────────────────

  describe('remember me', () => {
    it('saves username to localStorage when Remember Me is checked', async () => {
      setupMocks({ loginResult: Promise.resolve(true) });
      renderLoginForm();

      fireEvent.click(screen.getByLabelText(/remember me/i));
      fireEvent.change(getUsername(), { target: { value: 'savedUser' } });
      fireEvent.click(getLoginButton());

      await waitFor(() => {
        expect(localStorage.getItem('dispatcharr_remembered_username')).toBe('savedUser');
      });
    });

    it('removes username from localStorage when Remember Me is unchecked', async () => {
      localStorage.setItem('dispatcharr_remembered_username', 'oldUser');
      setupMocks({ loginResult: Promise.resolve(true) });
      renderLoginForm();

      fireEvent.click(screen.getByLabelText(/remember me/i));
      fireEvent.click(getLoginButton());

      await waitFor(() => {
        expect(localStorage.getItem('dispatcharr_remembered_username')).toBeNull();
      });
    });

    it('pre-fills username from localStorage on mount', () => {
      localStorage.setItem('dispatcharr_remembered_username', 'storedUser');
      setupMocks();
      renderLoginForm();
      expect(getUsername()).toHaveValue('storedUser');
    });
  });

  // ── Save Password ─────────────────────────────────────────────────────────

  describe('save password', () => {
    it('saves encoded password to localStorage when Save Password is checked', async () => {
      setupMocks({ loginResult: Promise.resolve(true) });
      renderLoginForm();

      await waitFor(() => {
        fireEvent.click(screen.getByLabelText(/remember me/i));
        fireEvent.click(screen.getByLabelText(/save password/i));
        fireEvent.change(getPassword(), { target: { value: 'mySecret' } });
        fireEvent.click(getLoginButton());
      });

      await waitFor(() => {
        expect(localStorage.getItem('dispatcharr_saved_password')).not.toBeNull();
      });
    });

    it('removes password from localStorage when Save Password is unchecked', async () => {
      localStorage.setItem('dispatcharr_saved_password', btoa('oldPass'));
      setupMocks({ loginResult: Promise.resolve(true) });
      renderLoginForm();

      fireEvent.click(getLoginButton());

      await waitFor(() => {
        expect(localStorage.getItem('dispatcharr_saved_password')).toBeNull();
      });
    });

    it('pre-fills password from localStorage on mount', () => {
      localStorage.setItem('dispatcharr_remembered_username', 'storedUser');
      localStorage.setItem('dispatcharr_saved_password', btoa('storedPass'));
      setupMocks();
      renderLoginForm();
      expect(getPassword()).toHaveValue('storedPass');
    });
  });

  // ── Forgot Password modal ──────────────────────────────────────────────────

  describe('forgot password modal', () => {
    it('opens the forgot password modal when the anchor is clicked', () => {
      setupMocks();
      renderLoginForm();

      fireEvent.click(screen.getByText(/forgot password/i));
      expect(screen.getByTestId('modal')).toBeInTheDocument();
    });

    it('shows the modal title', () => {
      setupMocks();
      renderLoginForm();

      fireEvent.click(screen.getByText(/forgot password/i));
      expect(screen.getByTestId('modal-title')).toBeInTheDocument();
    });

    it('closes the modal when the close button is clicked', () => {
      setupMocks();
      renderLoginForm();

      fireEvent.click(screen.getByText(/forgot password/i));
      fireEvent.click(screen.getByTestId('modal-close'));

      expect(screen.queryByTestId('modal')).not.toBeInTheDocument();
    });
  });
});