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
  // Group changes by their setting group based on field name prefixes
  const groupedChanges = {
    stream_settings: {},
    epg_settings: {},
    dvr_settings: {},
    backup_settings: {},
    system_settings: {},
  };

  // Map of field prefixes to their groups
  const streamFields = [
    'default_user_agent',
    'default_stream_profile',
    'm3u_hash_key',
    'preferred_region',
    'auto_import_mapped_files',
    'tmdb_api_key',
  ];
  const epgFields = [
    'epg_match_mode',
    'epg_match_ignore_prefixes',
    'epg_match_ignore_suffixes',
    'epg_match_ignore_custom',
  ];
  const dvrFields = [
    'tv_template',
    'movie_template',
    'tv_fallback_dir',
    'tv_fallback_template',
    'movie_fallback_template',
    'comskip_enabled',
    'comskip_custom_path',
    'pre_offset_minutes',
    'post_offset_minutes',
    'series_rules',
  ];
  const backupFields = [
    'schedule_enabled',
    'schedule_frequency',
    'schedule_time',
    'schedule_day_of_week',
    'retention_count',
    'schedule_cron_expression',
  ];
  const systemFields = ['time_zone', 'max_system_events'];

  for (const formKey in changedSettings) {
    let value = changedSettings[formKey];

    // Handle special grouped settings (proxy_settings and network_access)
    if (formKey === 'proxy_settings') {
      const existing = settings['proxy_settings'];
      if (existing?.id) {
        await updateSetting({ ...existing, value });
      } else {
        await createSetting({
          key: 'proxy_settings',
          name: 'Proxy Settings',
          value,
        });
      }
      continue;
    }

    if (formKey === 'network_access') {
      const existing = settings['network_access'];
      if (existing?.id) {
        await updateSetting({ ...existing, value });
      } else {
        await createSetting({
          key: 'network_access',
          name: 'Network Access',
          value,
        });
      }
      continue;
    }

    // Type conversions for proper storage
    // EPG fields should remain as arrays, don't convert them
    if (formKey === 'm3u_hash_key' && Array.isArray(value)) {
      value = value.join(',');
    }

    if (
      ['default_user_agent', 'default_stream_profile'].includes(formKey) &&
      value != null
    ) {
      value = parseInt(value, 10);
    }

    const numericFields = [
      'pre_offset_minutes',
      'post_offset_minutes',
      'retention_count',
      'schedule_day_of_week',
      'max_system_events',
    ];
    if (numericFields.includes(formKey) && value != null) {
      value = typeof value === 'number' ? value : parseInt(value, 10);
    }

    const booleanFields = [
      'comskip_enabled',
      'schedule_enabled',
      'auto_import_mapped_files',
    ];
    if (booleanFields.includes(formKey) && value != null) {
      value = typeof value === 'boolean' ? value : Boolean(value);
    }

    // Route to appropriate group
    if (streamFields.includes(formKey)) {
      groupedChanges.stream_settings[formKey] = value;
    } else if (epgFields.includes(formKey)) {
      groupedChanges.epg_settings[formKey] = value;
    } else if (dvrFields.includes(formKey)) {
      groupedChanges.dvr_settings[formKey] = value;
    } else if (backupFields.includes(formKey)) {
      groupedChanges.backup_settings[formKey] = value;
    } else if (systemFields.includes(formKey)) {
      groupedChanges.system_settings[formKey] = value;
    }
  }

  // Update each group that has changes
  for (const [groupKey, changes] of Object.entries(groupedChanges)) {
    if (Object.keys(changes).length === 0) continue;

    const existing = settings[groupKey];
    const currentValue = existing?.value || {};
    const newValue = { ...currentValue, ...changes };

    if (existing?.id) {
      const result = await updateSetting({ ...existing, value: newValue });
      if (!result) {
        throw new Error(`Failed to update ${groupKey}`);
      }
    } else {
      const name = groupKey
        .split('_')
        .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
        .join(' ');
      const result = await createSetting({
        key: groupKey,
        name: name,
        value: newValue,
      });
      if (!result) {
        throw new Error(`Failed to create ${groupKey}`);
      }
    }
  }
};

export const getChangedSettings = (values, settings) => {
  const changedSettings = {};

  // EPG fields that should be kept as arrays
  const epgFields = [
    'epg_match_ignore_prefixes',
    'epg_match_ignore_suffixes',
    'epg_match_ignore_custom',
  ];

  for (const settingKey in values) {
    // Skip grouped settings that are handled by their own dedicated forms
    if (settingKey === 'proxy_settings' || settingKey === 'network_access') {
      continue;
    }

    // Only compare against existing value if the setting exists
    const existing = settings[settingKey];

    let actualValue = values[settingKey];
    let compareValue;

    // Handle EPG mode field - always include (defaults to 'default' if not set)
    if (settingKey === 'epg_match_mode') {
      changedSettings[settingKey] = actualValue || 'default';
      continue;
    }

    if (settingKey === 'tmdb_api_key') {
      changedSettings[settingKey] = String(actualValue || '');
      continue;
    }

    // Handle EPG fields specially - keep as arrays, don't skip empty arrays
    if (epgFields.includes(settingKey)) {
      if (!Array.isArray(actualValue)) {
        actualValue = [];
      }
      // Always include EPG fields in changes (even if empty)
      changedSettings[settingKey] = actualValue;
      continue;
    }

    // Convert array values (like m3u_hash_key) to comma-separated strings for comparison
    if (Array.isArray(actualValue)) {
      actualValue = actualValue.join(',');
      compareValue = actualValue;
    } else {
      compareValue = String(actualValue);
    }

    // Skip empty values to avoid validation errors
    if (!compareValue) {
      continue;
    }

    if (!existing) {
      // Create new setting on save - preserve original type
      changedSettings[settingKey] = actualValue;
    } else if (compareValue !== String(existing.value)) {
      // If the user changed the setting's value from what's in the DB - preserve original type
      changedSettings[settingKey] = actualValue;
    }
  }
  return changedSettings;
};

export const parseSettings = (settings) => {
  const parsed = {};

  // Stream settings - direct mapping with underscore keys
  const streamSettings = settings['stream_settings']?.value;
  if (streamSettings && typeof streamSettings === 'object') {
    // IDs must be strings for Select components
    parsed.default_user_agent =
      streamSettings.default_user_agent != null
        ? String(streamSettings.default_user_agent)
        : null;
    parsed.default_stream_profile =
      streamSettings.default_stream_profile != null
        ? String(streamSettings.default_stream_profile)
        : null;
    parsed.preferred_region = streamSettings.preferred_region;
    parsed.auto_import_mapped_files = streamSettings.auto_import_mapped_files;
    parsed.tmdb_api_key = String(streamSettings.tmdb_api_key || '');

    // m3u_hash_key should be array
    const hashKey = streamSettings.m3u_hash_key;
    if (typeof hashKey === 'string') {
      parsed.m3u_hash_key = hashKey ? hashKey.split(',').filter((v) => v) : [];
    } else if (Array.isArray(hashKey)) {
      parsed.m3u_hash_key = hashKey;
    } else {
      parsed.m3u_hash_key = [];
    }
  }

  if (!parsed.tmdb_api_key) {
    const mediaLibrarySettings = settings['media_library_settings']?.value;
    if (mediaLibrarySettings && typeof mediaLibrarySettings === 'object') {
      parsed.tmdb_api_key = String(mediaLibrarySettings.tmdb_api_key || '');
    } else {
      const legacyTmdb = settings['tmdb-api-key']?.value;
      if (legacyTmdb != null) {
        parsed.tmdb_api_key = String(legacyTmdb);
      }
    }
  }

  // EPG settings - direct mapping with underscore keys
  const epgSettings = settings['epg_settings']?.value;
  // Always set EPG fields (even if settings don't exist yet)
  parsed.epg_match_ignore_prefixes =
    epgSettings && Array.isArray(epgSettings.epg_match_ignore_prefixes)
      ? epgSettings.epg_match_ignore_prefixes
      : [];
  parsed.epg_match_ignore_suffixes =
    epgSettings && Array.isArray(epgSettings.epg_match_ignore_suffixes)
      ? epgSettings.epg_match_ignore_suffixes
      : [];
  parsed.epg_match_ignore_custom =
    epgSettings && Array.isArray(epgSettings.epg_match_ignore_custom)
      ? epgSettings.epg_match_ignore_custom
      : [];

  // DVR settings - direct mapping with underscore keys
  const dvrSettings = settings['dvr_settings']?.value;
  if (dvrSettings && typeof dvrSettings === 'object') {
    parsed.tv_template = dvrSettings.tv_template;
    parsed.movie_template = dvrSettings.movie_template;
    parsed.tv_fallback_dir = dvrSettings.tv_fallback_dir;
    parsed.tv_fallback_template = dvrSettings.tv_fallback_template;
    parsed.movie_fallback_template = dvrSettings.movie_fallback_template;
    parsed.comskip_enabled =
      typeof dvrSettings.comskip_enabled === 'boolean'
        ? dvrSettings.comskip_enabled
        : Boolean(dvrSettings.comskip_enabled);
    parsed.comskip_custom_path = dvrSettings.comskip_custom_path;
    parsed.pre_offset_minutes =
      typeof dvrSettings.pre_offset_minutes === 'number'
        ? dvrSettings.pre_offset_minutes
        : parseInt(dvrSettings.pre_offset_minutes, 10) || 0;
    parsed.post_offset_minutes =
      typeof dvrSettings.post_offset_minutes === 'number'
        ? dvrSettings.post_offset_minutes
        : parseInt(dvrSettings.post_offset_minutes, 10) || 0;
    parsed.series_rules = dvrSettings.series_rules;
  }

  // Backup settings - direct mapping with underscore keys
  const backupSettings = settings['backup_settings']?.value;
  if (backupSettings && typeof backupSettings === 'object') {
    parsed.schedule_enabled =
      typeof backupSettings.schedule_enabled === 'boolean'
        ? backupSettings.schedule_enabled
        : Boolean(backupSettings.schedule_enabled);
    parsed.schedule_frequency = String(backupSettings.schedule_frequency || '');
    parsed.schedule_time = String(backupSettings.schedule_time || '');
    parsed.schedule_day_of_week =
      typeof backupSettings.schedule_day_of_week === 'number'
        ? backupSettings.schedule_day_of_week
        : parseInt(backupSettings.schedule_day_of_week, 10) || 0;
    parsed.retention_count =
      typeof backupSettings.retention_count === 'number'
        ? backupSettings.retention_count
        : parseInt(backupSettings.retention_count, 10) || 0;
    parsed.schedule_cron_expression = String(
      backupSettings.schedule_cron_expression || ''
    );
  }

  // System settings - direct mapping with underscore keys
  const systemSettings = settings['system_settings']?.value;
  if (systemSettings && typeof systemSettings === 'object') {
    parsed.time_zone = String(systemSettings.time_zone || '');
    parsed.max_system_events =
      typeof systemSettings.max_system_events === 'number'
        ? systemSettings.max_system_events
        : parseInt(systemSettings.max_system_events, 10) || 100;
  }

  // Proxy and network access are already grouped objects
  if (settings['proxy_settings']?.value) {
    parsed.proxy_settings = settings['proxy_settings'].value;
  }
  if (settings['network_access']?.value) {
    parsed.network_access = settings['network_access'].value;
  }

  return parsed;
};
