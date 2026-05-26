import API from '../../api.js';
import {
  getNow,
  isAfter,
  parseDate,
  toDate,
  toTimeString,
} from '../dateTimeUtils.js';
import { buildRecurringPayload } from './RecordingUtils.js';

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
        isAfter(toUserTime(rec.start_time), now)
    )
    .sort(
      (a, b) =>
        toUserTime(a.start_time).valueOf() - toUserTime(b.start_time).valueOf()
    );
};

export const updateRecurringRule = async (ruleId, values) => {
  await API.updateRecurringRule(ruleId, {
    ...buildRecurringPayload(values),
    enabled: Boolean(values.enabled),
  });
};

export const deleteRecurringRuleById = async (ruleId) => {
  await API.deleteRecurringRule(ruleId);
};

export const updateRecurringRuleEnabled = async (ruleId, checked) => {
  await API.updateRecurringRule(ruleId, { enabled: checked });
};

export const getFormDefaults = (rule) => {
  return {
    channel_id: `${rule.channel}`,
    days_of_week: (rule.days_of_week || []).map((d) => String(d)),
    rule_name: rule.name || '',
    start_time: toTimeString(rule.start_time),
    end_time: toTimeString(rule.end_time),
    start_date: parseDate(rule.start_date) || toDate(getNow()),
    end_date: parseDate(rule.end_date),
    enabled: Boolean(rule.enabled),
  };
};
