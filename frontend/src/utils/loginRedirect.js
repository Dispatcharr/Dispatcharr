export const defaultRoute = '/channels';

export const getSafeNextPath = (path) => {
  if (
    !path ||
    !path.startsWith('/') ||
    path.startsWith('//') ||
    path.startsWith('/\\') ||
    path.includes('://') ||
    path === '/login' ||
    path.startsWith('/login?') ||
    path.startsWith('/login/')
  ) {
    return null;
  }
  return path;
};
