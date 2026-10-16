import { USER_LEVELS } from '../constants';

/** Stored in custom_properties.dvr_access */
export const DVR_ACCESS = {
  NONE: 'none',
  VIEW: 'view',
  MANAGE: 'manage',
};

/**
 * Resolve the DVR access level for a user.
 * Admins → manage. Streamers → none. Standard users read
 * custom_properties.dvr_access (absent defaults to view).
 */
export const getDvrAccess = (user) => {
  if (!user) return DVR_ACCESS.NONE;
  if (user.user_level >= USER_LEVELS.ADMIN) return DVR_ACCESS.MANAGE;
  if (user.user_level < USER_LEVELS.STANDARD) return DVR_ACCESS.NONE;
  const raw = (user.custom_properties || {}).dvr_access;
  if (
    raw === DVR_ACCESS.NONE ||
    raw === DVR_ACCESS.VIEW ||
    raw === DVR_ACCESS.MANAGE
  ) {
    return raw;
  }
  return DVR_ACCESS.VIEW;
};

/**
 * Whether the user may manage DVR (create/delete/rules), same as admin for
 * DVR endpoints.
 */
export const canManageDvr = (user) => getDvrAccess(user) === DVR_ACCESS.MANAGE;

/**
 * Whether the user may list/play DVR recordings and see the DVR nav item.
 */
export const canViewDvr = (user) => getDvrAccess(user) !== DVR_ACCESS.NONE;
