/**
 * Centralized URL utilities for SSR-safe URL generation
 * Handles both development and production environments
 * Works on both server (via Request) and client (via window)
 */

/**
 * Get the base URL from a Request object (server-side)
 */
function getBaseUrlFromRequest(request: Request): string {
  const url = new URL(request.url);
  const protocol = url.protocol;
  const host = url.host;

  if (!import.meta.env.PROD) {
    // Development: Use backend port
    return `${protocol}//${url.hostname}:5656`;
  }

  // Production: Use request host
  return `${protocol}//${host}`;
}

/**
 * Get the base URL from window (client-side)
 */
function getBaseUrlFromWindow(): string {
  if (typeof window === "undefined") return "";

  const protocol = window.location.protocol;
  const hostname = window.location.hostname;

  if (!import.meta.env.PROD) {
    // Development: Use backend port
    return `${protocol}//${hostname}:5656`;
  }

  // Production: Use current host
  return `${protocol}//${window.location.host}`;
}

/**
 * Get the base URL (auto-detects client vs server)
 */
export function getBaseUrl(request?: Request): string {
  if (request) {
    return getBaseUrlFromRequest(request);
  }
  return getBaseUrlFromWindow();
}

/**
 * Get the M3U output URL base
 */
export function getM3uUrlBase(request?: Request): string {
  const base = getBaseUrl(request);
  return base ? `${base}/output/m3u` : "";
}

/**
 * Get the EPG output URL base
 */
export function getEpgUrlBase(request?: Request): string {
  const base = getBaseUrl(request);
  return base ? `${base}/output/epg` : "";
}

/**
 * Get the HDHR URL base
 */
export function getHdhrUrlBase(request?: Request): string {
  const base = getBaseUrl(request);
  return base ? `${base}/hdhr` : "";
}

/**
 * Get the current protocol (http: or https:)
 */
export function getProtocol(request?: Request): string {
  if (request) {
    const url = new URL(request.url);
    return url.protocol;
  }
  if (typeof window === "undefined") return "";
  return window.location.protocol;
}

/**
 * Get the current host (hostname:port)
 */
export function getHost(request?: Request): string {
  if (request) {
    const url = new URL(request.url);
    return url.host;
  }
  if (typeof window === "undefined") return "";
  return window.location.host;
}

/**
 * Get the current hostname (without port)
 */
export function getHostname(request?: Request): string {
  if (request) {
    const url = new URL(request.url);
    return url.hostname;
  }
  if (typeof window === "undefined") return "";
  return window.location.hostname;
}

/**
 * Check if we're in production environment
 */
export function isProduction(): boolean {
  return !!import.meta.env.PROD;
}

/**
 * Check if we're in browser (client-side)
 */
export function isBrowser(): boolean {
  return typeof window !== "undefined";
}
