import { describe, expect, it } from 'vitest';
import {
  initialMetadataLanguage,
  metadataLanguageOrder,
  MAX_METADATA_LANGUAGES,
} from '../vodMetadataLanguages.js';

describe('Library metadata language display preferences', () => {
  it('uses the configured order, not alphabetic order or the transport language', () => {
    const item = {
      metadata_languages: ['es-ES', 'de-DE', 'en-US'],
      metadata: {
        localized: {
          'en-US': { title: 'Film' },
          'es-ES': { title: 'Película' },
          'de-DE': { title: 'Film DE' },
        },
      },
    };
    expect(initialMetadataLanguage(item)).toBe('es-ES');
    expect(metadataLanguageOrder(item)).toEqual(['es-ES', 'de-DE', 'en-US']);
  });
  it('skips blank translations, then stays in canonical view with the first configured language', () => {
    const item = {
      metadata_languages: ['de-DE', 'en-US'],
      metadata: {
        localized: {
          'de-DE': { title: ' ', overview: '' },
          'en-US': { overview: 'Available description' },
        },
      },
    };
    expect(initialMetadataLanguage(item)).toBe('en-US');
    item.metadata.localized['en-US'].overview = '';
    expect(initialMetadataLanguage(item)).toBe('de-DE');
    expect(initialMetadataLanguage()).toBe('provider');
  });
  it('keeps previously stored languages selectable without making them defaults', () => {
    const item = {
      metadata_languages: ['de-DE'],
      metadata: {
        localized: { 'en-US': { title: 'Saved' }, 'ja-JP': { title: '保存' } },
      },
    };
    expect(metadataLanguageOrder(item)).toEqual(['de-DE', 'en-US', 'ja-JP']);
    expect(initialMetadataLanguage(item)).toBe('de-DE');
  });
  it('does not truncate existing languages when the new selection limit is five', () => {
    const languages = ['es-ES', 'de-DE', 'en-US', 'fr-FR', 'it-IT', 'ja-JP'];
    expect(MAX_METADATA_LANGUAGES).toBe(5);
    expect(metadataLanguageOrder({ metadata_languages: languages })).toEqual(
      languages
    );
  });
});
