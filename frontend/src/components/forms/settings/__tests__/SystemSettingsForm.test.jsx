import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import SystemSettingsForm from '../SystemSettingsForm';

// ── Store mocks ────────────────────────────────────────────────────────────────
vi.mock('../../../../store/settings.jsx', () => ({ default: vi.fn() }));

// ── Constants mock ─────────────────────────────────────────────────────────────
vi.mock('../../../../constants.js', () => ({
  REGION_CHOICES: [
    { label: 'United States', value: 'US' },
    { label: 'Europe', value: 'EU' },
  ],
}));

// ── Utility mocks ──────────────────────────────────────────────────────────────
vi.mock('../../../../utils/pages/SettingsUtils.js', () => ({
  getChangedSettings: vi.fn(),
  parseSettings: vi.fn(),
  saveChangedSettings: vi.fn(),
}));

vi.mock('../../../../utils/forms/settings/SystemSettingsFormUtils.js', () => ({
  getSystemSettingsFormInitialValues: vi.fn(),
}));

vi.mock('../ConnectionSecurityPanel.jsx', () => ({
  default: () => (
    <div data-testid="connection-security-panel">ConnectionSecurityPanel</div>
  ),
}));

// ── Mantine form ───────────────────────────────────────────────────────────────
vi.mock('@mantine/form', () => ({
  useForm: vi.fn(),
}));

// ── Mantine core ───────────────────────────────────────────────────────────────
vi.mock('@mantine/core', () => ({
  Alert: ({ title }) => <div data-testid="alert">{title}</div>,
  Button: ({ children, onClick, disabled }) => (
    <button onClick={onClick} disabled={disabled}>
      {children}
    </button>
  ),
  Flex: ({ children }) => <div>{children}</div>,
  NumberInput: ({ label, value, onChange, min, max, step, description }) => (
    <div>
      <label>{label}</label>
      <p>{description}</p>
      <input
        data-testid="number-input"
        type="number"
        value={value}
        min={min}
        max={max}
        step={step}
        onChange={(e) => onChange(Number(e.target.value))}
      />
    </div>
  ),
  Stack: ({ children }) => <div>{children}</div>,
  Group: ({ children }) => <div>{children}</div>,
  Select: ({ label, id, data, description }) => (
    <div>
      <label htmlFor={id}>{label}</label>
      {description && <p>{description}</p>}
      <select data-testid={id} id={id} aria-label={label}>
        {data?.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>
    </div>
  ),
  Switch: ({ id }) => (
    <input data-testid={id} id={id} type="checkbox" onChange={() => {}} />
  ),
  Text: ({ children }) => <span>{children}</span>,
  Divider: () => <hr />,
}));

// ──────────────────────────────────────────────────────────────────────────────
// Imports after mocks
// ──────────────────────────────────────────────────────────────────────────────
import useSettingsStore from '../../../../store/settings.jsx';
import {
  getChangedSettings,
  parseSettings,
  saveChangedSettings,
} from '../../../../utils/pages/SettingsUtils.js';
import { getSystemSettingsFormInitialValues } from '../../../../utils/forms/settings/SystemSettingsFormUtils.js';
import { useForm } from '@mantine/form';

// ──────────────────────────────────────────────────────────────────────────────
// Helpers
// ──────────────────────────────────────────────────────────────────────────────
const makeSettings = (overrides = {}) => ({
  max_system_events: 100,
  ...overrides,
});

const makeEnvironment = (overrides = {}) => ({
  env_mode: 'aio',
  ...overrides,
});

const setupMocks = ({
  settings = makeSettings(),
  environment = makeEnvironment(),
} = {}) => {
  const formValues = {
    max_system_events: settings?.max_system_events ?? 100,
    preferred_region: '',
    auto_import_mapped_files: true,
    enable_ip_lookup: true,
    catchup_enabled: true,
  };

  const formMock = {
    values: formValues,
    getValues: vi.fn().mockReturnValue(formValues),
    setValues: vi.fn(),
    setFieldValue: vi.fn((key, value) => {
      formMock.values[key] = value;
    }),
    getInputProps: vi.fn((field, opts) => {
      if (opts?.type === 'checkbox') {
        return { checked: formValues[field] ?? false, onChange: vi.fn() };
      }
      return { value: formValues[field] ?? '', onChange: vi.fn() };
    }),
    onSubmit: vi.fn((handler) => handler),
    submitting: false,
  };

  vi.mocked(useForm).mockReturnValue(formMock);
  vi.mocked(getSystemSettingsFormInitialValues).mockReturnValue(formValues);
  vi.mocked(useSettingsStore).mockImplementation((sel) =>
    sel({ settings, environment })
  );
  vi.mocked(parseSettings).mockReturnValue(formValues);
  vi.mocked(getChangedSettings).mockReturnValue({
    max_system_events: settings?.max_system_events ?? 100,
  });
  vi.mocked(saveChangedSettings).mockResolvedValue(undefined);

  return { formMock };
};

// ──────────────────────────────────────────────────────────────────────────────
// Tests
// ──────────────────────────────────────────────────────────────────────────────
describe('SystemSettingsForm', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // ── Rendering ──────────────────────────────────────────────────────────────

  describe('rendering', () => {
    it('renders the Save button', () => {
      setupMocks();
      render(<SystemSettingsForm active={true} />);
      expect(screen.getByText('Save')).toBeInTheDocument();
    });

    it('renders the NumberInput for max_system_events', () => {
      setupMocks();
      render(<SystemSettingsForm active={true} />);
      expect(screen.getByTestId('number-input')).toBeInTheDocument();
    });

    it('renders the NumberInput label', () => {
      setupMocks();
      render(<SystemSettingsForm active={true} />);
      expect(screen.getByText('Maximum System Events')).toBeInTheDocument();
    });

    it('renders the NumberInput description', () => {
      setupMocks();
      render(<SystemSettingsForm active={true} />);
      expect(
        screen.getByText(
          'Number of events to retain (minimum: 10, maximum: 1000). Events are displayed on the Stats page.'
        )
      ).toBeInTheDocument();
    });

    it('renders the Preferred Region select', () => {
      setupMocks();
      render(<SystemSettingsForm active={true} />);
      expect(screen.getByLabelText('Preferred Region')).toBeInTheDocument();
    });

    it('populates region options from REGION_CHOICES', () => {
      setupMocks();
      render(<SystemSettingsForm active={true} />);
      expect(screen.getByText('United States')).toBeInTheDocument();
      expect(screen.getByText('Europe')).toBeInTheDocument();
    });

    it('renders the Auto-Import Mapped Files switch', () => {
      setupMocks();
      render(<SystemSettingsForm active={true} />);
      expect(
        screen.getByTestId('auto_import_mapped_files')
      ).toBeInTheDocument();
    });

    it('renders the Enable Catchup switch', () => {
      setupMocks();
      render(<SystemSettingsForm active={true} />);
      expect(screen.getByTestId('catchup_enabled')).toBeInTheDocument();
    });

    it('does not show success alert on initial render', () => {
      setupMocks();
      render(<SystemSettingsForm active={true} />);
      expect(screen.queryByTestId('alert')).not.toBeInTheDocument();
    });

    it('does not render Connection Security panel in non-modular mode', () => {
      setupMocks({ environment: makeEnvironment({ env_mode: 'aio' }) });
      render(<SystemSettingsForm active={true} />);
      expect(
        screen.queryByTestId('connection-security-panel')
      ).not.toBeInTheDocument();
    });

    it('renders Connection Security panel in modular mode', () => {
      setupMocks({ environment: makeEnvironment({ env_mode: 'modular' }) });
      render(<SystemSettingsForm active={true} />);
      expect(
        screen.getByTestId('connection-security-panel')
      ).toBeInTheDocument();
    });

    it('renders NumberInput with value from form values', () => {
      setupMocks({ settings: makeSettings({ max_system_events: 250 }) });
      render(<SystemSettingsForm active={true} />);
      expect(screen.getByTestId('number-input')).toHaveValue(250);
    });

    it('falls back to 100 when max_system_events is 0/falsy', () => {
      const formValues = { max_system_events: 0 };
      const formMock = {
        values: formValues,
        getValues: vi.fn().mockReturnValue(formValues),
        setValues: vi.fn(),
        setFieldValue: vi.fn(),
        getInputProps: vi.fn((field, opts) => {
          if (opts?.type === 'checkbox') {
            return { checked: formValues[field] ?? false, onChange: vi.fn() };
          }
          return { value: formValues[field] ?? '', onChange: vi.fn() };
        }),
        onSubmit: vi.fn((handler) => handler),
        submitting: false,
      };
      vi.mocked(useForm).mockReturnValue(formMock);
      vi.mocked(getSystemSettingsFormInitialValues).mockReturnValue(formValues);
      vi.mocked(useSettingsStore).mockImplementation((sel) =>
        sel({
          settings: makeSettings({ max_system_events: 0 }),
          environment: makeEnvironment(),
        })
      );
      vi.mocked(parseSettings).mockReturnValue(formValues);
      vi.mocked(getChangedSettings).mockReturnValue({});
      vi.mocked(saveChangedSettings).mockResolvedValue(undefined);

      render(<SystemSettingsForm active={true} />);
      expect(screen.getByTestId('number-input')).toHaveValue(100);
    });
  });

  // ── Settings initialization ────────────────────────────────────────────────

  describe('settings initialization', () => {
    it('calls parseSettings with settings on mount', () => {
      const settings = makeSettings();
      setupMocks({ settings });
      render(<SystemSettingsForm active={true} />);
      expect(parseSettings).toHaveBeenCalledWith(settings);
    });

    it('calls form.setValues with parsed settings on mount', () => {
      const settings = makeSettings();
      const { formMock } = setupMocks({ settings });
      render(<SystemSettingsForm active={true} />);
      expect(formMock.setValues).toHaveBeenCalledWith({
        max_system_events: 100,
        preferred_region: '',
        auto_import_mapped_files: true,
        enable_ip_lookup: true,
        catchup_enabled: true,
      });
    });

    it('does not call parseSettings when settings is null', () => {
      const nullFormValues = { max_system_events: 100 };
      const formMock = {
        values: nullFormValues,
        getValues: vi.fn().mockReturnValue(nullFormValues),
        setValues: vi.fn(),
        setFieldValue: vi.fn(),
        getInputProps: vi.fn((field, opts) => {
          if (opts?.type === 'checkbox') {
            return {
              checked: nullFormValues[field] ?? false,
              onChange: vi.fn(),
            };
          }
          return { value: nullFormValues[field] ?? '', onChange: vi.fn() };
        }),
        onSubmit: vi.fn((handler) => handler),
        submitting: false,
      };
      vi.mocked(useForm).mockReturnValue(formMock);
      vi.mocked(getSystemSettingsFormInitialValues).mockReturnValue(
        nullFormValues
      );
      vi.mocked(useSettingsStore).mockImplementation((sel) =>
        sel({ settings: null, environment: makeEnvironment() })
      );
      vi.mocked(parseSettings).mockReturnValue({});
      vi.mocked(saveChangedSettings).mockResolvedValue(undefined);

      render(<SystemSettingsForm active={true} />);
      expect(parseSettings).not.toHaveBeenCalled();
    });
  });

  // ── NumberInput interaction ────────────────────────────────────────────────

  describe('NumberInput interaction', () => {
    it('calls form.setFieldValue when NumberInput changes', () => {
      const { formMock } = setupMocks();
      render(<SystemSettingsForm active={true} />);
      fireEvent.change(screen.getByTestId('number-input'), {
        target: { value: '200' },
      });
      expect(formMock.setFieldValue).toHaveBeenCalledWith(
        'max_system_events',
        200
      );
    });
  });

  // ── Save / submit ──────────────────────────────────────────────────────────

  describe('save button', () => {
    it('calls getChangedSettings and saveChangedSettings on submit', async () => {
      const settings = makeSettings();
      const { formMock } = setupMocks({ settings });
      render(<SystemSettingsForm active={true} />);

      fireEvent.click(screen.getByText('Save'));

      await waitFor(() => {
        expect(getChangedSettings).toHaveBeenCalledWith(
          formMock.getValues(),
          settings
        );
        expect(saveChangedSettings).toHaveBeenCalled();
      });
    });

    it('shows success alert after successful save', async () => {
      setupMocks();
      render(<SystemSettingsForm active={true} />);

      fireEvent.click(screen.getByText('Save'));

      await waitFor(() => {
        expect(screen.getByTestId('alert')).toBeInTheDocument();
      });
      expect(screen.getByText('Saved Successfully')).toBeInTheDocument();
    });

    it('does not show success alert when saveChangedSettings throws', async () => {
      const consoleSpy = vi
        .spyOn(console, 'error')
        .mockImplementation(() => {});
      setupMocks();
      vi.mocked(saveChangedSettings).mockRejectedValue(
        new Error('save failed')
      );

      render(<SystemSettingsForm active={true} />);
      fireEvent.click(screen.getByText('Save'));

      await waitFor(() => {
        expect(consoleSpy).toHaveBeenCalled();
      });
      expect(screen.queryByTestId('alert')).not.toBeInTheDocument();
      consoleSpy.mockRestore();
    });

    it('logs error when saveChangedSettings throws', async () => {
      const error = new Error('save failed');
      const consoleSpy = vi
        .spyOn(console, 'error')
        .mockImplementation(() => {});
      setupMocks();
      vi.mocked(saveChangedSettings).mockRejectedValue(error);

      render(<SystemSettingsForm active={true} />);
      fireEvent.click(screen.getByText('Save'));

      await waitFor(() => {
        expect(consoleSpy).toHaveBeenCalledWith(
          'Error saving settings:',
          error
        );
      });
      consoleSpy.mockRestore();
    });
  });

  // ── active prop / saved state reset ───────────────────────────────────────

  describe('active prop behavior', () => {
    it('clears saved alert when active becomes false', async () => {
      setupMocks();
      const { rerender } = render(<SystemSettingsForm active={true} />);

      fireEvent.click(screen.getByText('Save'));
      await waitFor(() => {
        expect(screen.getByTestId('alert')).toBeInTheDocument();
      });

      rerender(<SystemSettingsForm active={false} />);
      await waitFor(() => {
        expect(screen.queryByTestId('alert')).not.toBeInTheDocument();
      });
    });

    it('does not clear saved alert while active remains true', async () => {
      setupMocks();
      const { rerender } = render(<SystemSettingsForm active={true} />);

      fireEvent.click(screen.getByText('Save'));
      await waitFor(() => {
        expect(screen.getByTestId('alert')).toBeInTheDocument();
      });

      rerender(<SystemSettingsForm active={true} />);
      expect(screen.getByTestId('alert')).toBeInTheDocument();
    });
  });
});
