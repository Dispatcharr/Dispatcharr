import API from '../../api.js';
import {
  add,
  diff,
  format,
  getNow,
  initializeTime,
  isValid,
  roundToNearest,
  setMillisecond,
  setSecond,
  toDate,
  toTimeString,
} from '../dateTimeUtils.js';
import { isNotEmpty } from '@mantine/form';

export const asDate = (value) => {
  if (!value) return null;
  if (value instanceof Date) return value;
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
};

export const toIsoIfDate = (value) => {
  const dt = asDate(value);
  return dt ? dt.toISOString() : value;
};

export const toDateString = (value) => {
  const dt = asDate(value);
  return dt ? format(dt, 'YYYY-MM-DD') : null;
};

export const createRoundedDate = (minutesAhead = 0) => {
  let rounded = roundToNearest(getNow(), 30);
  rounded = setSecond(rounded, 0);
  rounded = setMillisecond(rounded, 0);
  return toDate(minutesAhead ? add(rounded, minutesAhead, 'minute') : rounded);
};

// robust onChange for TimeInput (string or event)
export const timeChange = (setter) => (valOrEvent) => {
  if (typeof valOrEvent === 'string') setter(valOrEvent);
  else if (valOrEvent?.currentTarget) setter(valOrEvent.currentTarget.value);
};

export const getChannelsSummary = () => {
  return API.getChannelsSummary();
};
export const updateRecording = (id, data) => {
  return API.updateRecording(id, data);
};
export const createRecording = (data) => {
  return API.createRecording(data);
};
export const createRecurringRule = (data) => {
  return API.createRecurringRule(data);
};

/**
 * Sorts a channels array or object by channel_number (then name) and maps
 * each entry to a { value, label } select option.
 *
 * @param {Array|Object} channels
 * @param {(item: object) => string} [labelFn]  defaults to `name || "Channel id"`
 */
export const sortedChannelOptions = (channels, labelFn) => {
  const list = Array.isArray(channels)
    ? channels
    : Object.values(channels || {});

  const defaultLabel = (item) => item.name || `Channel ${item.id}`;

  return [...list]
    .sort((a, b) => {
      const aNum = Number(a.channel_number) || 0;
      const bNum = Number(b.channel_number) || 0;
      if (aNum !== bNum) return aNum - bNum;
      return (a.name || '').localeCompare(b.name || '');
    })
    .map((item) => ({
      value: String(item.id),
      label: (labelFn ?? defaultLabel)(item),
    }));
};

/** Label that includes the channel number prefix used in Recording/SeriesRule UIs. */
export const numberedChannelLabel = (item) =>
  item.channel_number
    ? `${item.channel_number} - ${item.name || `Channel ${item.id}`}`
    : item.name || `Channel ${item.id}`;

export const getSingleFormDefaults = (recording = null, channel = null) => {
  const defaultStart = createRoundedDate();
  const defaultEnd = createRoundedDate(60);
  return {
    channel_id: recording
      ? `${recording.channel}`
      : channel
        ? `${channel.id}`
        : '',
    start_time: recording
      ? asDate(recording.start_time) || defaultStart
      : defaultStart,
    end_time: recording ? asDate(recording.end_time) || defaultEnd : defaultEnd,
  };
};

export const getRecurringFormDefaults = (channel = null) => {
  const defaultStart = createRoundedDate();
  const defaultEnd = createRoundedDate(60);
  const defaultDate = new Date();
  return {
    channel_id: channel ? `${channel.id}` : '',
    days_of_week: [],
    start_time: format(defaultStart, 'HH:mm'),
    end_time: format(defaultEnd, 'HH:mm'),
    rule_name: channel?.name || '',
    start_date: defaultDate,
    end_date: defaultDate,
  };
};

export const buildSinglePayload = (values) => ({
  channel: values.channel_id,
  start_time: toIsoIfDate(values.start_time),
  end_time: toIsoIfDate(values.end_time),
});

export const buildRecurringPayload = (values) => ({
  channel: values.channel_id,
  days_of_week: (values.days_of_week || []).map(Number),
  start_time: toTimeString(values.start_time),
  end_time: toTimeString(values.end_time),
  start_date: toDateString(values.start_date),
  end_date: toDateString(values.end_date),
  name: values.rule_name?.trim() || '',
});

export const singleFormValidators = {
  channel_id: isNotEmpty('Select a channel'),
  start_time: isNotEmpty('Select a start time'),
  end_time: (value, values) => {
    const start = asDate(values.start_time);
    const end = asDate(value);
    if (!end) return 'Select an end time';
    if (start && end <= start) return 'End time must be after start time';
    return null;
  },
};

export const recurringFormValidators = {
  channel_id: isNotEmpty('Select a channel'),
  days_of_week: (value) => (value?.length ? null : 'Pick at least one day'),
  start_time: (value) => (value ? null : 'Select a start time'),
  end_time: (value, values) => {
    if (!value) return 'Select an end time';
    const start = initializeTime(
      values.start_time,
      ['HH:mm', 'hh:mm A', 'h:mm A'],
      null,
      true
    );
    const end = initializeTime(
      value,
      ['HH:mm', 'hh:mm A', 'h:mm A'],
      null,
      true
    );
    if (isValid(start) && isValid(end) && diff(start, end, 'minute') === 0)
      return 'End time must differ from start time';
    return null;
  },
  end_date: (value, values) => {
    const end = asDate(value);
    const start = asDate(values.start_date);
    if (!end) return 'Select an end date';
    if (start && end < start) return 'End date cannot be before start date';
    return null;
  },
};
