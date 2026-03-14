import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import ProxySettingsForm from '../ProxySettingsForm';

// ── Constants mock ─────────────────────────────────────────────────────────────
vi.mock('../../../../constants.js', () => ({
  PROXY_SETTINGS_OPTIONS: {
    buffering_timeout: {
      label: 'Buffering Timeout',
      description: 'Timeout in seconds',
    },
    buffering_speed: {
      label: 'Buffering Speed',
      description: 'Speed multiplier',
    },
    redis_url: { label: 'Redis URL', description: 'Redis connection URL' },
  },
}));

// ── Store mock ─────────────────────────────────────────────────────────────────
vi.mock('../../../../store/settings.jsx', () => ({ default: vi.fn() }));

// ── Utility mocks ──────────────────────────────────────────────────────────────
vi.mock('../../../../utils/pages/SettingsUtils.js', () => ({
  updateSetting: vi.fn(),
}));

vi.mock('../../../../utils/forms/settings/ProxySettingsFormUtils.js', () => ({
  getProxySettingsFormInitialValues: vi.fn(),
  getProxySettingDefaults: vi.fn(),
}));

// ── Mantine form ───────────────────────────────────────────────────────────────
vi.mock('@mantine/form', () => ({ useForm: vi.fn() }));

// ── Mantine core ───────────────────────────────────────────────────────────────
vi.mock('@mantine/core', () => ({
  Alert: ({ title, children }) => (
    <div data-testid="alert">
      <span data-testid="alert-title">{title}</span>
      {children}
    </div>
  ),
  Button: ({ children, onClick, disabled, loading, type, variant, color }) => (
    <button
      type={type || 'button'}
      onClick={onClick}
      disabled={disabled || loading}
      data-variant={variant}
      data-color={color}
      data-loading={String(loading)}
    >
      {children}
    </button>
  ),
  Flex: ({ children }) => <div>{children}</div>,
  NumberInput: ({ label, description, min, max, step, ...rest }) => (
    <div>
      <label>{label}</label>
      {description && <span data-testid={`desc-${label}`}>{description}</span>}
      <input
        data-testid={`number-input-${label}`}
        type="number"
        aria-label={label}
        min={min}
        max={max}
        step={step}
        onChange={(e) => rest.onChange?.(Number(e.target.value))}
        value={rest.value ?? 0}
      />
    </div>
  ),
  Stack: ({ children }) => <div>{children}</div>,
  TextInput: ({ label, description, ...rest }) => (
    <div>
      <label>{label}</label>
      {description && <span data-testid={`desc-${label}`}>{description}</span>}
      <input
        data-testid={`text-input-${label}`}
        aria-label={label}
        onChange={(e) => rest.onChange?.(e)}
        value={rest.value ?? ''}
      />
    </div>
  ),
}));

// ──────────────────────────────────────────────────────────────────────────────
// Imports after mocks
// ──────────────────────────────────────────────────────────────────────────────
import useSettingsStore from '../../../../store/settings.jsx';
import { useForm } from '@mantine/form';
import { updateSetting } from '../../../../utils/pages/SettingsUtils.js';
import {
  getProxySettingsFormInitialValues,
  getProxySettingDefaults,
} from '../../../../utils/forms/settings/ProxySettingsFormUtils.js';

// ──────────────────────────────────────────────────────────────────────────────
// Helpers
// ──────────────────────────────────────────────────────────────────────────────
const mockInitialValues = {
  buffering_timeout: 30,
  buffering_speed: 1.0,
  redis_url: 'redis://localhost:6379',
};

const mockDefaults = {
  buffering_timeout: 30,
  buffering_speed: 1.0,
  redis_url: '',
};

const makeFormMock = (overrides = {}) => ({
  getInputProps: vi.fn((field) => ({
    value: mockInitialValues[field] ?? '',
    onChange: vi.fn(),
  })),
  setValues: vi.fn(),
  getValues: vi.fn(() => mockInitialValues),
  onSubmit: vi.fn((handler) => (e) => {
    e?.preventDefault?.();
    return handler();
  }),
  submitting: false,
  errors: {},
  ...overrides,
});

const makeSettings = (overrides = {}) => ({
  proxy_settings: {
    key: 'proxy_settings',
    value: { ...mockInitialValues },
  },
  ...overrides,
});

const setupMocks = ({ settings = makeSettings(), formOverrides = {} } = {}) => {
  const formMock = makeFormMock(formOverrides);

  vi.mocked(useForm).mockReturnValue(formMock);
  vi.mocked(getProxySettingsFormInitialValues).mockReturnValue(
    mockInitialValues
  );
  vi.mocked(getProxySettingDefaults).mockReturnValue(mockDefaults);
  vi.mocked(updateSetting).mockResolvedValue({ success: true });
  vi.mocked(useSettingsStore).mockImplementation((sel) => sel({ settings }));

  return { formMock };
};

// ──────────────────────────────────────────────────────────────────────────────
// Tests
// ──────────────────────────────────────────────────────────────────────────────
describe('ProxySettingsForm', () => {
  let formMock;

  beforeEach(() => {
    vi.clearAllMocks();
    ({ formMock } = setupMocks());
  });

  // ── Rendering ──────────────────────────────────────────────────────────────
  describe('rendering', () => {
    it('does not show success alert on initial render', () => {
      render(<ProxySettingsForm active={true} />);
      expect(screen.queryByTestId('alert')).not.toBeInTheDocument();
    });

    it('renders NumberInput for buffering_timeout', () => {
      render(<ProxySettingsForm active={true} />);
      expect(
        screen.getByTestId('number-input-Buffering Timeout')
      ).toBeInTheDocument();
    });

    it('renders NumberInput for buffering_speed', () => {
      render(<ProxySettingsForm active={true} />);
      expect(
        screen.getByTestId('number-input-Buffering Speed')
      ).toBeInTheDocument();
    });

    it('renders TextInput for redis_url', () => {
      render(<ProxySettingsForm active={true} />);
      expect(screen.getByTestId('text-input-Redis URL')).toBeInTheDocument();
    });

    it('renders description text for fields that have one', () => {
      render(<ProxySettingsForm active={true} />);
      expect(screen.getByTestId('desc-Buffering Timeout')).toBeInTheDocument();
    });
  });

  // ── Initialization ─────────────────────────────────────────────────────────
  describe('initialization', () => {
    it('calls getProxySettingsFormInitialValues on mount', () => {
      render(<ProxySettingsForm active={true} />);
      expect(getProxySettingsFormInitialValues).toHaveBeenCalled();
    });

    it('calls setValues with merged defaults and stored settings on mount', async () => {
      render(<ProxySettingsForm active={true} />);
      await waitFor(() => {
        expect(formMock.setValues).toHaveBeenCalledWith({
          ...mockDefaults,
          ...makeSettings().proxy_settings.value,
        });
      });
    });

    it('does not call setValues when proxy_settings is missing', async () => {
      ({ formMock } = setupMocks({ settings: {} }));
      render(<ProxySettingsForm active={true} />);
      await waitFor(() => {
        expect(formMock.setValues).not.toHaveBeenCalled();
      });
    });

    it('does not call setValues when proxy_settings.value is missing', async () => {
      ({ formMock } = setupMocks({
        settings: { proxy_settings: { key: 'proxy_settings' } },
      }));
      render(<ProxySettingsForm active={true} />);
      await waitFor(() => {
        expect(formMock.setValues).not.toHaveBeenCalled();
      });
    });

    it('handles null settings gracefully', () => {
      vi.mocked(useSettingsStore).mockImplementation((sel) =>
        sel({ settings: null })
      );
      expect(() => render(<ProxySettingsForm active={true} />)).not.toThrow();
    });
  });

  // ── active prop ────────────────────────────────────────────────────────────
  describe('active prop', () => {
    it('clears saved state when active becomes false', async () => {
      vi.mocked(updateSetting).mockResolvedValue({ success: true });
      const { rerender } = render(<ProxySettingsForm active={true} />);

      // Trigger a successful save
      fireEvent.submit(screen.getByText('Save').closest('form'));
      await waitFor(() => {
        expect(screen.getByTestId('alert')).toBeInTheDocument();
      });

      rerender(<ProxySettingsForm active={false} />);

      await waitFor(() => {
        expect(screen.queryByTestId('alert')).not.toBeInTheDocument();
      });
    });
  });

  // ── Form submission ────────────────────────────────────────────────────────
  describe('form submission', () => {
    it('calls updateSetting with proxy_settings on Save', async () => {
      render(<ProxySettingsForm active={true} />);
      fireEvent.submit(screen.getByText('Save').closest('form'));

      await waitFor(() => {
        expect(updateSetting).toHaveBeenCalledWith({
          ...makeSettings().proxy_settings,
          value: mockInitialValues,
        });
      });
    });

    it('shows success alert when updateSetting returns a truthy result', async () => {
      render(<ProxySettingsForm active={true} />);
      fireEvent.submit(screen.getByText('Save').closest('form'));

      await waitFor(() => {
        expect(screen.getByTestId('alert')).toBeInTheDocument();
        expect(screen.getByTestId('alert-title')).toHaveTextContent(
          'Saved Successfully'
        );
      });
    });

    it('does not show success alert when updateSetting returns undefined', async () => {
      vi.mocked(updateSetting).mockResolvedValue(undefined);
      render(<ProxySettingsForm active={true} />);
      fireEvent.submit(screen.getByText('Save').closest('form'));

      await waitFor(() => {
        expect(updateSetting).toHaveBeenCalled();
      });
      expect(screen.queryByTestId('alert')).not.toBeInTheDocument();
    });

    it('does not show success alert when updateSetting returns null', async () => {
      vi.mocked(updateSetting).mockResolvedValue(null);
      render(<ProxySettingsForm active={true} />);
      fireEvent.submit(screen.getByText('Save').closest('form'));

      await waitFor(() => {
        expect(updateSetting).toHaveBeenCalled();
      });
      expect(screen.queryByTestId('alert')).not.toBeInTheDocument();
    });

    it('does not show success alert when updateSetting throws', async () => {
      vi.mocked(updateSetting).mockRejectedValue(new Error('save failed'));
      render(<ProxySettingsForm active={true} />);
      fireEvent.submit(screen.getByText('Save').closest('form'));

      expect(screen.queryByTestId('alert')).not.toBeInTheDocument();
    });

    it('resets saved to false at the start of a new submission', async () => {
      render(<ProxySettingsForm active={true} />);

      // First save — succeeds
      fireEvent.submit(screen.getByText('Save').closest('form'));
      await waitFor(() => screen.getByTestId('alert'));

      // Second save — returns undefined (no result)
      vi.mocked(updateSetting).mockResolvedValue(undefined);
      fireEvent.submit(screen.getByText('Save').closest('form'));

      await waitFor(() => {
        expect(screen.queryByTestId('alert')).not.toBeInTheDocument();
      });
    });
  });

  // ── Reset to Defaults ──────────────────────────────────────────────────────
  describe('Reset to Defaults', () => {
    it('calls getProxySettingDefaults when Reset to Defaults is clicked', () => {
      render(<ProxySettingsForm active={true} />);
      fireEvent.click(screen.getByText('Reset to Defaults'));
      expect(getProxySettingDefaults).toHaveBeenCalled();
    });

    it('calls form.setValues with defaults when Reset to Defaults is clicked', () => {
      render(<ProxySettingsForm active={true} />);
      fireEvent.click(screen.getByText('Reset to Defaults'));
      expect(formMock.setValues).toHaveBeenCalledWith(mockDefaults);
    });

    it('does not submit the form when Reset to Defaults is clicked', async () => {
      render(<ProxySettingsForm active={true} />);
      fireEvent.click(screen.getByText('Reset to Defaults'));
      await waitFor(() => {
        expect(updateSetting).not.toHaveBeenCalled();
      });
    });
  });

  // ── ProxySettingsOptions field routing ─────────────────────────────────────
  describe('ProxySettingsOptions field routing', () => {
    it('calls getInputProps for each PROXY_SETTINGS_OPTIONS key', () => {
      render(<ProxySettingsForm active={true} />);
      expect(formMock.getInputProps).toHaveBeenCalledWith('buffering_timeout');
      expect(formMock.getInputProps).toHaveBeenCalledWith('buffering_speed');
      expect(formMock.getInputProps).toHaveBeenCalledWith('redis_url');
    });
  });
});
