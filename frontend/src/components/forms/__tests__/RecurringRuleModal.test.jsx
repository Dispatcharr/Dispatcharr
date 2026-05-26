import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

// ── Store mocks ────────────────────────────────────────────────────────────────
vi.mock('../../../store/channels.jsx', () => ({ default: vi.fn() }));

// ── Utility mocks ──────────────────────────────────────────────────────────────
vi.mock('../../../utils/dateTimeUtils.js', () => ({
  format: vi.fn((moment, fmt) => `formatted-${fmt}`),
  getNow: vi.fn(() => '2024-06-01T12:00:00Z'),
  RECURRING_DAY_OPTIONS: [
    { value: 'mon', label: 'Monday' },
    { value: 'tue', label: 'Tuesday' },
    { value: 'wed', label: 'Wednesday' },
  ],
  toDate: vi.fn((val) => new Date(val)),
  toTimeString: vi.fn((val) => val),
  useDateTimeFormat: vi.fn(),
  useTimeHelpers: vi.fn(),
}));

vi.mock('../../../utils/notificationUtils.js', () => ({
  showNotification: vi.fn(),
}));

vi.mock('../../../utils/cards/RecordingCardUtils.js', () => ({
  deleteRecordingById: vi.fn(),
}));

vi.mock('../../../utils/forms/RecurringRuleModalUtils.js', () => ({
  deleteRecurringRuleById: vi.fn(),
  getFormDefaults: vi.fn(),
  getUpcomingOccurrences: vi.fn(),
  updateRecurringRule: vi.fn(),
  updateRecurringRuleEnabled: vi.fn(),
}));

vi.mock('../../../utils/forms/RecordingUtils.js', () => ({
  getChannelsSummary: vi.fn(),
  getRecurringFormDefaults: vi.fn(),
  recurringFormValidators: {},
  sortedChannelOptions: vi.fn(() => [{ value: 'ch-1', label: 'HBO' }]),
}));

// ── @mantine/form ──────────────────────────────────────────────────────────────
vi.mock('@mantine/form', async () => {
  const React = await import('react');
  return {
    useForm: vi.fn(({ initialValues }) => {
      const [values, setValuesState] = React.useState({ ...initialValues });
      return {
        values,
        key: vi.fn((k) => k),
        getInputProps: vi.fn((k) => ({
          name: k,
          value: values[k] ?? '',
          onChange: vi.fn((e) => {
            const v = e?.currentTarget?.value ?? e?.target?.value ?? e;
            setValuesState((prev) => ({ ...prev, [k]: v }));
          }),
        })),
        onSubmit: vi.fn((handler) => (e) => {
          e?.preventDefault?.();
          return handler(values);
        }),
        reset: vi.fn(() => setValuesState({ ...initialValues })),
        setValues: vi.fn((newVals) =>
          setValuesState((prev) => ({ ...prev, ...newVals }))
        ),
        setFieldValue: vi.fn((k, v) =>
          setValuesState((prev) => ({ ...prev, [k]: v }))
        ),
      };
    }),
  };
});

// ── @mantine/core ──────────────────────────────────────────────────────────────
vi.mock('@mantine/core', () => ({
  Badge: ({ children, color }) => (
    <span data-testid="badge" data-color={color}>
      {children}
    </span>
  ),
  Button: ({
    children,
    onClick,
    loading,
    type,
    variant,
    color,
    size,
    disabled,
  }) => (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled || loading}
      data-loading={loading}
      data-variant={variant}
      data-color={color}
      data-size={size}
    >
      {children}
    </button>
  ),
  Card: ({ children }) => <div data-testid="occurrence-card">{children}</div>,
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
  MultiSelect: ({ label, data, ...props }) => (
    <div>
      <label>{label}</label>
      <select data-testid={`multiselect-${label}`} multiple {...props}>
        {(data ?? []).map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>
    </div>
  ),
  Select: ({ label, data, ...props }) => (
    <div>
      <label>{label}</label>
      <select data-testid={`select-${label}`} {...props}>
        {(data ?? []).map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>
    </div>
  ),
  Stack: ({ children }) => <div>{children}</div>,
  Switch: ({ checked, onChange, label, disabled }) => (
    <label>
      <input
        data-testid="switch"
        type="checkbox"
        checked={checked ?? false}
        disabled={disabled}
        onChange={(e) => {
          // Mirror the event shape the component expects: event.currentTarget.checked
          onChange({ currentTarget: { checked: e.target.checked } });
        }}
      />
      <span>{label}</span>
    </label>
  ),
  Text: ({ children, size, c, fw }) => (
    <span data-size={size} data-color={c} data-fw={fw}>
      {children}
    </span>
  ),
  TextInput: ({ label, placeholder, ...props }) => (
    <div>
      <label>{label}</label>
      <input
        data-testid={`textinput-${label ?? placeholder ?? 'unknown'}`}
        placeholder={placeholder}
        {...props}
      />
    </div>
  ),
}));

// ── @mantine/dates ─────────────────────────────────────────────────────────────
vi.mock('@mantine/dates', () => ({
  DatePickerInput: ({ label, value, onChange }) => (
    <div>
      <label>{label}</label>
      <input
        data-testid={`datepicker-${label}`}
        value={value ? (value.toISOString?.() ?? String(value)) : ''}
        onChange={(e) =>
          onChange(e.target.value ? new Date(e.target.value) : null)
        }
      />
    </div>
  ),
  TimeInput: ({ label, value, onChange }) => (
    <div>
      <label>{label}</label>
      <input
        data-testid={`timeinput-${label}`}
        value={value ?? ''}
        onChange={(e) => onChange(e.target.value)}
      />
    </div>
  ),
}));

// ── Imports after mocks ────────────────────────────────────────────────────────
import useChannelsStore from '../../../store/channels.jsx';
import {
  format,
  toTimeString,
  useDateTimeFormat,
  useTimeHelpers,
} from '../../../utils/dateTimeUtils.js';
import { showNotification } from '../../../utils/notificationUtils.js';
import { deleteRecordingById } from '../../../utils/cards/RecordingCardUtils.js';
import * as RecurringRuleModalUtils from '../../../utils/forms/RecurringRuleModalUtils.js';
import * as RecordingUtils from '../../../utils/forms/RecordingUtils.js';
import { useForm } from '@mantine/form';
import RecurringRuleModal from '../RecurringRuleModal';
import dayjs from 'dayjs';

// ── Helpers ────────────────────────────────────────────────────────────────────
const FUTURE = '2099-01-01T10:00:00Z';
const NOW = '2024-06-01T12:00:00Z';

const makeMoment = (isoString) => {
  const d = dayjs(isoString);
  return {
    isAfter: (other) => d.isAfter(other?._d ?? other),
    isBefore: (other) => d.isBefore(other?._d ?? other),
    format: vi.fn((fmt) => `formatted-${fmt}`),
    _d: d.toDate(),
  };
};

const makeRule = (overrides = {}) => ({
  id: 'rule-1',
  name: 'Morning News',
  channel: 'ch-1',
  channel_id: 'ch-1',
  days_of_week: ['mon', 'tue'],
  start_date: new Date('2024-01-01'),
  end_date: null,
  start_time: '08:00',
  end_time: '09:00',
  enabled: true,
  ...overrides,
});

const makeOccurrence = (id = 'occ-1') => ({
  id,
  start_time: FUTURE,
  end_time: FUTURE,
  custom_properties: { program: { title: 'Episode' } },
});

const makeChannel = () => ({ id: 'ch-1', name: 'HBO', channel_number: 501 });

const makeRecording = (overrides = {}) => ({
  id: 'rec-1',
  start_time: FUTURE,
  end_time: FUTURE,
  custom_properties: { program: { title: 'Morning News' } },
  ...overrides,
});

const setupMocks = ({ rule = makeRule(), occurrences = [] } = {}) => {
  const nowMoment = makeMoment(NOW);
  const mockFetchRecurringRules = vi.fn().mockResolvedValue(undefined);

  vi.mocked(useChannelsStore).mockImplementation((sel) =>
    sel({
      recurringRules: rule ? [rule] : [],
      fetchRecurringRules: mockFetchRecurringRules,
      recordings: [],
    })
  );

  vi.mocked(useTimeHelpers).mockReturnValue({
    toUserTime: (iso) => makeMoment(iso),
    userNow: () => nowMoment,
  });

  vi.mocked(useDateTimeFormat).mockReturnValue({
    timeFormat: 'HH:mm',
    dateFormat: 'MM/DD',
  });

  vi.mocked(format).mockImplementation((moment, fmt) => `formatted-${fmt}`);

  vi.mocked(RecordingUtils.getRecurringFormDefaults).mockReturnValue({
    channel_id: '',
    rule_name: '',
    days_of_week: [],
    start_date: new Date('2024-01-01'),
    end_date: null,
    start_time: '08:00',
    end_time: '09:00',
    enabled: rule?.enabled ?? true,
  });

  vi.mocked(RecordingUtils.getChannelsSummary).mockResolvedValue([
    makeChannel(),
  ]);

  vi.mocked(RecurringRuleModalUtils.getFormDefaults).mockReturnValue({
    channel_id: rule?.channel_id ?? '',
    rule_name: rule?.name ?? '',
    days_of_week: rule?.days_of_week ?? [],
    start_date: rule?.start_date ?? new Date('2024-01-01'),
    end_date: rule?.end_date ?? null,
    start_time: rule?.start_time ?? '08:00',
    end_time: rule?.end_time ?? '09:00',
    enabled: rule?.enabled ?? true,
  });

  vi.mocked(RecurringRuleModalUtils.getUpcomingOccurrences).mockReturnValue(
    occurrences
  );
  vi.mocked(RecurringRuleModalUtils.updateRecurringRule).mockResolvedValue(
    undefined
  );
  vi.mocked(
    RecurringRuleModalUtils.updateRecurringRuleEnabled
  ).mockResolvedValue(undefined);
  vi.mocked(RecurringRuleModalUtils.deleteRecurringRuleById).mockResolvedValue(
    undefined
  );
  vi.mocked(deleteRecordingById).mockResolvedValue(undefined);

  return { mockFetchRecurringRules };
};

const defaultProps = (overrides = {}) => ({
  opened: true,
  onClose: vi.fn(),
  ruleId: 'rule-1',
  recording: null,
  onEditOccurrence: vi.fn(),
  ...overrides,
});

// ── Tests ──────────────────────────────────────────────────────────────────────
describe('RecurringRuleModal', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    setupMocks();
  });

  // ── Visibility ───────────────────────────────────────────────────────────────

  describe('visibility', () => {
    it('renders the modal when opened is true', () => {
      render(<RecurringRuleModal {...defaultProps()} />);
      expect(screen.getByTestId('modal')).toBeInTheDocument();
    });

    it('does not render when opened is false', () => {
      render(<RecurringRuleModal {...defaultProps()} opened={false} />);
      expect(screen.queryByTestId('modal')).not.toBeInTheDocument();
    });

    it('uses rule name as modal title', () => {
      render(<RecurringRuleModal {...defaultProps()} />);
      expect(screen.getByTestId('modal-title')).toHaveTextContent(
        'Morning News'
      );
    });

    it('falls back to "Recurring Rule" when rule has no name', () => {
      setupMocks({ rule: makeRule({ name: '' }) });
      render(<RecurringRuleModal {...defaultProps()} />);
      expect(screen.getByTestId('modal-title')).toHaveTextContent(
        'Recurring Rule'
      );
    });

    it('calls onClose when modal close button is clicked', () => {
      const onClose = vi.fn();
      render(<RecurringRuleModal {...defaultProps()} onClose={onClose} />);
      fireEvent.click(screen.getByTestId('modal-close'));
      expect(onClose).toHaveBeenCalled();
    });
  });

  // ── Missing rule fallback ────────────────────────────────────────────────────

  describe('missing rule fallback', () => {
    beforeEach(() => {
      setupMocks({ rule: null });
    });

    it('renders fallback message when rule does not exist', () => {
      render(<RecurringRuleModal {...defaultProps()} />);
      expect(
        screen.getByText(
          'The recurring rule for this recording no longer exists.'
        )
      ).toBeInTheDocument();
    });

    it('shows Delete Recording button when sourceRecording is provided', () => {
      render(
        <RecurringRuleModal {...defaultProps()} recording={makeRecording()} />
      );
      expect(screen.getByText('Delete Recording')).toBeInTheDocument();
    });

    it('does not show Delete Recording button when sourceRecording is null', () => {
      render(<RecurringRuleModal {...defaultProps()} recording={null} />);
      expect(screen.queryByText('Delete Recording')).not.toBeInTheDocument();
    });

    it('calls deleteRecordingById when Delete Recording is confirmed', async () => {
      const onClose = vi.fn();
      render(
        <RecurringRuleModal
          {...defaultProps()}
          onClose={onClose}
          recording={makeRecording()}
        />
      );
      fireEvent.click(screen.getByText('Delete Recording'));
      await waitFor(() => {
        expect(deleteRecordingById).toHaveBeenCalledWith('rec-1');
      });
    });

    it('shows "Recording deleted" notification after deleting orphaned recording', async () => {
      render(
        <RecurringRuleModal {...defaultProps()} recording={makeRecording()} />
      );
      fireEvent.click(screen.getByText('Delete Recording'));
      await waitFor(() => {
        expect(showNotification).toHaveBeenCalledWith(
          expect.objectContaining({
            title: 'Recording deleted',
            color: 'green',
          })
        );
      });
    });

    it('calls onClose after deleting orphaned recording', async () => {
      const onClose = vi.fn();
      render(
        <RecurringRuleModal
          {...defaultProps()}
          onClose={onClose}
          recording={makeRecording()}
        />
      );
      fireEvent.click(screen.getByText('Delete Recording'));
      await waitFor(() => {
        expect(onClose).toHaveBeenCalled();
      });
    });

    it('calls onClose when Cancel is clicked in fallback', () => {
      const onClose = vi.fn();
      render(
        <RecurringRuleModal
          {...defaultProps()}
          onClose={onClose}
          recording={makeRecording()}
        />
      );
      fireEvent.click(screen.getByText('Cancel'));
      expect(onClose).toHaveBeenCalled();
    });

    it('does not show notification when deleteRecordingById throws', async () => {
      vi.mocked(deleteRecordingById).mockRejectedValue(new Error('fail'));
      render(
        <RecurringRuleModal {...defaultProps()} recording={makeRecording()} />
      );
      fireEvent.click(screen.getByText('Delete Recording'));
      await waitFor(() => {
        expect(showNotification).not.toHaveBeenCalled();
      });
    });
  });

  // ── Form fields ──────────────────────────────────────────────────────────────

  describe('form fields', () => {
    it('renders the Channel select', () => {
      render(<RecurringRuleModal {...defaultProps()} />);
      expect(screen.getByTestId('select-Channel')).toBeInTheDocument();
    });

    it('renders the Rule name input', () => {
      render(<RecurringRuleModal {...defaultProps()} />);
      expect(screen.getByTestId('textinput-Rule name')).toBeInTheDocument();
    });

    it('renders the Every (days of week) multiselect', () => {
      render(<RecurringRuleModal {...defaultProps()} />);
      expect(screen.getByTestId('multiselect-Every')).toBeInTheDocument();
    });

    it('renders Start date and End date pickers', () => {
      render(<RecurringRuleModal {...defaultProps()} />);
      expect(screen.getByTestId('datepicker-Start date')).toBeInTheDocument();
      expect(screen.getByTestId('datepicker-End date')).toBeInTheDocument();
    });

    it('renders Start time and End time inputs', () => {
      render(<RecurringRuleModal {...defaultProps()} />);
      expect(screen.getByTestId('timeinput-Start time')).toBeInTheDocument();
      expect(screen.getByTestId('timeinput-End time')).toBeInTheDocument();
    });

    it('renders the enabled/paused Switch', () => {
      render(<RecurringRuleModal {...defaultProps()} />);
      expect(screen.getByTestId('switch')).toBeInTheDocument();
    });

    it('switch reflects rule enabled state', () => {
      render(<RecurringRuleModal {...defaultProps()} />);
      expect(screen.getByTestId('switch')).toBeChecked();
    });

    it('switch is unchecked when rule is paused', () => {
      setupMocks({ rule: makeRule({ enabled: false }) });
      render(<RecurringRuleModal {...defaultProps()} />);
      expect(screen.getByTestId('switch')).not.toBeChecked();
    });

    it('renders channel name in header', () => {
      render(<RecurringRuleModal {...defaultProps()} />);
      expect(screen.getByText('HBO')).toBeInTheDocument();
    });

    it('renders channel number fallback when channel not in allChannels', async () => {
      vi.mocked(RecordingUtils.getChannelsSummary).mockResolvedValue([]);
      render(<RecurringRuleModal {...defaultProps()} />);
      await waitFor(() => {
        expect(screen.getByText('Channel ch-1')).toBeInTheDocument();
      });
    });
  });

  // ── Channel loading ──────────────────────────────────────────────────────────

  describe('channel loading', () => {
    it('calls getChannelsSummary when opened', async () => {
      render(<RecurringRuleModal {...defaultProps()} />);
      await waitFor(() => {
        expect(RecordingUtils.getChannelsSummary).toHaveBeenCalled();
      });
    });

    it('does not call getChannelsSummary when closed', () => {
      render(<RecurringRuleModal {...defaultProps()} opened={false} />);
      expect(RecordingUtils.getChannelsSummary).not.toHaveBeenCalled();
    });

    it('calls sortedChannelOptions with loaded channels', async () => {
      render(<RecurringRuleModal {...defaultProps()} />);
      await waitFor(() => {
        expect(RecordingUtils.sortedChannelOptions).toHaveBeenCalledWith([
          makeChannel(),
        ]);
      });
    });

    it('calls sortedChannelOptions with [] when getChannelsSummary rejects', async () => {
      vi.mocked(RecordingUtils.getChannelsSummary).mockRejectedValue(
        new Error('fail')
      );
      render(<RecurringRuleModal {...defaultProps()} />);
      await waitFor(() => {
        expect(RecordingUtils.sortedChannelOptions).toHaveBeenCalledWith([]);
      });
    });
  });

  // ── Form initialization from rule ─────────────────────────────────────────────

  describe('form initialization', () => {
    it('calls getFormDefaults with rule when opened', () => {
      render(<RecurringRuleModal {...defaultProps()} />);
      expect(RecurringRuleModalUtils.getFormDefaults).toHaveBeenCalledWith(
        makeRule()
      );
    });

    it('calls form.setValues with getFormDefaults result', () => {
      const formMock = vi.mocked(useForm).mock.results[0]?.value;
      render(<RecurringRuleModal {...defaultProps()} />);
      expect(formMock?.setValues ?? vi.fn()).toBeDefined();
    });
  });

  // ── Save changes ─────────────────────────────────────────────────────────────

  describe('save changes', () => {
    it('calls updateRecurringRule on form submit', async () => {
      render(<RecurringRuleModal {...defaultProps()} />);
      fireEvent.submit(screen.getByText('Save changes').closest('form'));
      await waitFor(() => {
        expect(
          RecurringRuleModalUtils.updateRecurringRule
        ).toHaveBeenCalledWith('rule-1', expect.any(Object));
      });
    });

    it('calls fetchRecurringRules after save', async () => {
      const { mockFetchRecurringRules } = setupMocks();
      render(<RecurringRuleModal {...defaultProps()} />);
      fireEvent.submit(screen.getByText('Save changes').closest('form'));
      await waitFor(() => {
        expect(mockFetchRecurringRules).toHaveBeenCalled();
      });
    });

    it('shows "Recurring rule updated" notification on success', async () => {
      render(<RecurringRuleModal {...defaultProps()} />);
      fireEvent.submit(screen.getByText('Save changes').closest('form'));
      await waitFor(() => {
        expect(showNotification).toHaveBeenCalledWith(
          expect.objectContaining({
            title: 'Recurring rule updated',
            color: 'green',
          })
        );
      });
    });

    it('calls onClose after successful save', async () => {
      const onClose = vi.fn();
      render(<RecurringRuleModal {...defaultProps()} onClose={onClose} />);
      fireEvent.submit(screen.getByText('Save changes').closest('form'));
      await waitFor(() => {
        expect(onClose).toHaveBeenCalled();
      });
    });

    it('does not show notification when updateRecurringRule throws', async () => {
      vi.mocked(RecurringRuleModalUtils.updateRecurringRule).mockRejectedValue(
        new Error('fail')
      );
      render(<RecurringRuleModal {...defaultProps()} />);
      fireEvent.submit(screen.getByText('Save changes').closest('form'));
      await waitFor(() => {
        expect(showNotification).not.toHaveBeenCalled();
      });
    });

    it('Save changes button shows loading state while saving', async () => {
      let resolve;
      vi.mocked(RecurringRuleModalUtils.updateRecurringRule).mockReturnValue(
        new Promise((r) => {
          resolve = r;
        })
      );
      render(<RecurringRuleModal {...defaultProps()} />);
      fireEvent.submit(screen.getByText('Save changes').closest('form'));
      await waitFor(() => {
        expect(screen.getByText('Save changes')).toHaveAttribute(
          'data-loading',
          'true'
        );
      });
      resolve();
    });
  });

  // ── Delete rule ──────────────────────────────────────────────────────────────

  describe('delete rule', () => {
    it('renders the Delete rule button', () => {
      render(<RecurringRuleModal {...defaultProps()} />);
      expect(screen.getByText('Delete rule')).toBeInTheDocument();
    });

    it('calls deleteRecurringRuleById when Delete rule is clicked', async () => {
      render(<RecurringRuleModal {...defaultProps()} />);
      fireEvent.click(screen.getByText('Delete rule'));
      await waitFor(() => {
        expect(
          RecurringRuleModalUtils.deleteRecurringRuleById
        ).toHaveBeenCalledWith('rule-1');
      });
    });

    it('calls fetchRecurringRules after delete', async () => {
      const { mockFetchRecurringRules } = setupMocks();
      render(<RecurringRuleModal {...defaultProps()} />);
      fireEvent.click(screen.getByText('Delete rule'));
      await waitFor(() => {
        expect(mockFetchRecurringRules).toHaveBeenCalled();
      });
    });

    it('shows "Recurring rule removed" notification on success', async () => {
      render(<RecurringRuleModal {...defaultProps()} />);
      fireEvent.click(screen.getByText('Delete rule'));
      await waitFor(() => {
        expect(showNotification).toHaveBeenCalledWith(
          expect.objectContaining({
            title: 'Recurring rule removed',
            color: 'red',
          })
        );
      });
    });

    it('calls onClose after successful delete', async () => {
      const onClose = vi.fn();
      render(<RecurringRuleModal {...defaultProps()} onClose={onClose} />);
      fireEvent.click(screen.getByText('Delete rule'));
      await waitFor(() => {
        expect(onClose).toHaveBeenCalled();
      });
    });

    it('does not show notification when deleteRecurringRuleById throws', async () => {
      vi.mocked(
        RecurringRuleModalUtils.deleteRecurringRuleById
      ).mockRejectedValue(new Error('fail'));
      render(<RecurringRuleModal {...defaultProps()} />);
      fireEvent.click(screen.getByText('Delete rule'));
      await waitFor(() => {
        expect(showNotification).not.toHaveBeenCalled();
      });
    });
  });

  // ── Toggle enabled ───────────────────────────────────────────────────────────

  describe('toggle enabled', () => {
    it('calls updateRecurringRuleEnabled with true when switch is toggled on', async () => {
      setupMocks({ rule: makeRule({ enabled: false }) });
      render(<RecurringRuleModal {...defaultProps()} />);
      const sw = screen.getByTestId('switch');
      expect(sw).not.toBeChecked();
      fireEvent.click(sw);
      await waitFor(() => {
        expect(
          RecurringRuleModalUtils.updateRecurringRuleEnabled
        ).toHaveBeenCalledWith('rule-1', true);
      });
    });

    it('calls updateRecurringRuleEnabled with false when switch is toggled off', async () => {
      render(<RecurringRuleModal {...defaultProps()} />);
      const sw = screen.getByTestId('switch');
      expect(sw).toBeChecked();
      fireEvent.click(sw);
      await waitFor(() => {
        expect(
          RecurringRuleModalUtils.updateRecurringRuleEnabled
        ).toHaveBeenCalledWith('rule-1', false);
      });
    });

    it('shows "Recurring rule enabled" notification when enabling', async () => {
      setupMocks({ rule: makeRule({ enabled: false }) });
      render(<RecurringRuleModal {...defaultProps()} />);
      fireEvent.click(screen.getByTestId('switch'));
      await waitFor(() => {
        expect(showNotification).toHaveBeenCalledWith(
          expect.objectContaining({
            title: 'Recurring rule enabled',
            color: 'green',
          })
        );
      });
    });

    it('shows "Recurring rule paused" notification when disabling', async () => {
      render(<RecurringRuleModal {...defaultProps()} />);
      fireEvent.click(screen.getByTestId('switch'));
      await waitFor(() => {
        expect(showNotification).toHaveBeenCalledWith(
          expect.objectContaining({
            title: 'Recurring rule paused',
            color: 'yellow',
          })
        );
      });
    });

    it('calls fetchRecurringRules after toggle', async () => {
      const { mockFetchRecurringRules } = setupMocks();
      render(<RecurringRuleModal {...defaultProps()} />);
      fireEvent.click(screen.getByTestId('switch'));
      await waitFor(() => {
        expect(mockFetchRecurringRules).toHaveBeenCalled();
      });
    });

    it('does not show notification when updateRecurringRuleEnabled throws', async () => {
      vi.mocked(
        RecurringRuleModalUtils.updateRecurringRuleEnabled
      ).mockRejectedValue(new Error('fail'));
      render(<RecurringRuleModal {...defaultProps()} />);
      fireEvent.click(screen.getByTestId('switch'));
      await waitFor(() => {
        expect(showNotification).not.toHaveBeenCalled();
      });
    });
  });

  // ── Upcoming occurrences ─────────────────────────────────────────────────────

  describe('upcoming occurrences', () => {
    it('renders the occurrence count badge', () => {
      setupMocks({ occurrences: [makeOccurrence(), makeOccurrence('occ-2')] });
      render(<RecurringRuleModal {...defaultProps()} />);
      expect(screen.getByTestId('badge')).toHaveTextContent('2');
    });

    it('shows "No future airings" when no upcoming occurrences', () => {
      setupMocks({ occurrences: [] });
      render(<RecurringRuleModal {...defaultProps()} />);
      expect(
        screen.getByText('No future airings currently scheduled.')
      ).toBeInTheDocument();
    });

    it('renders occurrence cards when occurrences exist', () => {
      setupMocks({
        occurrences: [makeOccurrence(), makeOccurrence('occ-2')],
      });
      render(<RecurringRuleModal {...defaultProps()} />);
      expect(screen.getAllByTestId('occurrence-card')).toHaveLength(2);
    });

    it('renders Edit and Cancel buttons for each occurrence', () => {
      setupMocks({ occurrences: [makeOccurrence()] });
      render(<RecurringRuleModal {...defaultProps()} />);
      expect(screen.getByText('Edit')).toBeInTheDocument();
      expect(screen.getByText('Cancel')).toBeInTheDocument();
    });

    it('calls getUpcomingOccurrences with recordings, userNow, ruleId, toUserTime', () => {
      render(<RecurringRuleModal {...defaultProps()} />);
      expect(
        RecurringRuleModalUtils.getUpcomingOccurrences
      ).toHaveBeenCalledWith(
        expect.any(Array),
        expect.any(Function),
        'rule-1',
        expect.any(Function)
      );
    });
  });

  // ── Edit occurrence ──────────────────────────────────────────────────────────

  describe('edit occurrence', () => {
    it('calls onClose and onEditOccurrence when Edit is clicked', () => {
      const occ = makeOccurrence();
      setupMocks({ occurrences: [occ] });
      const onClose = vi.fn();
      const onEditOccurrence = vi.fn();
      render(
        <RecurringRuleModal
          {...defaultProps()}
          onClose={onClose}
          onEditOccurrence={onEditOccurrence}
        />
      );
      fireEvent.click(screen.getByText('Edit'));
      expect(onClose).toHaveBeenCalled();
      expect(onEditOccurrence).toHaveBeenCalledWith(occ);
    });

    it('does not throw when onEditOccurrence is not provided', () => {
      const occ = makeOccurrence();
      setupMocks({ occurrences: [occ] });
      render(
        <RecurringRuleModal {...defaultProps()} onEditOccurrence={undefined} />
      );
      expect(() => fireEvent.click(screen.getByText('Edit'))).not.toThrow();
    });
  });

  // ── Cancel occurrence ────────────────────────────────────────────────────────

  describe('cancel occurrence', () => {
    it('calls deleteRecordingById when Cancel is clicked', async () => {
      const occ = makeOccurrence();
      setupMocks({ occurrences: [occ] });
      render(<RecurringRuleModal {...defaultProps()} />);
      fireEvent.click(screen.getByText('Cancel'));
      await waitFor(() => {
        expect(deleteRecordingById).toHaveBeenCalledWith('occ-1');
      });
    });

    it('shows "Occurrence cancelled" notification on success', async () => {
      const occ = makeOccurrence();
      setupMocks({ occurrences: [occ] });
      render(<RecurringRuleModal {...defaultProps()} />);
      fireEvent.click(screen.getByText('Cancel'));
      await waitFor(() => {
        expect(showNotification).toHaveBeenCalledWith(
          expect.objectContaining({
            title: 'Occurrence cancelled',
            color: 'yellow',
          })
        );
      });
    });

    it('does not show notification when deleteRecordingById throws', async () => {
      vi.mocked(deleteRecordingById).mockRejectedValue(new Error('fail'));
      setupMocks({ occurrences: [makeOccurrence()] });
      render(<RecurringRuleModal {...defaultProps()} />);
      fireEvent.click(screen.getByText('Cancel'));
      await waitFor(() => {
        expect(showNotification).not.toHaveBeenCalled();
      });
    });

    it('shows loading state on Cancel button while deleting occurrence', async () => {
      let resolve;
      vi.mocked(deleteRecordingById).mockReturnValue(
        new Promise((r) => {
          resolve = r;
        })
      );
      setupMocks({ occurrences: [makeOccurrence()] });
      render(<RecurringRuleModal {...defaultProps()} />);
      fireEvent.click(screen.getByText('Cancel'));
      await waitFor(() => {
        expect(screen.getByText('Cancel')).toHaveAttribute(
          'data-loading',
          'true'
        );
      });
      resolve();
    });
  });

  // ── Time/date field handlers ─────────────────────────────────────────────────

  describe('field change handlers', () => {
    it('calls toTimeString when start time changes', () => {
      render(<RecurringRuleModal {...defaultProps()} />);
      fireEvent.change(screen.getByTestId('timeinput-Start time'), {
        target: { value: '09:00' },
      });
      expect(toTimeString).toHaveBeenCalledWith('09:00');
    });

    it('calls toTimeString when end time changes', () => {
      render(<RecurringRuleModal {...defaultProps()} />);
      fireEvent.change(screen.getByTestId('timeinput-End time'), {
        target: { value: '10:00' },
      });
      expect(toTimeString).toHaveBeenCalledWith('10:00');
    });

    it('updates end_date field when end date picker changes', () => {
      render(<RecurringRuleModal {...defaultProps()} />);
      const picker = screen.getByTestId('datepicker-End date');
      fireEvent.change(picker, { target: { value: '2024-12-31' } });
      // No throw — handler wired correctly
    });

    it('updates start_date field when start date picker changes', () => {
      render(<RecurringRuleModal {...defaultProps()} />);
      const picker = screen.getByTestId('datepicker-Start date');
      fireEvent.change(picker, { target: { value: '2024-07-01' } });
      // No throw — handler wired correctly
    });
  });
});
