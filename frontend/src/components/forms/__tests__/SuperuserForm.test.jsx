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
  Anchor: ({ children, onClick, component = 'a', type, ...rest }) => {
    const Component = component;
    return (
      <Component type={type} onClick={onClick} {...rest}>
        {children}
      </Component>
    );
  },
  Button: ({ children, type, fullWidth, disabled, onClick }) => (
    <button
      type={type}
      data-fullwidth={fullWidth}
      disabled={disabled}
      onClick={onClick}
    >
      {children}
    </button>
  ),
  Center: ({ children, style }) => <div style={style}>{children}</div>,
  Code: ({ children, block }) =>
    block ? <pre>{children}</pre> : <code>{children}</code>,
  Divider: ({ style }) => <hr style={style} />,
  Group: ({ children }) => <div>{children}</div>,
  Image: ({ src, alt }) => <img src={src} alt={alt} />,
  Modal: ({ children, opened, title, ...rest }) =>
    opened ? (
      <div role="dialog" data-testid={rest['data-testid']} data-title={title}>
        <strong>{title}</strong>
        {children}
      </div>
    ) : null,
  Paper: ({ children, style }) => <div style={style}>{children}</div>,
  Stack: ({ children }) => <div>{children}</div>,
  Text: ({ children, size, color, align, weight, mb }) => (
    <span
      data-size={size}
      data-color={color}
      data-align={align}
      data-weight={weight}
      data-mb={mb}
    >
      {children}
    </span>
  ),
  TextInput: ({ label, name, value, onChange, required, type, disabled }) => (
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
        disabled={disabled}
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
  setSuperuserStatus = vi.fn(),
  setupStatus = {
    superuser_exists: false,
    setup_allowed: true,
    client_ip: '127.0.0.1',
  },
} = {}) => {
  vi.mocked(useAuthStore).mockImplementation((sel) =>
    sel({
      setSuperuserStatus,
      setupAllowed: setupStatus.setup_allowed,
      setupClientIp: setupStatus.client_ip,
    })
  );
  vi.mocked(useSettingsStore).mockImplementation((sel) =>
    sel({ fetchVersion, version })
  );
  return { fetchVersion, setSuperuserStatus };
};

describe('SuperuserForm', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // ── Rendering ──────────────────────────────────────────────────────────────

  describe('rendering', () => {
    it('renders the Dispatcharr title', async () => {
      setupMocks();
      render(<SuperuserForm />);
      expect(screen.getByText('Dispatcharr')).toBeInTheDocument();
    });

    it('renders the welcome message', async () => {
      setupMocks();
      render(<SuperuserForm />);
      expect(
        screen.getByText(
          'Welcome! Create your Super User Account to get started.'
        )
      ).toBeInTheDocument();
    });

    it('renders the logo image', async () => {
      setupMocks();
      render(<SuperuserForm />);
      expect(screen.getByAltText('Dispatcharr Logo')).toBeInTheDocument();
    });

    it('renders Username input', async () => {
      setupMocks();
      render(<SuperuserForm />);
      expect(screen.getByTestId('input-username')).toBeInTheDocument();
    });

    it('renders Password input with type="password"', async () => {
      setupMocks();
      render(<SuperuserForm />);
      const input = screen.getByTestId('input-password');
      expect(input).toBeInTheDocument();
      expect(input).toHaveAttribute('type', 'password');
    });

    it('renders Email input with type="email"', async () => {
      setupMocks();
      render(<SuperuserForm />);
      const input = screen.getByTestId('input-email');
      expect(input).toBeInTheDocument();
      expect(input).toHaveAttribute('type', 'email');
    });

    it('renders the Create Account button', async () => {
      setupMocks();
      render(<SuperuserForm />);
      expect(
        screen.getByRole('button', { name: 'Create Account' })
      ).toBeInTheDocument();
    });

    it('does not render version text when version is not loaded', async () => {
      setupMocks({ version: {} });
      render(<SuperuserForm />);
      expect(screen.queryByText(/^v/)).not.toBeInTheDocument();
    });

    it('renders version text when version is loaded', async () => {
      setupMocks({ version: { version: '1.2.3' } });
      render(<SuperuserForm />);
      expect(screen.getByText('v1.2.3')).toBeInTheDocument();
    });

    it('opens setup help modal when setup is not allowed from this IP', async () => {
      setupMocks({
        setupStatus: {
          superuser_exists: false,
          setup_allowed: false,
          client_ip: '203.0.113.50',
        },
      });
      render(<SuperuserForm />);
      await waitFor(() => {
        expect(screen.getByTestId('setup-help')).toBeInTheDocument();
      });
      expect(
        screen.getByText('Finish setup from this network')
      ).toBeInTheDocument();
      expect(screen.getAllByText('203.0.113.50').length).toBeGreaterThan(0);
      expect(
        screen.queryByRole('button', { name: 'Create Account' })
      ).not.toBeInTheDocument();
      expect(
        screen.getByRole('button', { name: 'View setup instructions' })
      ).toBeInTheDocument();
    });
  });

  // ── useEffect ─────────────────────────────────────────────────────────────

  describe('useEffect', () => {
    it('calls fetchVersion on mount', async () => {
      const { fetchVersion } = setupMocks();
      render(<SuperuserForm />);
      expect(fetchVersion).toHaveBeenCalledTimes(1);
    });

    it('does not call fetchVersion again on re-render with same fetchVersion ref', async () => {
      const { fetchVersion } = setupMocks();
      const { rerender } = render(<SuperuserForm />);
      rerender(<SuperuserForm />);
      // fetchVersion is stable, so useEffect should only fire once
      expect(fetchVersion).toHaveBeenCalledTimes(1);
    });
  });

  // ── Form field interactions ────────────────────────────────────────────────

  describe('form field interactions', () => {
    it('updates username field when typed', async () => {
      setupMocks();
      render(<SuperuserForm />);
      fireEvent.change(screen.getByTestId('input-username'), {
        target: { name: 'username', value: 'admin' },
      });
      expect(screen.getByTestId('input-username')).toHaveValue('admin');
    });

    it('updates password field when typed', async () => {
      setupMocks();
      render(<SuperuserForm />);
      fireEvent.change(screen.getByTestId('input-password'), {
        target: { name: 'password', value: 'secret123' },
      });
      expect(screen.getByTestId('input-password')).toHaveValue('secret123');
    });

    it('updates email field when typed', async () => {
      setupMocks();
      render(<SuperuserForm />);
      fireEvent.change(screen.getByTestId('input-email'), {
        target: { name: 'email', value: 'admin@example.com' },
      });
      expect(screen.getByTestId('input-email')).toHaveValue(
        'admin@example.com'
      );
    });

    it('initializes all fields as empty strings', async () => {
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

    it('calls setSuperuserStatus when response.superuser_exists is true', async () => {
      const { setSuperuserStatus } = setupMocks();
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
        expect(setSuperuserStatus).toHaveBeenCalledWith({
          superuser_exists: true,
        });
      });
    });

    it('does not call setSuperuserStatus when response.superuser_exists is false', async () => {
      const { setSuperuserStatus } = setupMocks();
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

      expect(setSuperuserStatus).not.toHaveBeenCalled();
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

    it('does not call setSuperuserStatus when API throws', async () => {
      const { setSuperuserStatus } = setupMocks();
      vi.mocked(API.createSuperUser).mockRejectedValue(new Error('Network'));
      render(<SuperuserForm />);

      fireEvent.submit(
        screen.getByRole('button', { name: 'Create Account' }).closest('form')
      );

      await waitFor(() => {
        expect(API.createSuperUser).toHaveBeenCalled();
      });

      expect(setSuperuserStatus).not.toHaveBeenCalled();
    });

    it('opens setup help modal when create is blocked with 403', async () => {
      setupMocks();
      const err = new Error('Forbidden');
      err.status = 403;
      err.body = {
        client_ip: '198.51.100.10',
        setup_allowed: false,
      };
      vi.mocked(API.createSuperUser).mockRejectedValue(err);
      render(<SuperuserForm />);

      fireEvent.submit(
        screen.getByRole('button', { name: 'Create Account' }).closest('form')
      );

      await waitFor(() => {
        expect(screen.getByTestId('setup-help')).toBeInTheDocument();
      });
      expect(
        screen.getByText('Finish setup from this network')
      ).toBeInTheDocument();
      expect(screen.getAllByText('198.51.100.10').length).toBeGreaterThan(0);
      expect(
        screen.getByRole('button', { name: 'View setup instructions' })
      ).toBeInTheDocument();
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
