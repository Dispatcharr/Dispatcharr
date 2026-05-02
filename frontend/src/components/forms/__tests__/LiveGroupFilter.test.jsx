import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import LiveGroupFilter from '../LiveGroupFilter';

// ── Store mocks ────────────────────────────────────────────────────────────────
vi.mock('../../../store/channels', () => ({ default: vi.fn() }));
vi.mock('../../../store/streamProfiles', () => ({ default: vi.fn() }));

// ── Hook mocks ─────────────────────────────────────────────────────────────────
vi.mock('../../../hooks/useSmartLogos', () => ({
  useChannelLogoSelection: vi.fn(),
}));

// ── Utility mocks ──────────────────────────────────────────────────────────────
vi.mock('../../../utils/forms/LiveGroupFilterUtils', () => ({
  ADVANCED_OPTIONS_CONFIG: [
    {
      value: 'stream_profile',
      label: 'Stream Profile',
      description:
        'Assign a specific stream profile to all channels in this group during auto sync',
      isActive: (p) => p.stream_profile_id !== undefined,
      defaults: { stream_profile_id: null },
      removeKeys: ['stream_profile_id'],
    },
  ],
  getEPGs: vi.fn(),
  getEpgSourceData: vi.fn(),
  getEpgSourceValue: vi.fn(),
  getSelectedAdvancedOptions: vi.fn(),
  applyAdvancedOptionsChange: vi.fn(),
}));

// ── Component mocks ────────────────────────────────────────────────────────────
vi.mock('../Logo', () => ({
  default: ({ isOpen, onClose, onSuccess }) =>
    isOpen ? (
      <div data-testid="logo-form">
        <button data-testid="logo-form-close" onClick={onClose}>
          Close
        </button>
        <button
          data-testid="logo-form-success"
          onClick={() => onSuccess({ logo: { id: 99 } })}
        >
          Submit
        </button>
      </div>
    ) : null,
}));

vi.mock('../../LazyLogo', () => ({
  default: ({ logoId, alt }) => (
    <img data-testid="lazy-logo" alt={alt} data-logo-id={logoId} />
  ),
}));

vi.mock('react-window', () => ({
  FixedSizeList: ({ children, itemCount }) => (
    <div data-testid="fixed-size-list">
      {Array.from({ length: itemCount }, (_, index) =>
        children({ index, style: {} })
      )}
    </div>
  ),
}));

vi.mock('../../../images/logo.png', () => ({ default: 'logo.png' }));

// ── Mantine core ───────────────────────────────────────────────────────────────
vi.mock('@mantine/core', async () => ({
  TextInput: ({
    label,
    placeholder,
    value,
    onChange,
    onClick,
    readOnly,
    size,
  }) => (
    <input
      aria-label={label || placeholder}
      placeholder={placeholder}
      value={value || ''}
      onChange={onChange}
      onClick={onClick}
      readOnly={readOnly}
      data-size={size}
    />
  ),
  Button: ({ children, onClick, disabled, variant, size, leftSection }) => (
    <button
      onClick={onClick}
      disabled={disabled}
      data-variant={variant}
      data-size={size}
    >
      {leftSection}
      {children}
    </button>
  ),
  Checkbox: ({ label, checked, onChange, disabled, size, description }) => (
    <label>
      <input
        type="checkbox"
        aria-label={label}
        checked={checked}
        onChange={onChange}
        disabled={disabled}
        data-size={size}
      />
      {label}
      {description && (
        <span data-testid="checkbox-description">{description}</span>
      )}
    </label>
  ),
  Flex: ({ children, gap }) => <div data-gap={gap}>{children}</div>,
  Select: ({ label, placeholder, value, onChange, data, size }) => (
    <select
      aria-label={label || placeholder}
      value={value || ''}
      onChange={(e) => onChange(e.target.value || null)}
      data-size={size}
    >
      <option value="">{placeholder || label}</option>
      {data?.map((d) => (
        <option key={d.value} value={d.value}>
          {d.label}
        </option>
      ))}
    </select>
  ),
  Stack: ({ children, gap }) => <div data-gap={gap}>{children}</div>,
  Group: ({ children, justify }) => (
    <div data-justify={justify}>{children}</div>
  ),
  SimpleGrid: ({ children }) => <div data-testid="simple-grid">{children}</div>,
  Text: ({ children, size, c }) => (
    <span data-size={size} data-color={c}>
      {children}
    </span>
  ),
  NumberInput: ({ label, value, onChange, min, step, size }) => (
    <input
      type="number"
      aria-label={label}
      value={value || ''}
      onChange={(e) => onChange(Number(e.target.value))}
      min={min}
      step={step}
      data-size={size}
    />
  ),
  Divider: ({ label }) => <hr aria-label={label} />,
  Alert: ({ children, icon }) => (
    <div data-testid="alert">
      {icon}
      {children}
    </div>
  ),
  Box: ({ children, style }) => <div style={style}>{children}</div>,
  MultiSelect: ({ label, placeholder, value, onChange, data, size }) => (
    <select
      aria-label={label || placeholder}
      multiple
      value={value || []}
      onChange={(e) => {
        const selected = Array.from(e.target.selectedOptions).map(
          (o) => o.value
        );
        onChange(selected);
      }}
      data-size={size}
    >
      {data?.map((d) => (
        <option key={d.value} value={d.value}>
          {d.label}
        </option>
      ))}
    </select>
  ),
  Tooltip: ({ children, label, disabled }) => (
    <div data-tooltip={label} data-tooltip-disabled={disabled}>
      {children}
    </div>
  ),
  Popover: ({ children, opened }) => (
    <div data-testid="popover" data-opened={opened}>
      {children}
    </div>
  ),
  ScrollArea: ({ children, style }) => <div style={style}>{children}</div>,
  Center: ({ children }) => <div data-testid="center">{children}</div>,
  SegmentedControl: ({ value, onChange, data }) => (
    <div data-testid="segmented-control">
      {data?.map((d) => (
        <button
          key={d.value}
          data-active={value === d.value}
          onClick={() => onChange(d.value)}
        >
          {d.label}
        </button>
      ))}
    </div>
  ),
  PopoverTarget: ({ children }) => <div>{children}</div>,
  PopoverDropdown: ({ children, onMouseDown }) => (
    <div data-testid="popover-dropdown" onMouseDown={onMouseDown}>
      {children}
    </div>
  ),
}));

// ── lucide-react ───────────────────────────────────────────────────────────────
vi.mock('lucide-react', () => ({
  Info: () => <svg data-testid="icon-info" />,
  CircleCheck: () => <svg data-testid="icon-circle-check" />,
  CircleX: () => <svg data-testid="icon-circle-x" />,
}));

// ──────────────────────────────────────────────────────────────────────────────
// Imports after mocks
// ──────────────────────────────────────────────────────────────────────────────
import useChannelsStore from '../../../store/channels';
import useStreamProfilesStore from '../../../store/streamProfiles';
import { useChannelLogoSelection } from '../../../hooks/useSmartLogos';
import {
  getEPGs,
  getEpgSourceData,
} from '../../../utils/forms/LiveGroupFilterUtils.js';

// ── Fixtures ───────────────────────────────────────────────────────────────────
const makeChannelGroup = (id, name) => ({ id, name });

const makeGroupState = (overrides = {}) => ({
  channel_group: 1,
  name: 'Sports',
  enabled: true,
  auto_channel_sync: false,
  auto_sync_channel_start: 1,
  original_enabled: true,
  custom_properties: {},
  ...overrides,
});

const makePlaylist = (groups = []) => ({
  channel_groups: groups,
});

const defaultChannelGroups = {
  1: makeChannelGroup(1, 'Sports'),
  2: makeChannelGroup(2, 'News'),
  3: makeChannelGroup(3, 'Movies'),
};

const defaultProfiles = {
  1: { id: 1, name: 'Profile A' },
  2: { id: 2, name: 'Profile B' },
};

const defaultStreamProfiles = [
  { id: 10, name: 'Stream HD' },
  { id: 11, name: 'Stream SD' },
];

const setupStoreMocks = ({
  channelGroups = defaultChannelGroups,
  profiles = defaultProfiles,
  streamProfiles = defaultStreamProfiles,
  fetchStreamProfiles = vi.fn(),
} = {}) => {
  vi.mocked(useChannelsStore).mockImplementation((sel) =>
    sel({ channelGroups, profiles })
  );
  vi.mocked(useStreamProfilesStore).mockImplementation((sel) =>
    sel({ profiles: streamProfiles, fetchProfiles: fetchStreamProfiles })
  );
};

const setupLogoMock = ({
  logos = { 5: { id: 5, name: 'My Logo', url: '/logos/5.png' } },
  ensureLogosLoaded = vi.fn(),
  isLoading = false,
} = {}) => {
  vi.mocked(useChannelLogoSelection).mockReturnValue({
    logos,
    ensureLogosLoaded,
    isLoading,
  });
  return { ensureLogosLoaded };
};

const defaultProps = ({
  groupStates = [],
  setGroupStates = vi.fn(),
  autoEnableNewGroupsLive = true,
  setAutoEnableNewGroupsLive = vi.fn(),
  playlist = makePlaylist([]),
} = {}) => ({
  playlist,
  groupStates,
  setGroupStates,
  autoEnableNewGroupsLive,
  setAutoEnableNewGroupsLive,
});

// ──────────────────────────────────────────────────────────────────────────────

describe('LiveGroupFilter', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    setupStoreMocks();
    setupLogoMock();
    vi.mocked(getEPGs).mockResolvedValue([]);
  });

  // ── Rendering ────────────────────────────────────────────────────────────

  describe('rendering', () => {
    it('renders the info alert', async () => {
      render(<LiveGroupFilter {...defaultProps()} />);
      await waitFor(() => {
        expect(screen.getByTestId('alert')).toBeInTheDocument();
        expect(screen.getByText(/Auto Channel Sync/)).toBeInTheDocument();
      });
    });

    it('renders auto-enable checkbox with correct checked state', async () => {
      render(
        <LiveGroupFilter {...defaultProps({ autoEnableNewGroupsLive: true })} />
      );
      const checkbox = screen.getByRole('checkbox', {
        name: /Automatically enable new groups/i,
      });
      await waitFor(() => {
        expect(checkbox).toBeChecked();
      });
    });

    it('renders auto-enable checkbox unchecked when false', () => {
      render(
        <LiveGroupFilter
          {...defaultProps({ autoEnableNewGroupsLive: false })}
        />
      );
      const checkbox = screen.getByRole('checkbox', {
        name: /Automatically enable new groups/i,
      });
      expect(checkbox).not.toBeChecked();
    });

    it('renders filter input', async () => {
      render(<LiveGroupFilter {...defaultProps()} />);
      await waitFor(() => {
        expect(
          screen.getByPlaceholderText('Filter groups...')
        ).toBeInTheDocument();
      });
    });

    it('renders All/Enabled/Disabled segmented control', async () => {
      render(<LiveGroupFilter {...defaultProps()} />);
      await waitFor(() => {
        expect(screen.getByText('All')).toBeInTheDocument();
        expect(screen.getByText('Enabled')).toBeInTheDocument();
        expect(screen.getByText('Disabled')).toBeInTheDocument();
      });
    });

    it('renders Select Visible and Deselect Visible buttons', async () => {
      render(<LiveGroupFilter {...defaultProps()} />);
      await waitFor(() => {
        expect(screen.getByText('Select Visible')).toBeInTheDocument();
        expect(screen.getByText('Deselect Visible')).toBeInTheDocument();
      });
    });

    it('renders group cards', async () => {
      const groupStates = [makeGroupState()];
      render(<LiveGroupFilter {...defaultProps({ groupStates })} />);
      await waitFor(() => {
        expect(screen.getByText('Sports')).toBeInTheDocument();
      });
    });

    it('renders no group cards when groupStates is empty', () => {
      render(<LiveGroupFilter {...defaultProps({ groupStates: [] })} />);
      expect(screen.queryByTestId('icon-circle-check')).not.toBeInTheDocument();
    });

    it('renders enabled group with CircleCheck icon', async () => {
      const groupStates = [makeGroupState({ enabled: true })];
      render(<LiveGroupFilter {...defaultProps({ groupStates })} />);
      await waitFor(() => {
        expect(screen.getByTestId('icon-circle-check')).toBeInTheDocument();
      });
    });

    it('renders disabled group with CircleX icon', async () => {
      const groupStates = [makeGroupState({ enabled: false })];
      render(<LiveGroupFilter {...defaultProps({ groupStates })} />);
      await waitFor(() => {
        expect(screen.getByTestId('icon-circle-x')).toBeInTheDocument();
      });
    });
  });

  // ── Initialization ───────────────────────────────────────────────────────

  describe('initialization', () => {
    it('calls ensureLogosLoaded on mount', () => {
      const { ensureLogosLoaded } = setupLogoMock();
      render(<LiveGroupFilter {...defaultProps()} />);
      expect(ensureLogosLoaded).toHaveBeenCalled();
    });

    it('calls fetchStreamProfiles when streamProfiles is empty', () => {
      const fetchStreamProfiles = vi.fn();
      setupStoreMocks({ streamProfiles: [], fetchStreamProfiles });
      render(<LiveGroupFilter {...defaultProps()} />);
      expect(fetchStreamProfiles).toHaveBeenCalled();
    });

    it('does not call fetchStreamProfiles when streamProfiles already loaded', () => {
      const fetchStreamProfiles = vi.fn();
      setupStoreMocks({ fetchStreamProfiles });
      render(<LiveGroupFilter {...defaultProps()} />);
      expect(fetchStreamProfiles).not.toHaveBeenCalled();
    });

    it('calls getEPGs on mount', async () => {
      render(<LiveGroupFilter {...defaultProps()} />);
      await waitFor(() => expect(getEPGs).toHaveBeenCalled());
    });

    it('handles getEPGs failure gracefully', async () => {
      vi.mocked(getEPGs).mockRejectedValue(new Error('Network error'));
      expect(() =>
        render(<LiveGroupFilter {...defaultProps()} />)
      ).not.toThrow();
    });
  });

  // ── setGroupStates on playlist/channelGroups change ──────────────────────

  describe('setGroupStates from playlist', () => {
    it('calls setGroupStates when channelGroups and playlist are set', () => {
      const setGroupStates = vi.fn();
      const playlist = makePlaylist([
        {
          channel_group: 1,
          enabled: true,
          auto_channel_sync: false,
          auto_sync_channel_start: 1,
        },
      ]);
      render(
        <LiveGroupFilter {...defaultProps({ playlist, setGroupStates })} />
      );
      expect(setGroupStates).toHaveBeenCalled();
    });

    it('skips groups that are not in channelGroups', () => {
      const setGroupStates = vi.fn();
      const playlist = makePlaylist([{ channel_group: 999, enabled: true }]);
      render(
        <LiveGroupFilter {...defaultProps({ playlist, setGroupStates })} />
      );
      expect(setGroupStates).toHaveBeenCalledWith([]);
    });

    it('parses custom_properties string in playlist groups', () => {
      const setGroupStates = vi.fn();
      const playlist = makePlaylist([
        {
          channel_group: 1,
          enabled: true,
          auto_channel_sync: false,
          auto_sync_channel_start: 1,
          custom_properties: JSON.stringify({ foo: 'bar' }),
        },
      ]);
      render(
        <LiveGroupFilter {...defaultProps({ playlist, setGroupStates })} />
      );
      const [mappedGroups] =
        setGroupStates.mock.calls[setGroupStates.mock.calls.length - 1];
      expect(mappedGroups[0].custom_properties).toEqual({ foo: 'bar' });
    });

    it('handles invalid custom_properties JSON gracefully', () => {
      const setGroupStates = vi.fn();
      const playlist = makePlaylist([
        { channel_group: 1, enabled: true, custom_properties: '{invalid}' },
      ]);
      expect(() =>
        render(
          <LiveGroupFilter {...defaultProps({ playlist, setGroupStates })} />
        )
      ).not.toThrow();
    });

    it('does not call setGroupStates when channelGroups is empty', () => {
      setupStoreMocks({ channelGroups: {} });
      const setGroupStates = vi.fn();
      render(<LiveGroupFilter {...defaultProps({ setGroupStates })} />);
      expect(setGroupStates).not.toHaveBeenCalled();
    });
  });

  // ── autoEnableNewGroupsLive checkbox ─────────────────────────────────────

  describe('autoEnableNewGroupsLive toggle', () => {
    it('calls setAutoEnableNewGroupsLive when checkbox is changed', () => {
      const setAutoEnableNewGroupsLive = vi.fn();
      render(
        <LiveGroupFilter
          {...defaultProps({
            autoEnableNewGroupsLive: true,
            setAutoEnableNewGroupsLive,
          })}
        />
      );
      fireEvent.click(
        screen.getByRole('checkbox', {
          name: /Automatically enable new groups/i,
        })
      );
      expect(setAutoEnableNewGroupsLive).toHaveBeenCalled();
    });
  });

  // ── toggleGroupEnabled ───────────────────────────────────────────────────

  describe('toggleGroupEnabled', () => {
    it('calls setGroupStates toggling enabled for matching group', async () => {
      const groupStates = [makeGroupState({ enabled: true })];
      let lastUpdater;
      const setGroupStates = vi.fn((arg) => {
        if (typeof arg === 'function') lastUpdater = arg;
      });
      render(
        <LiveGroupFilter {...defaultProps({ groupStates, setGroupStates })} />
      );

      fireEvent.click(screen.getByText('Sports'));
      await waitFor(() => {
        expect(setGroupStates).toHaveBeenCalled();
        const result = lastUpdater(groupStates);
        expect(result).toEqual(
          expect.arrayContaining([
            expect.objectContaining({ channel_group: 1, enabled: false }),
          ])
        );
      });
    });

    it('does not toggle unrelated group', async () => {
      const groupStates = [
        makeGroupState({ channel_group: 1, name: 'Sports', enabled: true }),
        makeGroupState({ channel_group: 2, name: 'News', enabled: true }),
      ];
      let lastUpdater;
      const setGroupStates = vi.fn((arg) => {
        if (typeof arg === 'function') lastUpdater = arg;
      });
      render(
        <LiveGroupFilter {...defaultProps({ groupStates, setGroupStates })} />
      );
      const buttons = screen.getAllByRole('button', { name: /Sports/ });
      fireEvent.click(buttons[0]); // click Sports
      await waitFor(() => {
        expect(setGroupStates).toHaveBeenCalled();
        const result = lastUpdater(groupStates);
        expect(result[0].enabled).toBe(false);
        expect(result[1].enabled).toBe(true);
      });
    });
  });

  // ── Filter ───────────────────────────────────────────────────────────────

  describe('group text filter', () => {
    it('filters groups by name text', () => {
      const groupStates = [
        makeGroupState({ channel_group: 1, name: 'Sports' }),
        makeGroupState({ channel_group: 2, name: 'News' }),
      ];
      render(<LiveGroupFilter {...defaultProps({ groupStates })} />);
      fireEvent.change(screen.getByPlaceholderText('Filter groups...'), {
        target: { value: 'sport' },
      });
      expect(screen.getByText('Sports')).toBeInTheDocument();
      expect(screen.queryByText('News')).not.toBeInTheDocument();
    });

    it('shows all groups when filter is cleared', () => {
      const groupStates = [
        makeGroupState({ channel_group: 1, name: 'Sports' }),
        makeGroupState({ channel_group: 2, name: 'News' }),
      ];
      render(<LiveGroupFilter {...defaultProps({ groupStates })} />);
      const input = screen.getByPlaceholderText('Filter groups...');
      fireEvent.change(input, { target: { value: 'sport' } });
      fireEvent.change(input, { target: { value: '' } });
      expect(screen.getByText('Sports')).toBeInTheDocument();
      expect(screen.getByText('News')).toBeInTheDocument();
    });
  });

  // ── Status filter ─────────────────────────────────────────────────────────

  describe('status filter', () => {
    it('filters to only enabled groups', () => {
      const groupStates = [
        makeGroupState({ channel_group: 1, name: 'Sports', enabled: true }),
        makeGroupState({ channel_group: 2, name: 'News', enabled: false }),
      ];
      render(<LiveGroupFilter {...defaultProps({ groupStates })} />);
      fireEvent.click(screen.getByText('Enabled'));
      expect(screen.getByText('Sports')).toBeInTheDocument();
      expect(screen.queryByText('News')).not.toBeInTheDocument();
    });

    it('filters to only disabled groups', () => {
      const groupStates = [
        makeGroupState({ channel_group: 1, name: 'Sports', enabled: true }),
        makeGroupState({ channel_group: 2, name: 'News', enabled: false }),
      ];
      render(<LiveGroupFilter {...defaultProps({ groupStates })} />);
      fireEvent.click(screen.getByText('Disabled'));
      expect(screen.queryByText('Sports')).not.toBeInTheDocument();
      expect(screen.getByText('News')).toBeInTheDocument();
    });

    it('shows all groups when All is selected', () => {
      const groupStates = [
        makeGroupState({ channel_group: 1, name: 'Sports', enabled: true }),
        makeGroupState({ channel_group: 2, name: 'News', enabled: false }),
      ];
      render(<LiveGroupFilter {...defaultProps({ groupStates })} />);
      fireEvent.click(screen.getByText('Disabled'));
      fireEvent.click(screen.getByText('All'));
      expect(screen.getByText('Sports')).toBeInTheDocument();
      expect(screen.getByText('News')).toBeInTheDocument();
    });
  });

  // ── selectAll / deselectAll ───────────────────────────────────────────────

  describe('Select / Deselect Visible', () => {
    it('selectAll enables all visible groups', async () => {
      let lastUpdater;
      const setGroupStates = vi.fn((arg) => {
        if (typeof arg === 'function') lastUpdater = arg;
      });
      const groupStates = [
        makeGroupState({ channel_group: 1, name: 'Sports', enabled: false }),
        makeGroupState({ channel_group: 2, name: 'News', enabled: false }),
      ];
      render(
        <LiveGroupFilter {...defaultProps({ groupStates, setGroupStates })} />
      );
      fireEvent.click(screen.getByText('Select Visible'));
      await waitFor(() => {
        expect(setGroupStates).toHaveBeenCalled();
        const result = lastUpdater(groupStates);
        expect(result[0].enabled).toBe(true);
        expect(result[1].enabled).toBe(true);
      });
    });

    it('deselectAll disables all visible groups', async () => {
      let lastUpdater;
      const setGroupStates = vi.fn((arg) => {
        if (typeof arg === 'function') lastUpdater = arg;
      });
      const groupStates = [
        makeGroupState({ channel_group: 1, name: 'Sports', enabled: true }),
        makeGroupState({ channel_group: 2, name: 'News', enabled: true }),
      ];
      render(
        <LiveGroupFilter {...defaultProps({ groupStates, setGroupStates })} />
      );
      fireEvent.click(screen.getByText('Deselect Visible'));
      await waitFor(() => {
        expect(setGroupStates).toHaveBeenCalled();
        const result = lastUpdater(groupStates);
        expect(result[0].enabled).toBe(false);
        expect(result[1].enabled).toBe(false);
      });
    });

    it('selectAll only enables visible (filtered) groups', async () => {
      let lastUpdater;
      const setGroupStates = vi.fn((arg) => {
        if (typeof arg === 'function') lastUpdater = arg;
      });
      const groupStates = [
        makeGroupState({ channel_group: 1, name: 'Sports', enabled: false }),
        makeGroupState({ channel_group: 2, name: 'News', enabled: false }),
      ];
      render(
        <LiveGroupFilter {...defaultProps({ groupStates, setGroupStates })} />
      );
      fireEvent.change(screen.getByPlaceholderText('Filter groups...'), {
        target: { value: 'Sports' },
      });
      fireEvent.click(screen.getByText('Select Visible'));
      await waitFor(() => {
        expect(setGroupStates).toHaveBeenCalled();
        const result = lastUpdater(groupStates);
        expect(result[0].enabled).toBe(true); // Sports - visible
        expect(result[1].enabled).toBe(false); // News - hidden
      });
    });
  });

  // ── Auto Channel Sync checkbox ────────────────────────────────────────────

  describe('Auto Channel Sync', () => {
    it('renders Auto Channel Sync checkbox when group is enabled', () => {
      const groupStates = [makeGroupState({ enabled: true })];
      render(<LiveGroupFilter {...defaultProps({ groupStates })} />);
      expect(
        screen.getByRole('checkbox', { name: /Auto Channel Sync/i })
      ).toBeInTheDocument();
    });

    it('Auto Channel Sync checkbox is disabled when group is disabled', () => {
      const groupStates = [makeGroupState({ enabled: false })];
      render(<LiveGroupFilter {...defaultProps({ groupStates })} />);
      expect(
        screen.getByRole('checkbox', { name: /Auto Channel Sync/i })
      ).toBeDisabled();
    });

    it('toggleAutoSync calls setGroupStates toggling auto_channel_sync', async () => {
      let lastUpdater;
      const setGroupStates = vi.fn((arg) => {
        if (typeof arg === 'function') lastUpdater = arg;
      });
      const groupStates = [
        makeGroupState({ enabled: true, auto_channel_sync: false }),
      ];
      render(
        <LiveGroupFilter {...defaultProps({ groupStates, setGroupStates })} />
      );
      fireEvent.click(
        screen.getByRole('checkbox', { name: /Auto Channel Sync/i })
      );
      await waitFor(() => {
        expect(setGroupStates).toHaveBeenCalled();
        const result = lastUpdater(groupStates);
        expect(result[0].auto_channel_sync).toBe(true);
      });
    });

    it('shows Start Channel # input when auto_channel_sync is enabled', () => {
      const groupStates = [
        makeGroupState({ enabled: true, auto_channel_sync: true }),
      ];
      render(<LiveGroupFilter {...defaultProps({ groupStates })} />);
      expect(
        screen.getByRole('spinbutton', { name: /Start Channel #/i })
      ).toBeInTheDocument();
    });

    it('hides Start Channel # when auto_channel_sync is false', () => {
      const groupStates = [
        makeGroupState({ enabled: true, auto_channel_sync: false }),
      ];
      render(<LiveGroupFilter {...defaultProps({ groupStates })} />);
      expect(
        screen.queryByRole('spinbutton', { name: /Start Channel #/i })
      ).not.toBeInTheDocument();
    });

    it('updateChannelStart calls setGroupStates with new value', async () => {
      let lastUpdater;
      const setGroupStates = vi.fn((arg) => {
        if (typeof arg === 'function') lastUpdater = arg;
      });
      const groupStates = [
        makeGroupState({ enabled: true, auto_channel_sync: true }),
      ];
      render(
        <LiveGroupFilter {...defaultProps({ groupStates, setGroupStates })} />
      );
      fireEvent.change(
        screen.getByRole('spinbutton', { name: /Start Channel #/i }),
        {
          target: { value: '100' },
        }
      );
      await waitFor(() => {
        expect(setGroupStates).toHaveBeenCalled();
        const result = lastUpdater(groupStates);
        expect(result[0].auto_sync_channel_start).toBe(100);
      });
    });
  });

  // ── Channel Numbering Mode ────────────────────────────────────────────────

  describe('Channel Numbering Mode', () => {
    it('shows Channel Numbering Mode select when auto_channel_sync enabled', () => {
      const groupStates = [
        makeGroupState({ enabled: true, auto_channel_sync: true }),
      ];
      render(<LiveGroupFilter {...defaultProps({ groupStates })} />);
      expect(
        screen.getByRole('combobox', { name: /Channel Numbering Mode/i })
      ).toBeInTheDocument();
    });

    it('shows Fallback Channel # when numbering mode is provider', () => {
      const groupStates = [
        makeGroupState({
          enabled: true,
          auto_channel_sync: true,
          custom_properties: { channel_numbering_mode: 'provider' },
        }),
      ];
      render(<LiveGroupFilter {...defaultProps({ groupStates })} />);
      expect(
        screen.getByRole('spinbutton', { name: /Fallback Channel #/i })
      ).toBeInTheDocument();
    });

    it('hides Start Channel # when mode is not fixed', () => {
      const groupStates = [
        makeGroupState({
          enabled: true,
          auto_channel_sync: true,
          custom_properties: { channel_numbering_mode: 'next_available' },
        }),
      ];
      render(<LiveGroupFilter {...defaultProps({ groupStates })} />);
      expect(
        screen.queryByRole('spinbutton', { name: /Start Channel #/i })
      ).not.toBeInTheDocument();
    });

    it('updating Channel Numbering Mode calls setGroupStates', () => {
      const setGroupStates = vi.fn();
      const groupStates = [
        makeGroupState({ enabled: true, auto_channel_sync: true }),
      ];
      render(
        <LiveGroupFilter {...defaultProps({ groupStates, setGroupStates })} />
      );
      fireEvent.change(
        screen.getByRole('combobox', { name: /Channel Numbering Mode/i }),
        {
          target: { value: 'provider' },
        }
      );
      expect(setGroupStates).toHaveBeenCalled();
    });
  });

  // ── Advanced Options MultiSelect ──────────────────────────────────────────

  describe('Advanced Options MultiSelect', () => {
    const makeAutoSyncGroup = (customProps = {}) =>
      makeGroupState({
        enabled: true,
        auto_channel_sync: true,
        custom_properties: customProps,
      });

    it('renders Advanced Options multiselect when auto_channel_sync is enabled', () => {
      render(
        <LiveGroupFilter
          {...defaultProps({ groupStates: [makeAutoSyncGroup()] })}
        />
      );
      expect(
        screen.getByRole('listbox', { name: /Advanced Options/i })
      ).toBeInTheDocument();
    });

    it('shows Channel Name Find input when name_regex_pattern is set', () => {
      const groupStates = [
        makeAutoSyncGroup({
          name_regex_pattern: '.*',
          name_replace_pattern: '$1',
        }),
      ];
      render(<LiveGroupFilter {...defaultProps({ groupStates })} />);
      expect(
        screen.getByRole('textbox', { name: /Channel Name Find/i })
      ).toBeInTheDocument();
    });

    it('shows Channel Name Replace input when name_replace_pattern is set', () => {
      const groupStates = [
        makeAutoSyncGroup({
          name_regex_pattern: '.*',
          name_replace_pattern: '$1',
        }),
      ];
      render(<LiveGroupFilter {...defaultProps({ groupStates })} />);
      expect(
        screen.getByRole('textbox', { name: /Channel Name Replace/i })
      ).toBeInTheDocument();
    });

    it('shows Channel Name Filter input when name_match_regex is set', () => {
      const groupStates = [makeAutoSyncGroup({ name_match_regex: '^Sports' })];
      render(<LiveGroupFilter {...defaultProps({ groupStates })} />);
      expect(
        screen.getByRole('textbox', { name: /Channel Name Filter/i })
      ).toBeInTheDocument();
    });

    it('shows Channel Profiles multiselect when channel_profile_ids is set', () => {
      const groupStates = [makeAutoSyncGroup({ channel_profile_ids: [] })];
      render(<LiveGroupFilter {...defaultProps({ groupStates })} />);
      expect(
        screen.getByRole('listbox', { name: /Channel Profiles/i })
      ).toBeInTheDocument();
    });

    it('shows Override Channel Group select when group_override is set', () => {
      const groupStates = [makeAutoSyncGroup({ group_override: null })];
      render(<LiveGroupFilter {...defaultProps({ groupStates })} />);
      expect(
        screen.getByRole('combobox', { name: /Override Channel Group/i })
      ).toBeInTheDocument();
    });

    it('shows Stream Profile select when stream_profile_id is set', () => {
      const groupStates = [makeAutoSyncGroup({ stream_profile_id: null })];
      render(<LiveGroupFilter {...defaultProps({ groupStates })} />);
      expect(
        screen.getByRole('combobox', { name: /Stream Profile/i })
      ).toBeInTheDocument();
    });

    it('shows Channel Sort Order select when channel_sort_order is set', () => {
      const groupStates = [makeAutoSyncGroup({ channel_sort_order: '' })];
      render(<LiveGroupFilter {...defaultProps({ groupStates })} />);
      expect(
        screen.getByRole('combobox', { name: /Channel Sort Order/i })
      ).toBeInTheDocument();
    });

    it('shows Reverse Sort Order checkbox when channel_sort_order is set', () => {
      const groupStates = [
        makeAutoSyncGroup({
          channel_sort_order: '',
          channel_sort_reverse: false,
        }),
      ];
      render(<LiveGroupFilter {...defaultProps({ groupStates })} />);
      expect(
        screen.getByRole('checkbox', { name: /Reverse Sort Order/i })
      ).toBeInTheDocument();
    });

    it('shows EPG Source select when force_dummy_epg is set', () => {
      const groupStates = [makeAutoSyncGroup({ force_dummy_epg: true })];
      render(<LiveGroupFilter {...defaultProps({ groupStates })} />);
      expect(
        screen.getByRole('combobox', { name: /EPG Source/i })
      ).toBeInTheDocument();
    });

    it('shows EPG Source select when custom_epg_id is set', () => {
      const groupStates = [makeAutoSyncGroup({ custom_epg_id: 42 })];
      render(<LiveGroupFilter {...defaultProps({ groupStates })} />);
      expect(
        screen.getByRole('combobox', { name: /EPG Source/i })
      ).toBeInTheDocument();
    });
  });

  // ── Logo handling ─────────────────────────────────────────────────────────

  describe('custom logo', () => {
    const makeLogoGroup = () =>
      makeGroupState({
        enabled: true,
        auto_channel_sync: true,
        custom_properties: { custom_logo_id: null },
      });

    it('shows Upload or Create Logo button when custom_logo_id is set', () => {
      const groupStates = [makeLogoGroup()];
      render(<LiveGroupFilter {...defaultProps({ groupStates })} />);
      expect(screen.getByText('Upload or Create Logo')).toBeInTheDocument();
    });

    it('opens LogoForm when Upload or Create Logo is clicked', () => {
      const groupStates = [makeLogoGroup()];
      render(<LiveGroupFilter {...defaultProps({ groupStates })} />);
      fireEvent.click(screen.getByText('Upload or Create Logo'));
      expect(screen.getByTestId('logo-form')).toBeInTheDocument();
    });

    it('closes LogoForm when close is clicked', () => {
      const groupStates = [makeLogoGroup()];
      render(<LiveGroupFilter {...defaultProps({ groupStates })} />);
      fireEvent.click(screen.getByText('Upload or Create Logo'));
      fireEvent.click(screen.getByTestId('logo-form-close'));
      expect(screen.queryByTestId('logo-form')).not.toBeInTheDocument();
    });

    it('calls setGroupStates with new logo id on success', async () => {
      let lastUpdater;
      const setGroupStates = vi.fn((arg) => {
        if (typeof arg === 'function') lastUpdater = arg;
      });
      const groupStates = [makeLogoGroup()];
      render(
        <LiveGroupFilter {...defaultProps({ groupStates, setGroupStates })} />
      );
      fireEvent.click(screen.getByText('Upload or Create Logo'));
      fireEvent.click(screen.getByTestId('logo-form-success'));
      expect(setGroupStates).toHaveBeenCalled();
      await waitFor(() => {
        expect(setGroupStates).toHaveBeenCalled();
        const result = lastUpdater(groupStates);
        expect(result[0].custom_properties.custom_logo_id).toBe(99);
      });
    });

    it('closes LogoForm after successful logo upload', () => {
      const groupStates = [makeLogoGroup()];
      render(<LiveGroupFilter {...defaultProps({ groupStates })} />);
      fireEvent.click(screen.getByText('Upload or Create Logo'));
      fireEvent.click(screen.getByTestId('logo-form-success'));
      expect(screen.queryByTestId('logo-form')).not.toBeInTheDocument();
    });
  });

  // ── EPG sources loaded from API ───────────────────────────────────────────

  describe('EPG sources', () => {
    it('populates EPG Source select with sources from API', async () => {
      vi.mocked(getEpgSourceData).mockReturnValue([
        { id: 1, value: 'epg_one', label: 'EPG One' },
        { id: 2, value: 'epg_two', label: 'EPG Two' },
      ]);
      const groupStates = [
        makeGroupState({
          enabled: true,
          auto_channel_sync: true,
          custom_properties: { force_dummy_epg: true },
        }),
      ];
      render(<LiveGroupFilter {...defaultProps({ groupStates })} />);
      await waitFor(() => {
        expect(
          screen.getByRole('option', { name: /EPG One/i })
        ).toBeInTheDocument();
        expect(
          screen.getByRole('option', { name: /EPG Two/i })
        ).toBeInTheDocument();
      });
    });
  });

  // ── Group sorting ─────────────────────────────────────────────────────────

  describe('group sorting', () => {
    it('renders groups sorted alphabetically', () => {
      const groupStates = [
        makeGroupState({ channel_group: 2, name: 'Zebra' }),
        makeGroupState({ channel_group: 1, name: 'Alpha' }),
      ];
      render(<LiveGroupFilter {...defaultProps({ groupStates })} />);
      const buttons = screen.getAllByRole('button', { name: /Alpha|Zebra/ });
      expect(buttons[0]).toHaveTextContent('Alpha');
      expect(buttons[1]).toHaveTextContent('Zebra');
    });
  });
});
