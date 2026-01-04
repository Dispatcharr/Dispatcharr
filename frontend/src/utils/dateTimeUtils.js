import { useCallback, useEffect } from 'react';
import dayjs from 'dayjs';
import duration from 'dayjs/plugin/duration';
import relativeTime from 'dayjs/plugin/relativeTime';
import utc from 'dayjs/plugin/utc';
import timezone from 'dayjs/plugin/timezone';
import useSettingsStore from '../store/settings';
import useLocalStorage from '../hooks/useLocalStorage';

dayjs.extend(duration);
dayjs.extend(relativeTime);
dayjs.extend(utc);
dayjs.extend(timezone);

export const convertToMs = (dateTime) => dayjs(dateTime).valueOf();

export const initializeTime = (dateTime) => dayjs(dateTime);

export const startOfDay = (dateTime) => dayjs(dateTime).startOf('day');

export const isBefore = (date1, date2) => dayjs(date1).isBefore(date2);

export const isAfter = (date1, date2) => dayjs(date1).isAfter(date2);

export const isSame = (date1, date2, unit = 'day') =>
  dayjs(date1).isSame(date2, unit);

export const add = (dateTime, value, unit) => dayjs(dateTime).add(value, unit);

export const diff = (date1, date2, unit = 'millisecond') =>
  dayjs(date1).diff(date2, unit);

export const format = (dateTime, formatStr) =>
  dayjs(dateTime).format(formatStr);

export const getNow = () => dayjs();

export const getNowMs = () => Date.now();

export const roundToNearest = (dateTime, minutes) => {
  const current = initializeTime(dateTime);
  const minute = current.minute();
  const snappedMinute = Math.round(minute / minutes) * minutes;

  return snappedMinute === 60
    ? current.add(1, 'hour').minute(0)
    : current.minute(snappedMinute);
};

export const useUserTimeZone = () => {
  const settings = useSettingsStore((s) => s.settings);
  const [timeZone, setTimeZone] = useLocalStorage(
    'time-zone',
    dayjs.tz?.guess
      ? dayjs.tz.guess()
      : Intl.DateTimeFormat().resolvedOptions().timeZone
  );

  useEffect(() => {
    const tz = settings?.['system-time-zone']?.value;
    if (tz && tz !== timeZone) {
      setTimeZone(tz);
    }
  }, [settings, timeZone, setTimeZone]);

  return timeZone;
};

export const useTimeHelpers = () => {
  const timeZone = useUserTimeZone();

  const toUserTime = useCallback(
    (value) => {
      if (!value) return dayjs.invalid();
      try {
        return initializeTime(value).tz(timeZone);
      } catch (error) {
        return initializeTime(value);
      }
    },
    [timeZone]
  );

  const userNow = useCallback(() => getNow().tz(timeZone), [timeZone]);

  return { timeZone, toUserTime, userNow };
};

export const RECURRING_DAY_OPTIONS = [
  { value: 6, label: 'Sun' },
  { value: 0, label: 'Mon' },
  { value: 1, label: 'Tue' },
  { value: 2, label: 'Wed' },
  { value: 3, label: 'Thu' },
  { value: 4, label: 'Fri' },
  { value: 5, label: 'Sat' },
];

export const useDateTimeFormat = () => {
  const [timeFormatSetting] = useLocalStorage('time-format', '12h');
  const [dateFormatSetting] = useLocalStorage('date-format', 'mdy');
  // Use user preference for time format
  const timeFormat = timeFormatSetting === '12h' ? 'h:mma' : 'HH:mm';
  const dateFormat = dateFormatSetting === 'mdy' ? 'MMM D' : 'D MMM';

  return [timeFormat, dateFormat];
};

export const toTimeString = (value) => {
  if (!value) return '00:00';
  if (typeof value === 'string') {
    const parsed = dayjs(value, ['HH:mm', 'HH:mm:ss', 'h:mm A'], true);
    if (parsed.isValid()) return parsed.format('HH:mm');
    return value;
  }
  const parsed = initializeTime(value);
  return parsed.isValid() ? parsed.format('HH:mm') : '00:00';
};

export const parseDate = (value) => {
  if (!value) return null;
  const parsed = dayjs(value, ['YYYY-MM-DD', dayjs.ISO_8601], true);
  return parsed.isValid() ? parsed.toDate() : null;
};

const TIMEZONE_FALLBACKS = [
  'UTC',
  'America/New_York',
  'America/Chicago',
  'America/Denver',
  'America/Los_Angeles',
  'America/Phoenix',
  'America/Anchorage',
  'Pacific/Honolulu',
  'Europe/London',
  'Europe/Paris',
  'Europe/Berlin',
  'Europe/Madrid',
  'Europe/Warsaw',
  'Europe/Moscow',
  'Asia/Dubai',
  'Asia/Kolkata',
  'Asia/Shanghai',
  'Asia/Tokyo',
  'Asia/Seoul',
  'Australia/Sydney',
];

const getSupportedTimeZones = () => {
  try {
    if (typeof Intl.supportedValuesOf === 'function') {
      return Intl.supportedValuesOf('timeZone');
    }
  } catch (error) {
    console.warn('Unable to enumerate supported time zones:', error);
  }
  return TIMEZONE_FALLBACKS;
};

const getTimeZoneOffsetMinutes = (date, timeZone) => {
  try {
    const dtf = new Intl.DateTimeFormat('en-US', {
      timeZone,
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hourCycle: 'h23',
    });
    const parts = dtf.formatToParts(date).reduce((acc, part) => {
      if (part.type !== 'literal') acc[part.type] = part.value;
      return acc;
    }, {});
    const asUTC = Date.UTC(
      Number(parts.year),
      Number(parts.month) - 1,
      Number(parts.day),
      Number(parts.hour),
      Number(parts.minute),
      Number(parts.second)
    );
    return (asUTC - date.getTime()) / 60000;
  } catch (error) {
    console.warn(`Failed to compute offset for ${timeZone}:`, error);
    return 0;
  }
};

const formatOffset = (minutes) => {
  const rounded = Math.round(minutes);
  const sign = rounded < 0 ? '-' : '+';
  const absolute = Math.abs(rounded);
  const hours = String(Math.floor(absolute / 60)).padStart(2, '0');
  const mins = String(absolute % 60).padStart(2, '0');
  return `UTC${sign}${hours}:${mins}`;
};

export const buildTimeZoneOptions = (preferredZone) => {
  const zones = getSupportedTimeZones();
  const referenceYear = new Date().getUTCFullYear();
  const janDate = new Date(Date.UTC(referenceYear, 0, 1, 12, 0, 0));
  const julDate = new Date(Date.UTC(referenceYear, 6, 1, 12, 0, 0));

  const options = zones
    .map((zone) => {
      const janOffset = getTimeZoneOffsetMinutes(janDate, zone);
      const julOffset = getTimeZoneOffsetMinutes(julDate, zone);
      const currentOffset = getTimeZoneOffsetMinutes(new Date(), zone);
      const minOffset = Math.min(janOffset, julOffset);
      const maxOffset = Math.max(janOffset, julOffset);
      const usesDst = minOffset !== maxOffset;
      const labelParts = [`now ${formatOffset(currentOffset)}`];
      if (usesDst) {
        labelParts.push(
          `DST range ${formatOffset(minOffset)} to ${formatOffset(maxOffset)}`
        );
      }
      return {
        value: zone,
        label: `${zone} (${labelParts.join(' | ')})`,
        numericOffset: minOffset,
      };
    })
    .sort((a, b) => {
      if (a.numericOffset !== b.numericOffset) {
        return a.numericOffset - b.numericOffset;
      }
      return a.value.localeCompare(b.value);
    });
  if (
    preferredZone &&
    !options.some((option) => option.value === preferredZone)
  ) {
    const currentOffset = getTimeZoneOffsetMinutes(new Date(), preferredZone);
    options.push({
      value: preferredZone,
      label: `${preferredZone} (now ${formatOffset(currentOffset)})`,
      numericOffset: currentOffset,
    });
    options.sort((a, b) => {
      if (a.numericOffset !== b.numericOffset) {
        return a.numericOffset - b.numericOffset;
      }
      return a.value.localeCompare(b.value);
    });
  }
  return options;
};

export const getDefaultTimeZone = () => {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
  } catch (error) {
    return 'UTC';
  }
};