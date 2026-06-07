import API from '../../api.js';

// Fields that users can override on an auto-synced channel. Mirrors
// `OVERRIDABLE_FIELDS` in `apps/channels/managers.py`. Keep the two in sync.
export const OVERRIDABLE_FIELDS = [
  'name',
  'channel_number',
  'channel_group_id',
  'logo_id',
  'tvg_id',
  'tvc_guide_stationid',
  'epg_data_id',
  'stream_profile_id',
];

// Display labels for the override fields above.
export const OVERRIDE_FIELD_LABELS = {
  name: 'Name',
  channel_number: 'Channel Number',
  channel_group_id: 'Channel Group',
  logo_id: 'Logo',
  tvg_id: 'TVG-ID',
  tvc_guide_stationid: 'Gracenote Station ID',
  epg_data_id: 'EPG',
  stream_profile_id: 'Stream Profile',
};

export const matchChannelEpg = (channel) => {
  return API.matchChannelEpg(channel.id);
};
export const createLogo = (newLogoData) => {
  return API.createLogo(newLogoData);
};
const setChannelEPG = (channel, values) => {
  return API.setChannelEPG(channel.id, values.epg_data_id);
};
const updateChannel = (values) => {
  return API.updateChannel(values);
};
export const addChannel = (channel) => {
  return API.addChannel(channel);
};
export const requeryChannels = () => {
  API.requeryChannels();
};

// PATCH semantic: `override: null` deletes the override row; per-field
// nulls only clear the matching field.
export const clearChannelOverrides = (channelId) => {
  return API.updateChannel({ id: channelId, override: null });
};

// Coerce a form value to the backend's storage shape so equality
// comparisons against channel data don't drift on type mismatches.
export const normalizeFieldValue = (field, value) => {
  if (value === '' || value === null || value === undefined || value === '-1') {
    return null;
  }
  // The stream_profile and logo pickers encode "(use default)" as '0',
  // which is semantically a null FK on the Channel row.
  if ((field === 'stream_profile_id' || field === 'logo_id') && value === '0') {
    return null;
  }
  if (field === 'channel_number') {
    const n = parseFloat(value);
    return Number.isFinite(n) ? n : null;
  }
  if (
    field === 'channel_group_id' ||
    field === 'logo_id' ||
    field === 'epg_data_id' ||
    field === 'stream_profile_id'
  ) {
    const n = parseInt(value, 10);
    return Number.isFinite(n) ? n : null;
  }
  return value;
};

// Per-field form shape for FK pickers (string for popovers, raw for
// the EPG select); used by the reset-to-provider affordance.
const PROVIDER_FORM_VALUE_BUILDERS = {
  channel_group_id: (channel) =>
    channel?.channel_group_id != null ? `${channel.channel_group_id}` : '',
  stream_profile_id: (channel) =>
    channel?.stream_profile_id != null ? `${channel.stream_profile_id}` : '0',
  logo_id: (channel) => (channel?.logo_id != null ? `${channel.logo_id}` : ''),
  epg_data_id: (channel) => channel?.epg_data_id ?? '',
};

export const getProviderFormValue = (channel, field) => {
  const builder = PROVIDER_FORM_VALUE_BUILDERS[field];
  if (builder) return builder(channel);
  return channel?.[field] ?? '';
};

// Whether a field carries an override. Manual channels return false (no
// provider value to override). True when a persisted override row holds a
// value for the field, OR the live form value diverges from provider. The
// persisted check keeps the reset control available when an override's
// value coincides with the provider value.
export const isFormFieldOverridden = (channel, field, formValue) => {
  if (!channel?.auto_created) return false;
  const persisted = channel.override?.[field];
  if (persisted !== null && persisted !== undefined) return true;
  const normalizedForm = normalizeFieldValue(field, formValue);
  const normalizedProvider = normalizeFieldValue(field, channel[field]);
  return normalizedForm !== normalizedProvider;
};

// Human labels for the table's overrides indicator tooltip.
export const listOverriddenFields = (channel) => {
  if (!channel?.override) return [];
  return OVERRIDABLE_FIELDS.filter((field) => {
    const value = channel.override[field];
    return value !== null && value !== undefined;
  }).map((field) => OVERRIDE_FIELD_LABELS[field]);
};

// "Provider: <value>" subtext for auto-synced channels (null for manual).
export const getProviderHint = (channel, field) => {
  if (!channel?.auto_created) return null;
  const providerValue = channel[field];
  const display =
    providerValue === null ||
    providerValue === undefined ||
    providerValue === ''
      ? '(empty)'
      : providerValue;
  return `Provider: ${display}`;
};

// FK provider hint that resolves the ID to a display name via lookup.
export const getFkProviderHint = (channel, field, lookup) => {
  if (!channel?.auto_created) return null;
  const providerId = channel[field];
  if (providerId === null || providerId === undefined) {
    return 'Provider: (none)';
  }
  const entry = lookup?.[providerId];
  const display = entry?.name || entry?.tvg_id || String(providerId);
  return `Provider: ${display}`;
};

// Build the override PATCH payload by diffing form values against
// provider values. Matching fields become null (clear); diverging
// fields carry the form value.
export const buildOverridePayload = (channel, formattedValues) => {
  if (!channel) return undefined;
  const payload = {};
  let anyOverride = false;

  for (const field of OVERRIDABLE_FIELDS) {
    const formValue = normalizeFieldValue(field, formattedValues[field]);
    const providerValue = normalizeFieldValue(field, channel[field]);
    if (formValue === null && providerValue === null) continue;
    if (formValue !== providerValue) {
      payload[field] = formValue;
      if (formValue !== null) anyOverride = true;
    } else {
      payload[field] = null;
    }
  }

  if (!anyOverride) {
    // Every field matches provider; explicit null deletes the row.
    return null;
  }
  return payload;
};

// Prefer the backend-resolved effective_* so the form loads with the
// overridden value; fall back to the raw field otherwise.
const effective = (channel, field) => {
  if (!channel) return undefined;
  const effKey = `effective_${field}`;
  if (effKey in channel && channel[effKey] !== undefined) {
    return channel[effKey];
  }
  return channel[field];
};

export const getChannelFormDefaultValues = (channel, channelGroups) => {
  const name = effective(channel, 'name') ?? '';
  const channelNumber = effective(channel, 'channel_number');
  const groupId = effective(channel, 'channel_group_id');
  const streamProfileId = effective(channel, 'stream_profile_id');
  const tvgId = effective(channel, 'tvg_id');
  const gracenoteId = effective(channel, 'tvc_guide_stationid');
  const epgDataId = effective(channel, 'epg_data_id');
  const logoId = effective(channel, 'logo_id');
  return {
    name: name || '',
    channel_number:
      channelNumber !== null && channelNumber !== undefined
        ? channelNumber
        : '',
    channel_group_id: groupId
      ? `${groupId}`
      : Object.keys(channelGroups).length > 0
        ? Object.keys(channelGroups)[0]
        : '',
    stream_profile_id: streamProfileId ? `${streamProfileId}` : '0',
    tvg_id: tvgId || '',
    tvc_guide_stationid: gracenoteId || '',
    epg_data_id: epgDataId ?? '',
    logo_id: logoId ? `${logoId}` : '',
    user_level: `${channel?.user_level ?? '0'}`,
    is_adult: channel?.is_adult ?? false,
    hidden_from_output: channel?.hidden_from_output ?? false,
  };
};

export const getFormattedValues = (values) => {
  const formattedValues = { ...values };

  // Convert empty or "0" stream_profile_id to null for the API
  if (
    !formattedValues.stream_profile_id ||
    formattedValues.stream_profile_id === '0'
  ) {
    formattedValues.stream_profile_id = null;
  }

  // Ensure tvg_id is properly included (no empty strings)
  formattedValues.tvg_id = formattedValues.tvg_id || null;

  // Ensure tvc_guide_stationid is properly included (no empty strings)
  formattedValues.tvc_guide_stationid =
    formattedValues.tvc_guide_stationid || null;

  return formattedValues;
};

export const handleEpgUpdate = async (
  channel,
  values,
  formattedValues,
  channelStreams
) => {
  // Auto-synced channels route identity edits into the override row. Sync
  // keeps writing provider values to Channel.* unmodified, so the override
  // is what actually persists user changes across refreshes. `hidden_from_output`
  // stays as a direct Channel field even for auto-created channels because
  // it is a status flag, not a value replacement.
  if (channel.auto_created) {
    const overridePayload = buildOverridePayload(channel, formattedValues);
    const payload = {
      id: channel.id,
      hidden_from_output: formattedValues.hidden_from_output,
    };
    if (overridePayload !== undefined) {
      payload.override = overridePayload;
    }
    await updateChannel(payload);
    return;
  }

  // Manual channels: existing behavior preserved. When the EPG has changed,
  // the dedicated set-EPG endpoint triggers an EPG refresh; other field
  // updates go through the regular PATCH and are skipped entirely when
  // there is nothing besides epg_data_id to update.
  if (values.epg_data_id !== (channel.epg_data_id ?? '')) {
    await setChannelEPG(channel, values);

    const { epg_data_id: _epg_data_id, ...otherValues } = formattedValues;
    if (Object.keys(otherValues).length > 0) {
      await updateChannel({
        id: channel.id,
        ...otherValues,
        streams: channelStreams.map((stream) => stream.id),
      });
    }
  } else {
    await updateChannel({
      id: channel.id,
      ...formattedValues,
      streams: channelStreams.map((stream) => stream.id),
    });
  }
};
