export const PLAYER_PREFS_KEY = 'dispatcharr-player-prefs';

export const getPlayerPrefs = () => {
  try {
    return JSON.parse(localStorage.getItem(PLAYER_PREFS_KEY) || '{}');
  } catch {
    return {};
  }
};

export const savePlayerPrefs = (updates) => {
  try {
    localStorage.setItem(
      PLAYER_PREFS_KEY,
      JSON.stringify({ ...getPlayerPrefs(), ...updates })
    );
  } catch {}
};

export const getLivePlayerErrorMessage = (errorType, errorDetail) => {
  if (errorType !== 'MediaError') {
    return errorDetail
      ? `Error: ${errorType} - ${errorDetail}`
      : `Error: ${errorType}`;
  }

  const errorString = errorDetail?.toLowerCase() || '';

  if (
    errorString.includes('audio') ||
    errorString.includes('ac3') ||
    errorString.includes('ac-3')
  ) {
    return 'Audio codec not supported by your browser. Try Chrome or Edge for better audio codec support.';
  }

  if (
    errorString.includes('video') ||
    errorString.includes('h264') ||
    errorString.includes('h.264')
  ) {
    return 'Video codec not supported by your browser. Try Chrome or Edge for better video codec support.';
  }

  if (errorString.includes('mse')) {
    return "Your browser doesn't support the codecs used in this stream. Try Chrome or Edge for better compatibility.";
  }

  return 'Media codec not supported by your browser. This may be due to unsupported audio (AC3) or video codecs. Try Chrome or Edge.';
};

export const getVODPlayerErrorMessage = (error) => {
  if (!error) return 'Video playback error';

  switch (error.code) {
    case error.MEDIA_ERR_ABORTED:
      return 'Video playback was aborted';
    case error.MEDIA_ERR_NETWORK:
      return 'Network error while loading video';
    case error.MEDIA_ERR_DECODE:
      return 'Video codec not supported by your browser';
    case error.MEDIA_ERR_SRC_NOT_SUPPORTED:
      return 'Video format not supported by your browser';
    default:
      return error.message || 'Unknown video error';
  }
};

export const getClientCoordinates = (event) => ({
  clientX: event.touches?.[0]?.clientX ?? event.clientX,
  clientY: event.touches?.[0]?.clientY ?? event.clientY,
});

export const calculateNewDimensions = (
  deltaX,
  deltaY,
  startWidth,
  startHeight,
  handle,
  ratio
) => {
  const widthDelta = deltaX * handle.xDir;
  const heightDelta = deltaY * handle.yDir;

  let width = startWidth + widthDelta;
  let height = width / ratio;

  // Use vertical-driven resize if user drags mostly vertically
  if (Math.abs(deltaY) > Math.abs(deltaX)) {
    height = startHeight + heightDelta;
    width = height * ratio;
  }

  return { width, height };
};

export const applyConstraints = (
  width,
  height,
  ratio,
  startPos,
  handle,
  minWidth,
  minHeight,
  visibleMargin
) => {
  // Apply minimum constraints
  if (width < minWidth) {
    width = minWidth;
    height = width / ratio;
  }
  if (height < minHeight) {
    height = minHeight;
    width = height * ratio;
  }

  // Apply viewport constraints
  const posX = startPos?.x ?? 0;
  const posY = startPos?.y ?? 0;
  // Absolute caps ensure the player can never exceed the viewport even when
  // its position is negative (partially off-screen on the opposite edge).
  const maxWidth = !handle.isLeft
    ? Math.min(
        window.innerWidth - visibleMargin,
        Math.max(minWidth, window.innerWidth - posX - visibleMargin)
      )
    : null;
  const maxHeight = !handle.isTop
    ? Math.min(
        window.innerHeight - visibleMargin,
        Math.max(minHeight, window.innerHeight - posY - visibleMargin)
      )
    : null;

  if (maxWidth && width > maxWidth) {
    width = maxWidth;
    height = width / ratio;
  }
  if (maxHeight && height > maxHeight) {
    height = maxHeight;
    width = height * ratio;
  }

  // Final adjustment to maintain aspect ratio
  if (maxWidth && width > maxWidth) {
    width = maxWidth;
    height = width / ratio;
  }

  return { width, height };
};
