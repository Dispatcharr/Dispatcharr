import API from '../../api.js';
import {
  format,
  getDay,
  getHour,
  getMinute,
  getMonth,
  getNow,
  getYear,
  MONTH_ABBR,
  MONTH_NAMES,
  setHour,
  setMinute,
  setSecond,
  setTz,
} from '../dateTimeUtils.js';

export const getTimezones = () => {
  return API.getTimezones();
};
export const updateEPG = (values, epg) => {
  return API.updateEPG({ ...values, id: epg.id });
};
export const addEPG = (values) => {
  return API.addEPG(values);
};

export const getDummyEpgFormInitialValues = () => {
  return {
    name: '',
    is_active: true,
    source_type: 'dummy',
    custom_properties: buildCustomProperties({}),
  };
};

export const buildCustomProperties = (custom = {}) => ({
  title_pattern: custom.title_pattern || '',
  time_pattern: custom.time_pattern || '',
  date_pattern: custom.date_pattern || '',
  timezone:
    custom.timezone || custom.timezone_offset?.toString() || 'US/Eastern',
  output_timezone: custom.output_timezone || '',
  program_duration: custom.program_duration || 180,
  sample_title: custom.sample_title || '',
  title_template: custom.title_template || '',
  subtitle_template: custom.subtitle_template || '',
  description_template: custom.description_template || '',
  upcoming_title_template: custom.upcoming_title_template || '',
  upcoming_description_template: custom.upcoming_description_template || '',
  ended_title_template: custom.ended_title_template || '',
  ended_description_template: custom.ended_description_template || '',
  fallback_title_template: custom.fallback_title_template || '',
  fallback_description_template: custom.fallback_description_template || '',
  channel_logo_url: custom.channel_logo_url || '',
  program_poster_url: custom.program_poster_url || '',
  name_source: custom.name_source || 'channel',
  stream_index: custom.stream_index || 1,
  category: custom.category || '',
  include_date: custom.include_date ?? true,
  include_live: custom.include_live ?? false,
  include_new: custom.include_new ?? false,
});

export const validateCustomTitlePattern = (value) => {
  if (!value?.trim()) return 'Title pattern is required';
  try {
    new RegExp(value);
    return null;
  } catch (e) {
    return `Invalid regex: ${e.message}`;
  }
};

export const validateCustomNameSource = (value) => {
  if (!value) return 'Name source is required';
  return null;
};

export const validateCustomStreamIndex = (values, value) => {
  if (values.custom_properties?.name_source === 'stream') {
    if (!value || value < 1) {
      return 'Stream index must be at least 1';
    }
  }
  return null;
};

export const matchPattern = (pattern, input, errorPrefix) => {
  if (!pattern || !input) return { matched: false, groups: {}, error: null };
  try {
    const match = input.match(new RegExp(pattern));
    return match
      ? { matched: true, groups: match.groups || {}, error: null }
      : { matched: false, groups: {}, error: null };
  } catch (e) {
    return {
      matched: false,
      groups: {},
      error: `${errorPrefix}: ${e.message}`,
    };
  }
};

export const addNormalizedGroups = (groups) => {
  const result = { ...groups };
  Object.keys(groups).forEach((key) => {
    if (groups[key]) {
      result[`${key}_normalize`] = String(groups[key])
        .replace(/[^a-zA-Z0-9\s]/g, '')
        .replace(/\s+/g, '')
        .toLowerCase();
    }
  });
  return result;
};

const formatTime12 = (h, m) => {
  const period = h < 12 ? 'AM' : 'PM';
  let h12 = h % 12 || 12;
  return m > 0
    ? `${h12}:${String(m).padStart(2, '0')} ${period}`
    : `${h12} ${period}`;
};

const formatTime12Long = (h, m) => {
  const period = h < 12 ? 'AM' : 'PM';
  let h12 = h % 12 || 12;
  return `${h12}:${String(m).padStart(2, '0')} ${period}`;
};

const formatTime24 = (h, m) =>
  `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`;

export const buildTimePlaceholders = (
  timeGroups,
  dateGroups,
  sourceTimezone,
  outputTimezone,
  programDuration
) => {
  if (!timeGroups || !timeGroups.hour) return {};

  try {
    let hour24 = parseInt(timeGroups.hour);
    const minute = timeGroups.minute ? parseInt(timeGroups.minute) : 0;
    const ampm = timeGroups.ampm?.toLowerCase();

    if (ampm === 'pm' && hour24 !== 12) hour24 += 12;
    else if (ampm === 'am' && hour24 === 12) hour24 = 0;

    let baseDate = setTz(getNow(), sourceTimezone);

    if (dateGroups.month && dateGroups.day) {
      const monthValue = dateGroups.month;
      let extractedMonth;
      if (/^\d+$/.test(monthValue)) {
        extractedMonth = parseInt(monthValue);
      } else {
        const lower = monthValue.toLowerCase();
        const idx =
          MONTH_NAMES.indexOf(lower) !== -1
            ? MONTH_NAMES.indexOf(lower)
            : MONTH_ABBR.indexOf(lower);
        extractedMonth = idx !== -1 ? idx + 1 : getMonth(getNow()) + 1;
      }
      const extractedDay = parseInt(dateGroups.day);
      const extractedYear = dateGroups.year
        ? parseInt(dateGroups.year)
        : getYear(getNow());
      if (
        !isNaN(extractedMonth) &&
        !isNaN(extractedDay) &&
        !isNaN(extractedYear) &&
        extractedMonth >= 1 &&
        extractedMonth <= 12 &&
        extractedDay >= 1 &&
        extractedDay <= 31
      ) {
        baseDate = setTz(
          `${extractedYear}-${String(extractedMonth).padStart(2, '0')}-${String(extractedDay).padStart(2, '0')}`,
          sourceTimezone
        );
      }
    }

    let sourceDate = setHour(baseDate, hour24);
    sourceDate = setMinute(sourceDate, minute);
    sourceDate = setSecond(sourceDate, 0);
    const workDate =
      outputTimezone && outputTimezone !== sourceTimezone
        ? setTz(sourceDate, outputTimezone)
        : sourceDate;

    const h24 = getHour(workDate);
    const min = getMinute(workDate);

    const endTotalMin = h24 * 60 + min + (programDuration || 180);
    const endH24 = Math.floor(endTotalMin / 60) % 24;
    const endMin = endTotalMin % 60;

    return {
      starttime: formatTime12(h24, min),
      starttime_long: formatTime12Long(h24, min),
      starttime24: formatTime24(h24, min),
      endtime: formatTime12(endH24, endMin),
      endtime_long: formatTime12Long(endH24, endMin),
      endtime24: formatTime24(endH24, endMin),
      date: format(workDate, 'YYYY-MM-DD'),
      month: getMonth(workDate) + 1,
      day: getDay(workDate),
      year: getYear(workDate),
    };
  } catch (e) {
    console.error('Error building time placeholders:', e);
  }
};

const PLAIN_TEMPLATES = [
  { stateKey: 'titleTemplate', resultKey: 'formattedTitle' },
  { stateKey: 'subtitleTemplate', resultKey: 'formattedSubtitle' },
  { stateKey: 'descriptionTemplate', resultKey: 'formattedDescription' },
  { stateKey: 'upcomingTitleTemplate', resultKey: 'formattedUpcomingTitle' },
  {
    stateKey: 'upcomingDescriptionTemplate',
    resultKey: 'formattedUpcomingDescription',
  },
  { stateKey: 'endedTitleTemplate', resultKey: 'formattedEndedTitle' },
  {
    stateKey: 'endedDescriptionTemplate',
    resultKey: 'formattedEndedDescription',
  },
];

const URL_TEMPLATES = [
  { stateKey: 'channelLogoUrl', resultKey: 'formattedChannelLogoUrl' },
  { stateKey: 'programPosterUrl', resultKey: 'formattedProgramPosterUrl' },
];

export const applyTemplates = (templateValues, groups, hasMatch) => {
  const result = {};
  if (!hasMatch) return result;

  PLAIN_TEMPLATES.forEach(({ stateKey, resultKey }) => {
    if (templateValues[stateKey]) {
      result[resultKey] = templateValues[stateKey].replace(
        /\{(\w+)\}/g,
        (m, k) => groups[k] || m
      );
    }
  });

  URL_TEMPLATES.forEach(({ stateKey, resultKey }) => {
    if (templateValues[stateKey]) {
      result[resultKey] = templateValues[stateKey].replace(
        /\{(\w+)\}/g,
        (m, k) => (groups[k] ? encodeURIComponent(String(groups[k])) : m)
      );
    }
  });

  return result;
};
