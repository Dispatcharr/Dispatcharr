import API from '../../api.js';

export const getEPGs = () => {
  return API.getEPGs();
};

export const getChannelsInRange = (start, end, controller) => {
  return API.getChannelsInRange(start, end, {
    signal: controller.signal,
  });
};

export const getStreamsRegexPreview = (
  group,
  find,
  replace,
  match,
  exclude,
  controller,
  playlist
) => {
  return API.getStreamsRegexPreview(group.name, {
    find: find || undefined,
    replace: find ? replace : undefined,
    match: match || undefined,
    exclude: exclude || undefined,
    limit: 10,
    signal: controller.signal,
    m3uAccountId: playlist?.id,
  });
};

// "Expected" occupants are this group's own auto-sync output:
// auto_created, in this group on this account, no channel_number
// override. Channels from any other provider, group, or with a user
// pin all surface as a warning so the user is aware their range
// overlaps with existing assignments. Sync still merges shared
// ranges across providers, so the warning is informational rather
// than blocking.
export const isExpectedOccupantForGroup = (
  occupant,
  groupChannelGroupId,
  playlist
) => {
  if (!occupant) return false;
  if (!occupant.auto_created) return false;
  if (occupant.has_channel_number_override) return false;
  if (
    occupant.channel_group_id !== undefined &&
    occupant.channel_group_id !== groupChannelGroupId
  )
    return false;
  return !(
    occupant.auto_created_by_account_id !== undefined &&
    playlist?.id !== undefined &&
    occupant.auto_created_by_account_id !== playlist.id
  );
};

// The group the sync's own channels actually land in. A group_override
// routes auto-created channels into a different ChannelGroup, so the
// conflict check must recognize occupants of that target group as this
// config's own output rather than flagging them against the source group.
export const effectiveSyncGroupId = (group) => {
  const override = group?.custom_properties?.group_override;
  if (override !== undefined && override !== null && override !== '') {
    return Number(override);
  }
  return group?.channel_group;
};

export const rangeFor = (g) => {
  if (!g.enabled || !g.auto_channel_sync) return null;
  const mode = g.custom_properties?.channel_numbering_mode || 'fixed';
  if (mode === 'next_available') return null;
  const startRaw =
    mode === 'provider'
      ? (g.custom_properties?.channel_numbering_fallback ?? 1)
      : (g.auto_sync_channel_start ?? 1);
  const start = Number(startRaw);
  if (!Number.isFinite(start)) return null;
  const endRaw = g.auto_sync_channel_end;
  const end =
    endRaw === null || endRaw === undefined || endRaw === ''
      ? start
      : Number(endRaw);
  return { start, end, startRaw };
};

export const abortTimers = (timerRef, abortRef) => {
  Object.values(timerRef.current).forEach((t) => clearTimeout(t));
  timerRef.current = {};
  Object.values(abortRef.current).forEach((c) => {
    try {
      c.abort();
    } catch {
      // ignore
    }
  });
  abortRef.current = {};
};

export const getRegexOptions = (
  findValue,
  replaceValue,
  filterValue,
  excludeValue
) => {
  return {
    find: findValue,
    replace: replaceValue,
    match: filterValue,
    exclude: excludeValue,
  };
};

export const computeAutoSyncStart = (prev, id) => {
  let proposedStart = 1;
  for (const other of prev) {
    if (other.channel_group == id) continue;
    if (!other.enabled || !other.auto_channel_sync) continue;
    const otherMode =
      other.custom_properties?.channel_numbering_mode || 'fixed';
    if (otherMode === 'next_available') continue;
    const otherStart = Number(
      otherMode === 'provider'
        ? (other.custom_properties?.channel_numbering_fallback ?? 1)
        : (other.auto_sync_channel_start ?? 1)
    );
    if (!Number.isFinite(otherStart)) continue;
    const otherEnd =
      other.auto_sync_channel_end === null ||
      other.auto_sync_channel_end === undefined ||
      other.auto_sync_channel_end === ''
        ? otherStart
        : Number(other.auto_sync_channel_end);
    const upper = Math.max(otherStart, otherEnd);
    if (upper + 1 > proposedStart) proposedStart = upper + 1;
  }
  return proposedStart;
};

export const isGroupVisible = (group, groupFilter, statusFilter) => {
  const matchesText = group.name
    .toLowerCase()
    .includes(groupFilter.toLowerCase());
  const matchesStatus =
    statusFilter === 'all' ||
    (statusFilter === 'enabled' && group.enabled) ||
    (statusFilter === 'disabled' && !group.enabled);
  return matchesText && matchesStatus;
};
