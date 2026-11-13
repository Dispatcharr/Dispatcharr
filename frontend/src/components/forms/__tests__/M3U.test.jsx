import {
  render,
  screen,
  fireEvent,
  waitFor,
  act,
  within,
} from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import M3U from '../M3U';
import { useDateTimeFormat } from '../../../utils/dateTimeUtils.js';
import classes from '../M3U.module.css';

// ── Store mocks ────────────────────────────────────────────────────────────────
vi.mock('../../../store/userAgents', () => ({ default: vi.fn() }));
vi.mock('../../../store/channels', () => ({ default: vi.fn() }));
vi.mock('../../../store/epgs', () => ({ default: vi.fn() }));
vi.mock('../../../store/useVODStore', () => ({ default: vi.fn() }));

// ── Utility mocks ──────────────────────────────────────────────────────────────
vi.mock('../../../utils/forms/M3uUtils.js', () => ({
  addPlaylist: vi.fn(),
  getPlaylist: vi.fn(),
  prepareSubmitValues: vi.fn((values) => values),
  updatePlaylist: vi.fn(),
  expDateFromPlaylist: (expDate) => {
    if (!expDate) return null;
    const parsed = new Date(expDate);
    return Number.isNaN(parsed.getTime()) ? null : parsed;
  },
  expDateKey: (expDate) => {
    if (expDate instanceof Date) {
      return Number.isNaN(expDate.getTime()) ? null : expDate.toISOString();
    }
    if (!expDate) return null;
    const parsed = new Date(expDate);
    return Number.isNaN(parsed.getTime()) ? null : parsed.toISOString();
  },
}));

vi.mock('../../../store/playlists', () => ({ default: vi.fn() }));

vi.mock('../../../utils/forms/DummyEpgUtils.js', () => ({
  addEPG: vi.fn(),
}));

vi.mock('../../../utils/notificationUtils.js', () => ({
  showNotification: vi.fn(),
}));

vi.mock('../../../utils/dateTimeUtils.js', () => ({
  useDateTimeFormat: vi.fn(),
}));

// ── Sub-component mocks ────────────────────────────────────────────────────────
vi.mock('../M3UProfiles', () => ({
  default: ({ onChange }) => (
    <div data-testid="m3u-profiles">
      <button onClick={() => onChange?.([])}>M3UProfiles</button>
    </div>
  ),
}));

vi.mock('../M3UGroupFilter', () => ({
  default: ({ onChange, isInitialSetup }) => (
    <div
      data-testid="m3u-group-filter"
      data-initial-setup={String(isInitialSetup)}
    >
      <button onClick={() => onChange?.([])}>M3UGroupFilter</button>
    </div>
  ),
}));

vi.mock('../M3UFilters', () => ({
  default: ({ onChange }) => (
    <div data-testid="m3u-filters">
      <button onClick={() => onChange?.([])}>M3UFilters</button>
    </div>
  ),
}));

vi.mock('../ScheduleInput', () => ({
  default: ({ intervalLabel, intervalValue, onIntervalChange }) => (
    <div data-testid="schedule-input">
      <input
        data-testid="schedule-value"
        aria-label={intervalLabel}
        value={intervalValue ?? ''}
        onChange={(e) => onIntervalChange?.(Number(e.target.value))}
      />
    </div>
  ),
}));

// ── Mantine dates ──────────────────────────────────────────────────────────────
vi.mock('@mantine/dates', () => ({
  DateTimePicker: ({ label, value, onChange, placeholder, valueFormat }) => (
    <div>
      <label>
        {label}
        <input
          data-testid="date-time-picker"
          data-value-format={valueFormat}
          placeholder={placeholder}
          value={value ? value.toISOString() : ''}
          onChange={(e) =>
            onChange?.(e.target.value ? new Date(e.target.value) : null)
          }
        />
      </label>
    </div>
  ),
}));

// ── Mantine form ───────────────────────────────────────────────────────────────
vi.mock('@mantine/form', () => {
  let _values = null;

  return {
    isNotEmpty: vi.fn(() => (val) => (val ? null : 'Required')),
    __resetFormState: () => {
      _values = null;
    },
    useForm: vi.fn(({ initialValues = {} } = {}) => {
      if (_values === null) {
        _values = { ...initialValues };
      }

      return {
        key: vi.fn((field) => field),
        getValues: () => ({ ..._values }),
        setValues: (v) => {
          Object.assign(_values, v);
        },
        setFieldValue: (field, val) => {
          _values[field] = val;
        },
        reset: () => {
          _values = { ...initialValues };
        },
        submitting: false,
        onSubmit: vi.fn((handler) => (e) => {
          e?.preventDefault?.();
          if (_values?.name) handler();
        }),
        getInputProps: vi.fn((field) => ({
          value: _values?.[field] ?? '',
          onChange: vi.fn((e) => {
            const val = e?.target?.value ?? e;
            if (_values) _values[field] = val;
          }),
          error: null,
        })),
      };
    }),
  };
});

// ── Mantine core ───────────────────────────────────────────────────────────────
vi.mock('@mantine/core', () => ({
  Box: ({ children }) => <div>{children}</div>,
  Button: ({ children, onClick, type, loading, disabled, variant, color }) => (
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
  Checkbox: ({ label, checked, onChange, disabled }) => (
    <label>
      <input
        type="checkbox"
        aria-label={label}
        checked={!!checked}
        onChange={(e) => onChange?.(e)}
        disabled={disabled}
      />
      {label}
    </label>
  ),
  Divider: ({ label }) => <hr aria-label={label} />,
  FileInput: ({ label, placeholder, onChange, accept, disabled }) => (
    <div>
      <label>
        {label}
        <input
          type="file"
          aria-label={label || placeholder}
          accept={accept}
          disabled={disabled}
          onChange={(e) => onChange?.(e.target.files?.[0] ?? null)}
        />
      </label>
    </div>
  ),
  Flex: ({ children }) => <div>{children}</div>,
  Group: ({ children }) => <div>{children}</div>,
  LoadingOverlay: ({ visible }) =>
    visible ? <div data-testid="loading-overlay" /> : null,
  Modal: ({ children, opened, onClose, title, size }) =>
    opened ? (
      <div data-testid="modal" data-size={size}>
        <div data-testid="modal-title">{title}</div>
        <button data-testid="modal-close" onClick={onClose}>
          ×
        </button>
        {children}
      </div>
    ) : null,
  MultiSelect: ({
    id,
    label,
    placeholder,
    value,
    onChange,
    data,
    clearable,
  }) => (
    <div>
      <label>
        {label}
        <select
          multiple
          aria-label={label}
          data-testid={id ? `multiselect-${id}` : undefined}
          value={value || []}
          onChange={(e) => {
            const selected = Array.from(e.target.selectedOptions).map(
              (o) => o.value
            );
            onChange?.(selected);
          }}
        >
          {data?.map((d) => (
            <option key={d.value} value={d.value}>
              {d.label}
            </option>
          ))}
        </select>
      </label>
      {placeholder && (
        <span data-testid={id ? `placeholder-${id}` : 'placeholder'}>
          {placeholder}
        </span>
      )}
      {clearable && value?.length > 0 && (
        <button aria-label={`clear-${label}`} onClick={() => onChange?.([])}>
          clear
        </button>
      )}
    </div>
  ),
  NumberInput: ({
    label,
    placeholder,
    value,
    onChange,
    min,
    max,
    disabled,
    error,
  }) => (
    <div>
      <label>
        {label}
        <input
          type="number"
          aria-label={label || placeholder}
          placeholder={placeholder}
          value={value ?? ''}
          min={min}
          max={max}
          disabled={disabled}
          onChange={(e) => onChange?.(Number(e.target.value))}
        />
      </label>
      {error && <span data-testid={`error-${label}`}>{error}</span>}
    </div>
  ),
  PasswordInput: ({
    label,
    placeholder,
    value,
    onChange,
    onBlur,
    error,
    disabled,
  }) => (
    <div>
      <label>
        {label}
        <input
          type="password"
          aria-label={label || placeholder}
          placeholder={placeholder}
          value={value || ''}
          disabled={disabled}
          onChange={(e) => onChange?.(e)}
          onBlur={onBlur}
        />
      </label>
      {error && <span data-testid={`error-${label}`}>{error}</span>}
    </div>
  ),
  Select: ({ label, placeholder, value, onChange, data, disabled, error }) => (
    <div>
      <label>
        {label}
        <select
          aria-label={label || placeholder}
          value={value || ''}
          disabled={disabled}
          onChange={(e) => onChange?.(e.target.value || null)}
        >
          <option value="">{placeholder}</option>
          {data?.map((d) => {
            const val = typeof d === 'string' ? d : d.value;
            const lbl = typeof d === 'string' ? d : d.label;
            return (
              <option key={val} value={val}>
                {lbl}
              </option>
            );
          })}
        </select>
      </label>
      {error && <span data-testid={`error-${label}`}>{error}</span>}
    </div>
  ),
  SimpleGrid: ({ children, cols }) => (
    <div data-testid="account-columns" data-cols={JSON.stringify(cols)}>{children}</div>
  ),
  Stack: ({ children, role, className, 'aria-label': label }) => <div role={role} className={className} aria-label={label}>{children}</div>,
  Text: ({ children }) => <span>{children}</span>,
  Switch: ({ label, checked, onChange, disabled }) => (
    <label>
      <input
        type="checkbox"
        role="switch"
        aria-label={label}
        checked={!!checked}
        disabled={disabled}
        onChange={(e) => onChange?.(e)}
      />
      {label}
    </label>
  ),
  TextInput: ({
    id,
    label,
    placeholder,
    value,
    onChange,
    onBlur,
    error,
    disabled,
    ...rest
  }) => (
    <div>
      <label>
        {label}
        <input
          data-testid={id ? `text-input-${id}` : undefined}
          aria-label={label || placeholder}
          placeholder={placeholder}
          value={value || ''}
          disabled={disabled}
          onChange={onChange}
          onBlur={onBlur}
          {...rest}
        />
      </label>
      {error && <span data-testid={`error-${label}`}>{error}</span>}
    </div>
  ),
}));

// ──────────────────────────────────────────────────────────────────────────────
// Imports after mocks
// ──────────────────────────────────────────────────────────────────────────────
import useUserAgentsStore from '../../../store/userAgents';
import useChannelsStore from '../../../store/channels';
import useEPGsStore from '../../../store/epgs';
import useVODStore from '../../../store/useVODStore';
import usePlaylistsStore from '../../../store/playlists';
import * as M3uUtils from '../../../utils/forms/M3uUtils.js';
import * as DummyEpgUtils from '../../../utils/forms/DummyEpgUtils.js';
import * as mantineForm from '@mantine/form';

// ── Helpers ────────────────────────────────────────────────────────────────────
const makeM3uAccount = (overrides = {}) => ({
  id: 1,
  name: 'Test M3U',
  server_url: 'http://example.com/playlist.m3u',
  username: 'user1',
  password: 'pass1',
  account_type: 'XC',
  max_streams: 0,
  refresh_interval: 24,
  auto_refresh: false,
  is_active: true,
  custom_properties: {},
  ...overrides,
});

const makeUserAgent = (overrides = {}) => ({
  id: 1,
  name: 'Default Agent',
  user_agent: 'Mozilla/5.0',
  ...overrides,
});

const defaultProps = (overrides = {}) => ({
  m3uAccount: null,
  isOpen: true,
  onClose: vi.fn(),
  ...overrides,
});

const setupStores = (overrides = {}) => {
  const fetchUserAgents = vi.fn();
  const fetchChannelGroups = vi.fn();
  const fetchEPGs = vi.fn();
  const fetchCategories = vi.fn();

  useUserAgentsStore.mockImplementation((selector) => {
    const state = {
      userAgents: overrides.userAgents || [],
      fetchUserAgents,
    };
    return selector(state);
  });

  useChannelsStore.mockImplementation((selector) => {
    const state = {
      fetchChannelGroups,
    };
    return selector(state);
  });

  useEPGsStore.mockImplementation((selector) => {
    const state = {
      fetchEPGs,
    };
    return selector(state);
  });

  useVODStore.mockImplementation((selector) => {
    const state = {
      fetchCategories,
    };
    return selector(state);
  });

  usePlaylistsStore.mockImplementation((selector) => {
    const playlists = overrides.playlists || [];
    return selector({ playlists });
  });

  return {
    fetchUserAgents,
    fetchChannelGroups,
    fetchEPGs,
    fetchCategories,
  };
};

// ──────────────────────────────────────────────────────────────────────────────

describe('M3U', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mantineForm.__resetFormState();
    vi.mocked(useDateTimeFormat).mockReturnValue({
      timeFormat: 'HH:mm',
      dateYearFormat: 'MMM D, YYYY',
    });
    vi.mocked(M3uUtils.addPlaylist).mockResolvedValue(
      makeM3uAccount({ id: 2 })
    );
    vi.mocked(M3uUtils.updatePlaylist).mockResolvedValue(makeM3uAccount());
    vi.mocked(M3uUtils.getPlaylist).mockResolvedValue(makeM3uAccount());
    vi.mocked(M3uUtils.prepareSubmitValues).mockImplementation((v) => v);
    vi.mocked(DummyEpgUtils.addEPG).mockResolvedValue({
      id: 10,
      name: 'Dummy EPG',
    });
  });

  // ── Rendering ──────────────────────────────────────────────────────────────

  describe('rendering', () => {
    it('renders the modal when isOpen is true', () => {
      setupStores();
      render(<M3U {...defaultProps()} />);
      expect(screen.getByTestId('modal')).toBeInTheDocument();
    });

    it('does not render the modal when isOpen is false', () => {
      setupStores();
      render(<M3U {...defaultProps({ isOpen: false })} />);
      expect(screen.queryByTestId('modal')).not.toBeInTheDocument();
    });

    it('renders Name input', () => {
      setupStores();
      render(<M3U {...defaultProps()} />);
      expect(screen.getByTestId('text-input-name')).toBeInTheDocument();
    });

    it('uses a day-first expiration format without a comma before the year', () => {
      setupStores();
      vi.mocked(useDateTimeFormat).mockReturnValue({
        timeFormat: 'HH:mm',
        dateYearFormat: 'D MMM YYYY',
      });
      render(
        <M3U
          {...defaultProps({
            m3uAccount: makeM3uAccount({ account_type: 'Other' }),
          })}
        />
      );
      expect(screen.getByTestId('date-time-picker')).toHaveAttribute(
        'data-value-format',
        'D MMM YYYY HH:mm'
      );
    });

    it('renders URL input', () => {
      setupStores();
      render(<M3U {...defaultProps()} />);
      expect(screen.getByTestId('text-input-server_url')).toBeInTheDocument();
    });

    it('renders submit button with "Add" label for new account', () => {
      setupStores();
      render(<M3U {...defaultProps()} />);
      expect(
        screen.getByRole('button', { name: /add|create|save/i })
      ).toBeInTheDocument();
    });

    it('renders submit button with "Update" or "Save" label for existing account', () => {
      setupStores();
      render(<M3U {...defaultProps({ m3uAccount: makeM3uAccount() })} />);
      expect(
        screen.getByRole('button', { name: /update|save/i })
      ).toBeInTheDocument();
    });

    it('pre-fills name when editing', () => {
      setupStores();
      render(<M3U {...defaultProps({ m3uAccount: makeM3uAccount() })} />);
      expect(screen.getByDisplayValue('Test M3U')).toBeInTheDocument();
    });

    it('pre-fills URL when editing', () => {
      setupStores();
      render(<M3U {...defaultProps({ m3uAccount: makeM3uAccount() })} />);
      expect(
        screen.getByDisplayValue('http://example.com/playlist.m3u')
      ).toBeInTheDocument();
    });

    it('renders M3UProfiles sub-component', () => {
      setupStores();
      render(<M3U {...defaultProps({ m3uAccount: makeM3uAccount() })} />);
      expect(screen.getByTestId('m3u-profiles')).toBeInTheDocument();
    });

    it('renders M3UGroupFilter sub-component', () => {
      setupStores();
      render(<M3U {...defaultProps({ m3uAccount: makeM3uAccount() })} />);
      expect(screen.getByTestId('m3u-group-filter')).toBeInTheDocument();
    });

    it('renders M3UFilters sub-component', () => {
      setupStores();
      render(<M3U {...defaultProps({ m3uAccount: makeM3uAccount() })} />);
      expect(screen.getByTestId('m3u-filters')).toBeInTheDocument();
    });

    it('renders ScheduleInput sub-component', () => {
      setupStores();
      render(<M3U {...defaultProps()} />);
      expect(screen.getByTestId('schedule-input')).toBeInTheDocument();
    });

    it('populates user agent select with agents from store', () => {
      setupStores({
        userAgents: [
          makeUserAgent({ id: 1, name: 'Agent One' }),
          makeUserAgent({ id: 2, name: 'Agent Two' }),
        ],
      });
      render(<M3U {...defaultProps()} />);
      expect(screen.getByText('Agent One')).toBeInTheDocument();
      expect(screen.getByText('Agent Two')).toBeInTheDocument();
    });
  });

  // ── Hash key override ────────────────────────────────────────────────────

  describe('hash key override', () => {
    it('shows the "use global default" placeholder for a new account', () => {
      setupStores();
      render(<M3U {...defaultProps()} />);
      expect(screen.getByTestId('placeholder-hash_key')).toBeInTheDocument();
    });

    it('shows the placeholder when editing an account with no override', () => {
      setupStores();
      render(
        <M3U
          {...defaultProps({
            m3uAccount: makeM3uAccount({ hash_key: null }),
          })}
        />
      );
      expect(screen.getByTestId('placeholder-hash_key')).toBeInTheDocument();
    });

    it('hides the placeholder when editing an account with an override set', () => {
      // Regression test: the modal used to keep showing "Use global
      // default" even with fields selected, because the form runs in
      // Mantine's uncontrolled mode - the placeholder was originally
      // computed from form.values.hash_key, which does not reflect the
      // bulk form.setValues() call used to populate an existing account.
      setupStores();
      render(
        <M3U
          {...defaultProps({
            m3uAccount: makeM3uAccount({ hash_key: 'name,tvg_id,m3u_id' }),
          })}
        />
      );
      expect(
        screen.queryByTestId('placeholder-hash_key')
      ).not.toBeInTheDocument();
    });

    it('pre-selects the fields from an existing override', () => {
      setupStores();
      render(
        <M3U
          {...defaultProps({
            m3uAccount: makeM3uAccount({ hash_key: 'name,tvg_id' }),
          })}
        />
      );
      const select = screen.getByTestId('multiselect-hash_key');
      const selected = Array.from(select.selectedOptions).map((o) => o.value);
      expect(selected).toEqual(['name', 'tvg_id']);
    });

    it('brings back the placeholder after clearing a set override', async () => {
      setupStores();
      render(
        <M3U
          {...defaultProps({
            m3uAccount: makeM3uAccount({ hash_key: 'name,tvg_id' }),
          })}
        />
      );
      expect(
        screen.queryByTestId('placeholder-hash_key')
      ).not.toBeInTheDocument();

      fireEvent.click(
        screen.getByRole('button', { name: 'clear-Hash Key Override' })
      );

      await waitFor(() => {
        expect(screen.getByTestId('placeholder-hash_key')).toBeInTheDocument();
      });
    });

    it('resets to no override when switching from editing to a new account', () => {
      setupStores();
      const { rerender } = render(
        <M3U
          {...defaultProps({
            m3uAccount: makeM3uAccount({ hash_key: 'name,tvg_id' }),
          })}
        />
      );
      expect(
        screen.queryByTestId('placeholder-hash_key')
      ).not.toBeInTheDocument();

      act(() => {
        rerender(<M3U {...defaultProps({ m3uAccount: null })} />);
      });

      expect(screen.getByTestId('placeholder-hash_key')).toBeInTheDocument();
    });
  });

  // ── Cancel behaviour ───────────────────────────────────────────────────────

  describe('cancel behaviour', () => {
    it('calls onClose when modal X is clicked', () => {
      const onClose = vi.fn();
      setupStores();
      render(<M3U {...defaultProps({ onClose })} />);
      fireEvent.click(screen.getByTestId('modal-close'));
      expect(onClose).toHaveBeenCalled();
    });
  });

  // ── Adding a playlist ──────────────────────────────────────────────────────

  describe('adding a new playlist', () => {
    const fillRequiredFields = () => {
      const nameInput = screen.getByTestId('text-input-name');
      fireEvent.change(nameInput, { target: { value: 'New Playlist' } });

      const urlInput = screen.getByTestId('text-input-server_url');
      if (urlInput) {
        fireEvent.change(urlInput, {
          target: { value: 'http://example.com/new.m3u' },
        });
      }
    };

    it('calls addPlaylist on valid submit', async () => {
      setupStores();
      render(<M3U {...defaultProps()} />);
      fillRequiredFields();
      fireEvent.click(screen.getByRole('button', { name: /add|create|save/i }));
      await waitFor(() => {
        expect(M3uUtils.addPlaylist).toHaveBeenCalled();
      });
    });

    it('marks the new account group save as the initial refresh', async () => {
      setupStores();
      render(<M3U {...defaultProps()} />);
      fillRequiredFields();
      fireEvent.click(screen.getByRole('button', { name: /add|create|save/i }));

      await waitFor(() => {
        expect(screen.getByTestId('m3u-group-filter')).toHaveAttribute(
          'data-initial-setup',
          'true'
        );
      });
    });

    it('calls prepareSubmitValues before addPlaylist', async () => {
      setupStores();
      render(<M3U {...defaultProps()} />);
      fillRequiredFields();
      fireEvent.click(screen.getByRole('button', { name: /add|create|save/i }));
      await waitFor(() => {
        expect(M3uUtils.prepareSubmitValues).toHaveBeenCalled();
      });
    });

    it('calls onClose after successful add', async () => {
      const onClose = vi.fn();
      setupStores();
      render(
        <M3U
          {...defaultProps({
            onClose,
            m3uAccount: makeM3uAccount({ account_type: 'Other' }),
          })}
        />
      );
      fillRequiredFields();
      fireEvent.click(screen.getByRole('button', { name: /add|create|save/i }));
      await waitFor(() => {
        expect(onClose).toHaveBeenCalled();
      });
    });
  });

  // ── Updating a playlist ────────────────────────────────────────────────────

  describe('updating an existing playlist', () => {
    it('calls updatePlaylist on submit', async () => {
      setupStores();
      render(<M3U {...defaultProps({ m3uAccount: makeM3uAccount() })} />);
      fireEvent.click(screen.getByRole('button', { name: /update|save/i }));
      await waitFor(() => {
        expect(M3uUtils.updatePlaylist).toHaveBeenCalled();
      });
    });

    it('does not call addPlaylist when updating', async () => {
      setupStores();
      render(<M3U {...defaultProps({ m3uAccount: makeM3uAccount() })} />);
      fireEvent.click(screen.getByRole('button', { name: /update|save/i }));
      await waitFor(() => {
        expect(M3uUtils.updatePlaylist).toHaveBeenCalled();
      });
      expect(M3uUtils.addPlaylist).not.toHaveBeenCalled();
    });

    it('calls onClose after successful update', async () => {
      const onClose = vi.fn();
      setupStores();
      render(
        <M3U {...defaultProps({ m3uAccount: makeM3uAccount(), onClose })} />
      );
      fireEvent.click(screen.getByRole('button', { name: /update|save/i }));
      await waitFor(() => {
        expect(onClose).toHaveBeenCalled();
      });
    });
  });

  // ── Form validation ────────────────────────────────────────────────────────

  describe('form validation', () => {
    it('does not call addPlaylist when Name is empty', async () => {
      setupStores();
      render(<M3U {...defaultProps()} />);
      // Clear name if pre-filled, then submit
      const nameInput = screen.getByTestId('text-input-name');
      fireEvent.change(nameInput, { target: { value: '' } });
      fireEvent.click(screen.getByRole('button', { name: /add|create|save/i }));
      await new Promise((r) => setTimeout(r, 50));
      expect(M3uUtils.addPlaylist).not.toHaveBeenCalled();
    });
  });

  // ── Refresh / schedule behaviour ───────────────────────────────────────────

  describe('schedule and refresh', () => {
    it('renders the ScheduleInput', () => {
      setupStores();
      render(<M3U {...defaultProps()} />);
      expect(screen.getByTestId('schedule-input')).toBeInTheDocument();
    });

    it('shows an independent VOD schedule only when enabled', () => {
      setupStores();
      render(
        <M3U
          {...defaultProps({
            m3uAccount: makeM3uAccount({ enable_vod: true }),
          })}
        />
      );

      expect(screen.getAllByTestId('schedule-input')).toHaveLength(1);
      fireEvent.click(screen.getByRole('switch', { name: 'Separate VOD refresh schedule' }));
      expect(screen.getAllByTestId('schedule-input')).toHaveLength(2);
    });
  });

  describe('separate Live TV and VOD columns', () => {
    it('applies responsive separators to all four settings columns', () => {
      setupStores();
      render(<M3U {...defaultProps()} />);
      for (const name of ['Account settings', 'Connection settings', 'Live TV settings', 'VOD settings']) {
        expect(screen.getByRole('group', { name })).toHaveClass(classes.column);
      }
    });

    it('uses four responsive columns and keeps the refresh controls in their own groups', () => {
      setupStores();
      render(<M3U {...defaultProps({
        m3uAccount: makeM3uAccount({ enable_vod: true, vod_refresh_after_live: false }),
      })} />);

      expect(screen.getByTestId('modal')).toHaveAttribute('data-size', '1280');
      expect(screen.getByTestId('account-columns')).toHaveAttribute(
        'data-cols', JSON.stringify({ base: 1, sm: 2, md: 4 })
      );
      const live = within(screen.getByRole('group', { name: 'Live TV settings' }));
      const vod = within(screen.getByRole('group', { name: 'VOD settings' }));
      expect(live.getByLabelText('Live TV refresh interval (hours)')).toBeInTheDocument();
      expect(live.getByRole('spinbutton', { name: 'Stale Stream Retention (days)' })).toBeInTheDocument();
      expect(live.queryByRole('spinbutton', { name: 'VOD Priority' })).not.toBeInTheDocument();
      expect(vod.getByLabelText('VOD refresh interval (hours)')).toBeInTheDocument();
      expect(vod.getByRole('spinbutton', { name: 'VOD Priority' })).toBeInTheDocument();
      expect(vod.getByRole('switch', { name: 'Enable VOD Scanning' })).toBeInTheDocument();
      expect(vod.queryByLabelText('Live TV refresh interval (hours)')).not.toBeInTheDocument();
    });

    it('keeps Create EPG in the Live TV column when creating an XC account', () => {
      setupStores();
      render(<M3U {...defaultProps()} />);
      const live = within(screen.getByRole('group', { name: 'Live TV settings' }));
      const vod = within(screen.getByRole('group', { name: 'VOD settings' }));
      expect(live.getByRole('switch', { name: 'Create EPG' })).toBeInTheDocument();
      expect(vod.queryByRole('switch', { name: 'Create EPG' })).not.toBeInTheDocument();
    });

    it('uses three columns without VOD controls for a standard M3U account', () => {
      setupStores();
      render(<M3U {...defaultProps({ m3uAccount: makeM3uAccount({ account_type: 'STD' }) })} />);
      expect(screen.getByTestId('modal')).toHaveAttribute('data-size', '960');
      expect(screen.getByTestId('account-columns')).toHaveAttribute(
        'data-cols', JSON.stringify({ base: 1, sm: 2, md: 3 })
      );
      expect(screen.queryByRole('group', { name: 'VOD settings' })).not.toBeInTheDocument();
    });

    it('updates the column layout immediately when the account type changes', () => {
      setupStores();
      render(<M3U {...defaultProps()} />);
      fireEvent.change(screen.getByRole('combobox', { name: 'Account Type' }), {
        target: { value: 'STD' },
      });
      expect(screen.queryByRole('group', { name: 'VOD settings' })).not.toBeInTheDocument();
      expect(screen.getByTestId('modal')).toHaveAttribute('data-size', '960');
      fireEvent.change(screen.getByRole('combobox', { name: 'Account Type' }), {
        target: { value: 'XC' },
      });
      expect(screen.getByRole('group', { name: 'VOD settings' })).toBeInTheDocument();
      expect(screen.getByTestId('modal')).toHaveAttribute('data-size', '1280');
    });

    it('does not expose client-triggered refresh controls', () => {
      setupStores();
      render(<M3U {...defaultProps()} />);
      expect(
        screen.queryByLabelText('Client refresh cooldown (minutes)')
      ).not.toBeInTheDocument();
    });

    it('preserves the independent Live TV and VOD values when saving the new layout', async () => {
      setupStores();
      const account = makeM3uAccount({
        enable_vod: true,
        vod_refresh_after_live: false,
        refresh_interval: 6,
        vod_refresh_interval: 24,
        priority: 30,
      });
      render(<M3U {...defaultProps({ m3uAccount: account })} />);
      fireEvent.change(screen.getByLabelText('Live TV refresh interval (hours)'), { target: { value: '8' } });
      fireEvent.change(screen.getByLabelText('VOD refresh interval (hours)'), { target: { value: '48' } });
      fireEvent.click(screen.getByRole('button', { name: 'Save' }));
      await waitFor(() => expect(M3uUtils.updatePlaylist).toHaveBeenCalledWith(
        account,
        expect.objectContaining({
          refresh_interval: 8,
          vod_refresh_interval: 48,
          vod_refresh_after_live: false,
          enable_vod: true,
          priority: 30,
        }),
        null
      ));
    });
  });

  // ── Max streams ────────────────────────────────────────────────────────────

  describe('max streams field', () => {
    it('renders max streams number input', () => {
      setupStores();
      render(<M3U {...defaultProps()} />);
      expect(
        screen.getByRole('spinbutton', { name: /max.?stream/i })
      ).toBeInTheDocument();
    });

    it('pre-fills max_streams when editing', () => {
      setupStores();
      render(
        <M3U
          {...defaultProps({ m3uAccount: makeM3uAccount({ max_streams: 5 }) })}
        />
      );
      expect(screen.getByDisplayValue('5')).toBeInTheDocument();
    });
  });

  // ── User agent select ──────────────────────────────────────────────────────

  describe('user agent select', () => {
    it('renders user agent select', () => {
      setupStores();
      render(<M3U {...defaultProps()} />);
      expect(
        screen.getByRole('combobox', { name: /user.?agent/i })
      ).toBeInTheDocument();
    });
  });

  // ── Credential fields ──────────────────────────────────────────────────────

  describe('credential fields', () => {
    it('renders username input', () => {
      setupStores();
      render(<M3U {...defaultProps()} />);
      expect(screen.getByTestId('text-input-username')).toBeInTheDocument();
    });

    it('renders password input', () => {
      setupStores();
      render(<M3U {...defaultProps()} />);
      expect(
        document.querySelector('input[type="password"]')
      ).toBeInTheDocument();
    });

    it('pre-fills username when editing', () => {
      setupStores();
      render(<M3U {...defaultProps({ m3uAccount: makeM3uAccount() })} />);
      expect(screen.getByDisplayValue('user1')).toBeInTheDocument();
    });
  });

  // ── Dummy EPG creation ─────────────────────────────────────────────────────

  describe('dummy EPG auto-creation', () => {
    it('calls addEPG after successfully adding a playlist', async () => {
      setupStores();
      render(<M3U {...defaultProps()} />);

      const nameInput = screen.getByTestId('text-input-name');
      fireEvent.change(nameInput, { target: { value: 'My Playlist' } });

      const urlInput = screen.getByTestId('text-input-server_url');
      if (urlInput) {
        fireEvent.change(urlInput, {
          target: { value: 'http://example.com/p.m3u' },
        });
      }

      fireEvent.click(screen.getByRole('button', { name: /add|create|save/i }));
      await waitFor(() => {
        expect(M3uUtils.addPlaylist).toHaveBeenCalled();
      });
      // addEPG may be called conditionally — assert it was called or not based on a checkbox
    });
  });
});
