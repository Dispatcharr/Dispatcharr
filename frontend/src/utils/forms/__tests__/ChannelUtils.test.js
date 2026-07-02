import { describe, it, expect, vi, beforeEach } from 'vitest';
import API from '../../../api.js';
import {
  matchChannelEpg,
  createLogo,
  addChannel,
  requeryChannels,
  getChannelFormDefaultValues,
  getFormattedValues,
  handleEpgUpdate,
  getProviderHint,
  getFkProviderHint,
  normalizeFieldValue,
  buildOverridePayload,
  listOverriddenFields,
  clearChannelOverrides,
  isFormFieldOverridden,
} from '../ChannelUtils.js';

// ── API mock ───────────────────────────────────────────────────────────────────
vi.mock('../../../api.js', () => ({
  default: {
    matchChannelEpg: vi.fn(),
    createLogo: vi.fn(),
    setChannelEPG: vi.fn(),
    updateChannel: vi.fn(),
    addChannel: vi.fn(),
    requeryChannels: vi.fn(),
  },
}));

// ── Fixtures ───────────────────────────────────────────────────────────────────
const makeChannel = (overrides = {}) => ({
  id: 'ch-1',
  name: 'HBO',
  channel_number: 501,
  channel_group_id: 2,
  stream_profile_id: 3,
  tvg_id: 'hbo.us',
  tvc_guide_stationid: 'hbo-station',
  epg_data_id: 'epg-1',
  logo_id: 10,
  user_level: 1,
  is_adult: false,
  ...overrides,
});

const makeChannelGroups = () => ({
  1: { id: 1, name: 'Group A' },
  2: { id: 2, name: 'Group B' },
});

const makeChannelStreams = () => [{ id: 's1' }, { id: 's2' }];

// ──────────────────────────────────────────────────────────────────────────────

describe('ChannelUtils', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // ── matchChannelEpg ──────────────────────────────────────────────────────────

  describe('matchChannelEpg', () => {
    it('calls API.matchChannelEpg with the channel id', () => {
      const channel = makeChannel();
      API.matchChannelEpg.mockResolvedValue({ matched: true });
      matchChannelEpg(channel);
      expect(API.matchChannelEpg).toHaveBeenCalledWith('ch-1');
    });

    it('returns the API response', async () => {
      API.matchChannelEpg.mockResolvedValue({ matched: true });
      const result = await matchChannelEpg(makeChannel());
      expect(result).toEqual({ matched: true });
    });
  });

  // ── createLogo ───────────────────────────────────────────────────────────────

  describe('createLogo', () => {
    it('calls API.createLogo with the provided logo data', () => {
      const logoData = { name: 'My Logo', url: '/logo.png' };
      API.createLogo.mockResolvedValue({ id: 99 });
      createLogo(logoData);
      expect(API.createLogo).toHaveBeenCalledWith(logoData);
    });

    it('returns the API response', async () => {
      API.createLogo.mockResolvedValue({ id: 99 });
      const result = await createLogo({ name: 'Logo' });
      expect(result).toEqual({ id: 99 });
    });
  });

  // ── addChannel ───────────────────────────────────────────────────────────────

  describe('addChannel', () => {
    it('calls API.addChannel with the channel object', () => {
      const channel = makeChannel();
      API.addChannel.mockResolvedValue({ id: 'ch-new' });
      addChannel(channel);
      expect(API.addChannel).toHaveBeenCalledWith(channel);
    });

    it('returns the API response', async () => {
      API.addChannel.mockResolvedValue({ id: 'ch-new' });
      const result = await addChannel(makeChannel());
      expect(result).toEqual({ id: 'ch-new' });
    });
  });

  // ── requeryChannels ──────────────────────────────────────────────────────────

  describe('requeryChannels', () => {
    it('calls API.requeryChannels', () => {
      vi.mocked(API.requeryChannels).mockResolvedValue(undefined);
      requeryChannels();
      expect(API.requeryChannels).toHaveBeenCalledTimes(1);
    });

    it('returns the promise from API.requeryChannels', async () => {
      const response = { results: [{ id: 1 }] };
      vi.mocked(API.requeryChannels).mockResolvedValue(response);
      await expect(requeryChannels()).resolves.toBe(response);
    });

    it('propagates rejection from API.requeryChannels', async () => {
      vi.mocked(API.requeryChannels).mockRejectedValue(new Error('network'));
      await expect(requeryChannels()).rejects.toThrow('network');
    });
  });

  // ── getChannelFormDefaultValues ──────────────────────────────────────────────

  describe('getChannelFormDefaultValues', () => {
    it('returns all channel field values as strings where required', () => {
      const channel = makeChannel();
      const result = getChannelFormDefaultValues(channel, makeChannelGroups());
      expect(result).toEqual({
        name: 'HBO',
        channel_number: 501,
        channel_group_id: '2',
        stream_profile_id: '3',
        tvg_id: 'hbo.us',
        tvc_guide_stationid: 'hbo-station',
        epg_data_id: 'epg-1',
        logo_id: '10',
        user_level: '1',
        is_adult: false,
        hidden_from_output: false,
      });
    });

    it('falls back to first channelGroup key when channel has no channel_group_id', () => {
      const channel = makeChannel({ channel_group_id: null });
      const result = getChannelFormDefaultValues(channel, makeChannelGroups());
      expect(result.channel_group_id).toBe('1');
    });

    it('returns empty string for channel_group_id when channelGroups is empty and channel has no group', () => {
      const channel = makeChannel({ channel_group_id: null });
      const result = getChannelFormDefaultValues(channel, {});
      expect(result.channel_group_id).toBe('');
    });

    it('defaults stream_profile_id to "0" when not set on channel', () => {
      const channel = makeChannel({ stream_profile_id: null });
      const result = getChannelFormDefaultValues(channel, makeChannelGroups());
      expect(result.stream_profile_id).toBe('0');
    });

    it('defaults name to empty string when channel is null', () => {
      const result = getChannelFormDefaultValues(null, makeChannelGroups());
      expect(result.name).toBe('');
    });

    it('defaults channel_number to empty string when channel is null', () => {
      const result = getChannelFormDefaultValues(null, makeChannelGroups());
      expect(result.channel_number).toBe('');
    });

    it('defaults channel_number to empty string when channel_number is null', () => {
      const channel = makeChannel({ channel_number: null });
      const result = getChannelFormDefaultValues(channel, makeChannelGroups());
      expect(result.channel_number).toBe('');
    });

    it('defaults channel_number to empty string when channel_number is undefined', () => {
      const channel = makeChannel({ channel_number: undefined });
      const result = getChannelFormDefaultValues(channel, makeChannelGroups());
      expect(result.channel_number).toBe('');
    });

    it('preserves channel_number of 0 as 0', () => {
      const channel = makeChannel({ channel_number: 0 });
      const result = getChannelFormDefaultValues(channel, makeChannelGroups());
      expect(result.channel_number).toBe(0);
    });

    it('defaults tvg_id to empty string when not set', () => {
      const channel = makeChannel({ tvg_id: null });
      const result = getChannelFormDefaultValues(channel, makeChannelGroups());
      expect(result.tvg_id).toBe('');
    });

    it('defaults tvc_guide_stationid to empty string when not set', () => {
      const channel = makeChannel({ tvc_guide_stationid: null });
      const result = getChannelFormDefaultValues(channel, makeChannelGroups());
      expect(result.tvc_guide_stationid).toBe('');
    });

    it('defaults epg_data_id to empty string when channel is null', () => {
      const result = getChannelFormDefaultValues(null, makeChannelGroups());
      expect(result.epg_data_id).toBe('');
    });

    it('defaults logo_id to empty string when not set', () => {
      const channel = makeChannel({ logo_id: null });
      const result = getChannelFormDefaultValues(channel, makeChannelGroups());
      expect(result.logo_id).toBe('');
    });

    it('defaults user_level to "0" when channel is null', () => {
      const result = getChannelFormDefaultValues(null, makeChannelGroups());
      expect(result.user_level).toBe('0');
    });

    it('defaults is_adult to false when channel is null', () => {
      const result = getChannelFormDefaultValues(null, makeChannelGroups());
      expect(result.is_adult).toBe(false);
    });

    it('returns all defaults when channel is null', () => {
      const groups = makeChannelGroups();
      const result = getChannelFormDefaultValues(null, groups);
      expect(result).toEqual({
        name: '',
        channel_number: '',
        channel_group_id: '1',
        stream_profile_id: '0',
        tvg_id: '',
        tvc_guide_stationid: '',
        epg_data_id: '',
        logo_id: '',
        user_level: '0',
        is_adult: false,
        hidden_from_output: false,
      });
    });
  });

  // ── getFormattedValues ───────────────────────────────────────────────────────

  describe('getFormattedValues', () => {
    it('converts "0" stream_profile_id to null', () => {
      const result = getFormattedValues({
        stream_profile_id: '0',
        tvg_id: 'x',
        tvc_guide_stationid: 'y',
      });
      expect(result.stream_profile_id).toBeNull();
    });

    it('converts empty string stream_profile_id to null', () => {
      const result = getFormattedValues({
        stream_profile_id: '',
        tvg_id: 'x',
        tvc_guide_stationid: 'y',
      });
      expect(result.stream_profile_id).toBeNull();
    });

    it('preserves non-zero stream_profile_id', () => {
      const result = getFormattedValues({
        stream_profile_id: '5',
        tvg_id: 'x',
        tvc_guide_stationid: 'y',
      });
      expect(result.stream_profile_id).toBe('5');
    });

    it('converts empty tvg_id to null', () => {
      const result = getFormattedValues({
        stream_profile_id: '1',
        tvg_id: '',
        tvc_guide_stationid: 'y',
      });
      expect(result.tvg_id).toBeNull();
    });

    it('preserves non-empty tvg_id', () => {
      const result = getFormattedValues({
        stream_profile_id: '1',
        tvg_id: 'hbo.us',
        tvc_guide_stationid: 'y',
      });
      expect(result.tvg_id).toBe('hbo.us');
    });

    it('converts empty tvc_guide_stationid to null', () => {
      const result = getFormattedValues({
        stream_profile_id: '1',
        tvg_id: 'x',
        tvc_guide_stationid: '',
      });
      expect(result.tvc_guide_stationid).toBeNull();
    });

    it('preserves non-empty tvc_guide_stationid', () => {
      const result = getFormattedValues({
        stream_profile_id: '1',
        tvg_id: 'x',
        tvc_guide_stationid: 'hbo-station',
      });
      expect(result.tvc_guide_stationid).toBe('hbo-station');
    });

    it('does not mutate the original values object', () => {
      const values = {
        stream_profile_id: '0',
        tvg_id: '',
        tvc_guide_stationid: '',
      };
      getFormattedValues(values);
      expect(values.stream_profile_id).toBe('0');
    });

    it('passes through unrelated fields unchanged', () => {
      const result = getFormattedValues({
        stream_profile_id: '1',
        tvg_id: 'x',
        tvc_guide_stationid: 'y',
        name: 'HBO',
      });
      expect(result.name).toBe('HBO');
    });
  });

  // ── handleEpgUpdate ──────────────────────────────────────────────────────────

  describe('handleEpgUpdate', () => {
    const makeValues = (overrides = {}) => ({
      name: 'HBO',
      stream_profile_id: '3',
      tvg_id: 'hbo.us',
      tvc_guide_stationid: 'hbo-station',
      epg_data_id: 'epg-new',
      ...overrides,
    });

    const makeFormattedValues = (overrides = {}) => ({
      name: 'HBO',
      stream_profile_id: '3',
      tvg_id: 'hbo.us',
      tvc_guide_stationid: 'hbo-station',
      epg_data_id: 'epg-new',
      ...overrides,
    });

    beforeEach(() => {
      API.setChannelEPG.mockResolvedValue(undefined);
      API.updateChannel.mockResolvedValue(undefined);
    });

    describe('when epg_data_id has changed', () => {
      it('calls API.setChannelEPG with channel id and new epg_data_id', async () => {
        const channel = makeChannel({ epg_data_id: 'epg-old' });
        const values = makeValues({ epg_data_id: 'epg-new' });
        await handleEpgUpdate(
          channel,
          values,
          makeFormattedValues({ epg_data_id: 'epg-new' }),
          makeChannelStreams()
        );
        expect(API.setChannelEPG).toHaveBeenCalledWith('ch-1', 'epg-new');
      });

      it('calls API.updateChannel with remaining fields and stream ids', async () => {
        const channel = makeChannel({ epg_data_id: 'epg-old' });
        const values = makeValues({ epg_data_id: 'epg-new' });
        const formatted = makeFormattedValues({ epg_data_id: 'epg-new' });
        await handleEpgUpdate(channel, values, formatted, makeChannelStreams());
        expect(API.updateChannel).toHaveBeenCalledWith(
          expect.objectContaining({
            id: 'ch-1',
            streams: ['s1', 's2'],
          })
        );
        // epg_data_id must NOT be in the updateChannel call
        const callArg = API.updateChannel.mock.calls[0][0];
        expect(callArg).not.toHaveProperty('epg_data_id');
      });

      it('does not call API.updateChannel when formattedValues only contains epg_data_id', async () => {
        const channel = makeChannel({ epg_data_id: 'epg-old' });
        const values = makeValues({ epg_data_id: 'epg-new' });
        // Only epg_data_id in formatted — after stripping it, nothing remains
        await handleEpgUpdate(
          channel,
          values,
          { epg_data_id: 'epg-new' },
          makeChannelStreams()
        );
        expect(API.updateChannel).not.toHaveBeenCalled();
      });
    });

    describe('when epg_data_id has not changed', () => {
      it('does not call API.setChannelEPG', async () => {
        const channel = makeChannel({ epg_data_id: 'epg-1' });
        const values = makeValues({ epg_data_id: 'epg-1' });
        await handleEpgUpdate(
          channel,
          values,
          makeFormattedValues({ epg_data_id: 'epg-1' }),
          makeChannelStreams()
        );
        expect(API.setChannelEPG).not.toHaveBeenCalled();
      });

      it('calls API.updateChannel with all formatted values and stream ids', async () => {
        const channel = makeChannel({ epg_data_id: 'epg-1' });
        const values = makeValues({ epg_data_id: 'epg-1' });
        const formatted = makeFormattedValues({ epg_data_id: 'epg-1' });
        await handleEpgUpdate(channel, values, formatted, makeChannelStreams());
        expect(API.updateChannel).toHaveBeenCalledWith({
          id: 'ch-1',
          ...formatted,
          streams: ['s1', 's2'],
        });
      });

      it('handles empty channel streams array', async () => {
        const channel = makeChannel({ epg_data_id: 'epg-1' });
        const values = makeValues({ epg_data_id: 'epg-1' });
        await handleEpgUpdate(
          channel,
          values,
          makeFormattedValues({ epg_data_id: 'epg-1' }),
          []
        );
        expect(API.updateChannel).toHaveBeenCalledWith(
          expect.objectContaining({ streams: [] })
        );
      });
    });

    it('propagates API.setChannelEPG rejection', async () => {
      API.setChannelEPG.mockRejectedValue(new Error('EPG error'));
      const channel = makeChannel({ epg_data_id: 'epg-old' });
      const values = makeValues({ epg_data_id: 'epg-new' });
      await expect(
        handleEpgUpdate(
          channel,
          values,
          makeFormattedValues({ epg_data_id: 'epg-new' }),
          makeChannelStreams()
        )
      ).rejects.toThrow('EPG error');
    });

    it('propagates API.updateChannel rejection', async () => {
      API.updateChannel.mockRejectedValue(new Error('Update error'));
      const channel = makeChannel({ epg_data_id: 'epg-1' });
      const values = makeValues({ epg_data_id: 'epg-1' });
      await expect(
        handleEpgUpdate(
          channel,
          values,
          makeFormattedValues({ epg_data_id: 'epg-1' }),
          makeChannelStreams()
        )
      ).rejects.toThrow('Update error');
    });
  });

  // ── normalizeFieldValue ──────────────────────────────────────────────────────

  describe('normalizeFieldValue', () => {
    it('returns null for empty string', () => {
      expect(normalizeFieldValue('name', '')).toBeNull();
    });

    it('returns null for null', () => {
      expect(normalizeFieldValue('name', null)).toBeNull();
    });

    it('returns null for undefined', () => {
      expect(normalizeFieldValue('name', undefined)).toBeNull();
    });

    it('returns null for the "-1" sentinel', () => {
      expect(normalizeFieldValue('name', '-1')).toBeNull();
    });

    it('coerces channel_number string "10" to numeric 10', () => {
      expect(normalizeFieldValue('channel_number', '10')).toBe(10);
    });

    it('coerces channel_number "5.5" to 5.5 (preserves decimal)', () => {
      expect(normalizeFieldValue('channel_number', '5.5')).toBe(5.5);
    });

    it('coerces logo_id string "10" to integer 10', () => {
      expect(normalizeFieldValue('logo_id', '10')).toBe(10);
    });

    it('coerces channel_group_id string "3" to integer 3', () => {
      expect(normalizeFieldValue('channel_group_id', '3')).toBe(3);
    });

    it('coerces epg_data_id string "7" to integer 7', () => {
      expect(normalizeFieldValue('epg_data_id', '7')).toBe(7);
    });

    it('coerces stream_profile_id string "2" to integer 2', () => {
      expect(normalizeFieldValue('stream_profile_id', '2')).toBe(2);
    });

    it('treats stream_profile_id "0" as null (the "use default" sentinel)', () => {
      expect(normalizeFieldValue('stream_profile_id', '0')).toBeNull();
    });

    it('treats logo_id "0" as null (the "Default" picker option)', () => {
      expect(normalizeFieldValue('logo_id', '0')).toBeNull();
    });

    it('returns string field unchanged', () => {
      expect(normalizeFieldValue('name', 'ESPN HD')).toBe('ESPN HD');
    });

    it('returns null for non-numeric channel_number', () => {
      expect(normalizeFieldValue('channel_number', 'abc')).toBeNull();
    });

    it('returns null for non-integer FK id input', () => {
      // parseInt('abc') is NaN, which is_not_finite, returns null.
      expect(normalizeFieldValue('logo_id', 'abc')).toBeNull();
    });
  });

  // ── normalizeFieldValue: sentinel battery ────────────────────────────────────
  // Every overridable form field gets walked through the sentinel matrix so
  // future field additions inherit coverage automatically. Add the field to
  // OVERRIDABLE_FIELDS in ChannelUtils.js, then add its row to the matrix
  // below.

  describe('normalizeFieldValue: sentinel battery', () => {
    // Sentinels common to all fields that must always normalize to null.
    const universalNullSentinels = ['', null, undefined, '-1'];

    // (field, expectations) pairs for every overridable form field.
    // Each row documents what the field accepts as input and what
    // normalizeFieldValue must return for the canonical inputs.
    const matrix = [
      {
        field: 'name',
        kind: 'string',
        passthrough: [['ESPN HD', 'ESPN HD']],
        zeroSentinelIsNull: false,
      },
      {
        field: 'tvg_id',
        kind: 'string',
        passthrough: [['hbo.us', 'hbo.us']],
        zeroSentinelIsNull: false,
      },
      {
        field: 'tvc_guide_stationid',
        kind: 'string',
        passthrough: [['hbo-station', 'hbo-station']],
        zeroSentinelIsNull: false,
      },
      {
        field: 'channel_number',
        kind: 'numeric',
        passthrough: [
          ['10', 10],
          ['5.5', 5.5],
          ['0', 0],
        ],
        zeroSentinelIsNull: false,
      },
      {
        field: 'channel_group_id',
        kind: 'fk-int',
        passthrough: [
          ['3', 3],
          ['0', 0],
        ],
        zeroSentinelIsNull: false,
      },
      {
        field: 'epg_data_id',
        kind: 'fk-int',
        passthrough: [
          ['7', 7],
          ['0', 0],
        ],
        zeroSentinelIsNull: false,
      },
      {
        field: 'logo_id',
        kind: 'fk-int',
        passthrough: [['10', 10]],
        // '0' is a domain sentinel: the picker's "Default" option.
        zeroSentinelIsNull: true,
      },
      {
        field: 'stream_profile_id',
        kind: 'fk-int',
        passthrough: [['2', 2]],
        // '0' is a domain sentinel: "(use default)" in the form.
        zeroSentinelIsNull: true,
      },
    ];

    matrix.forEach(({ field, passthrough, zeroSentinelIsNull }) => {
      describe(`field: ${field}`, () => {
        universalNullSentinels.forEach((sentinel) => {
          it(`normalizes ${JSON.stringify(sentinel)} to null`, () => {
            expect(normalizeFieldValue(field, sentinel)).toBeNull();
          });
        });

        if (zeroSentinelIsNull) {
          it(`treats "0" as the domain sentinel and returns null`, () => {
            expect(normalizeFieldValue(field, '0')).toBeNull();
          });
        }

        passthrough.forEach(([input, expected]) => {
          it(`coerces ${JSON.stringify(input)} to ${JSON.stringify(expected)}`, () => {
            expect(normalizeFieldValue(field, input)).toBe(expected);
          });
        });
      });
    });
  });

  // ── getProviderHint / getFkProviderHint ──────────────────────────────────────

  describe('getProviderHint', () => {
    it('returns null for null channel', () => {
      expect(getProviderHint(null, 'name')).toBeNull();
    });

    it('returns null for manual (non-auto) channel', () => {
      const ch = makeChannel({ auto_created: false });
      expect(getProviderHint(ch, 'name')).toBeNull();
    });

    it('returns "Provider: <value>" for auto-created channel with value', () => {
      const ch = makeChannel({ auto_created: true, name: 'ESPN' });
      expect(getProviderHint(ch, 'name')).toBe('Provider: ESPN');
    });

    it('renders "(empty)" placeholder for null/empty provider value', () => {
      const ch = makeChannel({ auto_created: true, tvg_id: null });
      expect(getProviderHint(ch, 'tvg_id')).toBe('Provider: (empty)');
    });

    it('renders "(empty)" for empty string provider value', () => {
      const ch = makeChannel({ auto_created: true, tvg_id: '' });
      expect(getProviderHint(ch, 'tvg_id')).toBe('Provider: (empty)');
    });
  });

  describe('getFkProviderHint', () => {
    it('returns null for null channel', () => {
      expect(getFkProviderHint(null, 'channel_group_id', {})).toBeNull();
    });

    it('returns null for manual channel', () => {
      const ch = makeChannel({ auto_created: false });
      expect(getFkProviderHint(ch, 'channel_group_id', {})).toBeNull();
    });

    it('returns "(none)" when provider FK id is null', () => {
      const ch = makeChannel({ auto_created: true, channel_group_id: null });
      expect(getFkProviderHint(ch, 'channel_group_id', {})).toBe(
        'Provider: (none)'
      );
    });

    it('returns the lookup name when FK id resolves', () => {
      const ch = makeChannel({ auto_created: true, channel_group_id: 5 });
      const lookup = { 5: { name: 'Sports' } };
      expect(getFkProviderHint(ch, 'channel_group_id', lookup)).toBe(
        'Provider: Sports'
      );
    });

    it('falls back to tvg_id when name is missing', () => {
      const ch = makeChannel({ auto_created: true, epg_data_id: 9 });
      const lookup = { 9: { tvg_id: 'espn.us' } };
      expect(getFkProviderHint(ch, 'epg_data_id', lookup)).toBe(
        'Provider: espn.us'
      );
    });

    it('falls back to stringified id when lookup misses', () => {
      const ch = makeChannel({ auto_created: true, logo_id: 99 });
      expect(getFkProviderHint(ch, 'logo_id', {})).toBe('Provider: 99');
    });
  });

  // ── listOverriddenFields ─────────────────────────────────────────────────────

  describe('listOverriddenFields', () => {
    it('returns [] for channel without override', () => {
      const ch = makeChannel({ override: null });
      expect(listOverriddenFields(ch)).toEqual([]);
    });

    it('returns [] for null channel', () => {
      expect(listOverriddenFields(null)).toEqual([]);
    });

    it('returns labels for all fields where override has a value', () => {
      const ch = makeChannel({
        override: { name: 'ESPN HD', channel_number: 100, logo_id: null },
      });
      const labels = listOverriddenFields(ch);
      expect(labels).toContain('Name');
      expect(labels).toContain('Channel Number');
      expect(labels).not.toContain('Logo');
    });
  });

  // ── isFormFieldOverridden ────────────────────────────────────────────────────

  describe('isFormFieldOverridden', () => {
    it('returns false for manual channels', () => {
      const ch = makeChannel({ auto_created: false });
      expect(isFormFieldOverridden(ch, 'name', 'Anything')).toBe(false);
    });

    it('returns true when the form value differs from the provider value', () => {
      const ch = makeChannel({ auto_created: true, name: 'Provider Name' });
      expect(isFormFieldOverridden(ch, 'name', 'Custom Name')).toBe(true);
    });

    it('returns false when no override exists and form matches provider', () => {
      const ch = makeChannel({ auto_created: true, name: 'Provider Name' });
      expect(isFormFieldOverridden(ch, 'name', 'Provider Name')).toBe(false);
    });

    // A persisted override whose value coincides with the provider value
    // must still count as overridden, so the reset affordance stays
    // available to clear it. Value-only detection wrongly returned false
    // here (pencil showed, reset button vanished).
    it('returns true when a persisted override exists even if its value equals the provider value', () => {
      const ch = makeChannel({
        auto_created: true,
        channel_group_id: 5,
        override: { channel_group_id: 5 },
      });
      expect(isFormFieldOverridden(ch, 'channel_group_id', '5')).toBe(true);
    });

    it('returns false when the override field is explicitly null (cleared)', () => {
      const ch = makeChannel({
        auto_created: true,
        channel_group_id: 5,
        override: { channel_group_id: null },
      });
      expect(isFormFieldOverridden(ch, 'channel_group_id', '5')).toBe(false);
    });
  });

  // ── buildOverridePayload ─────────────────────────────────────────────────────

  describe('buildOverridePayload', () => {
    it('returns undefined for null channel', () => {
      expect(buildOverridePayload(null, {})).toBeUndefined();
    });

    it('returns null when every form value matches provider', () => {
      // No override needed => signal "delete the override row" via null.
      const ch = makeChannel();
      const formattedValues = {
        name: ch.name,
        channel_number: ch.channel_number,
        channel_group_id: ch.channel_group_id,
        logo_id: ch.logo_id,
        tvg_id: ch.tvg_id,
        tvc_guide_stationid: ch.tvc_guide_stationid,
        epg_data_id: ch.epg_data_id,
        stream_profile_id: ch.stream_profile_id,
      };
      expect(buildOverridePayload(ch, formattedValues)).toBeNull();
    });

    it('emits the diverging field with form value, others as null (clear)', () => {
      const ch = makeChannel();
      const formattedValues = {
        name: 'ESPN-NEW',
        channel_number: ch.channel_number,
        channel_group_id: ch.channel_group_id,
        logo_id: ch.logo_id,
        tvg_id: ch.tvg_id,
        tvc_guide_stationid: ch.tvc_guide_stationid,
        epg_data_id: ch.epg_data_id,
        stream_profile_id: ch.stream_profile_id,
      };
      const payload = buildOverridePayload(ch, formattedValues);
      expect(payload).not.toBeNull();
      expect(payload.name).toBe('ESPN-NEW');
      // Fields that match provider are emitted as null (clear that
      // override field; ensures returning to provider value is cleanly
      // expressed through one PATCH).
      expect(payload.channel_number).toBeNull();
      expect(payload.tvg_id).toBeNull();
    });

    it('coerces FK id "10" string to int 10 before comparing against provider 10', () => {
      // Without normalization, "10" !== 10 would falsely emit logo_id as
      // a divergence; the test pins normalizeFieldValue's role in the
      // diff path.
      const ch = makeChannel({ logo_id: 10 });
      const formattedValues = {
        name: ch.name,
        channel_number: ch.channel_number,
        channel_group_id: ch.channel_group_id,
        logo_id: '10',
        tvg_id: ch.tvg_id,
        tvc_guide_stationid: ch.tvc_guide_stationid,
        epg_data_id: ch.epg_data_id,
        stream_profile_id: ch.stream_profile_id,
      };
      // No actual divergence; helper should return null.
      expect(buildOverridePayload(ch, formattedValues)).toBeNull();
    });
  });

  // ── clearChannelOverrides ────────────────────────────────────────────────────

  describe('clearChannelOverrides', () => {
    it('PATCHes the channel with override:null', () => {
      API.updateChannel.mockResolvedValue({ id: 1, override: null });
      clearChannelOverrides(7);
      expect(API.updateChannel).toHaveBeenCalledWith({
        id: 7,
        override: null,
      });
    });
  });
});
