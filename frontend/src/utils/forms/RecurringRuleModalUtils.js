import API from '../../api.js';
import { toTimeString } from '../dateTimeUtils.js';
import dayjs from 'dayjs';

export const getChannelOptions = (channels) => {
  return Object.values(channels || {})
    .sort((a, b) => {
      const aNum = Number(a.channel_number) || 0;
      const bNum = Number(b.channel_number) || 0;
      if (aNum === bNum) {
        return (a.name || '').localeCompare(b.name || '');
      }
      return aNum - bNum;
    })
    .map((item) => ({
      value: `${item.id}`,
      label: item.name || `Channel ${item.id}`,
    }));
};

export const getUpcomingOccurrences = (
  recordings,
  userNow,
  ruleId,
  toUserTime
) => {
  const list = Array.isArray(recordings)
    ? recordings
    : Object.values(recordings || {});
  const now = userNow();
  return list
    .filter(
      (rec) =>
        rec?.custom_properties?.rule?.id === ruleId &&
        toUserTime(rec.start_time).isAfter(now)
    )
    .sort(
      (a, b) =>
        toUserTime(a.start_time).valueOf() - toUserTime(b.start_time).valueOf()
    );
};

export const updateRecurringRule = async (ruleId, values) => {
  await API.updateRecurringRule(ruleId, {
    channel: values.channel_id,
    days_of_week: (values.days_of_week || []).map((d) => Number(d)),
    start_time: toTimeString(values.start_time),
    end_time: toTimeString(values.end_time),
    start_date: values.start_date
      ? dayjs(values.start_date).format('YYYY-MM-DD')
      : null,
    end_date: values.end_date
      ? dayjs(values.end_date).format('YYYY-MM-DD')
      : null,
    name: values.rule_name?.trim() || '',
    enabled: Boolean(values.enabled),
  });
};

export const deleteRecurringRuleById = async (ruleId) => {
  await API.deleteRecurringRule(ruleId);
};

export const updateRecurringRuleEnabled = async (ruleId, checked) => {
  await API.updateRecurringRule(ruleId, { enabled: checked });
};