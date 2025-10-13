// frontend/src/components/FloatingVideo.js
import React, { useCallback, useEffect, useRef, useState } from 'react';
import Draggable from 'react-draggable';
import useVideoStore from '../store/useVideoStore';
import mpegts from 'mpegts.js';
import {
  CloseButton,
  Flex,
  Loader,
  Text,
  Box,
  Button,
  Progress,
  Group,
  Slider,
  ActionIcon,
} from '@mantine/core';
import { Play, Pause, Volume2, VolumeX, Maximize, Minimize } from 'lucide-react';
import API from '../api';
import useAuthStore from '../store/auth';

const CONTROL_HIDE_DELAY = 2500;

const formatTime = (value) => {
  if (!Number.isFinite(value)) {
    return '0:00';
  }
  const totalSeconds = Math.max(0, Math.floor(value));
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  if (hours > 0) {
    return `${hours}:${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
  }
  return `${minutes}:${String(seconds).padStart(2, '0')}`;
};

export default function FloatingVideo() {
  const isVisible = useVideoStore((s) => s.isVisible);
  const streamUrl = useVideoStore((s) => s.streamUrl);
  const contentType = useVideoStore((s) => s.contentType);
  const metadata = useVideoStore((s) => s.metadata);
  const hideVideo = useVideoStore((s) => s.hideVideo);
  const videoRef = useRef(null);
  const playerRef = useRef(null);
  const videoContainerRef = useRef(null);
  const [isLoading, setIsLoading] = useState(false);
  const [loadError, setLoadError] = useState(null);
  const [showOverlay, setShowOverlay] = useState(true);
  const overlayTimeoutRef = useRef(null);
  const lastProgressSentRef = useRef(0);
  const [nextAutoplay, setNextAutoplay] = useState(null);
  const [autoplayCountdown, setAutoplayCountdown] = useState(null);
  const autoPlayTimerRef = useRef(null);
  const countdownIntervalRef = useRef(null);
  const AUTOPLAY_SECONDS = 10;
  const authUser = useAuthStore((s) => s.user);
  const [isPlaying, setIsPlaying] = useState(false);
  const [currentTimeSeconds, setCurrentTimeSeconds] = useState(
    (metadata?.startOffsetMs ?? 0) / 1000
  );
  const [durationSeconds, setDurationSeconds] = useState(
    metadata?.durationMs ? metadata.durationMs / 1000 : 0
  );
  const [isScrubbing, setIsScrubbing] = useState(false);
  const [scrubValueSeconds, setScrubValueSeconds] = useState(
    (metadata?.startOffsetMs ?? 0) / 1000
  );
  const [showControls, setShowControls] = useState(true);
  const controlsTimeoutRef = useRef(null);
  const serverSeekInProgressRef = useRef(false);
  const lastServerSeekAbsoluteRef = useRef((metadata?.startOffsetMs ?? 0) / 1000);
  const wasPlayingBeforeScrubRef = useRef(false);
  const [volume, setVolume] = useState(1);
  const [isMuted, setIsMuted] = useState(false);
  const previousVolumeRef = useRef(1);
  const [showVolumeControl, setShowVolumeControl] = useState(false);
  const [isFullscreen, setIsFullscreen] = useState(false);

  const updateVideoMetadata = useCallback((updates) => {
    if (!updates || typeof updates !== 'object') {
      return;
    }
    useVideoStore.setState((state) => {
      if (!state.metadata) {
        return {};
      }
      return {
        metadata: {
          ...state.metadata,
          ...updates,
        },
      };
    });
  }, []);

  const clearControlsTimeout = () => {
    if (controlsTimeoutRef.current) {
      clearTimeout(controlsTimeoutRef.current);
      controlsTimeoutRef.current = null;
    }
  };

  useEffect(() => {
    if (!showControls) {
      setShowVolumeControl(false);
    }
  }, [showControls]);

  const handlePointerActivity = () => {
    setShowControls(true);
    clearControlsTimeout();
    controlsTimeoutRef.current = setTimeout(() => {
      if (!isScrubbing && !serverSeekInProgressRef.current) {
        setShowControls(false);
      }
    }, CONTROL_HIDE_DELAY);
  };

  useEffect(() => {
    const video = videoRef.current;
    if (video) {
      video.volume = volume;
      video.muted = isMuted || volume === 0;
    }
  }, [volume, isMuted]);

  useEffect(() => {
    const video = videoRef.current;
    if (video) {
      video.volume = volume;
      video.muted = isMuted || volume === 0;
    }
  }, [streamUrl]);

  useEffect(() => {
    const handleFullscreenChange = () => {
      const container = videoContainerRef.current;
      setIsFullscreen(document.fullscreenElement === container);
    };

    document.addEventListener('fullscreenchange', handleFullscreenChange);
    document.addEventListener('webkitfullscreenchange', handleFullscreenChange);
    document.addEventListener('mozfullscreenchange', handleFullscreenChange);
    document.addEventListener('MSFullscreenChange', handleFullscreenChange);

    return () => {
      document.removeEventListener('fullscreenchange', handleFullscreenChange);
      document.removeEventListener('webkitfullscreenchange', handleFullscreenChange);
      document.removeEventListener('mozfullscreenchange', handleFullscreenChange);
      document.removeEventListener('MSFullscreenChange', handleFullscreenChange);
    };
  }, []);

  const toggleFullscreen = () => {
    const container = videoContainerRef.current;
    if (!container) return;
    handlePointerActivity();
    const request = container.requestFullscreen
      || container.webkitRequestFullscreen
      || container.mozRequestFullScreen
      || container.msRequestFullscreen;
    const exit =
      document.exitFullscreen ||
      document.webkitExitFullscreen ||
      document.mozCancelFullScreen ||
      document.msExitFullscreen;

    if (!document.fullscreenElement && request) {
      request.call(container).catch(() => {});
    } else if (document.fullscreenElement === container && exit) {
      exit.call(document).catch(() => {});
    } else if (request) {
      exit?.call(document).finally(() => {
        request.call(container).catch(() => {});
      });
    }
  };

  const handleVolumeSliderChange = (value) => {
    if (!Number.isFinite(value)) {
      return;
    }
    handlePointerActivity();
    const clamped = Math.max(0, Math.min(1, value));
    setVolume(clamped);
    if (clamped > 0) {
      previousVolumeRef.current = clamped;
      setIsMuted(false);
    } else {
      setIsMuted(true);
    }
  };

  const toggleMute = () => {
    handlePointerActivity();
    const video = videoRef.current;
    if (!video) {
      return;
    }
    if (isMuted || volume === 0 || video.muted) {
      const restored = previousVolumeRef.current > 0 ? previousVolumeRef.current : 0.5;
      setVolume(restored);
      setIsMuted(false);
    } else {
      previousVolumeRef.current = volume > 0 ? volume : 0.5;
      setVolume(0);
      setIsMuted(true);
    }
  };

  const handleVolumeButtonClick = () => {
    handlePointerActivity();
    if (!showVolumeControl) {
      setShowVolumeControl(true);
      return;
    }
    toggleMute();
  };

  const togglePlayback = () => {
    const video = videoRef.current;
    if (!video || serverSeekInProgressRef.current || isLoading) return;
    handlePointerActivity();
    if (video.paused) {
      video.play().catch(() => {});
    } else {
      video.pause();
    }
  };

  const performSeek = (targetSeconds) => {
    if (!Number.isFinite(targetSeconds)) {
      return;
    }

    const sanitized = Math.max(0, targetSeconds);
    const startOffsetSeconds = (metadata?.startOffsetMs ?? 0) / 1000;
    const video = videoRef.current;

    const isLocalSeek =
      !metadata?.requiresTranscode || metadata?.transcodeStatus === 'ready' || !metadata?.mediaItemId;

    if (isLocalSeek) {
      if (video) {
        const shouldResume = wasPlayingBeforeScrubRef.current || !video.paused;
        try {
          video.currentTime = Math.max(0, sanitized - startOffsetSeconds);
        } catch (err) {
          console.debug('Failed to adjust local playback position', err);
        }
        if (shouldResume) {
          video.play().catch(() => {});
        }
        setIsPlaying(!video.paused);
      }
      setCurrentTimeSeconds(sanitized);
      setScrubValueSeconds(sanitized);
      lastServerSeekAbsoluteRef.current = sanitized;
      serverSeekInProgressRef.current = false;
      setIsLoading(false);
      handlePointerActivity();
      wasPlayingBeforeScrubRef.current = false;
      return;
    }

    if (!metadata?.fileId) {
      console.debug('Seek requested without file identifier; aborting');
      serverSeekInProgressRef.current = false;
      setIsLoading(false);
      return;
    }

    serverSeekInProgressRef.current = true;
    lastServerSeekAbsoluteRef.current = sanitized;
    setIsLoading(true);
    setLoadError(null);
    setShowControls(true);
    clearControlsTimeout();

    if (video) {
      try {
        video.pause();
      } catch (pauseError) {
        console.debug('Failed to pause prior to server seek', pauseError);
      }
    }
    setIsPlaying(false);

    const startMs = Math.round(sanitized * 1000);

    API.streamMediaItem(metadata.mediaItemId, {
      fileId: metadata.fileId,
      startMs,
    })
      .then((streamInfo) => {
        const playbackUrl = streamInfo?.url || streamInfo?.stream_url;
        if (!playbackUrl) {
          throw new Error('Streaming endpoint did not return a playable URL.');
        }

        const startOffsetMs = streamInfo?.start_offset_ms ?? 0;
        const resumeHandledByServer = startOffsetMs > 0;
        const requiresTranscode = Boolean(streamInfo?.requires_transcode);
        const transcodeStatus = streamInfo?.transcode_status ?? metadata?.transcodeStatus ?? null;
        const derivedDurationMs =
          streamInfo?.duration_ms ??
          metadata?.durationMs ??
          (videoRef.current?.duration
            ? Math.round(
                ((metadata?.startOffsetMs ?? 0) / 1000 + videoRef.current.duration) * 1000
              )
            : undefined);

        if (!resumeHandledByServer) {
          updateVideoMetadata({
            requiresTranscode,
            transcodeStatus,
            durationMs: derivedDurationMs ?? metadata?.durationMs ?? null,
            resumeHandledByServer: false,
            resumePositionMs: startMs,
          });
          if (videoRef.current) {
            const resumeWasPlaying = wasPlayingBeforeScrubRef.current || !videoRef.current.paused;
            try {
              videoRef.current.currentTime = Math.max(0, sanitized - startOffsetSeconds);
            } catch (err) {
              console.debug('Failed to adjust local playback position after server seek fallback', err);
            }
            if (resumeWasPlaying) {
              videoRef.current.play().catch(() => {});
            }
            setIsPlaying(!videoRef.current.paused);
          }
          setCurrentTimeSeconds(sanitized);
          setScrubValueSeconds(sanitized);
          lastServerSeekAbsoluteRef.current = sanitized;
          serverSeekInProgressRef.current = false;
          wasPlayingBeforeScrubRef.current = false;
          setIsLoading(false);
          setLoadError(null);
          handlePointerActivity();
          return;
        }

        const nextMetadata = {
          ...metadata,
          resumePositionMs: startMs,
          resumeHandledByServer,
          startOffsetMs:
            startOffsetMs || (resumeHandledByServer ? startMs : metadata?.startOffsetMs ?? 0),
          requiresTranscode,
          transcodeStatus,
          durationMs: derivedDurationMs,
        };

        wasPlayingBeforeScrubRef.current = false;
        useVideoStore.getState().showVideo(playbackUrl, 'library', nextMetadata);
      })
      .catch((err) => {
        console.error('Failed to perform server-side seek', err);
        setLoadError('Unable to seek in this stream.');
        setIsLoading(false);
        serverSeekInProgressRef.current = false;
        if (video) {
          try {
            video.play();
          } catch (playErr) {
            console.debug('Failed to resume after seek failure', playErr);
          }
        }
        wasPlayingBeforeScrubRef.current = false;
      });
  };

  const handleScrubChange = (value) => {
    const video = videoRef.current;
    if (!isScrubbing) {
      setIsScrubbing(true);
      wasPlayingBeforeScrubRef.current = video ? !video.paused : false;
    }
    if (video) {
      try {
        video.pause();
      } catch (pauseError) {
        console.debug('Failed to pause video while scrubbing', pauseError);
      }
      setIsPlaying(false);
    }
    setScrubValueSeconds(value);
    handlePointerActivity();
  };

  const handleScrubEnd = (value) => {
    setIsScrubbing(false);
    performSeek(value);
  };

  const sendLibraryProgress = (positionSeconds, durationSeconds, completed = false) => {
    if (contentType !== 'library') return;
    if (!metadata?.mediaItemId || !authUser?.id) return;
    const startOffsetMs = metadata?.startOffsetMs ?? 0;
    const relativePosition = Number.isFinite(positionSeconds) ? positionSeconds : 0;
    const absolutePositionSeconds = Math.max(0, startOffsetMs / 1000 + relativePosition);

    let totalDurationMs;
    if (metadata?.durationMs) {
      totalDurationMs = metadata.durationMs;
    } else {
      const relativeDuration = Number.isFinite(durationSeconds) ? durationSeconds : 0;
      const fallbackDurationSeconds =
        relativeDuration > 0
          ? relativeDuration
          : videoRef.current?.duration
          ? videoRef.current.duration
          : 0;
      totalDurationMs = Math.round(
        Math.max(absolutePositionSeconds, startOffsetMs / 1000 + fallbackDurationSeconds) * 1000
      );
    }

    let positionMs = Math.round(absolutePositionSeconds * 1000);
    if (completed) {
      positionMs = totalDurationMs;
    } else {
      positionMs = Math.min(positionMs, totalDurationMs);
    }

    const payload = {
      user: authUser.id,
      media_item: metadata.mediaItemId,
      position_ms: Math.max(0, positionMs),
      duration_ms: Math.max(0, totalDurationMs),
      completed,
    };
    API.setMediaWatchProgress(payload).catch((error) => {
      console.debug('Failed to update watch progress', error);
    });
  };

  useEffect(() => {
    const start = (metadata?.startOffsetMs ?? 0) / 1000;
    setCurrentTimeSeconds(start);
    setScrubValueSeconds(start);
    if (metadata?.durationMs) {
      setDurationSeconds(metadata.durationMs / 1000);
    }
    wasPlayingBeforeScrubRef.current = false;
  }, [metadata?.mediaItemId, metadata?.startOffsetMs, metadata?.durationMs]);

  useEffect(() => {
    if (isScrubbing) {
      setShowControls(true);
      clearControlsTimeout();
    }
  }, [isScrubbing]);


  useEffect(() => () => clearControlsTimeout(), []);

  const clearAutoPlayTimers = () => {
    if (autoPlayTimerRef.current) {
      clearTimeout(autoPlayTimerRef.current);
      autoPlayTimerRef.current = null;
    }
    if (countdownIntervalRef.current) {
      clearInterval(countdownIntervalRef.current);
      countdownIntervalRef.current = null;
    }
    setNextAutoplay(null);
    setAutoplayCountdown(null);
  };

  // Safely destroy the mpegts player to prevent errors
  const safeDestroyPlayer = () => {
    try {
      if (playerRef.current) {
        setIsLoading(false);
        setLoadError(null);
        setIsPlaying(false);
        clearControlsTimeout();
        setShowControls(true);

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

    lastProgressSentRef.current = 0;

    // Clear overlay timer
    if (overlayTimeoutRef.current) {
      clearTimeout(overlayTimeoutRef.current);
      overlayTimeoutRef.current = null;
    }

    clearAutoPlayTimers();
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

  const playEpisodeAtIndex = async (index) => {
    const sequence = metadata?.playbackSequence;
    const episodeIds = sequence?.episodeIds || [];
    const nextEpisodeId = episodeIds[index];
    if (!nextEpisodeId) {
      clearAutoPlayTimers();
      return;
    }

    clearAutoPlayTimers();
    try {
      const episodeDetail = await API.getMediaItem(nextEpisodeId);
      const fileId = episodeDetail.files?.[0]?.id;
      if (!fileId) {
        setLoadError('Next episode is missing media files.');
        return;
      }
      const summary = episodeDetail.watch_summary;
      const resumePositionMs =
        summary?.status === 'in_progress'
          ? summary.position_ms || 0
          : episodeDetail.watch_progress?.position_ms || 0;
      const initialDurationMs =
        summary?.duration_ms ??
        episodeDetail.watch_progress?.duration_ms ??
        episodeDetail.runtime_ms ??
        episodeDetail.files?.[0]?.duration_ms ??
        null;

      const streamInfo = await API.streamMediaItem(episodeDetail.id, {
        fileId,
        startMs: resumePositionMs,
      });
      const playbackUrl = streamInfo?.url || streamInfo?.stream_url;
      if (!playbackUrl) {
        setLoadError('Streaming endpoint did not return a playable URL.');
        return;
      }

      const startOffsetMs = streamInfo?.start_offset_ms ?? 0;
      const resumeHandledByServer = startOffsetMs > 0;
      const requiresTranscode = Boolean(streamInfo?.requires_transcode);
      const transcodeStatus = streamInfo?.transcode_status ?? null;
      const durationMs =
        streamInfo?.duration_ms ?? initialDurationMs;

      const playbackSequence = {
        episodeIds,
        currentIndex: index,
      };

      useVideoStore.getState().showVideo(playbackUrl, 'library', {
        mediaItemId: episodeDetail.id,
        mediaTitle: episodeDetail.title,
        showId: metadata?.showId,
        showTitle: metadata?.showTitle,
        name: episodeDetail.title,
        year: episodeDetail.release_year,
        logo:
          episodeDetail.poster_url
            ? { url: episodeDetail.poster_url }
            : metadata?.logo || (metadata?.showPoster ? { url: metadata.showPoster } : undefined),
        progressId: episodeDetail.watch_progress?.id,
        resumePositionMs,
        resumeHandledByServer,
        startOffsetMs,
        requiresTranscode,
        transcodeStatus,
        durationMs,
        fileId,
        playbackSequence,
      });
    } catch (error) {
      console.error('Failed to auto-play next episode', error);
      setLoadError('Unable to start the next episode automatically.');
    }
  };

  const startAutoPlayCountdown = (nextIndex) => {
    const sequence = metadata?.playbackSequence;
    if (!sequence?.episodeIds || nextIndex >= sequence.episodeIds.length) {
      return;
    }
    clearAutoPlayTimers();
    setNextAutoplay({ index: nextIndex, episodeId: sequence.episodeIds[nextIndex] });
    setAutoplayCountdown(AUTOPLAY_SECONDS);
    countdownIntervalRef.current = setInterval(() => {
      setAutoplayCountdown((prev) => {
        if (prev === null) return null;
        if (prev <= 1) {
          if (countdownIntervalRef.current) {
            clearInterval(countdownIntervalRef.current);
            countdownIntervalRef.current = null;
          }
          return 0;
        }
        return prev - 1;
      });
    }, 1000);
    autoPlayTimerRef.current = setTimeout(() => {
      playEpisodeAtIndex(nextIndex);
    }, AUTOPLAY_SECONDS * 1000);
  };

  const cancelAutoPlay = () => {
    clearAutoPlayTimers();
  };

  const playNextEpisodeNow = () => {
    if (nextAutoplay) {
      playEpisodeAtIndex(nextAutoplay.index);
    }
  };

  // Initialize VOD player (native HTML5 with enhanced controls)
  const initializeVODPlayer = () => {
    if (!videoRef.current || !streamUrl) return;

    setIsLoading(true);
    setLoadError(null);
    setShowOverlay(true); // Show overlay initially

    console.log('Initializing VOD player for:', streamUrl);

    const video = videoRef.current;
    let resumeApplied = false;

    // Enhanced video element configuration for VOD
    video.preload = 'metadata';
    video.crossOrigin = 'anonymous';

    // Set up event listeners
    const handleLoadStart = () => {
      setIsLoading(true);
      handlePointerActivity();
    };
    const handleLoadedData = () => {
      setIsLoading(false);
      handlePointerActivity();
    };
    const handleLoadedMetadata = () => {
      const startOffsetSeconds = (metadata?.startOffsetMs ?? 0) / 1000;
      const videoDuration = Number.isFinite(video.duration) ? video.duration : 0;
      const resolvedDuration = metadata?.durationMs
        ? Math.max(videoDuration + startOffsetSeconds, metadata.durationMs / 1000)
        : videoDuration + startOffsetSeconds;
      if (resolvedDuration > 0) {
        setDurationSeconds(resolvedDuration);
      }
      const absolutePosition = startOffsetSeconds + video.currentTime;
      setCurrentTimeSeconds(absolutePosition);
      setScrubValueSeconds(absolutePosition);
    };

    const handleCanPlay = () => {
      setIsLoading(false);
      // Auto-play for VOD content
      video.play().catch((e) => {
        console.log('Auto-play prevented:', e);
        setLoadError('Auto-play was prevented. Click play to start.');
      });
      if (
        contentType === 'library' &&
        metadata?.resumePositionMs &&
        !metadata?.resumeHandledByServer &&
        !resumeApplied
      ) {
        try {
          video.currentTime = metadata.resumePositionMs / 1000;
          resumeApplied = true;
        } catch (error) {
          console.debug('Failed to set resume position', error);
        }
      }
      const startOffsetSeconds = (metadata?.startOffsetMs ?? 0) / 1000;
      const absolutePosition = startOffsetSeconds + video.currentTime;
      setCurrentTimeSeconds(absolutePosition);
      setScrubValueSeconds(absolutePosition);
      setIsPlaying(!video.paused);
      handlePointerActivity();
      // Start overlay timer when video is ready
      startOverlayTimer();
    };

    const handlePlay = () => {
      setIsPlaying(true);
      handlePointerActivity();
    };

    const handlePause = () => {
      setIsPlaying(false);
      handlePointerActivity();
    };
    const handleError = (e) => {
      setIsLoading(false);
      const error = e.target.error;
      let errorMessage = 'Video playback error';

      if (error) {
        switch (error.code) {
          case error.MEDIA_ERR_ABORTED:
            errorMessage = 'Video playback was aborted';
            break;
          case error.MEDIA_ERR_NETWORK:
            errorMessage = 'Network error while loading video';
            break;
          case error.MEDIA_ERR_DECODE:
            errorMessage = 'Video codec not supported by your browser';
            break;
          case error.MEDIA_ERR_SRC_NOT_SUPPORTED:
            errorMessage = 'Video format not supported by your browser';
            break;
          default:
            errorMessage = error.message || 'Unknown video error';
        }
      }

      setLoadError(errorMessage);
    };

    // Enhanced progress tracking for VOD
    const handleProgress = () => {
      if (video.buffered.length > 0) {
        const bufferedEnd = video.buffered.end(video.buffered.length - 1);
        const duration = video.duration;
        if (duration > 0) {
          const bufferedPercent = (bufferedEnd / duration) * 100;
          // You could emit this to a store for UI feedback
        }
      }
    };

    const handleTimeUpdate = () => {
      if (contentType !== 'library') return;
      const startOffsetSeconds = (metadata?.startOffsetMs ?? 0) / 1000;
      const relativePosition = Number.isFinite(video.currentTime) ? video.currentTime : 0;
      const absolutePosition = startOffsetSeconds + relativePosition;
      setCurrentTimeSeconds(absolutePosition);
      if (!isScrubbing) {
        setScrubValueSeconds(absolutePosition);
      }

      if (Number.isFinite(video.duration) && video.duration > 0) {
        const potentialDuration = Math.max(
          durationSeconds,
          startOffsetSeconds + video.duration,
          metadata?.durationMs ? metadata.durationMs / 1000 : 0
        );
        if (potentialDuration > durationSeconds) {
          setDurationSeconds(potentialDuration);
        }
      }

      const now = Date.now();
      if (now - lastProgressSentRef.current < 5000) {
        return;
      }
      lastProgressSentRef.current = now;
      sendLibraryProgress(video.currentTime, video.duration, false);
    };

    const handleEnded = () => {
      if (contentType !== 'library') return;
      if (!video.duration || Number.isNaN(video.duration)) return;
      const startOffsetSeconds = (metadata?.startOffsetMs ?? 0) / 1000;
      const totalSeconds = Math.max(durationSeconds, startOffsetSeconds + video.duration);
      setCurrentTimeSeconds(totalSeconds);
      setScrubValueSeconds(totalSeconds);
      sendLibraryProgress(video.duration, video.duration, true);
      const sequence = metadata?.playbackSequence;
      if (sequence?.episodeIds?.length) {
        const nextIndex = (sequence.currentIndex ?? -1) + 1;
        if (nextIndex < sequence.episodeIds.length) {
          startAutoPlayCountdown(nextIndex);
        }
      }
    };

    // Add event listeners
    video.addEventListener('loadstart', handleLoadStart);
    video.addEventListener('loadedmetadata', handleLoadedMetadata);
    video.addEventListener('loadeddata', handleLoadedData);
    video.addEventListener('canplay', handleCanPlay);
    video.addEventListener('play', handlePlay);
    video.addEventListener('pause', handlePause);
    video.addEventListener('error', handleError);
    video.addEventListener('progress', handleProgress);
    video.addEventListener('timeupdate', handleTimeUpdate);
    video.addEventListener('ended', handleEnded);

    // Set the source
    video.src = streamUrl;
    video.load();

    // Store cleanup function
    playerRef.current = {
      destroy: () => {
        video.removeEventListener('loadstart', handleLoadStart);
        video.removeEventListener('loadedmetadata', handleLoadedMetadata);
        video.removeEventListener('loadeddata', handleLoadedData);
        video.removeEventListener('canplay', handleCanPlay);
        video.removeEventListener('play', handlePlay);
        video.removeEventListener('pause', handlePause);
        video.removeEventListener('error', handleError);
        video.removeEventListener('progress', handleProgress);
        video.removeEventListener('timeupdate', handleTimeUpdate);
        video.removeEventListener('ended', handleEnded);
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

          let errorMessage = `Error: ${errorType}`;

          if (errorType === 'MediaError') {
            const errorString = errorDetail?.toLowerCase() || '';

            if (
              errorString.includes('audio') ||
              errorString.includes('ac3') ||
              errorString.includes('ac-3')
            ) {
              errorMessage =
                'Audio codec not supported by your browser. Try Chrome or Edge for better audio codec support.';
            } else if (
              errorString.includes('video') ||
              errorString.includes('h264') ||
              errorString.includes('h.264')
            ) {
              errorMessage =
                'Video codec not supported by your browser. Try Chrome or Edge for better video codec support.';
            } else if (errorString.includes('mse')) {
              errorMessage =
                "Your browser doesn't support the codecs used in this stream. Try Chrome or Edge for better compatibility.";
            } else {
              errorMessage =
                'Media codec not supported by your browser. This may be due to unsupported audio (AC3) or video codecs. Try Chrome or Edge.';
            }
          } else if (errorDetail) {
            errorMessage += ` - ${errorDetail}`;
          }

          setLoadError(errorMessage);
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
    if (contentType === 'vod' || contentType === 'library') {
      initializeVODPlayer();
    } else {
      initializeLivePlayer();
    }

    // Cleanup when component unmounts or streamUrl changes
    return () => {
      safeDestroyPlayer();
    };
  }, [isVisible, streamUrl, contentType]);


  useEffect(() => {
    if (isVisible) {
      setShowControls(true);
      handlePointerActivity();
    } else {
      clearControlsTimeout();
    }
  }, [isVisible]);
  useEffect(() => {
    serverSeekInProgressRef.current = false;
  }, [streamUrl]);

  useEffect(() => {
    lastServerSeekAbsoluteRef.current = (metadata?.startOffsetMs ?? 0) / 1000;
  }, [metadata?.startOffsetMs]);

  useEffect(() => {
    clearAutoPlayTimers();
  }, [metadata?.mediaItemId]);

  // Modified hideVideo handler to clean up player first
  const handleClose = (e) => {
    if (e) {
      e.stopPropagation();
      e.preventDefault();
    }
    if (
      typeof document !== 'undefined' &&
      (document.fullscreenElement === videoContainerRef.current ||
        document.webkitFullscreenElement === videoContainerRef.current ||
        document.mozFullScreenElement === videoContainerRef.current ||
        document.msFullscreenElement === videoContainerRef.current)
    ) {
      const exit =
        document.exitFullscreen ||
        document.webkitExitFullscreen ||
        document.mozCancelFullScreen ||
        document.msExitFullscreen;
      exit?.call(document).catch(() => {});
    }
    setShowVolumeControl(false);
    safeDestroyPlayer();
    setTimeout(() => {
      hideVideo();
    }, 50);
  };

  // If the floating video is hidden or no URL is selected, do not render
  if (!isVisible || !streamUrl) {
    return null;
  }

  const baseDurationSeconds =
    Number.isFinite(durationSeconds) && durationSeconds > 0
      ? durationSeconds
      : metadata?.durationMs
      ? metadata.durationMs / 1000
      : 0;
  const sliderMaxValue = Number.isFinite(baseDurationSeconds) && baseDurationSeconds > 0
    ? baseDurationSeconds
    : Math.max(scrubValueSeconds, currentTimeSeconds + 1);
  const sliderValue = Math.min(
    Math.max(isScrubbing ? scrubValueSeconds : currentTimeSeconds, 0),
    Math.max(sliderMaxValue, 1)
  );
  const formattedDurationLabel =
    Number.isFinite(baseDurationSeconds) && baseDurationSeconds > 0
      ? formatTime(sliderMaxValue)
      : '--:--';
  const formattedCurrentTime = sliderMaxValue > 0 ? formatTime(sliderValue) : '--:--';
  const showPlaybackControls = contentType !== 'live';
  const volumeIcon = isMuted || volume === 0 ? <VolumeX size={16} /> : <Volume2 size={16} />;
  const fullscreenIcon = isFullscreen ? <Minimize size={16} /> : <Maximize size={16} />;

  const containerStyle = isFullscreen
    ? {
        position: 'fixed',
        top: 0,
        left: 0,
        width: '100vw',
        height: '100vh',
        zIndex: 9999,
        backgroundColor: '#000',
        borderRadius: 0,
        overflow: 'hidden',
        boxShadow: 'none',
      }
    : {
        position: 'fixed',
        bottom: '20px',
        right: '20px',
        width: '320px',
        zIndex: 9999,
        backgroundColor: '#333',
        borderRadius: '8px',
        overflow: 'hidden',
        boxShadow: '0 2px 10px rgba(0,0,0,0.7)',
      };

  const videoStyles = {
    width: '100%',
    height: isFullscreen ? '100%' : '180px',
    backgroundColor: '#000',
    objectFit: 'contain',
  };

  return (
    <Draggable nodeRef={videoContainerRef} disabled={isFullscreen}>
      <div
        ref={videoContainerRef}
        style={containerStyle}
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
          onMouseMove={handlePointerActivity}
          onTouchStart={handlePointerActivity}
          onMouseEnter={() => {
            if (contentType !== 'live' && !isLoading) {
              setShowOverlay(true);
              if (overlayTimeoutRef.current) {
                clearTimeout(overlayTimeoutRef.current);
              }
            }
          }}
          onMouseLeave={() => {
            if (contentType !== 'live' && !isLoading) {
              startOverlayTimer();
            }
          }}
        >
          {/* Enhanced video element with better controls for VOD */}
          <video
            ref={videoRef}
            style={videoStyles}
            playsInline
            controls={contentType === 'live'}
            controlsList={contentType === 'live' ? undefined : 'nodownload'}
            onClick={togglePlayback}
            // Add poster for VOD if available
            {...(contentType !== 'live' && {
              poster: metadata?.logo?.url, // Use poster if available
            })}
          />

          {/* VOD title overlay when not loading - auto-hides after 4 seconds */}
          {!isLoading && metadata && contentType !== 'live' && showOverlay && (
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
                {metadata.name || metadata.title || metadata.mediaTitle}
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

          {showPlaybackControls && (
            <Box
              style={{
                position: 'absolute',
                bottom: 0,
                left: 0,
                right: 0,
                padding: '10px 14px',
                background: 'linear-gradient(transparent, rgba(0,0,0,0.85))',
                transition: 'opacity 0.2s ease-in-out',
                opacity: showControls ? 1 : 0,
                pointerEvents:
                  showControls && !serverSeekInProgressRef.current && !isLoading
                    ? 'auto'
                    : 'none',
                zIndex: 4,
              }}
            >
              <Group gap="sm" align="center" justify="space-between">
                <ActionIcon
                  variant="filled"
                  color="gray"
                  radius="xl"
                  size="lg"
                  onClick={togglePlayback}
                  aria-label={isPlaying ? 'Pause' : 'Play'}
                  disabled={serverSeekInProgressRef.current || isLoading}
                >
                  {isPlaying ? <Pause size={16} /> : <Play size={16} />}
                </ActionIcon>
                <Text size="xs" c="gray.1" style={{ width: 44 }}>{formattedCurrentTime}</Text>
                <Slider
                  style={{ flexGrow: 1 }}
                  min={0}
                  max={Math.max(sliderMaxValue, 1)}
                  step={0.1}
                  value={Math.min(Math.max(sliderValue, 0), Math.max(sliderMaxValue, 1))}
                  onChange={handleScrubChange}
                  onChangeEnd={handleScrubEnd}
                  size="sm"
                  label={null}
                  aria-label="Seek"
                  disabled={sliderMaxValue <= 0 || serverSeekInProgressRef.current || isLoading}
                  styles={{
                    track: { backgroundColor: 'rgba(255,255,255,0.2)' },
                    bar: { backgroundColor: '#1abc9c' },
                    thumb: { borderColor: '#1abc9c', backgroundColor: '#1abc9c' },
                  }}
                />
                <Text size="xs" c="gray.1" style={{ width: 44, textAlign: 'right' }}>{formattedDurationLabel}</Text>
                <Group gap="xs" align="center">
                  <Group gap={6} align="center">
                    <ActionIcon
                      variant="subtle"
                      color="gray"
                      radius="xl"
                      size="lg"
                      onClick={handleVolumeButtonClick}
                      onMouseDown={(e) => e.stopPropagation()}
                      onTouchStart={(e) => e.stopPropagation()}
                      aria-label="Adjust volume"
                    >
                      {volumeIcon}
                    </ActionIcon>
                    {showVolumeControl && (
                      <Slider
                        min={0}
                        max={100}
                        step={1}
                        value={Math.round(volume * 100)}
                        onChange={(value) => handleVolumeSliderChange(value / 100)}
                        onChangeEnd={(value) => handleVolumeSliderChange(value / 100)}
                        style={{ width: 100 }}
                        size="sm"
                        label={null}
                        onMouseDown={(e) => e.stopPropagation()}
                        onTouchStart={(e) => e.stopPropagation()}
                        aria-label="Volume"
                        styles={{
                          track: { backgroundColor: 'rgba(255,255,255,0.2)' },
                          bar: { backgroundColor: '#1abc9c' },
                          thumb: { borderColor: '#1abc9c', backgroundColor: '#1abc9c' },
                        }}
                      />
                    )}
                  </Group>
                  <ActionIcon
                    variant="subtle"
                    color="gray"
                    radius="xl"
                    size="lg"
                    onClick={toggleFullscreen}
                    onMouseDown={(e) => e.stopPropagation()}
                    onTouchStart={(e) => e.stopPropagation()}
                    aria-label={isFullscreen ? 'Exit fullscreen' : 'Enter fullscreen'}
                  >
                    {fullscreenIcon}
                  </ActionIcon>
                </Group>
              </Group>
            </Box>
          )}

          {nextAutoplay && autoplayCountdown !== null && (
            <Box
              style={{
                position: 'absolute',
                bottom: showPlaybackControls ? 70 : 12,
                left: 12,
                backgroundColor: 'rgba(15, 23, 42, 0.85)',
                padding: '10px 12px',
                borderRadius: 12,
                color: 'white',
                width: 'calc(100% - 70px)',
                maxWidth: 260,
                zIndex: 6,
              }}
              onClick={(e) => e.stopPropagation()}
            >
              <Text size="xs" fw={500} mb={6}>
                Next episode starts in {autoplayCountdown}s
              </Text>
              <Progress
                value={Math.min(
                  100,
                  Math.max(
                    0,
                    ((AUTOPLAY_SECONDS - autoplayCountdown) / AUTOPLAY_SECONDS) * 100
                  )
                )}
                size="sm"
                radius="md"
                color="cyan"
              />
              <Group gap="xs" mt={6} justify="flex-end">
                <Button
                  size="xs"
                  variant="subtle"
                  color="gray"
                  onClick={(e) => {
                    e.stopPropagation();
                    cancelAutoPlay();
                  }}
                >
                  Cancel
                </Button>
                <Button
                  size="xs"
                  variant="filled"
                  color="cyan"
                  leftSection={<Play size={14} />}
                  onClick={(e) => {
                    e.stopPropagation();
                    playNextEpisodeNow();
                  }}
                >
                  Play now
                </Button>
              </Group>
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
      </div>
    </Draggable>
  );
}
