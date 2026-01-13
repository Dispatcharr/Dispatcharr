import { createSetting, updateSetting } from '../../pages/SettingsUtils.js';

export const saveTimeZoneSetting = async (tzValue, settings) => {
  const existing = settings['system_settings'];
  const currentValue = existing?.value || {};
  const newValue = { ...currentValue, time_zone: tzValue };

  if (existing?.id) {
    await updateSetting({ ...existing, value: newValue });
  } else {
    await createSetting({
      key: 'system_settings',
      name: 'System Settings',
      value: newValue,
    });
  }
};