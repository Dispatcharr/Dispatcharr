import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import RecordingModal from '../Recording';

// ── Store mocks ────────────────────────────────────────────────────────────────
vi.mock('../../../store/channels', () => ({ default: vi.fn() }));

// ── Utility mocks ──────────────────────────────────────────────────────────────
vi.mock('../../../utils/dateTimeUtils.js', () => ({
  RECURRING_DAY_OPTIONS: [
    { value: 'mon', label: 'Monday' },
    { value: 'tue', label: 'Tuesday' },
  ],
  toTimeString: vi.fn((val) => val),
}));

vi.mock('../../../utils/notificationUtils.js', () => ({
  showNotification: vi.fn(),
}));

vi.mock('../../../utils/forms/RecordingUtils.js', () => ({
  buildRecurringPayload: vi.fn((v) => v),
  buildSinglePayload: vi.fn((v) => v),
  createRecording: vi.fn(),
  createRecurringRule: vi.fn(),
  sortedChannelOptions: vi.fn(() => [{ value: 'ch-1', label: '501 - HBO' }]),
  numberedChannelLabel: vi.fn((item) =>
    item.channel_number ? `${item.channel_number} - ${item.name}` : item.name
  ),
  getChannelsSummary: vi.fn(),
  getRecurringFormDefaults: vi.fn(() => ({
    channel_id: '',
    rule_name: '',
    days_of_week: [],
    start_date: new Date('2024-01-01'),
    end_date: null,
    start_time: '08:00',
    end_time: '09:00',
  })),
  getSingleFormDefaults: vi.fn(() => ({
    channel_id: 'ch-1',
    start_time: new Date('2024-06-01T10:00:00'),
    end_time: new Date('2024-06-01T11:00:00'),
  })),
  recurringFormValidators: {},
  singleFormValidators: {},
  timeChange: vi.fn((fn) => (e) => fn(e.target.value)),
  updateRecording: vi.fn(),
}));

// ── @mantine/form ──────────────────────────────────────────────────────────────
vi.mock('@mantine/form', () => ({
  useForm: vi.fn(({ initialValues }) => {
    const values = { ...initialValues };
    return {
      values,
      key: vi.fn((k) => k),
      getInputProps: vi.fn((k) => ({ name: k, value: values[k] ?? '', onChange: vi.fn() })),
      onSubmit: vi.fn((handler) => (e) => { e?.preventDefault?.(); return handler(values); }),
      reset: vi.fn(),
      setValues: vi.fn((newVals) => Object.assign(values, newVals)),
      setFieldValue: vi.fn((k, v) => { values[k] = v; }),
      validateField: vi.fn(),
    };
  }),
}));

// ── @mantine/core ──────────────────────────────────────────────────────────────
vi.mock('@mantine/core', () => ({
  Alert: ({ children, title }) => (
    <div data-testid="alert">
      <span data-testid="alert-title">{title}</span>
      {children}
    </div>
  ),
  Button: ({ children, onClick, loading, type }) => (
    <button type={type} onClick={onClick} data-loading={loading} disabled={loading}>
      {children}
    </button>
  ),
  Group: ({ children }) => <div>{children}</div>,
  Loader: ({ size, color }) => <span data-testid="loader" data-size={size} data-color={color} />,
  Modal: ({ children, opened, onClose, title }) =>
    opened ? (
      <div data-testid="modal">
        <div data-testid="modal-title">{title}</div>
        <button data-testid="modal-close" onClick={onClose}>×</button>
        {children}
      </div>
    ) : null,
  MultiSelect: ({ label, placeholder, ...props }) => (
    <div>
      <label>{label}</label>
      <input data-testid={`multiselect-${label}`} placeholder={placeholder} {...props} />
    </div>
  ),
  SegmentedControl: ({ value, onChange, data, disabled }) => (
    <div data-testid="segmented-control">
      {data.map((item) => (
        <button
          key={item.value}
          data-testid={`mode-${item.value}`}
          data-active={value === item.value}
          disabled={disabled}
          onClick={() => onChange(item.value)}
        >
          {item.label}
        </button>
      ))}
    </div>
  ),
  Select: ({ label, disabled, rightSection, data, ...props }) => (
    <div>
      <label>{label}</label>
      {rightSection}
      <select data-testid={`select-${label}`} disabled={disabled} {...props}>
        {(data ?? []).map((opt) => (
          <option key={opt.value} value={opt.value}>{opt.label}</option>
        ))}
      </select>
    </div>
  ),
  Stack: ({ children }) => <div>{children}</div>,
  TextInput: ({ label, placeholder, ...props }) => (
    <div>
      <label>{label}</label>
      <input data-testid={`textinput-${label}`} placeholder={placeholder} {...props} />
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
        value={value ? value.toISOString?.() ?? value : ''}
        onChange={(e) => onChange(e.target.value ? new Date(e.target.value) : null)}
      />
    </div>
  ),
  DateTimePicker: ({ label, ...props }) => (
    <div>
      <label>{label}</label>
      <input data-testid={`datetimepicker-${label}`} {...props} />
    </div>
  ),
  TimeInput: ({ label, value, onChange, onBlur }) => (
    <div>
      <label>{label}</label>
      <input
        data-testid={`timeinput-${label}`}
        value={value ?? ''}
        onChange={onChange}
        onBlur={onBlur}
      />
    </div>
  ),
}));

// ── lucide-react ───────────────────────────────────────────────────────────────
vi.mock('lucide-react', () => ({
  CircleAlert: () => <svg data-testid="icon-circle-alert" />,
}));

// ── Imports after mocks ────────────────────────────────────────────────────────
import useChannelsStore from '../../../store/channels';
import { showNotification } from '../../../utils/notificationUtils.js';
import * as RecordingUtils from '../../../utils/forms/RecordingUtils.js';

const setupStoreMock = () => {
  const mockFetchRecordings = vi.fn().mockResolvedValue(undefined);
  const mockFetchRecurringRules = vi.fn().mockResolvedValue(undefined);

  vi.mocked(useChannelsStore).mockImplementation((sel) =>
    sel({ fetchRecordings: mockFetchRecordings, fetchRecurringRules: mockFetchRecurringRules })
  );

  return { mockFetchRecordings, mockFetchRecurringRules };
};

const makeRecording = (overrides = {}) => ({
  id: 'rec-1',
  start_time: '2024-06-01T10:00:00Z',
  end_time: '2024-06-01T11:00:00Z',
  custom_properties: { program: { title: 'Test Show' } },
  ...overrides,
});

const makeChannel = () => ({ id: 'ch-1', name: 'HBO', channel_number: 501 });

describe('RecordingModal', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(RecordingUtils.getChannelsSummary).mockResolvedValue([
      { id: 'ch-1', name: 'HBO', channel_number: 501 },
    ]);
    vi.mocked(RecordingUtils.createRecording).mockResolvedValue(undefined);
    vi.mocked(RecordingUtils.updateRecording).mockResolvedValue(undefined);
    vi.mocked(RecordingUtils.createRecurringRule).mockResolvedValue(undefined);
    setupStoreMock();
  });

  // ── Visibility ─────────────────────────────────────────────────────────────

  describe('visibility', () => {
    it('renders the modal when isOpen is true', () => {
      render(<RecordingModal isOpen onClose={vi.fn()} />);
      expect(screen.getByTestId('modal')).toBeInTheDocument();
    });

    it('does not render when isOpen is false', () => {
      render(<RecordingModal isOpen={false} onClose={vi.fn()} />);
      expect(screen.queryByTestId('modal')).not.toBeInTheDocument();
    });
  });

  // ── Alert ──────────────────────────────────────────────────────────────────

  describe('scheduling conflict alert', () => {
    it('renders the scheduling conflicts alert', () => {
      render(<RecordingModal isOpen onClose={vi.fn()} />);
      expect(screen.getByTestId('alert')).toBeInTheDocument();
      expect(screen.getByTestId('alert-title')).toHaveTextContent('Scheduling Conflicts');
    });
  });

  // ── Mode switching ─────────────────────────────────────────────────────────

  describe('mode switching', () => {
    it('defaults to "single" mode', () => {
      render(<RecordingModal isOpen onClose={vi.fn()} />);
      expect(screen.getByTestId('mode-single')).toHaveAttribute('data-active', 'true');
    });

    it('switches to recurring mode when Recurring button clicked', () => {
      render(<RecordingModal isOpen onClose={vi.fn()} />);
      fireEvent.click(screen.getByTestId('mode-recurring'));
      expect(screen.getByTestId('mode-recurring')).toHaveAttribute('data-active', 'true');
    });

    it('shows DateTimePicker fields in single mode', () => {
      render(<RecordingModal isOpen onClose={vi.fn()} />);
      expect(screen.getByTestId('datetimepicker-Start')).toBeInTheDocument();
      expect(screen.getByTestId('datetimepicker-End')).toBeInTheDocument();
    });

    it('shows recurring fields when in recurring mode', () => {
      render(<RecordingModal isOpen onClose={vi.fn()} />);
      fireEvent.click(screen.getByTestId('mode-recurring'));
      expect(screen.getByTestId('textinput-Rule name')).toBeInTheDocument();
      expect(screen.getByTestId('timeinput-Start time')).toBeInTheDocument();
      expect(screen.getByTestId('timeinput-End time')).toBeInTheDocument();
    });

    it('disables mode toggle when editing an existing recording', () => {
      render(<RecordingModal isOpen onClose={vi.fn()} recording={makeRecording()} />);
      expect(screen.getByTestId('mode-single')).toBeDisabled();
      expect(screen.getByTestId('mode-recurring')).toBeDisabled();
    });

    it('shows "Schedule Recording" submit button in single mode', () => {
      render(<RecordingModal isOpen onClose={vi.fn()} />);
      expect(screen.getByText('Schedule Recording')).toBeInTheDocument();
    });

    it('shows "Save Rule" submit button in recurring mode', () => {
      render(<RecordingModal isOpen onClose={vi.fn()} />);
      fireEvent.click(screen.getByTestId('mode-recurring'));
      expect(screen.getByText('Save Rule')).toBeInTheDocument();
    });
  });

  // ── Channel loading ────────────────────────────────────────────────────────

  describe('channel loading', () => {
    it('calls getChannelsSummary when modal opens', async () => {
      render(<RecordingModal isOpen onClose={vi.fn()} />);
      await waitFor(() => {
        expect(RecordingUtils.getChannelsSummary).toHaveBeenCalled();
      });
    });

    it('calls sortedChannelOptions with loaded channels', async () => {
      const channels = [{ id: 'ch-1', name: 'HBO', channel_number: 501 }];
      vi.mocked(RecordingUtils.getChannelsSummary).mockResolvedValue(channels);
      render(<RecordingModal isOpen onClose={vi.fn()} />);
      await waitFor(() => {
        expect(RecordingUtils.sortedChannelOptions).toHaveBeenCalledWith(
          channels,
          RecordingUtils.numberedChannelLabel
        );
      });
    });

    it('calls sortedChannelOptions with [] when getChannelsSummary rejects', async () => {
      vi.mocked(RecordingUtils.getChannelsSummary).mockRejectedValue(new Error('fail'));
      render(<RecordingModal isOpen onClose={vi.fn()} />);
      await waitFor(() => {
        expect(RecordingUtils.sortedChannelOptions).toHaveBeenCalledWith(
          [],
          RecordingUtils.numberedChannelLabel
        );
      });
    });

    it('does not load channels when modal is closed', () => {
      render(<RecordingModal isOpen={false} onClose={vi.fn()} />);
      expect(RecordingUtils.getChannelsSummary).not.toHaveBeenCalled();
    });
  });

  // ── Single form submit (create) ────────────────────────────────────────────

  describe('single mode – create recording', () => {
    it('calls buildSinglePayload with form values on submit', async () => {
      render(<RecordingModal isOpen onClose={vi.fn()} />);
      fireEvent.submit(screen.getByText('Schedule Recording').closest('form'));
      await waitFor(() => {
        expect(RecordingUtils.buildSinglePayload).toHaveBeenCalled();
      });
    });

    it('calls createRecording when no existing recording', async () => {
      render(<RecordingModal isOpen onClose={vi.fn()} />);
      fireEvent.submit(screen.getByText('Schedule Recording').closest('form'));
      await waitFor(() => {
        expect(RecordingUtils.createRecording).toHaveBeenCalled();
      });
    });

    it('shows "Recording scheduled" notification after successful create', async () => {
      render(<RecordingModal isOpen onClose={vi.fn()} />);
      fireEvent.submit(screen.getByText('Schedule Recording').closest('form'));
      await waitFor(() => {
        expect(showNotification).toHaveBeenCalledWith(
          expect.objectContaining({ title: 'Recording scheduled', color: 'green' })
        );
      });
    });

    it('calls fetchRecordings after successful create', async () => {
      const { mockFetchRecordings } = setupStoreMock();
      render(<RecordingModal isOpen onClose={vi.fn()} />);
      fireEvent.submit(screen.getByText('Schedule Recording').closest('form'));
      await waitFor(() => {
        expect(mockFetchRecordings).toHaveBeenCalled();
      });
    });

    it('calls onClose after successful create', async () => {
      const onClose = vi.fn();
      render(<RecordingModal isOpen onClose={onClose} />);
      fireEvent.submit(screen.getByText('Schedule Recording').closest('form'));
      await waitFor(() => {
        expect(onClose).toHaveBeenCalled();
      });
    });

    it('does not call showNotification when createRecording throws', async () => {
      vi.mocked(RecordingUtils.createRecording).mockRejectedValue(new Error('fail'));
      render(<RecordingModal isOpen onClose={vi.fn()} />);
      fireEvent.submit(screen.getByText('Schedule Recording').closest('form'));
      await waitFor(() => {
        expect(showNotification).not.toHaveBeenCalled();
      });
    });
  });

  // ── Single form submit (update) ────────────────────────────────────────────

  describe('single mode – update recording', () => {
    it('calls updateRecording when editing an existing recording', async () => {
      render(
        <RecordingModal isOpen onClose={vi.fn()} recording={makeRecording()} />
      );
      fireEvent.submit(screen.getByText('Schedule Recording').closest('form'));
      await waitFor(() => {
        expect(RecordingUtils.updateRecording).toHaveBeenCalledWith(
          'rec-1',
          expect.anything()
        );
      });
    });

    it('does not call createRecording when updating', async () => {
      render(
        <RecordingModal isOpen onClose={vi.fn()} recording={makeRecording()} />
      );
      fireEvent.submit(screen.getByText('Schedule Recording').closest('form'));
      await waitFor(() => {
        expect(RecordingUtils.createRecording).not.toHaveBeenCalled();
      });
    });

    it('shows "Recording updated" notification after successful update', async () => {
      render(
        <RecordingModal isOpen onClose={vi.fn()} recording={makeRecording()} />
      );
      fireEvent.submit(screen.getByText('Schedule Recording').closest('form'));
      await waitFor(() => {
        expect(showNotification).toHaveBeenCalledWith(
          expect.objectContaining({ title: 'Recording updated', color: 'green' })
        );
      });
    });
  });

  // ── Recurring form submit ──────────────────────────────────────────────────

  describe('recurring mode – create rule', () => {
    it('calls buildRecurringPayload with form values on submit', async () => {
      render(<RecordingModal isOpen onClose={vi.fn()} />);
      fireEvent.click(screen.getByTestId('mode-recurring'));
      fireEvent.submit(screen.getByText('Save Rule').closest('form'));
      await waitFor(() => {
        expect(RecordingUtils.buildRecurringPayload).toHaveBeenCalled();
      });
    });

    it('calls createRecurringRule on submit', async () => {
      render(<RecordingModal isOpen onClose={vi.fn()} />);
      fireEvent.click(screen.getByTestId('mode-recurring'));
      fireEvent.submit(screen.getByText('Save Rule').closest('form'));
      await waitFor(() => {
        expect(RecordingUtils.createRecurringRule).toHaveBeenCalled();
      });
    });

    it('calls fetchRecurringRules and fetchRecordings on success', async () => {
      const { mockFetchRecurringRules, mockFetchRecordings } = setupStoreMock();
      render(<RecordingModal isOpen onClose={vi.fn()} />);
      fireEvent.click(screen.getByTestId('mode-recurring'));
      fireEvent.submit(screen.getByText('Save Rule').closest('form'));
      await waitFor(() => {
        expect(mockFetchRecurringRules).toHaveBeenCalled();
        expect(mockFetchRecordings).toHaveBeenCalled();
      });
    });

    it('shows "Recurring rule saved" notification on success', async () => {
      render(<RecordingModal isOpen onClose={vi.fn()} />);
      fireEvent.click(screen.getByTestId('mode-recurring'));
      fireEvent.submit(screen.getByText('Save Rule').closest('form'));
      await waitFor(() => {
        expect(showNotification).toHaveBeenCalledWith(
          expect.objectContaining({ title: 'Recurring rule saved', color: 'green' })
        );
      });
    });

    it('calls onClose after successful recurring submit', async () => {
      const onClose = vi.fn();
      render(<RecordingModal isOpen onClose={onClose} />);
      fireEvent.click(screen.getByTestId('mode-recurring'));
      fireEvent.submit(screen.getByText('Save Rule').closest('form'));
      await waitFor(() => {
        expect(onClose).toHaveBeenCalled();
      });
    });

    it('does not show notification when createRecurringRule throws', async () => {
      vi.mocked(RecordingUtils.createRecurringRule).mockRejectedValue(new Error('fail'));
      render(<RecordingModal isOpen onClose={vi.fn()} />);
      fireEvent.click(screen.getByTestId('mode-recurring'));
      fireEvent.submit(screen.getByText('Save Rule').closest('form'));
      await waitFor(() => {
        expect(showNotification).not.toHaveBeenCalled();
      });
    });
  });

  // ── Form initialization ────────────────────────────────────────────────────

  describe('form initialization', () => {
    it('calls getSingleFormDefaults with recording and channel when opening with existing recording', () => {
      const recording = makeRecording();
      const channel = makeChannel();
      render(<RecordingModal isOpen recording={recording} channel={channel} onClose={vi.fn()} />);
      expect(RecordingUtils.getSingleFormDefaults).toHaveBeenCalledWith(recording, channel);
    });

    it('calls getSingleFormDefaults with null when opening for new recording', () => {
      render(<RecordingModal isOpen onClose={vi.fn()} />);
      expect(RecordingUtils.getSingleFormDefaults).toHaveBeenCalledWith(null, null);
    });

    it('calls getRecurringFormDefaults with channel on open', () => {
      const channel = makeChannel();
      render(<RecordingModal isOpen channel={channel} onClose={vi.fn()} />);
      expect(RecordingUtils.getRecurringFormDefaults).toHaveBeenCalledWith(channel);
    });
  });

  // ── Close / reset ──────────────────────────────────────────────────────────

  describe('close and reset', () => {
    it('calls onClose when modal close button is clicked', () => {
      const onClose = vi.fn();
      render(<RecordingModal isOpen onClose={onClose} />);
      fireEvent.click(screen.getByTestId('modal-close'));
      expect(onClose).toHaveBeenCalled();
    });
  });
});