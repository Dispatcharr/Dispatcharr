import { format, getNowMs, toFriendlyDuration } from '../dateTimeUtils.js';

/** Parse a catch-up URL timestamp (UTC wall clock) into epoch ms. */
export const parseCatchupTimestampMs = (timestampStr) => {
  if (!timestampStr) {
    return null;
  }
  const match = String(timestampStr).match(
    /^(\d{4}-\d{2}-\d{2})[:_ ](\d{2})[-:](\d{2})/
  );
  if (!match) {
    return null;
  }
  const [, datePart, hour, minute] = match;
  const parsed = Date.parse(`${datePart}T${hour}:${minute}:00Z`);
  return Number.isNaN(parsed) ? null : parsed;
};

/** Best-effort play position within the programme (seconds). */
export const computeCatchupPlaybackSeconds = ({
  programmeStart,
  programStartTime,
  programDurationSecs,
  positionAnchorAt,
  playbackBaseSecs,
  paused = false,
  nowMs = getNowMs(),
  capToDuration = true,
  allowNegative = false,
}) => {
  let elapsedSinceAnchor = 0;
  if (!paused && positionAnchorAt != null) {
    const anchor = Number(positionAnchorAt);
    if (!Number.isNaN(anchor)) {
      elapsedSinceAnchor = Math.max(0, nowMs / 1000 - anchor);
    }
  }

  // Byte-range / client-reported bases are relative to the programme that
  // contained the original catch-up URL. When the stats card has advanced to a
  // later guide entry, rebase onto that programme's start.
  let effectiveBase = playbackBaseSecs;
  if (effectiveBase != null && !Number.isNaN(Number(effectiveBase))) {
    const urlMs = parseCatchupTimestampMs(programmeStart);
    const epgStartMs = programStartTime ? Date.parse(programStartTime) : null;
    if (
      urlMs != null &&
      epgStartMs != null &&
      !Number.isNaN(epgStartMs) &&
      epgStartMs > urlMs
    ) {
      effectiveBase = Number(effectiveBase) - (epgStartMs - urlMs) / 1000;
    }
    let position = Number(effectiveBase) + elapsedSinceAnchor;
    if (!allowNegative && position < 0) {
      position = 0;
    }
    if (capToDuration && programDurationSecs != null) {
      position = Math.min(position, Number(programDurationSecs));
    }
    return position;
  }

  const urlMs = parseCatchupTimestampMs(programmeStart);
  const epgStartMs = programStartTime ? Date.parse(programStartTime) : null;
  if (urlMs == null || epgStartMs == null || Number.isNaN(epgStartMs)) {
    return null;
  }
  const urlOffsetSec = (urlMs - epgStartMs) / 1000;
  let position = urlOffsetSec + elapsedSinceAnchor;
  if (!allowNegative && position < 0) {
    position = 0;
  }
  if (capToDuration && programDurationSecs != null) {
    position = Math.min(position, Number(programDurationSecs));
  }
  return position;
};

/**
 * True when the catch-up playhead is outside the displayed programme window.
 * Used to fetch the next guide entry once, then cache until that show ends.
 */
export const isCatchupPlayheadOutsideProgram = ({
  programmeStart,
  programStartTime,
  programDurationSecs,
  positionAnchorAt,
  playbackBaseSecs,
  paused = false,
  nowMs = getNowMs(),
}) => {
  if (programDurationSecs == null || !programStartTime) {
    return true;
  }
  const position = computeCatchupPlaybackSeconds({
    programmeStart,
    programStartTime,
    programDurationSecs,
    positionAnchorAt,
    playbackBaseSecs,
    paused,
    nowMs,
    capToDuration: false,
    allowNegative: true,
  });
  if (position == null) {
    return false;
  }
  return position < 0 || position >= Number(programDurationSecs);
};

/**
 * Archive playhead relative to the programme containing ``programmeStart``.
 * Uncapped so callers can detect when viewing has moved past that show.
 * Does not rebase onto a later displayed programme.
 */
export const computeCatchupArchivePositionSecs = ({
  programmeStart,
  programStartTime,
  positionAnchorAt,
  playbackBaseSecs,
  paused = false,
  nowMs = getNowMs(),
}) => {
  let elapsedSinceAnchor = 0;
  if (!paused && positionAnchorAt != null) {
    const anchor = Number(positionAnchorAt);
    if (!Number.isNaN(anchor)) {
      elapsedSinceAnchor = Math.max(0, nowMs / 1000 - anchor);
    }
  }

  // playback_base is always relative to the URL programme, even after the
  // stats card has advanced to a later guide entry.
  if (playbackBaseSecs != null && !Number.isNaN(Number(playbackBaseSecs))) {
    return Math.max(0, Number(playbackBaseSecs) + elapsedSinceAnchor);
  }

  const urlMs = parseCatchupTimestampMs(programmeStart);
  const epgStartMs = programStartTime ? Date.parse(programStartTime) : null;
  if (urlMs == null || epgStartMs == null || Number.isNaN(epgStartMs)) {
    return null;
  }
  // Only valid while programStartTime is the programme that contains the URL.
  // Once the card has advanced, omit position and let the API use Redis.
  if (epgStartMs > urlMs) {
    return null;
  }
  return Math.max(0, (urlMs - epgStartMs) / 1000 + elapsedSinceAnchor);
};

export const calculateConnectionDuration = (connection) => {
  const seconds = getConnectionDurationSeconds(connection);
  return toFriendlyDuration(seconds, 'seconds');
};

export const getConnectionDurationSeconds = (connection) => {
  if (!connection) {
    return 0;
  }
  if (connection.duration && connection.duration > 0) {
    return connection.duration;
  }
  if (connection.connected_at) {
    return Math.max(0, Math.floor(getNowMs() / 1000 - connection.connected_at));
  }
  return 0;
};

export const calculateConnectionStartTime = (connection, fullDateTimeFormat) => {
  if (!connection?.connected_at) {
    return 'Unknown';
  }
  return format(new Date(connection.connected_at * 1000), fullDateTimeFormat);
};
