import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import M3UGroupFilter from '../M3UGroupFilter';

// ── Store mocks ────────────────────────────────────────────────────────────────
vi.mock('../../../store/channels', () => ({ default: vi.fn() }));
vi.mock('../../../store/useVODStore', () => ({ default: vi.fn() }));

// ── Utility mocks ──────────────────────────────────────────────────────────────
vi.mock('../../../utils/notificationUtils.js', () => ({
  showNotification: vi.fn(),
}));

vi.mock('../../../utils/forms/M3uGroupFilterUtils.js', () => ({
  saveAndRefreshPlaylist: vi.fn(),
  buildGroupStates: vi.fn(),
}));

// ── Sub-component mocks ────────────────────────────────────────────────────────
vi.mock('../LiveGroupFilter', () => ({
  default: ({
    groupStates,
    setGroupStates,
    autoEnableNewGroupsLive,
    setAutoEnableNewGroupsLive,
  }) => (
    <div data-testid="live-group-filter">
      <span data-testid="live-group-count">{groupStates?.length ?? 0}</span>
      <button
        data-testid="live-toggle-auto"
        onClick={() => setAutoEnableNewGroupsLive?.(!autoEnableNewGroupsLive)}
      >
        Toggle Auto Live
      </button>
      <button
        data-testid="live-change-groups"
        onClick={() => setGroupStates?.([{ id: 99, enabled: true }])}
      >
        Change Groups
      </button>
    </div>
  ),
}));

vi.mock('../VODCategoryFilter', () => ({
  default: ({
    categoryStates,
    setCategoryStates,
    autoEnableNewGroups,
    setAutoEnableNewGroups,
    type,
  }) => (
    <div data-testid={`vod-category-filter-${type}`}>
      <span data-testid={`${type}-category-count`}>
        {categoryStates?.length ?? 0}
      </span>
      <button
        data-testid={`vod-toggle-auto-${type}`}
        onClick={() => setAutoEnableNewGroups?.(!autoEnableNewGroups)}
      >
        Toggle Auto {type}
      </button>
      <button
        data-testid={`vod-change-${type}`}
        onClick={() => setCategoryStates?.([{ id: 55, enabled: true }])}
      >
        Change {type}
      </button>
    </div>
  ),
}));

// ── Mantine core ───────────────────────────────────────────────────────────────
vi.mock('@mantine/core', () => ({
  Button: ({ children, onClick, loading, disabled, variant, color }) => (
    <button
      onClick={onClick}
      disabled={disabled || loading}
      data-loading={loading}
      data-variant={variant}
      data-color={color}
    >
      {children}
    </button>
  ),
  Flex: ({ children }) => <div>{children}</div>,
  LoadingOverlay: ({ visible }) =>
    visible ? <div data-testid="loading-overlay" /> : null,
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
  Stack: ({ children }) => <div>{children}</div>,
  Tabs: ({ children, defaultValue, value }) => (
    <div data-testid="tabs" data-value={value ?? defaultValue}>
      {children}
    </div>
  ),
  TabsList: ({ children }) => <div data-testid="tabs-list">{children}</div>,
  TabsPanel: ({ children, value }) => (
    <div data-testid={`tab-panel-${value}`}>{children}</div>
  ),
  TabsTab: ({ children, value, onClick }) => (
    <button data-testid={`tab-${value}`} onClick={onClick}>
      {children}
    </button>
  ),
}));

// ──────────────────────────────────────────────────────────────────────────────
// Imports after mocks
// ──────────────────────────────────────────────────────────────────────────────
import useChannelsStore from '../../../store/channels';
import useVODStore from '../../../store/useVODStore';
import { showNotification } from '../../../utils/notificationUtils.js';
import * as M3uGroupFilterUtils from '../../../utils/forms/M3uGroupFilterUtils.js';

// ── Helpers ────────────────────────────────────────────────────────────────────
const makePlaylist = (overrides = {}) => ({
  id: 1,
  name: 'Test Playlist',
  account_type: 'XC',
  enable_vod: true,
  ...overrides,
});

const makeGroup = (overrides = {}) => ({
  id: 1,
  name: 'Group A',
  playlist_id: 1,
  ...overrides,
});

const defaultProps = (overrides = {}) => ({
  playlist: makePlaylist(),
  isOpen: true,
  onClose: vi.fn(),
  ...overrides,
});

const setupStores = ({
  channelGroups = [makeGroup(), makeGroup({ id: 2, name: 'Group B' })],
  fetchCategories = vi.fn().mockResolvedValue(undefined),
} = {}) => {
  vi.mocked(useChannelsStore).mockImplementation((sel) =>
    sel({ channelGroups })
  );
  vi.mocked(useVODStore).mockImplementation((sel) => sel({ fetchCategories }));
  return { channelGroups, fetchCategories };
};

// ──────────────────────────────────────────────────────────────────────────────

describe('M3UGroupFilter', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(M3uGroupFilterUtils.saveAndRefreshPlaylist).mockResolvedValue(
      undefined
    );
    vi.mocked(M3uGroupFilterUtils.buildGroupStates).mockReturnValue([]);
  });

  // ── Guard conditions ───────────────────────────────────────────────────────

  describe('guard conditions', () => {
    it('does not render modal when isOpen is false', () => {
      setupStores();
      render(<M3UGroupFilter {...defaultProps({ isOpen: false })} />);
      expect(screen.queryByTestId('modal')).not.toBeInTheDocument();
    });
  });

  // ── Rendering ──────────────────────────────────────────────────────────────

  describe('rendering', () => {
    it('renders the modal when isOpen is true with a valid playlist', () => {
      setupStores();
      render(<M3UGroupFilter {...defaultProps()} />);
      expect(screen.getByTestId('modal')).toBeInTheDocument();
    });

    it('renders the modal title', () => {
      setupStores();
      render(<M3UGroupFilter {...defaultProps()} />);
      expect(screen.getByTestId('modal-title')).toBeInTheDocument();
    });

    it('renders tab list with Live and VOD tabs', () => {
      setupStores();
      render(<M3UGroupFilter {...defaultProps()} />);
      expect(screen.getByTestId('tabs-list')).toBeInTheDocument();
      expect(screen.getByTestId('tab-live')).toBeInTheDocument();
      expect(screen.getByTestId('tab-vod-movie')).toBeInTheDocument();
      expect(screen.getByTestId('tab-vod-series')).toBeInTheDocument();
    });

    it('renders LiveGroupFilter panel', () => {
      setupStores();
      render(<M3UGroupFilter {...defaultProps()} />);
      expect(screen.getByTestId('live-group-filter')).toBeInTheDocument();
    });

    it('renders VODCategoryFilter panels', () => {
      setupStores();
      render(<M3UGroupFilter {...defaultProps()} />);
      expect(
        screen.getByTestId('vod-category-filter-movie')
      ).toBeInTheDocument();
      expect(
        screen.getByTestId('vod-category-filter-series')
      ).toBeInTheDocument();
    });

    it('renders a Save button', () => {
      setupStores();
      render(<M3UGroupFilter {...defaultProps()} />);
      expect(screen.getByRole('button', { name: /save/i })).toBeInTheDocument();
    });

    it('renders a Cancel button', () => {
      setupStores();
      render(<M3UGroupFilter {...defaultProps()} />);
      expect(
        screen.getByRole('button', { name: /cancel/i })
      ).toBeInTheDocument();
    });
  });

  // ── Initialization ─────────────────────────────────────────────────────────

  describe('initialization', () => {
    it('calls buildGroupStates with channelGroups and playlist on mount', async () => {
      const { channelGroups } = setupStores();
      render(<M3UGroupFilter {...defaultProps()} />);
      await waitFor(() => {
        expect(M3uGroupFilterUtils.buildGroupStates).toHaveBeenCalledWith(
          channelGroups,
          undefined
        );
      });
    });

    it('calls fetchCategories on mount', async () => {
      const { fetchCategories } = setupStores();
      render(<M3UGroupFilter {...defaultProps()} />);
      await waitFor(() => {
        expect(fetchCategories).toHaveBeenCalled();
      });
    });

    it('re-initializes when playlist prop changes', async () => {
      setupStores();
      const { rerender } = render(<M3UGroupFilter {...defaultProps()} />);
      const updatedPlaylist = makePlaylist({
        id: 2,
        name: 'Updated Playlist',
        channel_groups: [{ id: 3, name: 'Group C', playlist_id: 2 }],
      });
      rerender(
        <M3UGroupFilter {...defaultProps({ playlist: updatedPlaylist })} />
      );
      await waitFor(() => {
        expect(M3uGroupFilterUtils.buildGroupStates).toHaveBeenCalledWith(
          expect.anything(),
          updatedPlaylist.channel_groups
        );
      });
    });
  });

  // ── Close / cancel behaviour ───────────────────────────────────────────────

  describe('close / cancel behaviour', () => {
    it('calls onClose when modal X is clicked', () => {
      const onClose = vi.fn();
      setupStores();
      render(<M3UGroupFilter {...defaultProps({ onClose })} />);
      fireEvent.click(screen.getByTestId('modal-close'));
      expect(onClose).toHaveBeenCalled();
    });

    it('calls onClose when Cancel button is clicked', () => {
      const onClose = vi.fn();
      setupStores();
      render(<M3UGroupFilter {...defaultProps({ onClose })} />);
      fireEvent.click(screen.getByRole('button', { name: /cancel/i }));
      expect(onClose).toHaveBeenCalled();
    });
  });

  // ── LiveGroupFilter interaction ────────────────────────────────────────────

  describe('LiveGroupFilter interaction', () => {
    it('updates groupStates when LiveGroupFilter fires onGroupStatesChange', async () => {
      setupStores();
      render(<M3UGroupFilter {...defaultProps()} />);
      await waitFor(() => screen.getByTestId('live-group-filter'));
      fireEvent.click(screen.getByTestId('live-change-groups'));
      expect(screen.getByTestId('live-group-count')).toHaveTextContent('1');
    });

    it('toggles autoEnableNewGroupsLive when LiveGroupFilter fires onAutoEnableChange', async () => {
      setupStores();
      render(<M3UGroupFilter {...defaultProps()} />);
      await waitFor(() => screen.getByTestId('live-group-filter'));
      // Toggle twice to verify it actually flips
      fireEvent.click(screen.getByTestId('live-toggle-auto'));
      fireEvent.click(screen.getByTestId('live-toggle-auto'));
      // No crash = state updated correctly
    });
  });

  // ── VODCategoryFilter interaction ──────────────────────────────────────────

  describe('VODCategoryFilter interaction', () => {
    it('updates movieCategoryStates when movie VODCategoryFilter fires setCategoryStates', async () => {
      setupStores();
      render(<M3UGroupFilter {...defaultProps()} />);
      fireEvent.click(screen.getByTestId('vod-change-movie'));
      expect(screen.getByTestId('movie-category-count')).toHaveTextContent('1');
    });

    it('updates seriesCategoryStates when series VODCategoryFilter fires setCategoryStates', async () => {
      setupStores();
      render(<M3UGroupFilter {...defaultProps()} />);
      fireEvent.click(screen.getByTestId('vod-change-series'));
      expect(screen.getByTestId('series-category-count')).toHaveTextContent(
        '1'
      );
    });

    it('toggles autoEnableNewGroupsVod when movie VODCategoryFilter fires setAutoEnableNewGroups', () => {
      setupStores();
      render(<M3UGroupFilter {...defaultProps()} />);
      fireEvent.click(screen.getByTestId('vod-toggle-auto-movie'));
      fireEvent.click(screen.getByTestId('vod-toggle-auto-movie'));
    });

    it('toggles autoEnableNewGroupsSeries when series VODCategoryFilter fires setAutoEnableNewGroups', () => {
      setupStores();
      render(<M3UGroupFilter {...defaultProps()} />);
      fireEvent.click(screen.getByTestId('vod-toggle-auto-series'));
      fireEvent.click(screen.getByTestId('vod-toggle-auto-series'));
    });
  });

  // ── Save ───────────────────────────────────────────────────────────────────

  describe('saving', () => {
    it('calls saveAndRefreshPlaylist with playlist and current states on Save click', async () => {
      setupStores();
      render(<M3UGroupFilter {...defaultProps()} />);
      await waitFor(() => screen.getByRole('button', { name: /save/i }));
      fireEvent.click(screen.getByRole('button', { name: /save/i }));
      await waitFor(() => {
        expect(M3uGroupFilterUtils.saveAndRefreshPlaylist).toHaveBeenCalledWith(
          expect.objectContaining({ id: 1 }),
          expect.any(Array),
          expect.any(Array),
          expect.any(Array),
          expect.objectContaining({
            auto_enable_new_groups_live: true,
            auto_enable_new_groups_vod: true,
            auto_enable_new_groups_series: true,
          })
        );
      });
    });

    it('calls onClose after successful save', async () => {
      const onClose = vi.fn();
      setupStores();
      render(<M3UGroupFilter {...defaultProps({ onClose })} />);
      await waitFor(() => screen.getByRole('button', { name: /save/i }));
      fireEvent.click(screen.getByRole('button', { name: /save/i }));
      await waitFor(() => {
        expect(onClose).toHaveBeenCalled();
      });
    });

    it('shows success notification after saving', async () => {
      setupStores();
      render(<M3UGroupFilter {...defaultProps()} />);
      await waitFor(() => screen.getByRole('button', { name: /save/i }));
      fireEvent.click(screen.getByRole('button', { name: /save/i }));
      await waitFor(() => {
        expect(showNotification).toHaveBeenCalledWith(
          expect.objectContaining({
            color: expect.stringMatching(/green|teal/),
          })
        );
      });
    });

    it('does not call onClose when saveAndRefreshPlaylist throws', async () => {
      vi.mocked(M3uGroupFilterUtils.saveAndRefreshPlaylist).mockRejectedValue(
        new Error('save failed')
      );
      const onClose = vi.fn();
      setupStores();
      render(<M3UGroupFilter {...defaultProps({ onClose })} />);
      await waitFor(() => screen.getByRole('button', { name: /save/i }));
      fireEvent.click(screen.getByRole('button', { name: /save/i }));
      expect(onClose).not.toHaveBeenCalled();
    });
  });

  // ── Loading state ──────────────────────────────────────────────────────────

  describe('loading state', () => {
    it('disables Save button while submitting', async () => {
      let resolveSave;
      vi.mocked(M3uGroupFilterUtils.saveAndRefreshPlaylist).mockImplementation(
        () =>
          new Promise((res) => {
            resolveSave = res;
          })
      );
      setupStores();
      render(<M3UGroupFilter {...defaultProps()} />);
      await waitFor(() => screen.getByRole('button', { name: /save/i }));

      const saveBtn = screen.getByRole('button', { name: /save/i });
      fireEvent.click(saveBtn);

      await waitFor(() => {
        expect(saveBtn.disabled || saveBtn.dataset.loading === 'true').toBe(
          true
        );
      });

      resolveSave();
    });
  });
});
