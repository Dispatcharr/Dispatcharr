import API from '../../api.js';

export const getEPGs = () => {
  return API.getEPGs();
};

export const ADVANCED_OPTIONS_CONFIG = [
  {
    value: 'force_epg',
    label: 'Force EPG Source',
    description:
      'Force a specific EPG source for all auto-synced channels, or disable EPG assignment entirely',
    isActive: (p) =>
      p.custom_epg_id !== undefined ||
      p.force_dummy_epg ||
      p.force_epg_selected,
    defaults: { force_dummy_epg: true },
    removeKeys: ['force_dummy_epg', 'custom_epg_id', 'force_epg_selected'],
  },
  {
    value: 'group_override',
    label: 'Override Channel Group',
    description: 'Override the group assignment for all channels in this group',
    isActive: (p) => p.group_override !== undefined,
    defaults: { group_override: null },
    removeKeys: ['group_override'],
  },
  {
    value: 'name_regex',
    label: 'Channel Name Find & Replace (Regex)',
    description:
      'Find and replace part of the channel name using a regex pattern',
    isActive: (p) =>
      p.name_regex_pattern !== undefined ||
      p.name_replace_pattern !== undefined,
    defaults: { name_regex_pattern: '', name_replace_pattern: '' },
    removeKeys: ['name_regex_pattern', 'name_replace_pattern'],
  },
  {
    value: 'name_match_regex',
    label: 'Channel Name Filter (Regex)',
    description: 'Only sync channels whose name matches this regex.',
    isActive: (p) => p.name_match_regex !== undefined,
    defaults: { name_match_regex: '' },
    removeKeys: ['name_match_regex'],
  },
  {
    value: 'profile_assignment',
    label: 'Channel Profile Assignment',
    description:
      'Specify which channel profiles the auto-synced channels should be added to',
    isActive: (p) => p.channel_profile_ids !== undefined,
    defaults: { channel_profile_ids: [] },
    removeKeys: ['channel_profile_ids'],
  },
  {
    value: 'channel_sort_order',
    label: 'Channel Sort Order',
    description:
      'Specify the order in which channels are created (name, tvg_id, updated_at)',
    isActive: (p) => p.channel_sort_order !== undefined,
    defaults: { channel_sort_order: '', channel_sort_reverse: false },
    removeKeys: ['channel_sort_order', 'channel_sort_reverse'],
  },
  {
    value: 'stream_profile_assignment',
    label: 'Stream Profile Assignment',
    description:
      'Assign a specific stream profile to all channels in this group during auto sync',
    isActive: (p) => p.stream_profile_id !== undefined,
    defaults: { stream_profile_id: null },
    removeKeys: ['stream_profile_id'],
  },
  {
    value: 'custom_logo',
    label: 'Custom Logo',
    description:
      'Assign a custom logo to all auto-synced channels in this group',
    isActive: (p) => p.custom_logo_id !== undefined,
    defaults: { custom_logo_id: null },
    removeKeys: ['custom_logo_id'],
  },
];

export const getSelectedAdvancedOptions = (customProps) =>
  ADVANCED_OPTIONS_CONFIG.filter((opt) => opt.isActive(customProps ?? {})).map(
    (opt) => opt.value
  );

export const applyAdvancedOptionsChange = (prevCustomProps, newValues) => {
  const next = { ...prevCustomProps };

  // Add defaults for newly selected options
  for (const opt of ADVANCED_OPTIONS_CONFIG) {
    if (newValues.includes(opt.value) && !opt.isActive(next)) {
      Object.assign(next, opt.defaults);
    }
  }

  // Remove keys for deselected options
  for (const opt of ADVANCED_OPTIONS_CONFIG) {
    if (!newValues.includes(opt.value) && opt.isActive(next)) {
      for (const key of opt.removeKeys) delete next[key];
    }
  }

  return next;
};

export const getEpgSourceValue = (group) => {
  // Show custom EPG if set
  if (
    group.custom_properties?.custom_epg_id !== undefined &&
    group.custom_properties?.custom_epg_id !== null
  ) {
    return group.custom_properties.custom_epg_id.toString();
  }
  // Show "No EPG" if force_dummy_epg is set
  if (group.custom_properties?.force_dummy_epg) {
    return '0';
  }
  // Otherwise show empty/placeholder
  return null;
};

export const getEpgSourceData = (epgSources) => {
  return [
    { value: '0', label: 'No EPG (Disabled)' },
    ...[...epgSources]
      .sort((a, b) => a.name.localeCompare(b.name))
      .map((source) => ({
        value: source.id.toString(),
        label: `${source.name} (${
          source.source_type === 'dummy'
            ? 'Dummy'
            : source.source_type === 'xmltv'
              ? 'XMLTV'
              : source.source_type === 'schedules_direct'
                ? 'Schedules Direct'
                : source.source_type
        })`,
      })),
  ];
};
