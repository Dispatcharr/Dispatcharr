export const getTimeshiftSettingsFormInitialValues = () => {
  return {
    timeshift_default_timezone: 'UTC',
    timeshift_default_language: 'en',
    xmltv_prev_days_override: 0,
    timeshift_debug_logging: false,
  };
};

export const getTimeshiftSettingsFormValidation = () => {
  return {
    timeshift_default_language: (value) =>
      value && !/^[a-z]{2}$/i.test(value)
        ? 'Must be a 2-letter ISO 639-1 code'
        : null,
  };
};
