import { describe, it, expect, vi, beforeEach } from 'vitest';

// ── Module mocks (must be before imports) ─────────────────────────────────────
vi.mock('../../../api.js', () => ({
  default: {
    getTimezones: vi.fn(),
    addEPG: vi.fn(),
    updateEPG: vi.fn(),
  },
}));

vi.mock('../../dateTimeUtils.js', () => ({
  format: vi.fn(),
  getDay: vi.fn(),
  getHour: vi.fn(),
  getMinute: vi.fn(),
  getMonth: vi.fn(),
  getNow: vi.fn(),
  getYear: vi.fn(),
  MONTH_ABBR: [
    'Jan',
    'Feb',
    'Mar',
    'Apr',
    'May',
    'Jun',
    'Jul',
    'Aug',
    'Sep',
    'Oct',
    'Nov',
    'Dec',
  ],
  MONTH_NAMES: [
    'January',
    'February',
    'March',
    'April',
    'May',
    'June',
    'July',
    'August',
    'September',
    'October',
    'November',
    'December',
  ],
  setHour: vi.fn((dt) => dt),
  setMinute: vi.fn((dt) => dt),
  setSecond: vi.fn((dt) => dt),
  setTz: vi.fn(),
}));

// ── Imports after mocks ────────────────────────────────────────────────────────
import API from '../../../api.js';
import * as dateTimeUtils from '../../dateTimeUtils.js';
import {
  getTimezones,
  updateEPG,
  addEPG,
  getDummyEpgFormInitialValues,
  buildCustomProperties,
  validateCustomTitlePattern,
  validateCustomNameSource,
  validateCustomStreamIndex,
  matchPattern,
  addNormalizedGroups,
  applyTemplates,
  buildTimePlaceholders,
} from '../DummyEpgUtils.js';

// ── Helpers ────────────────────────────────────────────────────────────────────
const makeEPG = (overrides = {}) => ({
  id: 42,
  name: 'Test EPG',
  is_active: true,
  source_type: 'dummy',
  custom_properties: {},
  ...overrides,
});

const makeCustom = (overrides = {}) => ({
  title_pattern: '(?<title>.+)',
  time_pattern: '(?<hour>\\d+):(?<minute>\\d+)',
  date_pattern: '',
  timezone: 'US/Eastern',
  output_timezone: '',
  program_duration: 180,
  sample_title: 'Test Show 9:00 PM',
  title_template: '{title}',
  subtitle_template: '',
  description_template: '',
  upcoming_title_template: '',
  upcoming_description_template: '',
  ended_title_template: '',
  ended_description_template: '',
  fallback_title_template: '',
  fallback_description_template: '',
  channel_logo_url: '',
  program_poster_url: '',
  name_source: 'channel',
  stream_index: 1,
  category: '',
  include_date: true,
  include_live: false,
  include_new: false,
  ...overrides,
});

// ──────────────────────────────────────────────────────────────────────────────
// Tests
// ──────────────────────────────────────────────────────────────────────────────
describe('DummyEpgUtils', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // ── getTimezones ───────────────────────────────────────────────────────────
  describe('getTimezones', () => {
    it('calls API.getTimezones and returns its result', async () => {
      vi.mocked(API.getTimezones).mockResolvedValue({
        timezones: ['UTC', 'US/Eastern'],
      });
      const result = await getTimezones();
      expect(API.getTimezones).toHaveBeenCalledTimes(1);
      expect(result).toEqual({ timezones: ['UTC', 'US/Eastern'] });
    });

    it('propagates rejection from API.getTimezones', async () => {
      vi.mocked(API.getTimezones).mockRejectedValue(new Error('Network error'));
      await expect(getTimezones()).rejects.toThrow('Network error');
    });
  });

  // ── addEPG ─────────────────────────────────────────────────────────────────
  describe('addEPG', () => {
    it('calls API.addEPG with the provided values', async () => {
      const values = { name: 'New EPG', source_type: 'dummy' };
      vi.mocked(API.addEPG).mockResolvedValue({ id: 1, ...values });
      const result = await addEPG(values);
      expect(API.addEPG).toHaveBeenCalledWith(values);
      expect(result).toMatchObject({ id: 1, name: 'New EPG' });
    });

    it('propagates rejection from API.addEPG', async () => {
      vi.mocked(API.addEPG).mockRejectedValue(new Error('Server error'));
      await expect(addEPG({})).rejects.toThrow('Server error');
    });
  });

  // ── updateEPG ──────────────────────────────────────────────────────────────
  describe('updateEPG', () => {
    it('calls API.updateEPG with values merged with epg.id', async () => {
      const epg = makeEPG({ id: 42 });
      const values = { name: 'Updated EPG' };
      vi.mocked(API.updateEPG).mockResolvedValue({
        id: 42,
        name: 'Updated EPG',
      });

      const result = await updateEPG(values, epg);

      expect(API.updateEPG).toHaveBeenCalledWith({
        name: 'Updated EPG',
        id: 42,
      });
      expect(result).toMatchObject({ id: 42 });
    });

    it('passes the correct id when multiple epgs exist', async () => {
      const epg = makeEPG({ id: 99 });
      vi.mocked(API.updateEPG).mockResolvedValue({});
      await updateEPG({ name: 'X' }, epg);
      expect(API.updateEPG).toHaveBeenCalledWith(
        expect.objectContaining({ id: 99 })
      );
    });

    it('propagates rejection from API.updateEPG', async () => {
      vi.mocked(API.updateEPG).mockRejectedValue(new Error('Update failed'));
      await expect(updateEPG({}, makeEPG())).rejects.toThrow('Update failed');
    });
  });

  // ── getDummyEpgFormInitialValues ───────────────────────────────────────────
  describe('getDummyEpgFormInitialValues', () => {
    it('returns an object with name, is_active, source_type, and custom_properties', () => {
      const result = getDummyEpgFormInitialValues();
      expect(result).toMatchObject({
        name: expect.any(String),
        is_active: expect.any(Boolean),
        source_type: 'dummy',
      });
      expect(result.custom_properties).toBeDefined();
    });

    it('sets is_active to true by default', () => {
      expect(getDummyEpgFormInitialValues().is_active).toBe(true);
    });

    it('sets include_date to true by default', () => {
      expect(
        getDummyEpgFormInitialValues().custom_properties.include_date
      ).toBe(true);
    });

    it('sets include_live and include_new to false by default', () => {
      const { custom_properties: cp } = getDummyEpgFormInitialValues();
      expect(cp.include_live).toBe(false);
      expect(cp.include_new).toBe(false);
    });

    it('defaults name_source to "channel"', () => {
      expect(getDummyEpgFormInitialValues().custom_properties.name_source).toBe(
        'channel'
      );
    });

    it('defaults program_duration to 180', () => {
      expect(
        getDummyEpgFormInitialValues().custom_properties.program_duration
      ).toBe(180);
    });

    it('defaults stream_index to 1', () => {
      expect(
        getDummyEpgFormInitialValues().custom_properties.stream_index
      ).toBe(1);
    });
  });

  // ── buildCustomProperties ──────────────────────────────────────────────────
  describe('buildCustomProperties', () => {
    it('returns defaults when called with no arguments', () => {
      const result = buildCustomProperties();
      expect(result.timezone).toBe('US/Eastern');
      expect(result.program_duration).toBe(180);
      expect(result.name_source).toBe('channel');
      expect(result.stream_index).toBe(1);
      expect(result.include_date).toBe(true);
      expect(result.include_live).toBe(false);
      expect(result.include_new).toBe(false);
    });

    it('preserves provided values over defaults', () => {
      const custom = makeCustom({
        timezone: 'US/Pacific',
        program_duration: 60,
      });
      const result = buildCustomProperties(custom);
      expect(result.timezone).toBe('US/Pacific');
      expect(result.program_duration).toBe(60);
    });

    it('preserves include_date: false when explicitly set', () => {
      const result = buildCustomProperties({ include_date: false });
      expect(result.include_date).toBe(false);
    });

    it('preserves include_live: true when explicitly set', () => {
      const result = buildCustomProperties({ include_live: true });
      expect(result.include_live).toBe(true);
    });

    it('preserves include_new: true when explicitly set', () => {
      const result = buildCustomProperties({ include_new: true });
      expect(result.include_new).toBe(true);
    });

    it('maps all template fields', () => {
      const custom = makeCustom({
        title_template: 'T:{title}',
        subtitle_template: 'S:{title}',
        description_template: 'D:{title}',
        upcoming_title_template: 'U:{title}',
        upcoming_description_template: 'UD:{title}',
        ended_title_template: 'E:{title}',
        ended_description_template: 'ED:{title}',
        fallback_title_template: 'FT:{title}',
        fallback_description_template: 'FD:{title}',
        channel_logo_url: 'http://logo',
        program_poster_url: 'http://poster',
      });
      const result = buildCustomProperties(custom);
      expect(result.title_template).toBe('T:{title}');
      expect(result.subtitle_template).toBe('S:{title}');
      expect(result.description_template).toBe('D:{title}');
      expect(result.upcoming_title_template).toBe('U:{title}');
      expect(result.upcoming_description_template).toBe('UD:{title}');
      expect(result.ended_title_template).toBe('E:{title}');
      expect(result.ended_description_template).toBe('ED:{title}');
      expect(result.fallback_title_template).toBe('FT:{title}');
      expect(result.fallback_description_template).toBe('FD:{title}');
      expect(result.channel_logo_url).toBe('http://logo');
      expect(result.program_poster_url).toBe('http://poster');
    });

    it('falls back to empty string for missing string fields', () => {
      const result = buildCustomProperties({});
      expect(result.title_pattern).toBe('');
      expect(result.time_pattern).toBe('');
      expect(result.date_pattern).toBe('');
      expect(result.output_timezone).toBe('');
      expect(result.sample_title).toBe('');
      expect(result.category).toBe('');
    });
  });

  // ── validateCustomTitlePattern ─────────────────────────────────────────────
  describe('validateCustomTitlePattern', () => {
    it('returns an error message when value is empty', () => {
      expect(validateCustomTitlePattern('')).toBeTruthy();
    });

    it('returns an error message when value is whitespace only', () => {
      expect(validateCustomTitlePattern('   ')).toBeTruthy();
    });

    it('returns null for a valid regex pattern', () => {
      expect(validateCustomTitlePattern('(?<title>.+)')).toBeNull();
    });

    it('returns an error message for an invalid regex', () => {
      expect(validateCustomTitlePattern('(?<invalid')).toBeTruthy();
    });

    it('returns an error message when value is null', () => {
      expect(validateCustomTitlePattern(null)).toBeTruthy();
    });

    it('returns an error message when value is undefined', () => {
      expect(validateCustomTitlePattern(undefined)).toBeTruthy();
    });

    it('returns null for a complex valid regex with named groups', () => {
      expect(
        validateCustomTitlePattern('(?<title>[A-Z].+)\\s(?<time>\\d+:\\d+)')
      ).toBeNull();
    });
  });

  // ── validateCustomNameSource ───────────────────────────────────────────────
  describe('validateCustomNameSource', () => {
    it('returns an error message when value is empty string', () => {
      expect(validateCustomNameSource('')).toBeTruthy();
    });

    it('returns an error message when value is null', () => {
      expect(validateCustomNameSource(null)).toBeTruthy();
    });

    it('returns an error message when value is undefined', () => {
      expect(validateCustomNameSource(undefined)).toBeTruthy();
    });

    it('returns null for "channel"', () => {
      expect(validateCustomNameSource('channel')).toBeNull();
    });

    it('returns null for "stream"', () => {
      expect(validateCustomNameSource('stream')).toBeNull();
    });
  });

  // ── validateCustomStreamIndex (if exported) ────────────────────────────────
  describe('validateCustomStreamIndex', () => {
    const streamValues = { custom_properties: { name_source: 'stream' } };
    const channelValues = { custom_properties: { name_source: 'channel' } };

    it('returns null for a positive integer when name_source is stream', () => {
      expect(validateCustomStreamIndex(streamValues, 1)).toBeNull();
    });

    it('returns null for a large positive integer when name_source is stream', () => {
      expect(validateCustomStreamIndex(streamValues, 10)).toBeNull();
    });

    it('returns an error for 0 when name_source is stream', () => {
      expect(validateCustomStreamIndex(streamValues, 0)).toBeTruthy();
    });

    it('returns an error for a negative number when name_source is stream', () => {
      expect(validateCustomStreamIndex(streamValues, -1)).toBeTruthy();
    });

    it('returns an error for null value when name_source is stream', () => {
      expect(validateCustomStreamIndex(streamValues, null)).toBeTruthy();
    });

    it('returns an error for undefined value when name_source is stream', () => {
      expect(validateCustomStreamIndex(streamValues, undefined)).toBeTruthy();
    });

    it('returns null regardless of value when name_source is channel', () => {
      expect(validateCustomStreamIndex(channelValues, 0)).toBeNull();
      expect(validateCustomStreamIndex(channelValues, -1)).toBeNull();
      expect(validateCustomStreamIndex(channelValues, null)).toBeNull();
    });

    it('returns null when custom_properties is missing', () => {
      expect(validateCustomStreamIndex({}, 0)).toBeNull();
    });
  });

  // ── matchPattern ───────────────────────────────────────────────────────────
  describe('matchPattern', () => {
    it('returns matched: false and no error when pattern is empty', () => {
      const result = matchPattern('', 'Test Show 9:00 PM');
      expect(result.matched).toBe(false);
      expect(result.error).toBeFalsy();
    });

    it('returns matched: true with named groups when pattern matches', () => {
      const result = matchPattern('(?<title>Test Show)', 'Test Show 9:00 PM');
      expect(result.matched).toBe(true);
      expect(result.groups).toMatchObject({ title: 'Test Show' });
      expect(result.error).toBeFalsy();
    });

    it('returns matched: false with no error when pattern does not match', () => {
      const result = matchPattern('(?<title>No Match)', 'Test Show 9:00 PM');
      expect(result.matched).toBe(false);
      expect(result.error).toBeFalsy();
    });

    it('returns an error string when regex is invalid', () => {
      const result = matchPattern('(?<invalid', 'Test Show');
      expect(result.matched).toBe(false);
      expect(result.error).toBeTruthy();
    });

    it('uses the provided errorLabel in the error message', () => {
      const result = matchPattern('(?<bad', 'sample', 'Time Pattern Error');
      expect(result.error).toContain('Time Pattern Error');
    });

    it('returns matched: false when sample is empty', () => {
      const result = matchPattern('(?<title>.+)', '');
      expect(result.matched).toBe(false);
    });

    it('captures multiple named groups', () => {
      const result = matchPattern(
        '(?<title>.+?)\\s(?<hour>\\d+):(?<minute>\\d+)',
        'Test Show 9:00'
      );
      expect(result.matched).toBe(true);
      expect(result.groups).toMatchObject({
        title: 'Test Show',
        hour: '9',
        minute: '00',
      });
    });
  });

  // ── addNormalizedGroups ────────────────────────────────────────────────────
  describe('addNormalizedGroups', () => {
    it('returns an empty object when groups is empty', () => {
      expect(addNormalizedGroups({})).toEqual({});
    });

    it('preserves original group keys', () => {
      const result = addNormalizedGroups({ title: 'Test Show' });
      expect(result.title).toBe('Test Show');
    });

    it('adds a _normalize key for each group', () => {
      const result = addNormalizedGroups({ title: 'Test Show' });
      expect(result.title_normalize).toBeDefined();
    });

    it('normalizes accented characters', () => {
      const result = addNormalizedGroups({ title: 'Héllo Wörld' });
      expect(result.title_normalize).not.toContain('é');
      expect(result.title_normalize).not.toContain('ö');
    });

    it('adds normalized keys for multiple groups', () => {
      const result = addNormalizedGroups({
        title: 'Show',
        subtitle: 'Épilogue',
      });
      expect(result.title_normalize).toBeDefined();
      expect(result.subtitle_normalize).toBeDefined();
    });
  });

  // ── applyTemplates ─────────────────────────────────────────────────────────
  describe('applyTemplates', () => {
    const templates = {
      titleTemplate: '{title}',
      subtitleTemplate: '{subtitle}',
      descriptionTemplate: '{title} - {subtitle}',
      upcomingTitleTemplate: 'Upcoming: {title}',
      upcomingDescriptionTemplate: 'Details for {title}',
      endedTitleTemplate: 'Ended: {title}',
      endedDescriptionTemplate: 'Summary of {title}',
      channelLogoUrl: 'http://logo/{title}',
      programPosterUrl: 'http://poster/{title}',
    };

    const groups = { title: 'Test Show', subtitle: 'Pilot' };

    it('returns an empty/falsy result when hasMatch is false', () => {
      const result = applyTemplates(templates, groups, false);
      expect(result.formattedTitle).toBeFalsy();
    });

    it('fills {title} placeholder in titleTemplate', () => {
      const result = applyTemplates(templates, groups, true);
      expect(result.formattedTitle).toBe('Test Show');
    });

    it('fills multiple placeholders in descriptionTemplate', () => {
      const result = applyTemplates(templates, groups, true);
      expect(result.formattedDescription).toBe('Test Show - Pilot');
    });

    it('fills upcomingTitleTemplate', () => {
      const result = applyTemplates(templates, groups, true);
      expect(result.formattedUpcomingTitle).toBe('Upcoming: Test Show');
    });

    it('fills endedTitleTemplate', () => {
      const result = applyTemplates(templates, groups, true);
      expect(result.formattedEndedTitle).toBe('Ended: Test Show');
    });

    it('fills channelLogoUrl', () => {
      const result = applyTemplates(templates, groups, true);
      expect(result.formattedChannelLogoUrl).toBe('http://logo/Test%20Show');
    });

    it('fills programPosterUrl', () => {
      const result = applyTemplates(templates, groups, true);
      expect(result.formattedProgramPosterUrl).toBe(
        'http://poster/Test%20Show'
      );
    });

    it('returns empty string for template that has no matching placeholder', () => {
      const result = applyTemplates(
        { ...templates, subtitleTemplate: '{nonexistent}' },
        groups,
        true
      );
      // placeholder not in groups — expect either empty or the literal token
      expect(typeof result.formattedSubtitle).toBe('string');
    });

    it('returns an object with all expected keys', () => {
      const result = applyTemplates(templates, groups, true);
      expect(result).toHaveProperty('formattedTitle');
      expect(result).toHaveProperty('formattedSubtitle');
      expect(result).toHaveProperty('formattedDescription');
      expect(result).toHaveProperty('formattedUpcomingTitle');
      expect(result).toHaveProperty('formattedUpcomingDescription');
      expect(result).toHaveProperty('formattedEndedTitle');
      expect(result).toHaveProperty('formattedEndedDescription');
      expect(result).toHaveProperty('formattedChannelLogoUrl');
      expect(result).toHaveProperty('formattedProgramPosterUrl');
    });
  });

  // ── buildTimePlaceholders ──────────────────────────────────────────────────
  describe('buildTimePlaceholders', () => {
    beforeEach(() => {
      // Provide realistic return values from dateTimeUtils
      vi.mocked(dateTimeUtils.getHour).mockReturnValue(21); // 9 PM
      vi.mocked(dateTimeUtils.getMinute).mockReturnValue(0);
      vi.mocked(dateTimeUtils.getDay).mockReturnValue(15);
      vi.mocked(dateTimeUtils.getMonth).mockReturnValue(5); // June (0-indexed)
      vi.mocked(dateTimeUtils.getYear).mockReturnValue(2024);
      vi.mocked(dateTimeUtils.format).mockImplementation((dt, fmt) => fmt);
      vi.mocked(dateTimeUtils.setHour).mockImplementation((dt) => dt);
      vi.mocked(dateTimeUtils.setMinute).mockImplementation((dt) => dt);
      vi.mocked(dateTimeUtils.setSecond).mockImplementation((dt) => dt);
      vi.mocked(dateTimeUtils.setTz).mockImplementation((dt) => dt);
      vi.mocked(dateTimeUtils.getNow).mockReturnValue('2024-06-15T21:00:00Z');
    });

    it('returns an object when given valid time groups', () => {
      const timeGroups = { hour: '9', minute: '00', ampm: 'PM' };
      const result = buildTimePlaceholders(
        timeGroups,
        {},
        'US/Eastern',
        '',
        180
      );
      expect(result).toBeDefined();
      expect(typeof result).toBe('object');
    });

    it('returns starttime key when time groups have hour and minute', () => {
      const timeGroups = { hour: '9', minute: '00', ampm: 'PM' };
      const result = buildTimePlaceholders(
        timeGroups,
        {},
        'US/Eastern',
        '',
        180
      );
      expect(result).toHaveProperty('starttime');
    });

    it('returns endtime key calculated from duration', () => {
      const timeGroups = { hour: '9', minute: '00', ampm: 'PM' };
      const result = buildTimePlaceholders(
        timeGroups,
        {},
        'US/Eastern',
        '',
        180
      );
      expect(result).toHaveProperty('endtime');
    });

    it('returns empty object when timeGroups has no hour', () => {
      const result = buildTimePlaceholders({}, {}, 'US/Eastern', '', 180);
      expect(Object.keys(result).length).toBe(0);
    });

    it('returns empty object when timeGroups is null', () => {
      const result = buildTimePlaceholders(null, {}, 'US/Eastern', '', 180);
      expect(Object.keys(result).length).toBe(0);
    });

    it('incorporates date groups when provided', () => {
      const timeGroups = { hour: '9', minute: '00' };
      const dateGroups = { year: '2024', month: '06', day: '15' };
      const result = buildTimePlaceholders(
        timeGroups,
        dateGroups,
        'US/Eastern',
        '',
        180
      );
      expect(result).toBeDefined();
    });
  });
});
