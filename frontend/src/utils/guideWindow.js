/**
 * Pure helpers for TV Guide incremental EPG time windows.
 *
 * Initial load: now − 1h → now + 24h. Further browsing warm-prefetches
 * 12h chunks. Soft cull keeps ~36h around the viewport while on the page.
 */

import { PX_PER_MS } from './guideUtils.js';

export const MS_PER_HOUR = 60 * 60 * 1000;
export const INITIAL_LOOKBACK_MS = 1 * MS_PER_HOUR;
export const INITIAL_FORWARD_MS = 24 * MS_PER_HOUR;
export const CHUNK_MS = 12 * MS_PER_HOUR;
/** Soft keep window while staying on the Guide page (~three 12h chunks). */
export const KEEP_MS = 36 * MS_PER_HOUR;
/** Prefetch when the viewport edge is within this distance of the loaded edge. */
export const PREFETCH_MARGIN_MS = CHUNK_MS / 2;

/**
 * @param {number} nowMs
 * @returns {{ startMs: number, endMs: number }}
 */
export function getInitialWindow(nowMs) {
  return {
    startMs: nowMs - INITIAL_LOOKBACK_MS,
    endMs: nowMs + INITIAL_FORWARD_MS,
  };
}

/**
 * @param {number} ms
 * @returns {string} ISO 8601 UTC datetime for grid start/end query params
 */
export function toIsoParam(ms) {
  return new Date(ms).toISOString();
}

/**
 * @param {URLSearchParams} params
 * @param {number} startMs
 * @param {number} endMs
 * @returns {URLSearchParams}
 */
export function appendWindowParams(params, startMs, endMs) {
  params.set('start', toIsoParam(startMs));
  params.set('end', toIsoParam(endMs));
  return params;
}

/**
 * @param {number} loadedEndMs
 * @returns {{ startMs: number, endMs: number }}
 */
export function nextChunkForward(loadedEndMs) {
  return {
    startMs: loadedEndMs,
    endMs: loadedEndMs + CHUNK_MS,
  };
}

/**
 * @param {number} loadedStartMs
 * @returns {{ startMs: number, endMs: number }}
 */
export function nextChunkBackward(loadedStartMs) {
  return {
    startMs: loadedStartMs - CHUNK_MS,
    endMs: loadedStartMs,
  };
}

/**
 * @param {number} viewportEndMs
 * @param {number} loadedEndMs
 */
export function shouldPrefetchForward(viewportEndMs, loadedEndMs) {
  return viewportEndMs >= loadedEndMs - PREFETCH_MARGIN_MS;
}

/**
 * @param {number} viewportStartMs
 * @param {number} loadedStartMs
 * @param {number} [scrollLeft=0] timeline scrollLeft in px; backward warm-ahead
 *   only when the user is actually at the left edge (avoids always prefetching
 *   on open when lookback is only 1h but the margin is 6h).
 * @param {number} [edgePx=48]
 */
export function shouldPrefetchBackward(
  viewportStartMs,
  loadedStartMs,
  scrollLeft = 0,
  edgePx = 48
) {
  if (scrollLeft > edgePx) {
    return false;
  }
  return viewportStartMs <= loadedStartMs + PREFETCH_MARGIN_MS;
}

/**
 * Map scroll + timeline origin to the visible time range.
 *
 * @param {number} timelineStartMs
 * @param {number} scrollLeft
 * @param {number} viewportWidthPx
 * @param {number} [pxPerMs=PX_PER_MS]
 * @returns {{ startMs: number, endMs: number, centerMs: number }}
 */
export function viewportTimeRange(
  timelineStartMs,
  scrollLeft,
  viewportWidthPx,
  pxPerMs = PX_PER_MS
) {
  const startMs = timelineStartMs + scrollLeft / pxPerMs;
  const widthMs = Math.max(0, viewportWidthPx) / pxPerMs;
  const endMs = startMs + widthMs;
  return {
    startMs,
    endMs,
    centerMs: startMs + widthMs / 2,
  };
}

/**
 * Merge incoming programs into existing by id. Incoming wins on conflict.
 *
 * @param {Array<{ id?: string|number }>} existing
 * @param {Array<{ id?: string|number }>} incoming
 * @returns {Array}
 */
export function mergeProgramsById(existing, incoming) {
  if (!incoming?.length) {
    return existing || [];
  }
  if (!existing?.length) {
    return [...incoming];
  }
  const map = new Map();
  for (const program of existing) {
    if (program?.id != null) {
      map.set(String(program.id), program);
    }
  }
  for (const program of incoming) {
    if (program?.id != null) {
      map.set(String(program.id), program);
    }
  }
  return Array.from(map.values());
}

/**
 * ScrollLeft delta so the viewport stays on the same absolute time when the
 * timeline origin (`startMs`) moves. Positive when the range grows left;
 * negative when the left bound is culled forward.
 *
 * @param {number} oldStartMs
 * @param {number} newStartMs
 * @param {number} [pxPerMs=PX_PER_MS]
 */
export function timelineOriginScrollDeltaPx(
  oldStartMs,
  newStartMs,
  pxPerMs = PX_PER_MS
) {
  return (oldStartMs - newStartMs) * pxPerMs;
}

/**
 * Drop programs entirely outside a keep window centered on the viewport.
 * Returns the filtered list and the tight loaded range covering survivors
 * (at least the keep window clipped to the previous loaded span).
 *
 * @param {Array<{ startMs?: number, endMs?: number, start_time?: string, end_time?: string }>} programs
 * @param {number} viewportCenterMs
 * @param {number} keepMs
 * @param {number} loadedStartMs
 * @param {number} loadedEndMs
 * @param {(value: unknown) => number} toMs
 * @returns {{ programs: Array, rangeStartMs: number, rangeEndMs: number, culled: boolean }}
 */
export function cullProgramsToKeepWindow(
  programs,
  viewportCenterMs,
  keepMs,
  loadedStartMs,
  loadedEndMs,
  toMs
) {
  const span = loadedEndMs - loadedStartMs;
  if (!(span > keepMs) || !programs?.length) {
    return {
      programs: programs || [],
      rangeStartMs: loadedStartMs,
      rangeEndMs: loadedEndMs,
      culled: false,
    };
  }

  const half = keepMs / 2;
  let keepStart = viewportCenterMs - half;
  let keepEnd = viewportCenterMs + half;

  // Prefer sliding within the loaded span; clamp to edges when near ends.
  if (keepStart < loadedStartMs) {
    keepStart = loadedStartMs;
    keepEnd = loadedStartMs + keepMs;
  } else if (keepEnd > loadedEndMs) {
    keepEnd = loadedEndMs;
    keepStart = loadedEndMs - keepMs;
  }

  const kept = [];
  for (const program of programs) {
    const pStart =
      program.startMs != null ? program.startMs : toMs(program.start_time);
    const pEnd =
      program.endMs != null ? program.endMs : toMs(program.end_time);
    // Keep if it overlaps the keep window (not entirely outside).
    if (pEnd > keepStart && pStart < keepEnd) {
      kept.push(program);
    }
  }

  return {
    programs: kept,
    rangeStartMs: keepStart,
    rangeEndMs: keepEnd,
    culled: kept.length !== programs.length || keepStart !== loadedStartMs || keepEnd !== loadedEndMs,
  };
}
