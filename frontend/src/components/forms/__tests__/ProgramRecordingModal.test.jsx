import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

// ── Dependency mocks ───────────────────────────────────────────────────────────
vi.mock('../../../utils/cards/RecordingCardUtils.js', () => ({
  deleteRecordingById: vi.fn(),
  deleteSeriesAndRule: vi.fn(),
}));

vi.mock('../../../utils/guideUtils.js', () => ({
  deleteSeriesRuleByTvgId: vi.fn(),
}));

vi.mock('../SeriesRuleEditorModal.jsx', () => ({
  default: ({ opened, onClose }) =>
    opened ? (
      <div data-testid="series-rule-editor-modal">
        <button data-testid="series-rule-editor-close" onClick={onClose}>
          Close Editor
        </button>
      </div>
    ) : null,
}));

vi.mock('@mantine/core', async () => ({
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
  Flex: ({ children }) => <div>{children}</div>,
  Button: ({ children, onClick, disabled, loading, color, variant }) => (
    <button
      onClick={onClick}
      disabled={disabled || loading}
      data-color={color}
      data-variant={variant}
    >
      {children}
    </button>
  ),
  Anchor: ({ children, onClick }) => (
    <a data-testid="anchor" onClick={onClick}>
      {children}
    </a>
  ),
}));

// ── Imports after mocks ────────────────────────────────────────────────────────
import ProgramRecordingModal from '../ProgramRecordingModal.jsx';
import {
  deleteRecordingById,
  deleteSeriesAndRule,
} from '../../../utils/cards/RecordingCardUtils.js';
import { deleteSeriesRuleByTvgId } from '../../../utils/guideUtils.js';

// ── Helpers ────────────────────────────────────────────────────────────────────
const makeProgram = (overrides = {}) => ({
  tvg_id: 'tvg-1',
  title: 'Test Show',
  ...overrides,
});

const makeRecording = (overrides = {}) => ({
  id: 'rec-1',
  ...overrides,
});

const defaultProps = (overrides = {}) => ({
  opened: true,
  onClose: vi.fn(),
  program: makeProgram(),
  recording: null,
  existingRuleMode: null,
  existingRule: null,
  onRecordOne: vi.fn(),
  onRecordSeriesAll: vi.fn(),
  onRecordSeriesNew: vi.fn(),
  onExistingRuleModeChange: vi.fn(),
  ...overrides,
});

// ─── ProgramRecordingModal ─────────────────────────────────────────────────────

describe('ProgramRecordingModal', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(deleteRecordingById).mockResolvedValue(undefined);
    vi.mocked(deleteSeriesAndRule).mockResolvedValue(undefined);
    vi.mocked(deleteSeriesRuleByTvgId).mockResolvedValue(undefined);
  });

  // ── Visibility ─────────────────────────────────────────────────────────────

  describe('visibility', () => {
    it('renders the modal when opened is true', () => {
      render(<ProgramRecordingModal {...defaultProps()} />);
      expect(screen.getByTestId('modal')).toBeInTheDocument();
    });

    it('does not render the modal when opened is false', () => {
      render(<ProgramRecordingModal {...defaultProps({ opened: false })} />);
      expect(screen.queryByTestId('modal')).not.toBeInTheDocument();
    });

    it('calls onClose when the modal close button is clicked', () => {
      const onClose = vi.fn();
      render(<ProgramRecordingModal {...defaultProps({ onClose })} />);
      fireEvent.click(screen.getByTestId('modal-close'));
      expect(onClose).toHaveBeenCalled();
    });
  });

  // ── handleRemoveRecording ──────────────────────────────────────────────────

  describe('handleRemoveRecording', () => {
    it('calls deleteRecordingById with the recording id', async () => {
      const recording = makeRecording();
      render(<ProgramRecordingModal {...defaultProps({ recording })} />);
      fireEvent.click(screen.getByText('Remove this recording'));
      await waitFor(() => {
        expect(deleteRecordingById).toHaveBeenCalledWith('rec-1');
      });
    });

    it('calls onClose after deleting recording', async () => {
      const onClose = vi.fn();
      const recording = makeRecording();
      render(
        <ProgramRecordingModal {...defaultProps({ recording, onClose })} />
      );
      fireEvent.click(screen.getByText('Remove this recording'));
      await waitFor(() => {
        expect(onClose).toHaveBeenCalled();
      });
    });

    it('still calls onClose when deleteRecordingById throws', async () => {
      vi.mocked(deleteRecordingById).mockRejectedValue(new Error('fail'));
      const onClose = vi.fn();
      const recording = makeRecording();
      render(
        <ProgramRecordingModal {...defaultProps({ recording, onClose })} />
      );
      fireEvent.click(screen.getByText('Remove this recording'));
      await waitFor(() => {
        expect(onClose).toHaveBeenCalled();
      });
    });
  });

  // ── handleRemoveSeries ─────────────────────────────────────────────────────

  describe('handleRemoveSeries', () => {
    it('calls deleteSeriesAndRule with tvg_id and title', async () => {
      const program = makeProgram({ tvg_id: 'tvg-2', title: 'My Series' });
      const recording = makeRecording();
      render(
        <ProgramRecordingModal
          {...defaultProps({ program, recording, existingRuleMode: 'series' })}
        />
      );
      fireEvent.click(screen.getByText(/Remove this series/i));
      await waitFor(() => {
        expect(deleteSeriesAndRule).toHaveBeenCalledWith({
          tvg_id: 'tvg-2',
          title: 'My Series',
        });
      });
    });

    it('calls onClose after removing series', async () => {
      const onClose = vi.fn();
      const recording = makeRecording();
      render(
        <ProgramRecordingModal
          {...defaultProps({ onClose, recording, existingRuleMode: 'series' })}
        />
      );
      fireEvent.click(screen.getByText(/Remove this series/i));
      await waitFor(() => {
        expect(onClose).toHaveBeenCalled();
      });
    });
  });

  // ── handleRemoveSeriesRule ─────────────────────────────────────────────────

  describe('handleRemoveSeriesRule', () => {
    it('calls deleteSeriesRuleByTvgId with tvg_id and title', async () => {
      const program = makeProgram({ tvg_id: 'tvg-3', title: 'Rule Show' });
      render(
        <ProgramRecordingModal
          {...defaultProps({ program, existingRuleMode: 'rule' })}
        />
      );
      fireEvent.click(screen.getByText(/Remove series rule/i));
      await waitFor(() => {
        expect(deleteSeriesRuleByTvgId).toHaveBeenCalledWith(
          'tvg-3',
          'Rule Show'
        );
      });
    });

    it('calls onExistingRuleModeChange(null) after removing rule', async () => {
      const onExistingRuleModeChange = vi.fn();
      render(
        <ProgramRecordingModal
          {...defaultProps({
            existingRuleMode: 'rule',
            onExistingRuleModeChange,
          })}
        />
      );
      fireEvent.click(screen.getByText(/Remove series rule/i));
      await waitFor(() => {
        expect(onExistingRuleModeChange).toHaveBeenCalledWith(null);
      });
    });

    it('calls onClose after removing rule', async () => {
      const onClose = vi.fn();
      render(
        <ProgramRecordingModal
          {...defaultProps({ existingRuleMode: 'rule', onClose })}
        />
      );
      fireEvent.click(screen.getByText(/Remove series rule/i));
      await waitFor(() => {
        expect(onClose).toHaveBeenCalled();
      });
    });
  });

  // ── Record actions ─────────────────────────────────────────────────────────

  describe('record actions', () => {
    it('calls onRecordOne when "Record Once" is clicked', () => {
      const onRecordOne = vi.fn();
      render(<ProgramRecordingModal {...defaultProps({ onRecordOne })} />);
      fireEvent.click(screen.getByText('Just this one'));
      expect(onRecordOne).toHaveBeenCalled();
    });

    it('calls onRecordSeriesAll when "Record All" is clicked', () => {
      const onRecordSeriesAll = vi.fn();
      render(
        <ProgramRecordingModal {...defaultProps({ onRecordSeriesAll })} />
      );
      fireEvent.click(screen.getByText('Every episode'));
      expect(onRecordSeriesAll).toHaveBeenCalled();
    });

    it('calls onRecordSeriesNew when "Record New" is clicked', () => {
      const onRecordSeriesNew = vi.fn();
      render(
        <ProgramRecordingModal {...defaultProps({ onRecordSeriesNew })} />
      );
      fireEvent.click(screen.getByText('New episodes only'));
      expect(onRecordSeriesNew).toHaveBeenCalled();
    });
  });

  // ── SeriesRuleEditorModal ──────────────────────────────────────────────────

  describe('SeriesRuleEditorModal', () => {
    it('opens SeriesRuleEditorModal when "Edit Rule" is clicked', () => {
      render(
        <ProgramRecordingModal
          {...defaultProps({
            existingRuleMode: 'rule',
            existingRule: { id: 1 },
          })}
        />
      );
      fireEvent.click(screen.getByText(/Customize rule/i));
      expect(
        screen.getByTestId('series-rule-editor-modal')
      ).toBeInTheDocument();
    });

    it('closes SeriesRuleEditorModal when its onClose is called', () => {
      render(
        <ProgramRecordingModal
          {...defaultProps({
            existingRuleMode: 'rule',
            existingRule: { id: 1 },
          })}
        />
      );
      fireEvent.click(screen.getByText(/Customize rule/i));
      fireEvent.click(screen.getByTestId('series-rule-editor-close'));
      expect(
        screen.queryByTestId('series-rule-editor-modal')
      ).not.toBeInTheDocument();
    });
  });
});
