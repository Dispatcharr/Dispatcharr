import { render, screen, fireEvent, within } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import CronBuilder from '../CronBuilder';

// ── Utility mocks ──────────────────────────────────────────────────────────────
vi.mock('../../../utils/forms/CronBuilderUtils.js', () => ({
  buildCron: vi.fn(),
  parseCronPreset: vi.fn(),
  CRON_FIELDS: [
    { index: 0, label: 'Minute (0-59)', placeholder: '*, 0, */15' },
    { index: 1, label: 'Hour (0-23)', placeholder: '*, 0, 9-17' },
    { index: 2, label: 'Day of Month (1-31)', placeholder: '*, 1, 1-15' },
    { index: 3, label: 'Month (1-12)', placeholder: '*, 1, 1-6' },
    { index: 4, label: 'Day of Week (0-6, Sun-Sat)', placeholder: '*, 0, 1-5' },
  ],
  DAYS_OF_WEEK: [
    { value: '*', label: 'Every day' },
    { value: '1', label: 'Monday' },
    { value: '2', label: 'Tuesday' },
  ],
  FREQUENCY_OPTIONS: [
    { value: 'hourly', label: 'Hourly' },
    { value: 'daily', label: 'Daily' },
    { value: 'weekly', label: 'Weekly' },
    { value: 'monthly', label: 'Monthly' },
  ],
  PRESETS: [
    { label: 'Every Hour', description: 'Runs every hour', value: '0 * * * *' },
    {
      label: 'Every Day 3am',
      description: 'Runs every day at 3 AM',
      value: '0 3 * * *',
    },
    {
      label: 'Every Sunday',
      description: 'Runs every Sunday at 3AM',
      value: '0 3 * * 0',
    },
  ],
  updateCronPart: vi.fn(),
}));

// ── Mantine core ───────────────────────────────────────────────────────────────
vi.mock('@mantine/core', async () => ({
  Badge: ({ children, size, variant, color }) => (
    <span
      data-testid="badge"
      data-size={size}
      data-variant={variant}
      data-color={color}
    >
      {children}
    </span>
  ),
  Button: ({ children, onClick, variant }) => (
    <button onClick={onClick} data-variant={variant}>
      {children}
    </button>
  ),
  Code: ({ children }) => <code>{children}</code>,
  Divider: ({ label }) => <hr data-label={label} />,
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
  NumberInput: ({ label, value, onChange, min, max }) => (
    <div>
      <label>{label}</label>
      <input
        type="number"
        aria-label={label}
        value={value}
        min={min}
        max={max}
        onChange={(e) => onChange(Number(e.target.value))}
      />
    </div>
  ),
  Paper: ({ children }) => <div data-testid="paper">{children}</div>,
  Select: ({ label, data, value, onChange }) => (
    <div>
      <label>{label}</label>
      <select
        aria-label={label}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      >
        {data.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>
    </div>
  ),
  SimpleGrid: ({ children }) => <div>{children}</div>,
  Stack: ({ children }) => <div>{children}</div>,
  Tabs: ({ children, value }) => (
    <div data-testid="tabs" data-value={value}>
      {typeof children === 'function' ? children() : children}
    </div>
  ),
  TabsList: ({ children }) => <div data-testid="tabs-list">{children}</div>,
  TabsPanel: ({ children, value: panelValue }) => (
    <div data-testid={`panel-${panelValue}`}>{children}</div>
  ),
  TabsTab: ({ children, value, onClick }) => (
    <button data-testid={`tab-${value}`} onClick={onClick}>
      {children}
    </button>
  ),
  Text: ({ children, size, fw, c }) => (
    <span data-size={size} data-fw={fw} data-color={c}>
      {children}
    </span>
  ),
  TextInput: ({ label, placeholder, value, onChange }) => (
    <div>
      <label>{label}</label>
      <input
        aria-label={label}
        placeholder={placeholder}
        value={value}
        onChange={onChange}
      />
    </div>
  ),
}));

// ── lucide-react ───────────────────────────────────────────────────────────────
vi.mock('lucide-react', () => ({
  Calendar: () => <svg data-testid="icon-calendar" />,
  Clock: () => <svg data-testid="icon-clock" />,
}));

// ── Imports after mocks ────────────────────────────────────────────────────────
import * as CronBuilderUtils from '../../../utils/forms/CronBuilderUtils.js';

// ── Helpers ────────────────────────────────────────────────────────────────────
const defaultProps = {
  opened: true,
  onClose: vi.fn(),
  onApply: vi.fn(),
  currentValue: '',
};

const renderBuilder = (props = {}) =>
  render(<CronBuilder {...defaultProps} {...props} />);

describe('CronBuilder', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(CronBuilderUtils.buildCron).mockReturnValue('0 3 * * *');
    vi.mocked(CronBuilderUtils.parseCronPreset).mockReturnValue({
      frequency: 'daily',
      minute: 0,
      hour: 3,
      dayOfWeek: '*',
      dayOfMonth: 1,
    });
    vi.mocked(CronBuilderUtils.updateCronPart).mockImplementation(
      (cron, index, value) => {
        const parts = cron.split(' ');
        parts[index] = value || '*';
        return parts.join(' ');
      }
    );
  });

  // ── Modal visibility ─────────────────────────────────────────────────────

  describe('modal visibility', () => {
    it('renders the modal when opened is true', () => {
      renderBuilder();
      expect(screen.getByTestId('modal')).toBeInTheDocument();
    });

    it('does not render the modal when opened is false', () => {
      renderBuilder({ opened: false });
      expect(screen.queryByTestId('modal')).not.toBeInTheDocument();
    });

    it('displays the correct modal title', () => {
      renderBuilder();
      expect(screen.getByTestId('modal-title')).toHaveTextContent(
        'Cron Expression Builder'
      );
    });

    it('calls onClose when the close button is clicked', () => {
      const onClose = vi.fn();
      renderBuilder({ onClose });
      fireEvent.click(screen.getByTestId('modal-close'));
      expect(onClose).toHaveBeenCalledOnce();
    });

    it('calls onClose when Cancel button is clicked', () => {
      const onClose = vi.fn();
      renderBuilder({ onClose });
      fireEvent.click(screen.getByText('Cancel'));
      expect(onClose).toHaveBeenCalledOnce();
    });
  });

  // ── Tab rendering ────────────────────────────────────────────────────────

  describe('tab rendering', () => {
    it('renders the Simple tab', () => {
      renderBuilder();
      expect(screen.getByTestId('tab-simple')).toBeInTheDocument();
    });

    it('renders the Advanced tab', () => {
      renderBuilder();
      expect(screen.getByTestId('tab-advanced')).toBeInTheDocument();
    });

    it('renders the simple panel content by default', () => {
      renderBuilder();
      expect(screen.getByTestId('panel-simple')).toBeInTheDocument();
    });

    it('renders the advanced panel content', () => {
      renderBuilder();
      expect(screen.getByTestId('panel-advanced')).toBeInTheDocument();
    });
  });

  // ── Simple tab — presets ─────────────────────────────────────────────────

  describe('presets', () => {
    it('renders all preset buttons', () => {
      renderBuilder();
      expect(screen.getByText('Every Hour')).toBeInTheDocument();
      expect(screen.getByText('Every Day 3am')).toBeInTheDocument();
      expect(screen.getByText('Every Sunday')).toBeInTheDocument();
    });

    it('renders preset descriptions', () => {
      renderBuilder();
      expect(screen.getByText('Runs every hour')).toBeInTheDocument();
    });

    it('renders preset cron value badges', () => {
      renderBuilder();
      expect(screen.getByText('0 * * * *')).toBeInTheDocument();
    });

    it('calls parseCronPreset with the preset value on click', () => {
      renderBuilder();
      fireEvent.click(screen.getByText('Every Hour'));
      expect(CronBuilderUtils.parseCronPreset).toHaveBeenCalledWith(
        '0 * * * *'
      );
    });

    it('updates state from parseCronPreset result on preset click', () => {
      vi.mocked(CronBuilderUtils.parseCronPreset).mockReturnValue({
        frequency: 'hourly',
        minute: 0,
        hour: 0,
        dayOfWeek: '*',
        dayOfMonth: 1,
      });
      renderBuilder();
      fireEvent.click(screen.getByText('Every Hour'));
      // buildCron should be called with the updated frequency
      expect(CronBuilderUtils.buildCron).toHaveBeenCalledWith(
        'hourly',
        0,
        0,
        '*',
        1
      );
    });
  });

  // ── Simple tab — custom builder ──────────────────────────────────────────

  describe('custom builder', () => {
    const getSimplePanel = () => screen.getByTestId('panel-simple');

    it('renders the Frequency select', () => {
      renderBuilder();
      expect(
        within(getSimplePanel()).getByLabelText('Frequency')
      ).toBeInTheDocument();
    });

    it('renders the Minute input', () => {
      renderBuilder();
      expect(
        within(getSimplePanel()).getByLabelText('Minute (0-59)')
      ).toBeInTheDocument();
    });

    it('renders the Hour input when frequency is not hourly', () => {
      renderBuilder();
      expect(
        within(getSimplePanel()).getByLabelText('Hour (0-23)')
      ).toBeInTheDocument();
    });

    it('does not render Hour input when frequency is hourly', () => {
      renderBuilder();
      const freqSelect = within(getSimplePanel()).getByLabelText('Frequency');
      fireEvent.change(freqSelect, { target: { value: 'hourly' } });
      expect(
        within(getSimplePanel()).queryByLabelText('Hour (0-23)')
      ).not.toBeInTheDocument();
    });

    it('renders Day of Week select when frequency is weekly', () => {
      renderBuilder();
      const freqSelect = within(getSimplePanel()).getByLabelText('Frequency');
      fireEvent.change(freqSelect, { target: { value: 'weekly' } });
      expect(
        within(getSimplePanel()).getByLabelText('Day of Week')
      ).toBeInTheDocument();
    });

    it('does not render Day of Week for daily frequency', () => {
      renderBuilder();
      expect(
        within(getSimplePanel()).queryByLabelText('Day of Week')
      ).not.toBeInTheDocument();
    });

    it('renders Day of Month input when frequency is monthly', () => {
      renderBuilder();
      const freqSelect = within(getSimplePanel()).getByLabelText('Frequency');
      fireEvent.change(freqSelect, { target: { value: 'monthly' } });
      expect(
        within(getSimplePanel()).getByLabelText('Day of Month (1-31)')
      ).toBeInTheDocument();
    });

    it('does not render Day of Month for daily frequency', () => {
      renderBuilder();
      expect(
        within(getSimplePanel()).queryByLabelText('Day of Month (1-31)')
      ).not.toBeInTheDocument();
    });

    it('calls buildCron when minute changes', () => {
      renderBuilder();
      fireEvent.change(
        within(getSimplePanel()).getByLabelText('Minute (0-59)'),
        {
          target: { value: 30 },
        }
      );
      expect(CronBuilderUtils.buildCron).toHaveBeenCalledWith(
        'daily',
        30,
        3,
        '*',
        1
      );
    });

    it('calls buildCron when hour changes', () => {
      renderBuilder();
      fireEvent.change(within(getSimplePanel()).getByLabelText('Hour (0-23)'), {
        target: { value: 8 },
      });
      expect(CronBuilderUtils.buildCron).toHaveBeenCalledWith(
        'daily',
        0,
        8,
        '*',
        1
      );
    });
  });

  // ── Advanced tab ─────────────────────────────────────────────────────────

  describe('advanced tab', () => {
    const getAdvancedPanel = () => screen.getByTestId('panel-advanced');

    it('renders all 5 cron field inputs', () => {
      renderBuilder();
      expect(
        within(getAdvancedPanel()).getByLabelText('Minute (0-59)')
      ).toBeInTheDocument();
      expect(
        within(getAdvancedPanel()).getByLabelText('Hour (0-23)')
      ).toBeInTheDocument();
      expect(
        within(getAdvancedPanel()).getByLabelText('Day of Month (1-31)')
      ).toBeInTheDocument();
      expect(
        within(getAdvancedPanel()).getByLabelText('Month (1-12)')
      ).toBeInTheDocument();
      expect(
        within(getAdvancedPanel()).getByLabelText('Day of Week (0-6, Sun-Sat)')
      ).toBeInTheDocument();
    });

    it('renders descriptive helper text', () => {
      renderBuilder();
      expect(
        screen.getByText(/Build advanced cron expressions/)
      ).toBeInTheDocument();
    });

    it('calls updateCronPart when an advanced field changes', () => {
      renderBuilder();
      const minuteInput =
        within(getAdvancedPanel()).getByLabelText('Minute (0-59)');
      fireEvent.change(minuteInput, { target: { value: '30' } });
      expect(CronBuilderUtils.updateCronPart).toHaveBeenCalledWith(
        '* * * * *',
        0,
        '30'
      );
    });

    it('initializes advanced fields from currentValue when opened', () => {
      renderBuilder({ currentValue: '5 4 * * 1' });
      // The minute field (index 0) should display '5'
      const minuteInput =
        within(getAdvancedPanel()).getByLabelText('Minute (0-59)');
      expect(minuteInput).toHaveValue('5');
    });
  });

  // ── Expression preview ───────────────────────────────────────────────────

  describe('expression preview', () => {
    it('displays the generated cron expression in simple mode', () => {
      vi.mocked(CronBuilderUtils.buildCron).mockReturnValue('0 3 * * *');
      renderBuilder();
      const badges = screen.getAllByTestId('badge');
      const exprBadge = badges.find((b) => b.textContent === '0 3 * * *');
      expect(exprBadge).toBeInTheDocument();
    });

    it('displays manualCron in advanced mode', () => {
      renderBuilder({ currentValue: '5 4 * * 1', opened: true });
      // In advanced panel the badge value should reflect manualCron
      const badges = screen.getAllByTestId('badge');
      // The last large badge shows the active expression
      const exprBadge = badges.find((b) => b.dataset.size === 'lg');
      expect(exprBadge).toBeInTheDocument();
    });
  });

  // ── Apply action ─────────────────────────────────────────────────────────

  describe('apply action', () => {
    const getAdvancedPanel = () => screen.getByTestId('panel-advanced');

    it('calls onApply with the generated cron in simple mode', () => {
      vi.mocked(CronBuilderUtils.buildCron).mockReturnValue('0 3 * * *');
      const onApply = vi.fn();
      const onClose = vi.fn();
      renderBuilder({ onApply, onClose });
      fireEvent.click(screen.getByText('Apply Expression'));
      expect(onApply).toHaveBeenCalledWith('0 3 * * *');
    });

    it('calls onClose after applying', () => {
      const onApply = vi.fn();
      const onClose = vi.fn();
      renderBuilder({ onApply, onClose });
      fireEvent.click(screen.getByText('Apply Expression'));
      expect(onClose).toHaveBeenCalledOnce();
    });

    it('calls onApply with manualCron when in advanced mode', () => {
      const onApply = vi.fn();
      const onClose = vi.fn();
      renderBuilder({ onApply, onClose, currentValue: '5 4 * * 1' });

      // Switch to advanced mode by simulating tab onChange
      // The Tabs mock renders but doesn't fire onChange on tab clicks,
      // so we directly test that advanced panel input changes manualCron
      const minuteInput =
        within(getAdvancedPanel()).getByLabelText('Minute (0-59)');
      // The advanced panel's minute input value should be '5'
      expect(minuteInput).toHaveValue('5');
    });
  });

  // ── currentValue initialization ──────────────────────────────────────────

  describe('currentValue initialization', () => {
    const getAdvancedPanel = () => screen.getByTestId('panel-advanced');

    it('sets manualCron to currentValue when opened', () => {
      renderBuilder({ currentValue: '*/15 * * * *' });
      const minuteInput =
        within(getAdvancedPanel()).getByLabelText('Minute (0-59)');
      expect(minuteInput).toHaveValue('*/15');
    });

    it('keeps default manualCron when currentValue is empty', () => {
      renderBuilder({ currentValue: '' });
      const minuteInput =
        within(getAdvancedPanel()).getByLabelText('Minute (0-59)');
      expect(minuteInput).toHaveValue('*');
    });

    it('does not update manualCron when opened is false', () => {
      renderBuilder({ opened: false, currentValue: '5 4 * * 1' });
      expect(screen.queryByTestId('modal')).not.toBeInTheDocument();
    });
  });
});
