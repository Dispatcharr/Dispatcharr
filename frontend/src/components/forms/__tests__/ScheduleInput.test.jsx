import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import ScheduleInput from '../ScheduleInput';

// ── Mantine core ───────────────────────────────────────────────────────────────
vi.mock('@mantine/core', () => ({
  TextInput: ({
    label,
    placeholder,
    description,
    value,
    onChange,
    error,
    disabled,
  }) => (
    <div>
      <label>{typeof label === 'string' ? label : 'Cron Expression'}</label>
      <input
        data-testid="textinput-cron"
        placeholder={placeholder}
        value={value}
        onChange={onChange}
        disabled={disabled}
        aria-invalid={!!error}
      />
      {description && <span data-testid="cron-description">{description}</span>}
      {error && <span data-testid="cron-error">{error}</span>}
    </div>
  ),
  NumberInput: ({ label, description, value, onChange, min, disabled }) => (
    <div>
      <label>{label}</label>
      <input
        data-testid="numberinput-interval"
        type="number"
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        min={min}
        disabled={disabled}
      />
      {description && (
        <span data-testid="interval-description">{description}</span>
      )}
    </div>
  ),
  Anchor: ({ children, onClick }) => (
    <a
      data-testid={`anchor-${String(children).replace(/\s+/g, '-').toLowerCase()}`}
      onClick={onClick}
      href="#"
    >
      {children}
    </a>
  ),
  Stack: ({ children }) => <div>{children}</div>,
  Text: ({ children }) => <span>{children}</span>,
  Code: ({ children }) => <code>{children}</code>,
  Group: ({ children }) => <div>{children}</div>,
  Popover: ({ children }) => <div>{children}</div>,
  PopoverTarget: ({ children }) => <div>{children}</div>,
  PopoverDropdown: ({ children }) => (
    <div data-testid="popover-dropdown">{children}</div>
  ),
  ActionIcon: ({ children, onClick }) => (
    <button data-testid="action-icon-info" onClick={onClick}>
      {children}
    </button>
  ),
}));

// ── lucide-react ───────────────────────────────────────────────────────────────
vi.mock('lucide-react', () => ({
  Info: () => <svg data-testid="icon-info" />,
}));

// ── cronUtils ─────────────────────────────────────────────────────────────────
vi.mock('../../../utils/cronUtils', () => ({
  validateCronExpression: vi.fn(),
}));

// ── CronBuilder ────────────────────────────────────────────────────────────────
vi.mock('../CronBuilder', () => ({
  default: ({ opened, onClose, onApply, currentValue }) =>
    opened ? (
      <div data-testid="cron-builder">
        <span data-testid="cron-builder-value">{currentValue}</span>
        <button
          data-testid="cron-builder-apply"
          onClick={() => onApply('0 3 * * *')}
        >
          Apply
        </button>
        <button data-testid="cron-builder-close" onClick={onClose}>
          Close
        </button>
      </div>
    ) : null,
}));

// ──────────────────────────────────────────────────────────────────────────────
import { validateCronExpression } from '../../../utils/cronUtils';

const defaultIntervalProps = () => ({
  scheduleType: 'interval',
  onScheduleTypeChange: vi.fn(),
  intervalValue: 6,
  onIntervalChange: vi.fn(),
  cronValue: '',
  onCronChange: vi.fn(),
});

const defaultCronProps = () => ({
  scheduleType: 'cron',
  onScheduleTypeChange: vi.fn(),
  cronValue: '0 3 * * *',
  onCronChange: vi.fn(),
  intervalValue: 0,
  onIntervalChange: vi.fn(),
});

describe('ScheduleInput', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(validateCronExpression).mockReturnValue({ valid: true });
  });

  // ── Interval mode ────────────────────────────────────────────────────────

  describe('interval mode', () => {
    it('renders NumberInput in interval mode', () => {
      render(<ScheduleInput {...defaultIntervalProps()} />);
      expect(screen.getByTestId('numberinput-interval')).toBeInTheDocument();
    });

    it('displays the intervalValue', () => {
      render(<ScheduleInput {...defaultIntervalProps()} />);
      expect(screen.getByTestId('numberinput-interval')).toHaveValue(6);
    });

    it('renders default interval label', () => {
      render(<ScheduleInput {...defaultIntervalProps()} />);
      expect(screen.getByText('Refresh Interval (hours)')).toBeInTheDocument();
    });

    it('renders custom intervalLabel', () => {
      render(
        <ScheduleInput
          {...defaultIntervalProps()}
          intervalLabel="My Custom Label"
        />
      );
      expect(screen.getByText('My Custom Label')).toBeInTheDocument();
    });

    it('renders default interval description', () => {
      render(<ScheduleInput {...defaultIntervalProps()} />);
      expect(screen.getByTestId('interval-description')).toHaveTextContent(
        'How often to refresh (0 to disable)'
      );
    });

    it('calls onIntervalChange when value changes', () => {
      const props = defaultIntervalProps();
      render(<ScheduleInput {...props} />);
      fireEvent.change(screen.getByTestId('numberinput-interval'), {
        target: { value: '12' },
      });
      expect(props.onIntervalChange).toHaveBeenCalledWith(12);
    });

    it('shows "Use cron schedule" link in interval mode', () => {
      render(<ScheduleInput {...defaultIntervalProps()} />);
      expect(
        screen.getByTestId('anchor-use-cron-schedule')
      ).toBeInTheDocument();
    });

    it('calls onScheduleTypeChange("cron") when "Use cron schedule" is clicked', () => {
      const props = defaultIntervalProps();
      render(<ScheduleInput {...props} />);
      fireEvent.click(screen.getByTestId('anchor-use-cron-schedule'));
      expect(props.onScheduleTypeChange).toHaveBeenCalledWith('cron');
    });

    it('does not show cron switch link when disabled', () => {
      render(<ScheduleInput {...defaultIntervalProps()} disabled />);
      expect(
        screen.queryByTestId('anchor-use-cron-schedule')
      ).not.toBeInTheDocument();
    });

    it('disables the NumberInput when disabled prop is true', () => {
      render(<ScheduleInput {...defaultIntervalProps()} disabled />);
      expect(screen.getByTestId('numberinput-interval')).toBeDisabled();
    });

    it('renders custom switchToCronLabel', () => {
      render(
        <ScheduleInput
          {...defaultIntervalProps()}
          switchToCronLabel="Use custom cron schedule"
        />
      );
      expect(screen.getByText('Use custom cron schedule')).toBeInTheDocument();
    });
  });

  // ── Children (simple) mode ────────────────────────────────────────────────

  describe('children (simple) mode', () => {
    it('renders children instead of NumberInput', () => {
      render(
        <ScheduleInput {...defaultIntervalProps()}>
          <div data-testid="custom-child">Custom content</div>
        </ScheduleInput>
      );
      expect(screen.getByTestId('custom-child')).toBeInTheDocument();
      expect(
        screen.queryByTestId('numberinput-interval')
      ).not.toBeInTheDocument();
    });

    it('shows cron toggle link below children', () => {
      render(
        <ScheduleInput {...defaultIntervalProps()}>
          <div>Child</div>
        </ScheduleInput>
      );
      expect(
        screen.getByTestId('anchor-use-cron-schedule')
      ).toBeInTheDocument();
    });

    it('does not show cron link when disabled with children', () => {
      render(
        <ScheduleInput {...defaultIntervalProps()} disabled>
          <div>Child</div>
        </ScheduleInput>
      );
      expect(
        screen.queryByTestId('anchor-use-cron-schedule')
      ).not.toBeInTheDocument();
    });
  });

  // ── Cron mode ─────────────────────────────────────────────────────────────

  describe('cron mode', () => {
    it('renders TextInput in cron mode', () => {
      render(<ScheduleInput {...defaultCronProps()} />);
      expect(screen.getByTestId('textinput-cron')).toBeInTheDocument();
    });

    it('displays the cronValue', () => {
      render(<ScheduleInput {...defaultCronProps()} />);
      expect(screen.getByTestId('textinput-cron')).toHaveValue('0 3 * * *');
    });

    it('shows "Use interval schedule" link in cron mode', () => {
      render(<ScheduleInput {...defaultCronProps()} />);
      expect(
        screen.getByTestId('anchor-use-interval-schedule')
      ).toBeInTheDocument();
    });

    it('shows "Open Cron Builder" link', () => {
      render(<ScheduleInput {...defaultCronProps()} />);
      expect(
        screen.getByTestId('anchor-open-cron-builder')
      ).toBeInTheDocument();
    });

    it('calls onScheduleTypeChange("interval") and onCronChange("") when switching to interval', () => {
      const props = defaultCronProps();
      render(<ScheduleInput {...props} />);
      fireEvent.click(screen.getByTestId('anchor-use-interval-schedule'));
      expect(props.onScheduleTypeChange).toHaveBeenCalledWith('interval');
      expect(props.onCronChange).toHaveBeenCalledWith('');
    });

    it('calls onCronChange when cron input changes', () => {
      const props = defaultCronProps();
      render(<ScheduleInput {...props} />);
      fireEvent.change(screen.getByTestId('textinput-cron'), {
        target: { value: '0 5 * * *' },
      });
      expect(props.onCronChange).toHaveBeenCalledWith('0 5 * * *');
    });

    it('disables the TextInput when disabled prop is true', () => {
      render(<ScheduleInput {...defaultCronProps()} disabled />);
      expect(screen.getByTestId('textinput-cron')).toBeDisabled();
    });

    it('does not show cron links when disabled', () => {
      render(<ScheduleInput {...defaultCronProps()} disabled />);
      expect(
        screen.queryByTestId('anchor-use-interval-schedule')
      ).not.toBeInTheDocument();
      expect(
        screen.queryByTestId('anchor-open-cron-builder')
      ).not.toBeInTheDocument();
    });

    it('renders custom switchToIntervalLabel', () => {
      render(
        <ScheduleInput
          {...defaultCronProps()}
          switchToIntervalLabel="Use simple schedule"
        />
      );
      expect(screen.getByText('Use simple schedule')).toBeInTheDocument();
    });
  });

  // ── Cron validation ───────────────────────────────────────────────────────

  describe('cron validation', () => {
    it('shows no error when cron is valid', () => {
      vi.mocked(validateCronExpression).mockReturnValue({ valid: true });
      render(<ScheduleInput {...defaultCronProps()} />);
      expect(screen.queryByTestId('cron-error')).not.toBeInTheDocument();
    });

    it('shows error message when cron is invalid', async () => {
      vi.mocked(validateCronExpression).mockReturnValue({
        valid: false,
        error: 'Invalid cron expression',
      });
      render(<ScheduleInput {...defaultCronProps()} cronValue="bad cron" />);
      await waitFor(() => {
        expect(screen.getByTestId('cron-error')).toHaveTextContent(
          'Invalid cron expression'
        );
      });
    });

    it('clears error when cron input is cleared', async () => {
      vi.mocked(validateCronExpression).mockReturnValue({ valid: true });
      const props = { ...defaultCronProps(), cronValue: '' };
      render(<ScheduleInput {...props} />);
      await waitFor(() => {
        expect(screen.queryByTestId('cron-error')).not.toBeInTheDocument();
      });
    });

    it('calls validateCronExpression on cron value change', () => {
      vi.mocked(validateCronExpression).mockReturnValue({ valid: true });
      const props = defaultCronProps();
      render(<ScheduleInput {...props} />);
      fireEvent.change(screen.getByTestId('textinput-cron'), {
        target: { value: '0 6 * * 1' },
      });
      expect(validateCronExpression).toHaveBeenCalledWith('0 6 * * 1');
    });

    it('does not call validateCronExpression in interval mode', () => {
      render(<ScheduleInput {...defaultIntervalProps()} />);
      expect(validateCronExpression).not.toHaveBeenCalled();
    });
  });

  // ── Cron Builder ──────────────────────────────────────────────────────────

  describe('CronBuilder', () => {
    it('CronBuilder is not visible initially', () => {
      render(<ScheduleInput {...defaultCronProps()} />);
      expect(screen.queryByTestId('cron-builder')).not.toBeInTheDocument();
    });

    it('opens CronBuilder when "Open Cron Builder" is clicked', () => {
      render(<ScheduleInput {...defaultCronProps()} />);
      fireEvent.click(screen.getByTestId('anchor-open-cron-builder'));
      expect(screen.getByTestId('cron-builder')).toBeInTheDocument();
    });

    it('passes current cronValue to CronBuilder', () => {
      render(<ScheduleInput {...defaultCronProps()} cronValue="0 4 * * *" />);
      fireEvent.click(screen.getByTestId('anchor-open-cron-builder'));
      expect(screen.getByTestId('cron-builder-value')).toHaveTextContent(
        '0 4 * * *'
      );
    });

    it('closes CronBuilder when onClose is triggered', () => {
      render(<ScheduleInput {...defaultCronProps()} />);
      fireEvent.click(screen.getByTestId('anchor-open-cron-builder'));
      fireEvent.click(screen.getByTestId('cron-builder-close'));
      expect(screen.queryByTestId('cron-builder')).not.toBeInTheDocument();
    });

    it('calls onCronChange with applied value from CronBuilder', () => {
      vi.mocked(validateCronExpression).mockReturnValue({ valid: true });
      const props = defaultCronProps();
      render(<ScheduleInput {...props} />);
      fireEvent.click(screen.getByTestId('anchor-open-cron-builder'));
      fireEvent.click(screen.getByTestId('cron-builder-apply'));
      expect(props.onCronChange).toHaveBeenCalledWith('0 3 * * *');
    });
  });

  // ── Default props ─────────────────────────────────────────────────────────

  describe('default props', () => {
    it('defaults to interval mode when scheduleType is not provided', () => {
      render(
        <ScheduleInput
          onScheduleTypeChange={vi.fn()}
          onIntervalChange={vi.fn()}
          onCronChange={vi.fn()}
        />
      );
      expect(screen.getByTestId('numberinput-interval')).toBeInTheDocument();
    });

    it('defaults intervalValue to 0', () => {
      render(
        <ScheduleInput
          onScheduleTypeChange={vi.fn()}
          onIntervalChange={vi.fn()}
          onCronChange={vi.fn()}
        />
      );
      expect(screen.getByTestId('numberinput-interval')).toHaveValue(0);
    });
  });
});
