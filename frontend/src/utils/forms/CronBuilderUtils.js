export const PRESETS = [
  {
    label: 'Every hour',
    value: '0 * * * *',
    description: 'At the start of every hour',
  },
  {
    label: 'Every 6 hours',
    value: '0 */6 * * *',
    description: 'Every 6 hours starting at midnight',
  },
  {
    label: 'Every 12 hours',
    value: '0 */12 * * *',
    description: 'Twice daily at midnight and noon',
  },
  {
    label: 'Daily at midnight',
    value: '0 0 * * *',
    description: 'Once per day at 12:00 AM',
  },
  {
    label: 'Daily at 3 AM',
    value: '0 3 * * *',
    description: 'Once per day at 3:00 AM',
  },
  {
    label: 'Daily at noon',
    value: '0 12 * * *',
    description: 'Once per day at 12:00 PM',
  },
  {
    label: 'Weekly (Sunday midnight)',
    value: '0 0 * * 0',
    description: 'Once per week on Sunday',
  },
  {
    label: 'Weekly (Monday 3 AM)',
    value: '0 3 * * 1',
    description: 'Once per week on Monday',
  },
  {
    label: 'Monthly (1st at 2:30 AM)',
    value: '30 2 1 * *',
    description: 'First day of each month',
  },
];

export const DAYS_OF_WEEK = [
  { value: '*', label: 'Every day' },
  { value: '0', label: 'Sunday' },
  { value: '1', label: 'Monday' },
  { value: '2', label: 'Tuesday' },
  { value: '3', label: 'Wednesday' },
  { value: '4', label: 'Thursday' },
  { value: '5', label: 'Friday' },
  { value: '6', label: 'Saturday' },
];

export const FREQUENCY_OPTIONS = [
  { value: 'hourly', label: 'Hourly' },
  { value: 'daily', label: 'Daily' },
  { value: 'weekly', label: 'Weekly' },
  { value: 'monthly', label: 'Monthly' },
];

/** Simple-mode choices for hourly schedules (maps to the cron hour field). */
export const HOURLY_INTERVAL_OPTIONS = [
  { value: '*', label: 'Every hour' },
  { value: '*/2', label: 'Every 2 hours' },
  { value: '*/3', label: 'Every 3 hours' },
  { value: '*/4', label: 'Every 4 hours' },
  { value: '*/6', label: 'Every 6 hours' },
  { value: '*/8', label: 'Every 8 hours' },
  { value: '*/12', label: 'Every 12 hours' },
];

/** Hour field uses steps, lists, ranges, or wildcard (not a single 0-23 value). */
export const isHourlyHourPattern = (hr) => hr === '*' || /[^0-9]/.test(hr);

export const buildCron = (
  frequency,
  minute,
  hour,
  dayOfWeek,
  dayOfMonth,
  hours = '*'
) => {
  switch (frequency) {
    case 'hourly':
      return `${minute} ${hours || '*'} * * *`;
    case 'daily':
      return `${minute} ${hour} * * *`;
    case 'weekly':
      return `${minute} ${hour} * * ${dayOfWeek === '*' ? '0' : dayOfWeek}`;
    case 'monthly':
      return `${minute} ${hour} ${dayOfMonth} * *`;
    default:
      return '* * * * *';
  }
};

export const parseCronPreset = (cron) => {
  const [min, hr, day, _month, weekday] = cron.split(' ');
  const minute = parseInt(min, 10) || 0;
  const parsedHour = parseInt(hr, 10);
  const hour = Number.isNaN(parsedHour) ? 0 : parsedHour;

  if (weekday !== '*')
    return {
      frequency: 'weekly',
      minute,
      hour,
      hours: '*',
      dayOfWeek: weekday,
      dayOfMonth: 1,
    };
  if (day !== '*')
    return {
      frequency: 'monthly',
      minute,
      hour,
      hours: '*',
      dayOfWeek: '*',
      dayOfMonth: parseInt(day, 10) || 1,
    };
  if (isHourlyHourPattern(hr))
    return {
      frequency: 'hourly',
      minute,
      hour: 0,
      hours: hr,
      dayOfWeek: '*',
      dayOfMonth: 1,
    };
  return {
    frequency: 'daily',
    minute,
    hour,
    hours: '*',
    dayOfWeek: '*',
    dayOfMonth: 1,
  };
};

export const CRON_FIELDS = [
  { index: 0, label: 'Minute (0-59)', placeholder: '*, 0, */15, 0,15,30,45' },
  { index: 1, label: 'Hour (0-23)', placeholder: '*, 0, 9-17, */6, 2,4,16' },
  {
    index: 2,
    label: 'Day of Month (1-31)',
    placeholder: '*, 1, 1-15, */2, 1,15',
  },
  { index: 3, label: 'Month (1-12)', placeholder: '*, 1, 1-6, */3, 6,12' },
  {
    index: 4,
    label: 'Day of Week (0-6, Sun-Sat)',
    placeholder: '*, 0, 1-5, 0,6',
  },
];

export const updateCronPart = (cron, index, value) => {
  const parts =
    cron.split(' ').length >= 5 ? cron.split(' ') : ['*', '*', '*', '*', '*'];
  parts[index] = value || '*';
  return parts.join(' ');
};
