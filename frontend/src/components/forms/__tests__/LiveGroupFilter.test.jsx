import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

// Targeted Vitest for the orphan-cleanup SegmentedControl that lives at
// the top of the M3U account's group-settings page. Covers default-mode
// resolution, click-to-PATCH, and optimistic-update / error-revert
// behavior. Other parts of LiveGroupFilter (per-group inline config,
// gear modal, regex preview, overlap warning) are not unit-tested here
// because they depend on external APIs and live data; they are exercised
// via the in-repo manual UI walkthrough.

// ── Store mocks ────────────────────────────────────────────────────────────────
vi.mock('../../../store/channels', () => ({ default: vi.fn() }));
vi.mock('../../../store/streamProfiles', () => ({ default: vi.fn() }));

// ── Hook mocks ─────────────────────────────────────────────────────────────────
vi.mock('../../../hooks/useSmartLogos', () => ({
  useChannelLogoSelection: vi.fn(() => ({
    logos: {},
    ensureLogosLoaded: vi.fn(),
    isLoading: false,
  })),
}));

// ── Module mocks ───────────────────────────────────────────────────────────────
vi.mock('@mantine/notifications', () => ({
  notifications: { show: vi.fn() },
}));

vi.mock('../../../api', () => ({
  default: {
    updatePlaylist: vi.fn(() => Promise.resolve({})),
    getEPGs: vi.fn(() => Promise.resolve([])),
    getChannelsInRange: vi.fn(() => Promise.resolve({ data: [] })),
    getStreamsRegexPreview: vi.fn(() => Promise.resolve({ data: {} })),
    repackGroupChannels: vi.fn(() => Promise.resolve({})),
  },
}));

vi.mock('../../../utils/forms/GroupSyncUtils', () => ({
  getGroupReservation: vi.fn(() => null),
}));

// ── Child component mocks ──────────────────────────────────────────────────────
vi.mock('../GroupConfigureModal', () => ({
  default: ({ children }) => <div data-testid="group-config-modal">{children}</div>,
}));

vi.mock('../Logo', () => ({ default: () => null }));
vi.mock('../../LazyLogo', () => ({ default: () => null }));
vi.mock('../../../images/logo.png', () => ({ default: 'default-logo.png' }));

vi.mock('react-window', () => ({
  FixedSizeList: ({ children, itemCount }) => (
    <div data-testid="fixed-size-list">
      {Array.from({ length: itemCount }, (_, index) =>
        children({ index, style: {} })
      )}
    </div>
  ),
}));

vi.mock('lucide-react', () => ({
  Info: () => <svg data-testid="icon-info" />,
  CircleCheck: () => <svg data-testid="icon-check" />,
  CircleX: () => <svg data-testid="icon-x" />,
  Settings: () => <svg data-testid="icon-cog" />,
  AlertTriangle: () => <svg data-testid="icon-warn" />,
  RefreshCw: () => <svg data-testid="icon-refresh" />,
}));

// ── @mantine/core minimal mocks ────────────────────────────────────────────────
vi.mock('@mantine/core', () => ({
  TextInput: ({ value, onChange, placeholder }) => (
    <input value={value ?? ''} onChange={onChange} placeholder={placeholder} />
  ),
  Button: ({ children, onClick }) => <button onClick={onClick}>{children}</button>,
  Checkbox: ({ label, checked, onChange }) => (
    <label>
      <input type="checkbox" checked={!!checked} onChange={onChange} />
      {label}
    </label>
  ),
  Flex: ({ children }) => <div>{children}</div>,
  Select: ({ value, onChange, data }) => (
    <select value={value ?? ''} onChange={(e) => onChange?.(e.target.value)}>
      {(data ?? []).map((opt) => {
        const v = typeof opt === 'string' ? opt : opt.value;
        const l = typeof opt === 'string' ? opt : opt.label;
        return (
          <option key={v} value={v}>
            {l}
          </option>
        );
      })}
    </select>
  ),
  Stack: ({ children }) => <div>{children}</div>,
  Group: ({ children }) => <div>{children}</div>,
  SimpleGrid: ({ children }) => <div>{children}</div>,
  Text: ({ children }) => <span>{children}</span>,
  NumberInput: ({ value, onChange }) => (
    <input
      type="number"
      value={value ?? ''}
      onChange={(e) => onChange?.(Number(e.target.value))}
    />
  ),
  Divider: ({ label }) => <hr aria-label={label} />,
  Alert: ({ children }) => <div role="alert">{children}</div>,
  Box: ({ children }) => <div>{children}</div>,
  MultiSelect: ({ value, onChange }) => (
    <select multiple value={value ?? []} onChange={onChange}>
      {(value ?? []).map((v) => (
        <option key={v} value={v}>
          {v}
        </option>
      ))}
    </select>
  ),
  Tooltip: ({ children }) => <>{children}</>,
  Popover: ({ children }) => <div>{children}</div>,
  ScrollArea: ({ children }) => <div>{children}</div>,
  Center: ({ children }) => <div>{children}</div>,
  SegmentedControl: ({ value, onChange, data }) => (
    <div data-testid="segmented-control" data-value={value}>
      {data.map((opt) => (
        <button
          key={opt.value}
          data-testid={`segmented-${opt.value}`}
          data-active={value === opt.value}
          onClick={() => onChange?.(opt.value)}
        >
          {opt.label}
        </button>
      ))}
    </div>
  ),
  ActionIcon: ({ children, onClick }) => <button onClick={onClick}>{children}</button>,
  Switch: ({ label, checked, onChange }) => (
    <label>
      <input type="checkbox" checked={!!checked} onChange={onChange} />
      {label}
    </label>
  ),
}));

// ── Imports after mocks ────────────────────────────────────────────────────────
import LiveGroupFilter from '../LiveGroupFilter';
import API from '../../../api';
import { notifications } from '@mantine/notifications';
import useChannelsStore from '../../../store/channels';
import useStreamProfilesStore from '../../../store/streamProfiles';

// ──────────────────────────────────────────────────────────────────────────────

const makePlaylist = (overrides = {}) => ({
  id: 7,
  channel_groups: [],
  custom_properties: null,
  ...overrides,
});

const setupStores = () => {
  vi.mocked(useChannelsStore).mockImplementation((sel) =>
    sel({ channelGroups: {}, profiles: [] })
  );
  vi.mocked(useStreamProfilesStore).mockImplementation((sel) =>
    sel({ profiles: [], fetchProfiles: vi.fn() })
  );
};

const renderFilter = (playlistOverrides = {}) =>
  render(
    <LiveGroupFilter
      playlist={makePlaylist(playlistOverrides)}
      groupStates={[]}
      setGroupStates={vi.fn()}
      autoEnableNewGroupsLive={false}
      setAutoEnableNewGroupsLive={vi.fn()}
    />
  );

// The orphan-cleanup SegmentedControl shares its mocked testid with the
// status-filter SegmentedControl that lives elsewhere in the form, so
// disambiguate by walking from a uniquely-testided child button up to
// its parent SegmentedControl element.
const findCleanupControl = () =>
  screen.getByTestId('segmented-always').closest('[data-testid="segmented-control"]');

describe('LiveGroupFilter orphan-cleanup SegmentedControl', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    setupStores();
  });

  it('defaults to "always" when custom_properties is null', () => {
    renderFilter({ custom_properties: null });
    expect(findCleanupControl()).toHaveAttribute('data-value', 'always');
  });

  it('defaults to "always" when the orphan_channel_cleanup key is absent', () => {
    renderFilter({ custom_properties: { compact_numbering: true } });
    expect(findCleanupControl()).toHaveAttribute('data-value', 'always');
  });

  it('reads the persisted mode from custom_properties on mount', () => {
    renderFilter({
      custom_properties: { orphan_channel_cleanup: 'preserve_customized' },
    });
    expect(findCleanupControl()).toHaveAttribute(
      'data-value',
      'preserve_customized'
    );
  });

  it('PATCHes the playlist with merged custom_properties on click and updates the displayed value', async () => {
    renderFilter({
      custom_properties: { compact_numbering: true },
    });
    fireEvent.click(screen.getByTestId('segmented-never'));

    await waitFor(() => {
      expect(API.updatePlaylist).toHaveBeenCalledWith({
        id: 7,
        custom_properties: {
          compact_numbering: true,
          orphan_channel_cleanup: 'never',
        },
      });
    });
    expect(findCleanupControl()).toHaveAttribute('data-value', 'never');
  });

  it('reverts to the previous mode and surfaces an error toast when the PATCH fails', async () => {
    vi.mocked(API.updatePlaylist).mockRejectedValueOnce(
      new Error('Server error')
    );
    renderFilter({
      custom_properties: { orphan_channel_cleanup: 'always' },
    });
    fireEvent.click(screen.getByTestId('segmented-never'));

    await waitFor(() => {
      expect(notifications.show).toHaveBeenCalledWith(
        expect.objectContaining({ color: 'red' })
      );
    });
    expect(findCleanupControl()).toHaveAttribute('data-value', 'always');
  });
});
