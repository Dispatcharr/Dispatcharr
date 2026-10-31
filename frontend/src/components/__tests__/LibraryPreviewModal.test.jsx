import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import { MantineProvider } from '@mantine/core';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import api from '../../api';
import { showNotification } from '../../utils/notificationUtils.js';
vi.mock('../../utils/notificationUtils.js', () => ({
  showNotification: vi.fn(),
}));
import LibraryPreviewModal from '../LibraryPreviewModal.jsx';

const state = vi.hoisted(() => ({
  user: { user_level: 10 },
  accessToken: 'test-token',
  showVideo: vi.fn(),
  fetchContent: vi.fn(),
  copy: vi.fn(),
}));
vi.mock('../../store/auth', () => ({
  default: Object.assign((selector) => selector(state), {
    getState: () => state,
  }),
}));
vi.mock('../../store/settings', () => ({
  default: (selector) => selector({ environment: { env_mode: 'production' } }),
}));
vi.mock('../../store/useVideoStore', () => ({
  default: (selector) => selector(state),
}));
vi.mock('../../store/useLibraryStore', () => ({
  default: { getState: () => state },
}));
vi.mock('../../api', () => ({
  default: {
    getVODLibraryDetails: vi.fn(),
    getVODCanonicalTargets: vi.fn(),
    getMovieProviderInfo: vi.fn(),
    getSeriesInfo: vi.fn(),
    vodLibraryAction: vi.fn(),
  },
}));
vi.mock('../../utils', async (original) => ({
  ...(await original()),
  copyToClipboard: (...args) => state.copy(...args),
}));

const canonical = {
  key: 'movie:1',
  content_type: 'movie',
  content_id: 1,
  id: 1,
  uuid: 'movie-uuid',
  name: 'Library Film',
  display_name: '',
  description: 'Canonical description',
  year: 2020,
  genre: 'Drama',
  rating: '7',
  duration_secs: 7200,
  imdb_id: 'tt123',
  tmdb_id: '123',
  source_count: 2,
  metadata_locked: false,
  poster_url: '/canonical-poster',
  backdrop_url: '/canonical-backdrop',
  metadata_languages: ['de-DE', 'en-US', 'es-ES'],
  metadata: {
    director: '',
    localized: {
      'de-DE': { title: 'Film DE', overview: 'Beschreibung' },
      'en-US': { title: 'Film EN', overview: '' },
      'es-ES': { title: 'Film ES', overview: 'Descripción' },
    },
  },
};
const sources = [11, 12].map((id) => ({
  source_id: id,
  content_id: 1,
  content_type: 'movie',
  provider_name: `Raw film ${id}`,
  provider_id: 'same-id',
  account: { id, name: `Provider ${id}` },
  category: { id: 4, name: 'English' },
  container_extension: 'mkv',
  effective_metadata: {
    values: { audio_languages: ['eng'], resolution: '1080p' },
  },
  provider: {
    name: `Raw film ${id}`,
    description: `Provider plot ${id}`,
    year: 2019,
    director: 'Provider director',
    duration_secs: 90,
    technical: {},
    poster_url: `/provider-poster-${id}`,
    backdrop_url: `/provider-backdrop-${id}`,
  },
}));
const document = { canonical, sources, selected_source_id: 11 };
const renderPreview = (props = {}) =>
  render(
    <MantineProvider env="test">
      <LibraryPreviewModal item={canonical} onClose={vi.fn()} {...props} />
    </MantineProvider>
  );
const selectLanguage = async (name) => {
  fireEvent.click(
    await screen.findByRole('textbox', {
      name: 'Metadata language',
      exact: true,
    })
  );
  fireEvent.click(await screen.findByRole('option', { name, exact: true }));
};

beforeEach(() => {
  vi.clearAllMocks();
  state.user = { user_level: 10 };
  api.getVODLibraryDetails.mockImplementation(async (params) => ({
    ...document,
    selected_source_id: Number(
      params.get('source_id') || params.get('preferred_account') || 11
    ),
  }));
  api.vodLibraryAction.mockResolvedValue({ metadata: { id: 1 } });
  api.getMovieProviderInfo.mockResolvedValue({ refresh_status: 'completed' });
  api.getSeriesInfo.mockResolvedValue({ refresh_status: 'completed' });
});

describe('source-aware Library preview', () => {
  it('keeps a blocked title manageable, disables client actions and confirms unblocking', async () => {
    api.getVODLibraryDetails.mockResolvedValue({
      ...document,
      canonical: { ...canonical, library_blocked: true },
    });
    renderPreview();
    const unblock = await screen.findByRole('button', {
      name: 'Unblock title',
    });
    await waitFor(() => expect(unblock).toBeEnabled());
    expect(
      screen.getByRole('button', { name: 'Play source Provider 11 #11' })
    ).toBeDisabled();
    expect(
      screen.getByRole('button', { name: 'Copy source link Provider 11 #11' })
    ).toBeDisabled();
    expect(
      screen.getByRole('button', { name: 'Edit metadata', exact: true })
    ).toBeEnabled();
    fireEvent.click(unblock);
    const confirmation = await screen.findByRole('dialog', {
      name: 'Unblock title?',
    });
    expect(api.vodLibraryAction).not.toHaveBeenCalled();
    fireEvent.click(
      within(confirmation).getByRole('button', { name: 'Unblock', exact: true })
    );
    await waitFor(() =>
      expect(api.vodLibraryAction).toHaveBeenCalledWith('bulk', {
        items: [{ content_type: 'movie', id: 1 }],
        operation: 'unblock',
      })
    );
  });
  it('keeps a manual canonical title ahead of translations, but preserves the explicit provider view', async () => {
    const edited = {
      ...canonical,
      name: 'Manual title',
      display_name: 'Manual title',
    };
    api.getVODLibraryDetails.mockResolvedValue({
      ...document,
      canonical: edited,
    });
    renderPreview({ item: edited });
    await screen.findByRole('heading', { name: 'Manual title' });
    await selectLanguage('English (US) (en-US)');
    expect(
      screen.getByRole('heading', { name: 'Manual title' })
    ).toBeInTheDocument();
    await selectLanguage('Provider');
    expect(
      screen.getByRole('heading', { name: 'Raw film 11' })
    ).toBeInTheDocument();
  });
  it('defaults to the canonical clean title instead of a source when no translation is available', async () => {
    const cleaned = {
      ...canonical,
      name: 'Clean canonical',
      clean_title: 'Clean canonical',
      metadata: { localized: {} },
    };
    api.getVODLibraryDetails.mockResolvedValue({
      ...document,
      canonical: cleaned,
    });
    renderPreview({ item: cleaned });
    await screen.findByRole('heading', { name: 'Clean canonical' });
    expect(
      screen.getByRole('textbox', { name: 'Metadata language' })
    ).toHaveValue('German (de-DE)');
    expect(
      screen.queryByRole('heading', { name: 'Raw film 11' })
    ).not.toBeInTheDocument();
  });
  it('renders the stored title immediately and shows one delayed loading layer for a slow document', async () => {
    let resolve;
    api.getVODLibraryDetails.mockImplementationOnce(
      () =>
        new Promise((done) => {
          resolve = done;
        })
    );
    const onClose = vi.fn();
    renderPreview({ onClose });
    expect(screen.getByText('Beschreibung')).toBeInTheDocument();
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
    expect(
      await screen.findByText('Loading title details…')
    ).toBeInTheDocument();
    expect(screen.getByText('Beschreibung').closest('[inert]')).not.toBeNull();
    expect(screen.getAllByRole('status')).toHaveLength(1);
    fireEvent.click(
      screen.getByRole('button', { name: 'Close Movie preview' })
    );
    expect(onClose).toHaveBeenCalledOnce();
    await act(async () => resolve(document));
    await waitFor(() =>
      expect(screen.queryByRole('status')).not.toBeInTheDocument()
    );
    expect(api.getMovieProviderInfo).toHaveBeenCalledOnce();
  });
  it('avoids loading flashes for a fast cached document', async () => {
    renderPreview();
    await screen.findByRole('row', { name: 'Source Provider 11 #11' });
    await act(async () => new Promise((done) => setTimeout(done, 300)));
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: 'Refresh provider details' })
    ).not.toHaveAttribute('data-loading');
  });
  it('keeps complete stored details interactive during a background cache check', async () => {
    api.getVODLibraryDetails.mockResolvedValue({
      ...document,
      sources: sources.map((source) => ({
        ...source,
        provider: { ...source.provider, details_loaded: true },
      })),
    });
    api.getMovieProviderInfo.mockImplementation(() => new Promise(() => {}));
    renderPreview();
    await screen.findByRole('row', { name: 'Source Provider 11 #11' });
    await act(async () => new Promise((done) => setTimeout(done, 300)));
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
    expect(screen.getByText('Beschreibung').closest('[inert]')).toBeNull();
    expect(
      screen.getByRole('button', { name: 'Refresh provider details' })
    ).toBeDisabled();
  });
  it('shows missing provider details under the same delayed layer and releases it on failure', async () => {
    let resolve;
    api.getMovieProviderInfo.mockImplementationOnce(
      () =>
        new Promise((done) => {
          resolve = done;
        })
    );
    renderPreview();
    expect(
      await screen.findByText('Loading provider details…')
    ).toBeInTheDocument();
    expect(screen.getAllByRole('status')).toHaveLength(1);
    await act(async () => resolve({ refresh_status: 'failed' }));
    await waitFor(() =>
      expect(screen.queryByRole('status')).not.toBeInTheDocument()
    );
    expect(screen.getByText('Beschreibung')).toBeInTheDocument();
    expect(screen.getByText('Beschreibung').closest('[inert]')).toBeNull();
    expect(showNotification).toHaveBeenCalledWith(
      expect.objectContaining({ color: 'red' })
    );
  });
  it('checks the selected movie source once on entry without forcing fresh provider data', async () => {
    renderPreview();
    await screen.findByText('Beschreibung');
    expect(api.getMovieProviderInfo).toHaveBeenCalledExactlyOnceWith(1, 11, {
      background: true,
    });
    expect(api.getVODLibraryDetails).toHaveBeenCalledOnce();
    const selector = screen.getByRole('textbox', { name: 'Metadata language' });
    expect(
      selector.closest('.mantine-Select-root').previousElementSibling
    ).toBe(screen.getByRole('button', { name: 'Edit metadata', exact: true }));
  });

  it('keeps stored data visible and reloads details automatically when a pending movie source completes', async () => {
    api.getMovieProviderInfo
      .mockResolvedValueOnce({ refresh_status: 'pending' })
      .mockResolvedValue({ refresh_status: 'completed' });
    api.getVODLibraryDetails.mockResolvedValueOnce(document).mockResolvedValue({
      ...document,
      sources: [
        {
          ...sources[0],
          provider: {
            ...sources[0].provider,
            description: 'Updated provider details',
          },
        },
        sources[1],
      ],
    });
    renderPreview();
    await selectLanguage('Provider');
    expect(screen.getByText('Provider plot 11')).toBeInTheDocument();
    expect(
      await screen.findByText('Updated provider details', {}, { timeout: 4000 })
    ).toBeInTheDocument();
    expect(api.getVODLibraryDetails).toHaveBeenCalledTimes(2);
    expect(api.getMovieProviderInfo).toHaveBeenCalledTimes(2);
    expect(
      api.getMovieProviderInfo.mock.calls.every(
        ([, relation, options]) => relation === 11 && !options.forceRefresh
      )
    ).toBe(true);
  });

  it('ignores provider results from a source that is no longer selected', async () => {
    let resolve;
    api.getMovieProviderInfo.mockImplementation((id, relation) =>
      relation === 11
        ? new Promise((done) => {
            resolve = done;
          })
        : Promise.resolve({ refresh_status: 'completed' })
    );
    renderPreview();
    fireEvent.click(
      await screen.findByRole('row', { name: 'Source Provider 12 #12' })
    );
    await waitFor(() =>
      expect(
        screen.getByRole('row', { name: 'Source Provider 12 #12' })
      ).toHaveAttribute('aria-selected', 'true')
    );
    await act(async () => resolve({ refresh_status: 'failed' }));
    expect(showNotification).not.toHaveBeenCalled();
    expect(api.getMovieProviderInfo).toHaveBeenCalledTimes(2);
    expect(api.getVODLibraryDetails).toHaveBeenCalledTimes(2);
  });

  it('loads missing series episodes on entry and refreshes the source-exact paginated document after completion', async () => {
    const initial = {
      ...document,
      canonical: { ...canonical, content_type: 'series' },
      episodes: [],
      episode_count: 0,
      seasons: [],
    };
    api.getVODLibraryDetails.mockResolvedValueOnce(initial).mockResolvedValue({
      ...initial,
      selected_season: 1,
      seasons: [{ number: 1, count: 1 }],
      episodes: [
        {
          id: 9,
          name: 'Automatically loaded episode',
          season_number: 1,
          episode_number: 1,
        },
      ],
      episode_count: 1,
      episode_page: 1,
    });
    api.getSeriesInfo
      .mockResolvedValueOnce({ refresh_status: 'pending' })
      .mockResolvedValue({ refresh_status: 'completed' });
    renderPreview({ item: { ...canonical, content_type: 'series' } });
    expect(
      await screen.findByRole(
        'button',
        { name: 'Automatically loaded episode' },
        { timeout: 4000 }
      )
    ).toBeInTheDocument();
    expect(api.getVODLibraryDetails).toHaveBeenCalledTimes(2);
    expect(api.getSeriesInfo).toHaveBeenCalledTimes(2);
    expect(
      api.getSeriesInfo.mock.calls.every(
        ([id, relation, options]) =>
          id === 1 &&
          relation === 11 &&
          options.includeEpisodes === false &&
          !options.forceRefresh
      )
    ).toBe(true);
    expect(api.getMovieProviderInfo).not.toHaveBeenCalled();
    expect(
      screen.getByText('Automatically loaded episode')
    ).not.toHaveAttribute('data-inherit');
  });

  it('loads provider details using a resolved canonical alias and the exact selected relation', async () => {
    api.getVODLibraryDetails.mockResolvedValue({
      ...document,
      canonical: { ...canonical, content_id: 2 },
    });
    renderPreview();
    await screen.findByText('Beschreibung');
    expect(api.getMovieProviderInfo).toHaveBeenCalledExactlyOnceWith(2, 11, {
      background: true,
    });
  });

  it('ignores pending provider results after closing', async () => {
    let resolve;
    api.getMovieProviderInfo.mockImplementation(
      () =>
        new Promise((done) => {
          resolve = done;
        })
    );
    const { unmount } = renderPreview();
    await screen.findByText('Beschreibung');
    unmount();
    await act(async () => resolve({ refresh_status: 'failed' }));
    expect(showNotification).not.toHaveBeenCalled();
    expect(api.getVODLibraryDetails).toHaveBeenCalledOnce();
  });
  it('groups the stored technical source details like the production table', async () => {
    api.getVODLibraryDetails.mockResolvedValue({
      ...document,
      sources: [
        {
          ...sources[0],
          provider: {
            ...sources[0].provider,
            technical: {
              bitrate: '12500',
              file_size_bytes: 1500000000,
              video: { codec_name: 'hevc', avg_frame_rate: '24000/1001' },
              audio: { codec_name: 'eac3' },
            },
          },
          effective_metadata: {
            values: {
              audio_languages: ['eng'],
              resolution: '2160p',
              video_features: ['dv', 'hdr'],
            },
          },
        },
        sources[1],
      ],
    });
    renderPreview();
    const row = await screen.findByRole('row', {
      name: 'Source Provider 11 #11',
    });
    for (const value of [
      'MKV',
      '12.5 Mbps',
      '1.5 GB',
      'HEVC',
      'EAC3',
      '23.98 FPS',
      'Dolby Vision',
      'HDR',
      '2160p',
    ]) {
      expect(within(row).getByText(value)).toBeInTheDocument();
    }
    expect(api.getMovieProviderInfo).toHaveBeenCalledWith(1, 11, {
      background: true,
    });
  });

  it('handles failed poster and background images without displaying broken image text', async () => {
    renderPreview();
    const poster = await screen.findByRole('img', {
      name: 'Film DE',
      exact: true,
    });
    fireEvent.error(poster);
    expect(
      screen.queryByRole('img', { name: 'Film DE', exact: true })
    ).not.toBeInTheDocument();
    expect(screen.getByLabelText('No artwork available')).toBeInTheDocument();
    fireEvent.error(screen.getByRole('img', { name: 'Film DE backdrop' }));
    expect(
      screen.queryByRole('img', { name: 'Film DE backdrop' })
    ).not.toBeInTheDocument();
    await selectLanguage('Provider');
    expect(
      screen.getByRole('img', { name: 'Raw film 11', exact: true })
    ).toHaveAttribute('src', '/provider-poster-11');
    expect(
      screen.getByRole('img', { name: 'Raw film 11 backdrop' })
    ).toHaveAttribute('src', '/provider-backdrop-11');
  });

  it('keeps the production poster, backdrop, field layout and exact-source table in both metadata views', async () => {
    renderPreview();
    expect(
      await screen.findByRole('heading', { name: 'Film DE' })
    ).toBeInTheDocument();
    expect(
      screen.getByRole('img', { name: 'Film DE', exact: true })
    ).toHaveAttribute('src', '/canonical-poster');
    expect(
      screen.getByRole('img', { name: 'Film DE backdrop' })
    ).toHaveAttribute('src', '/canonical-backdrop');
    const table = screen.getByRole('table', { name: 'Exact VOD sources' });
    expect(
      within(table)
        .getAllByRole('columnheader')
        .map((cell) => cell.textContent)
    ).toEqual([
      'SourceM3U account · Category · IDs',
      'DUB',
      'SUB',
      'Resolution',
      'Details',
      'Actions',
    ]);
    expect(
      within(table).getAllByText(/Stream ID: same-id · Relation ID:/)
    ).toHaveLength(2);
    await selectLanguage('Provider');
    expect(
      screen.getByRole('img', { name: 'Raw film 11', exact: true })
    ).toHaveAttribute('src', '/provider-poster-11');
    expect(
      screen.getByRole('img', { name: 'Raw film 11 backdrop' })
    ).toHaveAttribute('src', '/provider-backdrop-11');
    fireEvent.click(
      screen.getByRole('row', { name: 'Source Provider 12 #12' })
    );
    await screen.findByText('Provider plot 12');
    expect(
      screen.getByRole('img', { name: 'Raw film 12', exact: true })
    ).toHaveAttribute('src', '/provider-poster-12');
    expect(
      screen.getByRole('img', { name: 'Raw film 12 backdrop' })
    ).toHaveAttribute('src', '/provider-backdrop-12');
    expect(api.getMovieProviderInfo).toHaveBeenCalledWith(1, 12, {
      background: true,
    });
    expect(api.vodLibraryAction).not.toHaveBeenCalled();
  });

  it('retains every source, dims the account-filter context and allows keyboard selection outside it', async () => {
    renderPreview({ accountId: '12' });
    const outside = await screen.findByRole('row', {
      name: 'Source Provider 11 #11',
    });
    const matching = screen.getByRole('row', {
      name: 'Source Provider 12 #12',
    });
    expect(outside).toHaveAttribute('data-outside-filter', 'true');
    expect(matching).not.toHaveAttribute('data-outside-filter');
    expect(matching).toHaveAttribute('aria-selected', 'true');
    expect(outside).not.toHaveAttribute('aria-disabled', 'true');
    expect(
      api.getVODLibraryDetails.mock.calls[0][0].get('preferred_account')
    ).toBe('12');
    fireEvent.keyDown(outside, { key: 'Enter' });
    await waitFor(() =>
      expect(outside).toHaveAttribute('aria-selected', 'true')
    );
    expect(api.getVODLibraryDetails.mock.calls.at(-1)[0].get('source_id')).toBe(
      '11'
    );
    expect(api.vodLibraryAction).not.toHaveBeenCalled();
  });

  it('does not change the selected source when a source action is clicked', async () => {
    renderPreview();
    await screen.findByText('Beschreibung');
    fireEvent.click(
      screen.getByRole('button', { name: 'Copy source link Provider 12 #12' })
    );
    expect(api.getMovieProviderInfo).toHaveBeenCalledTimes(1);
    expect(
      screen.getByRole('row', { name: 'Source Provider 11 #11' })
    ).toHaveAttribute('aria-selected', 'true');
    expect(
      new URL(state.copy.mock.calls[0][0]).searchParams.get('m3u_account_id')
    ).toBe('12');
  });

  it('defaults to the first available configured translation and retains a manual selection', async () => {
    api.getVODLibraryDetails.mockImplementation(async (params) => ({
      ...document,
      selected_source_id: Number(params.get('source_id') || 11),
      canonical: {
        ...canonical,
        metadata_languages: ['fr-FR', 'es-ES', 'de-DE', 'en-US'],
      },
    }));
    renderPreview();
    await screen.findByText('Descripción');
    expect(
      screen.getByRole('textbox', { name: 'Metadata language' })
    ).toHaveValue('Spanish (es-ES)');
    await selectLanguage('English (US) (en-US)');
    fireEvent.click(
      screen.getByRole('row', { name: 'Source Provider 12 #12', exact: true })
    );
    await waitFor(() =>
      expect(
        screen.getByRole('row', { name: 'Source Provider 12 #12' })
      ).toHaveAttribute('aria-selected', 'true')
    );
    expect(
      screen.getByRole('textbox', { name: 'Metadata language' })
    ).toHaveValue('English (US) (en-US)');
  });
  it('keeps equal language views and unchanged provider data separate', async () => {
    renderPreview();
    await screen.findByText('Beschreibung');
    expect(screen.getByText('2h 0m')).toBeInTheDocument();
    expect(screen.getByText('IMDb tt123')).toBeInTheDocument();
    expect(screen.queryByText('Provider director')).not.toBeInTheDocument();
    expect(
      screen.getByRole('textbox', { name: 'Metadata language', exact: true })
    ).toHaveValue('German (de-DE)');
    await selectLanguage('English (US) (en-US)');
    expect(screen.getByText('No description available.')).toBeInTheDocument();
    expect(screen.queryByText('Canonical description')).not.toBeInTheDocument();
    await selectLanguage('Provider');
    expect(screen.getByText('Provider plot 11')).toBeInTheDocument();
    expect(screen.getByText('Provider director')).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole('row', { name: 'Source Provider 12 #12', exact: true })
    );
    await screen.findByText('Provider plot 12');
    expect(
      screen.getByRole('textbox', { name: 'Metadata language', exact: true })
    ).toHaveValue('Provider');
    expect(
      screen.getByRole('textbox', { name: 'Metadata language', exact: true })
    ).toBeEnabled();
    expect(
      screen.queryByRole('button', { name: 'Provider', exact: true })
    ).not.toBeInTheDocument();
    await selectLanguage('German (de-DE)');
    expect(screen.getByText('Beschreibung')).toBeInTheDocument();
    expect(api.getMovieProviderInfo).toHaveBeenCalledWith(1, 12, {
      background: true,
    });
    expect(api.getSeriesInfo).not.toHaveBeenCalled();
    expect(api.vodLibraryAction).not.toHaveBeenCalled();
  });

  it('keeps the canonical fallback without adding a separate base-title option', async () => {
    api.getVODLibraryDetails.mockResolvedValue({
      ...document,
      canonical: { ...canonical, metadata: { localized: {} } },
    });
    renderPreview();
    await screen.findByText('Canonical description');
    const dropdown = screen.getByRole('textbox', {
      name: 'Metadata language',
      exact: true,
    });
    expect(dropdown).toHaveValue('German (de-DE)');
    fireEvent.click(dropdown);
    expect(
      screen.getByRole('option', { name: 'Provider', exact: true })
    ).toBeInTheDocument();
    expect(
      screen.queryByRole('option', { name: 'Base title', exact: true })
    ).not.toBeInTheDocument();
    fireEvent.click(
      screen.getByRole('option', { name: 'English (US) (en-US)', exact: true })
    );
    expect(screen.getByText('Canonical description')).toBeInTheDocument();
    expect(api.getMovieProviderInfo).toHaveBeenCalledWith(1, 11, {
      background: true,
    });
    expect(api.getSeriesInfo).not.toHaveBeenCalled();
    expect(api.vodLibraryAction).not.toHaveBeenCalled();
  });

  it('plays and copies the concrete source with account-scoped identifiers', async () => {
    renderPreview();
    fireEvent.click(
      await screen.findByRole('button', { name: 'Play source Provider 12 #12' })
    );
    const url = new URL(state.showVideo.mock.calls[0][0]);
    expect(url.pathname).toBe('/proxy/vod/movie/movie-uuid');
    expect(url.searchParams.get('m3u_account_id')).toBe('12');
    expect(url.searchParams.get('stream_id')).toBe('same-id');
    expect(url.searchParams.get('token')).toBe('test-token');
    fireEvent.click(
      screen.getByRole('button', { name: 'Copy source link Provider 11 #11' })
    );
    expect(
      new URL(state.copy.mock.calls[0][0]).searchParams.get('m3u_account_id')
    ).toBe('11');
  });

  it('reuses the canonical editor with discard protection and refreshes after Save', async () => {
    renderPreview();
    fireEvent.click(
      await screen.findByRole('button', { name: 'Edit metadata', exact: true })
    );
    const title = screen.getByRole('textbox', { name: 'Title', exact: true });
    fireEvent.change(title, { target: { value: 'Updated Film' } });
    fireEvent.click(
      screen.getByRole('button', { name: 'Close Edit title metadata' })
    );
    expect(
      await screen.findByText('Discard unsaved changes?')
    ).toBeInTheDocument();
    expect(api.vodLibraryAction).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Continue editing' }));
    await waitFor(() =>
      expect(
        screen.queryByText('Discard unsaved changes?')
      ).not.toBeInTheDocument()
    );
    api.getVODLibraryDetails.mockResolvedValue({
      ...document,
      canonical: {
        ...canonical,
        name: 'Updated Film',
        display_name: 'Updated Film',
        metadata: {
          ...canonical.metadata,
          localized: { 'de-DE': { title: 'Updated Film' } },
        },
      },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Save', exact: true }));
    await waitFor(() =>
      expect(api.vodLibraryAction).toHaveBeenCalledWith(
        'content',
        { content_type: 'movie', id: 1, display_name: 'Updated Film' },
        'PATCH'
      )
    );
    await waitFor(() =>
      expect(screen.queryByText('Edit title metadata')).not.toBeInTheDocument()
    );
    expect(await screen.findByText('Updated Film')).toBeInTheDocument();
    expect(state.fetchContent).toHaveBeenCalled();
  });

  it('reuses source metadata editing without changing the canonical assignment implicitly', async () => {
    renderPreview();
    fireEvent.click(
      await screen.findByRole('button', {
        name: 'Edit source metadata Provider 12 #12',
      })
    );
    expect(await screen.findByText('Edit source metadata')).toBeInTheDocument();
    expect(
      screen.getByRole('textbox', { name: 'Search Library title or TMDB ID' })
    ).toBeInTheDocument();
    expect(api.vodLibraryAction).not.toHaveBeenCalled();
  });

  it('protects or unlocks the canonical title, not the selected provider', async () => {
    let locked = true;
    api.getVODLibraryDetails.mockImplementation(async () => ({
      ...document,
      canonical: { ...canonical, metadata_locked: locked },
    }));
    api.vodLibraryAction.mockImplementation(async () => {
      locked = false;
      return { count: 1 };
    });
    renderPreview();
    expect(
      await screen.findByRole('button', { name: 'Edit metadata', exact: true })
    ).toBeDisabled();
    expect(
      screen.queryByRole('button', { name: 'Match title with TMDB' })
    ).not.toBeInTheDocument();
    fireEvent.click(
      await screen.findByRole('button', {
        name: 'Unlock automatic metadata matching',
      })
    );
    await waitFor(() =>
      expect(api.vodLibraryAction).toHaveBeenCalledWith('bulk', {
        items: [{ content_type: 'movie', id: 1 }],
        operation: 'unlock',
      })
    );
    expect(state.fetchContent).toHaveBeenCalled();
    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: 'Edit metadata', exact: true })
      ).toBeEnabled()
    );
    expect(
      screen.getByRole('button', { name: 'Lock automatic metadata matching' })
    ).toBeInTheDocument();
  });

  it('disables metadata editing again after locking the title', async () => {
    let locked = false;
    api.getVODLibraryDetails.mockImplementation(async () => ({
      ...document,
      canonical: { ...canonical, metadata_locked: locked },
    }));
    api.vodLibraryAction.mockImplementation(async () => {
      locked = true;
      return { count: 1 };
    });
    renderPreview();
    expect(
      await screen.findByRole('button', { name: 'Edit metadata', exact: true })
    ).toBeEnabled();
    fireEvent.click(
      screen.getByRole('button', { name: 'Lock automatic metadata matching' })
    );
    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: 'Edit metadata', exact: true })
      ).toBeDisabled()
    );
    expect(api.vodLibraryAction).toHaveBeenCalledWith('bulk', {
      items: [{ content_type: 'movie', id: 1 }],
      operation: 'lock',
    });
  });

  it('follows the edited source when a TMDB assignment moves it to another title', async () => {
    renderPreview({ item: { ...canonical, source_id: 11 } });
    fireEvent.click(
      await screen.findByRole('button', {
        name: 'Edit source metadata Provider 12 #12',
      })
    );
    api.getVODCanonicalTargets.mockResolvedValue({
      results: [{ id: 2, name: 'Moved Film', source_count: 1, tmdb_id: '456' }],
    });
    fireEvent.click(
      screen.getByRole('button', { name: 'Search', exact: true })
    );
    fireEvent.click(
      await screen.findByRole('button', { name: 'Move', exact: true })
    );
    api.vodLibraryAction.mockResolvedValue({ metadata: { id: 2 } });
    api.getVODLibraryDetails.mockImplementation(async (params) => ({
      ...document,
      canonical: {
        ...canonical,
        content_id: Number(params.get('id')),
        name: 'Moved Film',
        metadata: {
          ...canonical.metadata,
          localized: { 'de-DE': { title: 'Moved Film' } },
        },
      },
      selected_source_id: 12,
      sources: [sources[1]],
    }));
    fireEvent.click(
      within(screen.getByRole('dialog', { name: 'Move to title?' })).getByRole(
        'button',
        { name: 'Move', exact: true }
      )
    );
    await screen.findByText('Moved Film');
    const params = api.getVODLibraryDetails.mock.calls.at(-1)[0];
    expect(params.get('id')).toBe('2');
    expect(params.get('source_id')).toBe('12');
  });

  it('keeps management actions out of the standard-user preview', async () => {
    state.user = { user_level: 1 };
    renderPreview();
    await screen.findByText('Beschreibung');
    expect(
      screen.queryByRole('button', { name: 'Edit metadata', exact: true })
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: /Edit source metadata/ })
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: 'Match title with TMDB' })
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: 'Play source Provider 11 #11' })
    ).toBeInTheDocument();
  });

  it('loads source-exact series episodes and resets pagination when switching source', async () => {
    api.getVODLibraryDetails.mockImplementation(async (params) => {
      const source = Number(params.get('source_id') || 11);
      const season = Number(params.get('season') ?? 0);
      return {
        ...document,
        canonical: { ...canonical, content_type: 'series' },
        selected_source_id: source,
        selected_season: season,
        seasons: [
          { number: 0, count: 1 },
          { number: 1, count: 20 },
        ],
        episode_count: season === 0 ? 1 : 20,
        episode_page: 1,
        episodes: [
          {
            id: source,
            uuid: `episode-${source}`,
            name: `Episode from ${source}`,
            season_number: season,
            episode_number: 1,
            stream_id: `episode-stream-${source}`,
            duration_secs: 120,
            air_date: '2020-01-01',
            resolution: '1080p',
            video_codec: 'h264',
            container_extension: 'mkv',
          },
        ],
      };
    });
    renderPreview({ item: { ...canonical, content_type: 'series' } });
    expect(
      await screen.findByRole('tab', { name: 'Specials (1)' })
    ).toHaveAttribute('aria-selected', 'true');
    expect(
      screen.queryByRole('tab', { name: 'All seasons' })
    ).not.toBeInTheDocument();
    fireEvent.click(
      await screen.findByRole('button', {
        name: 'Play episode Episode from 11',
      })
    );
    expect(
      new URL(state.showVideo.mock.calls[0][0]).searchParams.get('stream_id')
    ).toBe('episode-stream-11');
    expect(
      new URL(state.showVideo.mock.calls[0][0]).searchParams.get(
        'm3u_account_id'
      )
    ).toBe('11');
    fireEvent.click(
      screen.getByRole('row', { name: 'Source Provider 12 #12', exact: true })
    );
    await screen.findByText('Episode from 12');
    expect(screen.queryByText('Episode from 11')).not.toBeInTheDocument();
    expect(api.getVODLibraryDetails.mock.calls.at(-1)[0].get('page')).toBe('1');
    expect(
      screen.getByRole('tab', { name: 'Season 1 (20)' })
    ).toBeInTheDocument();
    expect(
      within(screen.getByRole('table', { name: 'Source episodes' }))
        .getAllByRole('columnheader')
        .map((cell) => cell.textContent)
    ).toEqual([
      'Ep',
      'Title',
      'Duration',
      'Date',
      'Resolution',
      'Codec',
      'Format',
      'Actions',
    ]);
    fireEvent.click(screen.getByRole('tab', { name: 'Season 1 (20)' }));
    await waitFor(() =>
      expect(api.getVODLibraryDetails.mock.calls.at(-1)[0].get('season')).toBe(
        '1'
      )
    );
    fireEvent.click(
      screen.getByRole('button', { name: 'Episode from 12', exact: true })
    );
    expect(
      screen.getByRole('button', { name: 'Episode from 12', exact: true })
    ).toHaveAttribute('aria-expanded', 'true');
    expect(
      screen.queryByRole('button', { name: 'Play episode', exact: true })
    ).not.toBeInTheDocument();
    expect(screen.getAllByRole('dialog')).toHaveLength(1);
    fireEvent.click(
      screen.getByRole('button', {
        name: 'Play episode Episode from 12',
        exact: true,
      })
    );
    expect(
      new URL(state.showVideo.mock.calls.at(-1)[0]).searchParams.get(
        'm3u_account_id'
      )
    ).toBe('12');
  });

  it('uses neutral keyboard-operable episode titles and production-style details', async () => {
    api.getVODLibraryDetails.mockResolvedValue({
      ...document,
      canonical: { ...canonical, content_type: 'series' },
      selected_season: 1,
      seasons: [{ number: 1, count: 1 }],
      episode_count: 1,
      episode_page: 1,
      episodes: [
        {
          id: 9,
          name: 'A long episode title',
          season_number: 1,
          episode_number: 2,
          description: 'Episode description',
          director: 'Episode director',
          actors: 'Episode actor',
          genre: 'Documentary',
          rating: '8.0',
          imdb_id: 'tt456',
          poster_url: '/episode-poster',
          technical: {
            bitrate: '2500',
            video: { codec_name: 'h264', width: 1920, height: 1080 },
            audio: { codec_name: 'aac', channels: 2 },
          },
        },
      ],
    });
    renderPreview({ item: { ...canonical, content_type: 'series' } });
    const title = await screen.findByRole('button', {
      name: 'A long episode title',
      exact: true,
    });
    expect(title.tagName).toBe('BUTTON');
    expect(title).toHaveClass('mantine-UnstyledButton-root');
    expect(title).not.toHaveClass('mantine-Button-root');
    expect(title).toHaveAttribute('aria-expanded', 'false');
    fireEvent.click(title);
    expect(title).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByText('Episode description')).toBeInTheDocument();
    expect(screen.getByText('Episode director')).toBeInTheDocument();
    expect(screen.getByText('Episode actor')).toBeInTheDocument();
    expect(screen.getByText('h264, 1920x1080')).toBeInTheDocument();
    expect(screen.getByText('aac, 2 channels')).toBeInTheDocument();
    expect(
      screen.getByRole('link', { name: 'TMDB', exact: true })
    ).toHaveAttribute(
      'href',
      'https://www.themoviedb.org/tv/123/season/1/episode/2'
    );
    expect(
      screen.getByRole('img', { name: 'A long episode title' })
    ).toHaveStyle({
      width: 'calc(7.5rem * var(--mantine-scale))',
      height: 'calc(10rem * var(--mantine-scale))',
    });
    expect(
      screen.queryByRole('button', { name: 'Play episode', exact: true })
    ).not.toBeInTheDocument();
    expect(api.getSeriesInfo).toHaveBeenCalledWith(1, 11, {
      background: true,
      includeEpisodes: false,
    });
  });

  it('keeps episodes without a season number accessible without an All seasons tab', async () => {
    api.getVODLibraryDetails.mockResolvedValue({
      ...document,
      canonical: { ...canonical, content_type: 'series' },
      seasons: [{ number: null, count: 1 }],
      selected_season: -1,
      episode_count: 1,
      episode_page: 1,
      episodes: [
        {
          id: 9,
          name: 'Unassigned episode',
          season_number: null,
          episode_number: 1,
        },
      ],
    });
    renderPreview({ item: { ...canonical, content_type: 'series' } });
    expect(
      await screen.findByRole('tab', { name: 'Unassigned (1)' })
    ).toHaveAttribute('aria-selected', 'true');
    expect(
      screen.getByRole('button', { name: 'Unassigned episode', exact: true })
    ).toBeInTheDocument();
    expect(
      screen.queryByRole('tab', { name: 'All seasons' })
    ).not.toBeInTheDocument();
  });

  it('ignores stale detail responses after closing', async () => {
    let resolve;
    api.getVODLibraryDetails.mockImplementation(
      () =>
        new Promise((done) => {
          resolve = done;
        })
    );
    const { unmount } = renderPreview();
    await waitFor(() => expect(api.getVODLibraryDetails).toHaveBeenCalled());
    unmount();
    await act(async () => resolve(document));
    expect(screen.queryByText('Canonical description')).not.toBeInTheDocument();
  });

  it('retains stored details if the provider refresh fails', async () => {
    api.getMovieProviderInfo.mockResolvedValue({ refresh_status: 'failed' });
    renderPreview();
    await selectLanguage('Provider');
    fireEvent.click(
      screen.getByRole('button', { name: 'Refresh provider details' })
    );
    await waitFor(() =>
      expect(showNotification).toHaveBeenCalledWith(
        expect.objectContaining({
          message:
            'Provider details could not be loaded. Stored data is still available.',
          color: 'red',
        })
      )
    );
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(screen.getByText('Provider plot 11')).toBeInTheDocument();
    expect(api.getMovieProviderInfo).toHaveBeenCalledWith(1, 11, {
      background: true,
      forceRefresh: true,
    });
  });
});
