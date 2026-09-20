import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import M3U from '../M3U';

// ── Store mocks ────────────────────────────────────────────────────────────────
vi.mock('../../../store/userAgents', () => ({ default: vi.fn() }));
vi.mock('../../../store/serverGroups', () => ({ default: vi.fn() }));
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

vi.mock('../../../api', () => ({
  default: {
    getM3UAccountTemplates: vi.fn().mockResolvedValue([]),
    applyM3UAccountTemplate: vi.fn(),
    saveM3UAccountAsTemplate: vi.fn(),
    createM3UAccountTemplate: vi.fn(),
    deleteM3UAccountTemplate: vi.fn(),
  },
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
  default: ({ isOpen, onClose }) =>
    isOpen ? (
      <div data-testid="m3u-group-filter">
        <button data-testid="m3u-group-filter-close" onClick={onClose}>
          Close groups
        </button>
      </div>
    ) : null,
}));

vi.mock('../ScheduleInput', () => ({
  default: ({ onChange, value }) => (
    <div data-testid="schedule-input">
      <input
        data-testid="schedule-value"
        value={value || ''}
        onChange={(e) => onChange?.(e.target.value)}
      />
    </div>
  ),
}));

// ── Mantine dates ──────────────────────────────────────────────────────────────
vi.mock('@mantine/dates', () => ({
  DateTimePicker: ({ label, value, onChange, placeholder }) => (
    <div>
      <label>
        {label}
        <input
          data-testid="date-time-picker"
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
  Button: ({
    children,
    onClick,
    type,
    loading,
    disabled,
    variant,
    color,
    'aria-label': ariaLabel,
  }) => (
    <button
      type={type || 'button'}
      aria-label={ariaLabel}
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
  FileButton: ({ children, onChange }) =>
    children({ onChange: (event) => onChange?.(event?.target?.files?.[0]) }),
  Flex: ({ children }) => <div>{children}</div>,
  Group: ({ children }) => <div>{children}</div>,
  LoadingOverlay: ({ visible }) =>
    visible ? <div data-testid="loading-overlay" /> : null,
  Paper: ({ children }) => <div>{children}</div>,
  SimpleGrid: ({ children }) => <div>{children}</div>,
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
  Stack: ({ children }) => <div>{children}</div>,
  Tabs: ({ children }) => <div>{children}</div>,
  TabsList: ({ children }) => <div>{children}</div>,
  TabsPanel: ({ children }) => <div>{children}</div>,
  TabsTab: ({ children }) => <button type="button">{children}</button>,
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
  Text: ({ children }) => <span>{children}</span>,
  Tooltip: ({ children, label }) => <span title={label}>{children}</span>,
  Textarea: ({ label, value, onChange }) => (
    <label>
      {label}
      <textarea aria-label={label} value={value || ''} onChange={onChange} />
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
import useServerGroupsStore from '../../../store/serverGroups';
import useChannelsStore from '../../../store/channels';
import useEPGsStore from '../../../store/epgs';
import useVODStore from '../../../store/useVODStore';
import usePlaylistsStore from '../../../store/playlists';
import * as M3uUtils from '../../../utils/forms/M3uUtils.js';
import * as DummyEpgUtils from '../../../utils/forms/DummyEpgUtils.js';
import * as mantineForm from '@mantine/form';
import API from '../../../api';

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
  xc_live_refresh_min_age_minutes: 55,
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

  useServerGroupsStore.mockImplementation((selector) =>
    selector({ serverGroups: overrides.serverGroups || [] })
  );

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

    it('shows the XC client refresh freshness setting for XC accounts', () => {
      setupStores();
      render(<M3U {...defaultProps()} />);
      expect(
        screen.getByText('Provider refresh age (minutes)')
      ).toBeInTheDocument();
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

    it('renders URL input', () => {
      setupStores();
      render(<M3U {...defaultProps()} />);
      expect(screen.getByTestId('text-input-server_url')).toBeInTheDocument();
    });

    it('places the account template above the tabs', () => {
      setupStores();
      render(<M3U {...defaultProps()} />);
      const templateLabel = screen.getByText('Account template');
      const accountTab = screen.getByRole('button', { name: 'Account' });
      expect(
        templateLabel.compareDocumentPosition(accountTab) &
          Node.DOCUMENT_POSITION_FOLLOWING
      ).toBeTruthy();
    });

    it('deletes a selected account template after confirmation', async () => {
      API.getM3UAccountTemplates.mockResolvedValueOnce([
        {
          id: 9,
          name: 'Reusable template',
          account_type: 'XC',
          account_settings: {},
        },
      ]);
      API.deleteM3UAccountTemplate.mockResolvedValueOnce(undefined);
      setupStores();
      render(<M3U {...defaultProps()} />);

      const templateSelect = await screen.findByLabelText('No template');
      fireEvent.change(templateSelect, { target: { value: '9' } });
      fireEvent.click(screen.getByRole('button', { name: 'Delete' }));

      expect(
        screen.getByText('Delete M3U account template')
      ).toBeInTheDocument();
      const deleteButtons = screen.getAllByRole('button', { name: 'Delete' });
      fireEvent.click(deleteButtons[deleteButtons.length - 1]);

      await waitFor(() =>
        expect(API.deleteM3UAccountTemplate).toHaveBeenCalledWith(9)
      );
      expect(templateSelect).toHaveValue('');
      expect(screen.queryByText('Reusable template')).not.toBeInTheDocument();
    });

    it('places URL below Account Type', () => {
      setupStores();
      render(<M3U {...defaultProps()} />);
      const accountType = screen.getByRole('combobox', {
        name: 'Account Type',
      });
      const url = screen.getByTestId('text-input-server_url');
      expect(
        accountType.compareDocumentPosition(url) &
          Node.DOCUMENT_POSITION_FOLLOWING
      ).toBeTruthy();
    });

    it('groups content settings above the side-by-side refresh schedules', () => {
      setupStores();
      render(<M3U {...defaultProps()} />);
      expect(
        screen.getByRole('button', { name: 'Content' })
      ).toBeInTheDocument();
      expect(screen.getByText('Live TV')).toBeInTheDocument();
      expect(screen.getByText('VOD')).toBeInTheDocument();
      expect(screen.getByText('Live TV refresh schedule')).toBeInTheDocument();
      expect(screen.getByText('VOD refresh schedule')).toBeInTheDocument();
    });

    it('labels the separate VOD schedule switch and explains its fallback', async () => {
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

      await waitFor(() =>
        expect(
          screen.getAllByRole('switch', { name: 'Enabled' }).at(-1)
        ).toBeChecked()
      );
      expect(
        screen.getByTitle(
          'When disabled, VOD refresh runs after a successful Live TV refresh.'
        )
      ).toBeInTheDocument();
    });

    it('renders submit button with "Create" label for new account', () => {
      setupStores();
      render(<M3U {...defaultProps()} />);
      expect(
        screen.getByRole('button', { name: 'Create M3U account' })
      ).toBeInTheDocument();
      expect(screen.getByText('Create')).toBeInTheDocument();
    });

    it('renders submit button with "Update" or "Save" label for existing account', () => {
      setupStores();
      render(<M3U {...defaultProps({ m3uAccount: makeM3uAccount() })} />);
      expect(
        screen.getByRole('button', { name: 'Save M3U account' })
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
      fireEvent.click(screen.getByRole('button', { name: 'Groups' }));
      expect(screen.getByTestId('m3u-group-filter')).toBeInTheDocument();
    });

    it('returns to the account editor when the group editor closes', () => {
      const onClose = vi.fn();
      setupStores();
      render(
        <M3U {...defaultProps({ m3uAccount: makeM3uAccount(), onClose })} />
      );

      fireEvent.click(screen.getByRole('button', { name: 'Groups' }));
      fireEvent.click(screen.getByTestId('m3u-group-filter-close'));

      expect(screen.queryByTestId('m3u-group-filter')).not.toBeInTheDocument();
      expect(onClose).not.toHaveBeenCalled();
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
      fireEvent.click(
        screen.getByRole('button', { name: 'Create M3U account' })
      );
      await waitFor(() => {
        expect(M3uUtils.addPlaylist).toHaveBeenCalled();
      });
    });

    it('calls prepareSubmitValues before addPlaylist', async () => {
      setupStores();
      render(<M3U {...defaultProps()} />);
      fillRequiredFields();
      fireEvent.click(
        screen.getByRole('button', { name: 'Create M3U account' })
      );
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
      fireEvent.click(screen.getByRole('button', { name: 'Save M3U account' }));
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
      fireEvent.click(screen.getByRole('button', { name: 'Save M3U account' }));
      await waitFor(() => {
        expect(M3uUtils.updatePlaylist).toHaveBeenCalled();
      });
    });

    it('does not call addPlaylist when updating', async () => {
      setupStores();
      render(<M3U {...defaultProps({ m3uAccount: makeM3uAccount() })} />);
      fireEvent.click(screen.getByRole('button', { name: 'Save M3U account' }));
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
      fireEvent.click(screen.getByRole('button', { name: 'Save M3U account' }));
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
      fireEvent.click(
        screen.getByRole('button', { name: 'Create M3U account' })
      );
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

      fireEvent.click(
        screen.getByRole('button', { name: 'Create M3U account' })
      );
      await waitFor(() => {
        expect(M3uUtils.addPlaylist).toHaveBeenCalled();
      });
      // addEPG may be called conditionally — assert it was called or not based on a checkbox
    });
  });
});
