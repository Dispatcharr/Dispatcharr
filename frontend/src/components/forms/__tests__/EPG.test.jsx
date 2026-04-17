import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

// ── Utility mocks ──────────────────────────────────────────────────────────────
vi.mock('../../../utils/notificationUtils.js', () => ({
  showNotification: vi.fn(),
}));

vi.mock('../../../utils/forms/DummyEpgUtils.js', () => ({
  addEPG: vi.fn(),
  updateEPG: vi.fn(),
}));

// ── Mantine form ───────────────────────────────────────────────────────────────
vi.mock('@mantine/form', () => ({
  isNotEmpty: vi.fn(() => (val) => (val ? null : 'Required')),
  useForm: vi.fn(() => {
    const values = {
      name: '',
      source_type: 'xmltv',
      url: '',
      api_key: '',
      is_active: true,
      refresh_interval: 24,
      cron_expression: '',
      priority: 0,
    };
    return {
      key: vi.fn(),
      // Return the live object — no spread — so setFieldValue mutations are visible
      getValues: vi.fn(() => values),
      setValues: vi.fn((v) => Object.assign(values, v)),
      setFieldValue: vi.fn((field, value) => {
        values[field] = value;
      }),
      reset: vi.fn(),
      submitting: false,
      onSubmit: vi.fn((handler) => (e) => {
        e?.preventDefault?.();
        handler(values);
      }),
      getInputProps: vi.fn((field) => ({
        value: values[field] ?? '',
        onChange: vi.fn(),
        error: null,
      })),
    };
  }),
}));

// ── ScheduleInput mock ─────────────────────────────────────────────────────────
vi.mock('../ScheduleInput', () => ({
  default: ({
    scheduleType,
    onScheduleTypeChange,
    onIntervalChange,
    onCronChange,
  }) => (
    <div data-testid="schedule-input">
      <button
        data-testid="set-interval"
        onClick={() => onScheduleTypeChange('interval')}
      >
        Set Interval
      </button>
      <button
        data-testid="set-cron"
        onClick={() => onScheduleTypeChange('cron')}
      >
        Set Cron
      </button>
      <input
        data-testid="interval-input"
        onChange={(e) => onIntervalChange?.(Number(e.target.value))}
      />
      <input
        data-testid="cron-input"
        onChange={(e) => onCronChange?.(e.target.value)}
      />
      <span data-testid="schedule-type-value">{scheduleType}</span>
    </div>
  ),
}));

// ── Mantine core ───────────────────────────────────────────────────────────────
vi.mock('@mantine/core', async () => ({
  Box: ({ children, style }) => <div style={style}>{children}</div>,
  Button: ({ children, onClick, disabled, loading, type, color, variant }) => (
    <button
      type={type || 'button'}
      onClick={onClick}
      disabled={disabled || loading}
      data-color={color}
      data-variant={variant}
      data-loading={String(loading)}
    >
      {children}
    </button>
  ),
  Checkbox: ({ label, checked, onChange }) => (
    <label>
      <input
        type="checkbox"
        data-testid={`checkbox-${label?.toString().toLowerCase().replace(/\s+/g, '-')}`}
        checked={checked ?? false}
        onChange={(e) => onChange?.(e)}
      />
      {label}
    </label>
  ),
  Divider: () => <hr />,
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
  NativeSelect: ({ label, value, onChange, data }) => (
    <select
      aria-label={label}
      data-testid={`select-${label?.toString().toLowerCase().replace(/\s+/g, '-')}`}
      value={value ?? ''}
      onChange={(e) => onChange?.(e)}
    >
      {(data ?? []).map((opt) => {
        const val = typeof opt === 'string' ? opt : opt.value;
        const lbl = typeof opt === 'string' ? opt : opt.label;
        return (
          <option key={val} value={val}>
            {lbl}
          </option>
        );
      })}
    </select>
  ),
  NumberInput: ({ label, value, onChange, min, max, placeholder }) => (
    <input
      type="number"
      aria-label={label}
      data-testid={`number-${label?.toString().toLowerCase().replace(/\s+/g, '-')}`}
      value={value ?? ''}
      min={min}
      max={max}
      placeholder={placeholder}
      onChange={(e) => onChange?.(Number(e.target.value))}
    />
  ),
  Stack: ({ children }) => <div>{children}</div>,
  Text: ({ children, size, c, fw }) => (
    <span data-size={size} data-color={c} data-fw={fw}>
      {children}
    </span>
  ),
  TextInput: ({
    label,
    value,
    onChange,
    placeholder,
    error,
    id,
    name,
    required,
  }) => (
    <div>
      <label htmlFor={id || name}>{label}</label>
      <input
        id={id || name}
        data-testid={`input-${label?.toString().toLowerCase().replace(/\s+/g, '-')}`}
        value={value ?? ''}
        placeholder={placeholder}
        required={required}
        onChange={(e) =>
          onChange?.({
            target: { value: e.target.value },
            currentTarget: { value: e.target.value },
          })
        }
      />
      {error && <span data-testid="input-error">{error}</span>}
    </div>
  ),
}));

// ── Imports after mocks ────────────────────────────────────────────────────────
import EPG from '../EPG';
import * as DummyEpgUtils from '../../../utils/forms/DummyEpgUtils.js';
import { useForm } from '@mantine/form';

// ── Helpers ────────────────────────────────────────────────────────────────────
const makeEPG = (overrides = {}) => ({
  id: 1,
  name: 'Test EPG',
  source_type: 'xmltv',
  url: 'http://example.com/epg.xml',
  api_key: 'abc123',
  is_active: true,
  refresh_interval: 24,
  cron_expression: '',
  priority: 0,
  ...overrides,
});

const defaultProps = (overrides = {}) => ({
  epg: null,
  isOpen: true,
  onClose: vi.fn(),
  ...overrides,
});

// ──────────────────────────────────────────────────────────────────────────────
// Tests
// ──────────────────────────────────────────────────────────────────────────────
describe('EPG', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(DummyEpgUtils.addEPG).mockResolvedValue(undefined);
    vi.mocked(DummyEpgUtils.updateEPG).mockResolvedValue(undefined);
  });

  // ── Rendering ──────────────────────────────────────────────────────────────

  describe('rendering', () => {
    it('renders the modal when isOpen is true', () => {
      render(<EPG {...defaultProps()} />);
      expect(screen.getByTestId('modal')).toBeInTheDocument();
    });

    it('does not render the modal when isOpen is false', () => {
      render(<EPG {...defaultProps({ isOpen: false })} />);
      expect(screen.queryByTestId('modal')).not.toBeInTheDocument();
    });

    it('renders submit button with "Create" title for a new EPG', () => {
      render(<EPG {...defaultProps()} />);
      expect(screen.getByText('Create EPG Source')).toBeInTheDocument();
    });

    it('renders submit button with "Update" title when editing an existing EPG', () => {
      render(<EPG {...defaultProps({ epg: makeEPG() })} />);
      expect(screen.getByText('Update EPG Source')).toBeInTheDocument();
    });

    it('renders the Name input', () => {
      render(<EPG {...defaultProps()} />);
      expect(screen.getByTestId('input-name')).toBeInTheDocument();
    });

    it('renders the Source Type select', () => {
      render(<EPG {...defaultProps()} />);
      expect(screen.getByTestId('select-source-type')).toBeInTheDocument();
    });

    it('renders the URL input', () => {
      render(<EPG {...defaultProps()} />);
      expect(screen.getByTestId('input-url')).toBeInTheDocument();
    });

    it('renders the Priority input', () => {
      render(<EPG {...defaultProps()} />);
      expect(screen.getByTestId('number-priority')).toBeInTheDocument();
    });

    it('renders the ScheduleInput component', () => {
      render(<EPG {...defaultProps()} />);
      expect(screen.getByTestId('schedule-input')).toBeInTheDocument();
    });

    it('renders a cancel/close button', () => {
      render(<EPG {...defaultProps()} />);
      expect(
        screen.getByRole('button', { name: /cancel|close/i })
      ).toBeInTheDocument();
    });
  });

  // ── Form initialization ────────────────────────────────────────────────────

  describe('form initialization', () => {
    it('calls setValues with epg fields when epg prop is provided', () => {
      const epg = makeEPG();
      const mockSetValues = vi.fn();
      vi.mocked(useForm).mockReturnValueOnce({
        key: vi.fn(),
        getValues: vi.fn(() => ({ ...epg, cron_expression: '' })),
        setValues: mockSetValues,
        setFieldValue: vi.fn((field, value) => {
          epg[field] = value;
        }),
        reset: vi.fn(),
        submitting: false,
        onSubmit: vi.fn((h) => (e) => {
          e?.preventDefault?.();
          h({ ...epg });
        }),
        getInputProps: vi.fn((field) => ({
          value: epg[field] ?? '',
          onChange: vi.fn(),
          error: null,
        })),
      });

      render(<EPG {...defaultProps({ epg })} />);
      expect(mockSetValues).toHaveBeenCalledWith(
        expect.objectContaining({ name: 'Test EPG', source_type: 'xmltv' })
      );
    });

    it('does not call setValues when epg prop is null', () => {
      const mockSetValues = vi.fn();
      vi.mocked(useForm).mockReturnValueOnce({
        key: vi.fn(),
        getValues: vi.fn(() => ({})),
        setValues: mockSetValues,
        setFieldValue: vi.fn(() => {}),
        reset: vi.fn(),
        submitting: false,
        onSubmit: vi.fn((h) => (e) => {
          e?.preventDefault?.();
          h({});
        }),
        getInputProps: vi.fn(() => ({
          value: '',
          onChange: vi.fn(),
          error: null,
        })),
      });

      render(<EPG {...defaultProps({ epg: null })} />);
      expect(mockSetValues).not.toHaveBeenCalled();
    });

    it('sets scheduleType to "cron" when epg has a cron_expression', () => {
      const epg = makeEPG({
        cron_expression: '0 */6 * * *',
        refresh_interval: 0,
      });
      render(<EPG {...defaultProps({ epg })} />);
      expect(screen.getByTestId('schedule-type-value')).toHaveTextContent(
        'cron'
      );
    });

    it('sets scheduleType to "interval" when epg has no cron_expression', () => {
      const epg = makeEPG({ cron_expression: '', refresh_interval: 12 });
      render(<EPG {...defaultProps({ epg })} />);
      expect(screen.getByTestId('schedule-type-value')).toHaveTextContent(
        'interval'
      );
    });
  });

  // ── Source type ────────────────────────────────────────────────────────────

  describe('source type', () => {
    it('defaults source type to "xmltv"', () => {
      render(<EPG {...defaultProps()} />);
      const select = screen.getByTestId('select-source-type');
      expect(select).toHaveValue('xmltv');
    });

    it('shows URL input when source type is xmltv', () => {
      render(<EPG {...defaultProps()} />);
      expect(screen.getByTestId('input-url')).toBeInTheDocument();
    });

    it('hides API key input when source type is xmltv', () => {
      render(<EPG {...defaultProps()} />);
      expect(screen.queryByTestId('input-api-key')).not.toBeInTheDocument();
    });

    it('shows API key input when source type requires it', () => {
      const epg = makeEPG({ source_type: 'schedules_direct' });
      render(<EPG {...defaultProps({ epg })} />);
      expect(screen.getByTestId('input-api-key')).toBeInTheDocument();
    });
  });

  // ── Schedule type toggling ─────────────────────────────────────────────────

  describe('schedule type toggling', () => {
    it('scheduleType starts as "interval" for new EPG', () => {
      render(<EPG {...defaultProps()} />);
      expect(screen.getByTestId('schedule-type-value')).toHaveTextContent(
        'interval'
      );
    });

    it('updates scheduleType to "cron" when ScheduleInput fires onScheduleTypeChange', () => {
      render(<EPG {...defaultProps()} />);
      fireEvent.click(screen.getByTestId('set-cron'));
      expect(screen.getByTestId('schedule-type-value')).toHaveTextContent(
        'cron'
      );
    });

    it('updates scheduleType back to "interval" from cron', () => {
      render(<EPG {...defaultProps()} />);
      fireEvent.click(screen.getByTestId('set-cron'));
      fireEvent.click(screen.getByTestId('set-interval'));
      expect(screen.getByTestId('schedule-type-value')).toHaveTextContent(
        'interval'
      );
    });
  });

  // ── Form submission — add ──────────────────────────────────────────────────

  describe('form submission (add)', () => {
    it('calls addEPG when submitting a new EPG', async () => {
      render(<EPG {...defaultProps()} />);
      fireEvent.click(screen.getByText('Create EPG Source'));
      await waitFor(() => {
        expect(DummyEpgUtils.addEPG).toHaveBeenCalled();
      });
    });

    it('does not call updateEPG when adding a new EPG', async () => {
      render(<EPG {...defaultProps()} />);
      fireEvent.click(screen.getByText('Create EPG Source'));
      await waitFor(() => {
        expect(DummyEpgUtils.updateEPG).not.toHaveBeenCalled();
      });
    });

    it('calls onClose after successful add', async () => {
      const onClose = vi.fn();
      render(<EPG {...defaultProps({ onClose })} />);
      fireEvent.click(screen.getByText('Create EPG Source'));
      await waitFor(() => {
        expect(onClose).toHaveBeenCalled();
      });
    });

    it('clears cron_expression when schedule type is interval on submit', async () => {
      let capturedValues;
      vi.mocked(DummyEpgUtils.addEPG).mockImplementation((vals) => {
        capturedValues = vals;
        return Promise.resolve();
      });
      render(<EPG {...defaultProps()} />);
      fireEvent.click(screen.getByTestId('set-interval'));
      fireEvent.click(screen.getByText('Create EPG Source'));
      await waitFor(() => {
        expect(capturedValues?.cron_expression ?? '').toBe('');
      });
    });
  });

  // ── Form submission — update ───────────────────────────────────────────────

  describe('form submission (update)', () => {
    it('calls updateEPG when submitting an existing EPG', async () => {
      const epg = makeEPG();
      render(<EPG {...defaultProps({ epg })} />);
      fireEvent.click(screen.getByText('Update EPG Source'));
      await waitFor(() => {
        expect(DummyEpgUtils.updateEPG).toHaveBeenCalled();
      });
    });

    it('does not call addEPG when epg.id is present', async () => {
      const epg = makeEPG();
      render(<EPG {...defaultProps({ epg })} />);

      fireEvent.click(screen.getByText('Update EPG Source'));

      await waitFor(() => {
        expect(DummyEpgUtils.addEPG).not.toHaveBeenCalled();
      });
    });

    it('clears refresh_interval when schedule type is cron on submit', async () => {
      const epg = makeEPG({
        cron_expression: '0 * * * *',
        refresh_interval: 24,
      });
      vi.mocked(useForm).mockReturnValue({
        key: vi.fn(),
        getValues: vi.fn(() => ({ ...epg })),
        setValues: vi.fn((v) => Object.assign(epg, v)),
        setFieldValue: vi.fn((field, value) => {
          epg[field] = value;
        }),
        reset: vi.fn(),
        submitting: false,
        onSubmit: vi.fn((h) => (e) => {
          e?.preventDefault?.();
          h({ ...epg });
        }),
        getInputProps: vi.fn((field) => ({
          value: epg[field] ?? '',
          onChange: vi.fn(),
          error: null,
        })),
      });
      render(<EPG {...defaultProps({ epg })} />);
      fireEvent.click(screen.getByText('Update EPG Source'));

      await waitFor(() => {
        const [values] = vi.mocked(DummyEpgUtils.updateEPG).mock.calls[0]; // first arg
        expect(values.refresh_interval).toBe(0);
        expect(values.cron_expression).toBe('0 * * * *');
      });
    });

    it('clears cron_expression when schedule type is interval on submit', async () => {
      const epg = makeEPG({ cron_expression: '', refresh_interval: 12 });
      vi.mocked(useForm).mockReturnValue({
        key: vi.fn(),
        getValues: vi.fn(() => ({ ...epg })),
        setValues: vi.fn((v) => Object.assign(epg, v)),
        setFieldValue: vi.fn((field, value) => {
          epg[field] = value;
        }),
        reset: vi.fn(),
        submitting: false,
        onSubmit: vi.fn((h) => (e) => {
          e?.preventDefault?.();
          h({ ...epg });
        }),
        getInputProps: vi.fn((field) => ({
          value: epg[field] ?? '',
          onChange: vi.fn(),
          error: null,
        })),
      });
      render(<EPG {...defaultProps({ epg })} />);
      fireEvent.click(screen.getByText('Update EPG Source'));

      await waitFor(() => {
        const [values] = vi.mocked(DummyEpgUtils.updateEPG).mock.calls[0];
        expect(values.cron_expression).toBe('');
        expect(values.refresh_interval).toBe(12);
      });
    });

    it('calls onClose after successful update', async () => {
      const onClose = vi.fn();
      const epg = makeEPG();
      render(<EPG {...defaultProps({ epg, onClose })} />);

      fireEvent.click(screen.getByText('Update EPG Source'));

      await waitFor(() => {
        expect(onClose).toHaveBeenCalled();
      });
    });
  });

  // ── Modal close ────────────────────────────────────────────────────────────

  describe('modal close', () => {
    it('calls onClose when the modal close button is clicked', () => {
      const onClose = vi.fn();
      render(<EPG {...defaultProps({ onClose })} />);
      fireEvent.click(screen.getByTestId('modal-close'));
      expect(onClose).toHaveBeenCalled();
    });

    it('calls onClose when the Cancel button is clicked', () => {
      const onClose = vi.fn();
      render(<EPG {...defaultProps({ onClose })} />);
      fireEvent.click(screen.getByRole('button', { name: /cancel|close/i }));
      expect(onClose).toHaveBeenCalled();
    });

    it('resets the form on close', async () => {
      const mockReset = vi.fn();
      vi.mocked(useForm).mockReturnValueOnce({
        key: vi.fn(),
        getValues: vi.fn(() => ({})),
        setValues: vi.fn(),
        setFieldValue: vi.fn(() => {}),
        reset: mockReset,
        submitting: false,
        onSubmit: vi.fn((h) => (e) => {
          e?.preventDefault?.();
          h({});
        }),
        getInputProps: vi.fn(() => ({
          value: '',
          onChange: vi.fn(),
          error: null,
        })),
      });
      render(<EPG {...defaultProps()} />);
      fireEvent.click(screen.getByText('Create EPG Source'));
      await waitFor(() => {
        expect(mockReset).toHaveBeenCalled();
      });
    });
  });

  // ── Active checkbox ────────────────────────────────────────────────────────

  describe('active checkbox', () => {
    it('renders the Active checkbox', () => {
      render(<EPG {...defaultProps()} />);
      expect(
        screen.getByTestId('checkbox-enable-this-epg-source')
      ).toBeInTheDocument();
    });
  });
});
