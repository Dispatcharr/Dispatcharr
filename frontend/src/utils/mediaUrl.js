export const resolveMediaUrl = (value) => {
  const url = typeof value === 'string' ? value.trim() : '';
  if (!url) {
    return '';
  }

  if (/^https?:\/\//i.test(url)) {
    return url;
  }

  if (
    typeof import.meta !== 'undefined' &&
    import.meta.env &&
    import.meta.env.DEV &&
    url.startsWith('/')
  ) {
    return `${window.location.protocol}//${window.location.hostname}:5656${url}`;
  }

  return url;
};

export const resolveLogoUrl = (logo) => {
  if (!logo || typeof logo !== 'object') {
    return logo;
  }

  const preferred = logo.cache_url || logo.url;

  return {
    ...logo,
    url: resolveMediaUrl(preferred),
    cache_url: resolveMediaUrl(logo.cache_url),
  };
};
