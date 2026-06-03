import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

// ── Store mocks ────────────────────────────────────────────────────────────────
vi.mock('../../../store/channels', () => ({ default: vi.fn() }));
vi.mock('../../../store/streamProfiles', () => ({ default: vi.fn() }));
vi.mock('../../../store/epgs', () => ({ default: vi.fn() }));
vi.mock('../../../store/logos', () => ({ default: vi.fn() }));

// ── Hook mocks ─────────────────────────────────────────────────────────────────
vi.mock('../../../hooks/useSmartLogos', () => ({
  useChannelLogoSelection: vi.fn(),
}));

// ── Utility mocks ──────────────────────────────────────────────────────────────
vi.mock('../../../utils/notificationUtils.js', () => ({
  showNotification: vi.fn(),
  updateNotification: vi.fn(),
}));

vi.mock('../../../api', () => ({
  default: {
    getCurrentProgramForEpg: vi.fn().mockResolvedValue(null),
  },
}));

vi.mock('../../../utils/forms/ChannelUtils.js', () => ({
  addChannel: vi.fn(),
  clearChannelOverrides: vi.fn(),
  createLogo: vi.fn(),
  getChannelFormDefaultValues: vi.fn(),
  // Stubs return null so the form's `description` prop renders cleanly.
  getProviderHint: vi.fn(() => null),
  getFkProviderHint: vi.fn(() => null),
  getProviderFormValue: vi.fn(() => ''),
  getFormattedValues: vi.fn(),
  handleEpgUpdate: vi.fn(),
  isFormFieldOverridden: vi.fn(() => false),
  matchChannelEpg: vi.fn(),
  normalizeFieldValue: vi.fn((field, value) => value),
  OVERRIDABLE_FIELDS: ['name', 'channel_number'],
  OVERRIDE_FIELD_LABELS: {
    name: 'Name',
    channel_number: 'Channel Number',
  },
  requeryChannels: vi.fn(),
  buildOverridePayload: vi.fn(() => null),
}));

// ── Child component mocks ──────────────────────────────────────────────────────
vi.mock('../ChannelGroup', () => ({
  default: ({ isOpen, onClose }) =>
    isOpen ? (
      <div data-testid="channel-group-form">
        <button data-testid="channel-group-close" onClick={() => onClose(null)}>
          Close
        </button>
        <button
          data-testid="channel-group-save"
          onClick={() => onClose({ id: 99, name: 'New Group' })}
        >
          Save
        </button>
      </div>
    ) : null,
}));

vi.mock('../Logo', () => ({
  default: ({ isOpen, onClose, onSuccess }) =>
    isOpen ? (
      <div data-testid="logo-form">
        <button data-testid="logo-form-close" onClick={onClose}>
          Close
        </button>
        <button
          data-testid="logo-form-success"
          onClick={() => onSuccess({ logo: { id: 42, name: 'New Logo' } })}
        >
          Success
        </button>
      </div>
    ) : null,
}));

vi.mock('../../LazyLogo', () => ({
  default: ({ logoId, alt, style }) => (
    <img
      data-testid="lazy-logo"
      data-logo-id={logoId}
      alt={alt}
      style={style}
    />
  ),
}));

// ── Image mock ─────────────────────────────────────────────────────────────────
vi.mock('../../../images/logo.png', () => ({ default: 'default-logo.png' }));

// ── react-window mock ──────────────────────────────────────────────────────────
vi.mock('react-window', () => ({
  FixedSizeList: ({ children, itemCount }) => (
    <div data-testid="fixed-size-list">
      {Array.from({ length: itemCount }, (_, index) =>
        children({ index, style: {} })
      )}
    </div>
  ),
}));

// ── react-hook-form mock ───────────────────────────────────────────────────────
vi.mock('react-hook-form', async (importOriginal) => {
  const actual = await importOriginal();
  return {
    ...actual,
    useForm: vi.fn(),
  };
});

// ── @hookform/resolvers/yup mock ───────────────────────────────────────────────
vi.mock('@hookform/resolvers/yup', () => ({
  yupResolver: vi.fn(() => vi.fn()),
}));

// ── lucide-react mock ──────────────────────────────────────────────────────────
vi.mock('lucide-react', () => ({
  Blocks: () => <svg data-testid="icon-blocks" />,
  ChartLine: () => <svg data-testid="icon-chart-line" />,
  Database: () => <svg data-testid="icon-database" />,
  Download: () => <svg data-testid="icon-download" />,
  FileImage: () => <svg data-testid="icon-file-image" />,
  LayoutGrid: () => <svg data-testid="icon-layout-grid" />,
  ListOrdered: () => <svg data-testid="icon-list-ordered" />,
  Logs: () => <svg data-testid="icon-logs" />,
  MonitorCog: () => <svg data-testid="icon-monitor-cog" />,
  Package: () => <svg data-testid="icon-package" />,
  Play: () => <svg data-testid="icon-play" />,
  PlugZap: () => <svg data-testid="icon-plug-zap" />,
  Radio: () => <svg data-testid="icon-radio" />,
  Settings: () => <svg data-testid="icon-settings" />,
  SquarePlus: () => <svg data-testid="icon-square-plus" />,
  Undo2: () => <svg data-testid="icon-undo" />,
  User: () => <svg data-testid="icon-user" />,
  Video: () => <svg data-testid="icon-video" />,
  Webhook: () => <svg data-testid="icon-webhook" />,
  X: () => <svg data-testid="icon-x" />,
  Zap: () => <svg data-testid="icon-zap" />,
}));

// ── @mantine/core mock ─────────────────────────────────────────────────────────
vi.mock('@mantine/core', async () => ({
  ActionIcon: ({ children, onClick, disabled, title, style }) => (
    <button
      data-testid="action-icon"
      onClick={onClick}
      disabled={disabled}
      title={title}
      style={style}
    >
      {children}
    </button>
  ),
  Box: ({ children, style }) => <div style={style}>{children}</div>,
  Button: ({
    children,
    onClick,
    disabled,
    loading,
    type,
    variant,
    color,
    leftSection,
    title,
  }) => (
    <button
      onClick={onClick}
      disabled={disabled || loading}
      type={type}
      data-variant={variant}
      data-color={color}
      data-loading={String(loading)}
      title={title}
    >
      {leftSection}
      {children}
    </button>
  ),
  Center: ({ children, style }) => <div style={style}>{children}</div>,
  Divider: ({ orientation, size }) => (
    <hr data-orientation={orientation} data-size={size} />
  ),
  Flex: ({ children, gap, justify, align, mih }) => (
    <div
      style={{
        gap,
        justifyContent: justify,
        alignItems: align,
        minHeight: mih,
      }}
    >
      {children}
    </div>
  ),
  Group: ({ children, gap, justify, align, style }) => (
    <div style={{ gap, justifyContent: justify, alignItems: align, ...style }}>
      {children}
    </div>
  ),
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
  NumberInput: ({ id, name, label, value, onChange, error }) => (
    <div>
      <label htmlFor={id}>{label}</label>
      <input
        id={id}
        name={name}
        type="number"
        value={value ?? ''}
        onChange={(e) =>
          onChange(e.target.value === '' ? undefined : Number(e.target.value))
        }
        data-testid={`number-input-${name}`}
      />
      {error && <span data-testid={`error-${name}`}>{error}</span>}
    </div>
  ),
  Popover: ({ children, opened }) => (
    <div data-testid="popover" data-opened={String(opened)}>
      {children}
    </div>
  ),
  PopoverDropdown: ({ children, onMouseDown }) => (
    <div data-testid="popover-dropdown" onMouseDown={onMouseDown}>
      {children}
    </div>
  ),
  PopoverTarget: ({ children }) => (
    <div data-testid="popover-target">{children}</div>
  ),
  ScrollArea: ({ children, style }) => <div style={style}>{children}</div>,
  Select: ({ label, value, onChange, data, id, name, error }) => (
    <div>
      <label htmlFor={id ?? label}>{label}</label>
      <select
        id={id ?? label}
        data-testid={`select-${name ?? label}`}
        value={value ?? ''}
        onChange={(e) => onChange(e.target.value)}
      >
        {(data ?? []).map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>
      {error && <span data-testid={`error-${name}`}>{error}</span>}
    </div>
  ),
  Stack: ({ children, gap, align, justify, style }) => (
    <div style={{ gap, alignItems: align, justifyContent: justify, ...style }}>
      {children}
    </div>
  ),
  Switch: ({ label, checked, onChange }) => {
    // The form renders multiple switches (Mature Content, Hide from
    // Clients, and future flags), so derive a unique testid per label.
    // The Mature Content switch keeps "switch-mature" so tests that look
    // it up by that legacy id continue to work.
    const key =
      typeof label === 'string' && label.toLowerCase().includes('mature')
        ? 'switch-mature'
        : `switch-${String(label || '')
            .toLowerCase()
            .replace(/\s+/g, '-')}`;
    return (
      <label>
        <input
          data-testid={key}
          type="checkbox"
          checked={checked}
          onChange={onChange}
        />
        {label}
      </label>
    );
  },
  Text: ({ children, size, c, style }) => (
    <span data-size={size} data-color={c} style={style}>
      {children}
    </span>
  ),
  TextInput: ({
    id,
    name,
    label,
    readOnly,
    value,
    onClick,
    onChange,
    error,
    autoFocus,
    placeholder,
    rightSection,
    ...rest
  }) => (
    <div>
      <label htmlFor={id}>{label}</label>
      <input
        id={id}
        name={name}
        data-testid={`text-input-${name}`}
        readOnly={readOnly}
        value={value ?? ''}
        onClick={onClick}
        onChange={onChange ?? (() => {})}
        placeholder={placeholder}
        autoFocus={autoFocus}
        {...(rest.ref ? { ref: rest.ref } : {})}
        {...(rest['data-error'] ? { 'data-error': rest['data-error'] } : {})}
      />
      {rightSection}
      {error && <span data-testid={`error-${name}`}>{error}</span>}
    </div>
  ),
  Tooltip: ({ children, label }) => <div data-tooltip={label}>{children}</div>,
  UnstyledButton: ({ children, onClick }) => (
    <button data-testid="unstyled-button" onClick={onClick}>
      {children}
    </button>
  ),
  useMantineTheme: () => ({
    tailwind: { green: { 5: '#22c55e' } },
  }),
}));

// ── Imports after mocks ────────────────────────────────────────────────────────
import ChannelForm from '../Channel';
import useChannelsStore from '../../../store/channels';
import useStreamProfilesStore from '../../../store/streamProfiles';
import useEPGsStore from '../../../store/epgs';
import useLogosStore from '../../../store/logos';
import { useChannelLogoSelection } from '../../../hooks/useSmartLogos';
import { useForm } from 'react-hook-form';
import * as ChannelUtils from '../../../utils/forms/ChannelUtils.js';
import {
  showNotification,
  updateNotification,
} from '../../../utils/notificationUtils.js';

// ── Helpers ────────────────────────────────────────────────────────────────────

const makeFormMethods = (overrides = {}) => {
  const watchValues = {
    name: 'Test Channel',
    channel_group_id: '1',
    stream_profile_id: '0',
    user_level: '0',
    logo_id: '0',
    epg_data_id: null,
    channel_number: '',
    tvg_id: '',
    tvc_guide_stationid: '',
    is_adult: false,
    ...overrides.watchValues,
  };

  const register = vi.fn((name) => ({ name, ref: vi.fn() }));
  const handleSubmit = vi.fn((fn) => (e) => {
    e?.preventDefault?.();
    return fn(watchValues);
  });
  const setValue = vi.fn();
  const watch = vi.fn((key) => (key ? watchValues[key] : watchValues));
  const reset = vi.fn();

  return {
    register,
    handleSubmit,
    setValue,
    watch,
    reset,
    formState: { errors: {}, isSubmitting: false },
    ...overrides,
  };
};

const makeChannel = (overrides = {}) => ({
  id: 'ch-1',
  name: 'Test Channel',
  channel_number: 101,
  streams: [],
  epg_data_id: null,
  ...overrides,
});

const makeChannelGroups = () => ({
  1: { id: 1, name: 'Sports' },
  2: { id: 2, name: 'News' },
});

const makeStreamProfiles = () => [
  { id: 1, name: 'HD Profile' },
  { id: 2, name: 'SD Profile' },
];

const makeEpgs = () => ({
  10: { id: 10, name: 'EPG Source 1', is_active: true },
  11: { id: 11, name: 'EPG Source 2', is_active: true },
  12: { id: 12, name: 'Inactive EPG', is_active: false },
});

const makeTvgs = () => [
  {
    id: 'tvg-1',
    name: 'ESPN',
    tvg_id: 'espn.us',
    epg_source: 10,
    icon_url: 'http://example.com/espn.png',
  },
  {
    id: 'tvg-2',
    name: 'CNN',
    tvg_id: 'cnn.us',
    epg_source: 11,
    icon_url: 'http://example.com/cnn.png',
  },
];

const makeTvgsById = () => ({
  'tvg-1': {
    id: 'tvg-1',
    name: 'ESPN',
    tvg_id: 'espn.us',
    epg_source: 10,
    icon_url: 'http://example.com/espn.png',
  },
  'tvg-2': {
    id: 'tvg-2',
    name: 'CNN',
    tvg_id: 'cnn.us',
    epg_source: 11,
    icon_url: 'http://example.com/cnn.png',
  },
});

const makeLogos = () => ({
  42: {
    id: 42,
    name: 'ESPN Logo',
    url: 'http://example.com/espn.png',
    cache_url: '/cache/espn.png',
  },
  43: {
    id: 43,
    name: 'CNN Logo',
    url: 'http://example.com/cnn.png',
    cache_url: '/cache/cnn.png',
  },
});

const makeChannelLogos = () => ({
  42: { id: 42, name: 'ESPN Logo', cache_url: '/cache/espn.png' },
  43: { id: 43, name: 'CNN Logo', cache_url: '/cache/cnn.png' },
});

/** Wire up all store and hook mocks with sensible defaults */
const setupMocks = ({ formOverrides = {}, channel = null } = {}) => {
  const formMethods = makeFormMethods(formOverrides);
  vi.mocked(useForm).mockReturnValue(formMethods);

  // ── Stable references — created ONCE, not recreated per selector call ──────
  const channelGroups = makeChannelGroups();
  const streamProfiles = makeStreamProfiles();
  const epgs = makeEpgs();
  const tvgs = makeTvgs();
  const tvgsById = makeTvgsById();
  const logos = makeLogos();
  const channelLogos = makeChannelLogos();
  const stableDefaults = {
    name: channel?.name ?? '',
    channel_group_id: '1',
    stream_profile_id: '0',
    user_level: '0',
    logo_id: '0',
    epg_data_id: channel?.epg_data_id ?? null,
    channel_number: channel?.channel_number ?? '',
    tvg_id: '',
    tvc_guide_stationid: '',
    is_adult: false,
  };

  vi.mocked(useChannelsStore).mockImplementation((sel) =>
    sel({ channelGroups, fetchChannelProfiles: vi.fn() })
  );
  useChannelsStore.getState = vi.fn(() => ({ fetchChannelProfiles: vi.fn() }));

  vi.mocked(useStreamProfilesStore).mockImplementation((sel) =>
    sel({ profiles: streamProfiles })
  );

  vi.mocked(useEPGsStore).mockImplementation((sel) =>
    sel({ epgs, tvgs, tvgsById })
  );

  vi.mocked(useLogosStore).mockImplementation((sel) => sel({ logos }));

  const mockEnsureLogosLoaded = vi.fn();
  vi.mocked(useChannelLogoSelection).mockReturnValue({
    logos: channelLogos,
    ensureLogosLoaded: mockEnsureLogosLoaded,
    isLoading: false,
  });

  // Same object reference every call — prevents useMemo from recalculating
  vi.mocked(ChannelUtils.getChannelFormDefaultValues).mockReturnValue(
    stableDefaults
  );
  vi.mocked(ChannelUtils.getFormattedValues).mockImplementation((v) => v);

  return { formMethods, mockEnsureLogosLoaded };
};

const defaultProps = (overrides = {}) => ({
  channel: null,
  isOpen: true,
  onClose: vi.fn(),
  ...overrides,
});

// ──────────────────────────────────────────────────────────────────────────────
// Tests
// ──────────────────────────────────────────────────────────────────────────────

describe('ChannelForm', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // ── Visibility ─────────────────────────────────────────────────────────────

  describe('visibility', () => {
    it('renders the modal when isOpen is true', () => {
      setupMocks();
      render(<ChannelForm {...defaultProps()} />);
      expect(screen.getByTestId('modal')).toBeInTheDocument();
    });

    it('renders nothing when isOpen is false', () => {
      setupMocks();
      render(<ChannelForm {...defaultProps({ isOpen: false })} />);
      expect(screen.queryByTestId('modal')).not.toBeInTheDocument();
    });
  });

  // ── Basic rendering ────────────────────────────────────────────────────────

  describe('basic rendering', () => {
    it('renders the submit button', () => {
      setupMocks();
      render(<ChannelForm {...defaultProps()} />);
      expect(screen.getByText('Submit')).toBeInTheDocument();
    });

    it('renders "Saving..." when isSubmitting is true', () => {
      setupMocks({
        formOverrides: { formState: { errors: {}, isSubmitting: true } },
      });
      render(<ChannelForm {...defaultProps()} />);
      expect(screen.getByText('Saving...')).toBeInTheDocument();
    });

    it('renders the Channel Name text input', () => {
      setupMocks();
      render(<ChannelForm {...defaultProps()} />);
      expect(screen.getByTestId('text-input-name')).toBeInTheDocument();
    });

    it('renders Channel Group text input', () => {
      setupMocks();
      render(<ChannelForm {...defaultProps()} />);
      expect(
        screen.getByTestId('text-input-channel_group_id')
      ).toBeInTheDocument();
    });

    it('renders stream profile select with options', () => {
      setupMocks();
      render(<ChannelForm {...defaultProps()} />);
      const select = screen.getByTestId('select-stream_profile_id');
      expect(select).toBeInTheDocument();
      expect(screen.getByText('HD Profile')).toBeInTheDocument();
      expect(screen.getByText('SD Profile')).toBeInTheDocument();
    });

    it('renders the LazyLogo component', () => {
      setupMocks();
      render(<ChannelForm {...defaultProps()} />);
      expect(screen.getByTestId('lazy-logo')).toBeInTheDocument();
    });

    it('renders "Upload or Create Logo" button', () => {
      setupMocks();
      render(<ChannelForm {...defaultProps()} />);
      expect(screen.getByText('Upload or Create Logo')).toBeInTheDocument();
    });

    it('renders the Mature Content switch', () => {
      setupMocks();
      render(<ChannelForm {...defaultProps()} />);
      expect(screen.getByTestId('switch-mature')).toBeInTheDocument();
    });

    it('renders the channel number input', () => {
      setupMocks();
      render(<ChannelForm {...defaultProps()} />);
      expect(
        screen.getByTestId('number-input-channel_number')
      ).toBeInTheDocument();
    });

    it('renders TVG-ID text input', () => {
      setupMocks();
      render(<ChannelForm {...defaultProps()} />);
      expect(screen.getByTestId('text-input-tvg_id')).toBeInTheDocument();
    });

    it('renders Gracenote StationId text input', () => {
      setupMocks();
      render(<ChannelForm {...defaultProps()} />);
      expect(
        screen.getByTestId('text-input-tvc_guide_stationid')
      ).toBeInTheDocument();
    });

    it('renders EPG text input', () => {
      setupMocks();
      render(<ChannelForm {...defaultProps()} />);
      expect(screen.getByTestId('text-input-epg_data_id')).toBeInTheDocument();
    });
  });

  // ── EPG conditional buttons ────────────────────────────────────────────────

  describe('EPG-conditional buttons', () => {
    it('does not show "Use EPG Name" button when no epg_data_id', () => {
      setupMocks({ formOverrides: { watchValues: { epg_data_id: null } } });
      render(<ChannelForm {...defaultProps()} />);
      expect(screen.queryByText('Use EPG Name')).not.toBeInTheDocument();
    });

    it('shows "Use EPG Name" button when epg_data_id is set', () => {
      setupMocks({ formOverrides: { watchValues: { epg_data_id: 'tvg-1' } } });
      render(<ChannelForm {...defaultProps()} />);
      expect(screen.getByText('Use EPG Name')).toBeInTheDocument();
    });

    it('does not show "Use EPG Logo" button when no epg_data_id', () => {
      setupMocks({ formOverrides: { watchValues: { epg_data_id: null } } });
      render(<ChannelForm {...defaultProps()} />);
      expect(screen.queryByText('Use EPG Logo')).not.toBeInTheDocument();
    });

    it('shows "Use EPG Logo" button when epg_data_id is set', () => {
      setupMocks({ formOverrides: { watchValues: { epg_data_id: 'tvg-1' } } });
      render(<ChannelForm {...defaultProps()} />);
      expect(screen.getByText('Use EPG Logo')).toBeInTheDocument();
    });

    it('does not show "Use EPG TVG-ID" button when no epg_data_id', () => {
      setupMocks({ formOverrides: { watchValues: { epg_data_id: null } } });
      render(<ChannelForm {...defaultProps()} />);
      expect(screen.queryByText('Use EPG TVG-ID')).not.toBeInTheDocument();
    });

    it('shows "Use EPG TVG-ID" button when epg_data_id is set', () => {
      setupMocks({ formOverrides: { watchValues: { epg_data_id: 'tvg-1' } } });
      render(<ChannelForm {...defaultProps()} />);
      expect(screen.getByText('Use EPG TVG-ID')).toBeInTheDocument();
    });
  });

  // ── Auto Match button ──────────────────────────────────────────────────────

  describe('Auto Match button', () => {
    it('is disabled when channel is null', () => {
      setupMocks();
      render(<ChannelForm {...defaultProps({ channel: null })} />);
      const autoMatch = screen.getByText('Auto Match');
      expect(autoMatch).toBeDisabled();
    });

    it('is enabled when an existing channel is provided', () => {
      setupMocks({ channel: makeChannel() });
      render(<ChannelForm {...defaultProps({ channel: makeChannel() })} />);
      const autoMatch = screen.getByText('Auto Match');
      expect(autoMatch).not.toBeDisabled();
    });

    it('calls matchChannelEpg with the channel on click', async () => {
      const channel = makeChannel();
      vi.mocked(ChannelUtils.matchChannelEpg).mockResolvedValue({
        matched: true,
        message: 'Matched!',
        channel: { epg_data_id: 'tvg-1' },
      });
      setupMocks({ channel });
      render(<ChannelForm {...defaultProps({ channel })} />);
      fireEvent.click(screen.getByText('Auto Match'));
      await waitFor(() => {
        expect(ChannelUtils.matchChannelEpg).toHaveBeenCalledWith(channel);
      });
    });

    it('shows success notification when matchChannelEpg returns matched: true', async () => {
      const channel = makeChannel();
      vi.mocked(ChannelUtils.matchChannelEpg).mockResolvedValue({
        matched: true,
        message: 'Matched!',
        channel: { epg_data_id: 'tvg-1' },
      });
      setupMocks({ channel });
      render(<ChannelForm {...defaultProps({ channel })} />);
      fireEvent.click(screen.getByText('Auto Match'));
      await waitFor(() => {
        expect(showNotification).toHaveBeenCalledWith(
          expect.objectContaining({ title: 'Success', color: 'green' })
        );
      });
    });

    it('shows "No Match Found" notification when matchChannelEpg returns matched: false', async () => {
      const channel = makeChannel();
      vi.mocked(ChannelUtils.matchChannelEpg).mockResolvedValue({
        matched: false,
        message: 'No match',
      });
      setupMocks({ channel });
      render(<ChannelForm {...defaultProps({ channel })} />);
      fireEvent.click(screen.getByText('Auto Match'));
      await waitFor(() => {
        expect(showNotification).toHaveBeenCalledWith(
          expect.objectContaining({ title: 'No Match Found', color: 'orange' })
        );
      });
    });

    it('shows error notification when matchChannelEpg throws', async () => {
      const channel = makeChannel();
      vi.mocked(ChannelUtils.matchChannelEpg).mockRejectedValue(
        new Error('Network')
      );
      setupMocks({ channel });
      render(<ChannelForm {...defaultProps({ channel })} />);
      fireEvent.click(screen.getByText('Auto Match'));
      await waitFor(() => {
        expect(showNotification).toHaveBeenCalledWith(
          expect.objectContaining({ title: 'Error', color: 'red' })
        );
      });
    });

    it('sets epg_data_id via setValue when a match is found', async () => {
      const channel = makeChannel();
      vi.mocked(ChannelUtils.matchChannelEpg).mockResolvedValue({
        matched: true,
        message: 'Matched!',
        channel: { epg_data_id: 'tvg-1' },
      });
      const { formMethods } = setupMocks({ channel });
      render(<ChannelForm {...defaultProps({ channel })} />);
      fireEvent.click(screen.getByText('Auto Match'));
      await waitFor(() => {
        expect(formMethods.setValue).toHaveBeenCalledWith(
          'epg_data_id',
          'tvg-1'
        );
      });
    });
  });

  // ── "Use EPG Name" ─────────────────────────────────────────────────────────

  describe('"Use EPG Name" button', () => {
    it('sets channel name from EPG tvg name', async () => {
      const { formMethods } = setupMocks({
        formOverrides: { watchValues: { epg_data_id: 'tvg-1' } },
      });
      render(<ChannelForm {...defaultProps()} />);
      fireEvent.click(screen.getByText('Use EPG Name'));

      await waitFor(() => {
        expect(formMethods.setValue).toHaveBeenCalledWith('name', 'ESPN');
        expect(showNotification).toHaveBeenCalledWith(
          expect.objectContaining({ color: 'green' })
        );
      });
    });

    it('shows warning when EPG has no name', async () => {
      setupMocks({
        formOverrides: { watchValues: { epg_data_id: 'tvg-no-name' } },
      });
      // tvg-no-name not in tvgsById → tvg is undefined
      render(<ChannelForm {...defaultProps()} />);
      fireEvent.click(screen.getByText('Use EPG Name'));

      await waitFor(() => {
        expect(showNotification).toHaveBeenCalledWith(
          expect.objectContaining({ title: 'No Name Available' })
        );
      });
    });
  });

  // ── "Use EPG TVG-ID" ───────────────────────────────────────────────────────

  describe('"Use EPG TVG-ID" button', () => {
    it('sets tvg_id from EPG data', async () => {
      const { formMethods } = setupMocks({
        formOverrides: { watchValues: { epg_data_id: 'tvg-1' } },
      });
      render(<ChannelForm {...defaultProps()} />);
      fireEvent.click(screen.getByText('Use EPG TVG-ID'));

      await waitFor(() => {
        expect(formMethods.setValue).toHaveBeenCalledWith('tvg_id', 'espn.us');
        expect(showNotification).toHaveBeenCalledWith(
          expect.objectContaining({ color: 'green' })
        );
      });
    });

    it('shows warning when EPG has no TVG-ID', async () => {
      setupMocks({
        formOverrides: { watchValues: { epg_data_id: 'tvg-no-tvgid' } },
      });
      render(<ChannelForm {...defaultProps()} />);
      fireEvent.click(screen.getByText('Use EPG TVG-ID'));

      await waitFor(() => {
        expect(showNotification).toHaveBeenCalledWith(
          expect.objectContaining({ title: 'No TVG-ID Available' })
        );
      });
    });
  });

  // ── "Use EPG Logo" ─────────────────────────────────────────────────────────

  describe('"Use EPG Logo" button', () => {
    it('sets logo_id when a matching logo exists in the store', async () => {
      const { formMethods } = setupMocks({
        formOverrides: { watchValues: { epg_data_id: 'tvg-1' } },
      });
      render(<ChannelForm {...defaultProps()} />);
      fireEvent.click(screen.getByText('Use EPG Logo'));
      await waitFor(() => {
        expect(formMethods.setValue).toHaveBeenCalledWith('logo_id', 42);
        expect(showNotification).toHaveBeenCalledWith(
          expect.objectContaining({ color: 'green' })
        );
      });
    });

    it('creates a new logo when no matching logo exists', async () => {
      vi.mocked(ChannelUtils.createLogo).mockResolvedValue({
        id: 99,
        name: 'New EPG Logo',
      });
      const { formMethods } = setupMocks({
        formOverrides: {
          watchValues: { epg_data_id: 'tvg-2' },
        },
      });
      // tvg-2 has icon_url 'http://example.com/cnn.png' — but make allLogos not contain it
      vi.mocked(useLogosStore).mockImplementation(
        (sel) => sel({ logos: {} }) // empty logos so no match
      );
      render(<ChannelForm {...defaultProps()} />);
      fireEvent.click(screen.getByText('Use EPG Logo'));
      await waitFor(() => {
        expect(ChannelUtils.createLogo).toHaveBeenCalled();
        expect(formMethods.setValue).toHaveBeenCalledWith('logo_id', 99);
      });
    });

    it('shows error notification when createLogo throws', async () => {
      vi.mocked(ChannelUtils.createLogo).mockRejectedValue(new Error('fail'));
      setupMocks({
        formOverrides: { watchValues: { epg_data_id: 'tvg-2' } },
      });
      vi.mocked(useLogosStore).mockImplementation((sel) => sel({ logos: {} }));
      render(<ChannelForm {...defaultProps()} />);
      fireEvent.click(screen.getByText('Use EPG Logo'));
      await waitFor(() => {
        expect(updateNotification).toHaveBeenCalledWith(
          expect.objectContaining({ color: 'red' })
        );
      });
    });

    it('shows warning when no EPG source is selected', async () => {
      setupMocks({
        formOverrides: { watchValues: { epg_data_id: null } },
      });
      // epg_data_id is null so the button isn't even shown — verify notification path
      // by rendering with an id but no matching tvg
      setupMocks({
        formOverrides: { watchValues: { epg_data_id: 'tvg-no-icon' } },
      });
      render(<ChannelForm {...defaultProps()} />);
      fireEvent.click(screen.getByText('Use EPG Logo'));
      await waitFor(() => {
        expect(showNotification).toHaveBeenCalledWith(
          expect.objectContaining({ title: 'No EPG Icon' })
        );
      });
    });
  });

  // ── Logo modal ─────────────────────────────────────────────────────────────

  describe('logo modal', () => {
    it('opens Logo form when "Upload or Create Logo" is clicked', async () => {
      setupMocks();
      render(<ChannelForm {...defaultProps()} />);
      fireEvent.click(screen.getByText('Upload or Create Logo'));
      await waitFor(() => {
        expect(screen.getByTestId('logo-form')).toBeInTheDocument();
      });
    });

    it('closes Logo form when onClose is called', async () => {
      setupMocks();
      render(<ChannelForm {...defaultProps()} />);
      fireEvent.click(screen.getByText('Upload or Create Logo'));
      fireEvent.click(screen.getByTestId('logo-form-close'));
      await waitFor(() => {
        expect(screen.queryByTestId('logo-form')).not.toBeInTheDocument();
      });
    });

    it('sets logo_id and closes form on success', async () => {
      const { formMethods } = setupMocks();
      render(<ChannelForm {...defaultProps()} />);
      fireEvent.click(screen.getByText('Upload or Create Logo'));
      fireEvent.click(screen.getByTestId('logo-form-success'));
      await waitFor(() => {
        expect(formMethods.setValue).toHaveBeenCalledWith('logo_id', 42);
        expect(screen.queryByTestId('logo-form')).not.toBeInTheDocument();
      });
    });
  });

  // ── Channel Group modal ────────────────────────────────────────────────────

  describe('channel group modal', () => {
    it('opens ChannelGroupForm when the add-group icon is clicked', async () => {
      setupMocks();
      render(<ChannelForm {...defaultProps()} />);
      fireEvent.click(screen.getByTestId('icon-square-plus').closest('button'));
      await waitFor(() => {
        expect(screen.getByTestId('channel-group-form')).toBeInTheDocument();
      });
    });

    it('closes ChannelGroupForm when onClose returns null', async () => {
      setupMocks();
      render(<ChannelForm {...defaultProps()} />);
      fireEvent.click(screen.getByTestId('icon-square-plus').closest('button'));
      fireEvent.click(screen.getByTestId('channel-group-close'));
      await waitFor(() => {
        expect(
          screen.queryByTestId('channel-group-form')
        ).not.toBeInTheDocument();
      });
    });

    it('sets channel_group_id when a new group is returned', async () => {
      const { formMethods } = setupMocks();
      render(<ChannelForm {...defaultProps()} />);
      fireEvent.click(screen.getByTestId('icon-square-plus').closest('button'));
      fireEvent.click(screen.getByTestId('channel-group-save'));
      await waitFor(() => {
        expect(formMethods.setValue).toHaveBeenCalledWith(
          'channel_group_id',
          '99'
        );
        expect(
          screen.queryByTestId('channel-group-form')
        ).not.toBeInTheDocument();
      });
    });
  });

  // ── Form submission ────────────────────────────────────────────────────────

  describe('form submission', () => {
    it('calls addChannel when submitting a new channel', async () => {
      vi.mocked(ChannelUtils.addChannel).mockResolvedValue(undefined);
      setupMocks();
      const onClose = vi.fn();
      render(<ChannelForm {...defaultProps({ onClose })} />);
      fireEvent.click(screen.getByText('Submit'));
      await waitFor(() => {
        expect(ChannelUtils.addChannel).toHaveBeenCalled();
      });
    });

    it('calls handleEpgUpdate when submitting an existing channel', async () => {
      vi.mocked(ChannelUtils.handleEpgUpdate).mockResolvedValue(undefined);
      const channel = makeChannel();
      setupMocks({ channel });
      const onClose = vi.fn();
      render(<ChannelForm {...defaultProps({ channel, onClose })} />);
      fireEvent.click(screen.getByText('Submit'));
      await waitFor(() => {
        expect(ChannelUtils.handleEpgUpdate).toHaveBeenCalledWith(
          channel,
          expect.any(Object),
          expect.any(Object),
          expect.any(Array)
        );
      });
    });

    it('calls onClose after successful submission', async () => {
      vi.mocked(ChannelUtils.addChannel).mockResolvedValue(undefined);
      setupMocks();
      const onClose = vi.fn();
      render(<ChannelForm {...defaultProps({ onClose })} />);
      fireEvent.click(screen.getByText('Submit'));
      await waitFor(() => {
        expect(onClose).toHaveBeenCalled();
      });
    });

    it('calls requeryChannels after successful submission', async () => {
      vi.mocked(ChannelUtils.addChannel).mockResolvedValue(undefined);
      setupMocks();
      render(<ChannelForm {...defaultProps()} />);
      fireEvent.click(screen.getByText('Submit'));
      await waitFor(() => {
        expect(ChannelUtils.requeryChannels).toHaveBeenCalled();
      });
    });

    it('calls reset after successful submission', async () => {
      vi.mocked(ChannelUtils.addChannel).mockResolvedValue(undefined);
      const { formMethods } = setupMocks();
      render(<ChannelForm {...defaultProps()} />);
      fireEvent.click(screen.getByText('Submit'));
      await waitFor(() => {
        expect(formMethods.reset).toHaveBeenCalled();
      });
    });

    it('does NOT close the form when submission throws (preserves user edits)', async () => {
      // Regression guard: a save failure (validation error from the
      // backend, network failure, etc.) must not call reset() + onClose()
      // unconditionally; doing so drops the user's in-progress edits. The
      // form early-returns on saveFailed and surfaces an error notification
      // so the user can correct the error and retry without retyping.
      const error = new Error('Server error');
      error.body = { detail: 'channel_number must be unique' };
      vi.mocked(ChannelUtils.addChannel).mockRejectedValue(error);
      setupMocks();
      const onClose = vi.fn();
      render(<ChannelForm {...defaultProps({ onClose })} />);
      fireEvent.click(screen.getByText('Submit'));
      await waitFor(() => {
        expect(vi.mocked(ChannelUtils.addChannel)).toHaveBeenCalled();
      });
      expect(onClose).not.toHaveBeenCalled();
      expect(showNotification).toHaveBeenCalledWith(
        expect.objectContaining({
          color: 'red',
          message: 'channel_number must be unique',
        })
      );
    });
  });

  // ── Mature content switch ──────────────────────────────────────────────────

  describe('mature content switch', () => {
    it('calls setValue with is_adult: true when switch is toggled on', () => {
      const { formMethods } = setupMocks({
        formOverrides: { watchValues: { is_adult: false } },
      });
      render(<ChannelForm {...defaultProps()} />);
      fireEvent.click(screen.getByTestId('switch-mature'));
      expect(formMethods.setValue).toHaveBeenCalledWith('is_adult', true);
    });
  });

  // ── Logo list rendering ────────────────────────────────────────────────────

  describe('logo list', () => {
    it('renders logo entries from channelLogos', () => {
      setupMocks();
      render(<ChannelForm {...defaultProps()} />);
      // The FixedSizeList mock renders all items; both logo names should appear
      expect(screen.getByText('ESPN Logo')).toBeInTheDocument();
      expect(screen.getByText('CNN Logo')).toBeInTheDocument();
    });
  });

  // ── ensureLogosLoaded ──────────────────────────────────────────────────────

  describe('ensureLogosLoaded', () => {
    it('calls ensureLogosLoaded on mount', () => {
      const { mockEnsureLogosLoaded } = setupMocks();
      render(<ChannelForm {...defaultProps()} />);
      expect(mockEnsureLogosLoaded).toHaveBeenCalled();
    });
  });

  // ── EPG display value ──────────────────────────────────────────────────────

  describe('EPG input display value', () => {
    it('displays "Dummy" when no epg_data_id is set', () => {
      setupMocks({ formOverrides: { watchValues: { epg_data_id: null } } });
      render(<ChannelForm {...defaultProps()} />);
      const epgInput = screen.getByTestId('text-input-epg_data_id');
      expect(epgInput).toHaveValue('Dummy');
    });

    it('displays the EPG source name and tvg name when epg_data_id is set', () => {
      setupMocks({ formOverrides: { watchValues: { epg_data_id: 'tvg-1' } } });
      render(<ChannelForm {...defaultProps()} />);
      const epgInput = screen.getByTestId('text-input-epg_data_id');
      expect(epgInput).toHaveValue('EPG Source 1 - ESPN');
    });
  });

  // ── Override reactivity ────────────────────────────────────────────────────
  //
  // The "Currently overriding" tooltip and "Clear All Overrides (N)" button
  // are derived state computed from the form's watched values. The derivation
  // must recompute when any watched value changes, otherwise the affordance
  // becomes stale and the user loses both the override count and the clear
  // action between edits.

  describe('override reactivity', () => {
    const autoCreatedChannel = () =>
      makeChannel({ id: 'ch-auto', auto_created: true });

    it('updates "Clear All Overrides" affordance when a watched value diverges from provider', () => {
      const channel = autoCreatedChannel();
      // Initial render: no field is overridden, so the Clear All button
      // must NOT be visible.
      vi.mocked(ChannelUtils.isFormFieldOverridden).mockReturnValue(false);
      setupMocks({ channel });
      const { rerender } = render(
        <ChannelForm {...defaultProps()} channel={channel} />
      );
      expect(screen.queryByText(/Clear All Overrides/)).not.toBeInTheDocument();

      // Simulate the user typing into the name field. The mocked watch()
      // now returns a different name, AND isFormFieldOverridden now
      // reports the name field as overridden. The derived state must
      // recompute and surface the Clear All affordance.
      vi.mocked(ChannelUtils.isFormFieldOverridden).mockImplementation(
        (_ch, field) => field === 'name'
      );
      setupMocks({
        channel,
        formOverrides: { watchValues: { name: 'My Override' } },
      });
      rerender(<ChannelForm {...defaultProps()} channel={channel} />);

      expect(screen.getByText(/Clear All Overrides \(1\)/)).toBeInTheDocument();
    });

    it('hides "Clear All Overrides" when the last divergent field reverts to provider', () => {
      const channel = autoCreatedChannel();
      vi.mocked(ChannelUtils.isFormFieldOverridden).mockImplementation(
        (_ch, field) => field === 'name'
      );
      setupMocks({
        channel,
        formOverrides: { watchValues: { name: 'My Override' } },
      });
      const { rerender } = render(
        <ChannelForm {...defaultProps()} channel={channel} />
      );
      expect(screen.getByText(/Clear All Overrides \(1\)/)).toBeInTheDocument();

      // User types the provider value back into the field. No fields are
      // overridden anymore, so the affordance must disappear.
      vi.mocked(ChannelUtils.isFormFieldOverridden).mockReturnValue(false);
      setupMocks({
        channel,
        formOverrides: { watchValues: { name: 'Test Channel' } },
      });
      rerender(<ChannelForm {...defaultProps()} channel={channel} />);

      expect(screen.queryByText(/Clear All Overrides/)).not.toBeInTheDocument();
    });
  });

  // ── EPG filter search ──────────────────────────────────────────────────────
  describe('EPG filter search', () => {
    const skyText = 'Sky Sports Ultra HD (SkySportUltraHD.1.uk)';
    const btText = 'BT Sport 1 (BTSport1.uk)';

    const epgTvgs = [
      {
        id: 'tvg-sky',
        name: 'Sky Sports Ultra HD',
        tvg_id: 'SkySportUltraHD.1.uk',
        epg_source: 10,
        icon_url: '',
      },
      {
        id: 'tvg-bt',
        name: 'BT Sport 1',
        tvg_id: 'BTSport1.uk',
        epg_source: 10,
        icon_url: '',
      },
      // Accent in the name, but the id does NOT mirror it ("decale"): an ascii
      // query only matches if the haystack is accent-folded.
      {
        id: 'tvg-canal',
        name: 'Canal Décalé',
        tvg_id: 'CPLUS42.fr',
        epg_source: 10,
        icon_url: '',
      },
      // Plain ascii everywhere: an accented query only matches if the query
      // itself is accent-folded.
      {
        id: 'tvg-decaleplus',
        name: 'Decale Plus',
        tvg_id: 'DECP.fr',
        epg_source: 10,
        icon_url: '',
      },
    ];
    const canalText = 'Canal Décalé (CPLUS42.fr)';
    const decaleText = 'Decale Plus (DECP.fr)';

    // Render the form, point the store at our two same-source tvgs, and pick the
    // EPG source so the dropdown list is populated.
    const renderAndSelectSource = () => {
      setupMocks();
      // Stable references — recreating these per selector call would retrigger
      // the epgs-dependent effect and loop forever.
      const epgs = makeEpgs();
      const tvgsById = {};
      vi.mocked(useEPGsStore).mockImplementation((sel) =>
        sel({ epgs, tvgs: epgTvgs, tvgsById })
      );
      render(<ChannelForm {...defaultProps()} />);
      fireEvent.change(screen.getByTestId('select-Source'), {
        target: { value: '10' },
      });
    };

    const typeFilter = (value) =>
      fireEvent.change(screen.getByTestId('text-input-tvg-filter'), {
        target: { value },
      });

    it('matches when space-separated terms each appear across name and id', () => {
      renderAndSelectSource();
      typeFilter('Sky uk');
      expect(screen.getByText(skyText)).toBeInTheDocument();
      expect(screen.queryByText(btText)).not.toBeInTheDocument();
    });

    it('matches regardless of term order', () => {
      renderAndSelectSource();
      typeFilter('uk sky');
      expect(screen.getByText(skyText)).toBeInTheDocument();
      expect(screen.queryByText(btText)).not.toBeInTheDocument();
    });

    it('still matches a single substring term', () => {
      renderAndSelectSource();
      typeFilter('sky');
      expect(screen.getByText(skyText)).toBeInTheDocument();
      expect(screen.queryByText(btText)).not.toBeInTheDocument();
    });

    it('shows every row for the source when the filter is empty', () => {
      renderAndSelectSource();
      expect(screen.getByText(skyText)).toBeInTheDocument();
      expect(screen.getByText(btText)).toBeInTheDocument();
    });

    it('shows no rows when a term matches nothing', () => {
      renderAndSelectSource();
      typeFilter('sky zzz');
      expect(screen.queryByText(skyText)).not.toBeInTheDocument();
      expect(screen.queryByText(btText)).not.toBeInTheDocument();
    });

    it('ignores case, including all-caps', () => {
      renderAndSelectSource();
      typeFilter('SKY UK');
      expect(screen.getByText(skyText)).toBeInTheDocument();
      expect(screen.queryByText(btText)).not.toBeInTheDocument();
    });

    it('matches when one term hits the name and another hits the id', () => {
      renderAndSelectSource();
      typeFilter('Sports uk');
      expect(screen.getByText(skyText)).toBeInTheDocument();
      expect(screen.queryByText(btText)).not.toBeInTheDocument();
    });

    it('tolerates leading, trailing and repeated whitespace', () => {
      renderAndSelectSource();
      typeFilter('  sky   uk  ');
      expect(screen.getByText(skyText)).toBeInTheDocument();
      expect(screen.queryByText(btText)).not.toBeInTheDocument();
    });

    it('matches an id fragment that is not in the display name', () => {
      renderAndSelectSource();
      typeFilter('skysport');
      expect(screen.getByText(skyText)).toBeInTheDocument();
      expect(screen.queryByText(btText)).not.toBeInTheDocument();
    });

    it('matches a name word combined with a channel number', () => {
      renderAndSelectSource();
      typeFilter('bt 1');
      expect(screen.getByText(btText)).toBeInTheDocument();
      expect(screen.queryByText(skyText)).not.toBeInTheDocument();
    });

    it('folds accents in the data so a plain ascii query matches', () => {
      renderAndSelectSource();
      typeFilter('canal decale');
      expect(screen.getByText(canalText)).toBeInTheDocument();
      expect(screen.queryByText(decaleText)).not.toBeInTheDocument();
      expect(screen.queryByText(skyText)).not.toBeInTheDocument();
    });

    it('folds accents in the query so it matches plain ascii data', () => {
      renderAndSelectSource();
      typeFilter('décalé');
      expect(screen.getByText(decaleText)).toBeInTheDocument();
      expect(screen.queryByText(skyText)).not.toBeInTheDocument();
    });
  });
});
