import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

// ── Asset mock ─────────────────────────────────────────────────────────────────
vi.mock('../../../assets/logo.png', () => ({ default: 'logo.png' }));

// ── API mock ───────────────────────────────────────────────────────────────────
vi.mock('../../../api', () => ({
  default: {
    createSuperUser: vi.fn(),
  },
}));

// ── Store mocks ────────────────────────────────────────────────────────────────
vi.mock('../../../store/auth', () => ({ default: vi.fn() }));
vi.mock('../../../store/settings', () => ({ default: vi.fn() }));

// ── @mantine/core ──────────────────────────────────────────────────────────────
vi.mock('@mantine/core', () => ({
  Button: ({ children, type, fullWidth }) => (
    <button type={type} data-fullwidth={fullWidth}>
      {children}
    </button>
  ),
  Center: ({ children, style }) => <div style={style}>{children}</div>,
  Divider: ({ style }) => <hr style={style} />,
  Image: ({ src, alt }) => <img src={src} alt={alt} />,
  Paper: ({ children, style }) => <div style={style}>{children}</div>,
  Stack: ({ children }) => <div>{children}</div>,
  Text: ({ children, size, color, align }) => (
    <span data-size={size} data-color={color} data-align={align}>
      {children}
    </span>
  ),
  TextInput: ({ label, name, value, onChange, required, type }) => (
    <div>
      <label htmlFor={name}>{label}</label>
      <input
        id={name}
        name={name}
        data-testid={`input-${name}`}
        type={type ?? 'text'}
        value={value}
        onChange={onChange}
        required={required}
      />
    </div>
  ),
  Title: ({ children, order, align }) => {
    const Tag = `h${order ?? 1}`;
    return <Tag data-align={align}>{children}</Tag>;
  },
}));

// ── Imports after mocks ────────────────────────────────────────────────────────
import SuperuserForm from '../SuperuserForm';
import API from '../../../api';
import useAuthStore from '../../../store/auth';
import useSettingsStore from '../../../store/settings';

// ── Helpers ────────────────────────────────────────────────────────────────────
const setupMocks = ({
  version = {},
  fetchVersion = vi.fn(),
  setSuperuserExists = vi.fn(),
} = {}) => {
  vi.mocked(useAuthStore).mockImplementation((sel) =>
    sel({ setSuperuserExists })
  );
  vi.mocked(useSettingsStore).mockImplementation((sel) =>
    sel({ fetchVersion, version })
  );
  return { fetchVersion, setSuperuserExists };
};

describe('SuperuserForm', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // ── Rendering ──────────────────────────────────────────────────────────────

  describe('rendering', () => {
    it('renders the Dispatcharr title', () => {
      setupMocks();
      render(<SuperuserForm />);
      expect(screen.getByText('Dispatcharr')).toBeInTheDocument();
    });

    it('renders the welcome message', () => {
      setupMocks();
      render(<SuperuserForm />);
      expect(
        screen.getByText(
          'Welcome! Create your Super User Account to get started.'
        )
      ).toBeInTheDocument();
    });

    it('renders the logo image', () => {
      setupMocks();
      render(<SuperuserForm />);
      expect(screen.getByAltText('Dispatcharr Logo')).toBeInTheDocument();
    });

    it('renders Username input', () => {
      setupMocks();
      render(<SuperuserForm />);
      expect(screen.getByTestId('input-username')).toBeInTheDocument();
    });

    it('renders Password input with type="password"', () => {
      setupMocks();
      render(<SuperuserForm />);
      const input = screen.getByTestId('input-password');
      expect(input).toBeInTheDocument();
      expect(input).toHaveAttribute('type', 'password');
    });

    it('renders Email input with type="email"', () => {
      setupMocks();
      render(<SuperuserForm />);
      const input = screen.getByTestId('input-email');
      expect(input).toBeInTheDocument();
      expect(input).toHaveAttribute('type', 'email');
    });

    it('renders the Create Account button', () => {
      setupMocks();
      render(<SuperuserForm />);
      expect(
        screen.getByRole('button', { name: 'Create Account' })
      ).toBeInTheDocument();
    });

    it('does not render version text when version is not loaded', () => {
      setupMocks({ version: {} });
      render(<SuperuserForm />);
      expect(screen.queryByText(/^v/)).not.toBeInTheDocument();
    });

    it('renders version text when version is loaded', () => {
      setupMocks({ version: { version: '1.2.3' } });
      render(<SuperuserForm />);
      expect(screen.getByText('v1.2.3')).toBeInTheDocument();
    });
  });

  // ── useEffect ─────────────────────────────────────────────────────────────

  describe('useEffect', () => {
    it('calls fetchVersion on mount', () => {
      const { fetchVersion } = setupMocks();
      render(<SuperuserForm />);
      expect(fetchVersion).toHaveBeenCalledTimes(1);
    });

    it('does not call fetchVersion again on re-render with same fetchVersion ref', () => {
      const { fetchVersion } = setupMocks();
      const { rerender } = render(<SuperuserForm />);
      rerender(<SuperuserForm />);
      // fetchVersion is stable, so useEffect should only fire once
      expect(fetchVersion).toHaveBeenCalledTimes(1);
    });
  });

  // ── Form field interactions ────────────────────────────────────────────────

  describe('form field interactions', () => {
    it('updates username field when typed', () => {
      setupMocks();
      render(<SuperuserForm />);
      fireEvent.change(screen.getByTestId('input-username'), {
        target: { name: 'username', value: 'admin' },
      });
      expect(screen.getByTestId('input-username')).toHaveValue('admin');
    });

    it('updates password field when typed', () => {
      setupMocks();
      render(<SuperuserForm />);
      fireEvent.change(screen.getByTestId('input-password'), {
        target: { name: 'password', value: 'secret123' },
      });
      expect(screen.getByTestId('input-password')).toHaveValue('secret123');
    });

    it('updates email field when typed', () => {
      setupMocks();
      render(<SuperuserForm />);
      fireEvent.change(screen.getByTestId('input-email'), {
        target: { name: 'email', value: 'admin@example.com' },
      });
      expect(screen.getByTestId('input-email')).toHaveValue(
        'admin@example.com'
      );
    });

    it('initializes all fields as empty strings', () => {
      setupMocks();
      render(<SuperuserForm />);
      expect(screen.getByTestId('input-username')).toHaveValue('');
      expect(screen.getByTestId('input-password')).toHaveValue('');
      expect(screen.getByTestId('input-email')).toHaveValue('');
    });
  });

  // ── Form submission ────────────────────────────────────────────────────────

  describe('form submission', () => {
    it('calls API.createSuperUser with form values on submit', async () => {
      setupMocks();
      vi.mocked(API.createSuperUser).mockResolvedValue({
        superuser_exists: false,
      });
      render(<SuperuserForm />);

      fireEvent.change(screen.getByTestId('input-username'), {
        target: { name: 'username', value: 'admin' },
      });
      fireEvent.change(screen.getByTestId('input-password'), {
        target: { name: 'password', value: 'secret' },
      });
      fireEvent.change(screen.getByTestId('input-email'), {
        target: { name: 'email', value: 'admin@test.com' },
      });

      fireEvent.submit(
        screen.getByRole('button', { name: 'Create Account' }).closest('form')
      );

      await waitFor(() => {
        expect(API.createSuperUser).toHaveBeenCalledWith({
          username: 'admin',
          password: 'secret',
          email: 'admin@test.com',
        });
      });
    });

    it('calls setSuperuserExists(true) when response.superuser_exists is true', async () => {
      const { setSuperuserExists } = setupMocks();
      vi.mocked(API.createSuperUser).mockResolvedValue({
        superuser_exists: true,
      });
      render(<SuperuserForm />);

      fireEvent.change(screen.getByTestId('input-username'), {
        target: { name: 'username', value: 'admin' },
      });
      fireEvent.submit(
        screen.getByRole('button', { name: 'Create Account' }).closest('form')
      );

      await waitFor(() => {
        expect(setSuperuserExists).toHaveBeenCalledWith(true);
      });
    });

    it('does not call setSuperuserExists when response.superuser_exists is false', async () => {
      const { setSuperuserExists } = setupMocks();
      vi.mocked(API.createSuperUser).mockResolvedValue({
        superuser_exists: false,
      });
      render(<SuperuserForm />);

      fireEvent.submit(
        screen.getByRole('button', { name: 'Create Account' }).closest('form')
      );

      await waitFor(() => {
        expect(API.createSuperUser).toHaveBeenCalled();
      });

      expect(setSuperuserExists).not.toHaveBeenCalled();
    });

    it('does not throw when API.createSuperUser rejects', async () => {
      setupMocks();
      vi.mocked(API.createSuperUser).mockRejectedValue(new Error('Network'));
      render(<SuperuserForm />);

      fireEvent.submit(
        screen.getByRole('button', { name: 'Create Account' }).closest('form')
      );

      await expect(
        waitFor(() => expect(API.createSuperUser).toHaveBeenCalled())
      ).resolves.not.toThrow();
    });

    it('does not call setSuperuserExists when API throws', async () => {
      const { setSuperuserExists } = setupMocks();
      vi.mocked(API.createSuperUser).mockRejectedValue(new Error('Network'));
      render(<SuperuserForm />);

      fireEvent.submit(
        screen.getByRole('button', { name: 'Create Account' }).closest('form')
      );

      await waitFor(() => {
        expect(API.createSuperUser).toHaveBeenCalled();
      });

      expect(setSuperuserExists).not.toHaveBeenCalled();
    });

    it('submits with empty email when email field is left blank', async () => {
      setupMocks();
      vi.mocked(API.createSuperUser).mockResolvedValue({
        superuser_exists: false,
      });
      render(<SuperuserForm />);

      fireEvent.change(screen.getByTestId('input-username'), {
        target: { name: 'username', value: 'admin' },
      });
      fireEvent.change(screen.getByTestId('input-password'), {
        target: { name: 'password', value: 'secret' },
      });

      fireEvent.submit(
        screen.getByRole('button', { name: 'Create Account' }).closest('form')
      );

      await waitFor(() => {
        expect(API.createSuperUser).toHaveBeenCalledWith(
          expect.objectContaining({ email: '' })
        );
      });
    });
  });
});
