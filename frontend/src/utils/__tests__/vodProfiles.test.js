import { describe, expect, it } from 'vitest';
import {
  buildDuration,
  categoryRows,
  countsText,
  exampleName,
  fieldError,
  profileErrors,
  profilePayload,
  profileValidation,
  resolutionOptions,
  setCategoryChoices,
} from '../vodProfiles';

describe('vodProfiles', () => {
  it('formats the example like the server', () => {
    const template = '{title} [{dub} · {resolution} · {features}]';
    expect(exampleName(template)).toBe('Sintel [ENG · 1080p · HDR]');
    expect(exampleName('{title} [{edition} · {sub}] ({provider} | )')).toBe(
      'Sintel [GER] (Provider)'
    );
    expect(exampleName('{title} ({year}) {edition}')).toBe('Sintel (2010)');
    expect(exampleName(template, '4K')).toBe('Sintel 4K [ENG · 1080p · HDR]');
    expect(exampleName('{title} - {unknown}')).toBe('Sintel');
  });

  it('summarizes counts and build time', () => {
    const counts = {
      movie: { titles: 1200, entries: 1350 },
      series: { titles: 1, entries: 2 },
    };
    expect(countsText(counts)).toBe('1,200 movies · 1 series');
    expect(countsText(counts, 'entries')).toBe('1,350 movies · 2 series');
    expect(
      buildDuration('2026-11-03T08:00:00Z', '2026-11-03T08:00:06.6Z')
    ).toBe('6.6 s');
    expect(buildDuration('2026-11-03T08:00:00Z', '2026-11-03T08:02:05Z')).toBe(
      '2 min 5 s'
    );
    expect(buildDuration(null, '2026-11-03T08:00:00Z')).toBe('');
  });

  it('resolves categories like the catalogue', () => {
    const categories = [
      {
        id: 1,
        name: 'DE | Kids',
        category_type: 'movie',
        account: 3,
        enabled: true,
      },
      {
        id: 2,
        name: 'EN | Kids',
        category_type: 'movie',
        account: 4,
        enabled: true,
      },
      {
        id: 3,
        name: 'DE | Drama',
        category_type: 'movie',
        account: 3,
        enabled: true,
      },
      {
        id: 4,
        name: 'DE | Off',
        category_type: 'movie',
        account: 3,
        enabled: false,
      },
      {
        id: 5,
        name: 'DE | Series',
        category_type: 'series',
        account: 3,
        enabled: true,
      },
    ];
    // The server evaluates the import rules; unknown categories are disabled.
    const profile = {
      category_choices: [{ relation: 3, enabled: true }],
      category_rule_states: { 1: true, 2: false, 5: true },
    };
    const rows = categoryRows(categories, profile, 'movie');
    expect(rows.map((row) => [row.id, row.enabled, row.manual])).toEqual([
      [1, true, false],
      [2, false, false],
      [3, true, true],
    ]);
    // A choice that matches the automatic result is dropped.
    expect(setCategoryChoices(profile, [rows[0]], true)).toEqual([
      { relation: 3, enabled: true },
    ]);
    expect(setCategoryChoices(profile, [rows[0], rows[1]], false)).toEqual([
      { relation: 1, enabled: false },
      { relation: 3, enabled: true },
    ]);
    // Back to what the rules decide removes the manual choice.
    expect(setCategoryChoices(profile, [rows[2]], false)).toEqual([]);
  });

  it('builds a clean payload', () => {
    const payload = profilePayload({
      name: 'Kids',
      catalog_status: 'ready',
      content_filters: {
        audio_languages: [],
        resolution_min: 0,
        anime_mode: '',
        adult_mode: 'exclude',
        missing_tmdb_mode: 'exclude',
      },
      edition_rules: [
        { title_suffix: '4K', min_resolution: 2160 },
        { title_suffix: ' ', required_audio_languages: [] },
      ],
    });
    expect(payload.catalog_status).toBeUndefined();
    expect(payload.content_filters).toEqual({
      adult_mode: 'exclude',
      missing_tmdb_mode: 'exclude',
    });
    // Blank editions are dropped.
    expect(payload.edition_rules).toEqual([
      { title_suffix: '4K', min_resolution: 2160, name: '4K' },
    ]);
  });

  it('offers resolutions as pixel heights', () => {
    expect(resolutionOptions(['2160p', '1080p', 'SD', '480p'])).toEqual([
      { value: '0', label: 'Any' },
      { value: '2160', label: '2160p' },
      { value: '1080', label: '1080p' },
      { value: '480', label: 'SD' },
    ]);
  });

  it('maps server errors to fields and tabs', () => {
    expect(
      profileErrors({
        ranking: ['Use only supported ranking criteria.'],
        content_filters: { audio_languages: ['Unknown language.'] },
      })
    ).toEqual({
      errors: {
        ranking: 'Use only supported ranking criteria.',
        content_filters: { audio_languages: 'Unknown language.' },
      },
      detail: '',
      tab: 'content',
    });
    expect(profileErrors({ detail: 'Nope' })).toEqual({
      errors: {},
      detail: 'Nope',
      tab: undefined,
    });
  });

  it('checks fields while editing and missing values on save', () => {
    const values = {
      name: '',
      name_template: '{title} {quality}',
      content_filters: {
        resolution_min: 2160,
        resolution_max: 720,
        required_features: ['hdr'],
        excluded_features: ['hdr'],
      },
      edition_rules: [
        { title_suffix: '4K', min_resolution: 2160 },
        { title_suffix: '4k', required_video_features: ['hdr'] },
        { title_suffix: '' },
        { required_video_features: ['3d'] },
        { title_suffix: 'Extended' },
      ],
    };
    const editing = profileValidation(values);
    expect(editing.name).toBeUndefined();
    expect(editing.name_template).toBe('Unsupported placeholders: {quality}');
    expect(fieldError(editing, 'content_filters', 'resolution_max')).toBe(
      'Choose a maximum at or above the minimum.'
    );
    expect(fieldError(editing, 'content_filters', 'excluded_features')).toBe(
      'A feature cannot be required and excluded.'
    );
    expect(fieldError(editing, 'edition_rules', 1, 'title_suffix')).toBe(
      'Use a unique suffix for each edition.'
    );
    // Blank editions are ignored; started ones are checked right away.
    expect(editing.edition_rules[2]).toBeUndefined();
    expect(editing.edition_rules[3]).toEqual({
      title_suffix: 'Enter an edition suffix.',
    });
    expect(editing.edition_rules[4]).toEqual({
      conditions: 'Give each edition at least one condition.',
    });
    const saving = profileValidation(values, { submitted: true });
    expect(saving.name).toBe('Enter a profile name.');
    expect(
      profileValidation({ name: 'Kids', name_template: '{year}' }).name_template
    ).toBe('Include {title} in the name format.');
  });
});
