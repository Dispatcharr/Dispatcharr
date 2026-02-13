/**
 * Cron expression validation utility.
 *
 * Shared across CronModal, BackupManager, and any other component
 * that needs to validate 5-part cron expressions.
 */

export function validateCronExpression(expression) {
  if (!expression || expression.trim() === '') {
    return { valid: false, error: 'Cron expression is required' };
  }

  const parts = expression.trim().split(/\s+/);
  if (parts.length !== 5) {
    return {
      valid: false,
      error:
        'Cron expression must have exactly 5 parts: minute hour day month weekday',
    };
  }

  const [minute, hour, dayOfMonth, month, dayOfWeek] = parts;

  const cronPartRegex =
    /^(\*\/\d+|\*|\d+(-\d+)?(\/\d+)?(,\d+(-\d+)?(\/\d+)?)*)$/;

  const fields = [
    { value: minute, label: 'minute', min: 0, max: 59 },
    { value: hour, label: 'hour', min: 0, max: 23 },
    { value: dayOfMonth, label: 'day', min: 1, max: 31 },
    { value: month, label: 'month', min: 1, max: 12 },
    { value: dayOfWeek, label: 'weekday', min: 0, max: 6 },
  ];

  for (const { value, label, min, max } of fields) {
    if (!cronPartRegex.test(value)) {
      return {
        valid: false,
        error: `Invalid ${label} field (${min}-${max}, *, or cron syntax)`,
      };
    }

    // Extra numeric-range check for plain numbers
    if (
      !(
        value === '*' ||
        value.includes('/') ||
        value.includes('-') ||
        value.includes(',')
      )
    ) {
      const num = parseInt(value, 10);
      if (isNaN(num) || num < min || num > max) {
        return {
          valid: false,
          error: `${label.charAt(0).toUpperCase() + label.slice(1)} must be between ${min} and ${max}`,
        };
      }
    }
  }

  return { valid: true, error: null };
}
