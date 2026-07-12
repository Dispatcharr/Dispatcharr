import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import EpgSettingsForm from '../EpgSettingsForm';

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
  Button: ({ children, type, disabled }) => (
    <button type={type} disabled={disabled}>
      {children}
    </button>
  ),
  Flex: ({ children, justify }) => <div data-justify={justify}>{children}</div>,
  NumberInput: ({ label, description, min, max, value, onChange }) => (
    <div>
      {label && <label data-testid="number-input-label">{label}</label>}
      {description && (
        <span data-testid="number-input-description">{description}</span>
      )}
      <input
        data-testid="number-input"
        type="number"
        min={min}
        max={max}
        value={value ?? 0}
        onChange={(e) => onChange?.(Number(e.target.value))}
      />
    </div>
  ),
  Stack: ({ children, gap }) => <div data-gap={gap}>{children}</div>,
  Text: ({ children, size, c }) => (
    <span data-testid="text" data-size={size} data-color={c}>
      {children}
    </span>
  ),
}));

// ── SettingsUtils mock ────────────────────────────────────────────────────────
vi.mock('../../../../utils/pages/SettingsUtils.js', () => ({
  getChangedSettings: vi.fn(),
  parseSettings: vi.fn(),
  saveChangedSettings: vi.fn(),
}));

// ── EpgSettingsFormUtils mock ──────────────────────────────────────────────────
vi.mock('../../../../utils/forms/settings/EpgSettingsFormUtils.js', () => ({
  getEpgSettingsFormInitialValues: vi.fn(() => ({
    xmltv_prev_days_override: 0,
  })),
}));

// ──────────────────────────────────────────────────────────────────────────────
// Imports after mocks
// ──────────────────────────────────────────────────────────────────────────────
import useSettingsStore from '../../../../store/settings.jsx';
import { useForm } from '@mantine/form';
import * as SettingsUtils from '../../../../utils/pages/SettingsUtils.js';
import { getEpgSettingsFormInitialValues } from '../../../../utils/forms/settings/EpgSettingsFormUtils.js';
import { EPG_SETTINGS_OPTIONS } from '../../../../constants.js';

// ── Form mock factory ─────────────────────────────────────────────────────────

let mockForm;

const createMockForm = (initialValues = { xmltv_prev_days_override: 0 }) => {
  const state = { ...initialValues };
  return {
    values: state,
    setFieldValue: vi.fn((field, value) => {
      state[field] = value;
    }),
    getInputProps: vi.fn((field) => ({
      value: state[field],
      onChange: vi.fn((val) => {
        state[field] = val;
      }),
    })),
    getValues: vi.fn(() => ({ ...state })),
    onSubmit: vi.fn((handler) => (e) => {
      e?.preventDefault?.();
      return handler();
    }),
    submitting: false,
  };
};

// ── Settings factories ────────────────────────────────────────────────────────

const makeSettings = (epgValue = {}) => ({
  epg_settings: { id: 1, value: epgValue },
});

// ──────────────────────────────────────────────────────────────────────────────

describe('EpgSettingsForm', () => {
  beforeEach(() => {
    vi.clearAllMocks();

    mockForm = createMockForm();
    vi.mocked(useForm).mockReturnValue(mockForm);

    vi.mocked(useSettingsStore).mockImplementation((sel) =>
      sel({ settings: null })
    );

    vi.mocked(SettingsUtils.parseSettings).mockReturnValue({
      xmltv_prev_days_override: 0,
    });
    vi.mocked(SettingsUtils.getChangedSettings).mockReturnValue({});
    vi.mocked(SettingsUtils.saveChangedSettings).mockResolvedValue(undefined);
  });

  // ── Rendering ──────────────────────────────────────────────────────────────

  describe('rendering', () => {
    it('renders without crashing', () => {
      render(<EpgSettingsForm active={true} />);
      expect(screen.getByTestId('number-input')).toBeInTheDocument();
    });

    it('renders the NumberInput label from EPG_SETTINGS_OPTIONS', () => {
      render(<EpgSettingsForm active={true} />);
      expect(
        screen.getByText(EPG_SETTINGS_OPTIONS.xmltv_prev_days_override.label)
      ).toBeInTheDocument();
    });

    it('renders the NumberInput description from EPG_SETTINGS_OPTIONS', () => {
      render(<EpgSettingsForm active={true} />);
      expect(
        screen.getByText(
          EPG_SETTINGS_OPTIONS.xmltv_prev_days_override.description
        )
      ).toBeInTheDocument();
    });

    it('renders the disclaimer text about per-user defaults', () => {
      render(<EpgSettingsForm active={true} />);
      expect(
        screen.getByText(
          /Per-user defaults and URL parameters still override this global value/i
        )
      ).toBeInTheDocument();
    });

    it('renders the EPG channel matching hint', () => {
      render(<EpgSettingsForm active={true} />);
      expect(
        screen.getByText(
          /EPG channel matching options are configured from the Channels page/i
        )
      ).toBeInTheDocument();
    });

    it('renders a Save button of type="submit"', () => {
      render(<EpgSettingsForm active={true} />);
      const btn = screen.getByText('Save');
      expect(btn).toBeInTheDocument();
      expect(btn).toHaveAttribute('type', 'submit');
    });

    it('does not show the "Saved Successfully" alert initially', () => {
      render(<EpgSettingsForm active={true} />);
      expect(screen.queryByTestId('alert')).not.toBeInTheDocument();
    });

    it('NumberInput has min=0', () => {
      render(<EpgSettingsForm active={true} />);
      expect(screen.getByTestId('number-input')).toHaveAttribute('min', '0');
    });

    it('NumberInput has max=30', () => {
      render(<EpgSettingsForm active={true} />);
      expect(screen.getByTestId('number-input')).toHaveAttribute('max', '30');
    });

    it('NumberInput starts with value 0 from initial form values', () => {
      render(<EpgSettingsForm active={true} />);
      expect(screen.getByTestId('number-input')).toHaveValue(0);
    });
  });

  // ── Initialization ─────────────────────────────────────────────────────────

  describe('initialization', () => {
    it('calls getEpgSettingsFormInitialValues to seed useForm', () => {
      render(<EpgSettingsForm active={true} />);
      expect(getEpgSettingsFormInitialValues).toHaveBeenCalled();
    });

    it('passes initial values from getEpgSettingsFormInitialValues to useForm', () => {
      vi.mocked(getEpgSettingsFormInitialValues).mockReturnValue({
        xmltv_prev_days_override: 5,
      });
      render(<EpgSettingsForm active={true} />);
      expect(vi.mocked(useForm)).toHaveBeenCalledWith(
        expect.objectContaining({
          initialValues: { xmltv_prev_days_override: 5 },
        })
      );
    });

    it('calls useForm with mode="controlled"', () => {
      render(<EpgSettingsForm active={true} />);
      expect(vi.mocked(useForm)).toHaveBeenCalledWith(
        expect.objectContaining({ mode: 'controlled' })
      );
    });
  });

  // ── Settings effect ────────────────────────────────────────────────────────

  describe('settings effect', () => {
    it('calls parseSettings when settings are provided', () => {
      const settings = makeSettings({ xmltv_prev_days_override: 7 });
      vi.mocked(useSettingsStore).mockImplementation((sel) =>
        sel({ settings })
      );
      vi.mocked(SettingsUtils.parseSettings).mockReturnValue({
        xmltv_prev_days_override: 7,
      });

      render(<EpgSettingsForm active={true} />);

      expect(SettingsUtils.parseSettings).toHaveBeenCalledWith(settings);
    });

    it('calls setFieldValue with parsed xmltv_prev_days_override', () => {
      const settings = makeSettings({ xmltv_prev_days_override: 14 });
      vi.mocked(useSettingsStore).mockImplementation((sel) =>
        sel({ settings })
      );
      vi.mocked(SettingsUtils.parseSettings).mockReturnValue({
        xmltv_prev_days_override: 14,
      });

      render(<EpgSettingsForm active={true} />);

      expect(mockForm.setFieldValue).toHaveBeenCalledWith(
        'xmltv_prev_days_override',
        14
      );
    });

    it('calls setFieldValue with 0 when parsed value is undefined', () => {
      const settings = makeSettings({});
      vi.mocked(useSettingsStore).mockImplementation((sel) =>
        sel({ settings })
      );
      vi.mocked(SettingsUtils.parseSettings).mockReturnValue({});

      render(<EpgSettingsForm active={true} />);

      expect(mockForm.setFieldValue).toHaveBeenCalledWith(
        'xmltv_prev_days_override',
        0
      );
    });

    it('does not call parseSettings when settings is null', () => {
      vi.mocked(useSettingsStore).mockImplementation((sel) =>
        sel({ settings: null })
      );

      render(<EpgSettingsForm active={true} />);

      expect(SettingsUtils.parseSettings).not.toHaveBeenCalled();
    });
  });

  // ── active prop effect ─────────────────────────────────────────────────────

  describe('active prop effect', () => {
    it('resets the saved alert when active changes to false', async () => {
      vi.mocked(SettingsUtils.saveChangedSettings).mockResolvedValue(undefined);
      const { rerender } = render(<EpgSettingsForm active={true} />);

      // Trigger a successful save to get saved=true
      fireEvent.click(screen.getByText('Save'));
      await waitFor(() => {
        expect(screen.getByTestId('alert')).toBeInTheDocument();
      });

      // Switching active to false should dismiss the alert
      rerender(<EpgSettingsForm active={false} />);
      expect(screen.queryByTestId('alert')).not.toBeInTheDocument();
    });

    it('does not show alert when active starts as false', () => {
      render(<EpgSettingsForm active={false} />);
      expect(screen.queryByTestId('alert')).not.toBeInTheDocument();
    });
  });

  // ── Submit — success ───────────────────────────────────────────────────────

  describe('submit — success', () => {
    beforeEach(() => {
      vi.mocked(SettingsUtils.saveChangedSettings).mockResolvedValue(undefined);
    });

    it('calls getChangedSettings with form values and settings on submit', async () => {
      const settings = makeSettings({ xmltv_prev_days_override: 3 });
      vi.mocked(useSettingsStore).mockImplementation((sel) =>
        sel({ settings })
      );

      render(<EpgSettingsForm active={true} />);
      // Set the value after render so the settings useEffect (which resets the
      // field to the parseSettings result) has already run and won't overwrite it.
      mockForm.values.xmltv_prev_days_override = 5;
      fireEvent.click(screen.getByText('Save'));

      await waitFor(() => {
        expect(SettingsUtils.getChangedSettings).toHaveBeenCalledWith(
          expect.objectContaining({ xmltv_prev_days_override: 5 }),
          settings
        );
      });
    });

    it('calls saveChangedSettings with settings and changedSettings on submit', async () => {
      const settings = makeSettings({ xmltv_prev_days_override: 3 });
      vi.mocked(useSettingsStore).mockImplementation((sel) =>
        sel({ settings })
      );
      const changed = { xmltv_prev_days_override: 7 };
      vi.mocked(SettingsUtils.getChangedSettings).mockReturnValue(changed);

      render(<EpgSettingsForm active={true} />);
      fireEvent.click(screen.getByText('Save'));

      await waitFor(() => {
        expect(SettingsUtils.saveChangedSettings).toHaveBeenCalledWith(
          settings,
          changed
        );
      });
    });

    it('shows "Saved Successfully" alert after a successful save', async () => {
      render(<EpgSettingsForm active={true} />);
      fireEvent.click(screen.getByText('Save'));

      await waitFor(() => {
        expect(screen.getByTestId('alert')).toBeInTheDocument();
        expect(screen.getByText('Saved Successfully')).toBeInTheDocument();
      });
    });

    it('clears saved state before re-submitting', async () => {
      render(<EpgSettingsForm active={true} />);

      // First save
      fireEvent.click(screen.getByText('Save'));
      await waitFor(() => {
        expect(screen.getByTestId('alert')).toBeInTheDocument();
      });

      // Second save — saved resets to false then true again
      vi.mocked(SettingsUtils.saveChangedSettings).mockResolvedValue(undefined);
      fireEvent.click(screen.getByText('Save'));
      await waitFor(() => {
        expect(screen.getByTestId('alert')).toBeInTheDocument();
      });
    });
  });

  // ── Submit — error ─────────────────────────────────────────────────────────

  describe('submit — error', () => {
    it('does not show alert when saveChangedSettings throws', async () => {
      vi.mocked(SettingsUtils.saveChangedSettings).mockRejectedValue(
        new Error('network error')
      );
      render(<EpgSettingsForm active={true} />);
      fireEvent.click(screen.getByText('Save'));

      await waitFor(() => {
        expect(SettingsUtils.saveChangedSettings).toHaveBeenCalled();
      });
      expect(screen.queryByTestId('alert')).not.toBeInTheDocument();
    });

    it('does not throw when saveChangedSettings rejects', async () => {
      vi.mocked(SettingsUtils.saveChangedSettings).mockRejectedValue(
        new Error('fail')
      );
      render(<EpgSettingsForm active={true} />);

      await expect(
        waitFor(() => fireEvent.click(screen.getByText('Save')))
      ).resolves.not.toThrow();
    });
  });

  // ── getInputProps wiring ───────────────────────────────────────────────────

  describe('getInputProps wiring', () => {
    it('calls form.getInputProps with xmltv_prev_days_override', () => {
      render(<EpgSettingsForm active={true} />);
      expect(mockForm.getInputProps).toHaveBeenCalledWith(
        'xmltv_prev_days_override'
      );
    });
  });
});
