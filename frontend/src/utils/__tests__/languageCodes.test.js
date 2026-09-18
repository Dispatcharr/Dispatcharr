import { describe, expect, it } from 'vitest';
import {
  invalidLanguageCodes,
  languageCodeError,
  normalizeLanguageCode,
  normalizeLanguageCodes,
} from '../languageCodes.js';

describe('languageCodes', () => {
  it('normalizes common names and terminology codes to ISO 639-2/B', () => {
    expect(normalizeLanguageCode('deu')).toBe('ger');
    expect(normalizeLanguageCode('Deutsch')).toBe('ger');
    expect(normalizeLanguageCode('fra')).toBe('fre');
  });

  it('normalizes, removes duplicates, and preserves preference order', () => {
    expect(normalizeLanguageCodes(['GER', 'de', 'eng', 'English'])).toEqual([
      'ger',
      'eng',
    ]);
  });

  it('rejects arbitrary free text', () => {
    expect(invalidLanguageCodes(['ger', 'not-a-language'])).toEqual([
      'not-a-language',
    ]);
    expect(languageCodeError(['ger'])).toBeNull();
    expect(languageCodeError(['not-a-language'])).toContain('not-a-language');
  });
});
