import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { createElement } from 'react';
import M3UGroupFilter from '../M3UGroupFilter';
import editorClasses from '../AccountEditor.module.css';

// ── Store mocks ────────────────────────────────────────────────────────────────
vi.mock('../../../store/channels', () => ({ default: vi.fn() }));
vi.mock('../../../store/useVODStore', () => ({ default: vi.fn() }));
vi.mock('../../../hooks/useCategoryPreviewAvailability.jsx', () => ({
  default: () => ({
    availability: { live: new Set(), movie: new Set(), series: new Set() },
    hint: 'No imported entries.',
  }),
}));

// ── Utility mocks ──────────────────────────────────────────────────────────────
vi.mock('../../../utils/notificationUtils.js', () => ({
  showNotification: vi.fn(),
}));

vi.mock('../../../utils/forms/M3uGroupFilterUtils.js', () => ({
  saveAndRefreshPlaylist: vi.fn(),
  savePlaylistGroupSettings: vi.fn(),
  buildGroupStates: vi.fn(),
}));

// ── Sub-component mocks ────────────────────────────────────────────────────────
vi.mock('../LiveGroupFilter', () => ({
  default: ({
    groupStates,
    setGroupStates,
    onOpenRules,
    previewAvailableIds,
  }) => (
    <div
      data-testid="live-group-filter"
      data-preview-source={
        previewAvailableIds === undefined ? 'provider' : 'imported'
      }
    >
      <span data-testid="live-group-count">{groupStates?.length ?? 0}</span>
      <button data-testid="live-open-rules" onClick={onOpenRules}>
        Import rules
      </button>
      <button
        data-testid="live-annotate-groups"
        onClick={() =>
          setGroupStates?.((rows) =>
            rows.map((row) => ({
              ...row,
              original_enabled: row.enabled,
              name: 'Updated display name',
            }))
          )
        }
      >
        Annotate Groups
      </button>
      <button
        data-testid="live-disable-groups"
        onClick={() =>
          setGroupStates?.((rows) =>
            rows.map((row) => ({ ...row, enabled: false }))
          )
        }
      >
        Disable all live categories
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

vi.mock('../M3URulesModal.jsx', () => ({
  default: ({
    opened,
    onApplied,
    onClose,
    scope,
    title,
    accountType,
    categoryCount,
  }) =>
    opened ? (
      <button
        data-rule-title={title}
        data-account-type={accountType}
        data-category-count={categoryCount}
        onClick={() => {
          onApplied(
            scope === 'live'
              ? { scope: 'live', target_ids: [1], enabled: true }
              : {
                  scope,
                  target_ids: [55],
                  enabled: null,
                  category_updates: [
                    {
                      target_id: 55,
                      enabled: null,
                      metadata_defaults: {
                        audio_languages: ['ger'],
                        resolution: '1080p',
                      },
                    },
                  ],
                }
          );
          onClose();
        }}
      >
        Apply saved rule
      </button>
    ) : null,
}));

vi.mock('../VODCategoryFilter', () => ({
  default: ({
    categoryStates,
    setCategoryStates,
    type,
    onOpenRules,
    previewAvailableIds,
  }) => (
    <div
      data-testid={`vod-category-filter-${type}`}
      data-preview-source={
        previewAvailableIds === undefined ? 'provider' : 'imported'
      }
    >
      <span data-testid={`${type}-category-count`}>
        {categoryStates?.length ?? 0}
      </span>
      <span data-testid={`${type}-category-state`}>
        {JSON.stringify(categoryStates)}
      </span>
      <button onClick={onOpenRules}>Open {type} rules</button>
      <button
        data-testid={`vod-disable-${type}`}
        onClick={() =>
          setCategoryStates?.((rows) =>
            rows.map((row) => ({ ...row, enabled: false }))
          )
        }
      >
        Disable all {type} categories
      </button>
      <button
        data-testid={`vod-initialize-${type}`}
        onClick={() =>
          setCategoryStates?.([
            { id: 55, enabled: true, original_enabled: true },
          ])
        }
      >
        Initialize existing {type}
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

vi.mock('../../ConfirmationDialog.jsx', () => ({
  default: ({
    opened,
    title,
    message,
    confirmLabel = 'Discard',
    cancelLabel = 'Keep editing',
    onConfirm,
    onClose,
  }) =>
    opened ? (
      <div role="dialog" aria-label={title}>
        <p>{message}</p>
        <button onClick={onConfirm}>{confirmLabel}</button>
        <button onClick={onClose}>{cancelLabel}</button>
      </div>
    ) : null,
}));

// ── Mantine core ───────────────────────────────────────────────────────────────
vi.mock('@mantine/core', () => ({
  useModalStackContext: () => null,
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
  Flex: ({ children, component = 'div', className, 'aria-label': ariaLabel }) =>
    createElement(component, { className, 'aria-label': ariaLabel }, children),
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
    vi.mocked(M3uGroupFilterUtils.savePlaylistGroupSettings).mockResolvedValue(
      undefined
    );
    vi.mocked(M3uGroupFilterUtils.saveAndRefreshPlaylist).mockResolvedValue(
      undefined
    );
    vi.mocked(M3uGroupFilterUtils.buildGroupStates).mockReturnValue([]);
  });

  it('reports the full category count, including disabled and ignored categories, without saving', () => {
    setupStores();
    vi.mocked(M3uGroupFilterUtils.buildGroupStates).mockReturnValue([
      { channel_group: 1, enabled: true },
      { channel_group: 2, enabled: false },
      { channel_group: 3, enabled: false, ignored: true },
    ]);
    render(<M3UGroupFilter {...defaultProps()} />);
    fireEvent.click(screen.getByTestId('live-open-rules'));
    expect(
      screen.getByRole('button', { name: 'Apply saved rule' })
    ).toHaveAttribute('data-category-count', '3');
    expect(
      M3uGroupFilterUtils.savePlaylistGroupSettings
    ).not.toHaveBeenCalled();
  });

  it.each([false, true])(
    'allows targeted XC previews before imports, including initial setup=%s',
    (isInitialSetup) => {
      setupStores();
      render(<M3UGroupFilter {...defaultProps({ isInitialSetup })} />);
      expect(screen.getByTestId('live-group-filter')).toHaveAttribute(
        'data-preview-source',
        'provider'
      );
      for (const scope of ['movie', 'series'])
        expect(
          screen.getByTestId(`vod-category-filter-${scope}`)
        ).toHaveAttribute('data-preview-source', 'provider');
      expect(
        M3uGroupFilterUtils.savePlaylistGroupSettings
      ).not.toHaveBeenCalled();
    }
  );

  it('keeps standard playlists limited to already imported preview data', () => {
    setupStores();
    render(
      <M3UGroupFilter
        {...defaultProps({
          playlist: makePlaylist({ account_type: 'STD', enable_vod: false }),
        })}
      />
    );
    expect(screen.getByTestId('live-group-filter')).toHaveAttribute(
      'data-preview-source',
      'imported'
    );
  });

  it.each(['URL', 'File'])(
    'labels %s selection and import rules as Streams without changing their scope',
    (source) => {
      setupStores();
      render(
        <M3UGroupFilter
          {...defaultProps({
            playlist: makePlaylist({
              account_type: 'STD',
              enable_vod: false,
              server_url:
                source === 'URL' ? 'https://example.invalid/playlist.m3u' : '',
              file_path: source === 'File' ? '/data/playlist.m3u' : '',
            }),
          })}
        />
      );
      expect(screen.getByTestId('tab-live')).toHaveTextContent('Streams');
      expect(screen.queryByText('Live TV')).not.toBeInTheDocument();
      fireEvent.click(screen.getByTestId('live-open-rules'));
      const rule = screen.getByRole('button', { name: 'Apply saved rule' });
      expect(rule).toHaveAttribute('data-rule-title', 'Streams import rules');
      expect(rule).toHaveAttribute('data-account-type', 'STD');
      expect(
        M3uGroupFilterUtils.savePlaylistGroupSettings
      ).not.toHaveBeenCalled();
      expect(M3uGroupFilterUtils.saveAndRefreshPlaylist).not.toHaveBeenCalled();
    }
  );

  it.each(['movie', 'series'])(
    'merges applied %s metadata without clearing selection or leaving a dirty baseline',
    (type) => {
      setupStores();
      const onClose = vi.fn();
      render(<M3UGroupFilter {...defaultProps({ onClose })} />);
      fireEvent.click(screen.getByTestId(`vod-initialize-${type}`));
      fireEvent.click(
        screen.getByRole('button', { name: `Open ${type} rules` })
      );
      fireEvent.click(screen.getByRole('button', { name: 'Apply saved rule' }));
      const [category] = JSON.parse(
        screen.getByTestId(`${type}-category-state`).textContent
      );
      expect(category.enabled).toBe(true);
      expect(category.original_enabled).toBe(true);
      expect(category.custom_properties).toEqual({
        audio_languages: ['ger'],
        resolution: '1080p',
      });
      expect(category.original_custom_properties).toEqual(
        category.custom_properties
      );
      fireEvent.click(screen.getByTestId('modal-close'));
      expect(onClose).toHaveBeenCalledOnce();
    }
  );

  // ── Guard conditions ───────────────────────────────────────────────────────

  it('keeps category actions without a separate divider', () => {
    setupStores();
    render(<M3UGroupFilter {...defaultProps()} />);
    expect(
      screen.getByRole('contentinfo', { name: 'Category actions' })
    ).toHaveClass(editorClasses.plainFooter);
  });

  it('saves wizard selections before completing setup without handoff toasts', async () => {
    setupStores();
    M3uGroupFilterUtils.buildGroupStates.mockReturnValueOnce([
      { channel_group: 1, enabled: true },
    ]);
    const onSetupSave = vi.fn().mockResolvedValue(true);
    render(
      <M3UGroupFilter
        {...defaultProps({ isInitialSetup: true, onSetupSave })}
      />
    );
    fireEvent.click(screen.getByRole('button', { name: 'Save selection' }));
    await waitFor(() => expect(onSetupSave).toHaveBeenCalledOnce());
    expect(
      M3uGroupFilterUtils.savePlaylistGroupSettings
    ).toHaveBeenCalledOnce();
    expect(M3uGroupFilterUtils.saveAndRefreshPlaylist).not.toHaveBeenCalled();
    expect(showNotification).not.toHaveBeenCalled();
  });

  it('confirms discarding category changes while keeping setup resumable', () => {
    setupStores();
    const onClose = vi.fn();
    render(
      <M3UGroupFilter
        {...defaultProps({
          isInitialSetup: true,
          onSetupSave: vi.fn(),
          onClose,
        })}
      />
    );
    fireEvent.click(screen.getByTestId('live-change-groups'));
    fireEvent.click(screen.getByTestId('modal-close'));
    expect(onClose).not.toHaveBeenCalled();
    expect(
      screen.getByRole('dialog', { name: 'Discard category changes?' })
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Discard' }));
    expect(onClose).toHaveBeenCalledOnce();
  });

  it('does not treat initialized display metadata as unsaved category changes', () => {
    setupStores();
    M3uGroupFilterUtils.buildGroupStates.mockReturnValueOnce([
      { channel_group: 1, enabled: false, custom_properties: {} },
    ]);
    const onClose = vi.fn();
    render(
      <M3UGroupFilter
        {...defaultProps({
          isInitialSetup: true,
          onSetupSave: vi.fn(),
          onClose,
        })}
      />
    );
    fireEvent.click(screen.getByTestId('live-annotate-groups'));
    fireEvent.click(screen.getByTestId('modal-close'));
    expect(onClose).toHaveBeenCalledOnce();
    expect(
      screen.queryByRole('dialog', { name: 'Discard category changes?' })
    ).not.toBeInTheDocument();
  });

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
      expect(screen.getByTestId('modal-title')).toHaveTextContent('Categories');
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

    it('does not duplicate the modal close action in its footer', () => {
      setupStores();
      render(<M3UGroupFilter {...defaultProps()} />);
      expect(
        screen.queryByRole('button', { name: /close/i })
      ).not.toBeInTheDocument();
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
    it('protects unsaved selections during ordinary editing', () => {
      setupStores();
      const onClose = vi.fn();
      render(<M3UGroupFilter {...defaultProps({ onClose })} />);
      fireEvent.click(screen.getByTestId('live-change-groups'));
      fireEvent.click(screen.getByTestId('modal-close'));
      expect(onClose).not.toHaveBeenCalled();
      expect(
        screen.getByRole('dialog', { name: 'Discard category changes?' })
      ).toBeInTheDocument();
      fireEvent.click(screen.getByRole('button', { name: 'Keep editing' }));
      expect(screen.getByTestId('live-group-count')).toHaveTextContent('1');
      expect(onClose).not.toHaveBeenCalled();
      fireEvent.click(screen.getByTestId('modal-close'));
      fireEvent.click(screen.getByRole('button', { name: 'Discard' }));
      expect(onClose).toHaveBeenCalledOnce();
      expect(
        M3uGroupFilterUtils.savePlaylistGroupSettings
      ).not.toHaveBeenCalled();
      expect(M3uGroupFilterUtils.saveAndRefreshPlaylist).not.toHaveBeenCalled();
    });

    it('does not warn for changes already persisted by applying a saved rule', () => {
      setupStores();
      M3uGroupFilterUtils.buildGroupStates.mockReturnValueOnce([
        { channel_group: 1, enabled: false, custom_properties: {} },
      ]);
      const onClose = vi.fn();
      render(<M3UGroupFilter {...defaultProps({ onClose })} />);
      fireEvent.click(screen.getByTestId('live-open-rules'));
      fireEvent.click(screen.getByRole('button', { name: 'Apply saved rule' }));
      fireEvent.click(screen.getByTestId('modal-close'));
      expect(onClose).toHaveBeenCalledOnce();
      expect(
        screen.queryByRole('dialog', { name: 'Discard category changes?' })
      ).not.toBeInTheDocument();
    });

    it('calls onClose when modal X is clicked', () => {
      const onClose = vi.fn();
      setupStores();
      render(<M3UGroupFilter {...defaultProps({ onClose })} />);
      fireEvent.click(screen.getByTestId('modal-close'));
      expect(onClose).toHaveBeenCalled();
    });

    it('closing does not save or refresh', () => {
      const onClose = vi.fn();
      setupStores();
      render(<M3UGroupFilter {...defaultProps({ onClose })} />);
      fireEvent.click(screen.getByTestId('modal-close'));
      expect(onClose).toHaveBeenCalled();
      expect(
        M3uGroupFilterUtils.savePlaylistGroupSettings
      ).not.toHaveBeenCalled();
      expect(M3uGroupFilterUtils.saveAndRefreshPlaylist).not.toHaveBeenCalled();
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
  });

  // ── Save ───────────────────────────────────────────────────────────────────

  describe('saving', () => {
    beforeEach(() => {
      M3uGroupFilterUtils.buildGroupStates.mockReturnValue([
        { channel_group: 1, enabled: true },
      ]);
    });

    it('allows saving with all categories deliberately disabled after confirmation', async () => {
      setupStores();
      M3uGroupFilterUtils.buildGroupStates.mockReturnValueOnce([
        { channel_group: 1, enabled: false, custom_properties: {} },
      ]);
      render(<M3UGroupFilter {...defaultProps()} />);
      fireEvent.click(
        screen.getByRole('button', { name: 'Save', exact: true })
      );
      expect(
        M3uGroupFilterUtils.savePlaylistGroupSettings
      ).not.toHaveBeenCalled();
      fireEvent.click(screen.getByRole('button', { name: 'Save anyway' }));
      await waitFor(() =>
        expect(
          M3uGroupFilterUtils.savePlaylistGroupSettings
        ).toHaveBeenCalledWith(
          expect.objectContaining({ id: 1 }),
          [expect.objectContaining({ enabled: false })],
          [],
          [],
          {},
          false
        )
      );
    });

    it.each([
      { account_type: 'XC', enable_vod: false },
      { account_type: 'STD', enable_vod: true },
    ])('hides and does not load unavailable VOD selections (%j)', (account) => {
      const { fetchCategories } = setupStores();
      render(
        <M3UGroupFilter
          {...defaultProps({ playlist: makePlaylist(account) })}
        />
      );
      expect(screen.getByTestId('tab-live')).toBeInTheDocument();
      expect(screen.queryByTestId('tab-vod-movie')).not.toBeInTheDocument();
      expect(screen.queryByTestId('tab-vod-series')).not.toBeInTheDocument();
      expect(
        screen.queryByTestId('vod-category-filter-movie')
      ).not.toBeInTheDocument();
      expect(
        screen.queryByTestId('vod-category-filter-series')
      ).not.toBeInTheDocument();
      expect(fetchCategories).not.toHaveBeenCalled();
    });

    it('does not submit hidden VOD selections after VOD is disabled', async () => {
      setupStores();
      const props = defaultProps();
      const { rerender } = render(<M3UGroupFilter {...props} />);
      fireEvent.click(screen.getByTestId('vod-change-movie'));
      fireEvent.click(screen.getByTestId('vod-change-series'));
      rerender(
        <M3UGroupFilter
          {...props}
          playlist={makePlaylist({ enable_vod: false })}
        />
      );
      fireEvent.click(
        screen.getByRole('button', { name: 'Save', exact: true })
      );
      await waitFor(() =>
        expect(
          M3uGroupFilterUtils.savePlaylistGroupSettings
        ).toHaveBeenCalledWith(
          expect.objectContaining({ enable_vod: false }),
          [expect.objectContaining({ enabled: true })],
          [],
          [],
          {},
          false
        )
      );
    });

    it('saves current states without refreshing on an ordinary Save click', async () => {
      setupStores();
      render(<M3UGroupFilter {...defaultProps()} />);
      await waitFor(() => screen.getByRole('button', { name: /save/i }));
      fireEvent.click(screen.getByRole('button', { name: /save/i }));
      await waitFor(() => {
        expect(
          M3uGroupFilterUtils.savePlaylistGroupSettings
        ).toHaveBeenCalledWith(
          expect.objectContaining({ id: 1 }),
          expect.any(Array),
          expect.any(Array),
          expect.any(Array),
          {},
          false
        );
      });
    });

    it('marks only the initial group save for a combined first refresh', async () => {
      setupStores();
      M3uGroupFilterUtils.buildGroupStates.mockReturnValueOnce([
        { channel_group: 1, enabled: true },
      ]);
      render(<M3UGroupFilter {...defaultProps({ isInitialSetup: true })} />);
      fireEvent.click(screen.getByRole('button', { name: /save/i }));

      await waitFor(() => {
        expect(M3uGroupFilterUtils.saveAndRefreshPlaylist).toHaveBeenCalledWith(
          expect.objectContaining({ id: 1 }),
          expect.any(Array),
          expect.any(Array),
          expect.any(Array),
          expect.any(Object),
          true
        );
      });
    });

    it('keeps the dialog open after an ordinary save', async () => {
      const onClose = vi.fn();
      setupStores();
      render(<M3UGroupFilter {...defaultProps({ onClose })} />);
      await waitFor(() => screen.getByRole('button', { name: /save/i }));
      fireEvent.click(screen.getByRole('button', { name: /save/i }));
      await waitFor(() => {
        expect(
          M3uGroupFilterUtils.savePlaylistGroupSettings
        ).toHaveBeenCalled();
        expect(onClose).not.toHaveBeenCalled();
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

    it('explains that VOD follows the initial Live TV refresh', async () => {
      setupStores();
      M3uGroupFilterUtils.buildGroupStates.mockReturnValueOnce([
        { channel_group: 1, enabled: true },
      ]);
      render(<M3UGroupFilter {...defaultProps({ isInitialSetup: true })} />);
      fireEvent.click(screen.getByRole('button', { name: /save/i }));

      await waitFor(() => {
        expect(showNotification).toHaveBeenCalledWith(
          expect.objectContaining({
            title: 'Live TV Refresh Started',
            message: expect.stringContaining(
              'VOD will be queued in the background after Live TV completes'
            ),
          })
        );
      });
    });

    it('does not promise a VOD refresh when the account has VOD disabled', async () => {
      setupStores();
      M3uGroupFilterUtils.buildGroupStates.mockReturnValueOnce([
        { channel_group: 1, enabled: true },
      ]);
      render(
        <M3UGroupFilter
          {...defaultProps({
            playlist: makePlaylist({ enable_vod: false }),
            isInitialSetup: true,
          })}
        />
      );
      fireEvent.click(screen.getByRole('button', { name: /save/i }));

      await waitFor(() => {
        expect(showNotification).toHaveBeenCalledWith(
          expect.objectContaining({
            title: 'Live TV Refresh Started',
            message: expect.not.stringContaining('VOD'),
          })
        );
      });
    });

    it('does not call onClose when saveAndRefreshPlaylist throws', async () => {
      vi.mocked(
        M3uGroupFilterUtils.savePlaylistGroupSettings
      ).mockRejectedValue(new Error('save failed'));
      const onClose = vi.fn();
      setupStores();
      render(<M3UGroupFilter {...defaultProps({ onClose })} />);
      await waitFor(() => screen.getByRole('button', { name: /save/i }));
      fireEvent.click(screen.getByRole('button', { name: /save/i }));
      expect(onClose).not.toHaveBeenCalled();
    });
  });

  describe('empty category selection confirmation', () => {
    const warning = () =>
      screen.queryByRole('dialog', { name: 'No categories selected' });
    const save = () =>
      fireEvent.click(
        screen.getByRole('button', { name: 'Save', exact: true })
      );

    it('requires confirmation for the first empty wizard selection without saving or toasts', async () => {
      setupStores();
      const onSetupSave = vi.fn();
      render(
        <M3UGroupFilter
          {...defaultProps({ isInitialSetup: true, onSetupSave })}
        />
      );
      fireEvent.click(screen.getByRole('button', { name: 'Save selection' }));
      expect(warning()).toBeInTheDocument();
      expect(
        screen.getByText(/No content from this account is selected for import/)
      ).toBeInTheDocument();
      expect(
        M3uGroupFilterUtils.savePlaylistGroupSettings
      ).not.toHaveBeenCalled();
      expect(M3uGroupFilterUtils.saveAndRefreshPlaylist).not.toHaveBeenCalled();
      expect(onSetupSave).not.toHaveBeenCalled();
      expect(showNotification).not.toHaveBeenCalled();
      fireEvent.click(
        screen.getByRole('button', { name: 'Back to selection' })
      );
      expect(warning()).not.toBeInTheDocument();
      expect(onSetupSave).not.toHaveBeenCalled();
      fireEvent.click(screen.getByRole('button', { name: 'Save selection' }));
      fireEvent.click(screen.getByRole('button', { name: 'Save anyway' }));
      await waitFor(() => expect(onSetupSave).toHaveBeenCalledOnce());
      expect(
        M3uGroupFilterUtils.savePlaylistGroupSettings
      ).toHaveBeenCalledOnce();
      expect(M3uGroupFilterUtils.saveAndRefreshPlaylist).not.toHaveBeenCalled();
      expect(showNotification).not.toHaveBeenCalled();
    });

    it('requires a fresh confirmation for each empty wizard save', async () => {
      setupStores();
      const onSetupSave = vi.fn();
      render(
        <M3UGroupFilter
          {...defaultProps({ isInitialSetup: true, onSetupSave })}
        />
      );
      fireEvent.click(screen.getByRole('button', { name: 'Save selection' }));
      fireEvent.click(screen.getByRole('button', { name: 'Save anyway' }));
      await waitFor(() => expect(onSetupSave).toHaveBeenCalledOnce());
      fireEvent.click(screen.getByRole('button', { name: 'Save selection' }));
      expect(warning()).toBeInTheDocument();
      expect(onSetupSave).toHaveBeenCalledOnce();
      expect(
        M3uGroupFilterUtils.savePlaylistGroupSettings
      ).toHaveBeenCalledOnce();
      fireEvent.click(screen.getByRole('button', { name: 'Save anyway' }));
      await waitFor(() => expect(onSetupSave).toHaveBeenCalledTimes(2));
      expect(warning()).not.toBeInTheDocument();
    });

    it('requires confirmation even when an empty wizard selection was previously reviewed', async () => {
      setupStores();
      const onSetupSave = vi.fn();
      render(
        <M3UGroupFilter
          {...defaultProps({
            isInitialSetup: true,
            onSetupSave,
            playlist: makePlaylist({ setup_categories_reviewed: true }),
          })}
        />
      );
      fireEvent.click(screen.getByRole('button', { name: 'Save selection' }));
      expect(warning()).toBeInTheDocument();
      expect(onSetupSave).not.toHaveBeenCalled();
      fireEvent.click(screen.getByRole('button', { name: 'Save anyway' }));
      await waitFor(() => expect(onSetupSave).toHaveBeenCalledOnce());
      expect(warning()).not.toBeInTheDocument();
    });

    it('warns before disabling the last selected live category and keeps changes when cancelled', async () => {
      setupStores();
      M3uGroupFilterUtils.buildGroupStates.mockReturnValueOnce([
        { channel_group: 1, enabled: true },
      ]);
      render(<M3UGroupFilter {...defaultProps()} />);
      fireEvent.click(screen.getByTestId('live-disable-groups'));
      save();
      expect(warning()).toBeInTheDocument();
      fireEvent.click(
        screen.getByRole('button', { name: 'Back to selection' })
      );
      expect(screen.getByTestId('live-group-count')).toHaveTextContent('1');
      expect(
        M3uGroupFilterUtils.savePlaylistGroupSettings
      ).not.toHaveBeenCalled();
      save();
      fireEvent.click(screen.getByRole('button', { name: 'Save anyway' }));
      await waitFor(() =>
        expect(
          M3uGroupFilterUtils.savePlaylistGroupSettings
        ).toHaveBeenCalledOnce()
      );
      expect(
        M3uGroupFilterUtils.savePlaylistGroupSettings.mock.lastCall[1]
      ).toEqual([expect.objectContaining({ enabled: false })]);
      save();
      expect(warning()).toBeInTheDocument();
      expect(
        M3uGroupFilterUtils.savePlaylistGroupSettings
      ).toHaveBeenCalledOnce();
      fireEvent.click(screen.getByRole('button', { name: 'Save anyway' }));
      await waitFor(() =>
        expect(
          M3uGroupFilterUtils.savePlaylistGroupSettings
        ).toHaveBeenCalledTimes(2)
      );
      expect(warning()).not.toBeInTheDocument();
    });

    it.each([false, true])(
      'confirms an already empty selection on every ordinary save (metadata edit: %s)',
      async (editMetadata) => {
        setupStores();
        M3uGroupFilterUtils.buildGroupStates.mockReturnValueOnce([
          { channel_group: 1, enabled: false },
        ]);
        render(<M3UGroupFilter {...defaultProps()} />);
        if (editMetadata)
          fireEvent.click(screen.getByTestId('live-annotate-groups'));
        save();
        expect(warning()).toBeInTheDocument();
        expect(
          M3uGroupFilterUtils.savePlaylistGroupSettings
        ).not.toHaveBeenCalled();
        fireEvent.click(screen.getByRole('button', { name: 'Save anyway' }));
        await waitFor(() =>
          expect(
            M3uGroupFilterUtils.savePlaylistGroupSettings
          ).toHaveBeenCalledOnce()
        );
        expect(warning()).not.toBeInTheDocument();
      }
    );

    it('requires confirmation again after reopening an empty category selection', () => {
      setupStores();
      const props = defaultProps();
      const { rerender } = render(<M3UGroupFilter {...props} />);
      save();
      expect(warning()).toBeInTheDocument();
      fireEvent.click(
        screen.getByRole('button', { name: 'Back to selection' })
      );
      rerender(<M3UGroupFilter {...props} isOpen={false} />);
      rerender(<M3UGroupFilter {...props} />);
      save();
      expect(warning()).toBeInTheDocument();
      expect(
        M3uGroupFilterUtils.savePlaylistGroupSettings
      ).not.toHaveBeenCalled();
    });

    it('checks the legacy Save and Refresh action before saving or importing', async () => {
      setupStores();
      const onClose = vi.fn();
      render(
        <M3UGroupFilter {...defaultProps({ isInitialSetup: true, onClose })} />
      );
      fireEvent.click(screen.getByRole('button', { name: 'Save and Refresh' }));
      expect(warning()).toBeInTheDocument();
      expect(M3uGroupFilterUtils.saveAndRefreshPlaylist).not.toHaveBeenCalled();
      expect(onClose).not.toHaveBeenCalled();
      fireEvent.click(screen.getByRole('button', { name: 'Save anyway' }));
      await waitFor(() =>
        expect(
          M3uGroupFilterUtils.saveAndRefreshPlaylist
        ).toHaveBeenCalledOnce()
      );
      expect(onClose).toHaveBeenCalledOnce();
    });

    it.each(['movie', 'series'])(
      'counts selected %s categories even when saving from another tab',
      async (type) => {
        setupStores();
        render(
          <M3UGroupFilter
            {...defaultProps({ isInitialSetup: true, onSetupSave: vi.fn() })}
          />
        );
        fireEvent.click(screen.getByTestId(`vod-change-${type}`));
        fireEvent.click(screen.getByRole('button', { name: 'Save selection' }));
        await waitFor(() =>
          expect(
            M3uGroupFilterUtils.savePlaylistGroupSettings
          ).toHaveBeenCalledOnce()
        );
        expect(warning()).not.toBeInTheDocument();
      }
    );

    it.each(['movie', 'series'])(
      'warns when the last saved %s selection becomes empty',
      async (type) => {
        setupStores();
        render(<M3UGroupFilter {...defaultProps()} />);
        fireEvent.click(screen.getByTestId(`vod-initialize-${type}`));
        fireEvent.click(screen.getByTestId(`vod-disable-${type}`));
        save();
        expect(warning()).toBeInTheDocument();
        expect(
          M3uGroupFilterUtils.savePlaylistGroupSettings
        ).not.toHaveBeenCalled();
        fireEvent.click(screen.getByRole('button', { name: 'Save anyway' }));
        await waitFor(() =>
          expect(
            M3uGroupFilterUtils.savePlaylistGroupSettings
          ).toHaveBeenCalledOnce()
        );
      }
    );

    it('ignores retained hidden VOD rows after VOD is disabled', () => {
      setupStores();
      M3uGroupFilterUtils.buildGroupStates.mockReturnValueOnce([
        { channel_group: 1, enabled: true },
      ]);
      const props = defaultProps();
      const { rerender } = render(<M3UGroupFilter {...props} />);
      fireEvent.click(screen.getByTestId('vod-change-movie'));
      fireEvent.click(screen.getByTestId('live-disable-groups'));
      rerender(
        <M3UGroupFilter
          {...props}
          playlist={makePlaylist({ enable_vod: false })}
        />
      );
      save();
      expect(warning()).toBeInTheDocument();
      expect(
        M3uGroupFilterUtils.savePlaylistGroupSettings
      ).not.toHaveBeenCalled();
    });

    it('ignores VOD counts for a standard M3U account', () => {
      setupStores();
      render(
        <M3UGroupFilter
          {...defaultProps({
            isInitialSetup: true,
            onSetupSave: vi.fn(),
            playlist: makePlaylist({
              account_type: 'STD',
              category_selection_counts: {
                movie: { selected: 2 },
                series: { selected: 1 },
              },
            }),
          })}
        />
      );
      fireEvent.click(screen.getByRole('button', { name: 'Save selection' }));
      expect(warning()).toBeInTheDocument();
    });

    it('does not mistake pending VOD rows for an empty selection', async () => {
      setupStores();
      render(
        <M3UGroupFilter
          {...defaultProps({
            isInitialSetup: true,
            onSetupSave: vi.fn(),
            playlist: makePlaylist({
              category_selection_counts: { series: { selected: 2 } },
            }),
          })}
        />
      );
      fireEvent.click(screen.getByRole('button', { name: 'Save selection' }));
      await waitFor(() =>
        expect(
          M3uGroupFilterUtils.savePlaylistGroupSettings
        ).toHaveBeenCalledOnce()
      );
      expect(warning()).not.toBeInTheDocument();
    });

    it('does not ask to discard or close the category editor while confirmation is open', () => {
      setupStores();
      const onClose = vi.fn();
      render(
        <M3UGroupFilter
          {...defaultProps({
            isInitialSetup: true,
            onSetupSave: vi.fn(),
            onClose,
          })}
        />
      );
      fireEvent.click(screen.getByRole('button', { name: 'Save selection' }));
      fireEvent.click(screen.getByTestId('modal-close'));
      expect(warning()).toBeInTheDocument();
      expect(onClose).not.toHaveBeenCalled();
      expect(
        screen.queryByRole('dialog', { name: 'Discard category changes?' })
      ).not.toBeInTheDocument();
    });

    it('prevents duplicate writes when confirming an empty selection', async () => {
      setupStores();
      let resolve;
      M3uGroupFilterUtils.savePlaylistGroupSettings.mockImplementationOnce(
        () =>
          new Promise((done) => {
            resolve = done;
          })
      );
      render(
        <M3UGroupFilter
          {...defaultProps({ isInitialSetup: true, onSetupSave: vi.fn() })}
        />
      );
      fireEvent.click(screen.getByRole('button', { name: 'Save selection' }));
      const confirm = screen.getByRole('button', { name: 'Save anyway' });
      fireEvent.click(confirm);
      fireEvent.click(confirm);
      expect(
        M3uGroupFilterUtils.savePlaylistGroupSettings
      ).toHaveBeenCalledOnce();
      resolve();
      await waitFor(() =>
        expect(screen.queryByTestId('loading-overlay')).not.toBeInTheDocument()
      );
    });
  });

  // ── Loading state ──────────────────────────────────────────────────────────

  describe('loading state', () => {
    it('disables Save button while submitting', async () => {
      let resolveSave;
      vi.mocked(
        M3uGroupFilterUtils.savePlaylistGroupSettings
      ).mockImplementation(
        () =>
          new Promise((res) => {
            resolveSave = res;
          })
      );
      setupStores();
      M3uGroupFilterUtils.buildGroupStates.mockReturnValueOnce([
        { channel_group: 1, enabled: true },
      ]);
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
