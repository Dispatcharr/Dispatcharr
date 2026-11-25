import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import M3U from '../M3U';
import API from '../../../api.js';
import useUserAgentsStore from '../../../store/userAgents.jsx';
import useChannelsStore from '../../../store/channels.jsx';
import useEPGsStore from '../../../store/epgs.jsx';
import useVODStore from '../../../store/useVODStore.jsx';
import usePlaylistsStore from '../../../store/playlists.jsx';
import { useForm } from '@mantine/form';

vi.mock('../../../api.js', () => ({
  default: {
    addPlaylist: vi.fn(),
    updatePlaylist: vi.fn(),
    getPlaylist: vi.fn(),
    addEPG: vi.fn(),
  },
}));

vi.mock('../../../store/userAgents.jsx', () => ({ default: vi.fn() }));
vi.mock('../../../store/channels.jsx', () => ({ default: vi.fn() }));
vi.mock('../../../store/epgs.jsx', () => ({ default: vi.fn() }));
vi.mock('../../../store/useVODStore.jsx', () => ({ default: vi.fn() }));
vi.mock('../../../store/playlists.jsx', () => ({ default: vi.fn() }));

vi.mock('@mantine/notifications', () => ({
  notifications: {
    show: vi.fn(),
  },
}));

vi.mock('@mantine/form', () => ({
  useForm: vi.fn(),
  isNotEmpty: vi.fn(() => () => null),
}));

vi.mock('../M3UProfiles.jsx', () => ({
  default: ({ isOpen }) =>
    isOpen ? <div data-testid="profiles-modal">Profiles</div> : null,
}));

vi.mock('../M3UFilters.jsx', () => ({
  default: ({ isOpen }) =>
    isOpen ? <div data-testid="filters-modal">Filters</div> : null,
}));

vi.mock('../M3UGroupFilter.jsx', () => ({
  default: ({ isOpen, playlist }) =>
    isOpen ? (
      <div data-testid="group-filter-modal">Groups for {playlist?.name}</div>
    ) : null,
}));

vi.mock('../ScheduleInput.jsx', () => ({
  default: () => <div data-testid="schedule-input">Schedule Input</div>,
}));

vi.mock('@mantine/dates', () => ({
  DateTimePicker: ({ label, value, onChange, disabled }) => (
    <label>
      {label}
      <input
        aria-label={label}
        value={value ?? ''}
        onChange={(event) => onChange?.(event.target.value)}
        disabled={disabled}
      />
    </label>
  ),
}));

vi.mock('@mantine/core', () => {
  const wrapField = (Tag = 'input', defaultType = 'text') =>
    function Field({ label, id, data, checked, value, onChange, disabled }) {
      const inputProps =
        Tag === 'select'
          ? {}
          : {
              type: defaultType,
              checked,
            };

      return (
        <label htmlFor={id}>
          {label}
          <Tag
            id={id}
            aria-label={label}
            value={value ?? (Tag === 'select' ? '' : '')}
            disabled={disabled}
            {...inputProps}
            onChange={(event) => {
              if (Tag === 'select') {
                onChange?.(event.target.value);
              } else {
                onChange?.(event);
              }
            }}
          >
            {Tag === 'select'
              ? data?.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))
              : null}
          </Tag>
        </label>
      );
    };

  const Modal = ({ opened, children, title }) =>
    opened ? (
      <div data-testid="modal">
        <div>{title}</div>
        {children}
      </div>
    ) : null;
  Modal.NativeScrollArea = ({ children }) => <div>{children}</div>;

  return {
    Alert: ({ children }) => <div>{children}</div>,
    Box: ({ children }) => <div>{children}</div>,
    Button: ({ children, onClick, type = 'button', disabled, loading }) => (
      <button type={type} onClick={onClick} disabled={disabled || loading}>
        {children}
      </button>
    ),
    Checkbox: ({ label, id, checked, onChange, disabled }) => (
      <label htmlFor={id}>
        {label}
        <input
          id={id}
          aria-label={label}
          type="checkbox"
          checked={checked ?? false}
          onChange={onChange}
          disabled={disabled}
        />
      </label>
    ),
    Collapse: ({ in: isOpen, children }) => (isOpen ? <div>{children}</div> : null),
    Divider: () => <div />,
    FileInput: wrapField(),
    Flex: ({ children }) => <div>{children}</div>,
    Group: ({ children }) => <div>{children}</div>,
    LoadingOverlay: ({ visible }) =>
      visible ? <div data-testid="loading-overlay">Loading</div> : null,
    Modal,
    MultiSelect: () => null,
    NumberInput: wrapField('input', 'number'),
    PasswordInput: wrapField('input', 'password'),
    Select: wrapField('select'),
    Stack: ({ children }) => <div>{children}</div>,
    Switch: ({ id, description, checked, onChange }) => (
      <label htmlFor={id}>
        {description || id}
        <input
          id={id}
          aria-label={description || id}
          type="checkbox"
          checked={checked ?? false}
          onChange={onChange}
        />
      </label>
    ),
    Text: ({ children }) => <span>{children}</span>,
    TextInput: wrapField(),
  };
});

const baseFormValues = {
  name: 'Stalker Provider',
  server_url: 'http://portal.example.com/c/',
  user_agent: '0',
  is_active: true,
  max_streams: 0,
  refresh_interval: 24,
  cron_expression: '',
  account_type: 'STALKER',
  create_epg: false,
  username: 'demo',
  password: 'secret',
  mac: '00:1A:79:00:00:10',
  model: '',
  serial_number: '',
  device_id: '',
  device_id2: '',
  signature: '',
  timezone: '',
  stale_stream_days: 7,
  priority: 5,
  enable_vod: false,
};

let formValues;
let formMock;
let channelStore;
let epgStore;
let vodStore;

const createFormMock = (overrides = {}) => {
  formValues = { ...baseFormValues, ...overrides };

  formMock = {
    values: formValues,
    getValues: vi.fn(() => ({ ...formValues })),
    getInputProps: vi.fn((field, options) => {
      if (options?.type === 'checkbox') {
        return {
          checked: Boolean(formValues[field]),
          onChange: vi.fn(),
        };
      }

      return {
        value: formValues[field] ?? '',
        onChange: vi.fn(),
      };
    }),
    setValues: vi.fn((values) => {
      Object.assign(formValues, values);
    }),
    setFieldValue: vi.fn((field, value) => {
      formValues[field] = value;
    }),
    key: vi.fn((field) => field),
    reset: vi.fn(),
    onSubmit: vi.fn((handler) => async (event) => {
      event?.preventDefault?.();
      return handler();
    }),
    submitting: false,
  };

  vi.mocked(useForm).mockReturnValue(formMock);
};

const setupStores = () => {
  channelStore = {
    fetchChannelGroups: vi.fn().mockResolvedValue(undefined),
  };
  epgStore = {
    fetchEPGs: vi.fn().mockResolvedValue(undefined),
  };
  vodStore = {
    categories: {},
    fetchCategories: vi.fn().mockImplementation(async () => {
      vodStore.categories = {
        11: {
          id: 11,
          name: 'Movies',
          category_type: 'movie',
          m3u_accounts: [{ m3u_account: 99, enabled: true }],
        },
      };
    }),
  };

  vi.mocked(useUserAgentsStore).mockImplementation((selector) =>
    selector({ userAgents: [{ id: 1, name: 'Chrome' }] })
  );
  vi.mocked(useChannelsStore).mockImplementation((selector) =>
    selector(channelStore)
  );
  vi.mocked(useEPGsStore).mockImplementation((selector) => selector(epgStore));
  vi.mocked(useVODStore).mockImplementation((selector) => selector(vodStore));
  useVODStore.getState = vi.fn(() => vodStore);
  vi.mocked(usePlaylistsStore).mockImplementation(() => undefined);
};

describe('M3U form Stalker flow', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    createFormMock();
    setupStores();
    vi.mocked(API.addPlaylist).mockResolvedValue({ id: 99, name: 'Created Stalker' });
    vi.mocked(API.getPlaylist).mockResolvedValue({
      id: 99,
      name: 'Created Stalker',
      account_type: 'STALKER',
      enable_vod: false,
      channel_groups: [{ channel_group: 1, enabled: true }],
      profiles: [],
    });
  });

  it('does not render Test Connection for Stalker and allows VOD priority editing', async () => {
    render(
      <M3U
        m3uAccount={{
          id: 44,
          name: 'Existing Stalker',
          account_type: 'STALKER',
          server_url: 'http://portal.example.com/c/',
          user_agent: null,
          is_active: true,
          max_streams: 0,
          refresh_interval: 24,
          cron_expression: '',
          username: 'demo',
          mac: '00:1A:79:00:00:10',
          stale_stream_days: 7,
          priority: 5,
          enable_vod: true,
          channel_groups: [],
          profiles: [],
        }}
        isOpen={true}
        onClose={vi.fn()}
      />
    );

    expect(screen.queryByText('Test Connection')).not.toBeInTheDocument();
    expect(screen.getByLabelText('VOD Priority')).toBeEnabled();
  });

  it('shows Filters for an existing Stalker account and opens the filter modal', async () => {
    render(
      <M3U
        m3uAccount={{
          id: 44,
          name: 'Existing Stalker',
          account_type: 'STALKER',
          server_url: 'http://portal.example.com/c/',
          user_agent: null,
          is_active: true,
          max_streams: 0,
          refresh_interval: 24,
          cron_expression: '',
          username: 'demo',
          mac: '00:1A:79:00:00:10',
          stale_stream_days: 7,
          priority: 5,
          enable_vod: false,
          channel_groups: [],
          profiles: [],
        }}
        isOpen={true}
        onClose={vi.fn()}
      />
    );

    fireEvent.click(screen.getByText('Filters'));

    expect(screen.getByTestId('filters-modal')).toBeInTheDocument();
  });

  it('opens the group filter after first-time Stalker save and preloads VOD categories when enabled', async () => {
    createFormMock({ enable_vod: true });
    setupStores();

    vi.mocked(API.addPlaylist).mockResolvedValue({ id: 99, name: 'Created Stalker' });
    vi.mocked(API.getPlaylist).mockResolvedValue({
      id: 99,
      name: 'Created Stalker',
      account_type: 'STALKER',
      enable_vod: true,
      channel_groups: [{ channel_group: 1, enabled: true }],
      profiles: [],
    });

    render(<M3U m3uAccount={null} isOpen={true} onClose={vi.fn()} />);

    fireEvent.click(screen.getByText('Save'));

    await waitFor(() => {
      expect(API.addPlaylist).toHaveBeenCalledTimes(1);
      expect(API.getPlaylist).toHaveBeenCalledWith(99);
      expect(channelStore.fetchChannelGroups).toHaveBeenCalledTimes(1);
      expect(epgStore.fetchEPGs).toHaveBeenCalledTimes(1);
      expect(vodStore.fetchCategories).toHaveBeenCalledTimes(1);
      expect(screen.getByTestId('group-filter-modal')).toBeInTheDocument();
    });
  });

  it('keeps the form open and does not open an empty group filter when initial Stalker discovery failed', async () => {
    vi.mocked(API.getPlaylist).mockResolvedValue({
      id: 99,
      name: 'Created Stalker',
      account_type: 'STALKER',
      enable_vod: false,
      status: 'error',
      last_message: 'Portal rejected the provided credentials.',
      channel_groups: [],
      profiles: [],
    });

    render(<M3U m3uAccount={null} isOpen={true} onClose={vi.fn()} />);

    fireEvent.click(screen.getByText('Save'));

    await waitFor(() => {
      expect(API.addPlaylist).toHaveBeenCalledTimes(1);
      expect(API.getPlaylist).toHaveBeenCalledWith(99);
      expect(screen.queryByTestId('group-filter-modal')).not.toBeInTheDocument();
      expect(
        screen.getByText('Portal rejected the provided credentials.')
      ).toBeInTheDocument();
    });
  });
});
