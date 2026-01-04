import API from '../../api.js';

export const checkSetting = async (values) => {
  return await API.checkSetting(values);
};

export const updateSetting = async (values) => {
  return await API.updateSetting(values);
};

export const createSetting = async (values) => {
  return await API.createSetting(values);
};

export const rehashStreams = async () => {
  return await API.rehashStreams();
};

export const saveChangedSettings = async (settings, changedSettings) => {
  for (const updatedKey in changedSettings) {
    const existing = settings[updatedKey];
    if (existing?.id) {
      const result = await updateSetting({
        ...existing,
        value: changedSettings[updatedKey],
      });
      // API functions return undefined on error
      if (!result) {
        throw new Error('Failed to update setting');
      }
    } else {
      const result = await createSetting({
        key: updatedKey,
        name: updatedKey.replace(/-/g, ' '),
        value: changedSettings[updatedKey],
      });
      // API functions return undefined on error
      if (!result) {
        throw new Error('Failed to create setting');
      }
    }
  }
};

export const getChangedSettings = (values, settings) => {
  const changedSettings = {};

  for (const settingKey in values) {
    // Only compare against existing value if the setting exists
    const existing = settings[settingKey];

    // Convert array values (like m3u-hash-key) to comma-separated strings
    const stringValue = Array.isArray(values[settingKey])
      ? values[settingKey].join(',')
      : `${values[settingKey]}`;

    // Skip empty values to avoid validation errors
    if (!stringValue) {
      continue;
    }

    if (!existing) {
      // Create new setting on save
      changedSettings[settingKey] = stringValue;
    } else if (stringValue !== String(existing.value)) {
      // If the user changed the setting's value from what's in the DB:
      changedSettings[settingKey] = stringValue;
    }
  }
  return changedSettings;
};

export const parseSettings = (settings) => {
  return Object.entries(settings).reduce((acc, [key, value]) => {
    // Modify each value based on its own properties
    switch (value.value) {
      case 'true':
        value.value = true;
        break;
      case 'false':
        value.value = false;
        break;
    }

    let val = null;
    switch (key) {
      case 'm3u-hash-key':
        // Split comma-separated string, filter out empty strings
        val = value.value ? value.value.split(',').filter((v) => v) : [];
        break;
      case 'dvr-pre-offset-minutes':
      case 'dvr-post-offset-minutes':
        val = Number.parseInt(value.value || '0', 10);
        if (Number.isNaN(val)) val = 0;
        break;
      default:
        val = value.value;
        break;
    }

    acc[key] = val;
    return acc;
  }, {});
};