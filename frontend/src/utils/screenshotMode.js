export const HIDDEN_VALUE = '••••••••';

export const redactUrls = (value) =>
  value.replace(/\b[a-z][a-z0-9+.-]*:\/\/[^\s<>"']+/gi, HIDDEN_VALUE);
