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
import editorClasses from '../AccountEditor.module.css';
import { Modal } from '@mantine/core';

Modal.Stack = ({ children }) => <>{children}</>;
import API from '../../../api.js';

vi.mock('../../../api.js', () => ({
  default: { checkM3UConnection: vi.fn() },
}));

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
  useTimeHelpers: () => ({
    toUserTime: (value) => ({ format: (pattern) => `${pattern}: ${value}` }),
  }),
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
  default: ({ onChange, isInitialSetup, isOpen, onClose }) => (
    <div
      data-testid="m3u-group-filter"
      data-initial-setup={String(isInitialSetup)}
      data-open={String(isOpen)}
    >
      <button onClick={() => onChange?.([])}>M3UGroupFilter</button>
      <button onClick={onClose}>Close groups</button>
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

vi.mock('../M3USetupSteps.jsx', () => ({
  default: ({ onSelect, contentAvailable }) => (
    <div aria-label="M3U setup progress">
      <button type="button" onClick={() => onSelect?.('account')}>
        Account step
      </button>
      <button
        type="button"
        disabled={!contentAvailable}
        onClick={() => onSelect?.('content')}
      >
        Content step
      </button>
    </div>
  ),
}));
vi.mock('../M3UAccountEPG.jsx', () => ({
  default: ({ onOverlayChange }) => (
    <div data-testid="account-epg">
      <button type="button" onClick={() => onOverlayChange?.(true)}>
        Open EPG editor
      </button>
      <button type="button" onClick={() => onOverlayChange?.(false)}>
        Close EPG editor
      </button>
    </div>
  ),
}));
vi.mock('../M3UAccountCategories.jsx', () => ({
  default: ({ account, onEdit }) => (
    <div data-testid="account-categories" data-saved-name={account.name}>
      <button type="button" onClick={() => onEdit(account)}>
        Edit selection
      </button>
    </div>
  ),
}));
vi.mock('../../ConfirmationDialog.jsx', () => ({
  default: ({
    opened,
    title,
    message,
    confirmLabel = 'Discard',
    onConfirm,
    onClose,
  }) =>
    opened ? (
      <div role="dialog" aria-label={title}>
        <p>{message}</p>
        <button onClick={onConfirm}>{confirmLabel}</button>
        <button onClick={onClose}>Keep editing</button>
      </div>
    ) : null,
}));

// ── Mantine dates ──────────────────────────────────────────────────────────────
vi.mock('@mantine/dates', () => ({
  DateTimePicker: ({
    label,
    value,
    onChange,
    placeholder,
    valueFormat,
    'aria-label': ariaLabel,
  }) => (
    <div>
      <label>
        {label}
        <input
          data-testid="date-time-picker"
          aria-label={ariaLabel || label}
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
  let _dirtyValues = null;
  let _initialValues = null;

  return {
    isNotEmpty: vi.fn(() => (val) => (val ? null : 'Required')),
    __resetFormState: () => {
      _values = null;
      _dirtyValues = null;
      _initialValues = null;
    },
    useForm: vi.fn(({ initialValues = {} } = {}) => {
      if (_values === null) {
        _values = { ...initialValues };
        _initialValues = { ...initialValues };
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
          _values = { ..._initialValues };
          _dirtyValues = { ..._initialValues };
        },
        setInitialValues: (values) => {
          _initialValues = { ...values };
        },
        resetDirty: vi.fn(() => {
          _dirtyValues = { ..._values };
          _initialValues = { ..._values };
        }),
        submitting: false,
        setErrors: vi.fn(),
        clearErrors: vi.fn(),
        clearFieldError: vi.fn(),
        errors: {},
        isDirty: () =>
          JSON.stringify(_values) !==
          JSON.stringify(_dirtyValues || initialValues),
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
  useModalStackContext: () => null,
  Tabs: ({ children, onChange }) => (
    <div
      onClick={(event) => {
        if (event.target.dataset.value) onChange?.(event.target.dataset.value);
      }}
    >
      {children}
    </div>
  ),
  TabsList: ({ children }) => <div role="tablist">{children}</div>,
  TabsTab: ({ children, value, disabled }) => (
    <button type="button" role="tab" data-value={value} disabled={disabled}>
      {children}
    </button>
  ),
  TabsPanel: ({ children, className }) => (
    <div className={className}>{children}</div>
  ),
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
  FileInput: ({
    label,
    placeholder,
    onChange,
    accept,
    disabled,
    description,
    leftSection,
    error,
    'aria-label': ariaLabel,
  }) => (
    <div>
      <label>
        {label}
        {leftSection}
        <input
          type="file"
          aria-label={ariaLabel || label || placeholder}
          accept={accept}
          disabled={disabled}
          placeholder={placeholder}
          onChange={(e) => onChange?.(e.target.files?.[0] ?? null)}
        />
      </label>
      {description && <span>{description}</span>}
      {error && <span>{error}</span>}
    </div>
  ),
  Flex: ({ children, className, component, 'aria-label': ariaLabel }) => (
    <div
      role={component === 'footer' ? 'contentinfo' : undefined}
      className={className}
      aria-label={ariaLabel}
    >
      {children}
    </div>
  ),
  Group: ({ children }) => <div>{children}</div>,
  Paper: ({ children, display }) => (
    <div data-testid="settings-box" style={{ display }}>
      {children}
    </div>
  ),
  Tooltip: ({ children, label }) => <span data-help={label}>{children}</span>,
  LoadingOverlay: ({ visible }) =>
    visible ? <div data-testid="loading-overlay" /> : null,
  Modal: ({
    children,
    opened,
    onClose,
    title,
    size,
    classNames,
    closeOnEscape,
  }) =>
    opened ? (
      <div
        data-testid="modal"
        data-size={size}
        data-content-class={classNames?.content}
        data-close-on-escape={String(closeOnEscape ?? true)}
      >
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
    'aria-label': ariaLabel,
  }) => (
    <div>
      <label>
        {label}
        <select
          multiple
          aria-label={ariaLabel || label}
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
        <button
          aria-label={`clear-${ariaLabel || label}`}
          onClick={() => onChange?.([])}
        >
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
    'aria-label': ariaLabel,
  }) => (
    <div>
      <label>
        {label}
        <input
          type="number"
          aria-label={ariaLabel || label || placeholder}
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
  Select: ({
    label,
    placeholder,
    value,
    onChange,
    data,
    disabled,
    error,
    'aria-label': ariaLabel,
  }) => (
    <div>
      <label>
        {label}
        <select
          aria-label={ariaLabel || label || placeholder}
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
    <div data-testid="account-columns" data-cols={JSON.stringify(cols)}>
      {children}
    </div>
  ),
  Stack: ({ children, role, className, 'aria-label': label }) => (
    <div role={role} className={className} aria-label={label}>
      {children}
    </div>
  ),
  Text: ({ children }) => <span>{children}</span>,
  Switch: ({ label, checked, onChange, disabled, 'aria-label': ariaLabel }) => (
    <label>
      <input
        type="checkbox"
        role="switch"
        aria-label={ariaLabel || label}
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
    API.checkM3UConnection.mockResolvedValue({ success: true });
    mantineForm.__resetFormState();
    vi.mocked(useDateTimeFormat).mockReturnValue({
      timeFormat: 'HH:mm',
      dateYearFormat: 'MMM D, YYYY',
      fullDateTimeFormat: 'DD/MM/YYYY, HH:mm:ss',
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

    it('uses creation labels for a new account', () => {
      setupStores();
      render(<M3U {...defaultProps()} />);
      expect(screen.getByTestId('modal-title')).toHaveTextContent(
        'Create M3U account'
      );
      expect(screen.getByRole('button', { name: 'Next' })).toBeInTheDocument();
    });

    it('uses editing labels for an existing account', () => {
      setupStores();
      render(<M3U {...defaultProps({ m3uAccount: makeM3uAccount() })} />);
      expect(screen.getByTestId('modal-title')).toHaveTextContent(
        'Edit M3U account'
      );
      expect(screen.getByRole('button', { name: 'Save' })).toBeInTheDocument();
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

    it('does not duplicate Stream filters in the account editor', () => {
      setupStores();
      render(<M3U {...defaultProps({ m3uAccount: makeM3uAccount() })} />);
      expect(screen.queryByTestId('m3u-filters')).not.toBeInTheDocument();
      expect(
        screen.queryByRole('button', { name: 'Filters' })
      ).not.toBeInTheDocument();
      expect(screen.getByRole('tab', { name: 'Content' })).toBeInTheDocument();
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
    const fillRequiredFields = async () => {
      const nameInput = screen.getByTestId('text-input-name');
      fireEvent.change(nameInput, { target: { value: 'New Playlist' } });

      const urlInput = screen.getByTestId('text-input-server_url');
      if (urlInput) {
        fireEvent.change(urlInput, {
          target: { value: 'http://example.com/new.m3u' },
        });
      }
      fireEvent.change(screen.getByTestId('text-input-username'), {
        target: { value: 'example-user' },
      });
      fireEvent.change(document.querySelector('input[type="password"]'), {
        target: { value: 'example-password' },
      });
      fireEvent.click(screen.getByRole('button', { name: 'Next' }));
      await waitFor(() =>
        expect(screen.getByRole('button', { name: 'Back' })).toBeInTheDocument()
      );
    };

    it('calls addPlaylist on valid submit', async () => {
      setupStores();
      render(<M3U {...defaultProps()} />);
      await fillRequiredFields();
      fireEvent.click(screen.getByRole('button', { name: 'Next' }));
      await waitFor(() => {
        expect(M3uUtils.addPlaylist).toHaveBeenCalled();
      });
      expect(M3uUtils.addPlaylist.mock.calls[0][0].is_active).toBe(true);
    });

    it('does not offer an EPG when account creation returns no account', async () => {
      setupStores();
      vi.mocked(M3uUtils.addPlaylist).mockResolvedValueOnce(undefined);
      render(<M3U {...defaultProps()} />);
      await fillRequiredFields();
      fireEvent.click(screen.getByRole('button', { name: 'Next' }));
      await waitFor(() =>
        expect(M3uUtils.addPlaylist).toHaveBeenCalledTimes(1)
      );
      expect(
        screen.queryByText('Create matching EPG source?')
      ).not.toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Next' })).toBeEnabled();
      expect(DummyEpgUtils.addEPG).not.toHaveBeenCalled();
    });

    it('hands the persisted account to its resumable setup', async () => {
      const onClose = vi.fn();
      setupStores();
      render(<M3U {...defaultProps({ onClose })} />);
      await fillRequiredFields();
      fireEvent.click(screen.getByRole('button', { name: 'Next' }));
      await waitFor(() =>
        expect(onClose).toHaveBeenCalledWith(expect.objectContaining({ id: 2 }))
      );
      expect(M3uUtils.addPlaylist).toHaveBeenCalledWith(
        expect.objectContaining({ start_setup: true }),
        null
      );
    });

    it('calls prepareSubmitValues before addPlaylist', async () => {
      setupStores();
      render(<M3U {...defaultProps()} />);
      await fillRequiredFields();
      fireEvent.click(screen.getByRole('button', { name: 'Next' }));
      await waitFor(() => {
        expect(M3uUtils.prepareSubmitValues).toHaveBeenCalled();
      });
    });

    it('calls onClose after successful add', async () => {
      const onClose = vi.fn();
      setupStores();
      render(<M3U {...defaultProps({ onClose })} />);
      await fillRequiredFields();
      fireEvent.click(screen.getByRole('button', { name: 'Next' }));
      await waitFor(() => {
        expect(onClose).toHaveBeenCalled();
      });
    });
  });

  // ── Updating a playlist ────────────────────────────────────────────────────

  describe('updating an existing playlist', () => {
    it('saves only the chosen file source instead of the old URL', async () => {
      setupStores();
      const account = makeM3uAccount();
      render(<M3U {...defaultProps({ m3uAccount: account })} />);
      fireEvent.change(screen.getByRole('combobox', { name: 'Account Type' }), {
        target: { value: 'M3U_FILE' },
      });
      expect(screen.queryByLabelText('URL')).not.toBeInTheDocument();
      expect(screen.queryByLabelText('Username')).not.toBeInTheDocument();
      const file = new File(['#EXTM3U'], 'example.m3u');
      fireEvent.change(screen.getByLabelText('Playlist file'), {
        target: { files: [file] },
      });
      fireEvent.click(screen.getByRole('button', { name: 'Save' }));
      await waitFor(() =>
        expect(M3uUtils.updatePlaylist).toHaveBeenCalledWith(
          account,
          expect.objectContaining({
            account_type: 'STD',
            server_url: '',
            username: '',
            password: '',
          }),
          file
        )
      );
    });

    it('does not submit a hidden file after switching to URL input', async () => {
      setupStores();
      const account = makeM3uAccount({ account_type: 'STD' });
      render(<M3U {...defaultProps({ m3uAccount: account })} />);
      const type = screen.getByRole('combobox', { name: 'Account Type' });
      expect(type).toHaveValue('M3U_URL');
      expect(screen.queryByLabelText('Playlist file')).not.toBeInTheDocument();
      fireEvent.change(type, { target: { value: 'M3U_FILE' } });
      fireEvent.change(screen.getByLabelText('Playlist file'), {
        target: { files: [new File(['#EXTM3U'], 'hidden.m3u')] },
      });
      fireEvent.change(type, { target: { value: 'M3U_URL' } });
      fireEvent.click(screen.getByRole('button', { name: 'Save' }));
      await waitFor(() =>
        expect(M3uUtils.updatePlaylist).toHaveBeenCalledWith(
          account,
          expect.objectContaining({
            account_type: 'STD',
            server_url: account.server_url,
            file_path: '',
          }),
          null
        )
      );
    });

    it('keeps the saved playlist file without uploading it again', async () => {
      setupStores();
      const account = makeM3uAccount({
        account_type: 'STD',
        server_url: '',
        file_path: '/data/uploads/m3us/example.m3u',
      });
      render(<M3U {...defaultProps({ m3uAccount: account })} />);
      fireEvent.click(screen.getByRole('button', { name: 'Save' }));
      await waitFor(() =>
        expect(M3uUtils.updatePlaylist).toHaveBeenCalledWith(
          account,
          expect.objectContaining({ account_type: 'STD', server_url: '' }),
          null
        )
      );
      expect(M3uUtils.updatePlaylist.mock.calls[0][1]).not.toHaveProperty(
        'file_path'
      );
    });

    it('passes the saved account to the continuation callback', async () => {
      const onSaved = vi.fn();
      const onClose = vi.fn();
      const saved = makeM3uAccount({
        account_type: 'STD',
        setup_step: 'categories',
      });
      setupStores();
      vi.mocked(M3uUtils.updatePlaylist).mockResolvedValueOnce(saved);
      render(
        <M3U
          {...defaultProps({
            m3uAccount: makeM3uAccount({ setup_step: 'epg' }),
            onClose,
            onSaved,
          })}
        />
      );
      fireEvent.click(screen.getByRole('button', { name: 'Save' }));
      await waitFor(() =>
        expect(onSaved).toHaveBeenCalledExactlyOnceWith(saved)
      );
      expect(onClose).not.toHaveBeenCalled();
    });

    it('keeps failed corrections open without resuming setup', async () => {
      const onSaved = vi.fn();
      const onClose = vi.fn();
      setupStores();
      vi.mocked(M3uUtils.updatePlaylist)
        .mockResolvedValueOnce(undefined)
        .mockResolvedValueOnce(undefined);
      render(
        <M3U
          {...defaultProps({
            m3uAccount: makeM3uAccount({ setup_step: 'epg' }),
            onClose,
            onSaved,
          })}
        />
      );
      fireEvent.change(screen.getByTestId('text-input-name'), {
        target: { value: 'Corrected account' },
      });
      fireEvent.click(screen.getByRole('button', { name: 'Save' }));
      await waitFor(() =>
        expect(M3uUtils.updatePlaylist).toHaveBeenCalledOnce()
      );
      fireEvent.click(screen.getByRole('button', { name: 'Save' }));
      await waitFor(() =>
        expect(M3uUtils.updatePlaylist).toHaveBeenCalledTimes(2)
      );
      expect(onSaved).not.toHaveBeenCalled();
      expect(onClose).not.toHaveBeenCalled();
      expect(M3uUtils.updatePlaylist).toHaveBeenLastCalledWith(
        expect.anything(),
        expect.objectContaining({ name: 'Corrected account' }),
        null
      );
    });

    it('does not write the editor snapshot of enabled state when saving', async () => {
      setupStores();
      render(
        <M3U
          {...defaultProps({
            m3uAccount: makeM3uAccount({ is_active: false }),
          })}
        />
      );
      expect(
        screen.getByText('Disabled — enable this account from the overview.')
      ).toBeInTheDocument();
      fireEvent.click(screen.getByRole('button', { name: 'Save' }));
      await waitFor(() => expect(M3uUtils.updatePlaylist).toHaveBeenCalled());
      expect(M3uUtils.updatePlaylist.mock.calls[0][1]).not.toHaveProperty(
        'is_active'
      );
    });
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
      fireEvent.click(screen.getByRole('button', { name: 'Next' }));
      await new Promise((r) => setTimeout(r, 50));
      expect(M3uUtils.addPlaylist).not.toHaveBeenCalled();
    });
  });

  // ── Refresh / schedule behaviour ───────────────────────────────────────────

  describe('schedule and refresh', () => {
    it('shows saved Live and VOD completion times separately using the selected date format', () => {
      const account = makeM3uAccount({
        enable_vod: true,
        vod_refresh_after_live: false,
        updated_at: '2026-10-14T08:00:00Z',
        live_refresh_schedule: {
          enabled: true,
          next_run_at: '2026-10-14T14:00:00Z',
        },
        vod_refresh_schedule: {
          enabled: true,
          next_run_at: '2026-10-15T03:00:00Z',
        },
        custom_properties: {
          refresh_timings: { vod_completed_at: '2026-10-14T03:05:00Z' },
        },
      });
      setupStores({ playlists: [account] });
      render(<M3U {...defaultProps({ m3uAccount: account })} />);
      expect(
        screen.getByRole('group', { name: 'Live TV refresh schedule' })
      ).toHaveTextContent('Last: DD/MM/YYYY, HH:mm:ss: 2026-10-14T08:00:00Z');
      expect(
        screen.getByRole('group', { name: 'VOD refresh schedule' })
      ).toHaveTextContent('Last: DD/MM/YYYY, HH:mm:ss: 2026-10-14T03:05:00Z');
      expect(
        screen.getByRole('group', { name: 'VOD refresh schedule' })
      ).toHaveTextContent('Next: DD/MM/YYYY, HH:mm:ss: 2026-10-15T03:00:00Z');
    });

    it('shows VOD following the saved Live schedule without a fake separate next run', () => {
      const account = makeM3uAccount({
        enable_vod: true,
        vod_refresh_after_live: true,
        live_refresh_schedule: { enabled: true },
        vod_refresh_schedule: { enabled: false },
      });
      setupStores({ playlists: [account] });
      render(<M3U {...defaultProps({ m3uAccount: account })} />);
      expect(
        screen.getByRole('group', { name: 'VOD refresh schedule' })
      ).toHaveTextContent('Next: After Live TV refresh');
    });

    it('disables VOD settings until scanning is enabled without discarding its priority', () => {
      setupStores();
      render(
        <M3U
          {...defaultProps({
            m3uAccount: makeM3uAccount({ enable_vod: false, priority: 15 }),
          })}
        />
      );
      expect(
        screen.getByRole('spinbutton', { name: 'VOD Priority' })
      ).toBeDisabled();
      expect(
        screen.getByRole('spinbutton', { name: 'VOD Priority' })
      ).toHaveValue(15);
      expect(
        screen.getByRole('switch', {
          name: 'Enable separate VOD refresh schedule',
        })
      ).toBeDisabled();
    });
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
      fireEvent.click(
        screen.getByRole('switch', {
          name: 'Enable separate VOD refresh schedule',
        })
      );
      expect(screen.getAllByTestId('schedule-input')).toHaveLength(2);
    });
  });

  describe('account and content tabs', () => {
    it('leaves Escape to nested EPG dialogs', () => {
      setupStores();
      render(<M3U {...defaultProps({ m3uAccount: makeM3uAccount() })} />);
      fireEvent.click(screen.getByRole('tab', { name: 'EPG' }));
      fireEvent.click(screen.getByRole('button', { name: 'Open EPG editor' }));
      expect(screen.getByTestId('modal')).toHaveAttribute(
        'data-close-on-escape',
        'false'
      );
      fireEvent.click(screen.getByRole('button', { name: 'Close EPG editor' }));
      expect(screen.getByTestId('modal')).toHaveAttribute(
        'data-close-on-escape',
        'true'
      );
      expect(M3uUtils.updatePlaylist).not.toHaveBeenCalled();
    });
    it('keeps Settings, EPG and the shared category selection in separate tabs', () => {
      setupStores();
      render(
        <M3U
          {...defaultProps({
            m3uAccount: makeM3uAccount({ enable_vod: true }),
          })}
        />
      );
      expect(screen.getAllByRole('tab').map((tab) => tab.textContent)).toEqual([
        'Account',
        'Settings',
        'EPG',
        'Content',
        'Profiles',
      ]);
      fireEvent.click(screen.getByRole('tab', { name: 'Settings' }));
      expect(screen.queryByTestId('account-epg')).not.toBeInTheDocument();
      expect(
        screen.queryByTestId('account-categories')
      ).not.toBeInTheDocument();
      fireEvent.click(screen.getByRole('tab', { name: 'EPG' }));
      expect(screen.getByTestId('account-epg')).toBeInTheDocument();
      fireEvent.click(screen.getByRole('tab', { name: 'Content' }));
      expect(screen.queryByTestId('account-epg')).not.toBeInTheDocument();
      expect(screen.getByTestId('account-categories')).toBeInTheDocument();
      fireEvent.click(screen.getByRole('button', { name: 'Edit selection' }));
      expect(screen.getByTestId('m3u-group-filter')).toHaveAttribute(
        'data-open',
        'true'
      );
      expect(M3uUtils.updatePlaylist).not.toHaveBeenCalled();
    });
    it('keeps the account editor open while a nested groups dialog handles Escape', () => {
      const onClose = vi.fn();
      setupStores();
      render(
        <M3U {...defaultProps({ m3uAccount: makeM3uAccount(), onClose })} />
      );
      expect(screen.getByTestId('modal')).toHaveAttribute(
        'data-close-on-escape',
        'true'
      );
      fireEvent.click(screen.getByRole('tab', { name: 'Content' }));
      fireEvent.click(screen.getByRole('button', { name: 'Edit selection' }));
      expect(screen.getByTestId('modal')).toHaveAttribute(
        'data-close-on-escape',
        'false'
      );
      fireEvent.click(screen.getByRole('button', { name: 'Close groups' }));
      expect(screen.getByTestId('modal')).toHaveAttribute(
        'data-close-on-escape',
        'true'
      );
      expect(onClose).not.toHaveBeenCalled();
      expect(screen.getByTestId('account-categories')).toBeInTheDocument();
    });
    it('keeps only Save in the fixed footer and category actions in their topic', () => {
      setupStores();
      render(<M3U {...defaultProps({ m3uAccount: makeM3uAccount() })} />);
      const footer = screen.getByRole('contentinfo', {
        name: 'M3U account actions',
      });
      expect(footer).toHaveClass(editorClasses.footer);
      expect(
        within(footer).queryByRole('button', { name: 'Categories' })
      ).not.toBeInTheDocument();
      expect(
        within(footer).getByRole('button', { name: 'Save' })
      ).toBeInTheDocument();
      expect(within(footer).queryByRole('switch')).not.toBeInTheDocument();
    });
    it('groups account, connection and content settings into bordered boxes', () => {
      setupStores();
      render(<M3U {...defaultProps({ m3uAccount: makeM3uAccount() })} />);
      for (const name of [
        'Account settings',
        'Connection settings',
        'Live TV settings',
        'VOD settings',
      ]) {
        expect(
          screen
            .getByRole('group', { name })
            .closest('[data-testid="settings-box"]')
        ).toBeInTheDocument();
      }
      expect(screen.getByRole('tab', { name: 'Account' })).toBeInTheDocument();
      for (const name of ['Settings', 'EPG', 'Content'])
        expect(screen.getByRole('tab', { name })).toBeInTheDocument();
      for (const name of ['Categories', 'Live TV', 'VOD'])
        expect(screen.queryByRole('tab', { name })).not.toBeInTheDocument();
      expect(screen.getByRole('tab', { name: 'Profiles' })).toBeInTheDocument();
    });

    it('does not overwrite unsaved account fields when visiting Categories', () => {
      setupStores();
      render(<M3U {...defaultProps({ m3uAccount: makeM3uAccount() })} />);
      fireEvent.change(screen.getByDisplayValue('Test M3U'), {
        target: { value: 'Unsaved name' },
      });
      fireEvent.click(screen.getByRole('tab', { name: 'Content' }));
      expect(
        screen.getByRole('button', { name: 'Edit selection' })
      ).toBeInTheDocument();
      fireEvent.click(screen.getByRole('tab', { name: 'Account' }));
      expect(screen.getByDisplayValue('Unsaved name')).toBeInTheDocument();
      expect(M3uUtils.updatePlaylist).not.toHaveBeenCalled();
    });

    it('uses the latest saved account in Categories without resetting the form', () => {
      const original = makeM3uAccount();
      setupStores({ playlists: [original] });
      const view = render(<M3U {...defaultProps({ m3uAccount: original })} />);
      fireEvent.change(screen.getByDisplayValue('Test M3U'), {
        target: { value: 'Unsaved name' },
      });
      fireEvent.click(screen.getByRole('tab', { name: 'Content' }));
      setupStores({
        playlists: [{ ...original, name: 'Latest saved account' }],
      });
      view.rerender(<M3U {...defaultProps({ m3uAccount: original })} />);
      expect(screen.getByTestId('account-categories')).toHaveAttribute(
        'data-saved-name',
        'Latest saved account'
      );
      fireEvent.click(screen.getByRole('tab', { name: 'Account' }));
      expect(screen.getByDisplayValue('Unsaved name')).toBeInTheDocument();
    });

    it('keeps Live and VOD refresh controls in their own two-column content groups', () => {
      setupStores();
      render(
        <M3U
          {...defaultProps({
            m3uAccount: makeM3uAccount({
              enable_vod: true,
              vod_refresh_after_live: false,
            }),
          })}
        />
      );
      expect(screen.getByTestId('modal')).toHaveAttribute('data-size', '68vw');
      expect(screen.getByTestId('modal')).toHaveAttribute(
        'data-content-class',
        `${editorClasses.content} ${editorClasses.accountContent} ${editorClasses.m3uContent}`
      );
      expect(screen.getAllByTestId('account-columns')).toHaveLength(2);
      const live = within(
        screen.getByRole('group', { name: 'Live TV settings' })
      );
      const vod = within(screen.getByRole('group', { name: 'VOD settings' }));
      const liveSchedule = within(
        screen.getByRole('group', { name: 'Live TV refresh schedule' })
      );
      const vodSchedule = within(
        screen.getByRole('group', { name: 'VOD refresh schedule' })
      );
      expect(
        liveSchedule.getByLabelText('Live TV refresh interval (hours)')
      ).toBeInTheDocument();
      expect(
        live.queryByRole('spinbutton', { name: 'VOD Priority' })
      ).not.toBeInTheDocument();
      expect(
        vodSchedule.getByLabelText('VOD refresh interval (hours)')
      ).toBeInTheDocument();
      expect(
        vod.getByRole('switch', { name: 'Enable VOD' })
      ).toBeInTheDocument();
      expect(
        vod.queryByLabelText('Live TV refresh interval (hours)')
      ).not.toBeInTheDocument();
    });

    it('asks about EPG after creation rather than showing a content option', () => {
      setupStores();
      render(<M3U {...defaultProps()} />);
      const live = within(
        screen.getByRole('group', { name: 'Live TV settings' })
      );
      const vod = within(screen.getByRole('group', { name: 'VOD settings' }));
      expect(
        live.queryByRole('switch', { name: 'Create EPG' })
      ).not.toBeInTheDocument();
      expect(
        vod.queryByRole('switch', { name: 'Create EPG' })
      ).not.toBeInTheDocument();
    });

    it.each([
      ['URL', { server_url: 'https://example.invalid/list.m3u' }],
      ['file', { server_url: '', file_path: '/data/example.m3u' }],
    ])(
      'shows Streams without VOD settings for a standard %s account',
      (_, source) => {
        setupStores();
        render(
          <M3U
            {...defaultProps({
              m3uAccount: makeM3uAccount({ account_type: 'STD', ...source }),
            })}
          />
        );
        expect(
          screen.getByRole('group', { name: 'Streams settings' })
        ).toBeInTheDocument();
        expect(
          screen.getByRole('group', { name: 'Streams refresh schedule' })
        ).toBeInTheDocument();
        expect(
          screen.queryByRole('group', { name: 'VOD settings' })
        ).not.toBeInTheDocument();
        expect(
          screen.queryByRole('group', { name: 'VOD refresh schedule' })
        ).not.toBeInTheDocument();
        expect(
          screen.queryByRole('switch', { name: 'Enable VOD' })
        ).not.toBeInTheDocument();
        expect(
          screen.getAllByRole('tab').map((tab) => tab.textContent)
        ).toEqual(['Account', 'Settings', 'Content', 'Profiles']);
      }
    );

    it('keeps the activation hint for XC accounts with VOD disabled', () => {
      setupStores();
      render(
        <M3U
          {...defaultProps({
            m3uAccount: makeM3uAccount({ enable_vod: false }),
          })}
        />
      );
      expect(
        within(
          screen.getByRole('group', { name: 'VOD refresh schedule' })
        ).getByText('Enable VOD scanning to configure automatic VOD refreshes.')
      ).toBeInTheDocument();
    });

    it('shows only the upload input for an existing file account', () => {
      setupStores();
      render(
        <M3U
          {...defaultProps({
            m3uAccount: makeM3uAccount({
              account_type: 'STD',
              server_url: '',
              file_path: '/data/uploads/m3us/example.m3u',
            }),
          })}
        />
      );
      const input = screen.getByLabelText('Playlist file');
      expect(input).toHaveAttribute('type', 'file');
      expect(
        input.closest('label').querySelector('svg.lucide-upload')
      ).toBeInTheDocument();
      expect(input).toHaveAttribute('placeholder', 'Current: example.m3u');
      expect(screen.queryByLabelText('URL')).not.toBeInTheDocument();
      expect(
        screen.getByRole('combobox', { name: 'Account Type' })
      ).toHaveValue('M3U_FILE');
      expect(
        screen.queryByText('Use a playlist URL or upload a file.')
      ).not.toBeInTheDocument();
    });

    it('updates content controls when the account type changes', () => {
      setupStores();
      render(<M3U {...defaultProps()} />);
      fireEvent.change(screen.getByRole('combobox', { name: 'Account Type' }), {
        target: { value: 'M3U_URL' },
      });
      expect(
        screen.queryByRole('switch', { name: 'Enable VOD' })
      ).not.toBeInTheDocument();
      expect(
        screen.getByRole('group', { name: 'Streams settings' })
      ).toBeInTheDocument();
      fireEvent.change(screen.getByRole('combobox', { name: 'Account Type' }), {
        target: { value: 'XC' },
      });
      expect(
        screen.getByRole('group', { name: 'VOD settings' })
      ).toBeInTheDocument();
      expect(
        screen.getByRole('group', { name: 'Live TV settings' })
      ).toBeInTheDocument();
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
      fireEvent.change(
        screen.getByLabelText('Live TV refresh interval (hours)'),
        { target: { value: '8' } }
      );
      fireEvent.change(screen.getByLabelText('VOD refresh interval (hours)'), {
        target: { value: '48' },
      });
      fireEvent.click(screen.getByRole('button', { name: 'Save' }));
      await waitFor(() =>
        expect(M3uUtils.updatePlaylist).toHaveBeenCalledWith(
          account,
          expect.objectContaining({
            refresh_interval: 8,
            vod_refresh_interval: 48,
            vod_refresh_after_live: false,
            enable_vod: true,
            priority: 30,
          }),
          null
        )
      );
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

  describe('guided creation', () => {
    it.each(['account', 'content'])(
      'keeps the saved %s step when continuing later',
      (setup_step) => {
        setupStores();
        const onClose = vi.fn();
        render(
          <M3U
            {...defaultProps({
              m3uAccount: makeM3uAccount({ setup_step }),
              setupMode: true,
              onClose,
            })}
          />
        );
        fireEvent.click(screen.getByTestId('modal-close'));
        expect(
          screen.getByRole('dialog', { name: 'Continue setup later?' })
        ).toBeInTheDocument();
        expect(onClose).not.toHaveBeenCalled();
        fireEvent.click(screen.getByRole('button', { name: 'Continue later' }));
        expect(onClose).toHaveBeenCalledOnce();
        expect(M3uUtils.updatePlaylist).not.toHaveBeenCalled();
        expect(M3uUtils.addPlaylist).not.toHaveBeenCalled();
      }
    );

    it('confirms discarding only unsaved edits of an existing setup account', () => {
      setupStores();
      const onClose = vi.fn();
      render(
        <M3U
          {...defaultProps({
            m3uAccount: makeM3uAccount({ setup_step: 'account' }),
            setupMode: true,
            onClose,
          })}
        />
      );
      fireEvent.change(screen.getByTestId('text-input-name'), {
        target: { value: 'Unsaved name' },
      });
      fireEvent.click(screen.getByTestId('modal-close'));
      expect(
        screen.getByText(
          /Your account, EPG sources and saved setup progress will be kept/
        )
      ).toBeInTheDocument();
      fireEvent.click(screen.getByRole('button', { name: 'Keep editing' }));
      expect(screen.getByDisplayValue('Unsaved name')).toBeInTheDocument();
      fireEvent.click(screen.getByTestId('modal-close'));
      fireEvent.click(
        screen.getByRole('button', { name: 'Discard changes & close' })
      );
      expect(onClose).toHaveBeenCalledOnce();
      expect(M3uUtils.updatePlaylist).not.toHaveBeenCalled();
    });

    it.each(['M3U_URL', 'M3U_FILE'])(
      'hides the EPG tab for %s accounts',
      (source) => {
        setupStores();
        const account = makeM3uAccount({
          account_type: 'STD',
          server_url:
            source === 'M3U_URL' ? 'https://example.invalid/playlist.m3u' : '',
          file_path: source === 'M3U_FILE' ? '/data/playlist.m3u' : '',
        });
        render(<M3U {...defaultProps({ m3uAccount: account })} />);
        expect(
          screen.queryByRole('tab', { name: 'EPG' })
        ).not.toBeInTheDocument();
        expect(screen.queryByTestId('account-epg')).not.toBeInTheDocument();
      }
    );

    it.each(['account', 'content'])(
      'saves the existing %s step without creating another account',
      async (setup_step) => {
        setupStores();
        const account = makeM3uAccount({ setup_step });
        const onSetupNext = vi.fn();
        const onClose = vi.fn();
        render(
          <M3U
            {...defaultProps({
              m3uAccount: account,
              setupMode: true,
              onSetupNext,
              onClose,
            })}
          />
        );
        expect(screen.queryByRole('tablist')).not.toBeInTheDocument();
        expect(
          screen.queryByRole('button', { name: 'Save' })
        ).not.toBeInTheDocument();
        fireEvent.click(screen.getByRole('button', { name: 'Next' }));
        await waitFor(() => expect(onSetupNext).toHaveBeenCalledOnce());
        expect(M3uUtils.updatePlaylist).toHaveBeenCalledWith(
          account,
          expect.objectContaining({ name: account.name }),
          null
        );
        expect(M3uUtils.addPlaylist).not.toHaveBeenCalled();
        expect(onClose).not.toHaveBeenCalled();
      }
    );

    it('keeps the form draft when going back from Content to Account', async () => {
      setupStores();
      const account = makeM3uAccount({ setup_step: 'content' });
      const onSetupBack = vi.fn();
      const props = defaultProps({
        m3uAccount: account,
        setupMode: true,
        onSetupBack,
      });
      const { rerender } = render(<M3U {...props} />);
      fireEvent.change(screen.getByTestId('text-input-name'), {
        target: { value: 'Unsubmitted draft' },
      });
      fireEvent.click(screen.getByRole('button', { name: 'Back' }));
      expect(onSetupBack).toHaveBeenCalledOnce();
      expect(M3uUtils.updatePlaylist).not.toHaveBeenCalled();
      rerender(
        <M3U {...props} m3uAccount={{ ...account, setup_step: 'account' }} />
      );
      await waitFor(() =>
        expect(
          screen.queryByRole('button', { name: 'Back' })
        ).not.toBeInTheDocument()
      );
      expect(screen.getByDisplayValue('Unsubmitted draft')).toBeInTheDocument();
    });

    it('shows Live and VOD together and goes back to Account without saving', () => {
      setupStores();
      const onSetupBack = vi.fn();
      const onSetupNext = vi.fn();
      render(
        <M3U
          {...defaultProps({
            m3uAccount: makeM3uAccount({ setup_step: 'content' }),
            setupMode: true,
            onSetupBack,
            onSetupNext,
          })}
        />
      );
      expect(screen.queryByRole('tablist')).not.toBeInTheDocument();
      fireEvent.change(screen.getByLabelText('VOD Priority'), {
        target: { value: '27' },
      });
      fireEvent.click(screen.getByRole('button', { name: 'Back' }));
      expect(onSetupBack).toHaveBeenCalledOnce();
      expect(onSetupNext).not.toHaveBeenCalled();
      expect(M3uUtils.updatePlaylist).not.toHaveBeenCalled();
      expect(M3uUtils.addPlaylist).not.toHaveBeenCalled();
      expect(
        mantineForm.useForm.mock.results.at(-1).value.getValues().priority
      ).toBe(27);
    });

    it('does not allow Content before validating Account', () => {
      setupStores();
      render(<M3U {...defaultProps()} />);
      expect(
        screen.getByRole('button', { name: 'Content step' })
      ).toBeDisabled();
      fireEvent.click(screen.getByRole('button', { name: 'Next' }));
      expect(M3uUtils.addPlaylist).not.toHaveBeenCalled();
      expect(
        screen.getByRole('button', { name: 'Content step' })
      ).toBeDisabled();
    });

    it('warns before discarding a new unsaved draft', () => {
      setupStores();
      const onClose = vi.fn();
      render(<M3U {...defaultProps({ onClose })} />);
      fireEvent.change(screen.getByTestId('text-input-name'), {
        target: { value: 'Draft' },
      });
      fireEvent.click(screen.getByTestId('modal-close'));
      expect(onClose).not.toHaveBeenCalled();
      fireEvent.click(screen.getByRole('button', { name: 'Keep editing' }));
      expect(screen.getByDisplayValue('Draft')).toBeInTheDocument();
      fireEvent.click(screen.getByTestId('modal-close'));
      fireEvent.click(screen.getByRole('button', { name: 'Discard' }));
      expect(onClose).toHaveBeenCalledOnce();
    });
  });
});
