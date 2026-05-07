// Utilities for per-group auto-sync configuration in LiveGroupFilter /
// M3UGroupFilter. Range reservations (groups with both start and end set
// on Fixed or Provider numbering) claim channel numbers exclusively, so
// overlapping reservations across groups would produce conflicts during
// sync. Validation runs client-side at save-time to block obvious
// misconfigurations before the request is sent; the backend enforces
// the same rule across accounts as a safety net.

const MODE_WITHOUT_RANGE = 'next_available';

// Returns null if the group does not participate in reservations (disabled,
// not auto-syncing, unbounded, or in Next Available mode), otherwise a
// [start, end] pair of integers with start <= end.
export const getGroupReservation = (group) => {
  if (!group || !group.enabled || !group.auto_channel_sync) return null;
  const mode = group.custom_properties?.channel_numbering_mode || 'fixed';
  if (mode === MODE_WITHOUT_RANGE) return null;
  const endRaw = group.auto_sync_channel_end;
  if (endRaw === null || endRaw === undefined || endRaw === '') return null;
  const startRaw =
    mode === 'provider'
      ? (group.custom_properties?.channel_numbering_fallback ?? 1)
      : (group.auto_sync_channel_start ?? 1);
  const start = Math.floor(Number(startRaw));
  const end = Math.floor(Number(endRaw));
  if (!Number.isFinite(start) || !Number.isFinite(end)) return null;
  if (end < start) return null;
  return [start, end];
};

// Given an array of groupStates from the M3U Group Filter modal, returns
// overlap records describing pairs of groups whose reservations intersect.
// Shape: [{ a: { channel_group, name, start, end }, b: {...} }, ...]
// Callers surface these as user-facing errors and block submit.
export const detectGroupReservationOverlaps = (groupStates) => {
  const reservations = [];
  for (const g of groupStates || []) {
    const range = getGroupReservation(g);
    if (!range) continue;
    reservations.push({
      channel_group: g.channel_group,
      name: g.name,
      start: range[0],
      end: range[1],
    });
  }
  const conflicts = [];
  for (let i = 0; i < reservations.length; i += 1) {
    for (let j = i + 1; j < reservations.length; j += 1) {
      const a = reservations[i];
      const b = reservations[j];
      if (a.start <= b.end && b.start <= a.end) {
        conflicts.push({ a, b });
      }
    }
  }
  return conflicts;
};

// Human-readable summary of an overlap list for a notification body.
export const formatOverlapMessage = (conflicts) => {
  if (!conflicts || conflicts.length === 0) return '';
  const lines = conflicts.slice(0, 5).map(({ a, b }) => {
    return `"${a.name}" [${a.start}-${a.end}] overlaps "${b.name}" [${b.start}-${b.end}]`;
  });
  if (conflicts.length > 5) {
    lines.push(`... and ${conflicts.length - 5} more.`);
  }
  return lines.join('\n');
};
