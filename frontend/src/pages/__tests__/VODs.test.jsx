import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MantineProvider } from '@mantine/core';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import VODsPage from '../VODs';
import api from '../../api';
import { showNotification } from '../../utils/notificationUtils.js';
vi.mock('../../utils/notificationUtils.js', () => ({
  showNotification: vi.fn(),
}));
import useLibraryStore from '../../store/useLibraryStore';

const auth = vi.hoisted(() => ({
  user: { user_level: 10, custom_properties: {} },
}));
vi.mock('../../store/auth', () => ({ default: (selector) => selector(auth) }));
vi.mock('../../api', () => ({
  default: {
    getVODLibrary: vi.fn(),
    getVODLibraryOptions: vi.fn(),
    getVODLibraryState: vi.fn(),
  },
}));
vi.mock('../../components/LibraryPreviewModal', () => ({
  default: ({ item, onClose, accountId }) => (
    <div
      role="dialog"
      aria-label={
        item.content_type === 'movie' ? 'Movie preview' : 'Series preview'
      }
    >
      <span>{item.name}</span>
      <span data-testid="movie-id">{item.content_id}</span>
      <span data-testid="source-id">{item.source_id}</span>
      <span data-testid="preview-account">{accountId}</span>
      <button onClick={onClose}>Close preview</button>
    </div>
  ),
}));

const initialFilters = { ...useLibraryStore.getState().filters };
const movie = {
  key: 'movie:1',
  id: 1,
  content_id: 1,
  content_type: 'movie',
  name: 'Film',
  source_count: 2,
  metadata_summary: {},
  metadata_status: '',
  duration_secs: 3600,
  poster_url: '',
};
const series = {
  ...movie,
  key: 'series:2',
  id: 2,
  content_id: 2,
  content_type: 'series',
  name: 'Series',
  episode_count: 3,
};
const renderPage = () =>
  render(
    <MantineProvider env="test">
      <MemoryRouter initialEntries={['/vods']}>
        <Routes>
          <Route path="/vods" element={<VODsPage />} />
          <Route path="/channels" element={<div>Channels destination</div>} />
        </Routes>
      </MemoryRouter>
    </MantineProvider>
  );

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  auth.user = { user_level: 10, custom_properties: {} };
  useLibraryStore.setState({
    filters: { ...initialFilters },
    page: 1,
    pageSize: 24,
    rows: [],
    count: 0,
    loading: false,
    error: null,
    options: { accounts: [], categories: [] },
    optionsError: null,
    job: { status: 'idle', progress: {} },
  });
  api.getVODLibrary.mockResolvedValue({ results: [movie, series], count: 2 });
  api.getVODLibraryOptions.mockResolvedValue({
    accounts: [{ id: 3, name: 'Provider' }],
    categories: [{ id: 4, name: 'English', category_type: 'movie' }],
    audio_languages: ['eng'],
    subtitle_languages: [],
    resolution: ['1080p'],
    video_features: [],
    container_extensions: [],
    totals: { movie: 1234, series: 1 },
  });
  api.getVODLibraryState.mockResolvedValue({ status: 'idle', progress: {} });
});

describe('Library page and shared view pipeline', () => {
  it('shows the visible movie and series totals next to the title', async () => {
    renderPage();
    expect(await screen.findByLabelText('Library titles')).toHaveTextContent(
      '1,234 movies · 1 series'
    );
  });
  it('limits selection to the table and clears it when switching to posters', async () => {
    renderPage();
    await screen.findByRole('button', { name: 'Preview Film' });
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: /^Edit/ })
    ).not.toBeInTheDocument();
    const requests = api.getVODLibrary.mock.calls.length;
    fireEvent.click(screen.getByRole('radio', { name: 'List', exact: true }));
    expect(
      screen.getByRole('columnheader', { name: 'Sources' })
    ).toBeInTheDocument();
    expect(
      screen.getByRole('radio', { name: 'Titles', exact: true })
    ).toBeChecked();
    expect(screen.getByRole('button', { name: 'Edit (0)' })).toBeDisabled();
    fireEvent.click(screen.getByRole('checkbox', { name: 'Select Film' }));
    expect(screen.getByRole('button', { name: 'Edit (1)' })).toBeEnabled();
    expect(api.getVODLibrary).toHaveBeenCalledTimes(requests);
    expect(localStorage.getItem('vodsViewMode')).toBe('list');
    fireEvent.click(
      screen.getByRole('radio', { name: 'Posters', exact: true })
    );
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: /^Edit/ })
    ).not.toBeInTheDocument();
    expect(api.getVODLibrary).toHaveBeenCalledTimes(requests);
    fireEvent.click(screen.getByRole('radio', { name: 'List', exact: true }));
    expect(
      screen.getByRole('checkbox', { name: 'Select Film' })
    ).not.toBeChecked();
    expect(screen.getByRole('button', { name: 'Edit (0)' })).toBeDisabled();
  });
  it('restores the saved display mode independently from the title representation', async () => {
    localStorage.setItem('vodsViewMode', 'list');
    renderPage();
    await screen.findByRole('columnheader', { name: 'Artwork' });
    expect(
      screen.getByRole('radio', { name: 'List', exact: true })
    ).toBeChecked();
    expect(
      screen.getByRole('radio', { name: 'Titles', exact: true })
    ).toBeChecked();
  });
  it('keeps Sources list-only, opens the exact source and restores the title poster preference', async () => {
    api.getVODLibrary.mockImplementation(async (params) => ({
      results:
        params.get('view') === 'sources'
          ? [
              {
                ...movie,
                key: 'movie:5',
                source_id: 5,
                provider_name: 'Provider Film',
                account: { id: 3, name: 'Provider account' },
                category: { id: 4, name: 'English category' },
              },
            ]
          : [movie],
      count: 1,
    }));
    renderPage();
    await screen.findByRole('button', { name: 'Preview Film' });
    fireEvent.click(
      screen.getByRole('radio', { name: 'Sources', exact: true })
    );
    expect(await screen.findByText('Provider account')).toBeInTheDocument();
    expect(
      screen.queryByRole('radiogroup', { name: 'Library layout' })
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole('columnheader', { name: 'Source', exact: true })
    ).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole('button', { name: 'Preview Provider Film' })
    );
    expect(await screen.findByTestId('source-id')).toHaveTextContent('5');
    expect(screen.getByTestId('movie-id')).toHaveTextContent('1');
    fireEvent.click(screen.getByRole('button', { name: 'Close preview' }));
    fireEvent.click(screen.getByRole('radio', { name: 'Titles', exact: true }));
    expect(
      screen.getByRole('radio', { name: 'Posters', exact: true })
    ).toBeChecked();
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
  });
  it('passes the selected account into the preview as display context', async () => {
    useLibraryStore.setState((state) => ({
      filters: { ...state.filters, account: '3' },
    }));
    renderPage();
    fireEvent.click(
      await screen.findByRole('button', { name: 'Preview Film' })
    );
    expect(await screen.findByTestId('preview-account')).toHaveTextContent('3');
    expect(screen.getByTestId('movie-id')).toHaveTextContent('1');
  });
  it('starts with the existing poster cards and a shared filter toolbar', async () => {
    renderPage();
    await screen.findByRole('button', { name: 'Preview Film' });
    expect(
      screen.getByRole('heading', { name: 'Library' })
    ).toBeInTheDocument();
    expect(
      screen.getByRole('radio', { name: 'Posters', exact: true })
    ).toBeChecked();
    expect(
      screen.getByRole('button', { name: 'Filter library' })
    ).toBeInTheDocument();
    expect(
      api.getVODLibrary.mock.calls.some(
        ([params]) => params.get('view') === 'titles'
      )
    ).toBe(true);
  });
  it.each(['titles', 'sources'])(
    'uses the same endpoint for %s and preserves filters',
    async (view) => {
      renderPage();
      await screen.findByRole('button', { name: 'Preview Film' });
      fireEvent.change(screen.getByRole('textbox', { name: 'Search titles' }), {
        target: { value: 'Film' },
      });
      fireEvent.click(
        screen.getByRole('radio', {
          name: view === 'titles' ? 'Titles' : 'Sources',
          exact: true,
        })
      );
      await waitFor(() =>
        expect(
          api.getVODLibrary.mock.calls.some(
            ([params]) =>
              params.get('view') === view && params.get('search') === 'Film'
          )
        ).toBe(true)
      );
      expect(
        screen.getByRole('textbox', { name: 'Search titles' })
      ).toHaveValue('Film');
    }
  );
  it('opens and closes movie and series previews without provider refresh calls', async () => {
    renderPage();
    fireEvent.click(
      await screen.findByRole('button', { name: 'Preview Film' })
    );
    expect(
      await screen.findByRole('dialog', { name: 'Movie preview' })
    ).toBeInTheDocument();
    expect(screen.getByTestId('movie-id')).toHaveTextContent('1');
    fireEvent.click(screen.getByRole('button', { name: 'Close preview' }));
    fireEvent.click(screen.getByRole('button', { name: 'Preview Series' }));
    expect(
      await screen.findByRole('dialog', { name: 'Series preview' })
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Close preview' }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });
  it.each([
    null,
    { user_level: 0, custom_properties: {} },
    {
      user_level: 1,
      custom_properties: {
        vod_movies_enabled: false,
        vod_series_enabled: false,
      },
    },
  ])(
    'redirects users without VOD access before loading data (%j)',
    async (user) => {
      auth.user = user;
      renderPage();
      expect(
        await screen.findByText('Channels destination')
      ).toBeInTheDocument();
      expect(api.getVODLibrary).not.toHaveBeenCalled();
    }
  );
  it('does not expose source management or Library settings to standard users', async () => {
    auth.user = { user_level: 1, custom_properties: {} };
    renderPage();
    await screen.findByRole('button', { name: 'Preview Film' });
    expect(
      screen.queryByRole('radio', { name: 'Sources', exact: true })
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: 'Library settings' })
    ).not.toBeInTheDocument();
  });
  it.each([
    ['movie', 'vod_series_enabled'],
    ['series', 'vod_movies_enabled'],
  ])('locks the first request to the allowed %s type', async (type, flag) => {
    auth.user = { user_level: 1, custom_properties: { [flag]: false } };
    renderPage();
    await screen.findByRole('button', { name: 'Preview Film' });
    expect(
      api.getVODLibrary.mock.calls.every(
        ([params]) => params.get('type') === type
      )
    ).toBe(true);
  });
  it('hydrates page size before the first request and ignores invalid stored sizes', async () => {
    localStorage.setItem('vodsPageSize', '48');
    renderPage();
    await screen.findByRole('button', { name: 'Preview Film' });
    expect(api.getVODLibrary.mock.calls[0][0].get('page_size')).toBe('48');
  });
  it('shows an empty state only after the request completes', async () => {
    let resolve;
    api.getVODLibrary.mockImplementation(
      () =>
        new Promise((done) => {
          resolve = done;
        })
    );
    renderPage();
    await waitFor(() => expect(api.getVODLibrary).toHaveBeenCalled());
    expect(
      screen.queryByText('No titles match these filters.')
    ).not.toBeInTheDocument();
    resolve({ results: [], count: 0 });
    expect(
      await screen.findByText('No titles match these filters.')
    ).toBeInTheDocument();
  });
  it('keeps successful titles visible when option loading fails', async () => {
    api.getVODLibraryOptions.mockRejectedValue(
      new Error('Options unavailable')
    );
    renderPage();
    expect(
      await screen.findByRole('button', { name: 'Preview Film' })
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(showNotification).toHaveBeenCalledWith(
        expect.objectContaining({
          message: 'Options unavailable',
          color: 'red',
        })
      )
    );
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });
  it('supports retry after a content request fails', async () => {
    api.getVODLibrary
      .mockRejectedValueOnce(new Error('Content unavailable'))
      .mockResolvedValue({ results: [movie], count: 1 });
    renderPage();
    await waitFor(() =>
      expect(showNotification).toHaveBeenCalledWith(
        expect.objectContaining({
          message: 'Content unavailable',
          color: 'red',
        })
      )
    );
    fireEvent.click(screen.getByRole('button', { name: 'Retry library' }));
    expect(
      await screen.findByRole('button', { name: 'Preview Film' })
    ).toBeInTheDocument();
  });
  it('applies technical filters in the poster view without changing any data', async () => {
    renderPage();
    await screen.findByRole('button', { name: 'Preview Film' });
    fireEvent.click(screen.getByRole('button', { name: 'Filter library' }));
    fireEvent.click(screen.getByRole('textbox', { name: 'DUB', exact: true }));
    fireEvent.click(
      await screen.findByRole('option', { name: 'English (eng)', exact: true })
    );
    await waitFor(() =>
      expect(
        api.getVODLibrary.mock.calls.some(
          ([params]) =>
            params.get('view') === 'titles' &&
            params.get('audio_language') === 'eng'
        )
      ).toBe(true)
    );
  });
});
