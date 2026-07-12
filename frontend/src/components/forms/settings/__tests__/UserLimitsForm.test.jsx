import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import UserLimitsForm from '../UserLimitsForm';

// ── Store mock ─────────────────────────────────────────────────────────────────
vi.mock('../../../../store/settings.jsx', () => ({ default: vi.fn() }));

// ── @mantine/form mock ────────────────────────────────────────────────────────
vi.mock('@mantine/form', () => ({ useForm: vi.fn() }));

// ── @mantine/core mock ────────────────────────────────────────────────────────
vi.mock('@mantine/core', () => ({
  Alert: ({ title, color, variant }) => (
    <div data-testid="alert" data-color={color} data-variant={variant}>
      {title}
    </div>
  ),
  Button: ({ children, type, disabled, variant, color, onClick }) => (
    <button
      type={type}
      disabled={disabled}
      data-variant={variant}
      data-color={color}
      onClick={onClick}
    >
      {children}
    </button>
  ),
  Checkbox: ({ label, description, checked, onChange }) => (
    <div data-testid="checkbox-wrapper">
      {label && <label data-testid="checkbox-label">{label}</label>}
      {description && (
        <span data-testid="checkbox-description">{description}</span>
      )}
      <input
        data-testid={`checkbox-${label}`}
        type="checkbox"
        checked={checked ?? false}
        onChange={(e) => onChange?.(e.currentTarget.checked)}
      />
    </div>
  ),
  Flex: ({ children, mih, gap, justify, align }) => (
    <div
      data-mih={mih}
      data-gap={gap}
      data-justify={justify}
      data-align={align}
    >
      {children}
    </div>
  ),
  Stack: ({ children, gap }) => <div data-gap={gap}>{children}</div>,
}));

// ── SettingsUtils mock ────────────────────────────────────────────────────────
vi.mock('../../../../utils/pages/SettingsUtils.js', () => ({
  updateSetting: vi.fn(),
}));

// ──────────────────────────────────────────────────────────────────────────────
// Imports after mocks
// ──────────────────────────────────────────────────────────────────────────────
import useSettingsStore from '../../../../store/settings.jsx';
import { useForm } from '@mantine/form';
import { updateSetting } from '../../../../utils/pages/SettingsUtils.js';
import { USER_LIMITS_OPTIONS } from '../../../../constants.js';

// ── Derived constants (mirrors the component) ─────────────────────────────────
const USER_LIMIT_DEFAULTS = Object.keys(USER_LIMITS_OPTIONS).reduce(
  (acc, key) => {
    acc[key] = USER_LIMITS_OPTIONS[key].default;
    return acc;
  },
  {}
);

// ── Form mock factory ─────────────────────────────────────────────────────────

let mockForm;

const createMockForm = (initialValues = { ...USER_LIMIT_DEFAULTS }) => {
  const state = { ...initialValues };
  return {
    values: state,
    setValues: vi.fn((vals) => {
      Object.assign(state, vals);
    }),
    getInputProps: vi.fn((field, opts) => {
      if (opts?.type === 'checkbox') {
        return {
          checked: state[field],
          onChange: vi.fn((val) => {
            state[field] = val;
          }),
        };
      }
      return { value: state[field], onChange: vi.fn() };
    }),
    getValues: vi.fn(() => ({ ...state })),
    onSubmit: vi.fn((handler) => (e) => {
      e?.preventDefault?.();
      return handler();
    }),
    submitting: false,
  };
};

// ── Settings factories ────────────────────────────────────────────────────────

const makeSettings = (userLimitValue = {}) => ({
  user_limit_settings: { id: 1, value: userLimitValue },
});

// ──────────────────────────────────────────────────────────────────────────────

describe('UserLimitsForm', () => {
  beforeEach(() => {
    vi.clearAllMocks();

    mockForm = createMockForm();
    vi.mocked(useForm).mockReturnValue(mockForm);

    vi.mocked(useSettingsStore).mockImplementation((sel) =>
      sel({ settings: null })
    );

    vi.mocked(updateSetting).mockResolvedValue({ id: 1 });
  });

  // ── Rendering ──────────────────────────────────────────────────────────────

  describe('rendering', () => {
    it('renders without crashing', () => {
      render(<UserLimitsForm active={true} />);
      expect(screen.getAllByTestId('checkbox-wrapper')).toHaveLength(
        Object.keys(USER_LIMITS_OPTIONS).length
      );
    });

    it('renders a Checkbox for every USER_LIMITS_OPTIONS entry', () => {
      render(<UserLimitsForm active={true} />);
      Object.values(USER_LIMITS_OPTIONS).forEach((opt) => {
        expect(screen.getByText(opt.label)).toBeInTheDocument();
      });
    });

    it('renders every checkbox description', () => {
      render(<UserLimitsForm active={true} />);
      Object.values(USER_LIMITS_OPTIONS).forEach((opt) => {
        expect(screen.getByText(opt.description)).toBeInTheDocument();
      });
    });

    it('renders a Save button of type="submit"', () => {
      render(<UserLimitsForm active={true} />);
      const btn = screen.getByText('Save');
      expect(btn).toHaveAttribute('type', 'submit');
    });

    it('renders a "Reset to Defaults" button', () => {
      render(<UserLimitsForm active={true} />);
      expect(screen.getByText('Reset to Defaults')).toBeInTheDocument();
    });

    it('does not show the "Saved Successfully" alert initially', () => {
      render(<UserLimitsForm active={true} />);
      expect(screen.queryByTestId('alert')).not.toBeInTheDocument();
    });
  });

  // ── Initialization ─────────────────────────────────────────────────────────

  describe('initialization', () => {
    it('calls useForm with mode="controlled"', () => {
      render(<UserLimitsForm active={true} />);
      expect(vi.mocked(useForm)).toHaveBeenCalledWith(
        expect.objectContaining({ mode: 'controlled' })
      );
    });

    it('seeds useForm with USER_LIMIT_DEFAULTS as initialValues', () => {
      render(<UserLimitsForm active={true} />);
      expect(vi.mocked(useForm)).toHaveBeenCalledWith(
        expect.objectContaining({ initialValues: USER_LIMIT_DEFAULTS })
      );
    });

    it('calls getInputProps with type:"checkbox" for each option key', () => {
      render(<UserLimitsForm active={true} />);
      Object.keys(USER_LIMITS_OPTIONS).forEach((key) => {
        expect(mockForm.getInputProps).toHaveBeenCalledWith(key, {
          type: 'checkbox',
        });
      });
    });
  });

  // ── Settings effect ────────────────────────────────────────────────────────

  describe('settings effect', () => {
    it('calls setValues with merged defaults + stored values when settings provided', () => {
      const stored = {
        terminate_on_limit_exceeded: false,
        ignore_same_channel_connections: true,
      };
      vi.mocked(useSettingsStore).mockImplementation((sel) =>
        sel({ settings: makeSettings(stored) })
      );

      render(<UserLimitsForm active={true} />);

      expect(mockForm.setValues).toHaveBeenCalledWith({
        ...USER_LIMIT_DEFAULTS,
        ...stored,
      });
    });

    it('does not call setValues when settings is null', () => {
      vi.mocked(useSettingsStore).mockImplementation((sel) =>
        sel({ settings: null })
      );

      render(<UserLimitsForm active={true} />);

      expect(mockForm.setValues).not.toHaveBeenCalled();
    });

    it('does not call setValues when user_limit_settings.value is absent', () => {
      vi.mocked(useSettingsStore).mockImplementation((sel) =>
        sel({ settings: { user_limit_settings: { id: 1 } } })
      );

      render(<UserLimitsForm active={true} />);

      expect(mockForm.setValues).not.toHaveBeenCalled();
    });
  });

  // ── active prop effect ─────────────────────────────────────────────────────

  describe('active prop effect', () => {
    it('resets the saved alert when active changes to false', async () => {
      vi.mocked(useSettingsStore).mockImplementation((sel) =>
        sel({ settings: makeSettings({}) })
      );

      const { rerender } = render(<UserLimitsForm active={true} />);

      fireEvent.click(screen.getByText('Save'));
      await waitFor(() => {
        expect(screen.getByTestId('alert')).toBeInTheDocument();
      });

      rerender(<UserLimitsForm active={false} />);
      expect(screen.queryByTestId('alert')).not.toBeInTheDocument();
    });

    it('does not show alert when active starts as false', () => {
      render(<UserLimitsForm active={false} />);
      expect(screen.queryByTestId('alert')).not.toBeInTheDocument();
    });
  });

  // ── Reset to Defaults ──────────────────────────────────────────────────────

  describe('"Reset to Defaults" button', () => {
    it('calls form.setValues with USER_LIMIT_DEFAULTS when clicked', () => {
      render(<UserLimitsForm active={true} />);
      fireEvent.click(screen.getByText('Reset to Defaults'));
      expect(mockForm.setValues).toHaveBeenCalledWith(USER_LIMIT_DEFAULTS);
    });

    it('can be clicked multiple times without error', () => {
      render(<UserLimitsForm active={true} />);
      fireEvent.click(screen.getByText('Reset to Defaults'));
      fireEvent.click(screen.getByText('Reset to Defaults'));
      expect(mockForm.setValues).toHaveBeenCalledTimes(2);
    });
  });

  // ── Submit — success ───────────────────────────────────────────────────────

  describe('submit — success', () => {
    it('calls updateSetting with merged user_limit_settings + current values', async () => {
      const stored = { id: 42, key: 'user_limit_settings', value: {} };
      vi.mocked(useSettingsStore).mockImplementation((sel) =>
        sel({ settings: { user_limit_settings: stored } })
      );

      render(<UserLimitsForm active={true} />);
      // Set values after render to avoid settings effect overwriting them
      Object.assign(mockForm.values, { terminate_on_limit_exceeded: false });

      fireEvent.click(screen.getByText('Save'));

      await waitFor(() => {
        expect(updateSetting).toHaveBeenCalledWith({
          ...stored,
          value: expect.objectContaining({
            terminate_on_limit_exceeded: false,
          }),
        });
      });
    });

    it('shows "Saved Successfully" alert when updateSetting returns a truthy result', async () => {
      vi.mocked(updateSetting).mockResolvedValue({ id: 1 });
      vi.mocked(useSettingsStore).mockImplementation((sel) =>
        sel({ settings: makeSettings({}) })
      );

      render(<UserLimitsForm active={true} />);
      fireEvent.click(screen.getByText('Save'));

      await waitFor(() => {
        expect(screen.getByTestId('alert')).toBeInTheDocument();
        expect(screen.getByText('Saved Successfully')).toBeInTheDocument();
      });
    });

    it('does NOT show alert when updateSetting returns null/falsy', async () => {
      vi.mocked(updateSetting).mockResolvedValue(null);
      vi.mocked(useSettingsStore).mockImplementation((sel) =>
        sel({ settings: makeSettings({}) })
      );

      render(<UserLimitsForm active={true} />);
      fireEvent.click(screen.getByText('Save'));

      await waitFor(() => {
        expect(updateSetting).toHaveBeenCalled();
      });
      expect(screen.queryByTestId('alert')).not.toBeInTheDocument();
    });

    it('passes getValues() result as the value to updateSetting', async () => {
      const currentValues = {
        terminate_on_limit_exceeded: false,
        prioritize_single_client_channels: true,
        ignore_same_channel_connections: true,
        terminate_oldest: false,
      };
      mockForm.getValues.mockReturnValue(currentValues);
      vi.mocked(useSettingsStore).mockImplementation((sel) =>
        sel({ settings: makeSettings({}) })
      );

      render(<UserLimitsForm active={true} />);
      fireEvent.click(screen.getByText('Save'));

      await waitFor(() => {
        expect(updateSetting).toHaveBeenCalledWith(
          expect.objectContaining({ value: currentValues })
        );
      });
    });

    it('clears saved=false at start of each submit before setting it true', async () => {
      vi.mocked(updateSetting).mockResolvedValue({ id: 1 });
      vi.mocked(useSettingsStore).mockImplementation((sel) =>
        sel({ settings: makeSettings({}) })
      );

      render(<UserLimitsForm active={true} />);

      // First save
      fireEvent.click(screen.getByText('Save'));
      await waitFor(() =>
        expect(screen.getByTestId('alert')).toBeInTheDocument()
      );

      // Second save — alert should still appear after re-submit
      fireEvent.click(screen.getByText('Save'));
      await waitFor(() =>
        expect(screen.getByTestId('alert')).toBeInTheDocument()
      );
    });
  });

  // ── Submit — error ─────────────────────────────────────────────────────────

  describe('submit — error', () => {
    it('does not show alert when updateSetting throws', async () => {
      vi.mocked(updateSetting).mockRejectedValue(new Error('network error'));
      vi.mocked(useSettingsStore).mockImplementation((sel) =>
        sel({ settings: makeSettings({}) })
      );

      render(<UserLimitsForm active={true} />);
      fireEvent.click(screen.getByText('Save'));

      await waitFor(() => {
        expect(updateSetting).toHaveBeenCalled();
      });
      expect(screen.queryByTestId('alert')).not.toBeInTheDocument();
    });

    it('does not throw to the caller when updateSetting rejects', async () => {
      vi.mocked(updateSetting).mockRejectedValue(new Error('fail'));
      vi.mocked(useSettingsStore).mockImplementation((sel) =>
        sel({ settings: makeSettings({}) })
      );

      render(<UserLimitsForm active={true} />);

      await expect(
        waitFor(() => fireEvent.click(screen.getByText('Save')))
      ).resolves.not.toThrow();
    });
  });

  // ── Submit disabled state ──────────────────────────────────────────────────

  describe('Save button disabled state', () => {
    it('is disabled when form.submitting is true', () => {
      mockForm.submitting = true;
      render(<UserLimitsForm active={true} />);
      expect(screen.getByText('Save')).toBeDisabled();
    });

    it('is not disabled when form.submitting is false', () => {
      mockForm.submitting = false;
      render(<UserLimitsForm active={true} />);
      expect(screen.getByText('Save')).not.toBeDisabled();
    });
  });
});
