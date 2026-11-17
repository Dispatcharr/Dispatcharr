import { describe, it, expect } from 'vitest';
import {
  formatAudioStreamSelector,
  formatAudioStreamsTooltip,
  formatAudioTrackCompact,
  formatBestAudioBadge,
  getAudioTrackFields,
  groupAudioStreamsByLanguage,
} from '../audioStreamUtils';

const eng51 = {
  index: 1,
  audio_language: 'eng',
  audio_channels: '5.1',
  audio_codec: 'ac3',
  audio_bitrate: 384,
  sample_rate: 48000,
};
const engStereo = {
  index: 2,
  audio_language: 'eng',
  audio_channels: 'stereo',
  audio_codec: 'aac',
  audio_bitrate: 96,
  sample_rate: 48000,
};
const spaStereo = {
  index: 3,
  audio_language: 'spa',
  audio_channels: 'stereo',
  audio_codec: 'aac',
  audio_bitrate: 96,
  sample_rate: 48000,
};

describe('audioStreamUtils', () => {
  describe('formatAudioStreamSelector', () => {
    it('formats the FFmpeg absolute stream selector', () => {
      expect(formatAudioStreamSelector(eng51)).toBe('0:1');
    });

    it('formats a VLC TS pid as an i: selector', () => {
      expect(formatAudioStreamSelector({ pid: 257 })).toBe('i:257');
    });

    it('prefers the FFmpeg index when both index and pid exist', () => {
      expect(formatAudioStreamSelector({ index: 1, pid: 257 })).toBe('0:1');
    });

    it('returns an empty string when index is missing', () => {
      expect(formatAudioStreamSelector({ audio_codec: 'aac' })).toBe('');
      expect(formatAudioStreamSelector(null)).toBe('');
    });
  });

  describe('getAudioTrackFields', () => {
    it('lists language, channels, codec, bitrate, sample rate, then stream', () => {
      expect(getAudioTrackFields(eng51)).toEqual([
        { key: 'language', label: 'Language', value: 'ENG' },
        { key: 'channels', label: 'Channels', value: '5.1' },
        { key: 'codec', label: 'Codec', value: 'AC3' },
        { key: 'bitrate', label: 'Bitrate', value: '384 kbps' },
        { key: 'sample_rate', label: 'Sample Rate', value: '48000 Hz' },
        { key: 'stream', label: 'Stream', value: '0:1' },
      ]);
    });

    it('omits language when grouped under a language header', () => {
      const keys = getAudioTrackFields(eng51, { omitLanguage: true }).map(
        (field) => field.key
      );
      expect(keys).toEqual([
        'channels',
        'codec',
        'bitrate',
        'sample_rate',
        'stream',
      ]);
    });

    it('skips missing values but keeps a zero bitrate', () => {
      expect(
        getAudioTrackFields({ audio_codec: 'aac', audio_bitrate: 0 })
      ).toEqual([
        { key: 'codec', label: 'Codec', value: 'AAC' },
        { key: 'bitrate', label: 'Bitrate', value: '0 kbps' },
      ]);
    });

    it('returns no fields for a missing track', () => {
      expect(getAudioTrackFields(null)).toEqual([]);
      expect(getAudioTrackFields(undefined)).toEqual([]);
    });
  });

  describe('groupAudioStreamsByLanguage', () => {
    it('groups tracks while preserving first-seen language order', () => {
      expect(
        groupAudioStreamsByLanguage([eng51, engStereo, spaStereo])
      ).toEqual([
        { language: 'ENG', tracks: [eng51, engStereo] },
        { language: 'SPA', tracks: [spaStereo] },
      ]);
    });

    it('groups tracks without a language under No language', () => {
      const untagged = { audio_codec: 'aac', audio_channels: 'stereo' };
      expect(groupAudioStreamsByLanguage([untagged, eng51])).toEqual([
        { language: 'No language', tracks: [untagged] },
        { language: 'ENG', tracks: [eng51] },
      ]);
    });

    it('returns an empty list for missing or empty input', () => {
      expect(groupAudioStreamsByLanguage(undefined)).toEqual([]);
      expect(groupAudioStreamsByLanguage([])).toEqual([]);
    });
  });

  describe('formatAudioTrackCompact', () => {
    it('joins channels, codec and bitrate', () => {
      expect(formatAudioTrackCompact(eng51)).toBe('5.1 AC3 384 kbps');
    });

    it('returns an empty string for a missing track', () => {
      expect(formatAudioTrackCompact(null)).toBe('');
    });
  });

  describe('formatBestAudioBadge', () => {
    it('combines language, channels, codec and the count of other tracks', () => {
      expect(
        formatBestAudioBadge({
          audio_language: 'eng',
          audio_channels: '5.1',
          audio_codec: 'ac3',
          audio_streams: [{}, {}, {}, {}],
        })
      ).toBe('ENG 5.1 AC3 +3');
    });

    it('omits +N when only one track exists', () => {
      expect(
        formatBestAudioBadge({
          audio_language: 'eng',
          audio_channels: 'stereo',
          audio_codec: 'aac',
          audio_streams: [{}],
        })
      ).toBe('ENG stereo AAC');
    });

    it('works without a track list or language', () => {
      expect(
        formatBestAudioBadge({ audio_channels: 2, audio_codec: 'aac' })
      ).toBe('2 AAC');
    });

    it('returns an empty string for missing stats', () => {
      expect(formatBestAudioBadge(null)).toBe('');
    });
  });

  describe('formatAudioStreamsTooltip', () => {
    it('uses one compact line per language', () => {
      expect(formatAudioStreamsTooltip([eng51, engStereo, spaStereo])).toBe(
        'ENG: 5.1 AC3 384 kbps, stereo AAC 96 kbps\nSPA: stereo AAC 96 kbps'
      );
    });

    it('shows just the language when a track has no details', () => {
      expect(formatAudioStreamsTooltip([{ audio_language: 'fra' }])).toBe(
        'FRA'
      );
    });

    it('returns an empty string for missing or empty input', () => {
      expect(formatAudioStreamsTooltip(undefined)).toBe('');
      expect(formatAudioStreamsTooltip([])).toBe('');
    });
  });
});
