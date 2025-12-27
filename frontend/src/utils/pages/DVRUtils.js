// Deduplicate in-progress and upcoming by program id or channel+slot
const dedupeByProgramOrSlot = (arr) => {
  const out = [];
  const sigs = new Set();

  for (const r of arr) {
    const cp = r.custom_properties || {};
    const pr = cp.program || {};
    const sig =
      pr?.id != null
        ? `id:${pr.id}`
        : `slot:${r.channel}|${r.start_time}|${r.end_time}|${pr.title || ''}`;

    if (sigs.has(sig)) continue;
    sigs.add(sig);
    out.push(r);
  }
  return out;
};

const dedupeById = (list, toUserTime, completed, now, inProgress, upcoming) => {
  // ID-based dedupe guard in case store returns duplicates
  const seenIds = new Set();
  for (const rec of list) {
    if (rec && rec.id != null) {
      const k = String(rec.id);
      if (seenIds.has(k)) continue;
      seenIds.add(k);
    }

    const s = toUserTime(rec.start_time);
    const e = toUserTime(rec.end_time);
    const status = rec.custom_properties?.status;

    if (status === 'interrupted' || status === 'completed') {
      completed.push(rec);
    } else {
      if (now.isAfter(s) && now.isBefore(e)) inProgress.push(rec);
      else if (now.isBefore(s)) upcoming.push(rec);
      else completed.push(rec);
    }
  }
}

export const categorizeRecordings = (recordings, toUserTime, now) => {
  const inProgress = [];
  const upcoming = [];
  const completed = [];
  const list = Array.isArray(recordings)
    ? recordings
    : Object.values(recordings || {});

  dedupeById(list, toUserTime, completed, now, inProgress, upcoming);

  const inProgressDedup = dedupeByProgramOrSlot(inProgress).sort(
    (a, b) => toUserTime(b.start_time) - toUserTime(a.start_time)
  );

  // Group upcoming by series title+tvg_id (keep only next episode)
  const upcomingDedup = dedupeByProgramOrSlot(upcoming).sort(
    (a, b) => toUserTime(a.start_time) - toUserTime(b.start_time)
  );
  const grouped = new Map();

  for (const rec of upcomingDedup) {
    const cp = rec.custom_properties || {};
    const prog = cp.program || {};
    const key = `${prog.tvg_id || ''}|${(prog.title || '').toLowerCase()}`;
    if (!grouped.has(key)) {
      grouped.set(key, { rec, count: 1 });
    } else {
      const entry = grouped.get(key);
      entry.count += 1;
    }
  }

  const upcomingGrouped = Array.from(grouped.values()).map((e) => {
    const item = { ...e.rec };
    item._group_count = e.count;
    return item;
  });

  completed.sort((a, b) => toUserTime(b.end_time) - toUserTime(a.end_time));

  return {
    inProgress: inProgressDedup,
    upcoming: upcomingGrouped,
    completed,
  };
}