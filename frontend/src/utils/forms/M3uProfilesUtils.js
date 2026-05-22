export const parseExpirationDate = (profile) => {
  const expDate = profile?.custom_properties?.user_info?.exp_date;
  if (!expDate) return null;
  try {
    return new Date(parseInt(expDate) * 1000);
  } catch {
    return null;
  }
};

export const isAccountExpired = (profile) => {
  const expDate = parseExpirationDate(profile);
  if (!expDate) return false;
  return expDate < new Date();
};

export const getExpirationInfo = (profile) => {
  const expDate = parseExpirationDate(profile);
  if (!expDate) return null;

  const diffMs = expDate - new Date();
  if (diffMs <= 0) return { text: 'Expired', color: 'red' };

  const days = Math.floor(diffMs / (1000 * 60 * 60 * 24));
  if (days > 30) return { text: `${days} days`, color: 'green' };
  if (days > 7) return { text: `${days} days`, color: 'yellow' };
  if (days > 0) return { text: `${days} days`, color: 'orange' };

  const hours = Math.floor(diffMs / (1000 * 60 * 60));
  return { text: `${hours}h`, color: 'red' };
};

export const profileSortComparator = (a, b) => {
  if (a.is_default) return -1;
  if (b.is_default) return 1;
  return a.name.localeCompare(b.name);
};
