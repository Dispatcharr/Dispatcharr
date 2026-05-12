// Returns {name, start, end}[] for groups whose declared ranges
// intersect this group's range, or [] when there is no overlap.
import { getGroupReservation } from './GroupSyncUtils.js';

export const computeRangeOverlapsFor = (group, groupStates) => {
  const myReservation = getGroupReservation(group);
  if (!myReservation) return [];
  const [myStart, myEnd] = myReservation;
  const overlaps = [];
  for (const other of groupStates) {
    if (other.channel_group === group.channel_group) continue;
    const otherReservation = getGroupReservation(other);
    if (!otherReservation) continue;
    const [oStart, oEnd] = otherReservation;
    if (myStart <= oEnd && oStart <= myEnd) {
      overlaps.push({ name: other.name, start: oStart, end: oEnd });
    }
  }
  return overlaps;
};

const MAX_CHANNEL_NUMBER = 999999;

export const clampChannelNumber = (n) =>
  Math.max(1, Math.min(MAX_CHANNEL_NUMBER, Math.floor(Number(n) || 1)));
