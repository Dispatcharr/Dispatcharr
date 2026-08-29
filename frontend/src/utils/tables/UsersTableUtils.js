import { USER_LEVEL_LABELS } from '../../constants';

// The Name column has no backing model field — it is rendered from first_name
// and last_name. Sorting and searching both go through this helper so the
// column, the sort order, and the search all agree on what "name" means.
export const getUserFullName = (user) =>
  `${user.first_name || ''} ${user.last_name || ''}`.trim();

// Value a column is compared on when sorting. Only the columns that need
// something other than the raw field are listed; everything else falls through
// to user[column].
const getSortValue = (user, column) => {
  switch (column) {
    case 'name':
      return getUserFullName(user);
    // user_level is stored as a number (0 Streamer / 1 Standard / 10 Admin), so
    // comparing the raw value orders by privilege rather than alphabetically by
    // label, which is the ordering that is actually useful here.
    default:
      return user[column];
  }
};

export const getSortedUsers = (users, compareColumn, compareDesc) => {
  // Copy first: `users` is the array held in the Zustand store and sort()
  // mutates in place.
  return [...users].sort((a, b) => {
    const aVal = getSortValue(a, compareColumn);
    const bVal = getSortValue(b, compareColumn);

    // Users with no value (never logged in, blank name) always sort last,
    // whichever direction the column is sorted in.
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

// Fields the search box matches against. The XC password is deliberately
// excluded — it is masked in the table and matching it would let someone
// confirm a password without revealing it.
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
