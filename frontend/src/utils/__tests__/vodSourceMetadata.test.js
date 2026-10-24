import { describe, expect, it } from 'vitest';
import {
  categoryMetadata,
  categoryMetadataPatch,
  metadataSummary,
  metadataFieldItems,
  metadataFieldText,
} from '../vodSourceMetadata.js';
import { formatStreamLabel } from '../components/SeriesModalUtils.js';

describe('source-owned metadata presentation', () => {
  it('exposes individual metadata tags without splitting language codes or feature labels', () => {
    const values = {
      audio_languages: ['ger', 'eng'],
      resolution: '2160p',
      video_features: ['dv', 'custom:imax'],
    };
    expect(metadataFieldItems(values, 'audio_languages')).toEqual([
      'ger',
      'eng',
    ]);
    expect(metadataFieldItems(values, 'resolution')).toEqual(['2160p']);
    expect(metadataFieldItems(values, 'video_features')).toEqual([
      'Dolby Vision',
      'imax',
    ]);
    expect(metadataFieldText(values, 'video_features')).toBe(
      'Dolby Vision, imax'
    );
    expect(metadataFieldItems({}, 'subtitle_languages')).toEqual([]);
  });
  it('keeps compact language codes and numeric resolutions with feature labels', () => {
    expect(
      metadataSummary({
        audio_languages: ['ger', 'eng'],
        subtitle_languages: ['eng'],
        resolution: '2160p',
        video_features: ['hdr', 'dv', 'custom:imax'],
      })
    ).toBe('DUB: ger, eng · SUB: eng · 2160p · HDR, Dolby Vision, imax');
  });
  it('does not resurrect reset legacy language or quality values', () => {
    const values = categoryMetadata({
      custom_properties: {
        language: 'de',
        quality: '4K',
        audio_languages: null,
        resolution: null,
      },
    });
    expect(values.audio_languages).toEqual([]);
    expect(categoryMetadataPatch(values).resolution).toBeNull();
  });
  it('retains legacy input compatibility without changing stored codes itself', () => {
    expect(
      categoryMetadata({ custom_properties: { language: 'de', quality: '4K' } })
    ).toMatchObject({ audio_languages: ['ger'], resolution: '2160p' });
  });
  it('labels each selected source separately instead of combining canonical metadata', () => {
    const source = {
      stream_id: '10',
      m3u_account: { name: 'Provider A' },
      effective_metadata: {
        values: { audio_languages: ['ger', 'eng'], resolution: '1080p' },
      },
    };
    expect(formatStreamLabel(source)).toBe(
      'Provider A - DUB: ger, eng · 1080p (Stream 10)'
    );
    expect(
      formatStreamLabel({
        ...source,
        effective_metadata: {
          values: {
            audio_languages: ['fre'],
            resolution: '2160p',
            video_features: ['hdr'],
          },
        },
      })
    ).toBe('Provider A - DUB: fre · 2160p · HDR (Stream 10)');
    expect(source.effective_metadata.values.audio_languages).toEqual([
      'ger',
      'eng',
    ]);
  });
});
