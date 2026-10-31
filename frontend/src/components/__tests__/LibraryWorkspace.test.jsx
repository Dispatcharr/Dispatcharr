import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import { MantineProvider, Modal } from '@mantine/core';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import api from '../../api';
import { showNotification } from '../../utils/notificationUtils.js';
import useLibraryStore from '../../store/useLibraryStore';
import LibraryWorkspace from '../LibraryWorkspace.jsx';
import {
  LibraryContentEditor,
  LibraryMatchDialog,
  LibrarySourceEditor,
} from '../LibraryDialogs.jsx';

const auth = vi.hoisted(() => ({
  user: { user_level: 10, custom_properties: {} },
}));
vi.mock('../../store/auth', () => ({ default: (selector) => selector(auth) }));
vi.mock('../../api', () => ({
  default: {
    getVODLibrary: vi.fn(),
    getVODCanonicalTargets: vi.fn(),
    getVODLibraryOptions: vi.fn(),
    getVODLibraryState: vi.fn(),
    getVODLibrarySettings: vi.fn(),
    updateVODLibrarySettings: vi.fn(),
    vodLibraryAction: vi.fn(),
  },
}));

vi.mock('../../utils/notificationUtils.js', () => ({
  showNotification: vi.fn(),
}));

const chooseTarget = async () => {
  fireEvent.click(screen.getByRole('button', { name: 'Search', exact: true }));
  fireEvent.click(
    await screen.findByRole('button', { name: 'Move', exact: true })
  );
};

const item = {
  key: 'movie:1',
  id: 1,
  content_id: 1,
  content_type: 'movie',
  name: 'Film',
  provider_name: 'Film',
  year: 2020,
  description: 'Description',
  genre: 'Drama',
  rating: '7',
  poster_url: '/api/vod/movie/1/poster',
  source_count: 2,
  source_id: null,
  metadata_status: '',
  metadata_locked: false,
  metadata_summary: {
    audio_languages: ['eng', 'ger'],
    subtitle_languages: ['eng'],
    resolution: ['1080p'],
    container_extensions: ['mkv', 'mp4'],
    video_features: ['hdr'],
  },
};
const source = {
  ...item,
  provider_name: 'Provider Film',
  key: 'movie:5',
  source_id: 5,
  account: { id: 3, name: 'Account' },
  category: { id: 4, name: 'English' },
  metadata_summary: { ...item.metadata_summary, container_extensions: ['mkv'] },
  manual_metadata: { audio_languages: ['eng'] },
  effective_metadata: {
    values: { audio_languages: ['eng'] },
    provenance: { audio_languages: 'manual' },
  },
};
const initialSettings = {
  languages: ['en-US'],
  token_configured: true,
  token_source: 'stored',
  auto_enrich: false,
  match_missing: false,
  prefer_artwork: true,
  title_rules: [],
  year_rules: [{ value: '(YYYY)', position: 'end', enabled: true }],
};
const renderUI = (content) =>
  render(
    <MantineProvider env="test">
      <Modal.Stack>{content}</Modal.Stack>
    </MantineProvider>
  );

beforeEach(() => {
  vi.clearAllMocks();
  api.getVODCanonicalTargets.mockResolvedValue({
    results: [
      {
        id: 2,
        name: 'Correct Film',
        year: 2020,
        tmdb_id: '123',
        source_count: 1,
      },
    ],
  });
  localStorage.clear();
  auth.user = { user_level: 10, custom_properties: {} };
  useLibraryStore.setState({
    filters: {
      type: 'all',
      view: 'titles',
      search: '',
      account: '',
      category: '',
      locked: '',
      metadata_status: '',
    },
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
  api.getVODLibrary.mockImplementation(async (params) => ({
    results: [params.get('view') === 'sources' ? source : item],
    count: 2,
  }));
  api.getVODLibraryOptions.mockResolvedValue({
    accounts: [{ id: 3, name: 'Account' }],
    categories: [{ id: 4, name: 'English', category_type: 'movie' }],
  });
  api.getVODLibraryState.mockResolvedValue({ status: 'idle', progress: {} });
  api.getVODLibrarySettings.mockResolvedValue(initialSettings);
  api.updateVODLibrarySettings.mockResolvedValue(initialSettings);
  api.vodLibraryAction.mockResolvedValue({ count: 1 });
});

describe('Library management with real Mantine controls', () => {
  it.each(['list', 'posters'])(
    'marks globally blocked titles in %s without removing management access',
    async (displayMode) => {
      api.getVODLibrary.mockResolvedValue({
        results: [{ ...item, library_blocked: true }],
        count: 1,
      });
      renderUI(
        <LibraryWorkspace
          view="titles"
          displayMode={displayMode}
          onPreview={vi.fn()}
        />
      );
      const indicator = await screen.findByRole('img', {
        name: 'Blocked globally',
      });
      expect(indicator.closest('[data-blocked="true"]')).not.toBeNull();
      expect(
        screen.getByRole('button', { name: 'Preview Film', exact: true })
      ).toBeEnabled();
    }
  );
  it.each(['titles', 'sources'])(
    'selects all filtered %s across pages and keeps individual exclusions',
    async (view) => {
      const sources = view === 'sources';
      const first = sources ? source : item;
      const second = {
        ...first,
        key: 'series:8',
        content_type: 'series',
        content_id: 8,
        source_id: sources ? 8 : null,
        name: 'Second title',
        provider_name: 'Second provider',
      };
      api.getVODLibrary.mockImplementation(async (params) => ({
        results: [params.get('page') === '2' ? second : first],
        count: 48,
      }));
      api.vodLibraryAction.mockResolvedValue({
        count: 47,
        protected_count: 0,
        results: [],
      });
      renderUI(<LibraryWorkspace view={view} onPreview={vi.fn()} />);
      await screen.findByRole('checkbox', {
        name: `Select ${sources ? 'Provider Film' : 'Film'}`,
      });
      const selectAll = screen.getByRole('checkbox', {
        name: `Select all matching ${view}`,
      });
      fireEvent.click(selectAll);
      expect(
        screen.getByRole('button', { name: 'Edit (48)', exact: true })
      ).toBeEnabled();
      fireEvent.click(
        screen.getByRole('button', { name: 'Next page', exact: true })
      );
      const nextRow = await screen.findByRole('checkbox', {
        name: `Select ${sources ? 'Second provider' : 'Second title'}`,
      });
      expect(nextRow).toBeChecked();
      fireEvent.click(nextRow);
      expect(
        screen.getByRole('button', { name: 'Edit (47)', exact: true })
      ).toBeEnabled();
      fireEvent.click(
        screen.getByRole('button', { name: 'Previous page', exact: true })
      );
      expect(
        await screen.findByRole('checkbox', {
          name: `Select ${sources ? 'Provider Film' : 'Film'}`,
        })
      ).toBeChecked();
      fireEvent.click(
        screen.getByRole('button', { name: 'Edit (47)', exact: true })
      );
      const expected = {
        all_matching: true,
        filters: { type: 'all', view },
        excluded: [{ content_type: 'series', id: 8 }],
      };
      if (sources) {
        expect(
          await screen.findByRole('dialog', { name: 'Edit 47 sources' })
        ).toBeInTheDocument();
        expect(screen.queryByText('Move to title')).not.toBeInTheDocument();
        fireEvent.click(
          screen.getByRole('button', { name: 'Reset DUB languages override' })
        );
        fireEvent.click(
          screen.getByRole('button', { name: 'Save', exact: true })
        );
        await waitFor(() =>
          expect(api.vodLibraryAction).toHaveBeenCalledWith(
            'source-metadata',
            { ...expected, manual_metadata: { audio_languages: null } },
            'PATCH'
          )
        );
      } else {
        await waitFor(() =>
          expect(api.vodLibraryAction).toHaveBeenCalledWith('cleanup-preview', {
            ...expected,
            page: 1,
            page_size: 25,
            title_rules: [],
            year_rules: initialSettings.year_rules,
          })
        );
      }
    }
  );
  it('keeps explicit selections across pages and clears the full selection when filters change', async () => {
    const second = {
      ...item,
      key: 'movie:2',
      content_id: 2,
      name: 'Second title',
    };
    api.getVODLibrary.mockImplementation(async (params) => ({
      results: [params.get('page') === '2' ? second : item],
      count: 48,
    }));
    renderUI(<LibraryWorkspace view="titles" onPreview={vi.fn()} />);
    fireEvent.click(
      await screen.findByRole('checkbox', { name: 'Select Film' })
    );
    fireEvent.click(
      screen.getByRole('button', { name: 'Next page', exact: true })
    );
    fireEvent.click(
      await screen.findByRole('checkbox', { name: 'Select Second title' })
    );
    expect(
      screen.getByRole('button', { name: 'Edit (2)', exact: true })
    ).toBeEnabled();
    fireEvent.click(
      screen.getByRole('button', { name: 'Previous page', exact: true })
    );
    expect(
      await screen.findByRole('checkbox', { name: 'Select Film' })
    ).toBeChecked();
    fireEvent.click(
      screen.getByRole('checkbox', { name: 'Select all matching titles' })
    );
    fireEvent.click(screen.getByRole('button', { name: 'Clear', exact: true }));
    expect(
      screen.getByRole('button', { name: 'Edit (0)', exact: true })
    ).toBeDisabled();
    fireEvent.click(
      screen.getByRole('checkbox', { name: 'Select all matching titles' })
    );
    fireEvent.change(screen.getByRole('textbox', { name: 'Search titles' }), {
      target: { value: 'Different scope' },
    });
    expect(
      screen.getByRole('button', { name: 'Edit (0)', exact: true })
    ).toBeDisabled();
  });
  it('keeps type and year below the title and moves metadata status into its own column', async () => {
    api.getVODLibrary.mockResolvedValue({
      results: [
        {
          ...item,
          name: 'Clean Film',
          provider_name: 'EN Film (2020)',
          clean_title: 'Clean Film',
          metadata_status: 'ambiguous',
        },
      ],
      count: 1,
    });
    renderUI(<LibraryWorkspace view="titles" onPreview={vi.fn()} />);
    const title = await screen.findByText('Clean Film');
    const cell = title.closest('td');
    expect(screen.queryByText('EN Film (2020)')).not.toBeInTheDocument();
    expect(
      within(cell).queryByText('Clean: Clean Film')
    ).not.toBeInTheDocument();
    expect(within(cell).getByText('Movie · 2020')).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: 'Metadata' })).toHaveStyle({
      width: 'calc(7.5rem * var(--mantine-scale))',
    });
    const sourceCount = within(title.closest('tr')).getAllByRole('cell')[3];
    expect(sourceCount).toHaveTextContent('2');
    expect(within(sourceCount).queryByRole('button')).not.toBeInTheDocument();
  });
  it.each([
    ['movie', 'list'],
    ['series', 'list'],
    ['movie', 'posters'],
    ['series', 'posters'],
  ])(
    'uses only the canonical name in %s %s view',
    async (content_type, displayMode) => {
      api.getVODLibrary.mockResolvedValue({
        results: [
          {
            ...item,
            content_type,
            name: 'Localized canonical title',
            provider_name: 'Provider raw name',
            clean_title: 'Clean fallback',
          },
        ],
        count: 1,
      });
      renderUI(
        <LibraryWorkspace
          view="titles"
          displayMode={displayMode}
          onPreview={vi.fn()}
        />
      );
      await screen.findByText('Localized canonical title');
      expect(screen.queryByText('Provider raw name')).not.toBeInTheDocument();
      expect(screen.queryByText(/Clean: /)).not.toBeInTheDocument();
    }
  );
  it('uses the production table columns and retains Library management actions', async () => {
    renderUI(
      <LibraryWorkspace view="titles" onPreview={vi.fn()} onChanged={vi.fn()} />
    );
    await screen.findByText('Film');
    expect(
      screen.getAllByRole('columnheader').map((cell) => cell.textContent)
    ).toEqual([
      '',
      'Artwork',
      'Title',
      'Sources',
      'Genre',
      'Metadata',
      'DUB',
      'SUB',
      'Resolution',
      'Format',
      'Features',
      'Details',
    ]);
    const row = screen
      .getByRole('checkbox', { name: 'Select Film' })
      .closest('tr');
    const cells = within(row).getAllByRole('cell');
    expect(cells).toHaveLength(12);
    expect(
      within(cells[1]).getByRole('img', { name: 'Artwork for Film' })
    ).toHaveAttribute('loading', 'lazy');
    expect(cells[2]).toHaveTextContent('Film');
    expect(cells[2]).toHaveTextContent('Movie · 2020');
    expect(cells[4]).toHaveTextContent('Drama');
    expect(within(cells[9]).getByText('mkv')).toBeInTheDocument();
    expect(within(cells[9]).getByText('mp4')).toBeInTheDocument();
    expect(
      within(cells[11]).getByRole('button', {
        name: 'Preview Film',
      })
    ).toBeInTheDocument();
    expect(
      within(cells[11]).queryByRole('button', { name: 'Match Film with TMDB' })
    ).not.toBeInTheDocument();
    fireEvent.error(within(cells[1]).getByRole('img'));
    expect(within(cells[1]).queryByRole('img')).not.toBeInTheDocument();
    expect(api.vodLibraryAction).not.toHaveBeenCalled();
  });

  it('keeps exact source formats separate from the canonical format summary', async () => {
    renderUI(
      <LibraryWorkspace
        view="sources"
        onPreview={vi.fn()}
        onChanged={vi.fn()}
      />
    );
    await screen.findByText('Provider Film');
    expect(
      screen.getByRole('columnheader', { name: 'Source', exact: true })
    ).toBeInTheDocument();
    const row = screen
      .getByRole('checkbox', { name: 'Select Provider Film' })
      .closest('tr');
    const cells = within(row).getAllByRole('cell');
    expect(cells[3]).toHaveTextContent('Account');
    expect(cells[3]).toHaveTextContent('English');
    expect(cells[9]).toHaveTextContent('mkv');
    expect(cells[9]).not.toHaveTextContent('mp4');
    expect(
      within(cells[11]).getByRole('button', {
        name: 'Preview Provider Film',
      })
    ).toBeInTheDocument();
  });

  it('keeps long series names and genres wrapped and missing artwork or formats empty', async () => {
    const name = 'LongSeriesTitleWithoutSpaces'.repeat(15);
    const genre = 'LongGenreWithoutSpaces'.repeat(15);
    api.getVODLibrary.mockResolvedValue({
      results: [
        {
          ...item,
          key: 'series:2',
          content_id: 2,
          content_type: 'series',
          name,
          provider_name: name,
          genre,
          year: null,
          poster_url: '',
          metadata_summary: {
            ...item.metadata_summary,
            container_extensions: [],
          },
        },
      ],
      count: 1,
    });
    renderUI(
      <LibraryWorkspace view="titles" onPreview={vi.fn()} onChanged={vi.fn()} />
    );
    const title = await screen.findByText(name);
    const cells = within(title.closest('tr')).getAllByRole('cell');
    expect(title.className).toContain('wrappedText');
    expect(within(cells[4]).getByText(genre).className).toContain(
      'wrappedText'
    );
    expect(cells[2]).toHaveTextContent('Series · —');
    expect(cells[9]).toHaveTextContent('—');
    expect(within(cells[1]).queryByRole('img')).not.toBeInTheDocument();
  });

  it('keeps additional filters in a popover with accessible names', async () => {
    renderUI(
      <LibraryWorkspace view="titles" onPreview={vi.fn()} onChanged={vi.fn()} />
    );
    await screen.findByText('Film');
    expect(
      screen.queryByRole('textbox', { name: 'Metadata', exact: true })
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole('textbox', { name: 'Metadata protection' })
    ).not.toBeInTheDocument();
    const actions = screen.getByRole('group', { name: 'Library actions' });
    const filter = within(actions).getByRole('button', {
      name: 'Filter library',
    });
    expect(filter).not.toHaveAttribute('data-filter-active');
    expect(
      within(actions).queryByRole('button', { name: 'Library settings' })
    ).not.toBeInTheDocument();
    fireEvent.click(filter);
    expect(
      screen.getByRole('textbox', { name: 'Metadata', exact: true })
    ).toHaveAttribute('placeholder', 'Any');
    expect(
      screen.getByRole('textbox', { name: 'Metadata protection' })
    ).toHaveAttribute('placeholder', 'Protection');
    expect(api.vodLibraryAction).not.toHaveBeenCalled();
    expect(api.updateVODLibrarySettings).not.toHaveBeenCalled();
  });

  it('applies additional filters without a save and marks the active count', async () => {
    renderUI(
      <LibraryWorkspace view="titles" onPreview={vi.fn()} onChanged={vi.fn()} />
    );
    await screen.findByText('Film');
    const filter = screen.getByRole('button', { name: 'Filter library' });
    fireEvent.click(filter);
    fireEvent.click(
      screen.getByRole('textbox', { name: 'Metadata', exact: true })
    );
    fireEvent.click(await screen.findByRole('option', { name: 'No TMDB ID' }));
    fireEvent.click(
      screen.getByRole('textbox', { name: 'Metadata protection' })
    );
    fireEvent.click(await screen.findByRole('option', { name: 'Protected' }));
    await waitFor(() =>
      expect(
        api.getVODLibrary.mock.calls.some(
          ([params]) =>
            params.get('metadata_status') === 'missing_id' &&
            params.get('locked') === 'true'
        )
      ).toBe(true)
    );
    expect(filter).toHaveAttribute('data-filter-active', 'true');
    expect(filter).toHaveAccessibleDescription('2 filters active');
    expect(api.vodLibraryAction).not.toHaveBeenCalled();
    expect(api.updateVODLibrarySettings).not.toHaveBeenCalled();
  });

  it('resets popover filters and preserves search', async () => {
    useLibraryStore.setState((state) => ({
      filters: {
        ...state.filters,
        search: 'Film',
        account: '3',
        category: '4',
        locked: 'false',
        metadata_status: 'matched',
      },
    }));
    renderUI(
      <LibraryWorkspace view="titles" onPreview={vi.fn()} onChanged={vi.fn()} />
    );
    await screen.findByText('Film');
    const filter = screen.getByRole('button', { name: 'Filter library' });
    expect(filter).toHaveAccessibleDescription('4 filters active');
    fireEvent.click(filter);
    expect(
      screen.getByRole('textbox', { name: 'Metadata protection' })
    ).toHaveValue('Unlocked');
    fireEvent.click(screen.getByRole('button', { name: 'Reset filters' }));
    expect(useLibraryStore.getState().filters).toMatchObject({
      search: 'Film',
      account: '',
      category: '',
      locked: '',
      metadata_status: '',
    });
    expect(filter).not.toHaveAttribute('data-filter-active');
    expect(filter).not.toHaveAttribute('aria-description');
    expect(api.vodLibraryAction).not.toHaveBeenCalled();
  });

  it.each([
    [1, '1 title selected.'],
    [2, '2 titles selected.'],
  ])(
    'uses the correct cleanup selection label for %s titles',
    async (count) => {
      api.vodLibraryAction.mockResolvedValue({ count, results: [] });
      api.getVODLibrary.mockResolvedValue({
        results: Array.from({ length: count }, (_, index) => ({
          ...item,
          key: `movie:${index + 1}`,
          content_id: index + 1,
          name: index ? 'Second film' : 'Film',
          provider_name: index ? 'Second film' : 'Film',
        })),
        count,
      });
      renderUI(
        <LibraryWorkspace
          view="titles"
          onPreview={vi.fn()}
          onChanged={vi.fn()}
        />
      );
      await screen.findByText('Film');
      fireEvent.click(
        screen.getByRole('checkbox', { name: 'Select all matching titles' })
      );
      fireEvent.click(
        screen.getByRole('button', { name: `Edit (${count})`, exact: true })
      );
      const preview = await screen.findByRole('dialog', {
        name: `Edit selected titles (${count})`,
      });
      expect(within(preview).getByRole('heading')).toHaveTextContent(
        `Edit selected titles (${count})`
      );
      await waitFor(() =>
        expect(api.vodLibraryAction).toHaveBeenCalledTimes(1)
      );
      expect(api.vodLibraryAction.mock.calls[0][0]).toBe('cleanup-preview');
    }
  );

  it('shows canonical titles and compact source metadata tags', async () => {
    const preview = vi.fn();
    renderUI(
      <LibraryWorkspace view="titles" onPreview={preview} onChanged={vi.fn()} />
    );
    await screen.findByText('Film');
    expect(
      screen.getByRole('columnheader', { name: 'Sources' })
    ).toBeInTheDocument();
    expect(
      screen.getByText('ger').closest('[class*="language"]')
    ).not.toBeNull();
    expect(screen.getByText('Provider')).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole('button', { name: 'Preview Film', exact: true })
    );
    expect(preview).toHaveBeenCalledWith(item);
    expect(api.vodLibraryAction).not.toHaveBeenCalled();
  });
  it('uses only explicitly selected table rows and confirms a bulk change', async () => {
    renderUI(
      <LibraryWorkspace view="titles" onPreview={vi.fn()} onChanged={vi.fn()} />
    );
    await screen.findByText('Film');
    expect(
      screen.queryByRole('button', { name: 'Enrich', exact: true })
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('checkbox', { name: 'Select Film' }));
    expect(
      screen.queryByRole('button', { name: /Select all/ })
    ).not.toBeInTheDocument();
    fireEvent.click(
      screen.getByRole('button', { name: 'Edit (1)', exact: true })
    );
    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: 'Protect selected titles' })
      ).toBeEnabled()
    );
    fireEvent.click(
      screen.getByRole('button', { name: 'Protect selected titles' })
    );
    expect(
      api.vodLibraryAction.mock.calls.every(
        ([name]) => name === 'cleanup-preview'
      )
    ).toBe(true);
    fireEvent.click(
      screen.getByRole('button', { name: 'Confirm', exact: true })
    );
    await waitFor(() =>
      expect(api.vodLibraryAction).toHaveBeenCalledWith('bulk', {
        items: [{ content_type: 'movie', id: 1 }],
        operation: 'lock',
      })
    );
  });
  it('keeps source editing exact and does not offer title-wide bulk enrichment in source view', async () => {
    renderUI(
      <LibraryWorkspace
        view="sources"
        onPreview={vi.fn()}
        onChanged={vi.fn()}
      />
    );
    await screen.findByText('Account', { selector: 'p' });
    fireEvent.click(
      screen.getByRole('checkbox', { name: 'Select Provider Film' })
    );
    expect(
      screen.getByRole('button', { name: 'Edit (1)', exact: true })
    ).toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: 'Enrich', exact: true })
    ).not.toBeInTheDocument();
    expect(
      api.getVODLibrary.mock.calls.some(
        ([params]) => params.get('view') === 'sources'
      )
    ).toBe(true);
  });
  it('does not expose admin actions to ordinary users', async () => {
    auth.user.user_level = 1;
    renderUI(
      <LibraryWorkspace view="titles" onPreview={vi.fn()} onChanged={vi.fn()} />
    );
    await screen.findByText('Film');
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: 'Library settings' })
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: /Edit title metadata/ })
    ).not.toBeInTheDocument();
    expect(api.getVODLibraryState).not.toHaveBeenCalled();
  });

  it('shows a plain source count and edits the exact selected source from the toolbar', async () => {
    renderUI(
      <LibraryWorkspace
        view="sources"
        onPreview={vi.fn()}
        onChanged={vi.fn()}
      />
    );
    await screen.findByText('Provider Film');
    expect(
      screen.queryByRole('button', { name: '2', exact: true })
    ).not.toBeInTheDocument();
    fireEvent.click(
      screen.getByRole('checkbox', { name: 'Select Provider Film' })
    );
    fireEvent.click(screen.getByRole('button', { name: 'Edit (1)' }));
    expect(
      await screen.findByRole('dialog', { name: 'Edit source metadata' })
    ).toBeInTheDocument();
    expect(
      screen.getByRole('textbox', { name: 'Search Library title or TMDB ID' })
    ).toHaveValue('Film');
    fireEvent.click(
      screen.getByRole('button', { name: 'Close Edit source metadata' })
    );
    await waitFor(() =>
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    );
  });
  it('keeps background job controls out of the Library toolbar', async () => {
    api.getVODLibraryState.mockResolvedValue({
      status: 'cancelled',
      task_id: 'old',
      progress: { operation: 'cleanup', processed: 2, total: 10 },
    });
    renderUI(
      <LibraryWorkspace view="titles" onPreview={vi.fn()} onChanged={vi.fn()} />
    );
    await screen.findByText('Film');
    expect(
      screen.queryByRole('button', { name: 'Metadata job' })
    ).not.toBeInTheDocument();
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument();
    expect(api.getVODLibraryState).toHaveBeenCalledOnce();
    expect(api.vodLibraryAction).not.toHaveBeenCalled();
  });
});

describe('Library editors', () => {
  it('keeps an empty TMDB search read-only and reports missing candidates', async () => {
    api.vodLibraryAction.mockResolvedValue({ results: [] });
    renderUI(
      <LibraryContentEditor item={item} onClose={vi.fn()} onSaved={vi.fn()} />
    );
    fireEvent.click(
      screen.getByRole('button', { name: 'Search TMDB', exact: true })
    );
    await waitFor(() =>
      expect(showNotification).toHaveBeenCalledWith(
        expect.objectContaining({ color: 'orange' })
      )
    );
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: 'Save', exact: true })
    ).toBeDisabled();
    expect(api.vodLibraryAction).toHaveBeenCalledTimes(1);
    expect(api.vodLibraryAction.mock.calls[0][0]).toBe('tmdb-lookup');
  });
  it('loads TMDB candidates into the existing editor and only persists the combined draft on Save', async () => {
    const close = vi.fn();
    api.vodLibraryAction.mockImplementation(async (action) => {
      if (action !== 'tmdb-lookup') return { metadata: { id: 1 } };
      return {
        metadata: {
          id: '456',
          original_title: 'Loaded title',
          release_date: '2022-04-03',
          rating: 8,
          localized: {
            'en-US': { title: 'Loaded EN', overview: 'Loaded description' },
          },
        },
      };
    });
    renderUI(
      <LibraryContentEditor
        item={{ ...item, clean_title: 'Clean provider title' }}
        onClose={close}
        onSaved={vi.fn()}
      />
    );
    fireEvent.change(
      screen.getByRole('textbox', {
        name: 'Search title or TMDB ID',
        exact: true,
      }),
      { target: { value: 'tmdb:456' } }
    );
    fireEvent.click(
      screen.getByRole('button', { name: 'Search TMDB', exact: true })
    );
    await waitFor(() =>
      expect(
        screen.getByRole('textbox', { name: 'Title', exact: true })
      ).toHaveValue('Loaded EN')
    );
    expect(
      screen.getByRole('textbox', { name: 'Cleanup title', exact: true })
    ).toHaveValue('Clean provider title');
    expect(screen.getAllByRole('dialog')).toHaveLength(1);
    expect(api.vodLibraryAction).toHaveBeenCalledTimes(1);
    expect(api.vodLibraryAction).toHaveBeenCalledWith('tmdb-lookup', {
      content_type: 'movie',
      tmdb_id: '456',
    });
    expect(close).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText('Director / creator'), {
      target: { value: 'Curated director' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Save', exact: true }));
    const confirmation = await screen.findByRole('dialog', {
      name: 'Save this TMDB match?',
    });
    expect(api.vodLibraryAction).toHaveBeenCalledTimes(1);
    fireEvent.click(
      within(confirmation).getByRole('button', { name: 'Save', exact: true })
    );
    await waitFor(() => expect(close).toHaveBeenCalled());
    expect(api.vodLibraryAction).toHaveBeenCalledWith(
      'content',
      expect.objectContaining({
        content_type: 'movie',
        id: 1,
        tmdb_id: '456',
        display_name: '',
        clean_title: 'Clean provider title',
        year: 2022,
        metadata: expect.objectContaining({
          director: 'Curated director',
          release_date: '2022-04-03',
        }),
      }),
      'PATCH'
    );
    expect(
      api.vodLibraryAction.mock.calls.some(
        ([action]) => action === 'tmdb-match'
      )
    ).toBe(false);
  });

  it('keeps a title edited after loading a TMDB match as the manual title', async () => {
    const close = vi.fn();
    api.vodLibraryAction.mockImplementation(async (action) =>
      action === 'tmdb-lookup'
        ? {
            metadata: {
              id: '456',
              original_title: 'Loaded title',
              localized: { 'en-US': { title: 'Loaded EN' } },
            },
          }
        : { metadata: { id: 1 } }
    );
    renderUI(
      <LibraryContentEditor item={item} onClose={close} onSaved={vi.fn()} />
    );
    fireEvent.change(
      screen.getByRole('textbox', {
        name: 'Search title or TMDB ID',
        exact: true,
      }),
      { target: { value: 'tmdb:456' } }
    );
    fireEvent.click(
      screen.getByRole('button', { name: 'Search TMDB', exact: true })
    );
    const title = screen.getByRole('textbox', { name: 'Title', exact: true });
    await waitFor(() => expect(title).toHaveValue('Loaded EN'));
    fireEvent.change(title, { target: { value: 'Curated title' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save', exact: true }));
    fireEvent.click(
      within(
        await screen.findByRole('dialog', { name: 'Save this TMDB match?' })
      ).getByRole('button', { name: 'Save', exact: true })
    );
    await waitFor(() => expect(close).toHaveBeenCalled());
    expect(api.vodLibraryAction).toHaveBeenCalledWith(
      'content',
      expect.objectContaining({
        tmdb_id: '456',
        display_name: 'Curated title',
      }),
      'PATCH'
    );
  });

  it('discards loaded metadata without persisting the TMDB assignment', async () => {
    const close = vi.fn();
    api.vodLibraryAction.mockResolvedValue({
      metadata: { id: '456', original_title: 'Loaded title' },
    });
    renderUI(
      <LibraryContentEditor item={item} onClose={close} onSaved={vi.fn()} />
    );
    fireEvent.change(
      screen.getByRole('textbox', {
        name: 'Search title or TMDB ID',
        exact: true,
      }),
      { target: { value: 'tmdb:456' } }
    );
    fireEvent.click(
      screen.getByRole('button', { name: 'Search TMDB', exact: true })
    );
    await waitFor(() =>
      expect(
        screen.getByRole('textbox', { name: 'Title', exact: true })
      ).toHaveValue('Loaded title')
    );
    fireEvent.click(
      screen.getByRole('button', { name: 'Close Edit title metadata' })
    );
    fireEvent.click(
      await screen.findByRole('button', { name: 'Discard', exact: true })
    );
    expect(close).toHaveBeenCalled();
    expect(api.vodLibraryAction).toHaveBeenCalledTimes(1);
  });

  it('edits equal translations and rich metadata without sending unchanged fields or provider identity', async () => {
    const close = vi.fn();
    renderUI(
      <LibraryContentEditor
        item={{
          ...item,
          metadata_languages: ['de-DE', 'en-US'],
          metadata: {
            localized: { 'fr-FR': { title: 'Français' } },
            director: 'Original director',
          },
        }}
        onClose={close}
        onSaved={vi.fn()}
      />
    );
    expect(screen.getByRole('tab', { name: 'fr-FR' })).toBeInTheDocument();
    expect(screen.queryByText(/Primary|Secondary/)).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('de-DE · Title'), {
      target: { value: 'Deutscher Titel' },
    });
    fireEvent.change(screen.getByLabelText('Director / creator'), {
      target: { value: 'Updated director' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Save', exact: true }));
    await waitFor(() => expect(close).toHaveBeenCalled());
    expect(api.vodLibraryAction).toHaveBeenCalledWith(
      'content',
      {
        content_type: 'movie',
        id: 1,
        metadata: {
          localized: { 'de-DE': { title: 'Deutscher Titel' } },
          director: 'Updated director',
        },
      },
      'PATCH'
    );
  });
  it('disables save until changed and keeps the editor visible behind discard confirmation', async () => {
    const close = vi.fn();
    renderUI(
      <LibraryContentEditor item={item} onClose={close} onSaved={vi.fn()} />
    );
    expect(
      screen.getByRole('button', { name: 'Save', exact: true })
    ).toBeDisabled();
    fireEvent.change(
      screen.getByRole('textbox', { name: 'Title', exact: true }),
      { target: { value: 'Updated' } }
    );
    fireEvent.click(
      screen.getByRole('button', { name: 'Close Edit title metadata' })
    );
    expect(
      await screen.findByRole('dialog', { name: 'Discard unsaved changes?' })
    ).toBeInTheDocument();
    expect(
      screen.getByRole('textbox', { name: 'Title', exact: true, hidden: true })
    ).toHaveValue('Updated');
    fireEvent.click(screen.getByRole('button', { name: 'Continue editing' }));
    expect(close).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Save', exact: true }));
    await waitFor(() =>
      expect(api.vodLibraryAction).toHaveBeenCalledWith(
        'content',
        expect.objectContaining({ id: 1, display_name: 'Updated' }),
        'PATCH'
      )
    );
  });
  it('restores inherited source metadata without touching other source IDs', async () => {
    renderUI(
      <LibrarySourceEditor
        items={[source]}
        onClose={vi.fn()}
        onSaved={vi.fn()}
      />
    );
    expect(
      screen.getByRole('button', { name: 'Save', exact: true })
    ).toBeDisabled();
    fireEvent.click(
      screen.getByRole('button', { name: 'Reset DUB languages override' })
    );
    expect(screen.getByText('Inherit')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Save', exact: true }));
    await waitFor(() =>
      expect(api.vodLibraryAction).toHaveBeenCalledWith(
        'source-metadata',
        {
          items: [{ content_type: 'movie', id: 5 }],
          manual_metadata: { audio_languages: null },
        },
        'PATCH'
      )
    );
  });
  it('does not expose moving or creating titles in source bulk editing', async () => {
    const onClose = vi.fn();
    renderUI(
      <LibrarySourceEditor
        items={[source, { ...source, source_id: 6 }]}
        onClose={onClose}
        onSaved={vi.fn()}
      />
    );
    expect(screen.queryByText('Move to title')).not.toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: 'Create title from this source' })
    ).not.toBeInTheDocument();
    expect(api.vodLibraryAction).not.toHaveBeenCalled();
    expect(api.getVODCanonicalTargets).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();
  });
  it('keeps the canonical target draft when confirmation is cancelled', async () => {
    renderUI(
      <LibrarySourceEditor
        items={[source]}
        onClose={vi.fn()}
        onSaved={vi.fn()}
      />
    );
    await chooseTarget();
    fireEvent.click(
      await screen.findByRole('button', { name: 'Cancel', exact: true })
    );
    expect(
      screen.getByRole('button', { name: 'Move', exact: true })
    ).toBeInTheDocument();
    expect(api.vodLibraryAction).not.toHaveBeenCalled();
  });
  it('disables TMDB reassignment for a mixed movie and series selection', () => {
    renderUI(
      <LibrarySourceEditor
        items={[source, { ...source, source_id: 6, content_type: 'series' }]}
        onClose={vi.fn()}
        onSaved={vi.fn()}
      />
    );
    expect(
      screen.queryByRole('textbox', { name: 'Search Library title or TMDB ID' })
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: 'Save', exact: true })
    ).toBeDisabled();
  });
  it('previews TMDB metadata before requiring confirmation for source reassignment', async () => {
    api.vodLibraryAction
      .mockResolvedValueOnce({
        metadata: {
          id: '123',
          original_title: 'Original title',
          localized: {
            'de-DE': { title: 'Treffer', overview: 'Beschreibung' },
            'en-US': { title: 'Match', overview: 'Description' },
            'es-ES': { title: 'Coincidencia', overview: 'Descripción' },
          },
        },
      })
      .mockResolvedValue({ count: 1 });
    renderUI(
      <LibraryMatchDialog item={source} onClose={vi.fn()} onSaved={vi.fn()} />
    );
    fireEvent.change(
      screen.getByRole('textbox', { name: 'Search title or TMDB ID' }),
      {
        target: { value: 'tmdb:123' },
      }
    );
    fireEvent.click(
      screen.getByRole('button', { name: 'Search', exact: true })
    );
    await screen.findByText('Match');
    expect(screen.getByText('Original title')).toBeInTheDocument();
    for (const language of ['de-DE', 'en-US', 'es-ES']) {
      expect(screen.getByText(language)).toBeInTheDocument();
    }
    expect(screen.getByText('Treffer')).toBeInTheDocument();
    expect(screen.getByText('Descripción')).toBeInTheDocument();
    expect(api.vodLibraryAction).toHaveBeenCalledTimes(1);
    fireEvent.click(
      screen.getByRole('button', { name: 'Use match', exact: true })
    );
    const confirmation = screen.getByRole('dialog', {
      name: 'Use this TMDB match?',
    });
    fireEvent.click(
      within(confirmation).getByRole('button', {
        name: 'Use match',
        exact: true,
      })
    );
    await waitFor(() =>
      expect(api.vodLibraryAction).toHaveBeenCalledWith('tmdb-match', {
        content_type: 'movie',
        id: 5,
        source: true,
        tmdb_id: '123',
      })
    );
  });
  it.each([
    [false, 'movie'],
    [true, 'movie'],
    [false, 'series'],
    [true, 'series'],
  ])(
    'keeps TMDB results and an external inspection link inside the search box (embedded=%s, type=%s)',
    async (embedded, content_type) => {
      api.vodLibraryAction.mockResolvedValue({
        results: [{ id: '123', title: 'Matching title', year: 2020 }],
      });
      renderUI(
        <LibraryMatchDialog
          item={{ ...source, content_type }}
          embedded={embedded}
          onClose={vi.fn()}
          onSaved={vi.fn()}
        />
      );
      fireEvent.click(
        screen.getByRole('button', {
          name: embedded ? 'Search TMDB' : 'Search',
          exact: true,
        })
      );
      const results = await screen.findByRole('table', {
        name: 'TMDB search results',
      });
      const box = screen
        .getByRole('textbox', { name: 'Search title or TMDB ID' })
        .closest('.mantine-Paper-root');
      expect(box).toContainElement(results);
      expect(
        within(results).getByRole('columnheader', { name: 'Actions' })
      ).toHaveStyle({ textAlign: 'center' });
      expect(within(results).getByText('Matching title')).toBeInTheDocument();
      const link = within(results).getByRole('link', {
        name: 'Open Matching title on TMDB',
      });
      expect(link).toHaveAttribute(
        'href',
        `https://www.themoviedb.org/${content_type === 'series' ? 'tv' : 'movie'}/123`
      );
      expect(link).toHaveAttribute('target', '_blank');
      expect(link).toHaveAttribute('rel', 'noopener noreferrer');
      expect(
        within(results).getByRole('button', {
          name: embedded ? 'Load' : 'Preview',
          exact: true,
        })
      ).toBeEnabled();
      expect(api.vodLibraryAction).toHaveBeenCalledTimes(1);
    }
  );
  it('shows lookup failures as a notification and red field, not an inline banner', async () => {
    api.vodLibraryAction.mockRejectedValue(
      new Error('A TMDB API token is required')
    );
    renderUI(
      <LibraryContentEditor item={item} onClose={vi.fn()} onSaved={vi.fn()} />
    );
    fireEvent.click(
      screen.getByRole('button', { name: 'Search TMDB', exact: true })
    );
    await waitFor(() =>
      expect(showNotification).toHaveBeenCalledWith(
        expect.objectContaining({
          message: 'A TMDB API token is required',
          color: 'red',
        })
      )
    );
    expect(
      screen.getByRole('textbox', { name: 'Search title or TMDB ID' })
    ).toHaveAttribute('aria-invalid', 'true');
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Search TMDB ID')).not.toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: 'Save', exact: true })
    ).toBeDisabled();
  });
  it('retains rejected title edits and marks only the rejected field', async () => {
    api.vodLibraryAction.mockRejectedValue({
      status: 400,
      body: { display_name: ['Invalid title.'] },
    });
    const onClose = vi.fn();
    renderUI(
      <LibraryContentEditor item={item} onClose={onClose} onSaved={vi.fn()} />
    );
    fireEvent.change(
      screen.getByRole('textbox', { name: 'Title', exact: true }),
      { target: { value: 'Draft' } }
    );
    fireEvent.click(screen.getByRole('button', { name: 'Save', exact: true }));
    await waitFor(() =>
      expect(showNotification).toHaveBeenCalledWith(
        expect.objectContaining({ color: 'red' })
      )
    );
    expect(
      screen.getByRole('textbox', { name: 'Title', exact: true })
    ).toHaveAttribute('aria-invalid', 'true');
    expect(screen.getByLabelText('Cleanup title')).not.toHaveAttribute(
      'aria-invalid',
      'true'
    );
    expect(onClose).not.toHaveBeenCalled();
  });
  it('creates a title with an editable name and year only after confirmation', async () => {
    renderUI(
      <LibrarySourceEditor
        items={[source]}
        onClose={vi.fn()}
        onSaved={vi.fn()}
      />
    );
    fireEvent.click(
      screen.getByRole('button', { name: 'Create title from this source' })
    );
    fireEvent.change(screen.getByRole('textbox', { name: 'Title name' }), {
      target: { value: 'Curated title' },
    });
    expect(api.vodLibraryAction).not.toHaveBeenCalled();
    fireEvent.click(
      screen.getByRole('button', { name: 'Create', exact: true })
    );
    fireEvent.click(
      await screen.findByRole('button', { name: 'Create and move' })
    );
    await waitFor(() =>
      expect(api.vodLibraryAction).toHaveBeenCalledWith(
        'source-metadata',
        {
          items: [{ content_type: 'movie', id: 5 }],
          create_from_provider: true,
          title_name: 'Curated title',
          title_year: 2020,
        },
        'PATCH'
      )
    );
  });
  it('can resolve a new explicit TMDB ID through the same source search field', async () => {
    api.getVODCanonicalTargets.mockResolvedValue({ results: [] });
    api.vodLibraryAction.mockResolvedValue({
      metadata: { id: '456', original_title: 'External Film' },
    });
    renderUI(
      <LibrarySourceEditor
        items={[source]}
        onClose={vi.fn()}
        onSaved={vi.fn()}
      />
    );
    fireEvent.change(
      screen.getByRole('textbox', { name: 'Search Library title or TMDB ID' }),
      { target: { value: 'tmdb:456' } }
    );
    await chooseTarget();
    expect(api.vodLibraryAction).toHaveBeenCalledWith('tmdb-lookup', {
      content_type: 'movie',
      tmdb_id: '456',
    });
    fireEvent.click(
      within(screen.getByRole('dialog', { name: 'Move to title?' })).getByRole(
        'button',
        { name: 'Move', exact: true }
      )
    );
    await waitFor(() =>
      expect(api.vodLibraryAction).toHaveBeenCalledWith(
        'source-metadata',
        {
          items: [{ content_type: 'movie', id: 5 }],
          tmdb_id: '456',
        },
        'PATCH'
      )
    );
  });
  it('does not offer reassignment to the current canonical title', async () => {
    api.getVODCanonicalTargets.mockResolvedValue({
      results: [{ id: 1, name: 'Film', source_count: 1 }],
    });
    renderUI(
      <LibrarySourceEditor
        items={[source]}
        onClose={vi.fn()}
        onSaved={vi.fn()}
      />
    );
    fireEvent.click(
      screen.getByRole('button', { name: 'Search', exact: true })
    );
    expect(
      await screen.findByRole('button', { name: 'Current' })
    ).toBeDisabled();
    expect(
      screen.getByRole('button', { name: 'Save', exact: true })
    ).toBeDisabled();
  });
  it('moves one source independently and retains unsaved metadata in the editor', async () => {
    api.vodLibraryAction.mockResolvedValue({
      count: 1,
      metadata: { id: 2, name: 'Correct Film' },
    });
    const onClose = vi.fn();
    renderUI(
      <LibrarySourceEditor
        items={[source]}
        onClose={onClose}
        onSaved={vi.fn()}
      />
    );
    fireEvent.click(
      screen.getByRole('button', { name: 'Reset DUB languages override' })
    );
    await chooseTarget();
    const confirmation = screen.getByRole('dialog', { name: 'Move to title?' });
    expect(
      within(confirmation).getByText(/Unsaved source metadata will be kept/)
    ).toBeInTheDocument();
    fireEvent.click(
      within(confirmation).getByRole('button', { name: 'Move', exact: true })
    );
    await waitFor(() =>
      expect(api.vodLibraryAction).toHaveBeenCalledWith(
        'source-metadata',
        {
          items: [{ content_type: 'movie', id: 5 }],
          target_id: 2,
        },
        'PATCH'
      )
    );
    await waitFor(() =>
      expect(
        screen.queryByRole('dialog', { name: 'Move to title?' })
      ).not.toBeInTheDocument()
    );
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByText('Inherit')).toBeInTheDocument();
    expect(screen.getByText('Current: Correct Film')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Save', exact: true }));
    await waitFor(() =>
      expect(api.vodLibraryAction).toHaveBeenLastCalledWith(
        'source-metadata',
        {
          items: [{ content_type: 'movie', id: 5 }],
          manual_metadata: { audio_languages: null },
        },
        'PATCH'
      )
    );
    expect(onClose).toHaveBeenCalledOnce();
  });
  it('distinguishes a provider-supplied TMDB ID from enriched metadata', async () => {
    api.getVODLibrary.mockResolvedValue({
      results: [
        { ...item, tmdb_id: '42' },
        {
          ...item,
          key: 'movie:2',
          content_id: 2,
          name: 'Enriched film',
          provider_name: 'Enriched film',
          tmdb_id: '43',
          enriched_at: '2026-10-31T00:00:00Z',
        },
      ],
      count: 2,
    });
    renderUI(<LibraryWorkspace view="titles" onPreview={vi.fn()} />);
    await screen.findByText('Enriched film');
    expect(
      within(
        screen.getByRole('checkbox', { name: 'Select Film' }).closest('tr')
      ).getByText('Provider')
    ).toBeInTheDocument();
    expect(
      within(
        screen
          .getByRole('checkbox', { name: 'Select Enriched film' })
          .closest('tr')
      ).getByText('TMDB')
    ).toBeInTheDocument();
  });
  it('shows metadata protection beside the preview instead of inline editing actions', async () => {
    api.getVODLibrary.mockResolvedValue({
      results: [{ ...item, metadata_locked: true }],
      count: 1,
    });
    renderUI(<LibraryWorkspace view="titles" onPreview={vi.fn()} />);
    expect(
      await screen.findByRole('button', { name: 'Preview Film' })
    ).toBeEnabled();
    expect(
      screen.getByLabelText('Automatic metadata matching locked')
    ).toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: /Edit title metadata/ })
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: 'Match Film with TMDB' })
    ).not.toBeInTheDocument();
  });
});
