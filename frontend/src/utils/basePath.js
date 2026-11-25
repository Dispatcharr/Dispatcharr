/**
 * The path the UI is served under, without a trailing slash: '' at the site
 * root, '/media/dispatcharr' for a build made with
 * `npm run build -- --base=/media/dispatcharr/`. Vite sets
 * `import.meta.env.BASE_URL` from the build's `base` option ('/' by default),
 * so for a root deployment every helper here returns its input unchanged.
 */
export const getBasePath = () =>
  (import.meta.env.BASE_URL || '/').replace(/\/+$/, '');

/**
 * Prefixes a root-relative path ('/api/...', '/proxy/...') with the base
 * path. Absolute URLs, protocol-relative URLs ('//host/...') and relative
 * paths are returned as they are.
 */
export const withBasePath = (path) => {
  if (
    typeof path !== 'string' ||
    !path.startsWith('/') ||
    path.startsWith('//')
  ) {
    return path;
  }
  return `${getBasePath()}${path}`;
};
