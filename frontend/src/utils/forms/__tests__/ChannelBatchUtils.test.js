import { describe, it, expect, vi, beforeEach } from 'vitest';
import {
  getChannelGroupChange,
  getLogoChange,
  getStreamProfileChange,
  getUserLevelChange,
  getMatureContentChange,
  getRegexNameChange,
  getEpgChange,
  updateChannels,
  bulkRegexRenameChannels,
  batchSetEPG,
  getEpgData,
  setChannelNamesFromEpg,
  setChannelLogosFromEpg,
  setChannelTvgIdsFromEpg,
  computeRegexPreview,
  buildSubmitValues,
  buildEpgAssociations,
} from '../ChannelBatchUtils.js';

// ── API mock ───────────────────────────────────────────────────────────────────
vi.mock('../../../api.js', () => ({
  default: {
    updateChannels: vi.fn(),
    bulkRegexRenameChannels: vi.fn(),
    batchSetEPG: vi.fn(),
    getEPGData: vi.fn(),
    setChannelNamesFromEpg: vi.fn(),
    setChannelLogosFromEpg: vi.fn(),
    setChannelTvgIdsFromEpg: vi.fn(),
  },
}));

import API from '../../../api.js';

describe('ChannelBatchUtils', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // ── getChannelGroupChange ──────────────────────────────────────────────────────

  describe('getChannelGroupChange', () => {
    const channelGroups = {
      1: { name: 'Sports' },
      2: { name: 'News' },
    };

    it('returns null when selectedChannelGroup is falsy', () => {
      expect(getChannelGroupChange(null, channelGroups)).toBeNull();
      expect(getChannelGroupChange(undefined, channelGroups)).toBeNull();
      expect(getChannelGroupChange('', channelGroups)).toBeNull();
    });

    it('returns null when selectedChannelGroup is "-1"', () => {
      expect(getChannelGroupChange('-1', channelGroups)).toBeNull();
    });

    it('returns the group name when a valid group is selected', () => {
      expect(getChannelGroupChange('1', channelGroups)).toBe(
        '• Channel Group: Sports'
      );
    });

    it('returns "Unknown" when group id is not found in channelGroups', () => {
      expect(getChannelGroupChange('99', channelGroups)).toBe(
        '• Channel Group: Unknown'
      );
    });
  });

  // ── getLogoChange ─────────────────────────────────────────────────────────────

  describe('getLogoChange', () => {
    const channelLogos = {
      5: { name: 'HBO Logo' },
      6: { name: 'ESPN Logo' },
    };

    it('returns null when selectedLogoId is falsy', () => {
      expect(getLogoChange(null, channelLogos)).toBeNull();
      expect(getLogoChange(undefined, channelLogos)).toBeNull();
      expect(getLogoChange('', channelLogos)).toBeNull();
    });

    it('returns null when selectedLogoId is "-1"', () => {
      expect(getLogoChange('-1', channelLogos)).toBeNull();
    });

    it('returns "Use Default" message when selectedLogoId is "0"', () => {
      expect(getLogoChange('0', channelLogos)).toBe('• Logo: Use Default');
    });

    it('returns the logo name when a valid logo is selected', () => {
      expect(getLogoChange('5', channelLogos)).toBe('• Logo: HBO Logo');
    });

    it('returns "Selected Logo" fallback when logo id is not found', () => {
      expect(getLogoChange('99', channelLogos)).toBe('• Logo: Selected Logo');
    });
  });

  // ── getStreamProfileChange ────────────────────────────────────────────────────

  describe('getStreamProfileChange', () => {
    const streamProfiles = [
      { id: 1, name: 'HD Profile' },
      { id: 2, name: 'SD Profile' },
    ];

    it('returns null when streamProfileId is falsy', () => {
      expect(getStreamProfileChange(null, streamProfiles)).toBeNull();
      expect(getStreamProfileChange(undefined, streamProfiles)).toBeNull();
      expect(getStreamProfileChange('', streamProfiles)).toBeNull();
    });

    it('returns null when streamProfileId is "-1"', () => {
      expect(getStreamProfileChange('-1', streamProfiles)).toBeNull();
    });

    it('returns "Use Default" message when streamProfileId is "0"', () => {
      expect(getStreamProfileChange('0', streamProfiles)).toBe(
        '• Stream Profile: Use Default'
      );
    });

    it('returns the profile name when a valid profile is selected', () => {
      expect(getStreamProfileChange('1', streamProfiles)).toBe(
        '• Stream Profile: HD Profile'
      );
    });

    it('matches profile id using string coercion', () => {
      expect(getStreamProfileChange(2, streamProfiles)).toBe(
        '• Stream Profile: SD Profile'
      );
    });

    it('returns "Selected Profile" fallback when profile is not found', () => {
      expect(getStreamProfileChange('99', streamProfiles)).toBe(
        '• Stream Profile: Selected Profile'
      );
    });
  });

  // ── getUserLevelChange ────────────────────────────────────────────────────────

  describe('getUserLevelChange', () => {
    const userLevelLabels = {
      1: 'Admin',
      2: 'Viewer',
    };

    it('returns null when userLevel is falsy', () => {
      expect(getUserLevelChange(null, userLevelLabels)).toBeNull();
      expect(getUserLevelChange(undefined, userLevelLabels)).toBeNull();
      expect(getUserLevelChange('', userLevelLabels)).toBeNull();
    });

    it('returns null when userLevel is "-1"', () => {
      expect(getUserLevelChange('-1', userLevelLabels)).toBeNull();
    });

    it('returns the label when a valid user level is selected', () => {
      expect(getUserLevelChange('1', userLevelLabels)).toBe(
        '• User Level: Admin'
      );
    });

    it('returns the raw userLevel value when label is not found', () => {
      expect(getUserLevelChange('99', userLevelLabels)).toBe(
        '• User Level: 99'
      );
    });
  });

  // ── getMatureContentChange ────────────────────────────────────────────────────

  describe('getMatureContentChange', () => {
    it('returns null when isAdult is falsy', () => {
      expect(getMatureContentChange(null)).toBeNull();
      expect(getMatureContentChange(undefined)).toBeNull();
      expect(getMatureContentChange('')).toBeNull();
    });

    it('returns null when isAdult is "-1"', () => {
      expect(getMatureContentChange('-1')).toBeNull();
    });

    it('returns "Yes" when isAdult is "true"', () => {
      expect(getMatureContentChange('true')).toBe('• Mature Content: Yes');
    });

    it('returns "No" when isAdult is "false"', () => {
      expect(getMatureContentChange('false')).toBe('• Mature Content: No');
    });
  });

  // ── getRegexNameChange ────────────────────────────────────────────────────────

  describe('getRegexNameChange', () => {
    it('returns null when regexFind is falsy', () => {
      expect(getRegexNameChange(null, 'replace')).toBeNull();
      expect(getRegexNameChange(undefined, 'replace')).toBeNull();
      expect(getRegexNameChange('', 'replace')).toBeNull();
    });

    it('returns null when regexFind is only whitespace', () => {
      expect(getRegexNameChange('   ', 'replace')).toBeNull();
    });

    it('returns the regex change description with find and replace', () => {
      expect(getRegexNameChange('foo', 'bar')).toBe(
        '• Name Change: Apply regex find "foo" replace with "bar"'
      );
    });

    it('uses empty string for replace when regexReplace is falsy', () => {
      expect(getRegexNameChange('foo', null)).toBe(
        '• Name Change: Apply regex find "foo" replace with ""'
      );
      expect(getRegexNameChange('foo', undefined)).toBe(
        '• Name Change: Apply regex find "foo" replace with ""'
      );
    });
  });

  // ── getEpgChange ──────────────────────────────────────────────────────────────

  describe('getEpgChange', () => {
    const epgs = {
      10: { name: 'XMLTV Source' },
      11: { name: 'Another EPG' },
    };

    it('returns null when selectedDummyEpgId is falsy', () => {
      expect(getEpgChange(null, epgs)).toBeNull();
      expect(getEpgChange(undefined, epgs)).toBeNull();
      expect(getEpgChange('', epgs)).toBeNull();
    });

    it('returns clear assignment message when selectedDummyEpgId is "clear"', () => {
      expect(getEpgChange('clear', epgs)).toBe(
        '• EPG: Clear Assignment (use default dummy)'
      );
    });

    it('returns the EPG name when a valid EPG is selected', () => {
      expect(getEpgChange('10', epgs)).toBe('• Dummy EPG: XMLTV Source');
    });

    it('returns "Selected EPG" fallback when EPG id is not found', () => {
      expect(getEpgChange('99', epgs)).toBe('• Dummy EPG: Selected EPG');
    });
  });

  // ── API wrappers ──────────────────────────────────────────────────────────────

  describe('updateChannels', () => {
    it('calls API.updateChannels with channelIds and values', () => {
      const channelIds = [1, 2, 3];
      const values = { user_level: 1 };
      updateChannels(channelIds, values);
      expect(API.updateChannels).toHaveBeenCalledWith(channelIds, values);
    });

    it('returns the API promise', () => {
      const mockPromise = Promise.resolve({ success: true });
      vi.mocked(API.updateChannels).mockReturnValue(mockPromise);
      expect(updateChannels([1], {})).toBe(mockPromise);
    });
  });

  describe('bulkRegexRenameChannels', () => {
    it('calls API.bulkRegexRenameChannels with all arguments', () => {
      bulkRegexRenameChannels([1, 2], 'find', 'replace', 'g');
      expect(API.bulkRegexRenameChannels).toHaveBeenCalledWith(
        [1, 2],
        'find',
        'replace',
        'g'
      );
    });

    it('passes empty string when regexReplace is null', () => {
      bulkRegexRenameChannels([1], 'find', null, 'g');
      expect(API.bulkRegexRenameChannels).toHaveBeenCalledWith(
        [1],
        'find',
        '',
        'g'
      );
    });

    it('passes empty string when regexReplace is undefined', () => {
      bulkRegexRenameChannels([1], 'find', undefined, 'g');
      expect(API.bulkRegexRenameChannels).toHaveBeenCalledWith(
        [1],
        'find',
        '',
        'g'
      );
    });
  });

  describe('batchSetEPG', () => {
    it('calls API.batchSetEPG with associations', () => {
      const associations = [{ channel_id: 1, epg_data_id: 5 }];
      batchSetEPG(associations);
      expect(API.batchSetEPG).toHaveBeenCalledWith(associations);
    });
  });

  describe('getEpgData', () => {
    it('calls API.getEPGData', () => {
      getEpgData();
      expect(API.getEPGData).toHaveBeenCalled();
    });
  });

  describe('setChannelNamesFromEpg', () => {
    it('calls API.setChannelNamesFromEpg with channelIds', () => {
      setChannelNamesFromEpg([1, 2]);
      expect(API.setChannelNamesFromEpg).toHaveBeenCalledWith([1, 2]);
    });
  });

  describe('setChannelLogosFromEpg', () => {
    it('calls API.setChannelLogosFromEpg with channelIds', () => {
      setChannelLogosFromEpg([1, 2]);
      expect(API.setChannelLogosFromEpg).toHaveBeenCalledWith([1, 2]);
    });
  });

  describe('setChannelTvgIdsFromEpg', () => {
    it('calls API.setChannelTvgIdsFromEpg with channelIds', () => {
      setChannelTvgIdsFromEpg([1, 2]);
      expect(API.setChannelTvgIdsFromEpg).toHaveBeenCalledWith([1, 2]);
    });
  });

  // ── computeRegexPreview ───────────────────────────────────────────────────────

  describe('computeRegexPreview', () => {
    const nameById = {
      1: 'HBO East',
      2: 'HBO West',
      3: 'ESPN HD',
      4: 'CNN',
    };

    it('returns empty array when find is falsy', () => {
      expect(computeRegexPreview([1, 2], nameById, '')).toEqual([]);
      expect(computeRegexPreview([1, 2], nameById, null)).toEqual([]);
      expect(computeRegexPreview([1, 2], nameById, undefined)).toEqual([]);
    });

    it('returns invalid regex entry for a bad pattern', () => {
      const result = computeRegexPreview([1], nameById, '[invalid');
      expect(result).toEqual([{ before: 'Invalid regex', after: '' }]);
    });

    it('returns before/after pairs for matching channels', () => {
      const result = computeRegexPreview([1, 2], nameById, 'HBO', 'Cinemax');
      expect(result).toEqual([
        { before: 'HBO East', after: 'Cinemax East' },
        { before: 'HBO West', after: 'Cinemax West' },
      ]);
    });

    it('excludes channels where name does not change', () => {
      const result = computeRegexPreview([1, 2, 4], nameById, 'HBO', 'Cinemax');
      expect(result).toHaveLength(2);
      expect(result.find((r) => r.before === 'CNN')).toBeUndefined();
    });

    it('only includes ids that exist in nameById', () => {
      const result = computeRegexPreview(
        [1, 99, 2],
        nameById,
        'HBO',
        'Cinemax'
      );
      expect(result).toHaveLength(2);
    });

    it('respects the limit parameter', () => {
      const largeNameById = Object.fromEntries(
        Array.from({ length: 30 }, (_, i) => [i + 1, `HBO ${i + 1}`])
      );
      const ids = Array.from({ length: 30 }, (_, i) => i + 1);
      const result = computeRegexPreview(
        ids,
        largeNameById,
        'HBO',
        'Cinemax',
        5
      );
      expect(result).toHaveLength(5);
    });

    it('defaults to a limit of 25', () => {
      const largeNameById = Object.fromEntries(
        Array.from({ length: 30 }, (_, i) => [i + 1, `HBO ${i + 1}`])
      );
      const ids = Array.from({ length: 30 }, (_, i) => i + 1);
      const result = computeRegexPreview(ids, largeNameById, 'HBO', 'Cinemax');
      expect(result).toHaveLength(25);
    });

    it('uses empty string for replace when replace is null', () => {
      const result = computeRegexPreview([1], nameById, 'HBO East', null);
      expect(result).toEqual([{ before: 'HBO East', after: '' }]);
    });

    it('applies regex globally across the channel name', () => {
      const names = { 1: 'aabbaa' };
      const result = computeRegexPreview([1], names, 'a', 'x');
      expect(result).toEqual([{ before: 'aabbaa', after: 'xxbbxx' }]);
    });
  });

  // ── buildSubmitValues ─────────────────────────────────────────────────────────

  describe('buildSubmitValues', () => {
    const baseFormValues = {
      stream_profile_id: '-1',
      user_level: '-1',
      is_adult: '-1',
      logo: 'some-logo.png',
      channel_group: 'some-group',
    };

    it('removes channel_group and logo keys from the result', () => {
      const result = buildSubmitValues(baseFormValues, null, null);
      expect(result).not.toHaveProperty('channel_group');
      expect(result).not.toHaveProperty('logo');
    });

    it('removes stream_profile_id when it is "-1"', () => {
      const result = buildSubmitValues(
        { ...baseFormValues, stream_profile_id: '-1' },
        null,
        null
      );
      expect(result).not.toHaveProperty('stream_profile_id');
    });

    it('removes stream_profile_id when it is falsy', () => {
      const result = buildSubmitValues(
        { ...baseFormValues, stream_profile_id: '' },
        null,
        null
      );
      expect(result).not.toHaveProperty('stream_profile_id');
    });

    it('converts stream_profile_id "0" to null (use default)', () => {
      const result = buildSubmitValues(
        { ...baseFormValues, stream_profile_id: '0' },
        null,
        null
      );
      expect(result.stream_profile_id).toBeNull();
    });

    it('preserves a valid stream_profile_id string', () => {
      const result = buildSubmitValues(
        { ...baseFormValues, stream_profile_id: '3' },
        null,
        null
      );
      expect(result.stream_profile_id).toBe('3');
    });

    it('removes user_level when it is "-1"', () => {
      const result = buildSubmitValues(
        { ...baseFormValues, user_level: '-1' },
        null,
        null
      );
      expect(result).not.toHaveProperty('user_level');
    });

    it('preserves a valid user_level', () => {
      const result = buildSubmitValues(
        { ...baseFormValues, user_level: '2' },
        null,
        null
      );
      expect(result.user_level).toBe('2');
    });

    it('removes is_adult when it is "-1"', () => {
      const result = buildSubmitValues(
        { ...baseFormValues, is_adult: '-1' },
        null,
        null
      );
      expect(result).not.toHaveProperty('is_adult');
    });

    it('converts is_adult "true" to boolean true', () => {
      const result = buildSubmitValues(
        { ...baseFormValues, is_adult: 'true' },
        null,
        null
      );
      expect(result.is_adult).toBe(true);
    });

    it('converts is_adult "false" to boolean false', () => {
      const result = buildSubmitValues(
        { ...baseFormValues, is_adult: 'false' },
        null,
        null
      );
      expect(result.is_adult).toBe(false);
    });

    it('sets channel_group_id as integer when selectedChannelGroup is valid', () => {
      const result = buildSubmitValues(baseFormValues, '5', null);
      expect(result.channel_group_id).toBe(5);
    });

    it('removes channel_group_id when selectedChannelGroup is null', () => {
      const result = buildSubmitValues(
        { ...baseFormValues, channel_group_id: 99 },
        null,
        null
      );
      expect(result).not.toHaveProperty('channel_group_id');
    });

    it('removes channel_group_id when selectedChannelGroup is "-1"', () => {
      const result = buildSubmitValues(
        { ...baseFormValues, channel_group_id: 99 },
        '-1',
        null
      );
      expect(result).not.toHaveProperty('channel_group_id');
    });

    it('sets logo_id to null when selectedLogoId is "0" (use default)', () => {
      const result = buildSubmitValues(baseFormValues, null, '0');
      expect(result.logo_id).toBeNull();
    });

    it('sets logo_id as integer when selectedLogoId is a valid id', () => {
      const result = buildSubmitValues(baseFormValues, null, '7');
      expect(result.logo_id).toBe(7);
    });

    it('does not set logo_id when selectedLogoId is null', () => {
      const result = buildSubmitValues(baseFormValues, null, null);
      expect(result).not.toHaveProperty('logo_id');
    });

    it('does not set logo_id when selectedLogoId is "-1"', () => {
      const result = buildSubmitValues(baseFormValues, null, '-1');
      expect(result).not.toHaveProperty('logo_id');
    });

    it('does not mutate the original formValues object', () => {
      const formValues = { ...baseFormValues };
      buildSubmitValues(formValues, '1', '2');
      expect(formValues).toEqual(baseFormValues);
    });
  });

  // ── buildEpgAssociations ──────────────────────────────────────────────────────

  describe('buildEpgAssociations', () => {
    const channelIds = [1, 2, 3];

    const epgs = {
      10: { name: 'XMLTV Source', epg_data_count: 5 },
      11: { name: 'Empty EPG', epg_data_count: 0 },
    };

    const tvgs = [{ id: 42, epg_source: 10 }];

    it('returns null when selectedDummyEpgId is falsy', async () => {
      await expect(
        buildEpgAssociations(null, channelIds, epgs, tvgs)
      ).resolves.toBeNull();
      await expect(
        buildEpgAssociations('', channelIds, epgs, tvgs)
      ).resolves.toBeNull();
      await expect(
        buildEpgAssociations(undefined, channelIds, epgs, tvgs)
      ).resolves.toBeNull();
    });

    it('returns clear associations when selectedDummyEpgId is "clear"', async () => {
      const result = await buildEpgAssociations(
        'clear',
        channelIds,
        epgs,
        tvgs
      );
      expect(result).toEqual([
        { channel_id: 1, epg_data_id: null },
        { channel_id: 2, epg_data_id: null },
        { channel_id: 3, epg_data_id: null },
      ]);
    });

    it('returns null when the selected EPG has no epg_data_count', async () => {
      const result = await buildEpgAssociations('11', channelIds, epgs, tvgs);
      expect(result).toBeNull();
    });

    it('returns null when the selected EPG id is not found in epgs', async () => {
      const result = await buildEpgAssociations('99', channelIds, epgs, tvgs);
      expect(result).toBeNull();
    });

    it('uses cached tvgs data when epg_source matches', async () => {
      const result = await buildEpgAssociations('10', channelIds, epgs, tvgs);
      expect(API.getEPGData).not.toHaveBeenCalled();
      expect(result).toEqual([
        { channel_id: 1, epg_data_id: 42 },
        { channel_id: 2, epg_data_id: 42 },
        { channel_id: 3, epg_data_id: 42 },
      ]);
    });

    it('calls getEpgData when tvgs does not contain a matching epg_source', async () => {
      vi.mocked(API.getEPGData).mockResolvedValue([{ id: 55, epg_source: 10 }]);
      const result = await buildEpgAssociations('10', channelIds, epgs, []);
      expect(API.getEPGData).toHaveBeenCalled();
      expect(result).toEqual([
        { channel_id: 1, epg_data_id: 55 },
        { channel_id: 2, epg_data_id: 55 },
        { channel_id: 3, epg_data_id: 55 },
      ]);
    });

    it('returns null when getEpgData result has no matching epg_source', async () => {
      vi.mocked(API.getEPGData).mockResolvedValue([
        { id: 55, epg_source: 999 },
      ]);
      const result = await buildEpgAssociations('10', channelIds, epgs, []);
      expect(result).toBeNull();
    });
  });
});
