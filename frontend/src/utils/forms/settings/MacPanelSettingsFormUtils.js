export const getMacPanelSettingsDefaults = () => ({
  public_url: '',
});

export const getMacPanelSettingsFormInitialValues = () =>
  getMacPanelSettingsDefaults();

// A public_url is optional (the backend falls back to the admin's own
// request origin with a warning if unset) but must be a well-formed
// http(s) URL when provided — a trailing slash is fine, the backend strips
// it, but reject anything that isn't a URL at all.
const PUBLIC_URL_RE = /^https?:\/\/[^\s]+$/i;

export const getMacPanelSettingsFormValidation = () => ({
  public_url: (value) => {
    if (!value) return null;
    return PUBLIC_URL_RE.test(value)
      ? null
      : 'Must be a full URL starting with http:// or https://';
  },
});
