export const MAX_METADATA_LANGUAGES = 5;

export const METADATA_LANGUAGE_OPTIONS = [
  ['de-DE', 'German'],
  ['en-US', 'English (US)'],
  ['en-GB', 'English (UK)'],
  ['es-ES', 'Spanish'],
  ['es-MX', 'Spanish (Mexico)'],
  ['fr-FR', 'French'],
  ['it-IT', 'Italian'],
  ['nl-NL', 'Dutch'],
  ['pl-PL', 'Polish'],
  ['pt-PT', 'Portuguese'],
  ['pt-BR', 'Portuguese (Brazil)'],
  ['tr-TR', 'Turkish'],
  ['ja-JP', 'Japanese'],
  ['ko-KR', 'Korean'],
  ['zh-CN', 'Chinese (Simplified)'],
  ['zh-TW', 'Chinese (Traditional)'],
  ['ar-SA', 'Arabic'],
  ['hi-IN', 'Hindi'],
  ['ru-RU', 'Russian'],
  ['uk-UA', 'Ukrainian'],
  ['sv-SE', 'Swedish'],
  ['da-DK', 'Danish'],
  ['nb-NO', 'Norwegian'],
  ['fi-FI', 'Finnish'],
].map(([value, label]) => ({ value, label: `${label} (${value})` }));

export const metadataLanguageLabel = (language) =>
  METADATA_LANGUAGE_OPTIONS.find((option) => option.value === language)
    ?.label || language;

export const metadataLanguageOrder = (item) => [
  ...new Set([
    ...(item?.metadata_languages || []),
    ...Object.keys(item?.metadata?.localized || {}).sort(),
  ]),
];

export const initialMetadataLanguage = (item) =>
  (item?.metadata_languages || []).find((language) => {
    const translation = item.metadata?.localized?.[language];
    return ['title', 'overview', 'tagline'].some(
      (field) =>
        typeof translation?.[field] === 'string' && translation[field].trim()
    );
  }) ||
  metadataLanguageOrder(item)[0] ||
  'provider';
