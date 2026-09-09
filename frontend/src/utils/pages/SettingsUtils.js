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

/**
 * Per-group field definitions. One source of truth for parse, diff, and save.
 *
 * ``type`` drives coerce/compare (and default parse). Optional ``parse`` /
 * ``default`` override per-field form hydration.
 */
const GROUP_CONFIG = {
  stream_settings: {
    name: 'Stream Settings',
    fields: {
      default_user_agent: { type: 'id' },
      default_stream_profile: { type: 'id' },
      m3u_hash_key: { type: 'm3u_hash_key', default: [] },
      default_output_format: { type: 'string', default: 'mpegts' },
      hdhr_output_profile_id: { type: 'id' },
    },
  },
  epg_settings: {
    name: 'EPG Settings',
    fields: {
      epg_match_mode: { type: 'string', default: 'default' },
      epg_match_ignore_prefixes: { type: 'array', default: [] },
      epg_match_ignore_suffixes: { type: 'array', default: [] },
      epg_match_ignore_custom: { type: 'array', default: [] },
    },
  },
  dvr_settings: {
    name: 'DVR Settings',
    fields: {
      tv_template: { type: 'raw', default: '' },
      movie_template: { type: 'raw', default: '' },
      tv_fallback_dir: { type: 'raw', default: '' },
      tv_fallback_template: { type: 'raw', default: '' },
      movie_fallback_template: { type: 'raw', default: '' },
      comskip_enabled: { type: 'bool', default: false },
      comskip_custom_path: { type: 'raw', default: '' },
      comskip_mode: { type: 'string', default: 'cut' },
      comskip_hw_accel: {
        type: 'string',
        default: 'none',
        // Legacy "qsv" never worked with the bundled binary; map to hwassist.
        parse: (value) => {
          const hwAccel = value || 'none';
          return hwAccel === 'qsv' ? 'hwassist' : hwAccel;
        },
      },
      pre_offset_minutes: { type: 'int', default: 0 },
      post_offset_minutes: { type: 'int', default: 0 },
      series_rules: { type: 'array', default: [] },
      output_profile_id: { type: 'id' },
    },
  },
  system_settings: {
    name: 'System Settings',
    fields: {
      time_zone: { type: 'string', default: '' },
      max_system_events: { type: 'int', default: 100 },
      log_max_mb: { type: 'int', default: 10 },
      log_keep: { type: 'int', default: 5 },
      log_persist: { type: 'bool', default: true },
      preferred_region: { type: 'nullable', default: null },
      auto_import_mapped_files: { type: 'bool', default: true },
      enable_ip_lookup: { type: 'bool', default: true },
      catchup_enabled: { type: 'bool', default: true },
    },
  },
};

const toOptionalIdString = (value) =>
  value != null ? String(value) : null;

const toIntOr = (value, fallback) =>
  typeof value === 'number' ? value : parseInt(value, 10) || fallback;

const toBool = (value, fallback = false) =>
  typeof value === 'boolean' ? value : value == null ? fallback : Boolean(value);

const parseM3uHashKey = (hashKey) => {
  if (typeof hashKey === 'string') {
    return hashKey ? hashKey.split(',').filter((v) => v) : [];
  }
  if (Array.isArray(hashKey)) {
    return hashKey;
  }
  return [];
};

const parseFieldValue = (def, rawValue) => {
  if (typeof def.parse === 'function') {
    return def.parse(rawValue);
  }

  switch (def.type) {
    case 'id':
      return toOptionalIdString(rawValue);
    case 'int':
      return toIntOr(rawValue, def.default ?? 0);
    case 'bool':
      return toBool(rawValue, def.default ?? false);
    case 'array':
      return Array.isArray(rawValue) ? rawValue : (def.default ?? []);
    case 'm3u_hash_key':
      return parseM3uHashKey(rawValue);
    case 'nullable':
      return rawValue ?? def.default ?? null;
    case 'string':
      if (rawValue == null || rawValue === '') {
        return def.default ?? '';
      }
      return String(rawValue);
    case 'raw':
      // Apply default only when missing; keep an explicit empty string.
      if (rawValue == null && 'default' in def) {
        return def.default;
      }
      return rawValue;
    default:
      return rawValue;
  }
};

const parseGroupValue = (groupKey, raw) => {
  const group = GROUP_CONFIG[groupKey];
  if (!group) {
    return {};
  }

  const hasRaw = raw && typeof raw === 'object';
  const parsed = {};

  for (const [field, def] of Object.entries(group.fields)) {
    parsed[field] = parseFieldValue(def, hasRaw ? raw[field] : undefined);
  }

  return parsed;
};

const normalizeForCompare = (groupKey, field, value) => {
  const type = GROUP_CONFIG[groupKey]?.fields[field]?.type;

  if (type === 'array') {
    return JSON.stringify(Array.isArray(value) ? value : []);
  }
  if (type === 'm3u_hash_key') {
    if (Array.isArray(value)) {
      return value.join(',');
    }
    return String(value ?? '');
  }
  if (type === 'id') {
    if (value == null || value === '') {
      return '';
    }
    return String(value);
  }
  if (value == null) {
    return '';
  }
  return String(value);
};

const coerceFieldValue = (groupKey, field, value) => {
  const type = GROUP_CONFIG[groupKey]?.fields[field]?.type;

  if (type === 'm3u_hash_key' && Array.isArray(value)) {
    return value.join(',');
  }

  if (type === 'id') {
    if (value == null || value === '') {
      return null;
    }
    return parseInt(value, 10) || null;
  }

  if (type === 'int' && value != null) {
    return typeof value === 'number' ? value : parseInt(value, 10);
  }

  if (type === 'bool' && value != null) {
    if (typeof value === 'boolean') {
      return value;
    }
    if (typeof value === 'string') {
      const lowered = value.trim().toLowerCase();
      return ['true', '1', 'yes', 'on'].includes(lowered);
    }
    return value === 1;
  }

  return value;
};

/**
 * Parse one settings group into flat form values for that group only.
 */
export const parseGroupSettings = (settings, groupKey) => {
  if (!GROUP_CONFIG[groupKey]) {
    return {};
  }
  return parseGroupValue(groupKey, settings?.[groupKey]?.value);
};

/**
 * Diff form values against one group's stored `.value`. Only changed fields
 * are returned (including explicit null clears for optional IDs).
 */
export const getChangedGroupSettings = (values, settings, groupKey) => {
  const group = GROUP_CONFIG[groupKey];
  if (!group) {
    return {};
  }

  const stored = settings?.[groupKey]?.value || {};
  const changed = {};

  for (const field of Object.keys(group.fields)) {
    if (!(field in values)) {
      continue;
    }

    let actualValue = values[field];
    if (
      group.fields[field].type === 'array' &&
      !Array.isArray(actualValue)
    ) {
      actualValue = [];
    }

    if (
      normalizeForCompare(groupKey, field, actualValue) ===
      normalizeForCompare(groupKey, field, stored[field])
    ) {
      continue;
    }

    changed[field] = actualValue;
  }

  return changed;
};

/**
 * Coerce and merge a patch into one settings group row (update or create).
 */
export const saveGroupSettings = async (settings, groupKey, patch) => {
  const group = GROUP_CONFIG[groupKey];
  if (!group) {
    throw new Error(`Unknown settings group: ${groupKey}`);
  }

  const changes = {};
  for (const [formKey, rawValue] of Object.entries(patch || {})) {
    if (!(formKey in group.fields)) {
      continue;
    }
    changes[formKey] = coerceFieldValue(groupKey, formKey, rawValue);
  }

  if (Object.keys(changes).length === 0) {
    return;
  }

  const existing = settings?.[groupKey];
  const currentValue = existing?.value || {};
  const newValue = { ...currentValue, ...changes };

  if (existing?.id) {
    const result = await updateSetting({ ...existing, value: newValue });
    if (!result) {
      throw new Error(`Failed to update ${groupKey}`);
    }
  } else {
    const result = await createSetting({
      key: groupKey,
      name: group.name || groupKey,
      value: newValue,
    });
    if (!result) {
      throw new Error(`Failed to create ${groupKey}`);
    }
  }
};
