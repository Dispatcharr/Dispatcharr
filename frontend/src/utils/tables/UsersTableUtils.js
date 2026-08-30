import { USER_LEVEL_LABELS } from '../../constants';

// Shared by the Name cell, sort, and search so they cannot disagree on what
// "name" means (there is no backing model field).
export const getUserFullName = (user) =>
  `${user.first_name || ''} ${user.last_name || ''}`.trim();

const getSortValue = (user, column) => {
  switch (column) {
    case 'name':
      return getUserFullName(user);
    default:
      // user_level stays numeric so sort order is by privilege, not label.
      return user[column];
  }
};

export const getSortedUsers = (users, compareColumn, compareDesc) => {
  // Copy first: `users` is the Zustand store array and sort() mutates in place.
  return [...users].sort((a, b) => {
    const aVal = getSortValue(a, compareColumn);
    const bVal = getSortValue(b, compareColumn);

    // Empty values (never logged in, blank name) sort last in both directions.
    const aEmpty = aVal == null || aVal === '';
    const bEmpty = bVal == null || bVal === '';
    if (aEmpty && bEmpty) return 0;
    if (aEmpty) return 1;
    if (bEmpty) return -1;

    const comparison =
      typeof aVal === 'string'
        ? aVal.localeCompare(bVal, undefined, { sensitivity: 'base' })
        : aVal < bVal
          ? -1
          : aVal > bVal
            ? 1
            : 0;

    return compareDesc ? -comparison : comparison;
  });
};

// XC password deliberately omitted: the column masks it, and matching would
// let someone confirm a password without revealing it.
const getSearchableText = (user) =>
  [
    user.username,
    getUserFullName(user),
    user.email,
    USER_LEVEL_LABELS[user.user_level],
  ]
    .filter(Boolean)
    .join(' ')
    .toLowerCase();

export const getFilteredUsers = (users, search) => {
  const query = (search || '').trim().toLowerCase();
  if (!query) return users;

  return users.filter((user) => getSearchableText(user).includes(query));
};
