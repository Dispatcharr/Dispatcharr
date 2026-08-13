import { MantineProvider } from '@mantine/core';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import API from '../../api';
import {
  ExportCard,
  ExportSelectionEditor,
  SourceCard,
  SourceEditor,
} from '../MediaLibrary';

const source = {
  id: 20,
  name: 'Emby',
  provider_type: 'emby',
  base_url: 'https://emby.example.com',
  enabled: true,
  include_libraries: ['movies', 'shows'],
  last_synced_at: '2026-08-01T21:59:25Z',
  sync_interval: 0,
};

const latestRun = {
  status: 'completed',
  processed_items: 9498,
  created_items: 7806,
  updated_items: 11,
  removed_items: 4,
  skipped_items: 9,
  ambiguous_items: 2,
};

const handlers = {
  onToggle: vi.fn(),
  onTest: vi.fn(),
  onSync: vi.fn(),
  onViewScan: vi.fn(),
  onEdit: vi.fn(),
  onDelete: vi.fn(),
};

describe('Media Library source card', () => {
  it('keeps status, scan metrics, and actions in a consistent order', async () => {
    const user = userEvent.setup();
    render(
      <MantineProvider>
        <SourceCard
          source={source}
          latestRun={latestRun}
          busy={false}
          {...handlers}
        />
      </MantineProvider>
    );

    expect(screen.getByRole('switch', { name: 'Enabled' })).toBeChecked();

    const summary = screen.getByTestId('source-scan-summary');
    const summaryText = summary.textContent;
    const labels = [
      'Processed',
      'Created',
      'Updated',
      'Stale relations',
      'Skipped',
      'Ambiguous',
    ];

    expect(within(summary).getByText('9,498')).toBeInTheDocument();
    expect(
      within(summary).queryByText('What does ambiguous mean?')
    ).not.toBeInTheDocument();
    labels.slice(1).forEach((label, index) => {
      expect(summaryText.indexOf(labels[index])).toBeLessThan(
        summaryText.indexOf(label)
      );
    });

    const actions = within(screen.getByTestId('source-action-bar'))
      .getAllByRole('button')
      .map((button) => button.textContent.trim());
    expect(actions).toEqual(['Test', 'Sync', 'View Scan', 'Edit', 'Delete']);
    expect(screen.getByTestId('source-actions-row')).toHaveStyle({
      display: 'grid',
      gridTemplateColumns: '0.9fr 0.95fr 1.3fr 0.75fr 0.9fr',
      width: '100%',
    });

    await user.hover(within(summary).getByText('Ambiguous'));
    expect(
      await screen.findByText(/multiple plausible records or conflicting/i)
    ).toBeInTheDocument();
  });

  it('keeps the built-in DVR source syncable but not editable or deletable', () => {
    render(
      <MantineProvider>
        <SourceCard
          source={{
            ...source,
            id: 21,
            name: 'DVR',
            provider_type: 'dvr',
            library_path: '/data/recordings',
            include_libraries: [],
          }}
          latestRun={null}
          busy={false}
          {...handlers}
        />
      </MantineProvider>
    );

    expect(screen.getByLabelText('DVR recordings')).toBeInTheDocument();
    expect(screen.getByText('/data/recordings')).toBeInTheDocument();
    expect(screen.getByRole('switch', { name: 'Enabled' })).toBeChecked();
    expect(screen.getByRole('button', { name: 'Sync' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Edit' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Delete' })).not.toBeInTheDocument();
    expect(screen.getByTestId('source-actions-row')).toHaveStyle({
      gridTemplateColumns: '0.9fr 0.95fr 1.3fr',
    });
  });
});

describe('Media Library source editor', () => {
  it('defaults VOD priority to 10000 and saves an administrator override', async () => {
    const user = userEvent.setup();
    const saveSource = vi
      .spyOn(API, 'saveMediaLibrarySource')
      .mockResolvedValue({ id: 1 });

    render(
      <MantineProvider>
        <SourceEditor
          opened
          source={null}
          tmdbSettings={{ tmdb_configured: true }}
          onClose={vi.fn()}
          onSaved={vi.fn()}
        />
      </MantineProvider>
    );

    const priority = screen.getByLabelText('VOD priority');
    expect(priority).toHaveValue('10000');
    await user.clear(priority);
    await user.type(priority, '25000');
    await user.click(screen.getByRole('button', { name: 'Save source' }));

    await waitFor(() =>
      expect(saveSource).toHaveBeenCalledWith(
        expect.objectContaining({ vod_priority: 25000 })
      )
    );
  });
});

describe('Media Library export card', () => {
  it('uses the structured integration layout for export status and actions', async () => {
    const user = userEvent.setup();
    const onToggle = vi.fn();
    render(
      <MantineProvider>
        <ExportCard
          target={{
            id: 9,
            name: 'Media Library',
            enabled: true,
            output_root: '/media/STRM',
            auto_export_on_vod_change: true,
            last_exported_at: '2026-08-03T13:42:33Z',
            last_export_status: 'success',
            last_export_message: '26,228 STRM and 26,228 NFO files written.',
            last_export_summary: {
              movies_written: 20,
              series_written: 2,
              episodes_written: 8,
              strm_files_written: 28,
              nfo_files_written: 30,
            },
          }}
          busy={false}
          onToggle={onToggle}
          onSync={vi.fn()}
          onEdit={vi.fn()}
          onDelete={vi.fn()}
        />
      </MantineProvider>
    );

    expect(screen.getByLabelText('STRM/NFO export')).toBeInTheDocument();
    expect(screen.getByText('STRM/NFO export')).toBeInTheDocument();
    expect(screen.getByText('/media/STRM')).toBeInTheDocument();
    expect(screen.getByText('Media items')).toBeInTheDocument();
    expect(screen.getByText('STRM files')).toBeInTheDocument();
    expect(screen.getByText('NFO files')).toBeInTheDocument();
    expect(screen.queryByText('EXPORT')).not.toBeInTheDocument();

    const actions = within(screen.getByTestId('export-actions-row'))
      .getAllByRole('button')
      .map((button) => button.textContent.trim());
    expect(actions).toEqual(['Sync', 'Edit', 'Delete']);

    await user.click(screen.getByRole('switch', { name: 'Enabled' }));
    expect(onToggle).toHaveBeenCalledWith(false);
  });
});

describe('Media Library export selection', () => {
  it('supports individual movie selection and omits select-all for TV series', async () => {
    const user = userEvent.setup();
    vi.spyOn(API, 'getMediaLibraryExportSelectionOptions').mockResolvedValue({
      providers: [{ value: '7', label: 'Provider One' }],
      movie_categories: [{ value: '11', label: 'Action' }],
      series_categories: [{ value: '12', label: 'Drama' }],
    });
    vi.spyOn(API, 'getMediaLibraryExportCatalog').mockImplementation(
      (_id, params) =>
        Promise.resolve({
          results:
            params.content_type === 'movie'
              ? [
                  {
                    id: 41,
                    name: 'Movie One',
                    year: 2024,
                    selected: false,
                    providers: [[7, 'Provider One']],
                    categories: [[11, 'Action']],
                  },
                ]
              : [
                  {
                    id: 51,
                    name: 'Series One',
                    year: 2023,
                    selected: false,
                    providers: [[7, 'Provider One']],
                    categories: [[12, 'Drama']],
                  },
                ],
          count: 1,
          pages: 1,
          selected_count: 0,
        })
    );
    const updateSelection = vi
      .spyOn(API, 'updateMediaLibraryExportSelection')
      .mockResolvedValue({ selected_count: 1, changed: 1 });
    const buildExport = vi
      .spyOn(API, 'buildMediaLibraryExport')
      .mockResolvedValue({ id: 81, status: 'queued' });
    const onClose = vi.fn();

    render(
      <MantineProvider>
        <ExportSelectionEditor
          opened
          target={{
            id: 9,
            name: 'Jellyfin Library',
            enabled: true,
            selected_movie_count: 0,
            selected_series_count: 0,
          }}
          onClose={onClose}
        />
      </MantineProvider>
    );

    expect(await screen.findByText('Movie One')).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: 'Select all movies' })
    ).toBeInTheDocument();

    await user.click(screen.getByRole('textbox', { name: 'Provider' }));
    await user.click(
      await screen.findByRole('option', { name: 'Provider One', hidden: true })
    );
    await waitFor(() =>
      expect(API.getMediaLibraryExportCatalog).toHaveBeenLastCalledWith(
        9,
        expect.objectContaining({ provider: '7' })
      )
    );

    await user.click(screen.getByRole('textbox', { name: 'Category' }));
    await user.click(
      await screen.findByRole('option', { name: 'Action', hidden: true })
    );
    await waitFor(() =>
      expect(API.getMediaLibraryExportCatalog).toHaveBeenLastCalledWith(
        9,
        expect.objectContaining({ provider: '7', category: '11' })
      )
    );

    await user.click(screen.getByRole('checkbox', { name: 'Export Movie One' }));
    expect(updateSelection).toHaveBeenCalledWith(9, {
      content_type: 'movie',
      operation: 'select',
      ids: [41],
    });

    await user.click(screen.getByRole('tab', { name: /TV Series/ }));
    expect(
      await screen.findByText(/could trigger provider rate limits or a ban/i)
    ).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText('Series One')).toBeInTheDocument());
    expect(
      screen.queryByRole('button', { name: 'Select all movies' })
    ).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Apply and build' }));
    expect(buildExport).toHaveBeenCalledWith(9);
    expect(onClose).toHaveBeenCalledOnce();
  });
});
