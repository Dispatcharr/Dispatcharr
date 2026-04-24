import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import NetworkAccessForm from '../NetworkAccessForm';

// ── Constants mock ─────────────────────────────────────────────────────────────
vi.mock('../../../../constants.js', () => ({
  NETWORK_ACCESS_OPTIONS: [
    { value: 'all', label: 'All' },
    { value: 'local', label: 'Local Only' },
    { value: 'custom', label: 'Custom' },
  ],
}));

// ── Store mock ─────────────────────────────────────────────────────────────────
vi.mock('../../../../store/settings.jsx', () => ({ default: vi.fn() }));

// ── Utility mocks ──────────────────────────────────────────────────────────────
vi.mock('../../../../utils/pages/SettingsUtils.js', () => ({
  checkSetting: vi.fn(),
  updateSetting: vi.fn(),
}));

vi.mock('../../../../utils/forms/settings/NetworkAccessFormUtils.js', () => ({
  getNetworkAccessFormInitialValues: vi.fn(),
  getNetworkAccessFormValidation: vi.fn(),
  getNetworkAccessDefaults: vi.fn(),
}));

// ── Mantine form ───────────────────────────────────────────────────────────────
vi.mock('@mantine/form', () => ({ useForm: vi.fn() }));

// ── ConfirmationDialog mock ────────────────────────────────────────────────────
vi.mock('../../../ConfirmationDialog.jsx', () => ({
  default: ({ opened, onConfirm, onClose, title, message }) =>
    opened ? (
      <div data-testid="confirmation-dialog">
        <div data-testid="confirm-title">{title}</div>
        <div data-testid="confirm-message">{message}</div>
        <button data-testid="confirm-ok" onClick={onConfirm}>
          Confirm
        </button>
        <button data-testid="confirm-cancel" onClick={onClose}>
          Cancel
        </button>
      </div>
    ) : null,
}));

// ── Mantine core ───────────────────────────────────────────────────────────────
vi.mock('@mantine/core', () => ({
  Alert: ({ title, children }) => (
    <div data-testid="alert">
      <span data-testid="alert-title">{title}</span>
      {children}
    </div>
  ),
  Button: ({ children, onClick, disabled, loading, type, variant }) => (
    <button
      type={type || 'button'}
      onClick={onClick}
      disabled={disabled || loading}
      data-variant={variant}
      data-loading={String(loading)}
    >
      {children}
    </button>
  ),
  Flex: ({ children }) => <div>{children}</div>,
  Stack: ({ children }) => <div>{children}</div>,
  Text: ({ children }) => <span>{children}</span>,
  TextInput: ({ label, id, placeholder, error, ...rest }) => (
    <div>
      <input
        data-testid={id}
        id={id}
        aria-label={label}
        placeholder={placeholder}
        data-error={error}
        onChange={(e) => rest.onChange?.(e)}
        value={rest.value ?? ''}
      />
      {error && <span data-testid={`${id}-error`}>{error}</span>}
    </div>
  ),
}));

// ──────────────────────────────────────────────────────────────────────────────
// Imports after mocks
// ──────────────────────────────────────────────────────────────────────────────
import useSettingsStore from '../../../../store/settings.jsx';
import { useForm } from '@mantine/form';
import {
  checkSetting,
  updateSetting,
} from '../../../../utils/pages/SettingsUtils.js';
import {
  getNetworkAccessFormInitialValues,
  getNetworkAccessFormValidation,
  getNetworkAccessDefaults,
} from '../../../../utils/forms/settings/NetworkAccessFormUtils.js';

// ──────────────────────────────────────────────────────────────────────────────
// Helpers
// ──────────────────────────────────────────────────────────────────────────────
const mockInitialValues = {
  m3u_access: 'local',
  epg_access: 'local',
  recordings_access: 'all',
  m3u_custom_cidrs: '',
  epg_custom_cidrs: '',
  recordings_custom_cidrs: '',
};

const makeFormMock = (overrides = {}) => ({
  key: vi.fn(),
  getInputProps: vi.fn((field) => ({
    value: mockInitialValues[field] ?? '',
    onChange: vi.fn(),
  })),
  setValues: vi.fn(),
  setErrors: vi.fn(),
  setFieldValue: vi.fn(),
  getValues: vi.fn(() => mockInitialValues),
  validate: vi.fn(() => ({ hasErrors: false })),
  onSubmit: vi.fn((handler) => (e) => {
    e?.preventDefault?.();
    return handler(mockInitialValues);
  }),
  errors: {},
  ...overrides,
});

const makeSettings = (overrides = {}) => ({
  network_access: {
    key: 'network_access',
    value: {
      m3u_access: 'local',
      epg_access: 'local',
      recordings_access: 'all',
    },
  },
  ...overrides,
});

const setupMocks = ({ settings = makeSettings(), formOverrides = {} } = {}) => {
  const formMock = makeFormMock(formOverrides);

  vi.mocked(useForm).mockReturnValue(formMock);
  vi.mocked(getNetworkAccessFormInitialValues).mockReturnValue(
    mockInitialValues
  );
  vi.mocked(getNetworkAccessFormValidation).mockReturnValue({});
  vi.mocked(getNetworkAccessDefaults).mockReturnValue(mockInitialValues);
  vi.mocked(checkSetting).mockResolvedValue({
    client_ip: '192.168.1.1',
    UI: ['192.168.0.0/16'],
  });
  vi.mocked(updateSetting).mockResolvedValue(undefined);

  vi.mocked(useSettingsStore).mockImplementation((sel) => sel({ settings }));

  return { formMock };
};

// ──────────────────────────────────────────────────────────────────────────────
// Tests
// ──────────────────────────────────────────────────────────────────────────────
describe('NetworkAccessForm', () => {
  let formMock;

  beforeEach(() => {
    vi.clearAllMocks();
    ({ formMock } = setupMocks());
  });

  // ── Rendering ──────────────────────────────────────────────────────────────
  describe('rendering', () => {
    it('renders without crashing', () => {
      render(<NetworkAccessForm active={true} />);
      expect(screen.getByText('Save')).toBeInTheDocument();
    });

    it('renders the Save button', () => {
      render(<NetworkAccessForm active={true} />);
      expect(screen.getByText('Save')).toBeInTheDocument();
    });

    it('does not show success alert on initial render', () => {
      render(<NetworkAccessForm active={true} />);
      expect(screen.queryByTestId('alert')).not.toBeInTheDocument();
    });

    it('does not show confirmation dialog on initial render', () => {
      render(<NetworkAccessForm active={true} />);
      expect(
        screen.queryByTestId('confirmation-dialog')
      ).not.toBeInTheDocument();
    });

    it('does not show error alert on initial render', () => {
      render(<NetworkAccessForm active={true} />);
      expect(screen.queryByTestId('alert')).not.toBeInTheDocument();
    });
  });

  // ── Initialization ─────────────────────────────────────────────────────────
  describe('initialization', () => {
    it('calls getNetworkAccessFormInitialValues on mount', () => {
      render(<NetworkAccessForm active={true} />);
      expect(getNetworkAccessFormInitialValues).toHaveBeenCalled();
    });

    it('calls getNetworkAccessFormValidation on mount', () => {
      render(<NetworkAccessForm active={true} />);
      expect(getNetworkAccessFormValidation).toHaveBeenCalled();
    });

    it('does not call checkSetting on mount', () => {
      render(<NetworkAccessForm active={true} />);
      expect(checkSetting).not.toHaveBeenCalled();
    });

    it('calls checkSetting when form is submitted', async () => {
      render(<NetworkAccessForm active={true} />);
      fireEvent.click(screen.getByText('Save'));
      await waitFor(() => {
        expect(checkSetting).toHaveBeenCalled();
      });
    });

    it('sets form values from network_access settings on mount', async () => {
      render(<NetworkAccessForm active={true} />);
      await waitFor(() => {
        expect(formMock.setValues).toHaveBeenCalled();
      });
    });

    it('handles missing network_access setting gracefully', async () => {
      ({ formMock } = setupMocks({ settings: {} }));
      expect(() => render(<NetworkAccessForm active={true} />)).not.toThrow();
    });

    it('handles checkSetting error gracefully', async () => {
      vi.mocked(checkSetting).mockRejectedValue(new Error('network error'));
      render(<NetworkAccessForm active={true} />);
    });
  });

  // ── active prop ────────────────────────────────────────────────────────────
  describe('active prop', () => {
    it('resets saved state when active becomes false', async () => {
      vi.mocked(updateSetting).mockResolvedValue(undefined);
      const { rerender } = render(<NetworkAccessForm active={true} />);

      fireEvent.submit(
        screen.getByText('Save').closest('form') ??
          screen.getByText('Save').closest('div')
      );

      await waitFor(() => {
        expect(screen.queryByTestId('confirmation-dialog')).not.toBeNull();
      }).catch(() => {});

      rerender(<NetworkAccessForm active={false} />);

      await waitFor(() => {
        expect(screen.queryByTestId('alert')).not.toBeInTheDocument();
      });
    });
  });

  // ── Form submission ────────────────────────────────────────────────────────
  describe('form submission', () => {
    it('opens confirmation dialog on Save click', async () => {
      render(<NetworkAccessForm active={true} />);
      fireEvent.click(screen.getByText('Save'));
      await waitFor(() => {
        expect(screen.getByTestId('confirmation-dialog')).toBeInTheDocument();
      });
    });

    it('closes confirmation dialog on Cancel click', async () => {
      render(<NetworkAccessForm active={true} />);
      fireEvent.click(screen.getByText('Save'));

      await waitFor(() => screen.getByTestId('confirmation-dialog'));
      fireEvent.click(screen.getByTestId('confirm-cancel'));

      await waitFor(() => {
        expect(
          screen.queryByTestId('confirmation-dialog')
        ).not.toBeInTheDocument();
      });
    });

    it('calls updateSetting on confirm', async () => {
      render(<NetworkAccessForm active={true} />);
      fireEvent.click(screen.getByText('Save'));

      await waitFor(() => screen.getByTestId('confirmation-dialog'));
      fireEvent.click(screen.getByTestId('confirm-ok'));

      await waitFor(() => {
        expect(updateSetting).toHaveBeenCalled();
      });
    });

    it('shows success alert after confirmed save', async () => {
      render(<NetworkAccessForm active={true} />);
      fireEvent.click(screen.getByText('Save'));

      await waitFor(() => screen.getByTestId('confirmation-dialog'));
      fireEvent.click(screen.getByTestId('confirm-ok'));

      await waitFor(() => {
        const alertTitles = screen.getAllByTestId('alert-title');
        expect(
          alertTitles.some((el) => el.textContent === 'Saved Successfully')
        ).toBe(true);
      });
    });

    it('does not call updateSetting when confirmation is cancelled', async () => {
      render(<NetworkAccessForm active={true} />);
      fireEvent.click(screen.getByText('Save'));

      await waitFor(() => screen.getByTestId('confirmation-dialog'));
      fireEvent.click(screen.getByTestId('confirm-cancel'));

      await waitFor(() => {
        expect(updateSetting).not.toHaveBeenCalled();
      });
    });

    it('does not show success alert when updateSetting throws', async () => {
      vi.mocked(updateSetting).mockRejectedValue({
        body: { value: { m3u_custom_cidrs: 'Invalid CIDR' } },
      });
      render(<NetworkAccessForm active={true} />);
      fireEvent.click(screen.getByText('Save'));

      await waitFor(() => screen.getByTestId('confirmation-dialog'));
      fireEvent.click(screen.getByTestId('confirm-ok'));

      await waitFor(() => {
        const alertTitle = screen.queryByTestId('alert-title');
        expect(alertTitle?.textContent).not.toBe('Saved Successfully');
      });
    });
  });

  // ── Client IP display ──────────────────────────────────────────────────────
  describe('client IP display', () => {
    it('displays client IP address fetched on submit', async () => {
      render(<NetworkAccessForm active={true} />);
      fireEvent.click(screen.getByText('Save'));

      await waitFor(() => screen.getByTestId('confirmation-dialog'));
      fireEvent.click(screen.getByTestId('confirm-ok'));
      await waitFor(() => {
        expect(screen.getByText(/192\.168\.1\.1/)).toBeInTheDocument();
      });
    });

    it('does not display IP when checkSetting returns null', async () => {
      vi.mocked(checkSetting).mockResolvedValue(null);
      render(<NetworkAccessForm active={true} />);
      await waitFor(() => {
        expect(
          screen.queryByText(/\d+\.\d+\.\d+\.\d+/)
        ).not.toBeInTheDocument();
      });
    });
  });

  // ── Network access error ───────────────────────────────────────────────────
  describe('network access error state', () => {
    it('clears error state after successful save', async () => {
      vi.mocked(checkSetting).mockResolvedValue({
        error: true,
        message: 'Invalid CIDR',
        data: 'Error details',
      });

      render(<NetworkAccessForm active={true} />);

      // First save — fails
      fireEvent.click(screen.getByText('Save'));
      await waitFor(() => screen.getByTestId('alert'));

      vi.mocked(checkSetting).mockResolvedValue({
        client_ip: '192.168.1.1',
        UI: ['192.168.0.0/16'],
      });

      // Second save — succeeds
      fireEvent.click(screen.getByText('Save'));
      await waitFor(() => screen.getByTestId('confirmation-dialog'));
      fireEvent.click(screen.getByTestId('confirm-ok'));

      await waitFor(() => {
        const alertTitles = screen.getAllByTestId('alert-title');
        expect(
          alertTitles.some((el) => el.textContent === 'Saved Successfully')
        ).toBe(true);
      });
    });
  });
});
