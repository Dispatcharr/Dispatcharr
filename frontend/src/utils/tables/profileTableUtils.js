const nameCollator = new Intl.Collator(undefined, { sensitivity: 'base' });

// Locked (seeded/default) profiles first, then by name. Names are not unique
// and the API returns profiles in no guaranteed order, so id breaks ties to
// keep the row order stable across refreshes.
export const sortLockedFirstByName = (items) =>
  [...items].sort((a, b) => {
    if (Boolean(a.locked) !== Boolean(b.locked)) {
      return a.locked ? -1 : 1;
    }
    const byName = nameCollator.compare(a.name || '', b.name || '');
    if (byName !== 0) return byName;
    return (a.id ?? 0) - (b.id ?? 0);
  });
