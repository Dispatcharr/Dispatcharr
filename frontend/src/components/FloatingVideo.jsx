// frontend/src/components/FloatingVideo.js
import React, { useCallback, useEffect, useRef, useState } from 'react';
import Draggable from 'react-draggable';
import useVideoStore from '../store/useVideoStore';
import mpegts from 'mpegts.js';
import { CloseButton, Flex, Loader, Text, Box } from '@mantine/core';
import {
  applyConstraints,
  calculateNewDimensions,
  getClientCoordinates,
  getLivePlayerErrorMessage,
  getVODPlayerErrorMessage,
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
}

export default function FloatingVideo() {
  const isVisible = useVideoStore((s) => s.isVisible);
  const streamUrl = useVideoStore((s) => s.streamUrl);
  const contentType = useVideoStore((s) => s.contentType);
  const metadata = useVideoStore((s) => s.metadata);
  const hideVideo = useVideoStore((s) => s.hideVideo);

  const videoRef = useRef(null);
  const playerRef = useRef(null);
  const videoContainerRef = useRef(null);
  const resizeStateRef = useRef(null);
  const overlayTimeoutRef = useRef(null);
  const aspectRatioRef = useRef(320 / 180);
  const dragPositionRef = useRef(null);
  const dragOffsetRef = useRef({ x: 0, y: 0 });
  const initialPositionRef = useRef(null);

  const [isLoading, setIsLoading] = useState(false);
  const [loadError, setLoadError] = useState(null);
  const [showOverlay, setShowOverlay] = useState(true);
  const [videoSize, setVideoSize] = useState({ width: 320, height: 180 });
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
    setShowOverlay(true); // Show overlay initially

    console.log('Initializing VOD player for:', streamUrl);

    const video = videoRef.current;

    // Enhanced video element configuration for VOD
    video.preload = 'metadata';
    video.crossOrigin = 'anonymous';

    // Set up event listeners
    const handleLoadStart = () => setIsLoading(true);
    const handleLoadedData = () => setIsLoading(false);
    const handleCanPlay = () => {
      setIsLoading(false);
      // Auto-play for VOD content
      video.play().catch((e) => {
        console.log('Auto-play prevented:', e);
        setLoadError('Auto-play was prevented. Click play to start.');
      });
      // Start overlay timer when video is ready
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

    console.log('Initializing live stream player for:', streamUrl);

    try {
      if (!mpegts.getFeatureList().mseLivePlayback) {
        setIsLoading(false);
        setLoadError(
          "Your browser doesn't support live video streaming. Please try Chrome or Edge."
        );
        return;
      }

      const player = mpegts.createPlayer({
        type: 'mpegts',
        url: streamUrl,
        isLive: true,
        enableWorker: true,
        enableStashBuffer: false,
        liveBufferLatencyChasing: true,
        liveSync: true,
        cors: true,
        autoCleanupSourceBuffer: true,
        autoCleanupMaxBackwardDuration: 10,
        autoCleanupMinBackwardDuration: 5,
        reuseRedirectedURL: true,
      });

      player.attachMediaElement(videoRef.current);

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

    // Cleanup when component unmounts or streamUrl changes
    return () => {
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
      const minX = -(videoSize.width - VISIBLE_MARGIN);
      const minY = -(totalHeight - VISIBLE_MARGIN);
      const maxX = window.innerWidth - videoSize.width;
      const maxY = window.innerHeight - totalHeight;

      return {
        x: Math.min(Math.max(x, minX), maxX),
        y: Math.min(Math.max(y, minY), maxY),
      };
    },
    [
      VISIBLE_MARGIN,
      HEADER_HEIGHT,
      ERROR_HEIGHT,
      videoSize.height,
      videoSize.width,
    ]
  );

  const clampToVisibleWithSize = useCallback(
    (x, y, width, height) => {
      if (typeof window === 'undefined') return { x, y };

      const totalHeight = height + HEADER_HEIGHT + ERROR_HEIGHT;
      const minX = -(width - VISIBLE_MARGIN);
      const minY = -(totalHeight - VISIBLE_MARGIN);
      const maxX = window.innerWidth - width;
      const maxY = window.innerHeight - totalHeight;

      return {
        x: Math.min(Math.max(x, minX), maxX),
        y: Math.min(Math.max(y, minY), maxY),
      };
    },
    [VISIBLE_MARGIN, HEADER_HEIGHT, ERROR_HEIGHT]
  );

  const handleResizeMove = useCallback(
    (event) => {
      if (!resizeStateRef.current) return;

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

  const updatePositionIfNeeded = (handle, startPos, startWidth, startHeight, newSize) => {
    if (!handle.isLeft && !handle.isTop) return;

    const posX = startPos?.x ?? 0;
    const posY = startPos?.y ?? 0;
    let nextX = handle.isLeft ? posX + (startWidth - newSize.width) : posX;
    let nextY = handle.isTop ? posY + (startHeight - newSize.height) : posY;

    const clamped = clampToVisibleWithSize(nextX, nextY, newSize.width, newSize.height);
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

  // Initialize the floating window near bottom-right once
  useEffect(() => {
    if (initialPositionRef.current || typeof window === 'undefined') return;

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
        {/* Simple header row with a close button */}
        <Flex
          justify="flex-end"
          style={{
            padding: 3,
          }}
        >
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
            }}
          />
        </Flex>

        {/* Video container with relative positioning for the overlay */}
        <Box
          style={{ position: 'relative' }}
          onMouseEnter={() => {
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
            controls
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

        <ResizeHandles startResize={startResize}/>
      </div>
    </Draggable>
  );
}
