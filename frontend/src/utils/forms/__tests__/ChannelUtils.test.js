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
      requeryChannels();
      expect(API.requeryChannels).toHaveBeenCalledTimes(1);
    });

    it('returns undefined', () => {
      const result = requeryChannels();
      expect(result).toBeUndefined();
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
});
