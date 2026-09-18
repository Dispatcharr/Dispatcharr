import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../../api', () => ({
  default: {
    getVODPlaybackSessions: vi.fn(),
    getVODPlaybackFacets: vi.fn(),
    getVODPlaybackStats: vi.fn(),
    updateVODPlaybackRetention: vi.fn(),
    deleteVODPlaybackSessions: vi.fn(),
    bulkUpdateVODPlaybackMetadata: vi.fn(),
    updateVODRelationManualMetadata: vi.fn(),
  },
}));
vi.mock('../../utils/notificationUtils', () => ({
  showNotification: vi.fn(),
}));
vi.mock('../LanguagePicker.jsx', () => ({
  default: ({ label, value = [], onChange, disabled }) => (
    <label>
      {label}
      <input
        aria-label={label}
        value={value.join(',')}
        disabled={disabled}
        onChange={(event) =>
          onChange(event.target.value.split(',').filter(Boolean))
        }
      />
    </label>
  ),
}));
vi.mock('../VideoFeaturePicker.jsx', () => ({
  default: ({ label, value = [] }) => (
    <div aria-label={label || 'Video features'}>{value.join(',')}</div>
  ),
}));
vi.mock('lucide-react', () => ({
  Eye: () => null,
  RefreshCw: () => null,
  Trash2: () => null,
  Wrench: () => null,
}));
vi.mock('@mantine/hooks', () => ({
  useDebouncedValue: (value) => [value],
}));
vi.mock('../ConfirmationDialog.jsx', () => ({
  default: ({ opened, onConfirm, title }) =>
    opened ? (
      <div>
        <span>{title}</span>
        <button onClick={onConfirm}>Confirm delete</button>
      </div>
    ) : null,
}));
vi.mock('@mantine/core', () => {
  const Wrapper = ({ children }) => <div>{children}</div>;
  const Modal = Object.assign(
    ({ opened, children, title }) =>
      opened ? (
        <div>
          <h2>{title}</h2>
          {children}
        </div>
      ) : null,
    { NativeScrollArea: Wrapper }
  );
  return {
    ActionIcon: ({ children, onClick, disabled, 'aria-label': ariaLabel }) => (
      <button aria-label={ariaLabel} onClick={onClick} disabled={disabled}>
        {children}
      </button>
    ),
    Alert: Wrapper,
    Button: ({ children, onClick, loading, disabled }) => (
      <button onClick={onClick} disabled={loading || disabled}>
        {children}
      </button>
    ),
    Checkbox: ({ checked, onChange, 'aria-label': ariaLabel }) => (
      <input
        type="checkbox"
        aria-label={ariaLabel}
        checked={checked}
        onChange={onChange}
      />
    ),
    Group: Wrapper,
    Modal,
    NumberInput: ({ label, value, onChange, onBlur, onKeyDown, disabled }) => (
      <label>
        {label}
        <input
          type="number"
          aria-label={label}
          value={value}
          disabled={disabled}
          onChange={(event) => onChange(Number(event.target.value))}
          onBlur={onBlur}
          onKeyDown={onKeyDown}
        />
      </label>
    ),
    MultiSelect: ({ label, value = [], onChange, disabled }) => (
      <label>
        {label}
        <select
          multiple
          aria-label={label}
          value={value}
          disabled={disabled}
          onChange={(event) =>
            onChange(
              Array.from(event.target.selectedOptions, (option) => option.value)
            )
          }
        />
      </label>
    ),
    Pagination: ({ value, onChange }) => (
      <button aria-label="Next page" onClick={() => onChange(value + 1)} />
    ),
    ScrollArea: Wrapper,
    SegmentedControl: ({ 'aria-label': ariaLabel, value, onChange, data }) => (
      <select
        aria-label={ariaLabel}
        value={value}
        onChange={(event) => onChange(event.target.value)}
      >
        {data.map((item) => (
          <option key={item.value} value={item.value}>
            {item.label}
          </option>
        ))}
      </select>
    ),
    Select: ({ label, value, onChange, data = [], disabled }) => (
      <label>
        {label}
        <select
          aria-label={label}
          value={value || ''}
          disabled={disabled}
          onChange={(event) => onChange(event.target.value)}
        >
          <option value="" />
          {data.map((item) => (
            <option
              key={typeof item === 'string' ? item : item.value}
              value={typeof item === 'string' ? item : item.value}
            >
              {typeof item === 'string' ? item : item.label}
            </option>
          ))}
        </select>
      </label>
    ),
    Stack: Wrapper,
    Table: Wrapper,
    TableTbody: Wrapper,
    TableTd: Wrapper,
    TableTh: Wrapper,
    TableThead: Wrapper,
    TableTr: Wrapper,
    Text: Wrapper,
    TextInput: ({ label, value, onChange, type = 'text' }) => (
      <label>
        {label}
        <input
          type={type}
          aria-label={label}
          value={value}
          onChange={onChange}
        />
      </label>
    ),
  };
});

import API from '../../api';
import VODSourceManagerModal from '../VODSourceManagerModal';

const playback = {
  id: 1,
  started_at: '2026-08-23T12:00:00Z',
  content_name: 'Avatar - S01E01',
  account_name: 'provider-a',
  category_name: 'GERMANY KIDS',
  username: 'Maria',
  status: 'completed',
  mode: 'proxy',
  watched_seconds: 125,
  bytes_sent: 1048576,
  content_type: 'episode',
  relation_id: 21,
  detail_content_type: 'series',
  detail_canonical_id: 17,
  detail_relation_id: 21,
  source_effective_metadata: {
    values: {
      resolution: '1080p',
      audio_languages: ['ger'],
      subtitle_languages: ['eng'],
    },
    provenance: {
      resolution: 'observed',
      audio_languages: 'manual',
      subtitle_languages: 'observed',
    },
  },
};

describe('VODSourceManagerModal playback history', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    API.getVODPlaybackSessions.mockResolvedValue({ results: [playback] });
    API.getVODPlaybackFacets.mockResolvedValue({
      users: [{ value: '3', label: 'Maria' }],
      accounts: [{ value: '4', label: 'provider-a' }],
      categories: [
        {
          value: '5',
          label: 'GERMANY KIDS',
          m3u_account: 4,
        },
      ],
      retention_days: 0,
      can_manage_history: true,
    });
    API.getVODPlaybackStats.mockResolvedValue({
      sessions: 1,
      failover_sessions: 0,
      bytes_sent: 1048576,
      popular: [],
    });
    API.updateVODPlaybackRetention.mockResolvedValue({ retention_days: 30 });
    API.deleteVODPlaybackSessions.mockResolvedValue({ deleted_sessions: 1 });
    API.bulkUpdateVODPlaybackMetadata.mockResolvedValue({
      selected_sessions: 1,
      updated_sources: 1,
    });
    API.updateVODRelationManualMetadata.mockResolvedValue({});
  });

  it('shows the exact source, transfer data and technical metadata', async () => {
    render(<VODSourceManagerModal opened onClose={vi.fn()} />);
    expect(
      await screen.findByText('provider-a — GERMANY KIDS')
    ).toBeInTheDocument();
    expect(screen.getByText('1.0 MB')).toBeInTheDocument();
    expect(
      screen.getByText('1080p • Audio: ger • Subs: eng')
    ).toBeInTheDocument();
    expect(screen.getByText('2m 5s')).toBeInTheDocument();
    expect(
      screen.getByText(
        new Date(playback.started_at).toLocaleDateString(undefined, {
          weekday: 'short',
          year: 'numeric',
          month: 'short',
          day: 'numeric',
        })
      )
    ).toBeInTheDocument();
  });

  it('opens the canonical VOD detail view from playback history', async () => {
    const onClose = vi.fn();
    const onOpenContent = vi.fn();
    render(
      <VODSourceManagerModal
        opened
        onClose={onClose}
        onOpenContent={onOpenContent}
      />
    );
    await screen.findByText('Avatar - S01E01');
    fireEvent.click(screen.getByLabelText('Open details for Avatar - S01E01'));

    expect(onClose).toHaveBeenCalled();
    expect(onOpenContent).toHaveBeenCalledWith({
      id: 17,
      content_type: 'series',
      contentType: 'series',
      relation_id: 21,
      name: 'Avatar - S01E01',
    });
  });

  it('offers movies and series without a separate episode filter', async () => {
    render(<VODSourceManagerModal opened onClose={vi.fn()} />);
    await screen.findByText('Avatar - S01E01');
    expect(screen.getByLabelText('Type')).toHaveTextContent('Movies');
    expect(screen.getByLabelText('Type')).toHaveTextContent('Series');
    expect(screen.getByLabelText('Type')).not.toHaveTextContent('Episode');
  });

  it('saves manual metadata as locked source data', async () => {
    render(<VODSourceManagerModal opened onClose={vi.fn()} />);
    await screen.findByText('Avatar - S01E01');
    fireEvent.click(screen.getByLabelText('Edit source metadata'));
    fireEvent.change(screen.getByLabelText('DUB languages'), {
      target: { value: 'ger,eng' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Save and lock' }));
    await waitFor(() =>
      expect(API.updateVODRelationManualMetadata).toHaveBeenCalledWith(
        'episode',
        21,
        {
          audio_languages: ['ger', 'eng'],
          subtitle_languages: ['eng'],
          resolution: '1080p',
        },
        ['audio_languages', 'subtitle_languages', 'resolution']
      )
    );
  });

  it('updates automatic history retention in days', async () => {
    render(<VODSourceManagerModal opened onClose={vi.fn()} />);
    await screen.findByText('Avatar - S01E01');
    fireEvent.change(screen.getByLabelText('Auto-delete (days)'), {
      target: { value: '30' },
    });
    fireEvent.blur(screen.getByLabelText('Auto-delete (days)'));

    await waitFor(() =>
      expect(API.updateVODPlaybackRetention).toHaveBeenCalledWith(30)
    );
  });

  it('sends user and date filters to the paginated server endpoint', async () => {
    render(<VODSourceManagerModal opened onClose={vi.fn()} />);
    await screen.findByText('Avatar - S01E01');

    fireEvent.change(screen.getByLabelText('User'), {
      target: { value: '3' },
    });
    fireEvent.change(screen.getByLabelText('Started from'), {
      target: { value: '2026-08-23' },
    });

    await waitFor(() =>
      expect(API.getVODPlaybackSessions).toHaveBeenLastCalledWith(
        expect.objectContaining({
          user: '3',
          started_after: new Date('2026-08-23T00:00:00').toISOString(),
          page: 1,
          page_size: 50,
        })
      )
    );
  });

  it('deletes all history matching the current server filters', async () => {
    render(<VODSourceManagerModal opened onClose={vi.fn()} />);
    await screen.findByText('Avatar - S01E01');
    fireEvent.click(screen.getByLabelText('Select all matching history'));
    fireEvent.click(
      await screen.findByRole('button', { name: 'Delete selected' })
    );
    fireEvent.click(screen.getByRole('button', { name: 'Confirm delete' }));

    await waitFor(() =>
      expect(API.deleteVODPlaybackSessions).toHaveBeenCalledWith({
        ids: [],
        select_all: true,
        exclude_ids: [],
        filters: {},
      })
    );
  });

  it('mass edits each distinct source represented by selected history rows', async () => {
    render(<VODSourceManagerModal opened onClose={vi.fn()} />);
    await screen.findByText('Avatar - S01E01');
    fireEvent.click(screen.getByLabelText('Select Avatar - S01E01'));
    fireEvent.click(screen.getByRole('button', { name: 'Edit selected (1)' }));
    fireEvent.change(screen.getByLabelText('Resolution update mode'), {
      target: { value: 'set' },
    });
    fireEvent.change(screen.getByLabelText('Resolution'), {
      target: { value: '1080p' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Apply metadata' }));

    await waitFor(() =>
      expect(API.bulkUpdateVODPlaybackMetadata).toHaveBeenCalledWith(
        expect.objectContaining({ ids: [1] }),
        { resolution: { mode: 'set', value: '1080p' } }
      )
    );
  });
});
