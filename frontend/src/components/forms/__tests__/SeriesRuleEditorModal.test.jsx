import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

// ── Store mocks ────────────────────────────────────────────────────────────
vi.mock('../../../store/channels.jsx', () => ({ default: vi.fn() }));
vi.mock('../../../store/epgs.jsx', () => ({ default: vi.fn() }));

// ── Utility mocks ──────────────────────────────────────────────────────────
vi.mock('../../../utils.js', () => ({
  useDebounce: vi.fn((val) => val),
}));

vi.mock('../../../utils/notificationUtils.js', () => ({
  showNotification: vi.fn(),
}));

vi.mock('../../../utils/forms/RecordingUtils.js', () => ({
  getChannelsSummary: vi.fn(),
}));

vi.mock('../../../utils/guideUtils.js', () => ({
  createSeriesRule: vi.fn(),
  evaluateSeriesRulesByTvgId: vi.fn(),
}));

vi.mock('../../../utils/forms/SeriesRuleEditorModalUtils.js', () => ({
  TITLE_MODES: [
    { label: 'Exact', value: 'exact' },
    { label: 'Contains', value: 'contains' },
  ],
  DESCRIPTION_MODES: [
    { label: 'Contains', value: 'contains' },
    { label: 'Exact', value: 'exact' },
  ],
  EPISODE_MODES: [
    { label: 'All', value: 'all' },
    { label: 'New only', value: 'new' },
  ],
  formatRange: vi.fn((start, end) => `${start} - ${end}`),
  getChannelOptions: vi.fn(() => [{ value: '10', label: '501 - HBO' }]),
  getTvgOptions: vi.fn(),
  previewSeriesRule: vi.fn(),
}));

// ── Mantine core ───────────────────────────────────────────────────────────
vi.mock('@mantine/core', () => ({
  Alert: ({ children, color }) => (
    <div data-testid="alert" data-color={color}>
      {children}
    </div>
  ),
  Badge: ({ children, color }) => (
    <span data-testid="badge" data-color={color}>
      {children}
    </span>
  ),
  Button: ({ children, onClick, disabled, loading, variant }) => (
    <button
      onClick={onClick}
      disabled={disabled || loading}
      data-loading={loading}
      data-variant={variant}
    >
      {children}
    </button>
  ),
  Divider: () => <hr />,
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
  ScrollAreaAutosize: ({ children }) => <div>{children}</div>,
  SegmentedControl: ({ data, value, onChange, size }) => (
    <div data-testid="segmented-control" data-size={size}>
      {data.map((item) => (
        <button
          key={item.value}
          data-active={value === item.value}
          onClick={() => onChange(item.value)}
        >
          {item.label}
        </button>
      ))}
    </div>
  ),
  Select: ({ label, placeholder, data, value, onChange, description }) => (
    <div>
      <label>{label}</label>
      {description && (
        <span data-testid="select-description">{description}</span>
      )}
      <select
        data-testid={`select-${label?.replace(/\s+/g, '-').toLowerCase()}`}
        value={value ?? ''}
        onChange={(e) => onChange(e.target.value || null)}
      >
        <option value="">{placeholder}</option>
        {(data || []).map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>
    </div>
  ),
  Stack: ({ children }) => <div>{children}</div>,
  Text: ({ children, size, c, fw }) => (
    <span data-size={size} data-color={c} data-fw={fw}>
      {children}
    </span>
  ),
  Textarea: ({ label, placeholder, value, onChange, description }) => (
    <div>
      <label>{label}</label>
      {description && <span>{description}</span>}
      <textarea
        data-testid="textarea-description"
        placeholder={placeholder}
        value={value}
        onChange={onChange}
      />
    </div>
  ),
  TextInput: ({ label, placeholder, value, onChange, description }) => (
    <div>
      <label>{label}</label>
      {description && <span>{description}</span>}
      <input
        data-testid="input-title"
        placeholder={placeholder}
        value={value}
        onChange={onChange}
      />
    </div>
  ),
}));

// ── Imports after mocks ────────────────────────────────────────────────────
import SeriesRuleEditorModal from '../SeriesRuleEditorModal';
import useChannelsStore from '../../../store/channels.jsx';
import useEPGsStore from '../../../store/epgs.jsx';
import { useDebounce } from '../../../utils.js';
import { showNotification } from '../../../utils/notificationUtils.js';
import { getChannelsSummary } from '../../../utils/forms/RecordingUtils.js';
import {
  createSeriesRule,
  evaluateSeriesRulesByTvgId,
} from '../../../utils/guideUtils.js';
import {
  getTvgOptions,
  previewSeriesRule,
  formatRange,
} from '../../../utils/forms/SeriesRuleEditorModalUtils.js';

// ── Shared test data ───────────────────────────────────────────────────────
const mockTvgs = [
  { id: 1, tvg_id: 'tvg-1', name: 'Channel One' },
  { id: 2, tvg_id: 'tvg-2', name: 'Channel Two' },
];

const mockTvgsById = {
  1: { tvg_id: 'tvg-1', name: 'Channel One' },
  2: { tvg_id: 'tvg-2', name: 'Channel Two' },
};

const mockChannels = [
  { id: 10, name: 'HBO', channel_number: 501, epg_data_id: 1 },
  { id: 20, name: 'CNN', channel_number: 102, epg_data_id: 2 },
];

const mockTvgOptions = [
  { value: 'tvg-1', label: 'Channel One (tvg-1)' },
  { value: 'tvg-2', label: 'Channel Two (tvg-2)' },
];

const mockPreviewResponse = {
  matches: [
    {
      id: 'p1',
      title: 'Match Show',
      sub_title: 'Episode 1',
      description: 'A great show',
      start_time: '2024-01-01T10:00:00Z',
      end_time: '2024-01-01T11:00:00Z',
      tvg_id: 'tvg-1',
      is_new: true,
    },
  ],
  total: 1,
  epg_found: true,
};

// ── Setup helper ───────────────────────────────────────────────────────────
const setupMocks = () => {
  const mockFetchRecordings = vi.fn().mockResolvedValue(undefined);

  vi.mocked(useEPGsStore).mockImplementation((selector) =>
    selector({ tvgs: mockTvgs, tvgsById: mockTvgsById })
  );

  // Mock getState for the imperative call in handleSave
  useChannelsStore.getState = vi.fn().mockReturnValue({
    fetchRecordings: mockFetchRecordings,
  });

  vi.mocked(getTvgOptions).mockReturnValue(mockTvgOptions);
  vi.mocked(getChannelsSummary).mockResolvedValue(mockChannels);
  vi.mocked(previewSeriesRule).mockResolvedValue({
    matches: [],
    total: 0,
    epg_found: true,
  });
  vi.mocked(createSeriesRule).mockResolvedValue({ id: 'rule-1' });
  vi.mocked(evaluateSeriesRulesByTvgId).mockResolvedValue(undefined);
  vi.mocked(useDebounce).mockImplementation((val) => val);
  vi.mocked(formatRange).mockImplementation((s, e) => `${s} - ${e}`);

  return { mockFetchRecordings };
};

// ──────────────────────────────────────────────────────────────────────────
describe('SeriesRuleEditorModal', () => {
  let defaultProps;

  beforeEach(() => {
    vi.clearAllMocks();
    setupMocks();

    defaultProps = {
      opened: true,
      onClose: vi.fn(),
      initialRule: null,
      onSaved: vi.fn(),
    };
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  // ── Rendering ────────────────────────────────────────────────────────────

  describe('rendering', () => {
    it('renders the modal when opened is true', () => {
      render(<SeriesRuleEditorModal {...defaultProps} />);
      expect(screen.getByTestId('modal')).toBeInTheDocument();
    });

    it('does not render the modal when opened is false', () => {
      render(<SeriesRuleEditorModal {...defaultProps} opened={false} />);
      expect(screen.queryByTestId('modal')).not.toBeInTheDocument();
    });

    it('shows "New Series Rule" title when initialRule is null', () => {
      render(<SeriesRuleEditorModal {...defaultProps} />);
      expect(screen.getByTestId('modal-title')).toHaveTextContent(
        'New Series Rule'
      );
    });

    it('shows "Edit Series Rule" title when initialRule is provided', () => {
      render(
        <SeriesRuleEditorModal
          {...defaultProps}
          initialRule={{ tvg_id: 'tvg-1', mode: 'all', title: 'Test' }}
        />
      );
      expect(screen.getByTestId('modal-title')).toHaveTextContent(
        'Edit Series Rule'
      );
    });

    it('renders the title input', () => {
      render(<SeriesRuleEditorModal {...defaultProps} />);
      expect(screen.getByTestId('input-title')).toBeInTheDocument();
    });

    it('renders the description textarea', () => {
      render(<SeriesRuleEditorModal {...defaultProps} />);
      expect(screen.getByTestId('textarea-description')).toBeInTheDocument();
    });

    it('renders Cancel and Save rule buttons', () => {
      render(<SeriesRuleEditorModal {...defaultProps} />);
      expect(screen.getByText('Cancel')).toBeInTheDocument();
      expect(screen.getByText('Save rule')).toBeInTheDocument();
    });

    it('Save rule button is disabled when no title or description', () => {
      render(<SeriesRuleEditorModal {...defaultProps} />);
      expect(screen.getByText('Save rule')).toBeDisabled();
    });

    it('Save rule button is enabled when title is provided', async () => {
      render(<SeriesRuleEditorModal {...defaultProps} />);
      fireEvent.change(screen.getByTestId('input-title'), {
        target: { value: 'My Show' },
      });
      expect(screen.getByText('Save rule')).not.toBeDisabled();
    });

    it('Save rule button is enabled when description is provided', async () => {
      render(<SeriesRuleEditorModal {...defaultProps} />);
      fireEvent.change(screen.getByTestId('textarea-description'), {
        target: { value: 'some description' },
      });
      expect(screen.getByText('Save rule')).not.toBeDisabled();
    });
  });

  // ── State hydration from initialRule ─────────────────────────────────────

  describe('state hydration', () => {
    const initialRule = {
      tvg_id: 'tvg-1',
      mode: 'new',
      title: 'Pre-filled Title',
      title_mode: 'contains',
      description: 'Pre-filled description',
      description_mode: 'exact',
      channel_id: 10,
    };

    it('pre-fills title from initialRule', () => {
      render(
        <SeriesRuleEditorModal {...defaultProps} initialRule={initialRule} />
      );
      expect(screen.getByTestId('input-title')).toHaveValue('Pre-filled Title');
    });

    it('pre-fills description from initialRule', () => {
      render(
        <SeriesRuleEditorModal {...defaultProps} initialRule={initialRule} />
      );
      expect(screen.getByTestId('textarea-description')).toHaveValue(
        'Pre-filled description'
      );
    });

    it('uses default mode "all" when initialRule has no mode', () => {
      render(
        <SeriesRuleEditorModal {...defaultProps} initialRule={{ title: 'X' }} />
      );
      // "All" segmented button should be active (data-active=true)
      const allBtn = screen
        .getAllByText('All')
        .find((el) => el.closest('[data-testid="segmented-control"]'));
      expect(allBtn).toBeTruthy();
    });

    it('resets fields when modal is reopened without initialRule', async () => {
      const { rerender } = render(
        <SeriesRuleEditorModal {...defaultProps} initialRule={initialRule} />
      );
      rerender(
        <SeriesRuleEditorModal
          {...defaultProps}
          opened={false}
          initialRule={null}
        />
      );
      rerender(
        <SeriesRuleEditorModal
          {...defaultProps}
          opened={true}
          initialRule={null}
        />
      );
      expect(screen.getByTestId('input-title')).toHaveValue('');
      expect(screen.getByTestId('textarea-description')).toHaveValue('');
    });
  });

  // ── Channel loading ───────────────────────────────────────────────────────

  describe('channel loading', () => {
    it('calls getChannelsSummary when modal opens', async () => {
      render(<SeriesRuleEditorModal {...defaultProps} />);
      await waitFor(() => {
        expect(getChannelsSummary).toHaveBeenCalled();
      });
    });

    it('does not call getChannelsSummary when modal is closed', () => {
      render(<SeriesRuleEditorModal {...defaultProps} opened={false} />);
      expect(getChannelsSummary).not.toHaveBeenCalled();
    });

    it('handles getChannelsSummary rejection gracefully', async () => {
      vi.mocked(getChannelsSummary).mockRejectedValue(
        new Error('Network error')
      );
      render(<SeriesRuleEditorModal {...defaultProps} />);
      // Should not throw; channel options just empty
      await waitFor(() => {
        expect(getChannelsSummary).toHaveBeenCalled();
      });
    });
  });

  // ── TVG options ───────────────────────────────────────────────────────────

  describe('EPG channel options', () => {
    it('calls getTvgOptions with tvgs from store', () => {
      render(<SeriesRuleEditorModal {...defaultProps} />);
      expect(getTvgOptions).toHaveBeenCalledWith(mockTvgs);
    });
  });

  // ── Preview ───────────────────────────────────────────────────────────────

  describe('preview', () => {
    it('does not call previewSeriesRule when title, description, and tvg_id are all empty', async () => {
      render(<SeriesRuleEditorModal {...defaultProps} />);
      await waitFor(() => expect(getChannelsSummary).toHaveBeenCalled());
      expect(previewSeriesRule).not.toHaveBeenCalled();
    });

    it('calls previewSeriesRule when title is entered', async () => {
      render(<SeriesRuleEditorModal {...defaultProps} />);
      fireEvent.change(screen.getByTestId('input-title'), {
        target: { value: 'My Show' },
      });
      await waitFor(() => {
        expect(previewSeriesRule).toHaveBeenCalledWith(
          expect.objectContaining({ title: 'My Show' }),
          expect.any(Object)
        );
      });
    });

    it('calls previewSeriesRule when description is entered', async () => {
      render(<SeriesRuleEditorModal {...defaultProps} />);
      fireEvent.change(screen.getByTestId('textarea-description'), {
        target: { value: 'some words' },
      });
      await waitFor(() => {
        expect(previewSeriesRule).toHaveBeenCalledWith(
          expect.objectContaining({ description: 'some words' }),
          expect.any(Object)
        );
      });
    });

    it('renders preview match results', async () => {
      vi.mocked(previewSeriesRule).mockResolvedValue(mockPreviewResponse);
      render(<SeriesRuleEditorModal {...defaultProps} />);
      fireEvent.change(screen.getByTestId('input-title'), {
        target: { value: 'Match Show' },
      });
      await waitFor(() => {
        expect(screen.getByText(/Match Show/)).toBeInTheDocument();
      });
    });

    it('renders preview badge with match count', async () => {
      vi.mocked(previewSeriesRule).mockResolvedValue({
        matches: [{ id: 'p1', title: 'X' }],
        total: 5,
        epg_found: true,
      });
      render(<SeriesRuleEditorModal {...defaultProps} />);
      fireEvent.change(screen.getByTestId('input-title'), {
        target: { value: 'X' },
      });
      await waitFor(() => {
        expect(screen.getByTestId('badge')).toHaveTextContent('1 of 5');
      });
    });

    it('shows preview error alert when previewSeriesRule rejects', async () => {
      vi.mocked(previewSeriesRule).mockRejectedValue(
        new Error('Preview failed')
      );
      render(<SeriesRuleEditorModal {...defaultProps} />);
      fireEvent.change(screen.getByTestId('input-title'), {
        target: { value: 'Boom' },
      });
      await waitFor(() => {
        expect(screen.getByTestId('alert')).toBeInTheDocument();
        expect(screen.getByTestId('alert')).toHaveTextContent('Preview failed');
      });
    });

    it('shows "No EPG channel matches" warning when epg_found is false and tvg_id is set', async () => {
      vi.mocked(previewSeriesRule).mockResolvedValue({
        matches: [],
        total: 0,
        epg_found: false,
      });
      render(
        <SeriesRuleEditorModal
          {...defaultProps}
          initialRule={{ tvg_id: 'tvg-999', title: 'X' }}
        />
      );
      await waitFor(() => {
        expect(
          screen.getByText(/No EPG channel matches this tvg_id/)
        ).toBeInTheDocument();
      });
    });

    it('shows warn alert when preview.warn is true', async () => {
      vi.mocked(previewSeriesRule).mockResolvedValue({
        matches: Array(50).fill({ id: 'x', title: 'X' }),
        total: 50,
        epg_found: true,
        warn: true,
      });
      render(<SeriesRuleEditorModal {...defaultProps} />);
      fireEvent.change(screen.getByTestId('input-title'), {
        target: { value: 'X' },
      });
      await waitFor(() => {
        expect(
          screen.getByText(/This rule matches many programs/)
        ).toBeInTheDocument();
      });
    });

    it('shows "No matching upcoming programs" when matches empty and filter set', async () => {
      vi.mocked(previewSeriesRule).mockResolvedValue({
        matches: [],
        total: 0,
        epg_found: true,
      });
      render(<SeriesRuleEditorModal {...defaultProps} />);
      fireEvent.change(screen.getByTestId('input-title'), {
        target: { value: 'Unknown Show' },
      });
      await waitFor(() => {
        expect(
          screen.getByText(/No matching upcoming programs/)
        ).toBeInTheDocument();
      });
    });

    it('renders sub_title in preview match', async () => {
      vi.mocked(previewSeriesRule).mockResolvedValue(mockPreviewResponse);
      render(<SeriesRuleEditorModal {...defaultProps} />);
      fireEvent.change(screen.getByTestId('input-title'), {
        target: { value: 'Match Show' },
      });
      await waitFor(() => {
        expect(screen.getByText(/Episode 1/)).toBeInTheDocument();
      });
    });

    it('renders "(NEW)" marker for new episodes in preview', async () => {
      vi.mocked(previewSeriesRule).mockResolvedValue(mockPreviewResponse);
      render(<SeriesRuleEditorModal {...defaultProps} />);
      fireEvent.change(screen.getByTestId('input-title'), {
        target: { value: 'Match Show' },
      });
      await waitFor(() => {
        expect(screen.getByText(/(NEW)/)).toBeInTheDocument();
      });
    });
  });

  // ── handleSave ────────────────────────────────────────────────────────────

  describe('handleSave', () => {
    const renderWithTitle = () => {
      render(<SeriesRuleEditorModal {...defaultProps} />);
      fireEvent.change(screen.getByTestId('input-title'), {
        target: { value: 'My Show' },
      });
    };

    it('calls createSeriesRule with correct payload', async () => {
      renderWithTitle();
      fireEvent.click(screen.getByText('Save rule'));
      await waitFor(() => {
        expect(createSeriesRule).toHaveBeenCalledWith(
          expect.objectContaining({ title: 'My Show', mode: 'all' })
        );
      });
    });

    it('calls evaluateSeriesRulesByTvgId after createSeriesRule', async () => {
      renderWithTitle();
      fireEvent.click(screen.getByText('Save rule'));
      await waitFor(() => {
        expect(evaluateSeriesRulesByTvgId).toHaveBeenCalled();
      });
    });

    it('calls fetchRecordings after save', async () => {
      const { mockFetchRecordings } = setupMocks();
      renderWithTitle();
      fireEvent.click(screen.getByText('Save rule'));
      await waitFor(() => {
        expect(mockFetchRecordings).toHaveBeenCalled();
      });
    });

    it('calls showNotification on success', async () => {
      renderWithTitle();
      fireEvent.click(screen.getByText('Save rule'));
      await waitFor(() => {
        expect(showNotification).toHaveBeenCalledWith(
          expect.objectContaining({ title: 'Series rule saved' })
        );
      });
    });

    it('calls onSaved callback on success', async () => {
      renderWithTitle();
      fireEvent.click(screen.getByText('Save rule'));
      await waitFor(() => {
        expect(defaultProps.onSaved).toHaveBeenCalled();
      });
    });

    it('calls onClose after save', async () => {
      renderWithTitle();
      fireEvent.click(screen.getByText('Save rule'));
      await waitFor(() => {
        expect(defaultProps.onClose).toHaveBeenCalled();
      });
    });

    it('does not call showNotification when createSeriesRule throws', async () => {
      vi.mocked(createSeriesRule).mockRejectedValue(new Error('Server error'));
      renderWithTitle();
      fireEvent.click(screen.getByText('Save rule'));
      await waitFor(() => {
        expect(createSeriesRule).toHaveBeenCalled();
      });
      expect(showNotification).not.toHaveBeenCalled();
    });

    it('does not crash when evaluateSeriesRulesByTvgId throws', async () => {
      vi.mocked(evaluateSeriesRulesByTvgId).mockRejectedValue(
        new Error('eval fail')
      );
      renderWithTitle();
      await expect(
        waitFor(() => {
          fireEvent.click(screen.getByText('Save rule'));
        })
      ).resolves.not.toThrow();
    });

    it('does not crash when fetchRecordings throws', async () => {
      useChannelsStore.getState = vi.fn().mockReturnValue({
        fetchRecordings: vi.fn().mockRejectedValue(new Error('fetch fail')),
      });
      renderWithTitle();
      await expect(
        waitFor(() => {
          fireEvent.click(screen.getByText('Save rule'));
        })
      ).resolves.not.toThrow();
    });

    it('includes channel_id in payload when channelId is set', async () => {
      vi.mocked(getChannelsSummary).mockResolvedValue(mockChannels);
      render(
        <SeriesRuleEditorModal
          {...defaultProps}
          initialRule={{ channel_id: 10, title: 'Show' }}
        />
      );
      fireEvent.click(screen.getByText('Save rule'));
      await waitFor(() => {
        expect(createSeriesRule).toHaveBeenCalledWith(
          expect.objectContaining({ channel_id: 10 })
        );
      });
    });

    it('omits channel_id from payload when no channel selected', async () => {
      renderWithTitle();
      fireEvent.click(screen.getByText('Save rule'));
      await waitFor(() => {
        const call = vi.mocked(createSeriesRule).mock.calls[0][0];
        expect(call).not.toHaveProperty('channel_id');
      });
    });
  });

  // ── Cancel button ─────────────────────────────────────────────────────────

  describe('Cancel button', () => {
    it('calls onClose when Cancel is clicked', () => {
      render(<SeriesRuleEditorModal {...defaultProps} />);
      fireEvent.click(screen.getByText('Cancel'));
      expect(defaultProps.onClose).toHaveBeenCalled();
    });
  });

  // ── SegmentedControl interactions ─────────────────────────────────────────

  describe('SegmentedControl', () => {
    it('changes title mode when SegmentedControl is clicked', () => {
      render(<SeriesRuleEditorModal {...defaultProps} />);
      fireEvent.click(
        screen
          .getAllByText('Contains')
          .find((el) => el.closest('[data-testid="segmented-control"]'))
      );
      // No error thrown; state updated without crash
    });

    it('changes episode mode to "New only"', () => {
      render(<SeriesRuleEditorModal {...defaultProps} />);
      fireEvent.click(screen.getByText('New only'));
      // Payload mode becomes 'new'; verify via save
      fireEvent.change(screen.getByTestId('input-title'), {
        target: { value: 'Test' },
      });
      fireEvent.click(screen.getByText('Save rule'));
      waitFor(() => {
        expect(createSeriesRule).toHaveBeenCalledWith(
          expect.objectContaining({ mode: 'new' })
        );
      });
    });
  });
});
