import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { Modal } from '@mantine/core';

Modal.Stack = ({ children }) => <>{children}</>;

// ── Utility mocks ──────────────────────────────────────────────────────────────
global.fetch = vi.fn().mockResolvedValue({
  json: () => Promise.resolve({}),
});

vi.mock('../../../api.js', () => ({
  default: {
    getSDLineups: vi.fn().mockResolvedValue([]),
    addSDLineup: vi.fn().mockResolvedValue({ success: true }),
    deleteSDLineup: vi.fn().mockResolvedValue({ success: true }),
    searchSDLineups: vi.fn().mockResolvedValue([]),
    updateSDSettings: vi.fn().mockResolvedValue({}),
  },
}));

vi.mock('../../../utils/notificationUtils.js', () => ({
  showNotification: vi.fn(),
  hideNotification: vi.fn(),
}));

vi.mock('../../../utils/forms/DummyEpgUtils.js', () => ({
  addEPG: vi.fn(),
  updateEPG: vi.fn(),
}));

vi.mock('../../ConfirmationDialog.jsx', () => ({ default: () => null }));

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
      resetDirty: vi.fn(),
      isDirty: () => false,
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
  useModalStackContext: () => null,
  SimpleGrid: ({ children }) => <div>{children}</div>,
  Paper: ({ children }) => <div>{children}</div>,
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
  Alert: ({ children, title, color, icon }) => (
    <div data-testid="alert" data-color={color}>
      {title && <div data-testid="alert-title">{title}</div>}
      {children}
    </div>
  ),
  Select: ({ label, value, onChange, data, placeholder }) => (
    <select
      aria-label={label}
      data-testid={`select-${label?.toString().toLowerCase().replace(/\s+/g, '-')}`}
      value={value ?? ''}
      onChange={(e) => onChange?.(e.target.value)}
    >
      <option value="">{placeholder}</option>
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
  Loader: ({ size }) => <div data-testid="loader" data-size={size} />,
  Badge: ({ children, color }) => (
    <span data-testid="badge" data-color={color}>
      {children}
    </span>
  ),
  ScrollArea: ({ children }) => <div data-testid="scroll-area">{children}</div>,
  Table: ({ children }) => <table>{children}</table>,
  Tooltip: ({ children }) => <div>{children}</div>,
  Switch: ({ label, checked, onChange, disabled, description }) => (
    <label>
      <input
        type="checkbox"
        data-testid={`switch-${label?.toString().toLowerCase().replace(/\s+/g, '-')}`}
        checked={checked ?? false}
        onChange={(e) => onChange?.(e)}
        disabled={disabled}
      />
      {label}
    </label>
  ),
  UnstyledButton: ({ children, onClick, ...props }) => (
    <button type="button" onClick={onClick} {...props}>
      {children}
    </button>
  ),
  Alert: ({ children, title, color, icon }) => (
    <div data-testid="alert" data-color={color}>
      <strong>{title}</strong>
      {children}
    </div>
  ),
  Stack: ({ children, gap, role, 'aria-label': ariaLabel }) => (
    <div data-testid="stack" role={role} aria-label={ariaLabel}>
      {children}
    </div>
  ),
  Text: ({ children, ...props }) => <span>{children}</span>,
  TextInput: ({ label, value, onChange, placeholder, ...props }) => (
    <input
      type="text"
      aria-label={label}
      data-testid={`input-${label?.toString().toLowerCase().replace(/\s+/g, '-')}`}
      value={value || ''}
      onChange={onChange}
      placeholder={placeholder}
    />
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
    vi.mocked(DummyEpgUtils.updateEPG).mockResolvedValue({ id: 1 });
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
      expect(
        screen.getByRole('button', { name: 'Create' })
      ).toBeInTheDocument();
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
        resetDirty: vi.fn(),
        isDirty: () => false,
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
        resetDirty: vi.fn(),
        isDirty: () => false,
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

    it('shows username and password inputs when source type is schedules_direct', () => {
      const epg = makeEPG({ source_type: 'schedules_direct' });
      render(<EPG {...defaultProps({ epg })} />);
      expect(screen.getByTestId('input-username')).toBeInTheDocument();
      expect(screen.getByTestId('input-password')).toBeInTheDocument();
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
      fireEvent.click(screen.getByRole('button', { name: 'Create' }));
      await waitFor(() => {
        expect(DummyEpgUtils.addEPG).toHaveBeenCalled();
      });
    });

    it('does not call updateEPG when adding a new EPG', async () => {
      render(<EPG {...defaultProps()} />);
      fireEvent.click(screen.getByRole('button', { name: 'Create' }));
      await waitFor(() => {
        expect(DummyEpgUtils.updateEPG).not.toHaveBeenCalled();
      });
    });

    it('keeps a failed add open rather than discarding the draft', async () => {
      const onClose = vi.fn();
      render(<EPG {...defaultProps({ onClose })} />);
      fireEvent.click(screen.getByRole('button', { name: 'Create' }));
      await waitFor(() => expect(DummyEpgUtils.addEPG).toHaveBeenCalled());
      expect(onClose).not.toHaveBeenCalled();
    });

    it('clears cron_expression when schedule type is interval on submit', async () => {
      let capturedValues;
      vi.mocked(DummyEpgUtils.addEPG).mockImplementation((vals) => {
        capturedValues = vals;
        return Promise.resolve();
      });
      render(<EPG {...defaultProps()} />);
      fireEvent.click(screen.getByTestId('set-interval'));
      fireEvent.click(screen.getByRole('button', { name: 'Create' }));
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
      expect(DummyEpgUtils.updateEPG.mock.calls[0][0]).not.toHaveProperty(
        'is_active'
      );
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
        resetDirty: vi.fn(),
        isDirty: () => false,
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
        resetDirty: vi.fn(),
        isDirty: () => false,
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

    it('resets the form on an unchanged close', async () => {
      const mockReset = vi.fn();
      vi.mocked(useForm).mockReturnValueOnce({
        key: vi.fn(),
        getValues: vi.fn(() => ({})),
        setValues: vi.fn(),
        setFieldValue: vi.fn(() => {}),
        reset: mockReset,
        resetDirty: vi.fn(),
        isDirty: () => false,
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
      fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
      await waitFor(() => {
        expect(mockReset).toHaveBeenCalled();
      });
    });
  });

  // ── Active checkbox ────────────────────────────────────────────────────────

  describe('overview-controlled enabled state', () => {
    it.each([null, makeEPG({ is_active: false })])(
      'does not duplicate the enabled control (epg=%j)',
      (epg) => {
        render(<EPG {...defaultProps({ epg })} />);
        expect(
          screen.queryByTestId('checkbox-enable-this-epg-source')
        ).not.toBeInTheDocument();
      }
    );
    it('keeps URL with the source and the schedule in Settings', () => {
      render(<EPG {...defaultProps()} />);
      expect(
        screen.getByRole('group', { name: 'EPG source settings' })
      ).toContainElement(screen.getByTestId('input-url'));
      expect(
        screen.getByRole('group', { name: 'EPG settings' })
      ).toContainElement(screen.getByTestId('schedule-input'));
      expect(
        screen.getByRole('group', { name: 'EPG settings' })
      ).toContainElement(screen.getByTestId('number-priority'));
      expect(
        screen.getByRole('group', { name: 'EPG source settings' })
      ).not.toContainElement(screen.getByTestId('number-priority'));
      expect(screen.getByText('Settings')).toBeInTheDocument();
      expect(
        screen.queryByText('Refresh', { exact: true })
      ).not.toBeInTheDocument();
    });
    it.each(['xmltv', 'schedules_direct'])(
      'keeps auto-apply logos with Settings for an existing %s source',
      (source_type) => {
        render(<EPG {...defaultProps({ epg: makeEPG({ source_type }) })} />);
        const logos = screen.getByText('Auto-Apply EPG Logos to Channels');
        expect(
          screen.getByRole('group', { name: 'EPG settings' })
        ).toContainElement(logos);
        expect(
          screen.getByRole('group', { name: 'EPG source settings' })
        ).not.toContainElement(logos);
      }
    );
  });
});
