import { USER_LEVELS } from '../constants';

/**
 * Read a VOD access flag. Admins always allowed. Streamers never.
 * Standard users: absent flag defaults to true (explicit false disables).
 */
const isVodFlagEnabled = (user, flag) => {
  if (!user) return false;
  if (user.user_level >= USER_LEVELS.ADMIN) return true;
  if (user.user_level < USER_LEVELS.STANDARD) return false;
  return (user.custom_properties || {})[flag] !== false;
};

/** Whether movies VOD is allowed for a user. */
export const isVodMoviesEnabled = (user) =>
  isVodFlagEnabled(user, 'vod_movies_enabled');

/** Whether series VOD is allowed for a user. */
export const isVodSeriesEnabled = (user) =>
  isVodFlagEnabled(user, 'vod_series_enabled');

/**
 * Whether the user may open the VODs page and see the VODs nav item.
 */
export const canViewVod = (user) =>
  isVodMoviesEnabled(user) || isVodSeriesEnabled(user);
