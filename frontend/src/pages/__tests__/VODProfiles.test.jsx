import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import { MantineProvider } from '@mantine/core';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import VODProfilesPage from '../VODProfiles';
import useScreenshotMode from '../../store/useScreenshotMode.js';
import api from '../../api';
import { showNotification } from '../../utils/notificationUtils.js';

vi.mock('../../components/LibraryPreviewModal.jsx', () => ({
  default: ({ item, sourceNotes }) => (
    <div role="dialog" aria-label="Library preview">
      {JSON.stringify({ item, sourceNotes })}
    </div>
  ),
}));
vi.mock('../../utils/notificationUtils.js', () => ({
  showNotification: vi.fn(),
  updateNotification: vi.fn(),
  hideNotification: vi.fn(),
}));
const auth = vi.hoisted(() => ({ user: { user_level: 10 } }));
vi.mock('../../store/auth', () => ({ default: (selector) => selector(auth) }));
const rulesApi = vi.hoisted(() => ({
  getM3URules: vi.fn(),
  analyzeM3URules: vi.fn(),
}));
vi.mock('../../api', () => ({
  default: {
    getVODProfiles: vi.fn(),
    getVODProfile: vi.fn(),
    vodProfileRules: vi.fn(() => rulesApi),
    getVODProfileOptions: vi.fn(),
    saveVODProfile: vi.fn(),
    deleteVODProfile: vi.fn(),
    rebuildVODProfile: vi.fn(),
    previewVODProfile: vi.fn(),
  },
}));

const profile = (fields = {}) => ({
  id: 1,
  name: 'Default',
  is_default: true,
  is_active: true,
  output_mode: 'compact',
  output_groups: 'provider',
  name_template: '{title} [{dub} · {resolution} · {features}]',
  title_source: 'provider',
  metadata_source: 'provider',
  category_choices: [],
  category_rule_states: { 11: true, 12: true },
  category_rule_counts: { movie: 1, series: 1 },
  content_filters: {},
  excluded_titles: [],
  edition_rules: [],
  ranking: ['provider'],
  audio_language_order: [],
  subtitle_language_order: [],
  provider_order: [],
  users: [],
  catalog_status: 'ready',
  catalog_counts: {
    movie: { titles: 33163, entries: 36727 },
    series: { titles: 5712, entries: 6106 },
  },
  catalog_started_at: '2026-11-03T08:00:00Z',
  catalog_progress: {},
  catalog_completed_at: '2026-11-03T08:00:07.9Z',
  catalog_error: '',
  ...fields,
});

const options = {
  users: [
    { id: 7, name: 'kid' },
    { id: 8, name: 'guest' },
  ],
  accounts: [{ id: 3, name: 'Provider' }],
  categories: [
    {
      id: 11,
      category: 101,
      name: 'DE | Kids',
      category_type: 'movie',
      account: 3,
      enabled: true,
      custom_properties: { audio_languages: ['ger'] },
    },
    {
      id: 12,
      category: 102,
      name: 'EN | Action',
      category_type: 'movie',
      account: 3,
      enabled: true,
      custom_properties: {},
    },
  ],
  languages: [
    { value: 'ger', label: 'German (ger)' },
    { value: 'eng', label: 'English (eng)' },
  ],
  metadata_languages: ['en-US', 'de-DE'],
  resolutions: ['2160p', '1080p', '720p', 'SD'],
  video_features: ['3d', 'dv', 'hdr'],
};

const renderPage = () =>
  render(
    <MantineProvider>
      <MemoryRouter initialEntries={['/vods/profiles']}>
        <Routes>
          <Route path="/vods/profiles" element={<VODProfilesPage />} />
          <Route path="/channels" element={<div>Channels</div>} />
        </Routes>
      </MemoryRouter>
    </MantineProvider>
  );

describe('VODProfilesPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    auth.user = { user_level: 10 };
    api.getVODProfileOptions.mockResolvedValue(options);
  });

  it('shows one card per profile with its catalogue state', async () => {
    api.getVODProfiles.mockResolvedValue([
      profile(),
      profile({
        id: 2,
        name: 'Kids',
        is_default: false,
        users: [7],
        title_source: 'de-DE',
        name_template: '{title} ({year})',
        content_filters: { audio_languages: ['ger'], adult_mode: 'exclude' },
        excluded_titles: [{ content_type: 'movie', id: 5 }],
        edition_rules: [{ title_suffix: '4K' }],
        category_choices: [{ relation: 12, enabled: false }],
        catalog_status: 'failed',
        catalog_error: 'Database unavailable',
        catalog_counts: {},
      }),
    ]);
    renderPage();
    const defaultCard = await screen.findByLabelText('Default profile');
    expect(within(defaultCard).getByText('Ready')).toBeTruthy();
    expect(
      within(defaultCard).getByRole('switch', { name: 'Enable Default' })
    ).toBeDisabled();
    expect(await within(defaultCard).findByText('2 of 2 enabled')).toBeTruthy();
    expect(
      within(defaultCard).getByText('Compact · Provider categories')
    ).toBeTruthy();
    expect(
      within(defaultCard).getByText(
        'Format: {title} [{dub} · {resolution} · {features}]'
      )
    ).toBeTruthy();
    expect(
      within(defaultCard).getByText('Example: Sintel [ENG · 1080p · HDR]')
    ).toBeTruthy();
    expect(
      within(defaultCard).getByText('Entries: 36,727 movies · 6,106 series')
    ).toBeTruthy();
    expect(
      within(defaultCard).getByText('Titles: 33,163 movies · 5,712 series')
    ).toBeTruthy();
    expect(within(defaultCard).getByText(/^Built in 7\.9 s · /)).toBeTruthy();
    expect(
      within(defaultCard).getByRole('button', { name: 'Delete Default' })
    ).toBeDisabled();
    const kids = screen.getByLabelText('Kids profile');
    expect(within(kids).queryByText(/user/)).toBeNull();
    // Content filters are only shown in the editor, not on the card.
    expect(within(kids).queryByText('Content')).toBeNull();
    expect(within(kids).getByText('Failed')).toBeTruthy();
    expect(within(kids).getByText('1 of 2 enabled')).toBeTruthy();
    expect(within(kids).getByText('Editions: 4K')).toBeTruthy();
    expect(
      within(kids).getByText('Title: German (de-DE) · Metadata: Provider')
    ).toBeTruthy();
    expect(within(kids).getByText('Example: Sintel (2010)')).toBeTruthy();
    expect(within(kids).getByText('Database unavailable')).toBeTruthy();
  });

  it('prepares, disables and deletes a profile from its card', async () => {
    const kids = profile({ id: 2, name: 'Kids', is_default: false });
    api.getVODProfiles.mockResolvedValue([kids]);
    api.rebuildVODProfile.mockResolvedValue({
      ...kids,
      catalog_status: 'building',
      catalog_progress: { titles: 1200 },
    });
    api.saveVODProfile.mockResolvedValue({ ...kids, is_active: false });
    api.deleteVODProfile.mockResolvedValue(null);
    renderPage();
    fireEvent.click(
      await screen.findByRole('button', { name: 'Prepare Kids' })
    );
    await waitFor(() => expect(api.rebuildVODProfile).toHaveBeenCalledWith(2));
    // Preparation is reported as a notification, like an M3U refresh.
    expect(showNotification).toHaveBeenCalledWith(
      expect.objectContaining({
        id: 'vod-profile-catalog-2',
        title: 'Preparing Kids',
        message: '1,200 titles prepared…',
        loading: true,
      })
    );
    fireEvent.click(screen.getByRole('switch', { name: 'Enable Kids' }));
    await waitFor(() =>
      expect(api.saveVODProfile).toHaveBeenCalledWith({ is_active: false }, 2)
    );
    fireEvent.click(screen.getByRole('button', { name: 'Delete Kids' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Delete' }));
    await waitFor(() => expect(api.deleteVODProfile).toHaveBeenCalledWith(2));
    expect(showNotification).toHaveBeenCalledWith(
      expect.objectContaining({ title: 'Deleted Kids' })
    );
  });

  it('creates a profile and returns server errors to their tab', async () => {
    api.getVODProfiles.mockResolvedValue([profile()]);
    api.saveVODProfile
      .mockRejectedValueOnce({
        status: 400,
        body: { ranking: ['Use only supported ranking criteria.'] },
      })
      .mockResolvedValueOnce(
        profile({ id: 2, name: 'Kids', catalog_status: 'pending' })
      );
    renderPage();
    fireEvent.click(await screen.findByRole('button', { name: 'Add profile' }));
    const dialog = await screen.findByRole('dialog');
    fireEvent.change(
      within(dialog).getByRole('textbox', { name: /^Name\s*\*?$/ }),
      {
        target: { value: 'Kids' },
      }
    );
    expect(
      within(dialog).getByText('Example: Sintel [ENG · 1080p · HDR]')
    ).toBeTruthy();
    expect(within(dialog).queryByText(/tags/)).toBeNull();
    fireEvent.click(
      within(dialog).getByRole('button', { name: 'Insert year' })
    );
    expect(
      within(dialog).getByText('Example: Sintel [ENG · 1080p · HDR] 2010')
    ).toBeTruthy();
    fireEvent.click(within(dialog).getByRole('button', { name: 'Save' }));
    expect(
      await within(dialog).findByText('Use only supported ranking criteria.')
    ).toBeTruthy();
    expect(
      within(dialog).getByRole('tab', { name: 'Failover', selected: true })
    ).toBeTruthy();
    expect(api.saveVODProfile).toHaveBeenCalledWith(
      expect.objectContaining({
        name: 'Kids',
        name_template: '{title} [{dub} · {resolution} · {features}] {year}',
        ranking: ['provider'],
      }),
      undefined
    );
    fireEvent.click(within(dialog).getByRole('button', { name: 'Save' }));
    await waitFor(() =>
      expect(showNotification).toHaveBeenCalledWith(
        expect.objectContaining({ title: 'Saved Kids' })
      )
    );
  });

  it('shows field problems while editing and blocks saving', async () => {
    api.getVODProfiles.mockResolvedValue([profile()]);
    renderPage();
    fireEvent.click(
      await screen.findByRole('button', { name: 'Edit Default' })
    );
    const dialog = await screen.findByRole('dialog');
    fireEvent.change(within(dialog).getByRole('textbox', { name: 'Format' }), {
      target: { value: '{title} {quality}' },
    });
    expect(
      within(dialog).getByText('Unsupported placeholders: {quality}')
    ).toBeTruthy();
    fireEvent.click(within(dialog).getByRole('tab', { name: 'Editions' }));
    // Leaving a blank edition asks first, like unsaved M3U rules.
    fireEvent.click(
      within(dialog).getByRole('button', { name: 'Add edition' })
    );
    fireEvent.click(within(dialog).getByRole('tab', { name: 'Content' }));
    expect(
      await screen.findByText(
        'Discard unsaved changes? The affected rows are highlighted.'
      )
    ).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Keep editing' }));
    expect(
      within(dialog).getByRole('tab', { name: 'Editions', selected: true })
    ).toBeTruthy();
    fireEvent.click(within(dialog).getByRole('tab', { name: 'Content' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Discard' }));
    expect(
      within(dialog).getByRole('tab', { name: 'Content', selected: true })
    ).toBeTruthy();
    fireEvent.click(within(dialog).getByRole('tab', { name: 'Editions' }));
    expect(within(dialog).getByText(/No editions/)).toBeTruthy();
    fireEvent.click(
      within(dialog).getByRole('button', { name: 'Add edition' })
    );
    fireEvent.change(
      within(dialog).getByRole('textbox', { name: 'Edition 1 suffix' }),
      { target: { value: 'Extended' } }
    );
    expect(
      within(dialog).getByText('Give each edition at least one condition.')
    ).toBeTruthy();
    fireEvent.click(within(dialog).getByRole('button', { name: 'Save' }));
    expect(
      within(dialog).getByRole('tab', { name: 'General', selected: true })
    ).toBeTruthy();
    expect(showNotification).toHaveBeenCalledWith(
      expect.objectContaining({ title: 'Profile not saved' })
    );
    expect(api.saveVODProfile).not.toHaveBeenCalled();
  });

  it('previews unsaved settings', async () => {
    api.getVODProfiles.mockResolvedValue([profile()]);
    api.previewVODProfile.mockResolvedValue({
      count: 2,
      results: [
        {
          id: 1,
          title: 'Film',
          year: 2020,
          reason: '',
          excluded: false,
          entries: [
            {
              name: 'Film [GER · 2160p]',
              source_id: 21,
              fallbacks: [21],
              edition: '',
              provider: 'Provider',
              category: 'DE | Kids',
              metadata: { audio_languages: ['ger'], resolution: '2160p' },
              sources: 2,
            },
          ],
          sources: [
            {
              id: 21,
              provider: 'Provider',
              category: 'DE | Kids',
              metadata: { audio_languages: ['ger'], resolution: '2160p' },
              entry: 'Film [GER · 2160p]',
              state: 'selected',
              reason: '',
            },
            {
              id: 22,
              provider: 'Backup',
              category: 'EN | Action',
              metadata: { audio_languages: ['eng'] },
              entry: '',
              state: 'skipped',
              reason: 'Does not match the content filters.',
            },
          ],
        },
        {
          id: 2,
          title: 'Other',
          year: null,
          reason: 'No source matches the content filters.',
          excluded: false,
          entries: [],
          sources: [],
        },
      ],
    });
    renderPage();
    fireEvent.click(
      await screen.findByRole('button', { name: 'Edit Default' })
    );
    const dialog = await screen.findByRole('dialog');
    fireEvent.click(within(dialog).getByRole('tab', { name: 'Preview' }));
    expect(await within(dialog).findByText('Film [GER · 2160p]')).toBeTruthy();
    expect(within(dialog).getByText('2 movies')).toBeTruthy();
    expect(within(dialog).queryByText('Offered')).toBeNull();
    // Titles the profile does not offer are greyed out, like in the Library.
    const other = within(dialog).getByText('Other').closest('tr');
    expect(other.getAttribute('aria-disabled')).toBe('true');
    expect(api.previewVODProfile).toHaveBeenCalledWith(
      expect.objectContaining({
        content_type: 'movie',
        profile_id: 1,
        page: 1,
        page_size: 25,
        excluded: false,
      })
    );
    fireEvent.click(
      within(dialog).getByRole('button', { name: 'Open Film (2020)' })
    );
    const library = await screen.findByRole('dialog', {
      name: 'Library preview',
    });
    expect(JSON.parse(library.textContent)).toEqual({
      item: {
        content_type: 'movie',
        content_id: 1,
        source_id: 21,
        name: 'Film',
      },
      sourceNotes: {
        21: { order: 1 },
        22: {
          label: 'Excluded',
          reason: 'Does not match the content filters.',
        },
      },
    });
    fireEvent.click(
      within(dialog).getByRole('button', { name: 'Filter titles' })
    );
    expect(
      (await screen.findAllByLabelText('M3U account')).length
    ).toBeGreaterThan(0);
    fireEvent.click(
      within(dialog).getByRole('button', { name: 'Exclude Film (2020)' })
    );
    await waitFor(() =>
      expect(api.previewVODProfile).toHaveBeenLastCalledWith(
        expect.objectContaining({
          profile: expect.objectContaining({
            excluded_titles: [{ content_type: 'movie', id: 1 }],
          }),
        })
      )
    );
    expect(within(dialog).queryByText(/Excluded titles/)).toBeNull();
  });

  it('chooses categories like the M3U account selection', async () => {
    api.getVODProfiles.mockResolvedValue([profile()]);
    api.saveVODProfile.mockResolvedValue(profile());
    renderPage();
    fireEvent.click(
      await screen.findByRole('button', { name: 'Edit Default' })
    );
    const dialog = await screen.findByRole('dialog');
    fireEvent.click(within(dialog).getByRole('tab', { name: 'Categories' }));
    expect(
      within(dialog).getByText(
        'Categories without a matching rule are disabled.'
      )
    ).toBeTruthy();
    fireEvent.click(
      within(dialog).getByRole('button', {
        name: 'Disable category EN | Action',
      })
    );
    expect(
      within(dialog).getByRole('button', {
        name: 'Enable category EN | Action',
      })
    ).toBeTruthy();
    expect(within(dialog).getByText('ger')).toBeTruthy();
    fireEvent.click(within(dialog).getByRole('button', { name: 'Save' }));
    await waitFor(() =>
      expect(api.saveVODProfile).toHaveBeenCalledWith(
        expect.objectContaining({
          category_choices: [{ relation: 12, enabled: false }],
        }),
        1
      )
    );
    expect(api.saveVODProfile.mock.calls[0][0]).not.toHaveProperty('users');
    expect(api.saveVODProfile.mock.calls[0][0]).not.toHaveProperty(
      'category_rule_states'
    );
  });

  it('opens the M3U import rules for a saved profile only', async () => {
    rulesApi.getM3URules.mockResolvedValue([]);
    api.getVODProfile.mockResolvedValue(profile());
    api.getVODProfiles.mockResolvedValue([profile()]);
    renderPage();
    fireEvent.click(await screen.findByRole('button', { name: 'Add profile' }));
    let dialog = await screen.findByRole('dialog');
    fireEvent.click(within(dialog).getByRole('tab', { name: 'Categories' }));
    expect(
      within(dialog).getByRole('button', { name: 'Import rules' })
    ).toBeDisabled();
    fireEvent.click(within(dialog).getByRole('button', { name: /close/i }));
    fireEvent.click(
      await screen.findByRole('button', { name: 'Edit Default' })
    );
    dialog = await screen.findByRole('dialog');
    fireEvent.click(within(dialog).getByRole('tab', { name: 'Categories' }));
    fireEvent.click(
      within(dialog).getByRole('button', { name: 'Import rules (1)' })
    );
    await waitFor(() =>
      expect(rulesApi.getM3URules).toHaveBeenCalledWith(
        'vod-profile-1',
        'group-rules',
        'movie'
      )
    );
    expect(api.vodProfileRules).toHaveBeenCalledWith(1);
  });

  it('orders the failover criteria and their preferences', async () => {
    api.getVODProfiles.mockResolvedValue([profile()]);
    api.saveVODProfile.mockResolvedValue(profile());
    renderPage();
    fireEvent.click(
      await screen.findByRole('button', { name: 'Edit Default' })
    );
    const dialog = await screen.findByRole('dialog');
    fireEvent.click(within(dialog).getByRole('tab', { name: 'Failover' }));
    fireEvent.click(
      within(dialog).getByRole('switch', { name: 'Use Resolution' })
    );
    fireEvent.click(
      within(dialog).getByRole('switch', { name: 'Use Provider order' })
    );
    fireEvent.click(within(dialog).getByRole('button', { name: 'Save' }));
    await waitFor(() =>
      expect(api.saveVODProfile).toHaveBeenCalledWith(
        expect.objectContaining({ ranking: ['resolution_desc'] }),
        1
      )
    );
  });

  it('keeps editions and failover for Compact entries only', async () => {
    api.getVODProfiles.mockResolvedValue([profile()]);
    api.saveVODProfile.mockResolvedValue(profile());
    renderPage();
    fireEvent.click(
      await screen.findByRole('button', { name: 'Edit Default' })
    );
    const dialog = await screen.findByRole('dialog');
    fireEvent.click(within(dialog).getAllByText('Sources')[0]);
    fireEvent.click(within(dialog).getByText('Movie & Series'));
    fireEvent.click(within(dialog).getByText('Enriched'));
    // Every source is its own entry, so editions and failover do not apply.
    expect(
      within(dialog).getByRole('tab', { name: 'Editions' })
    ).toBeDisabled();
    expect(
      within(dialog).getByRole('tab', { name: 'Failover' })
    ).toBeDisabled();
    fireEvent.click(within(dialog).getByRole('button', { name: 'Save' }));
    await waitFor(() =>
      expect(api.saveVODProfile).toHaveBeenCalledWith(
        expect.objectContaining({
          output_mode: 'variants',
          output_groups: 'movie_series',
          metadata_source: 'enriched',
          title_source: 'provider',
        }),
        1
      )
    );
  });

  it('lists the users that receive a profile', async () => {
    api.getVODProfiles.mockResolvedValue([
      profile(),
      profile({ id: 2, name: 'Kids', is_default: false, users: [7] }),
    ]);
    renderPage();
    fireEvent.click(
      await screen.findByRole('button', { name: 'Edit Default' })
    );
    const dialog = await screen.findByRole('dialog');
    fireEvent.click(within(dialog).getByRole('tab', { name: 'Users' }));
    expect(within(dialog).getByText('guest')).toBeTruthy();
    expect(within(dialog).getByText('No active profile assigned')).toBeTruthy();
    expect(within(dialog).queryByText('kid')).toBeNull();
    // Screenshot mode hides usernames, as in the user list.
    act(() => useScreenshotMode.setState({ enabled: true }));
    expect(within(dialog).queryByText('guest')).toBeNull();
    act(() => useScreenshotMode.setState({ enabled: false }));
  });

  it('redirects users who cannot manage profiles', async () => {
    auth.user = { user_level: 1 };
    renderPage();
    expect(await screen.findByText('Channels')).toBeTruthy();
    expect(api.getVODProfiles).not.toHaveBeenCalled();
  });
});
