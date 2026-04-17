/**
 * Compare two semver-like version strings.
 * Returns negative if a < b, 0 if equal, positive if a > b.
 *
 * If either version is a prerelease (any dot-segment contains non-digit
 * characters), numeric ordering is meaningless. Fall back to exact string
 * equality: 0 if identical, non-zero otherwise.
 */
export function compareVersions(a, b) {
  if (!a || !b) return 0;
  const normalize = (v) => v.replace(/^v/, '');
  const na = normalize(a);
  const nb = normalize(b);
  const isPrerelease = (v) => v.split('.').some((p) => !/^\d+$/.test(p));
  if (isPrerelease(na) || isPrerelease(nb)) {
    return na === nb ? 0 : 1;
  }
  const pa = na.split('.').map(Number);
  const pb = nb.split('.').map(Number);
  for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
    const diff = (pa[i] || 0) - (pb[i] || 0);
    if (diff !== 0) return diff;
  }
  return 0;
}
