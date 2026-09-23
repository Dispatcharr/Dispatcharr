import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../../api', () => ({
  default: {
    getVODMetadataStatus: vi.fn(),
    previewVODMetadataTitles: vi.fn(),
    updateVODMetadataSettings: vi.fn(),
    refreshVODMetadata: vi.fn(),
    lockVODMetadata: vi.fn(),
    resetVODMetadata: vi.fn(),
    applyVODTitleCleanup: vi.fn(),
  },
}));
vi.mock('../../utils/notificationUtils', () => ({
  showNotification: vi.fn(),
}));
vi.mock('../forms/settings/VODMetadataSettingsForm', () => ({
  default: ({ status }) => (
    <div data-testid="tmdb-settings-form">
      TMDB settings {status ? 'loaded' : 'loading'}
    </div>
  ),
}));
vi.mock('../VODModal.jsx', () => ({
  default: ({ vod, opened }) =>
    opened ? <div data-testid="movie-detail">{vod.name}</div> : null,
}));
vi.mock('../SeriesModal.jsx', () => ({
  default: ({ series, opened }) =>
    opened ? <div data-testid="series-detail">{series.name}</div> : null,
}));
vi.mock('lucide-react', () => ({
  Eye: () => null,
  LockKeyhole: () => null,
  LockKeyholeOpen: () => null,
}));
vi.mock('@mantine/core', () => {
  const Wrapper = ({ children }) => <div>{children}</div>;
  const Table = ({ children }) => <table>{children}</table>;
  Table.Thead = ({ children }) => <thead>{children}</thead>;
  Table.Tbody = ({ children }) => <tbody>{children}</tbody>;
  Table.Tr = ({ children }) => <tr>{children}</tr>;
  Table.Th = ({ children }) => <th>{children}</th>;
  Table.Td = ({ children }) => <td>{children}</td>;
  return {
    ActionIcon: ({ children, onClick, 'aria-label': label }) => (
      <button aria-label={label} onClick={onClick}>
        {children}
      </button>
    ),
    Alert: Wrapper,
    Box: Wrapper,
    Divider: () => <hr />,
    Button: ({ children, onClick, disabled, loading }) => (
      <button disabled={disabled || loading} onClick={onClick}>
        {children}
      </button>
    ),
    Checkbox: ({ label, checked, onChange }) => (
      <label>
        <input type="checkbox" checked={checked} onChange={onChange} />
        {label}
      </label>
    ),
    Flex: Wrapper,
    Group: Wrapper,
    Loader: () => <span>Loading</span>,
    Modal: ({ opened, title, children }) =>
      opened ? (
        <div>
          <h2>{title}</h2>
          {children}
        </div>
      ) : null,
    Pagination: ({ value, total, onChange }) => (
      <button onClick={() => onChange(Math.min(value + 1, total))}>
        Page {value} of {total}
      </button>
    ),
    Progress: () => <div data-testid="metadata-progress" />,
    ScrollArea: Wrapper,
    Select: ({ label, data, value, onChange }) => (
      <label>
        {label}
        <select
          aria-label={label}
          value={value}
          onChange={(event) => onChange(event.currentTarget.value)}
        >
          {data.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </label>
    ),
    Stack: Wrapper,
    TagsInput: ({ label, value = [], onChange }) => (
      <label>
        {label}
        <input
          aria-label={label}
          value={value.join(',')}
          onChange={(event) =>
            onChange(event.currentTarget.value.split(',').filter(Boolean))
          }
        />
      </label>
    ),
    Table,
    Text: Wrapper,
    TextInput: ({ label, value, onChange, description, disabled }) => (
      <label>
        {label}
        {description}
        <input
          aria-label={label}
          value={value}
          onChange={onChange}
          disabled={disabled}
        />
      </label>
    ),
    Tooltip: Wrapper,
  };
});

import API from '../../api';
import useWarningsStore from '../../store/warnings';
import { showNotification } from '../../utils/notificationUtils';
import VODMetadataModal from '../VODMetadataModal';

const savedRule = {
  pattern: '4K-D+ -',
  replacement: ' ',
  enabled: true,
};
const savedYearRules = [
  { value: '(YYYY)', position: 'anywhere', enabled: true },
  { value: '[YYYY]', position: 'end', enabled: true },
  { value: '- YYYY', position: 'anywhere', enabled: true },
  { value: 'YYYY', position: 'end', enabled: true },
];
const statusResponse = {
  settings: { title_rules: [savedRule], year_rules: savedYearRules },
};

describe('VODMetadataModal', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useWarningsStore.setState({
      suppressedWarnings: {},
      actionPreferences: {},
    });
    API.getVODMetadataStatus.mockResolvedValue(statusResponse);
    API.previewVODMetadataTitles.mockResolvedValue({
      results: [
        {
          id: 7,
          content_type: 'movie',
          before: '4K-D+ - Bliss (2021)',
          after: '4K-D+ - Bliss',
          changed: true,
          year: 2021,
          tmdb_status: 'ambiguous',
          candidate_count: 2,
          metadata_auto_locked: true,
        },
      ],
      locked_count: 1,
    });
    API.updateVODMetadataSettings.mockResolvedValue(statusResponse);
  });

  it('shows TMDB settings and title cleanup together', async () => {
    render(<VODMetadataModal opened onClose={vi.fn()} />);
    expect(await screen.findByText('TMDB settings loaded')).toBeInTheDocument();
    expect(screen.getByText('TMDB settings')).toBeVisible();
    expect(screen.getByText('Title cleanup')).toBeVisible();
    expect(screen.queryByText('Enrich selected')).not.toBeInTheDocument();
    expect(screen.queryByText('Reload selected')).not.toBeInTheDocument();
  });

  it('shows only TMDB settings on the metadata settings page', async () => {
    render(
      <VODMetadataModal
        opened
        embedded
        settingsSection="metadata"
        onClose={vi.fn()}
      />
    );

    expect(await screen.findByText('TMDB settings loaded')).toBeInTheDocument();
    expect(screen.getByText('TMDB settings')).toBeVisible();
    expect(screen.queryByText('Title cleanup')).not.toBeInTheDocument();
    expect(
      screen.queryByLabelText('Prefixes to remove')
    ).not.toBeInTheDocument();
  });

  it('shows only title cleanup on its own settings page', async () => {
    render(
      <VODMetadataModal
        opened
        embedded
        settingsSection="title-cleanup"
        onClose={vi.fn()}
      />
    );

    expect(await screen.findByLabelText('Prefixes to remove')).toBeVisible();
    expect(screen.getByText('Title cleanup')).toBeVisible();
    expect(screen.queryByTestId('tmdb-settings-form')).not.toBeInTheDocument();
    expect(screen.queryByText('TMDB settings')).not.toBeInTheDocument();
  });

  it('does not render placeholder metadata settings while loading', async () => {
    let resolveStatus;
    API.getVODMetadataStatus.mockReturnValueOnce(
      new Promise((resolve) => {
        resolveStatus = resolve;
      })
    );

    render(<VODMetadataModal opened onClose={vi.fn()} />);

    expect(screen.getByText('TMDB settings loading')).toBeInTheDocument();
    expect(API.getVODMetadataStatus).toHaveBeenCalledTimes(1);
    resolveStatus(statusResponse);
    expect(await screen.findByText('TMDB settings loaded')).toBeInTheDocument();
    expect(API.getVODMetadataStatus).toHaveBeenCalledTimes(1);
  });

  it('treats cleanup values as literal prefixes', async () => {
    render(<VODMetadataModal opened onClose={vi.fn()} />);
    expect(await screen.findByDisplayValue('4K-D+ -')).toBeInTheDocument();
    expect(screen.queryByText(/regex/i)).not.toBeInTheDocument();
  });

  it('previews ordered cleanup rules against stored VOD titles', async () => {
    render(<VODMetadataModal opened onClose={vi.fn()} />);
    await screen.findByDisplayValue('4K-D+ -');
    fireEvent.change(screen.getByLabelText('Preview titles containing'), {
      target: { value: 'Bliss' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Search' }));

    await waitFor(() =>
      expect(API.previewVODMetadataTitles).toHaveBeenCalledWith(
        [
          {
            match_type: 'starts_with',
            value: '4K-D+ -',
            action: 'remove',
            replacement: '',
            enabled: true,
          },
        ],
        savedYearRules,
        null,
        'Bliss',
        { missing_tmdb_only: false, page: 1, page_size: 50 }
      )
    );
    expect(await screen.findByText('4K-D+ - Bliss')).toBeInTheDocument();
  });

  it('shows the extracted year and opens the canonical detail view', async () => {
    render(<VODMetadataModal opened onClose={vi.fn()} />);
    await screen.findByDisplayValue('4K-D+ -');
    fireEvent.change(screen.getByLabelText('Preview titles containing'), {
      target: { value: 'Bliss' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Search' }));

    expect(
      await screen.findByRole('columnheader', { name: 'Details' })
    ).toBeInTheDocument();
    expect(
      screen.queryByRole('columnheader', { name: 'Type' })
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole('columnheader', { name: 'Year' })
    ).toBeInTheDocument();
    expect(screen.getByText('2021')).toBeInTheDocument();
    expect(screen.getByLabelText('Metadata locked')).toBeInTheDocument();

    fireEvent.click(
      screen.getByRole('button', {
        name: 'Open details for 4K-D+ - Bliss',
      })
    );
    expect(await screen.findByTestId('movie-detail')).toHaveTextContent(
      '4K-D+ - Bliss'
    );
  });

  it('requires search text and separately previews every title without a TMDB ID', async () => {
    API.previewVODMetadataTitles.mockResolvedValueOnce({
      results: [
        {
          id: 9,
          content_type: 'movie',
          before: 'D+ - Daredevil (2026)',
          after: 'Daredevil',
          changed: true,
          year: 2026,
        },
      ],
      total: 51,
      page: 1,
      page_size: 50,
    });
    render(<VODMetadataModal opened onClose={vi.fn()} />);
    await screen.findByDisplayValue('4K-D+ -');

    expect(screen.getByRole('button', { name: 'Search' })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'Without TMDB ID' }));

    await waitFor(() =>
      expect(API.previewVODMetadataTitles).toHaveBeenCalledWith(
        expect.any(Array),
        savedYearRules,
        null,
        '',
        { missing_tmdb_only: true, page: 1, page_size: 50 }
      )
    );
    expect(await screen.findByText('1–50 of 51')).toBeInTheDocument();
  });

  it('automatically saves the configured literal prefixes', async () => {
    render(<VODMetadataModal opened onClose={vi.fn()} />);
    await screen.findByDisplayValue('4K-D+ -');
    fireEvent.change(screen.getByLabelText('Prefixes to remove'), {
      target: { value: '4K-D+ -,AMZ - ' },
    });
    await waitFor(() =>
      expect(API.updateVODMetadataSettings).toHaveBeenCalledWith({
        title_rules: [
          {
            match_type: 'starts_with',
            value: '4K-D+ -',
            action: 'remove',
            replacement: '',
            enabled: true,
          },
          {
            match_type: 'starts_with',
            value: 'AMZ -',
            action: 'remove',
            replacement: '',
            enabled: true,
          },
        ],
      })
    );
  });

  it('automatically saves configurable release-year formats', async () => {
    render(<VODMetadataModal opened onClose={vi.fn()} />);
    await screen.findByDisplayValue('(YYYY),[YYYY],- YYYY,YYYY');
    fireEvent.change(screen.getByLabelText('Release-year formats to remove'), {
      target: { value: '(YYYY),[YYYY],YYYY,[YYYY] release' },
    });

    await waitFor(() =>
      expect(API.updateVODMetadataSettings).toHaveBeenCalledWith({
        year_rules: [
          { value: '(YYYY)', position: 'anywhere', enabled: true },
          { value: '[YYYY]', position: 'end', enabled: true },
          { value: 'YYYY', position: 'end', enabled: true },
          { value: '[YYYY] release', position: 'end', enabled: true },
        ],
      })
    );
  });

  it('automatically previews the exact canonical library selection', async () => {
    const selectionContext = {
      count: 2,
      selections: [
        { id: 7, content_type: 'movie' },
        { id: 8, content_type: 'series' },
      ],
      select_all: false,
      exclude_selections: [],
      filters: {},
    };

    render(
      <VODMetadataModal
        opened
        onClose={vi.fn()}
        initialStatus={statusResponse}
        selectionContext={selectionContext}
      />
    );

    await waitFor(() =>
      expect(API.previewVODMetadataTitles).toHaveBeenCalledWith(
        [
          {
            match_type: 'starts_with',
            value: '4K-D+ -',
            action: 'remove',
            replacement: '',
            enabled: true,
          },
        ],
        savedYearRules,
        selectionContext.selections,
        '',
        {}
      )
    );
    expect(
      screen.queryByLabelText('Preview titles containing')
    ).not.toBeInTheDocument();
    expect(screen.queryByText('Exclude from TMDB')).not.toBeInTheDocument();
    expect(screen.queryByText('Allow TMDB lookup')).not.toBeInTheDocument();
    expect(screen.getByText('2 matches · select manually')).toBeVisible();
  });

  it('confirms a forced TMDB refresh for selected canonical titles', async () => {
    API.refreshVODMetadata.mockResolvedValue({ queued: true });
    API.previewVODMetadataTitles.mockResolvedValueOnce({
      results: [
        {
          id: 7,
          content_type: 'movie',
          before: 'Bliss',
          after: 'Bliss',
          metadata_auto_locked: false,
        },
      ],
      locked_count: 0,
    });
    const selectionContext = {
      count: 1,
      selections: [{ id: 7, content_type: 'movie' }],
      select_all: false,
      exclude_selections: [],
      filters: {},
    };
    render(
      <VODMetadataModal
        opened
        onClose={vi.fn()}
        initialStatus={statusResponse}
        selectionContext={selectionContext}
      />
    );

    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: 'Get TMDB data' })
      ).not.toBeDisabled()
    );
    fireEvent.click(screen.getByRole('button', { name: 'Get TMDB data' }));
    expect(
      screen.getByText('Request TMDB data for the selected titles?')
    ).toBeVisible();
    expect(screen.getByLabelText("Don't ask me again")).toBeVisible();
    fireEvent.click(
      screen.getAllByRole('button', { name: 'Get TMDB data' }).at(-1)
    );

    await waitFor(() =>
      expect(API.refreshVODMetadata).toHaveBeenCalledWith([], {
        ...selectionContext,
        force: true,
      })
    );
  });

  it('shows an immediate notification instead of opening actions for locked titles', async () => {
    const selectionContext = {
      count: 1,
      selections: [{ id: 7, content_type: 'movie' }],
      select_all: false,
      exclude_selections: [],
      filters: {},
    };
    render(
      <VODMetadataModal
        opened
        onClose={vi.fn()}
        initialStatus={statusResponse}
        selectionContext={selectionContext}
      />
    );

    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: 'Get TMDB data' })
      ).not.toBeDisabled()
    );
    fireEvent.click(screen.getByRole('button', { name: 'Apply cleanup' }));
    fireEvent.click(screen.getByRole('button', { name: 'Get TMDB data' }));
    fireEvent.click(screen.getByRole('button', { name: 'Reset to provider' }));

    expect(showNotification).toHaveBeenCalledTimes(3);
    expect(showNotification).toHaveBeenLastCalledWith(
      expect.objectContaining({
        title: 'Selected title is locked',
        color: 'red',
      })
    );
    expect(
      screen.queryByText('Request TMDB data for the selected titles?')
    ).not.toBeInTheDocument();
    expect(API.applyVODTitleCleanup).not.toHaveBeenCalled();
    expect(API.refreshVODMetadata).not.toHaveBeenCalled();
    expect(API.resetVODMetadata).not.toHaveBeenCalled();
  });

  it('remembers TMDB confirmation while keeping reset confirmation separate', async () => {
    API.previewVODMetadataTitles.mockResolvedValue({
      results: [
        {
          id: 7,
          content_type: 'movie',
          before: 'Bliss',
          after: 'Bliss',
          metadata_auto_locked: false,
        },
      ],
      locked_count: 0,
    });
    API.refreshVODMetadata.mockResolvedValue({ queued: true });
    const selectionContext = {
      count: 1,
      selections: [{ id: 7, content_type: 'movie' }],
      select_all: false,
      exclude_selections: [],
      filters: {},
    };
    render(
      <VODMetadataModal
        opened
        onClose={vi.fn()}
        initialStatus={statusResponse}
        selectionContext={selectionContext}
      />
    );

    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: 'Get TMDB data' })
      ).not.toBeDisabled()
    );
    fireEvent.click(screen.getByRole('button', { name: 'Get TMDB data' }));
    fireEvent.click(screen.getByLabelText("Don't ask me again"));
    fireEvent.click(
      screen.getAllByRole('button', { name: 'Get TMDB data' }).at(-1)
    );
    await waitFor(() =>
      expect(API.refreshVODMetadata).toHaveBeenCalledTimes(1)
    );

    fireEvent.click(screen.getByRole('button', { name: 'Get TMDB data' }));
    await waitFor(() =>
      expect(API.refreshVODMetadata).toHaveBeenCalledTimes(2)
    );
    expect(
      screen.queryByText('Request TMDB data for the selected titles?')
    ).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Reset to provider' }));
    expect(
      screen.getByText('Reset canonical metadata to provider data?')
    ).toBeVisible();
    expect(screen.getByLabelText("Don't ask me again")).toBeVisible();
  });

  it('uses one button to toggle the selection metadata lock', async () => {
    API.lockVODMetadata.mockResolvedValue({
      action: 'locked',
      locked: 1,
    });
    const selectionContext = {
      count: 1,
      selections: [{ id: 7, content_type: 'movie' }],
      select_all: false,
      exclude_selections: [],
      filters: {},
    };
    render(
      <VODMetadataModal
        opened
        onClose={vi.fn()}
        initialStatus={statusResponse}
        selectionContext={selectionContext}
      />
    );

    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: 'Lock / Unlock' })
      ).not.toBeDisabled()
    );
    fireEvent.click(screen.getByRole('button', { name: 'Lock / Unlock' }));

    await waitFor(() =>
      expect(API.lockVODMetadata).toHaveBeenCalledWith(
        selectionContext.selections,
        {
          select_all: false,
          exclude_selections: [],
          filters: {},
          toggle: true,
        }
      )
    );
  });
});
