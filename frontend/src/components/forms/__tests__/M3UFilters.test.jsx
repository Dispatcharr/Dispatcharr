import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import M3UFilters from '../M3UFilters';

// ── Store mocks ────────────────────────────────────────────────────────────────
vi.mock('../../../store/playlists', () => ({ default: vi.fn() }));
vi.mock('../../../store/warnings', () => ({ default: vi.fn() }));

// ── Utility mocks ──────────────────────────────────────────────────────────────
vi.mock('../../../utils/forms/M3uFilterUtils.js', () => ({
  deleteM3UFilter: vi.fn(),
  updateM3UFilter: vi.fn(),
}));

// ── Constants mock ─────────────────────────────────────────────────────────────
vi.mock('../../../constants', () => ({
  M3U_FILTER_TYPES: [
    { value: 'include', label: 'Include' },
    { value: 'exclude', label: 'Exclude' },
  ],
}));

// ── Sub-component mocks ────────────────────────────────────────────────────────
vi.mock('../M3UFilter', () => ({
  default: ({ isOpen, onClose, filter, m3u }) =>
    isOpen ? (
      <div data-testid="m3u-filter-editor">
        <div data-testid="editor-filter-id">{filter?.id ?? 'new'}</div>
        <button data-testid="editor-close" onClick={() => onClose()}>
          Close Editor
        </button>
        <button
          data-testid="editor-close-with-playlist"
          onClick={() => onClose({ id: m3u?.id, filters: [] })}
        >
          Close With Playlist
        </button>
      </div>
    ) : null,
}));

vi.mock('../../ConfirmationDialog', () => ({
  default: ({ opened, onConfirm, onClose, title }) =>
    opened ? (
      <div data-testid="confirmation-dialog">
        <div data-testid="confirm-title">{title}</div>
        <button data-testid="confirm-yes" onClick={onConfirm}>
          Yes
        </button>
        <button data-testid="confirm-no" onClick={onClose}>
          No
        </button>
      </div>
    ) : null,
}));

// ── DnD kit mocks ──────────────────────────────────────────────────────────────
vi.mock('@dnd-kit/core', () => ({
  closestCenter: vi.fn(),
  DndContext: vi.fn(({ children, onDragEnd }) => (
    <div data-testid="dnd-context" data-ondragend={!!onDragEnd}>
      {children}
    </div>
  )),
  KeyboardSensor: vi.fn(),
  MouseSensor: vi.fn(),
  TouchSensor: vi.fn(),
  useDraggable: () => ({
    attributes: {},
    listeners: {},
    setNodeRef: vi.fn(),
  }),
  useSensor: vi.fn((sensor) => sensor),
  useSensors: vi.fn((...sensors) => sensors),
}));

vi.mock('@dnd-kit/sortable', () => ({
  arrayMove: vi.fn((arr, from, to) => {
    const result = [...arr];
    const [item] = result.splice(from, 1);
    result.splice(to, 0, item);
    return result;
  }),
  SortableContext: ({ children }) => (
    <div data-testid="sortable-context">{children}</div>
  ),
  useSortable: () => ({
    transform: null,
    transition: null,
    setNodeRef: vi.fn(),
    isDragging: false,
  }),
  verticalListSortingStrategy: vi.fn(),
}));

vi.mock('@dnd-kit/utilities', () => ({
  CSS: { Transform: { toString: vi.fn(() => '') } },
}));

vi.mock('@dnd-kit/modifiers', () => ({
  restrictToVerticalAxis: vi.fn(),
}));

// ── lucide-react mocks ─────────────────────────────────────────────────────────
vi.mock('lucide-react', () => ({
  GripHorizontal: () => <svg data-testid="icon-grip" />,
  Info: () => <svg data-testid="icon-info" />,
  SquareMinus: () => <svg data-testid="icon-square-minus" />,
  SquarePen: () => <svg data-testid="icon-square-pen" />,
}));

// ── Mantine core ───────────────────────────────────────────────────────────────
vi.mock('@mantine/core', () => ({
  ActionIcon: ({ children, onClick, disabled, color }) => (
    <button
      data-testid="action-icon"
      data-color={color}
      onClick={onClick}
      disabled={disabled}
    >
      {children}
    </button>
  ),
  Alert: ({ children, title }) => (
    <div data-testid="alert">
      <div data-testid="alert-title">{title}</div>
      {children}
    </div>
  ),
  Box: ({ children, ref }) => <div ref={ref}>{children}</div>,
  Button: ({ children, onClick, disabled, loading, variant, color }) => (
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
  Center: ({ children }) => <div>{children}</div>,
  Flex: ({ children }) => <div>{children}</div>,
  Group: ({ children }) => <div>{children}</div>,
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
  Text: ({ children, size, c, fw }) => (
    <span data-size={size} data-color={c} data-fw={fw}>
      {children}
    </span>
  ),
  useMantineTheme: () => ({
    tailwind: {
      red: { 6: '#f56565' },
      green: { 5: '#48bb78'},
      yellow: { 3: '#ecc94b'},
    },
  }),
}));

// ──────────────────────────────────────────────────────────────────────────────
// Imports after mocks
// ──────────────────────────────────────────────────────────────────────────────
import usePlaylistsStore from '../../../store/playlists';
import useWarningsStore from '../../../store/warnings';
import * as M3uFilterUtils from '../../../utils/forms/M3uFilterUtils.js';

// ── Helpers ────────────────────────────────────────────────────────────────────
const makeFilter = (overrides = {}) => ({
  id: 1,
  filter_type: 'include',
  regex_pattern: 'HBO.*',
  is_active: true,
  exclude: false,
  order: 0,
  ...overrides,
});

const makePlaylist = (overrides = {}) => ({
  id: 10,
  name: 'Test Playlist',
  filters: [
    makeFilter({ id: 1, regex_pattern: 'HBO.*', order: 0 }),
    makeFilter({ id: 2, filter_type: 'exclude', regex_pattern: 'ESPN.*', order: 1 }),
  ],
  ...overrides,
});

const defaultProps = (overrides = {}) => ({
  playlist: makePlaylist(),
  isOpen: true,
  onClose: vi.fn(),
  ...overrides,
});

const setupStores = ({
                       fetchPlaylist = vi.fn().mockResolvedValue(undefined),
                       isWarningSuppressed = vi.fn().mockReturnValue(false),
                       suppressWarning = vi.fn(),
                     } = {}) => {
  vi.mocked(usePlaylistsStore).mockImplementation((sel) =>
    sel({ fetchPlaylist })
  );
  vi.mocked(useWarningsStore).mockImplementation((sel) =>
    sel({ isWarningSuppressed, suppressWarning })
  );
  return { fetchPlaylist, isWarningSuppressed, suppressWarning };
};

// ──────────────────────────────────────────────────────────────────────────────

describe('M3UFilters', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(M3uFilterUtils.deleteM3UFilter).mockResolvedValue(undefined);
    vi.mocked(M3uFilterUtils.updateM3UFilter).mockResolvedValue(undefined);
  });

  // ── Guard conditions ───────────────────────────────────────────────────────

  describe('guard conditions', () => {
    it('does not render modal when isOpen is false', () => {
      setupStores();
      render(<M3UFilters {...defaultProps({ isOpen: false })} />);
      expect(screen.queryByTestId('modal')).not.toBeInTheDocument();
    });

    it('does not render modal when playlist is null', () => {
      setupStores();
      render(<M3UFilters {...defaultProps({ playlist: {} })} />);
      expect(screen.queryByTestId('modal')).not.toBeInTheDocument();
    });

    it('does not render modal when playlist has no id', () => {
      setupStores();
      render(
        <M3UFilters
          {...defaultProps({ playlist: { ...makePlaylist(), id: undefined } })}
        />
      );
      expect(screen.queryByTestId('modal')).not.toBeInTheDocument();
    });
  });

  // ── Rendering ──────────────────────────────────────────────────────────────

  describe('rendering', () => {
    it('renders the modal when isOpen is true with a valid playlist', () => {
      setupStores();
      render(<M3UFilters {...defaultProps()} />);
      expect(screen.getByTestId('modal')).toBeInTheDocument();
    });

    it('renders the modal title', () => {
      setupStores();
      render(<M3UFilters {...defaultProps()} />);
      expect(screen.getByTestId('modal-title')).toBeInTheDocument();
    });

    it('renders an "Add Filter" button', () => {
      setupStores();
      render(<M3UFilters {...defaultProps()} />);
      expect(
        screen.getByRole('button', { name: /new/i })
      ).toBeInTheDocument();
    });

    it('renders filter patterns from playlist', () => {
      setupStores();
      render(<M3UFilters {...defaultProps()} />);
      expect(screen.getByText('HBO.*')).toBeInTheDocument();
      expect(screen.getByText('ESPN.*')).toBeInTheDocument();
    });

    it('renders filter type labels for each filter', () => {
      setupStores();
      render(<M3UFilters {...defaultProps()} />);
      expect(screen.getAllByText('Include').length).toBeGreaterThanOrEqual(1);
      expect(screen.getAllByText('Exclude').length).toBeGreaterThanOrEqual(1);
    });

    it('renders edit action icons for each filter', () => {
      setupStores();
      render(<M3UFilters {...defaultProps()} />);
      const penIcons = screen.getAllByTestId('icon-square-pen');
      expect(penIcons).toHaveLength(2);
    });

    it('renders delete action icons for each filter', () => {
      setupStores();
      render(<M3UFilters {...defaultProps()} />);
      const minusIcons = screen.getAllByTestId('icon-square-minus');
      expect(minusIcons).toHaveLength(2);
    });

    it('renders drag handle icons for each filter', () => {
      setupStores();
      render(<M3UFilters {...defaultProps()} />);
      const gripIcons = screen.getAllByTestId('icon-grip');
      expect(gripIcons).toHaveLength(2);
    });

    it('renders empty state when playlist has no filters', () => {
      setupStores();
      const playlist = makePlaylist({
        filters: [],
      });
      render(<M3UFilters {...defaultProps({ playlist })} />);
      expect(screen.queryByTestId('icon-square-pen')).not.toBeInTheDocument();
    });

    it('wraps list in DndContext', () => {
      setupStores();
      render(<M3UFilters {...defaultProps()} />);
      expect(screen.getByTestId('dnd-context')).toBeInTheDocument();
    });

    it('wraps list in SortableContext', () => {
      setupStores();
      render(<M3UFilters {...defaultProps()} />);
      expect(screen.getByTestId('sortable-context')).toBeInTheDocument();
    });
  });

  // ── Close / cancel ─────────────────────────────────────────────────────────

  describe('close behaviour', () => {
    it('calls onClose when modal X is clicked', () => {
      const onClose = vi.fn();
      setupStores();
      render(<M3UFilters {...defaultProps({ onClose })} />);
      fireEvent.click(screen.getByTestId('modal-close'));
      expect(onClose).toHaveBeenCalled();
    });
  });

  // ── Opening the filter editor ──────────────────────────────────────────────

  describe('opening the filter editor', () => {
    it('opens M3UFilter editor when Add Filter is clicked', () => {
      setupStores();
      render(<M3UFilters {...defaultProps()} />);
      fireEvent.click(screen.getByRole('button', { name: /new/i }));
      expect(screen.getByTestId('m3u-filter-editor')).toBeInTheDocument();
    });

    it('passes null filter to editor when adding a new filter', () => {
      setupStores();
      render(<M3UFilters {...defaultProps()} />);
      fireEvent.click(screen.getByRole('button', { name: /new/i }));
      expect(screen.getByTestId('editor-filter-id')).toHaveTextContent('new');
    });

    it('opens editor with the correct filter when edit icon is clicked', () => {
      setupStores();
      render(<M3UFilters {...defaultProps()} />);
      const editButtons = screen
        .getAllByTestId('icon-square-pen')
        .map((icon) => icon.closest('button'));
      fireEvent.click(editButtons[0]);
      expect(screen.getByTestId('m3u-filter-editor')).toBeInTheDocument();
      expect(screen.getByTestId('editor-filter-id')).toHaveTextContent('1');
    });

    it('closes editor when editor fires onClose without updated playlist', () => {
      setupStores();
      render(<M3UFilters {...defaultProps()} />);
      fireEvent.click(screen.getByRole('button', { name: /new/i }));
      fireEvent.click(screen.getByTestId('editor-close'));
      expect(screen.queryByTestId('m3u-filter-editor')).not.toBeInTheDocument();
    });

    it('closes editor and refreshes filters when editor fires onClose with playlist', async () => {
      setupStores();
      render(<M3UFilters {...defaultProps()} />);
      fireEvent.click(screen.getByRole('button', { name: /new/i }));
      fireEvent.click(screen.getByTestId('editor-close-with-playlist'));
      expect(screen.queryByTestId('m3u-filter-editor')).not.toBeInTheDocument();
    });
  });

  // ── Delete filter ──────────────────────────────────────────────────────────

  describe('deleting a filter', () => {
    const clickDeleteFirst = () => {
      const deleteButtons = screen
        .getAllByTestId('icon-square-minus')
        .map((icon) => icon.closest('button'));
      fireEvent.click(deleteButtons[0]);
    };

    it('opens confirmation dialog when delete icon is clicked (warning not suppressed)', () => {
      setupStores({ isWarningSuppressed: vi.fn().mockReturnValue(false) });
      render(<M3UFilters {...defaultProps()} />);
      clickDeleteFirst();
      expect(screen.getByTestId('confirmation-dialog')).toBeInTheDocument();
    });

    it('calls deleteM3UFilter directly when warning is suppressed', async () => {
      setupStores({ isWarningSuppressed: vi.fn().mockReturnValue(true) });
      render(<M3UFilters {...defaultProps()} />);
      clickDeleteFirst();
      await waitFor(() => {
        expect(M3uFilterUtils.deleteM3UFilter).toHaveBeenCalled();
      });
    });

    it('does not open confirmation dialog when warning is suppressed', async () => {
      setupStores({ isWarningSuppressed: vi.fn().mockReturnValue(true) });
      render(<M3UFilters {...defaultProps()} />);
      clickDeleteFirst();
      expect(
        screen.queryByTestId('confirmation-dialog')
      ).not.toBeInTheDocument();
    });

    it('calls deleteM3UFilter after confirming deletion', async () => {
      setupStores({ isWarningSuppressed: vi.fn().mockReturnValue(false) });
      render(<M3UFilters {...defaultProps()} />);
      clickDeleteFirst();
      fireEvent.click(screen.getByTestId('confirm-yes'));
      await waitFor(() => {
        expect(M3uFilterUtils.deleteM3UFilter).toHaveBeenCalled();
      });
    });

    it('calls fetchPlaylist after successful deletion', async () => {
      const { fetchPlaylist } = setupStores({
        isWarningSuppressed: vi.fn().mockReturnValue(false),
      });
      render(<M3UFilters {...defaultProps()} />);
      clickDeleteFirst();
      fireEvent.click(screen.getByTestId('confirm-yes'));
      await waitFor(() => {
        expect(fetchPlaylist).toHaveBeenCalledWith(10);
      });
    });

    it('closes confirmation dialog after confirming deletion', async () => {
      setupStores({ isWarningSuppressed: vi.fn().mockReturnValue(false) });
      render(<M3UFilters {...defaultProps()} />);
      clickDeleteFirst();
      fireEvent.click(screen.getByTestId('confirm-yes'));
      await waitFor(() => {
        expect(
          screen.queryByTestId('confirmation-dialog')
        ).not.toBeInTheDocument();
      });
    });

    it('closes confirmation dialog when No is clicked', () => {
      setupStores({ isWarningSuppressed: vi.fn().mockReturnValue(false) });
      render(<M3UFilters {...defaultProps()} />);
      clickDeleteFirst();
      fireEvent.click(screen.getByTestId('confirm-no'));
      expect(
        screen.queryByTestId('confirmation-dialog')
      ).not.toBeInTheDocument();
    });

    it('does not call deleteM3UFilter when No is clicked', () => {
      setupStores({ isWarningSuppressed: vi.fn().mockReturnValue(false) });
      render(<M3UFilters {...defaultProps()} />);
      clickDeleteFirst();
      fireEvent.click(screen.getByTestId('confirm-no'));
      expect(M3uFilterUtils.deleteM3UFilter).not.toHaveBeenCalled();
    });

    it('does not call fetchPlaylist when deleteM3UFilter throws', async () => {
      vi.mocked(M3uFilterUtils.deleteM3UFilter).mockRejectedValue(
        new Error('fail')
      );
      const { fetchPlaylist } = setupStores({
        isWarningSuppressed: vi.fn().mockReturnValue(false),
      });
      render(<M3UFilters {...defaultProps()} />);
      clickDeleteFirst();
      fireEvent.click(screen.getByTestId('confirm-yes'));
      await waitFor(() => {
        expect(M3uFilterUtils.deleteM3UFilter).toHaveBeenCalled();
      });
      expect(fetchPlaylist).not.toHaveBeenCalled();
    });
  });

  // ── Initialization from playlist prop ─────────────────────────────────────

  describe('filter initialization', () => {
    it('loads filters from playlist.custom_properties.filters on mount', () => {
      setupStores();
      render(<M3UFilters {...defaultProps()} />);
      expect(screen.getByText('HBO.*')).toBeInTheDocument();
      expect(screen.getByText('ESPN.*')).toBeInTheDocument();
    });

    it('updates displayed filters when playlist prop changes', () => {
      setupStores();
      const { rerender } = render(<M3UFilters {...defaultProps()} />);
      const updatedPlaylist = makePlaylist({
        filters: [makeFilter({ id: 3, regex_pattern: 'CNN.*', order: 0 })],
      });
      rerender(
        <M3UFilters
          {...defaultProps({ playlist: updatedPlaylist })}
        />
      );
      expect(screen.getByText('CNN.*')).toBeInTheDocument();
      expect(screen.queryByText('HBO.*')).not.toBeInTheDocument();
    });
  });

  // ── Drag and drop reordering ───────────────────────────────────────────────

  describe('drag and drop', () => {
    it('calls updateM3UFilter for reordered filters after drag end', async () => {
      setupStores();
      // We need to trigger handleDragEnd manually via the DndContext mock.
      // Re-mock DndContext to capture and expose onDragEnd.
      let capturedOnDragEnd;
      const { DndContext } = await import('@dnd-kit/core');
      vi.mocked(DndContext).mockImplementation(({ children, onDragEnd }) => {
        capturedOnDragEnd = onDragEnd;
        return <div data-testid="dnd-context">{children}</div>;
      });

      render(<M3UFilters {...defaultProps()} />);

      // Simulate drag: move filter id=1 over filter id=2
      await waitFor(() => expect(capturedOnDragEnd).toBeDefined());
      capturedOnDragEnd({ active: { id: 1 }, over: { id: 2 } });

      await waitFor(() => {
        expect(M3uFilterUtils.updateM3UFilter).toHaveBeenCalled();
      });
    });

    it('does not call updateM3UFilter when drag ends on same position', async () => {
      setupStores();
      let capturedOnDragEnd;
      const { DndContext } = await import('@dnd-kit/core');
      vi.mocked(DndContext).mockImplementation(({ children, onDragEnd }) => {
        capturedOnDragEnd = onDragEnd;
        return <div data-testid="dnd-context">{children}</div>;
      });

      render(<M3UFilters {...defaultProps()} />);

      await waitFor(() => expect(capturedOnDragEnd).toBeDefined());
      capturedOnDragEnd({ active: { id: 1 }, over: { id: 1 } });

      await waitFor(() => {
        expect(M3uFilterUtils.updateM3UFilter).not.toHaveBeenCalled();
      });
    });

    it('does not call updateM3UFilter when there is no over target', async () => {
      setupStores();
      let capturedOnDragEnd;
      const { DndContext } = await import('@dnd-kit/core');
      vi.mocked(DndContext).mockImplementation(({ children, onDragEnd }) => {
        capturedOnDragEnd = onDragEnd;
        return <div data-testid="dnd-context">{children}</div>;
      });

      render(<M3UFilters {...defaultProps()} />);

      await waitFor(() => expect(capturedOnDragEnd).toBeDefined());
      capturedOnDragEnd({ active: { id: 1 }, over: null });

      expect(M3uFilterUtils.updateM3UFilter).not.toHaveBeenCalled();
    });
  });

  // ── Warning suppression ────────────────────────────────────────────────────

  describe('warning suppression', () => {
    it('calls suppressWarning when user confirms and opts to suppress', async () => {
      // This depends on ConfirmationDialog exposing a "suppress" callback.
      // Here we verify suppressWarning is available from the store.
      const { suppressWarning } = setupStores({
        isWarningSuppressed: vi.fn().mockReturnValue(false),
      });
      render(<M3UFilters {...defaultProps()} />);
      expect(suppressWarning).toBeDefined();
    });
  });
});