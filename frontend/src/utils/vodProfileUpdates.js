export const VOD_PROFILE_REBUILD_EVENT =
  'dispatcharr:vod-profile-rebuild-required';

export const showVODProfileRebuildNotice = (response = {}) => {
  if (
    typeof window === 'undefined' ||
    response?.profile_update !== 'outdated' ||
    Number(response?.profiles_affected || 0) < 1
  ) {
    return;
  }
  window.dispatchEvent(
    new CustomEvent(VOD_PROFILE_REBUILD_EVENT, {
      detail: { profilesAffected: Number(response.profiles_affected) },
    })
  );
};
