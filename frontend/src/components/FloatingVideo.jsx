// frontend/src/components/FloatingVideo.js
import React, { useCallback, useEffect, useRef, useState } from 'react';
import Draggable from 'react-draggable';
import useVideoStore from '../store/useVideoStore';
import useAuthStore from '../store/auth';
import mpegts from 'mpegts.js';
import { CloseButton, Flex, Loader, Text, Box } from '@mantine/core';
import {
  applyConstraints,
  calculateNewDimensions,
  getClientCoordinates,
  getLivePlayerErrorMessage,
  getVODPlayerErrorMessage,
  getPlayerPrefs,
  savePlayerPrefs,
} from '../utils/components/FloatingVideoUtils.js';

const ResizeHandles = ({ startResize }) => {
  const HANDLE_SIZE = 18;
  const HANDLE_OFFSET = 0;

  const resizeHandleBaseStyle = {
    position: 'absolute',
    width: HANDLE_SIZE,
    height: HANDLE_SIZE,
    backgroundColor: 'transparent',
    borderRadius: 6,
    zIndex: 8,
    touchAction: 'none',
  };

  const resizeHandles = [
    {
      id: 'bottom-right',
      cursor: 'nwse-resize',
      xDir: 1,
      yDir: 1,
      isLeft: false,
      isTop: false,
      style: {
        bottom: HANDLE_OFFSET,
        right: HANDLE_OFFSET,
        borderBottom: '2px solid rgba(255, 255, 255, 0.9)',
        borderRight: '2px solid rgba(255, 255, 255, 0.9)',
        borderRadius: '0 0 6px 0',
      },
    },
    {
      id: 'bottom-left',
      cursor: 'nesw-resize',
      xDir: -1,
      yDir: 1,
      isLeft: true,
      isTop: false,
      style: {
        bottom: HANDLE_OFFSET,
        left: HANDLE_OFFSET,
        borderBottom: '2px solid rgba(255, 255, 255, 0.9)',
        borderLeft: '2px solid rgba(255, 255, 255, 0.9)',
        borderRadius: '0 0 0 6px',
      },
    },
    {
      id: 'top-right',
      cursor: 'nesw-resize',
      xDir: 1,
      yDir: -1,
      isLeft: false,
      isTop: true,
      style: {
        top: HANDLE_OFFSET,
        right: HANDLE_OFFSET,
        borderTop: '2px solid rgba(255, 255, 255, 0.9)',
        borderRight: '2px solid rgba(255, 255, 255, 0.9)',
        borderRadius: '0 6px 0 0',
      },
    },
    {
      id: 'top-left',
      cursor: 'nwse-resize',
      xDir: -1,
      yDir: -1,
      isLeft: true,
      isTop: true,
      style: {
        top: HANDLE_OFFSET,
        left: HANDLE_OFFSET,
        borderTop: '2px solid rgba(255, 255, 255, 0.9)',
        borderLeft: '2px solid rgba(255, 255, 255, 0.9)',
        borderRadius: '6px 0 0 0',
      },
    },
  ];

  return (
    <>
      {/* Resize handles */}
      {resizeHandles.map((handle) => (
        <Box
          key={handle.id}
          className="floating-video-no-drag"
          onMouseDown={(event) => startResize(event, handle)}
          onTouchStart={(event) => startResize(event, handle)}
          style={{
            ...resizeHandleBaseStyle,
            ...handle.style,
            cursor: handle.cursor,
          }}
        />
      ))}
    </>
  );
};

export default function FloatingVideo() {
  const isVisible = useVideoStore((s) => s.isVisible);
  const streamUrl = useVideoStore((s) => s.streamUrl);
  const contentType = useVideoStore((s) => s.contentType);
  const metadata = useVideoStore((s) => s.metadata);
  const hideVideo = useVideoStore((s) => s.hideVideo);
  const accessToken = useAuthStore((s) => s.accessToken);

  const videoRef = useRef(null);
  const playerRef = useRef(null);
  const videoContainerRef = useRef(null);
  const resizeStateRef = useRef(null);
  const overlayTimeoutRef = useRef(null);
  const aspectRatioRef = useRef(320 / 180);
  const dragPositionRef = useRef(null);
  const dragOffsetRef = useRef({ x: 0, y: 0 });
  const initialPositionRef = useRef(null);
  // Ref kept in sync with videoSize state for use inside event handlers
  // where closures over state would be stale.
  const videoSizeRef = useRef(null);

  const [isLoading, setIsLoading] = useState(false);
  const [loadError, setLoadError] = useState(null);
  const [showOverlay, setShowOverlay] = useState(false);
  const [showControls, setShowControls] = useState(false);
  const [videoSize, setVideoSize] = useState(() => {
    const prefs = getPlayerPrefs();
    const saved = prefs.size;
    if (saved?.width >= 220 && saved?.height >= 124) {
      if (typeof window !== 'undefined') {
        // Cap to viewport minus a margin so the header is always reachable on
        // first render even if the saved size was set on a larger display.
        const maxW = window.innerWidth - 48; // VISIBLE_MARGIN
        const maxH = window.innerHeight - 83; // HEADER_HEIGHT(38) + VISIBLE_MARGIN(48) - 1 extra row
        if (saved.width > maxW || saved.height > maxH) {
          const scale = Math.min(maxW / saved.width, maxH / saved.height);
          return {
            width: Math.max(220, Math.round(saved.width * scale)),
            height: Math.max(124, Math.round(saved.height * scale)),
          };
        }
      }
      return saved;
    }
    return { width: 320, height: 180 };
  });
  const [isResizing, setIsResizing] = useState(false);
  const [dragPosition, setDragPosition] = useState(null);

  const MIN_WIDTH = 220;
  const MIN_HEIGHT = 124;
  const VISIBLE_MARGIN = 48; // keep part of the window visible when dragging
  const HEADER_HEIGHT = 38; // height of the close button header area
  const ERROR_HEIGHT = 45; // approximate height of error message area when displayed

  // Safely destroy the mpegts player to prevent errors
  const safeDestroyPlayer = () => {
    try {
      if (playerRef.current) {
        setIsLoading(false);
        setLoadError(null);

        if (videoRef.current) {
          videoRef.current.removeAttribute('src');
          videoRef.current.load();
        }

        try {
          playerRef.current.pause();
        } catch (e) {
          // Ignore pause errors
        }

        try {
          playerRef.current.destroy();
        } catch (error) {
          if (
            error.name !== 'AbortError' &&
            !error.message?.includes('aborted')
          ) {
            console.log('Error during player destruction:', error.message);
          }
        } finally {
          playerRef.current = null;
        }
      }
    } catch (error) {
      console.log('Error during player cleanup:', error);
      playerRef.current = null;
    }

    // Clear overlay timer
    if (overlayTimeoutRef.current) {
      clearTimeout(overlayTimeoutRef.current);
      overlayTimeoutRef.current = null;
    }
  };

  // Start overlay auto-hide timer
  const startOverlayTimer = () => {
    if (overlayTimeoutRef.current) {
      clearTimeout(overlayTimeoutRef.current);
    }
    overlayTimeoutRef.current = setTimeout(() => {
      setShowOverlay(false);
    }, 4000); // Hide after 4 seconds
  };

  // Initialize VOD player (native HTML5 with enhanced controls)
  const initializeVODPlayer = () => {
    if (!videoRef.current || !streamUrl) return;

    setIsLoading(true);
    setLoadError(null);
    setShowOverlay(false);
    setShowControls(false);

    console.log('Initializing VOD player for:', streamUrl);

    const video = videoRef.current;

    // Enhanced video element configuration for VOD
    video.preload = 'metadata';
    video.crossOrigin = 'anonymous';

    // Restore saved volume
    const { volume: savedVolume, muted: savedMuted } = getPlayerPrefs();
    if (typeof savedVolume === 'number') video.volume = savedVolume;
    if (typeof savedMuted === 'boolean') video.muted = savedMuted;
    const handleLoadStart = () => setIsLoading(true);
    const handleLoadedData = () => setIsLoading(false);
    const handleCanPlay = () => {
      setIsLoading(false);
      // Auto-play for VOD content
      video.play().catch((e) => {
        console.log('Auto-play prevented:', e);
        setLoadError('Auto-play was prevented. Click play to start.');
      });
      // Show overlay briefly when video is ready, then auto-hide
      setShowOverlay(true);
      startOverlayTimer();
    };
    const handleError = (e) => {
      setIsLoading(false);

      setLoadError(getVODPlayerErrorMessage(e.target.error));
    };

    // Enhanced progress tracking for VOD
    const handleProgress = () => {
      // if (video.buffered.length > 0) {
      //   const bufferedEnd = video.buffered.end(video.buffered.length - 1);
      //   const duration = video.duration;
      //   if (duration > 0) {
      //     const bufferedPercent = (bufferedEnd / duration) * 100;
      //     // You could emit this to a store for UI feedback
      //   }
      // }
    };

    // Add event listeners
    video.addEventListener('loadstart', handleLoadStart);
    video.addEventListener('loadeddata', handleLoadedData);
    video.addEventListener('canplay', handleCanPlay);
    video.addEventListener('error', handleError);
    video.addEventListener('progress', handleProgress);

    // Set the source
    video.src = streamUrl;
    video.load();

    // Store cleanup function
    playerRef.current = {
      destroy: () => {
        video.removeEventListener('loadstart', handleLoadStart);
        video.removeEventListener('loadeddata', handleLoadedData);
        video.removeEventListener('canplay', handleCanPlay);
        video.removeEventListener('error', handleError);
        video.removeEventListener('progress', handleProgress);
        video.removeAttribute('src');
        video.load();
      },
    };
  };

  // Initialize live stream player (mpegts.js)
  const initializeLivePlayer = () => {
    if (!videoRef.current || !streamUrl) return;

    setIsLoading(true);
    setLoadError(null);
    setShowControls(false);

    try {
      if (!mpegts.getFeatureList().mseLivePlayback) {
        setIsLoading(false);
        setLoadError(
          "Your browser doesn't support live video streaming. Please try Chrome or Edge."
        );
        return;
      }

      // mpegts.js workers run in WorkerGlobalScope where relative URLs are
      // not resolved against the page origin. Always pass an absolute URL.
      const absoluteStreamUrl =
        streamUrl.startsWith('/') && typeof window !== 'undefined'
          ? `${window.location.origin}${streamUrl}`
          : streamUrl;

      const player = mpegts.createPlayer(
        {
          type: 'mpegts',
          url: absoluteStreamUrl,
          isLive: true,
          cors: true,
        },
        {
          enableWorker: true,
          enableStashBuffer: false,
          liveBufferLatencyChasing: false,
          liveSync: false,
          autoCleanupSourceBuffer: true,
          autoCleanupMaxBackwardDuration: 120,
          autoCleanupMinBackwardDuration: 60,
          reuseRedirectedURL: true,
          headers: accessToken
            ? { Authorization: `Bearer ${accessToken}` }
            : undefined,
        }
      );

      player.attachMediaElement(videoRef.current);

      // Restore saved volume
      const { volume: savedVolume, muted: savedMuted } = getPlayerPrefs();
      if (typeof savedVolume === 'number')
        videoRef.current.volume = savedVolume;
      if (typeof savedMuted === 'boolean') videoRef.current.muted = savedMuted;

      player.on(mpegts.Events.LOADING_COMPLETE, () => {
        setIsLoading(false);
      });

      player.on(mpegts.Events.METADATA_ARRIVED, () => {
        setIsLoading(false);
      });

      player.on(mpegts.Events.ERROR, (errorType, errorDetail) => {
        setIsLoading(false);

        if (errorType !== 'NetworkError' || !errorDetail?.includes('aborted')) {
          console.error('Player error:', errorType, errorDetail);

          setLoadError(getLivePlayerErrorMessage(errorType, errorDetail));
        }
      });

      player.load();

      player.on(mpegts.Events.MEDIA_INFO, () => {
        setIsLoading(false);
        try {
          player.play().catch((e) => {
            console.log('Auto-play prevented:', e);
            setLoadError('Auto-play was prevented. Click play to start.');
          });
        } catch (e) {
          console.log('Error during play:', e);
          setLoadError(`Playback error: ${e.message}`);
        }
      });

      playerRef.current = player;
    } catch (error) {
      setIsLoading(false);
      console.error('Error initializing player:', error);

      if (
        error.message?.includes('codec') ||
        error.message?.includes('format')
      ) {
        setLoadError(
          'Codec not supported by your browser. Please try a different browser (Chrome/Edge recommended).'
        );
      } else {
        setLoadError(`Initialization error: ${error.message}`);
      }
    }
  };

  useEffect(() => {
    if (!isVisible || !streamUrl) {
      safeDestroyPlayer();
      return;
    }

    // Clean up any existing player
    safeDestroyPlayer();

    // Initialize the appropriate player based on content type
    if (contentType === 'vod') {
      initializeVODPlayer();
    } else {
      initializeLivePlayer();
    }

    // Attach volume-change listener now that the video element is in the DOM
    const video = videoRef.current;
    const handleVolumeChange = () =>
      savePlayerPrefs({ volume: video.volume, muted: video.muted });
    video?.addEventListener('volumechange', handleVolumeChange);

    return () => {
      video?.removeEventListener('volumechange', handleVolumeChange);
      safeDestroyPlayer();
    };
  }, [isVisible, streamUrl, contentType]);

  // Modified hideVideo handler to clean up player first
  const handleClose = (e) => {
    if (e) {
      e.stopPropagation();
      e.preventDefault();
    }
    safeDestroyPlayer();
    setTimeout(() => {
      hideVideo();
    }, 50);
  };

  const clampToVisible = useCallback(
    (x, y) => {
      if (typeof window === 'undefined') return { x, y };

      const totalHeight = videoSize.height + HEADER_HEIGHT + ERROR_HEIGHT;
      const minX = 0;
      // minY = 0 ensures the header row is always within the viewport so the
      // user can always grab and reposition the window.
      const minY = 0;
      const maxX = Math.max(0, window.innerWidth - videoSize.width);
      const maxY = Math.max(0, window.innerHeight - totalHeight);

      return {
        x: Math.min(Math.max(x, minX), maxX),
        y: Math.min(Math.max(y, minY), maxY),
      };
    },
    [HEADER_HEIGHT, ERROR_HEIGHT, videoSize.height, videoSize.width]
  );

  const clampToVisibleWithSize = useCallback(
    (x, y, width, height) => {
      if (typeof window === 'undefined') return { x, y };

      const totalHeight = height + HEADER_HEIGHT + ERROR_HEIGHT;
      const minX = 0; // left edge must stay in viewport
      const minY = 0; // header must always be reachable
      const maxX = Math.max(0, window.innerWidth - width);
      const maxY = Math.max(0, window.innerHeight - totalHeight);

      return {
        x: Math.min(Math.max(x, minX), maxX),
        y: Math.min(Math.max(y, minY), maxY),
      };
    },
    [HEADER_HEIGHT, ERROR_HEIGHT]
  );

  const handleResizeMove = useCallback(
    (event) => {
      if (!resizeStateRef.current) return;

      // If the mouse button was released outside the window, stop resizing.
      // Remove the move listeners immediately; the mouseup/touchend listener
      // (endResize) will clean itself up the next time the user clicks.
      if (event.type === 'mousemove' && event.buttons === 0) {
        resizeStateRef.current = null;
        setIsResizing(false);
        window.removeEventListener('mousemove', handleResizeMove);
        window.removeEventListener('touchmove', handleResizeMove);
        return;
      }

      const { clientX, clientY } = getClientCoordinates(event);
      const {
        startX,
        startY,
        startWidth,
        startHeight,
        startPos,
        handle,
        aspectRatio,
      } = resizeStateRef.current;

      const ratio = aspectRatio || aspectRatioRef.current;
      const { width: nextWidth, height: nextHeight } = calculateNewDimensions(
        clientX - startX,
        clientY - startY,
        startWidth,
        startHeight,
        handle,
        ratio
      );

      const constrainedSize = applyConstraints(
        nextWidth,
        nextHeight,
        ratio,
        startPos,
        handle,
        MIN_WIDTH,
        MIN_HEIGHT,
        VISIBLE_MARGIN
      );

      setVideoSize({
        width: Math.round(constrainedSize.width),
        height: Math.round(constrainedSize.height),
      });

      updatePositionIfNeeded(
        handle,
        startPos,
        startWidth,
        startHeight,
        constrainedSize
      );
    },
    [MIN_HEIGHT, MIN_WIDTH, VISIBLE_MARGIN, clampToVisibleWithSize]
  );

  const updatePositionIfNeeded = (
    handle,
    startPos,
    startWidth,
    startHeight,
    newSize
  ) => {
    if (!handle.isLeft && !handle.isTop) return;

    const posX = startPos?.x ?? 0;
    const posY = startPos?.y ?? 0;
    let nextX = handle.isLeft ? posX + (startWidth - newSize.width) : posX;
    let nextY = handle.isTop ? posY + (startHeight - newSize.height) : posY;

    const clamped = clampToVisibleWithSize(
      nextX,
      nextY,
      newSize.width,
      newSize.height
    );
    const nextPos = {
      x: handle.isLeft ? clamped.x : nextX,
      y: handle.isTop ? clamped.y : nextY,
    };

    setDragPosition(nextPos);
    dragPositionRef.current = nextPos;
  };

  const endResize = useCallback(() => {
    setIsResizing(false);
    resizeStateRef.current = null;
    window.removeEventListener('mousemove', handleResizeMove);
    window.removeEventListener('mouseup', endResize);
    window.removeEventListener('touchmove', handleResizeMove);
    window.removeEventListener('touchend', endResize);
  }, [handleResizeMove]);

  const startResize = (event, handle) => {
    event.stopPropagation();
    event.preventDefault();

    const { clientX, clientY } = getClientCoordinates(event);

    const aspectRatio =
      videoSize.height > 0
        ? videoSize.width / videoSize.height
        : aspectRatioRef.current;
    aspectRatioRef.current = aspectRatio;
    const startPos = dragPositionRef.current ||
      initialPositionRef.current || { x: 0, y: 0 };

    resizeStateRef.current = {
      startX: clientX,
      startY: clientY,
      startWidth: videoSize.width,
      startHeight: videoSize.height,
      aspectRatio,
      startPos,
      handle,
    };

    setIsResizing(true);

    window.addEventListener('mousemove', handleResizeMove);
    window.addEventListener('mouseup', endResize);
    window.addEventListener('touchmove', handleResizeMove);
    window.addEventListener('touchend', endResize);
  };

  useEffect(() => {
    return () => {
      endResize();
    };
  }, [endResize]);

  useEffect(() => {
    dragPositionRef.current = dragPosition;
  }, [dragPosition]);

  // Keep videoSizeRef current so the window-resize handler never closes over
  // a stale videoSize value.
  useEffect(() => {
    videoSizeRef.current = videoSize;
  }, [videoSize]);

  // Re-clamp size and position when the browser viewport changes
  useEffect(() => {
    const handleWindowResize = () => {
      const maxW = window.innerWidth - VISIBLE_MARGIN;
      const maxH = window.innerHeight - VISIBLE_MARGIN;
      const { width: curW, height: curH } = videoSizeRef.current ?? {
        width: 320,
        height: 180,
      };

      let newW = curW;
      let newH = curH;
      if (curW > maxW || curH > maxH) {
        const scale = Math.min(maxW / curW, maxH / curH);
        newW = Math.max(MIN_WIDTH, Math.round(curW * scale));
        newH = Math.max(MIN_HEIGHT, Math.round(curH * scale));
        setVideoSize({ width: newW, height: newH });
      }

      if (dragPositionRef.current) {
        const totalH = newH + HEADER_HEIGHT + ERROR_HEIGHT;
        const clamped = {
          x: Math.min(
            Math.max(dragPositionRef.current.x, 0),
            Math.max(0, window.innerWidth - newW)
          ),
          y: Math.min(
            Math.max(dragPositionRef.current.y, 0),
            Math.max(0, window.innerHeight - totalH)
          ),
        };
        if (
          clamped.x !== dragPositionRef.current.x ||
          clamped.y !== dragPositionRef.current.y
        ) {
          setDragPosition(clamped);
          dragPositionRef.current = clamped;
        }
      }
    };
    window.addEventListener('resize', handleWindowResize);
    return () => window.removeEventListener('resize', handleWindowResize);
  }, [MIN_WIDTH, MIN_HEIGHT, VISIBLE_MARGIN, HEADER_HEIGHT, ERROR_HEIGHT]);

  // Persist size whenever it changes, but skip high-frequency writes during
  // an active resize drag — the final value is captured when isResizing clears.
  useEffect(() => {
    if (!isResizing) {
      savePlayerPrefs({ size: videoSize });
    }
  }, [videoSize, isResizing]);

  // Persist position when a resize ends
  useEffect(() => {
    if (!isResizing && dragPositionRef.current) {
      savePlayerPrefs({ position: dragPositionRef.current });
    }
  }, [isResizing]);

  // Initialize the floating window near bottom-right once
  useEffect(() => {
    if (initialPositionRef.current || typeof window === 'undefined') return;

    // Try to restore the last saved position
    const savedPos = getPlayerPrefs().position;
    if (savedPos) {
      const clamped = clampToVisible(savedPos.x, savedPos.y);
      initialPositionRef.current = clamped;
      setDragPosition(clamped);
      dragPositionRef.current = clamped;
      return;
    }

    const totalHeight = videoSize.height + HEADER_HEIGHT + ERROR_HEIGHT;
    const initialX = Math.max(10, window.innerWidth - videoSize.width - 20);
    const initialY = Math.max(10, window.innerHeight - totalHeight - 20);
    const pos = clampToVisible(initialX, initialY);

    initialPositionRef.current = pos;
    setDragPosition(pos);
    dragPositionRef.current = pos;
  }, [
    clampToVisible,
    videoSize.height,
    videoSize.width,
    HEADER_HEIGHT,
    ERROR_HEIGHT,
  ]);

  const handleDragStart = useCallback(
    (event, data) => {
      const clientX = event.touches?.[0]?.clientX ?? event.clientX;
      const clientY = event.touches?.[0]?.clientY ?? event.clientY;
      const rect = videoContainerRef.current?.getBoundingClientRect();

      if (clientX != null && clientY != null && rect) {
        dragOffsetRef.current = {
          x: clientX - rect.left,
          y: clientY - rect.top,
        };
      } else {
        dragOffsetRef.current = { x: 0, y: 0 };
      }

      const clamped = clampToVisible(data?.x ?? 0, data?.y ?? 0);
      setDragPosition(clamped);
      dragPositionRef.current = clamped;
    },
    [clampToVisible]
  );

  const handleDrag = useCallback(
    (event) => {
      // If the mouse button was released outside the browser window the
      // mouseup event is never delivered to react-draggable. Detect this on
      // the next mousemove and fire a synthetic mouseup so it stops dragging.
      if (event.type === 'mousemove' && event.buttons === 0) {
        window.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
        return;
      }
      const clientX = event.touches?.[0]?.clientX ?? event.clientX;
      const clientY = event.touches?.[0]?.clientY ?? event.clientY;
      if (clientX == null || clientY == null) return;

      const nextX = clientX - (dragOffsetRef.current?.x ?? 0);
      const nextY = clientY - (dragOffsetRef.current?.y ?? 0);
      const clamped = clampToVisible(nextX, nextY);
      setDragPosition(clamped);
      dragPositionRef.current = clamped;
    },
    [clampToVisible]
  );

  const handleDragStop = useCallback(
    (_, data) => {
      const clamped = clampToVisible(data?.x ?? 0, data?.y ?? 0);
      setDragPosition(clamped);
      dragPositionRef.current = clamped;
      savePlayerPrefs({ position: clamped });
    },
    [clampToVisible]
  );

  // If the floating video is hidden or no URL is selected, do not render
  if (!isVisible || !streamUrl) {
    return null;
  }

  return (
    <Draggable
      nodeRef={videoContainerRef}
      cancel=".floating-video-no-drag"
      disabled={isResizing}
      position={dragPosition || undefined}
      defaultPosition={initialPositionRef.current || { x: 0, y: 0 }}
      onStart={handleDragStart}
      onDrag={handleDrag}
      onStop={handleDragStop}
    >
      <div
        ref={videoContainerRef}
        style={{
          position: 'fixed',
          top: 0,
          left: 0,
          width: `${videoSize.width}px`,
          zIndex: 9999,
          backgroundColor: '#333',
          borderRadius: '8px',
          overflow: 'visible',
          boxShadow: '0 2px 10px rgba(0,0,0,0.7)',
        }}
      >
        {/* Header row with optional title and close button */}
        <Flex
          justify="space-between"
          align="center"
          style={{
            padding: '3px 3px 3px 8px',
            minHeight: '38px',
            cursor: 'grab',
            userSelect: 'none',
          }}
        >
          {metadata?.name ? (
            <Text
              size="xs"
              fw={600}
              style={{
                color: 'rgba(255,255,255,0.9)',
                flex: 1,
                overflow: 'hidden',
                whiteSpace: 'nowrap',
                textOverflow: 'ellipsis',
                paddingRight: 4,
                textShadow: '0px 1px 3px rgba(0,0,0,0.8)',
                userSelect: 'none',
              }}
            >
              {metadata.name}
            </Text>
          ) : (
            <Box style={{ flex: 1 }} />
          )}
          <CloseButton
            onClick={handleClose}
            onTouchEnd={handleClose}
            onMouseDown={(e) => e.stopPropagation()}
            onTouchStart={(e) => e.stopPropagation()}
            style={{
              minHeight: '32px',
              minWidth: '32px',
              cursor: 'pointer',
              touchAction: 'manipulation',
              flexShrink: 0,
            }}
          />
        </Flex>

        {/* Video container with relative positioning for the overlay */}
        <Box
          style={{ position: 'relative' }}
          onMouseEnter={() => {
            setShowControls(true);
            if (contentType === 'vod' && !isLoading) {
              setShowOverlay(true);
              if (overlayTimeoutRef.current) {
                clearTimeout(overlayTimeoutRef.current);
              }
            }
          }}
          onMouseLeave={() => {
            if (contentType === 'vod' && !isLoading) {
              startOverlayTimer();
            }
          }}
        >
          {/* Enhanced video element with better controls for VOD */}
          <video
            ref={videoRef}
            controls={showControls}
            className="floating-video-no-drag"
            style={{
              width: '100%',
              height: `${videoSize.height}px`,
              backgroundColor: '#000',
              borderRadius: '0 0 8px 8px',
              // Better controls styling for VOD
              ...(contentType === 'vod' && {
                controlsList: 'nodownload',
                playsInline: true,
              }),
            }}
            // Add poster for VOD if available
            {...(contentType === 'vod' && {
              poster: metadata?.logo?.url, // Use VOD poster if available
            })}
          />

          {/* VOD title overlay when not loading - auto-hides after 4 seconds */}
          {!isLoading && metadata && contentType === 'vod' && showOverlay && (
            <Box
              style={{
                position: 'absolute',
                top: 0,
                left: 0,
                right: 0,
                background: 'linear-gradient(rgba(0,0,0,0.8), transparent)',
                padding: '10px 10px 20px',
                color: 'white',
                pointerEvents: 'none', // Allow clicks to pass through to video controls
                transition: 'opacity 0.3s ease-in-out',
                opacity: showOverlay ? 1 : 0,
              }}
            >
              <Text
                size="sm"
                weight={500}
                style={{ textShadow: '1px 1px 2px rgba(0,0,0,0.8)' }}
              >
                {metadata.name}
              </Text>
              {metadata.year && (
                <Text
                  size="xs"
                  color="dimmed"
                  style={{ textShadow: '1px 1px 2px rgba(0,0,0,0.8)' }}
                >
                  {metadata.year}
                </Text>
              )}
            </Box>
          )}

          {/* Loading overlay - only show when loading */}
          {isLoading && (
            <Box
              style={{
                position: 'absolute',
                top: 0,
                left: 0,
                width: '100%',
                height: '100%',
                backgroundColor: 'rgba(0, 0, 0, 0.7)',
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                justifyContent: 'center',
                zIndex: 5,
              }}
            >
              <Loader color="cyan" size="md" />
              <Text color="white" size="sm" mt={10}>
                Loading {contentType === 'vod' ? 'video' : 'stream'}...
              </Text>
            </Box>
          )}
        </Box>

        {/* Error message below video - doesn't block controls */}
        {!isLoading && loadError && (
          <Box
            style={{
              padding: '10px',
              backgroundColor: '#2d1b2e',
              borderTop: '1px solid #444',
            }}
          >
            <Text color="red" size="xs" style={{ textAlign: 'center' }}>
              {loadError}
            </Text>
          </Box>
        )}

        <ResizeHandles startResize={startResize} />
      </div>
    </Draggable>
  );
}
