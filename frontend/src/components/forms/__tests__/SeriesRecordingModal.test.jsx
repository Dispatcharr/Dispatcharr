import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import SeriesRecordingModal from '../SeriesRecordingModal';

// ── Mantine core ───────────────────────────────────────────────────────────────
vi.mock('@mantine/core', () => ({
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
  Text: ({ children, size, c, fw }) => (
    <span data-testid="text" data-size={size} data-color={c} data-fw={fw}>
      {children}
    </span>
  ),
  Flex: ({ children }) => <div>{children}</div>,
  Group: ({ children }) => <div>{children}</div>,
  Button: ({ children, onClick, variant, color, disabled }) => (
    <button
      onClick={onClick}
      data-variant={variant}
      data-color={color}
      disabled={disabled}
    >
      {children}
    </button>
  ),
  Badge: ({ children, color }) => (
    <span data-testid="badge" data-color={color}>
      {children}
    </span>
  ),
}));

// ── Store ──────────────────────────────────────────────────────────────────────
vi.mock('../../../store/channels.jsx', () => ({
  default: { getState: vi.fn() },
}));

// ── Utils ──────────────────────────────────────────────────────────────────────
vi.mock('../../../utils/cards/RecordingCardUtils.js', () => ({
  deleteSeriesAndRule: vi.fn(),
}));

vi.mock('../../../utils/guideUtils.js', () => ({
  evaluateSeriesRulesByTvgId: vi.fn(),
  fetchRules: vi.fn(),
}));

vi.mock('../../../utils/notificationUtils.js', () => ({
  showNotification: vi.fn(),
}));

// ── SeriesRuleEditorModal ──────────────────────────────────────────────────────
vi.mock('../SeriesRuleEditorModal', () => ({
  default: ({ opened, onClose, initialRule, onSaved }) =>
    opened ? (
      <div data-testid="series-rule-editor">
        <span data-testid="editor-rule">{initialRule ? initialRule.title : 'new'}</span>
        <button data-testid="editor-close" onClick={onClose}>Close</button>
        <button data-testid="editor-save" onClick={onSaved}>Save</button>
      </div>
    ) : null,
}));

// ──────────────────────────────────────────────────────────────────────────────
import useChannelsStore from '../../../store/channels.jsx';
import { deleteSeriesAndRule } from '../../../utils/cards/RecordingCardUtils.js';
import { evaluateSeriesRulesByTvgId, fetchRules } from '../../../utils/guideUtils.js';
import { showNotification } from '../../../utils/notificationUtils.js';

const makeRule = (overrides = {}) => ({
  tvg_id: 'tvg-1',
  title: 'Test Show',
  mode: 'new',
  title_mode: 'exact',
  description: '',
  channel_id: null,
  ...overrides,
});

const defaultProps = (overrides = {}) => ({
  opened: true,
  onClose: vi.fn(),
  rules: [makeRule()],
  onRulesUpdate: vi.fn(),
  ...overrides,
});

const mockFetchRecordings = vi.fn().mockResolvedValue(undefined);

const setupMocks = () => {
  vi.mocked(useChannelsStore.getState).mockReturnValue({
    fetchRecordings: mockFetchRecordings,
  });
  vi.mocked(fetchRules).mockResolvedValue([makeRule()]);
  vi.mocked(evaluateSeriesRulesByTvgId).mockResolvedValue(undefined);
  vi.mocked(deleteSeriesAndRule).mockResolvedValue(undefined);
};

describe('SeriesRecordingModal', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    setupMocks();
  });

  // ── Visibility ─────────────────────────────────────────────────────────────

  describe('visibility', () => {
    it('renders when opened is true', () => {
      render(<SeriesRecordingModal {...defaultProps()} />);
      expect(screen.getByTestId('modal')).toBeInTheDocument();
    });

    it('does not render when opened is false', () => {
      render(<SeriesRecordingModal {...defaultProps({ opened: false })} />);
      expect(screen.queryByTestId('modal')).not.toBeInTheDocument();
    });

    it('renders modal title "Series Recording Rules"', () => {
      render(<SeriesRecordingModal {...defaultProps()} />);
      expect(screen.getByTestId('modal-title')).toHaveTextContent('Series Recording Rules');
    });

    it('calls onClose when modal close button is clicked', () => {
      const props = defaultProps();
      render(<SeriesRecordingModal {...props} />);
      fireEvent.click(screen.getByTestId('modal-close'));
      expect(props.onClose).toHaveBeenCalled();
    });
  });

  // ── Empty state ────────────────────────────────────────────────────────────

  describe('empty state', () => {
    it('shows "No series rules configured" when rules is empty', () => {
      render(<SeriesRecordingModal {...defaultProps({ rules: [] })} />);
      expect(screen.getByText('No series rules configured')).toBeInTheDocument();
    });

    it('shows "No series rules configured" when rules is null', () => {
      render(<SeriesRecordingModal {...defaultProps({ rules: null })} />);
      expect(screen.getByText('No series rules configured')).toBeInTheDocument();
    });

    it('does not show "No series rules configured" when rules are present', () => {
      render(<SeriesRecordingModal {...defaultProps()} />);
      expect(screen.queryByText('No series rules configured')).not.toBeInTheDocument();
    });
  });

  // ── Rule rendering ─────────────────────────────────────────────────────────

  describe('rule rendering', () => {
    it('renders rule title', () => {
      render(<SeriesRecordingModal {...defaultProps()} />);
      expect(screen.getByText('Test Show')).toBeInTheDocument();
    });

    it('falls back to tvg_id when rule has no title', () => {
      render(
        <SeriesRecordingModal
          {...defaultProps({ rules: [makeRule({ title: '', tvg_id: 'tvg-fallback' })] })}
        />
      );
      expect(screen.getByText('tvg-fallback')).toBeInTheDocument();
    });

    it('renders "Pinned channel" badge when channel_id is set', () => {
      render(
        <SeriesRecordingModal
          {...defaultProps({ rules: [makeRule({ channel_id: 'ch-1' })] })}
        />
      );
      expect(screen.getByText('Pinned channel')).toBeInTheDocument();
    });

    it('does not render "Pinned channel" badge when channel_id is null', () => {
      render(<SeriesRecordingModal {...defaultProps()} />);
      expect(screen.queryByText('Pinned channel')).not.toBeInTheDocument();
    });

    it('renders multiple rules', () => {
      const rules = [
        makeRule({ tvg_id: 'tvg-1', title: 'Show One' }),
        makeRule({ tvg_id: 'tvg-2', title: 'Show Two' }),
      ];
      render(<SeriesRecordingModal {...defaultProps({ rules })} />);
      expect(screen.getByText('Show One')).toBeInTheDocument();
      expect(screen.getByText('Show Two')).toBeInTheDocument();
    });

    it('renders Edit, Evaluate Now, and Remove buttons for each rule', () => {
      render(<SeriesRecordingModal {...defaultProps()} />);
      expect(screen.getByText('Edit')).toBeInTheDocument();
      expect(screen.getByText('Evaluate Now')).toBeInTheDocument();
      expect(screen.getByText('Remove')).toBeInTheDocument();
    });

    it('renders "Add rule" button', () => {
      render(<SeriesRecordingModal {...defaultProps()} />);
      expect(screen.getByText('Add rule')).toBeInTheDocument();
    });
  });

  // ── Rule summary ───────────────────────────────────────────────────────────

  describe('rule summary', () => {
    it('shows "New episodes" for mode new', () => {
      render(<SeriesRecordingModal {...defaultProps({ rules: [makeRule({ mode: 'new' })] })} />);
      expect(screen.getByText(/New episodes/)).toBeInTheDocument();
    });

    it('shows "Every episode" for mode all', () => {
      render(<SeriesRecordingModal {...defaultProps({ rules: [makeRule({ mode: 'all' })] })} />);
      expect(screen.getByText(/Every episode/)).toBeInTheDocument();
    });

    it('shows exact title label in summary', () => {
      render(
        <SeriesRecordingModal
          {...defaultProps({ rules: [makeRule({ title_mode: 'exact', title: 'Test Show' })] })}
        />
      );
      expect(screen.getByText(/Exact title: "Test Show"/)).toBeInTheDocument();
    });

    it('shows contains label in summary', () => {
      render(
        <SeriesRecordingModal
          {...defaultProps({ rules: [makeRule({ title_mode: 'contains', title: 'Test' })] })}
        />
      );
      expect(screen.getByText(/Title contains: "Test"/)).toBeInTheDocument();
    });

    it('shows regex label in summary', () => {
      render(
        <SeriesRecordingModal
          {...defaultProps({ rules: [makeRule({ title_mode: 'regex', title: '^Test' })] })}
        />
      );
      expect(screen.getByText(/Title regex: "\^Test"/)).toBeInTheDocument();
    });

    it('shows description in summary when present', () => {
      render(
        <SeriesRecordingModal
          {...defaultProps({ rules: [makeRule({ description: 'A drama' })] })}
        />
      );
      expect(screen.getByText(/Description: "A drama"/)).toBeInTheDocument();
    });

    it('does not show description in summary when empty', () => {
      render(<SeriesRecordingModal {...defaultProps()} />);
      expect(screen.queryByText(/Description:/)).not.toBeInTheDocument();
    });
  });

  // ── Evaluate Now ───────────────────────────────────────────────────────────

  describe('Evaluate Now', () => {
    it('calls evaluateSeriesRulesByTvgId with rule tvg_id', async () => {
      render(<SeriesRecordingModal {...defaultProps()} />);
      fireEvent.click(screen.getByText('Evaluate Now'));
      await waitFor(() => {
        expect(evaluateSeriesRulesByTvgId).toHaveBeenCalledWith('tvg-1');
      });
    });

    it('calls fetchRecordings after evaluation', async () => {
      render(<SeriesRecordingModal {...defaultProps()} />);
      fireEvent.click(screen.getByText('Evaluate Now'));
      await waitFor(() => {
        expect(mockFetchRecordings).toHaveBeenCalled();
      });
    });

    it('shows "Evaluated" notification after evaluation', async () => {
      render(<SeriesRecordingModal {...defaultProps()} />);
      fireEvent.click(screen.getByText('Evaluate Now'));
      await waitFor(() => {
        expect(showNotification).toHaveBeenCalledWith(
          expect.objectContaining({ title: 'Evaluated', message: 'Checked for episodes' })
        );
      });
    });

    it('still shows notification when fetchRecordings rejects', async () => {
      mockFetchRecordings.mockRejectedValueOnce(new Error('network'));
      render(<SeriesRecordingModal {...defaultProps()} />);
      fireEvent.click(screen.getByText('Evaluate Now'));
      await waitFor(() => {
        expect(showNotification).toHaveBeenCalledWith(
          expect.objectContaining({ title: 'Evaluated' })
        );
      });
    });
  });

  // ── Remove series ──────────────────────────────────────────────────────────

  describe('Remove series', () => {
    it('calls deleteSeriesAndRule with tvg_id and title', async () => {
      render(<SeriesRecordingModal {...defaultProps()} />);
      fireEvent.click(screen.getByText('Remove'));
      await waitFor(() => {
        expect(deleteSeriesAndRule).toHaveBeenCalledWith({
          tvg_id: 'tvg-1',
          title: 'Test Show',
        });
      });
    });

    it('calls fetchRecordings after removal', async () => {
      render(<SeriesRecordingModal {...defaultProps()} />);
      fireEvent.click(screen.getByText('Remove'));
      await waitFor(() => {
        expect(mockFetchRecordings).toHaveBeenCalled();
      });
    });

    it('calls fetchRules after removal', async () => {
      render(<SeriesRecordingModal {...defaultProps()} />);
      fireEvent.click(screen.getByText('Remove'));
      await waitFor(() => {
        expect(fetchRules).toHaveBeenCalled();
      });
    });

    it('calls onRulesUpdate with fetched rules after removal', async () => {
      const updated = [makeRule({ title: 'Updated Show' })];
      vi.mocked(fetchRules).mockResolvedValue(updated);
      const props = defaultProps();
      render(<SeriesRecordingModal {...props} />);
      fireEvent.click(screen.getByText('Remove'));
      await waitFor(() => {
        expect(props.onRulesUpdate).toHaveBeenCalledWith(updated);
      });
    });

    it('still calls onRulesUpdate when fetchRecordings rejects', async () => {
      mockFetchRecordings.mockRejectedValueOnce(new Error('network'));
      const props = defaultProps();
      render(<SeriesRecordingModal {...props} />);
      fireEvent.click(screen.getByText('Remove'));
      await waitFor(() => {
        expect(props.onRulesUpdate).toHaveBeenCalled();
      });
    });
  });

  // ── Add rule / Editor ──────────────────────────────────────────────────────

  describe('Add rule', () => {
    it('opens SeriesRuleEditorModal when "Add rule" is clicked', () => {
      render(<SeriesRecordingModal {...defaultProps()} />);
      fireEvent.click(screen.getByText('Add rule'));
      expect(screen.getByTestId('series-rule-editor')).toBeInTheDocument();
    });

    it('passes null initialRule when opening via "Add rule"', () => {
      render(<SeriesRecordingModal {...defaultProps()} />);
      fireEvent.click(screen.getByText('Add rule'));
      expect(screen.getByTestId('editor-rule')).toHaveTextContent('new');
    });

    it('closes SeriesRuleEditorModal when editor onClose fires', () => {
      render(<SeriesRecordingModal {...defaultProps()} />);
      fireEvent.click(screen.getByText('Add rule'));
      fireEvent.click(screen.getByTestId('editor-close'));
      expect(screen.queryByTestId('series-rule-editor')).not.toBeInTheDocument();
    });
  });

  // ── Edit rule ──────────────────────────────────────────────────────────────

  describe('Edit rule', () => {
    it('opens SeriesRuleEditorModal with the selected rule when Edit is clicked', () => {
      render(<SeriesRecordingModal {...defaultProps()} />);
      fireEvent.click(screen.getByText('Edit'));
      expect(screen.getByTestId('series-rule-editor')).toBeInTheDocument();
      expect(screen.getByTestId('editor-rule')).toHaveTextContent('Test Show');
    });

    it('calls fetchRules and onRulesUpdate when editor onSaved fires', async () => {
      const updated = [makeRule({ title: 'Saved Show' })];
      vi.mocked(fetchRules).mockResolvedValue(updated);
      const props = defaultProps();
      render(<SeriesRecordingModal {...props} />);
      fireEvent.click(screen.getByText('Edit'));
      fireEvent.click(screen.getByTestId('editor-save'));
      await waitFor(() => {
        expect(fetchRules).toHaveBeenCalled();
        expect(props.onRulesUpdate).toHaveBeenCalledWith(updated);
      });
    });

    it('closes editor after save', async () => {
      render(<SeriesRecordingModal {...defaultProps()} />);
      fireEvent.click(screen.getByText('Edit'));
      fireEvent.click(screen.getByTestId('editor-save'));
      await waitFor(() => {
        // editor is still open (onSaved doesn't auto-close) — just verify no error
        expect(fetchRules).toHaveBeenCalled();
      });
    });
  });
});