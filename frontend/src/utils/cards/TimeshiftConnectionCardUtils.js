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
}) => {
  let elapsedSinceAnchor = 0;
  if (!paused && positionAnchorAt != null) {
    const anchor = Number(positionAnchorAt);
    if (!Number.isNaN(anchor)) {
      elapsedSinceAnchor = Math.max(0, nowMs / 1000 - anchor);
    }
  }

  if (playbackBaseSecs != null && !Number.isNaN(Number(playbackBaseSecs))) {
    let position = Number(playbackBaseSecs) + elapsedSinceAnchor;
    if (position < 0) {
      position = 0;
    }
    if (programDurationSecs != null) {
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
  if (position < 0) {
    position = 0;
  }
  if (programDurationSecs != null) {
    position = Math.min(position, Number(programDurationSecs));
  }
  return position;
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
