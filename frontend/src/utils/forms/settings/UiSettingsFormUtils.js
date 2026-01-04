import { createSetting, updateSetting } from '../../pages/SettingsUtils.js';

export const saveTimeZoneSetting = async (tzValue, settings) => {
  const existing = settings['system-time-zone'];
  if (existing?.id) {
    await updateSetting({ ...existing, value: tzValue });
  } else {
    await createSetting({
      key: 'system-time-zone',
      name: 'System Time Zone',
      value: tzValue,
    });
  }
};