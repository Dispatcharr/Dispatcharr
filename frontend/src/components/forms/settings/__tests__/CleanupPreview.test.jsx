import { MantineProvider } from '@mantine/core';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import api from '../../../../api';
import CleanupPreview from '../CleanupPreview.jsx';

vi.mock('../../../../api', () => ({ default: { vodLibraryAction: vi.fn() } }));
vi.mock('../../../LibraryPreviewModal.jsx', () => ({
  default: ({ item, onClose }) => (
    <div role="dialog" aria-label={`Title preview ${item.content_id}`}>
      <button onClick={onClose}>Close preview</button>
    </div>
  ),
}));
const rules = {
  title_rules: [{ value: 'NF - ', enabled: true }],
  year_rules: [{ value: '(YYYY)', position: 'end', enabled: true }],
};
const response = {
  count: 1,
  page: 1,
  page_size: 25,
  results: [
    {
      id: 1,
      content_type: 'movie',
      before: 'NF - Film (2020)',
      after: 'Film',
      year: 2020,
      locked: true,
    },
  ],
};
const ui = (settings = rules) => (
  <MantineProvider env="test">
    <CleanupPreview settings={settings} />
  </MantineProvider>
);
const search = () => {
  fireEvent.change(screen.getByLabelText('Preview titles containing'), {
    target: { value: 'Film' },
  });
  fireEvent.click(screen.getByRole('button', { name: 'Search', exact: true }));
};

beforeEach(() => {
  vi.clearAllMocks();
  api.vodLibraryAction.mockResolvedValue(response);
});

describe('Settings cleanup preview', () => {
  it('constrains long titles and uses the shared first/last page controls', async () => {
    const longTitle = 'Long.Provider.Title.'.repeat(30);
    api.vodLibraryAction.mockResolvedValue({
      ...response,
      count: 438,
      results: [
        { ...response.results[0], before: longTitle, after: longTitle },
      ],
    });
    render(ui());
    search();
    await screen.findByRole('table', { name: 'Cleanup preview' });
    expect(screen.getByRole('table', { name: 'Cleanup preview' })).toHaveStyle({
      '--table-layout': 'fixed',
    });
    const titles = screen.getAllByText(longTitle, { exact: true });
    expect(titles).toHaveLength(2);
    titles.forEach((title) => expect(title).toHaveAttribute('data-truncate'));
    expect(screen.getByRole('button', { name: 'First page' })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'Last page' }));
    await waitFor(() =>
      expect(api.vodLibraryAction).toHaveBeenLastCalledWith(
        'cleanup-preview',
        expect.objectContaining({ page: 18, page_size: 25 })
      )
    );
  });
  it('only requests a read-only preview with draft rules and shows protected titles', async () => {
    render(ui());
    expect(api.vodLibraryAction).not.toHaveBeenCalled();
    expect(
      screen.getByRole('button', { name: 'Search', exact: true })
    ).toBeDisabled();
    search();
    expect(
      await screen.findByRole('table', { name: 'Cleanup preview' })
    ).toBeInTheDocument();
    expect(api.vodLibraryAction).toHaveBeenCalledExactlyOnceWith(
      'cleanup-preview',
      {
        scope: 'catalog',
        search: 'Film',
        missing_tmdb_only: false,
        page: 1,
        page_size: 25,
        ...rules,
      }
    );
    expect(screen.getByLabelText('Metadata locked')).toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: /Apply|Save/ })
    ).not.toBeInTheDocument();
  });

  it('matches the Library selection preview and opens the title preview', async () => {
    const item = {
      content_type: 'movie',
      content_id: 1,
      name: 'Film',
      provider_name: 'NF - Film (2020)',
      tmdb_id: '42',
    };
    api.vodLibraryAction.mockResolvedValue({
      ...response,
      results: [{ ...response.results[0], item }],
    });
    render(ui());
    search();
    await screen.findByRole('table', { name: 'Cleanup preview' });
    expect(
      screen.getAllByRole('columnheader').map((cell) => cell.textContent)
    ).toEqual([
      'Provider title',
      'Clean title',
      'Year',
      'TMDB result',
      'Details',
    ]);
    expect(screen.getByText('TMDB 42')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Preview Film' }));
    expect(
      screen.getByRole('dialog', { name: 'Title preview 1' })
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Close preview' }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('supports Without TMDB ID and bounded pagination', async () => {
    api.vodLibraryAction.mockResolvedValue({ ...response, count: 26 });
    render(ui());
    fireEvent.click(screen.getByRole('button', { name: 'Without TMDB ID' }));
    await screen.findByText('1–25 of 26');
    fireEvent.click(screen.getByRole('button', { name: '2', exact: true }));
    await waitFor(() =>
      expect(api.vodLibraryAction).toHaveBeenLastCalledWith(
        'cleanup-preview',
        expect.objectContaining({
          missing_tmdb_only: true,
          search: '',
          page: 2,
        })
      )
    );
  });

  it('discards stale responses when rules change and requests the new draft', async () => {
    let resolve;
    api.vodLibraryAction.mockImplementationOnce(
      () =>
        new Promise((done) => {
          resolve = done;
        })
    );
    const view = render(ui());
    search();
    const updated = { ...rules, title_rules: [] };
    view.rerender(ui(updated));
    resolve(response);
    await waitFor(() =>
      expect(screen.queryByRole('table')).not.toBeInTheDocument()
    );
    fireEvent.click(
      screen.getByRole('button', { name: 'Search', exact: true })
    );
    await screen.findByRole('table');
    expect(api.vodLibraryAction).toHaveBeenLastCalledWith(
      'cleanup-preview',
      expect.objectContaining({ title_rules: [] })
    );
  });

  it('shows validation errors without writing and allows retry', async () => {
    api.vodLibraryAction.mockRejectedValueOnce(
      new Error('Invalid year format')
    );
    render(ui());
    search();
    await waitFor(() =>
      expect(
        screen.getByLabelText('Preview titles containing')
      ).toHaveAttribute('aria-invalid', 'true')
    );
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    fireEvent.click(
      screen.getByRole('button', { name: 'Search', exact: true })
    );
    await screen.findByRole('table');
    expect(api.vodLibraryAction).toHaveBeenCalledTimes(2);
  });

  it('clears results when the search changes and shows empty results', async () => {
    api.vodLibraryAction.mockResolvedValue({
      ...response,
      count: 0,
      results: [],
    });
    render(ui());
    search();
    await screen.findByText('No matching titles');
    fireEvent.change(screen.getByLabelText('Preview titles containing'), {
      target: { value: 'Other' },
    });
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
  });
});
