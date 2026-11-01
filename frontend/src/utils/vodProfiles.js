// Shared VOD profile vocabulary for the Profiles page and editor.
import { metadataLanguageLabel } from './vodMetadataLanguages.js';

export const NAME_PLACEHOLDERS = [
  { value: 'title', help: 'Library title' },
  { value: 'year', help: 'Release year' },
  { value: 'edition', help: 'Edition suffix, e.g. 4K' },
  { value: 'dub', help: 'Audio languages, e.g. GER/ENG' },
  { value: 'sub', help: 'Subtitle languages, e.g. ENG' },
  { value: 'resolution', help: 'Resolution, e.g. 1080p' },
  { value: 'features', help: 'Video features, e.g. HDR' },
  { value: 'format', help: 'Container, e.g. MKV' },
  { value: 'provider', help: 'M3U account name' },
];

export const OUTPUT_MODES = [
  { value: 'compact', label: 'Compact' },
  { value: 'variants', label: 'Sources' },
];

export const OUTPUT_GROUPS = [
  { value: 'provider', label: 'Provider' },
  { value: 'movie_series', label: 'Movie & Series' },
];

export const METADATA_SOURCES = [
  { value: 'provider', label: 'Provider' },
  { value: 'enriched', label: 'Enriched' },
];

export const titleSourceLabel = (value) =>
  value === 'clean'
    ? 'Clean title'
    : value && value !== 'provider'
      ? metadataLanguageLabel(value)
      : 'Provider';

export const optionLabel = (choices, value) =>
  choices.find((choice) => choice.value === value)?.label || value;

export const CATALOG_STATUS = {
  pending: { label: 'Pending', color: 'yellow' },
  building: { label: 'Preparing', color: 'blue' },
  ready: { label: 'Ready', color: 'green' },
  failed: { label: 'Failed', color: 'red' },
};

export const CONTENT_MODES = [
  { value: '', label: 'Include' },
  { value: 'exclude', label: 'Exclude' },
  { value: 'only', label: 'Only' },
];

const FEATURE_LABELS = { '3d': '3D', hdr: 'HDR', dv: 'Dolby Vision' };

export const newProfile = () => ({
  name: '',
  is_active: true,
  is_default: false,
  output_mode: 'compact',
  output_groups: 'provider',
  name_template: '{title} [{dub} · {resolution} · {features}]',
  title_source: 'provider',
  metadata_source: 'provider',
  category_choices: [],
  content_filters: {},
  excluded_titles: [],
  edition_rules: [],
  ranking: ['provider'],
  audio_language_order: [],
  subtitle_language_order: [],
  provider_order: [],
});

const EDITABLE_FIELDS = Object.keys(newProfile());

export const newEditionRule = () => ({
  title_suffix: '',
  min_resolution: 0,
  max_resolution: 0,
  required_audio_languages: [],
  required_subtitle_languages: [],
  required_video_features: [],
});

const isEmpty = (value) =>
  value === '' ||
  value === 0 ||
  value == null ||
  (Array.isArray(value) && value.length === 0);

const EDITION_CONDITIONS = [
  'min_resolution',
  'max_resolution',
  'required_audio_languages',
  'required_subtitle_languages',
  'required_video_features',
];

// An added edition nobody filled in is not kept.
export const isBlankEdition = (rule) =>
  !rule.title_suffix?.trim() &&
  EDITION_CONDITIONS.every((field) => isEmpty(rule[field]));

export const profilePayload = (values) => {
  const payload = Object.fromEntries(
    EDITABLE_FIELDS.map((field) => [field, values[field]])
  );
  payload.content_filters = Object.fromEntries(
    Object.entries(values.content_filters || {}).filter(
      ([, value]) => !isEmpty(value)
    )
  );
  // The suffix doubles as the edition name.
  payload.edition_rules = (values.edition_rules || [])
    .filter((rule) => !isBlankEdition(rule))
    .map((rule) => ({ ...rule, name: rule.title_suffix }));
  return payload;
};

const resolutionHeight = (value) => {
  if (String(value).toLowerCase() === 'sd') return 480;
  const match = /^(\d{3,4})p$/i.exec(String(value || ''));
  return match ? Number(match[1]) : 0;
};

export const resolutionOptions = (resolutions = [], anyLabel = 'Any') => {
  // 480p and SD share a height; offer each height once.
  const heights = new Map();
  for (const value of resolutions) {
    const height = resolutionHeight(value);
    if (height && !heights.has(height)) heights.set(height, value);
  }
  return [
    { value: '0', label: anyLabel },
    ...[...heights].map(([height, label]) => ({
      value: String(height),
      label,
    })),
  ];
};

export const languageOptions = (languages = []) =>
  languages.map((language) => ({
    value: language.value,
    label: language.label,
  }));

export const featureOptions = (features = []) =>
  features.map((value) => ({ value, label: FEATURE_LABELS[value] || value }));

// Blender's open movie Sintel, so examples show a real, free title.
const SAMPLE = {
  title: 'Sintel',
  year: '2010',
  dub: 'ENG',
  sub: 'GER',
  resolution: '1080p',
  features: 'HDR',
  format: 'MKV',
  provider: 'Provider',
};

// Drop empty parts inside brackets, e.g. "[ · 1080p · ]" becomes "[1080p]".
const tidyGroup = (match, open, inner, close) => {
  let text = inner;
  for (const separator of ['·', '|']) {
    text = text
      .split(separator)
      .map((part) => part.trim())
      .filter(Boolean)
      .join(` ${separator} `);
  }
  return text ? `${open}${text}${close}` : '';
};

// Mirrors the server formatting so the example matches client output.
export const exampleName = (template, edition = '') => {
  let source = String(template || '');
  if (edition && !source.includes('{edition}')) {
    source = source.replace('{title}', '{title} {edition}');
  }
  const marker = '\u0000';
  const values = { ...SAMPLE, title: marker, edition };
  const name = source
    .replace(/\{(\w+)\}/g, (match, key) => (key in values ? values[key] : ''))
    .replace(/([[(])([^[\]()]*)([\])])/g, tidyGroup)
    .replace(/\s{2,}/g, ' ')
    .replace(/^[\s·|-]+|[\s·|-]+$/g, '');
  return name.replace(marker, SAMPLE.title) || SAMPLE.title;
};

// Mirrors the catalogue: a manual choice, else the saved import rules, which
// the server evaluates; categories without a matching rule are disabled.
export const categoryRows = (
  categories,
  profile,
  scope,
  ruleStates = profile.category_rule_states
) => {
  const choices = new Map(
    (profile.category_choices || []).map((choice) => [
      choice.relation,
      choice.enabled,
    ])
  );
  return categories
    .filter((category) => category.enabled && category.category_type === scope)
    .map((category) => {
      const automatic = ruleStates?.[category.id] === true;
      const manual = choices.has(category.id);
      return {
        ...category,
        automatic,
        manual,
        enabled: manual ? choices.get(category.id) : automatic,
      };
    });
};

// Keep only choices that differ from what the import rules decide.
export const setCategoryChoices = (profile, rows, enabled) => {
  const choices = new Map(
    (profile.category_choices || []).map((choice) => [
      choice.relation,
      choice.enabled,
    ])
  );
  for (const row of rows) {
    if (enabled === row.automatic) choices.delete(row.id);
    else choices.set(row.id, enabled);
  }
  return [...choices]
    .sort(([left], [right]) => left - right)
    .map(([relation, value]) => ({ relation, enabled: value }));
};

// Distinct titles, or the entries clients get in their lists.
export const countsText = (counts, field = 'titles') =>
  [
    ['movie', (count) => (count === 1 ? 'movie' : 'movies')],
    ['series', () => 'series'],
  ]
    .filter(([kind]) => Number.isInteger(counts?.[kind]?.[field]))
    .map(
      ([kind, noun]) =>
        `${counts[kind][field].toLocaleString()} ${noun(counts[kind][field])}`
    )
    .join(' · ');

export const buildDuration = (startedAt, completedAt) => {
  const seconds = (new Date(completedAt) - new Date(startedAt)) / 1000;
  if (!startedAt || !completedAt || !(seconds >= 0)) return '';
  return seconds < 60
    ? `${seconds.toFixed(1)} s`
    : `${Math.floor(seconds / 60)} min ${Math.round(seconds % 60)} s`;
};

const TAB_FIELDS = {
  general: [
    'name',
    'is_default',
    'title_source',
    'metadata_source',
    'output_mode',
    'output_groups',
    'name_template',
  ],
  categories: ['category_choices'],
  content: ['content_filters'],
  editions: ['edition_rules'],
  failover: [
    'ranking',
    'audio_language_order',
    'subtitle_language_order',
    'provider_order',
  ],
  preview: ['excluded_titles'],
};

const message = (value) => {
  if (Array.isArray(value)) return value.map(message).join(' ');
  if (value && typeof value === 'object')
    return Object.values(value).map(message).join(' ');
  return String(value ?? '');
};

// Filters and editions report errors per field (and per edition).
const NESTED_FIELDS = ['content_filters', 'edition_rules'];

const nested = (value) =>
  value && typeof value === 'object' && !Array.isArray(value)
    ? Object.fromEntries(
        Object.entries(value).map(([key, item]) => [key, nested(item)])
      )
    : message(value);

// Flatten DRF errors per field and name the editor tab that holds them.
export const profileErrors = (body) => {
  const errors = {};
  let detail = '';
  if (body && typeof body === 'object') {
    for (const [field, value] of Object.entries(body)) {
      if (field === 'detail' || field === 'non_field_errors')
        detail = message(value);
      else
        errors[field] = NESTED_FIELDS.includes(field)
          ? nested(value)
          : message(value);
    }
  }
  const tab = Object.keys(TAB_FIELDS).find((name) =>
    TAB_FIELDS[name].some((field) => field in errors)
  );
  return { errors, detail, tab };
};

export const tabHasError = (tab, errors) =>
  TAB_FIELDS[tab]?.some((field) => field in errors) || false;

const PLACEHOLDER_VALUES = new Set(NAME_PLACEHOLDERS.map((item) => item.value));

// The server's checks, run while editing so fields show problems right away.
// Missing values are only reported after a save attempt.
export const profileValidation = (values, { submitted = false } = {}) => {
  const errors = {};
  if (submitted && !values.name?.trim()) errors.name = 'Enter a profile name.';

  const template = values.name_template?.trim() || '';
  const fields = [...template.matchAll(/\{([^{}]*)\}/g)].map(
    (match) => match[1]
  );
  const unsupported = fields.filter((field) => !PLACEHOLDER_VALUES.has(field));
  if (!template) {
    if (submitted) errors.name_template = 'Enter a name format.';
  } else if (unsupported.length)
    errors.name_template = `Unsupported placeholders: ${unsupported
      .map((field) => `{${field}}`)
      .join(', ')}`;
  else if (!fields.includes('title'))
    errors.name_template = 'Include {title} in the name format.';

  const filters = values.content_filters || {};
  const filterErrors = {};
  if (
    filters.resolution_max &&
    (filters.resolution_min || 0) > filters.resolution_max
  )
    filterErrors.resolution_max = 'Choose a maximum at or above the minimum.';
  if (
    (filters.required_features || []).some((feature) =>
      (filters.excluded_features || []).includes(feature)
    )
  )
    filterErrors.excluded_features =
      'A feature cannot be required and excluded.';
  if (Object.keys(filterErrors).length) errors.content_filters = filterErrors;

  // A started edition is checked right away; a blank one is dropped.
  const editionErrors = {};
  const suffixes = new Set();
  (values.edition_rules || []).forEach((rule, index) => {
    if (isBlankEdition(rule)) return;
    const rowErrors = {};
    const suffix = rule.title_suffix?.trim().toLowerCase() || '';
    if (!suffix) rowErrors.title_suffix = 'Enter an edition suffix.';
    else if (suffixes.has(suffix))
      rowErrors.title_suffix = 'Use a unique suffix for each edition.';
    suffixes.add(suffix);
    if (rule.max_resolution && (rule.min_resolution || 0) > rule.max_resolution)
      rowErrors.max_resolution = 'Choose a maximum at or above the minimum.';
    if (EDITION_CONDITIONS.every((field) => isEmpty(rule[field])))
      rowErrors.conditions = 'Give each edition at least one condition.';
    if (Object.keys(rowErrors).length) editionErrors[index] = rowErrors;
  });
  if (Object.keys(editionErrors).length) errors.edition_rules = editionErrors;
  return errors;
};

// A field's own message from a flat or nested error, e.g. edition 0's suffix.
export const fieldError = (errors, field, ...path) => {
  let value = errors[field];
  for (const key of path) {
    if (!value || typeof value !== 'object') return undefined;
    value = value[key];
  }
  return typeof value === 'string' ? value : undefined;
};

// A field-level message that no single input shows, e.g. a server message.
export const generalError = (errors, field) =>
  typeof errors[field] === 'string' ? errors[field] : undefined;
