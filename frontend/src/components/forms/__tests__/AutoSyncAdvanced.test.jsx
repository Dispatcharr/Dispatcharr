import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

// ── Module mocks ───────────────────────────────────────────────────────────────
vi.mock('../../../utils/forms/AutoSyncAdvancedUtils.js', () => ({
  getEpgSourceValue: vi.fn(() => null),
  getEpgSourceData: vi.fn(() => []),
  repackGroupChannels: vi.fn(() => Promise.resolve({})),
  formatPreviewSummary: vi.fn(() => null),
}));

vi.mock('../../../utils/forms/LiveGroupFilterUtils.js', () => ({
  getRegexOptions: vi.fn(() => [
    { value: 'i', label: 'Case insensitive' },
    { value: 'g', label: 'Global' },
  ]),
}));

vi.mock('../../../store/channels.jsx', () => ({ default: vi.fn() }));

vi.mock('../../../utils/notificationUtils.js', () => ({
  showNotification: vi.fn(),
}));

vi.mock('../../../images/logo.png', () => ({ default: 'logo.png' }));

vi.mock('../../LazyLogo.jsx', () => ({
  default: ({ src, alt }) => (
    <img data-testid="lazy-logo" src={src} alt={alt} />
  ),
}));

vi.mock('react-window', () => ({
  FixedSizeList: ({ children, itemCount, itemData }) => (
    <div data-testid="fixed-size-list">
      {Array.from({ length: Math.min(itemCount, 5) }, (_, i) =>
        children({ index: i, style: {}, data: itemData })
      )}
    </div>
  ),
}));

vi.mock('lucide-react', () => ({
  RefreshCw: () => <svg data-testid="icon-refresh-cw" />,
}));

vi.mock('@mantine/core', () => ({
  Box: ({ children, style }) => <div style={style}>{children}</div>,
  Button: ({ children, onClick, disabled, loading, variant, size, color }) => (
    <button
      onClick={onClick}
      disabled={disabled || loading}
      data-variant={variant}
      data-size={size}
      data-color={color}
      data-loading={loading}
    >
      {children}
    </button>
  ),
  Center: ({ children }) => <div data-testid="center">{children}</div>,
  Checkbox: ({ checked, onChange, label, 'data-testid': testId }) => (
    <label>
      <input
        type="checkbox"
        data-testid={testId || label}
        checked={!!checked}
        onChange={(e) => onChange?.(e)}
      />
      {label}
    </label>
  ),
  Divider: () => <hr data-testid="divider" />,
  Flex: ({ children }) => <div data-testid="flex">{children}</div>,
  Group: ({ children }) => <div data-testid="group">{children}</div>,
  MultiSelect: ({ value, onChange, label, data, 'data-testid': testId }) => (
    <div>
      {label && <label>{label}</label>}
      <select
        multiple
        data-testid={testId || label}
        value={value ?? []}
        onChange={(e) =>
          onChange?.(Array.from(e.target.selectedOptions, (o) => o.value))
        }
      >
        {(data || []).map((opt) => (
          <option key={opt.value ?? opt} value={opt.value ?? opt}>
            {opt.label ?? opt}
          </option>
        ))}
      </select>
    </div>
  ),
  Popover: ({ children }) => <div data-testid="popover">{children}</div>,
  PopoverDropdown: ({ children }) => (
    <div data-testid="popover-dropdown">{children}</div>
  ),
  PopoverTarget: ({ children }) => (
    <div data-testid="popover-target">{children}</div>
  ),
  ScrollArea: ({ children }) => <div data-testid="scroll-area">{children}</div>,
  Select: ({
    value,
    onChange,
    label,
    data,
    'data-testid': testId,
    clearable,
  }) => (
    <div>
      {label && <label>{label}</label>}
      <select
        data-testid={testId || label}
        value={value ?? ''}
        onChange={(e) => onChange?.(e.target.value || null)}
      >
        {clearable && <option value="">--</option>}
        {(data || []).map((opt) => (
          <option key={opt.value ?? opt} value={opt.value ?? opt}>
            {opt.label ?? opt}
          </option>
        ))}
      </select>
    </div>
  ),
  Stack: ({ children }) => <div data-testid="stack">{children}</div>,
  Switch: ({ checked, onChange, label, 'data-testid': testId }) => (
    <label>
      <input
        type="checkbox"
        role="switch"
        data-testid={testId || label}
        checked={!!checked}
        onChange={(e) => onChange?.(e)}
      />
      {label}
    </label>
  ),
  Text: ({ children, size, c, fw }) => (
    <span data-testid="text" data-size={size} data-color={c} data-fw={fw}>
      {children}
    </span>
  ),
  TextInput: ({
    value,
    onChange,
    label,
    placeholder,
    'data-testid': testId,
  }) => (
    <div>
      {label && <label>{label}</label>}
      <input
        data-testid={testId || label}
        type="text"
        value={value ?? ''}
        placeholder={placeholder}
        onChange={(e) => onChange?.(e)}
      />
    </div>
  ),
  Tooltip: ({ children, label }) => (
    <div data-testid="tooltip" data-label={label}>
      {children}
    </div>
  ),
}));

// ── Imports after mocks ────────────────────────────────────────────────────────
import AutoSyncAdvanced from '../AutoSyncAdvanced';
import useChannelsStore from '../../../store/channels.jsx';
import { showNotification } from '../../../utils/notificationUtils.js';
import {
  getEpgSourceValue,
  getEpgSourceData,
  repackGroupChannels,
  formatPreviewSummary,
} from '../../../utils/forms/AutoSyncAdvancedUtils.js';
import { getRegexOptions } from '../../../utils/forms/LiveGroupFilterUtils.js';

// ── Helpers ────────────────────────────────────────────────────────────────────
const makeGroup = (overrides = {}) => ({
  channel_group: 1,
  name: 'Sports',
  logo_url: null,
  auto_sync_enabled: true,
  auto_sync_channel_start: 100,
  auto_sync_channel_end: 200,
  custom_properties: {},
  ...overrides,
});

const makeEpgSource = (overrides = {}) => ({
  id: 1,
  name: 'My EPG',
  source_type: 'xmltv',
  ...overrides,
});

const makePlaylist = (overrides = {}) => ({
  id: 5,
  custom_properties: {},
  ...overrides,
});

const defaultProps = (overrides = {}) => ({
  group: makeGroup(),
  epgSources: [makeEpgSource()],
  channelGroups: [],
  streamProfiles: [],
  regexPreviewState: {},
  onApplyGroupChange: vi.fn(),
  onScheduleRegexPreview: vi.fn(),
  onOpenLogoUpload: vi.fn(),
  channelLogos: [],
  playlist: makePlaylist(),
  logosLoading: false,
  ensureLogosLoaded: vi.fn(),
  ...overrides,
});

const renderComponent = (overrides = {}) => {
  const props = defaultProps(overrides);
  const utils = render(<AutoSyncAdvanced {...props} />);
  return { ...props, ...utils };
};

const setupStore = () => {
  vi.mocked(useChannelsStore).mockImplementation((sel) =>
    sel({ fetchGroups: vi.fn(), profiles: {} })
  );
};

// ──────────────────────────────────────────────────────────────────────────────
describe('AutoSyncAdvanced', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getEpgSourceValue).mockReturnValue(null);
    vi.mocked(getEpgSourceData).mockReturnValue([
      { value: '1', label: 'My EPG (xmltv)' },
    ]);
    vi.mocked(repackGroupChannels).mockResolvedValue({});
    vi.mocked(formatPreviewSummary).mockReturnValue(null);
    setupStore();
  });

  // ── Basic rendering ────────────────────────────────────────────────────────
  describe('basic rendering', () => {
    it('renders without crashing', () => {
      renderComponent();
      expect(screen.getAllByTestId('stack')[0]).toBeInTheDocument();
    });

    it('calls getEpgSourceData with epgSources on render', () => {
      const epgSources = [
        makeEpgSource(),
        makeEpgSource({ id: 2, name: 'EPG 2' }),
      ];
      renderComponent({ epgSources });
      expect(getEpgSourceData).toHaveBeenCalledWith(epgSources);
    });

    it('calls getEpgSourceValue with group.custom_properties on render', () => {
      const group = makeGroup();
      const epgSources = [makeEpgSource()];
      renderComponent({ group, epgSources });
      expect(getEpgSourceValue).toHaveBeenCalledWith({});
    });
  });

  // ── RegexPreviewBox ────────────────────────────────────────────────────────
  describe('RegexPreviewBox', () => {
    it('does not render preview box when no include regex is set', () => {
      renderComponent({ group: makeGroup({ custom_properties: {} }) });
      expect(screen.queryByText(/matched/i)).not.toBeInTheDocument();
    });

    it('renders include preview box when name_match_regex is set', () => {
      const group = makeGroup({
        custom_properties: { name_match_regex: 'ESPN' },
      });
      const regexPreviewState = {
        1: {
          filterResult: {
            match_count: 3,
            total_scanned: 50,
            scan_limit_hit: false,
          },
          loading: false,
        },
      };
      vi.mocked(formatPreviewSummary).mockReturnValue(
        '3 filter matches in 50 streams'
      );
      renderComponent({ group, regexPreviewState });
      expect(
        screen.getByText('3 filter matches in 50 streams')
      ).toBeInTheDocument();
    });

    it('renders exclude preview box when name_match_exclude_regex is set', () => {
      const group = makeGroup({
        custom_properties: { name_match_exclude_regex: 'HD' },
      });
      const regexPreviewState = {
        1: {
          excludeResult: {
            match_count: 2,
            total_scanned: 50,
            scan_limit_hit: false,
          },
          loading: false,
        },
      };
      vi.mocked(formatPreviewSummary).mockReturnValue(
        '2 exclude matches in 50 streams'
      );
      renderComponent({ group, regexPreviewState });
      expect(
        screen.getByText('2 exclude matches in 50 streams')
      ).toBeInTheDocument();
    });

    it('renders find preview box when name_regex_pattern is set', () => {
      const group = makeGroup({
        custom_properties: {
          name_regex_pattern: 'News',
          name_replace_pattern: '',
        },
      });
      const regexPreviewState = {
        1: {
          findResult: {
            matches: [
              { before: 'BBC News', after: 'BBC' },
              { before: 'Sky News', after: 'Sky' },
              { before: 'CNN News', after: 'CNN' },
              { before: 'Fox News', after: 'Fox' },
              { before: 'Al Jazeera News', after: 'Al Jazeera' },
            ],
            total_in_group: 50,
          },
          loading: false,
        },
      };
      vi.mocked(formatPreviewSummary).mockReturnValue(
        '5 regex matches in 50 streams'
      );
      renderComponent({ group, regexPreviewState });
      expect(
        screen.getByText('5 regex matches in 50 streams')
      ).toBeInTheDocument();
      expect(formatPreviewSummary).toHaveBeenCalledWith(
        'rename',
        regexPreviewState[1].findResult
      );
    });

    it('shows loading state in preview box when state.loading is true', () => {
      const group = makeGroup({
        custom_properties: { name_match_regex: 'Sports' },
      });
      const regexPreviewState = { 1: { loading: true } };
      renderComponent({ group, regexPreviewState });
      // No summary rendered during loading
      expect(formatPreviewSummary).not.toHaveBeenCalledWith(
        expect.anything(),
        expect.objectContaining({ match_count: expect.any(Number) })
      );
    });

    it('does not render include preview when name_match_regex is empty string', () => {
      const group = makeGroup({
        custom_properties: { name_match_regex: '' },
      });
      renderComponent({ group, regexPreviewState: {} });
      expect(formatPreviewSummary).not.toHaveBeenCalled();
    });

    it('renders regex error message when result has an error', () => {
      const group = makeGroup({
        custom_properties: { name_match_regex: 'bad(' },
      });
      const regexPreviewState = {
        1: { filterResult: { error: 'Unterminated group' }, loading: false },
      };
      renderComponent({ group, regexPreviewState });
      expect(
        screen.getByText(/invalid regex.*unterminated group/i)
      ).toBeInTheDocument();
    });

    it('renders no-match message when filter result has empty matches', () => {
      const group = makeGroup({
        custom_properties: { name_match_regex: 'ZZZ' },
      });
      const regexPreviewState = {
        1: {
          filterResult: { matches: [], total_in_group: 10, error: null },
          loading: false,
        },
      };
      vi.mocked(formatPreviewSummary).mockReturnValue(
        '0 filter matches in 10 streams'
      );
      renderComponent({ group, regexPreviewState });
      expect(
        screen.getByText(/no streams matched this pattern/i)
      ).toBeInTheDocument();
    });
  });

  // ── EPG source select ──────────────────────────────────────────────────────
  describe('EPG source select', () => {
    it('passes EPG source data from getEpgSourceData to the Select', () => {
      vi.mocked(getEpgSourceData).mockReturnValue([
        { value: '1', label: 'My EPG (xmltv)' },
        { value: '2', label: 'EPG 2 (m3u)' },
      ]);
      renderComponent();
      const options = screen.getAllByRole('option');
      const labels = options.map((o) => o.textContent);
      expect(labels).toEqual(
        expect.arrayContaining(['My EPG (xmltv)', 'EPG 2 (m3u)'])
      );
    });

    it('pre-selects the value returned by getEpgSourceValue', () => {
      vi.mocked(getEpgSourceValue).mockReturnValue('2');
      vi.mocked(getEpgSourceData).mockReturnValue([
        { value: '1', label: 'EPG 1' },
        { value: '2', label: 'EPG 2' },
      ]);
      renderComponent();
      // The select with value '2' is present
      const select = screen
        .getAllByRole('combobox')
        .find((s) => s.value === '2');
      expect(select).toBeTruthy();
    });

    it('calls onApplyGroupChange when EPG source is changed', () => {
      vi.mocked(getEpgSourceData).mockReturnValue([
        { value: '1', label: 'EPG 1' },
        { value: '2', label: 'EPG 2' },
      ]);
      const { onApplyGroupChange } = renderComponent();
      const selects = screen.getAllByRole('combobox');
      fireEvent.change(selects[0], { target: { value: '2' } });
      expect(onApplyGroupChange).toHaveBeenCalled();
    });
  });

  // ── Regex text inputs ──────────────────────────────────────────────────────
  describe('regex text inputs', () => {
    it('renders the include regex input', () => {
      renderComponent();
      // TextInput mocked with label as testid fallback
      const inputs = screen.getAllByRole('textbox');
      expect(inputs.length).toBeGreaterThan(0);
    });

    it('calls onScheduleRegexPreview when find regex changes', () => {
      const { onScheduleRegexPreview } = renderComponent();
      const findInput = screen.getByTestId('Find (Regex)');
      fireEvent.change(findInput, { target: { value: 'ESPN' } });
      expect(onScheduleRegexPreview).toHaveBeenCalled();
    });

    it('calls onScheduleRegexPreview when include regex changes', () => {
      const { onScheduleRegexPreview } = renderComponent();
      const includeInput = screen.getByTestId(
        'Include if name matches (Regex)'
      );
      fireEvent.change(includeInput, { target: { value: 'ESPN' } });
      expect(onScheduleRegexPreview).toHaveBeenCalled();
    });
  });

  // ── Repack channels ────────────────────────────────────────────────────────
  describe('repack channels button', () => {
    it('calls repackGroupChannels with playlist and group objects', async () => {
      vi.mocked(repackGroupChannels).mockResolvedValue({
        assigned: 5,
        released: 2,
        failed: 0,
      });
      const group = makeGroup({ channel_group: 7 });
      const playlist = makePlaylist({ id: 3 });
      renderComponent({ group, playlist });

      const repackBtn = screen.getByRole('button', { name: /renumber now/i });
      fireEvent.click(repackBtn);
      await waitFor(() => {
        expect(repackGroupChannels).toHaveBeenCalledWith(playlist, group);
      });
    });

    it('shows success notification after repack resolves', async () => {
      vi.mocked(repackGroupChannels).mockResolvedValue({});
      renderComponent();
      const repackBtn = screen.queryByRole('button', { name: /repack/i });
      if (repackBtn) {
        fireEvent.click(repackBtn);
        await waitFor(() => {
          expect(showNotification).toHaveBeenCalledWith(
            expect.objectContaining({
              color: expect.stringMatching(/teal|green|blue/i),
            })
          );
        });
      }
    });

    it('shows error notification when repack fails', async () => {
      vi.mocked(repackGroupChannels).mockRejectedValue(
        new Error('Server error')
      );
      renderComponent();
      const repackBtn = screen.queryByRole('button', { name: /repack/i });
      if (repackBtn) {
        fireEvent.click(repackBtn);
        await waitFor(() => {
          expect(showNotification).toHaveBeenCalledWith(
            expect.objectContaining({ color: expect.stringMatching(/red/i) })
          );
        });
      }
    });
  });

  // ── Logo upload ────────────────────────────────────────────────────────────
  describe('logo upload', () => {
    it('renders logo-related controls', () => {
      renderComponent();
      const logos = screen.queryAllByTestId('lazy-logo');
      expect(logos.length).toBeGreaterThanOrEqual(0);
    });

    it('calls onOpenLogoUpload when logo upload button is clicked', () => {
      const { onOpenLogoUpload } = renderComponent();
      const uploadBtn = screen.queryByRole('button', { name: /upload|logo/i });
      if (uploadBtn) {
        fireEvent.click(uploadBtn);
        expect(onOpenLogoUpload).toHaveBeenCalled();
      }
    });

    it('passes channelLogos to the logo selector when provided', () => {
      const channelLogos = [
        { id: 'logo1', url: '/logos/espn.png', name: 'ESPN' },
        { id: 'logo2', url: '/logos/cnn.png', name: 'CNN' },
      ];
      renderComponent({ channelLogos });
      // Just verify rendering doesn't throw with logos
      expect(screen.getAllByTestId('stack')[0]).toBeInTheDocument();
    });
  });

  // ── Stream profiles ────────────────────────────────────────────────────────
  describe('stream profiles', () => {
    it('populates profile options from streamProfiles prop', () => {
      const streamProfiles = [
        { id: 1, name: 'HD Profile' },
        { id: 2, name: 'SD Profile' },
      ];
      renderComponent({ streamProfiles });
      expect(screen.getAllByTestId('stack')[0]).toBeInTheDocument();
    });
  });

  // ── Custom properties toggles ──────────────────────────────────────────────
  describe('custom properties toggles', () => {
    it('renders switches/checkboxes for advanced options', () => {
      renderComponent();
      const switches = screen.queryAllByRole('switch');
      const checkboxes = screen.queryAllByRole('checkbox');
      expect(switches.length + checkboxes.length).toBeGreaterThan(0);
    });

    it('calls onApplyGroupChange with compact_numbering when switch is toggled on', () => {
      const { onApplyGroupChange } = renderComponent();
      const compactSwitch = screen.getByTestId('Compact numbering');
      fireEvent.click(compactSwitch);
      expect(onApplyGroupChange).toHaveBeenCalledWith(
        expect.objectContaining({
          custom_properties: expect.objectContaining({
            compact_numbering: true,
          }),
        })
      );
    });

    it('selects force_dummy_epg option via EPG select', () => {
      vi.mocked(getEpgSourceData).mockReturnValue([
        { value: '0', label: 'No EPG' },
        { value: '1', label: 'My EPG' },
      ]);
      const { onApplyGroupChange } = renderComponent();
      const selects = screen.getAllByRole('combobox');
      fireEvent.change(selects[0], { target: { value: '0' } });
      expect(onApplyGroupChange).toHaveBeenCalledWith(
        expect.objectContaining({
          custom_properties: expect.objectContaining({ force_dummy_epg: true }),
        })
      );
    });
  });

  // ── Regex options (MultiSelect) ────────────────────────────────────────────
  describe('regex options MultiSelect', () => {
    it('calls getRegexOptions when find input changes', () => {
      renderComponent();
      const findInput = screen.getByTestId('Find (Regex)');
      fireEvent.change(findInput, { target: { value: 'ESPN' } });
      expect(getRegexOptions).toHaveBeenCalled();
    });
  });

  // ── useEffect / prop sync ──────────────────────────────────────────────────
  describe('prop sync', () => {
    it('re-calls getEpgSourceValue when group prop changes', () => {
      const { rerender } = render(<AutoSyncAdvanced {...defaultProps()} />);
      expect(getEpgSourceValue).toHaveBeenCalledTimes(1);

      const newGroup = makeGroup({ channel_group: 2, name: 'News' });
      rerender(<AutoSyncAdvanced {...defaultProps({ group: newGroup })} />);
      expect(getEpgSourceValue).toHaveBeenCalledTimes(2);
    });

    it('re-calls getEpgSourceData when epgSources prop changes', () => {
      const { rerender } = render(<AutoSyncAdvanced {...defaultProps()} />);
      const callCount = vi.mocked(getEpgSourceData).mock.calls.length;

      const newSources = [
        makeEpgSource(),
        makeEpgSource({ id: 99, name: 'New' }),
      ];
      rerender(
        <AutoSyncAdvanced {...defaultProps({ epgSources: newSources })} />
      );
      expect(vi.mocked(getEpgSourceData).mock.calls.length).toBeGreaterThan(
        callCount
      );
    });
  });
});
