/**
 * Whether `url` is a plain http(s) URL, used before rendering an anchor
 * `href` sourced from third-party data (e.g. a plugin manifest) we don't
 * control, so a malicious manifest can't smuggle a `javascript:`/`data:`
 * URI into a clickable link.
 */
export const isSafeHttpUrl = (url) => typeof url === 'string' && /^https?:\/\//i.test(url);
