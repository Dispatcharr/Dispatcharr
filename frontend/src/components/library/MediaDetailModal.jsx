import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Alert,
  ActionIcon,
  Avatar,
  Badge,
  Box,
  Button,
  Divider,
  Group,
  Image,
  Loader,
  Modal,
  ScrollArea,
  Select,
  Stack,
  Text,
  Title,
  rem,
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import {
  CheckCircle2,
  AlertCircle,
  Clock,
  DownloadCloud,
  Info,
  PlayCircle,
  RefreshCcw,
  Undo2,
  Trash2,
  Pencil,
  XCircle,
} from 'lucide-react';

import API from '../../api';
import useMediaLibraryStore from '../../store/mediaLibrary';
import useVideoStore from '../../store/useVideoStore';
import useAuthStore from '../../store/auth';
import useSettingsStore from '../../store/settings';
import { USER_LEVELS } from '../../constants';
import MediaEditModal from './MediaEditModal';

// ---- quick tuning knobs ----
const CAST_TILE_WIDTH = 88;     // was 116
const CAST_TILE_HEIGHT = 122;   // was 160
const CAST_AVATAR_SIZE = 64;    // was 80
const CAST_GAP = 6;             // was "md" (~16)
const CAST_TILE_SPACING = 1;
const STACK_TIGHT = 4;          // was 6
const SECTION_STACK = 12;       // was larger in some places
const DETAIL_SCROLL_HEIGHT = '82vh';
const DETAIL_POSTER_MAX_HEIGHT = '72vh';
// ----------------------------

const runtimeLabel = (runtimeMs) => {
  if (!runtimeMs) return null;
  const totalSeconds = Math.round(runtimeMs / 1000);
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  if (hours) return `${hours}h ${minutes}m`;
  return `${minutes}m`;
};

const resolveArtworkUrl = (url, envMode) => {
  if (!url) return url;
  if (envMode === 'dev' && url.startsWith('/')) {
    return `${window.location.protocol}//${window.location.hostname}:5656${url}`;
  }
  return url;
};

const getEmbedUrl = (url) => {
  if (!url) return '';
  const match = url.match(
    /(?:youtube\.com\/watch\?v=|youtu\.be\/|video_id=)([\w-]+)/
  );
  const videoId = match ? match[1] : url;
  return `https://www.youtube.com/embed/${videoId}`;
};

const MediaDetailModal = ({ opened, onClose }) => {
  const activeItem = useMediaLibraryStore((s) => s.activeItem);
  const activeItemLoading = useMediaLibraryStore((s) => s.activeItemLoading);
  const activeItemError = useMediaLibraryStore((s) => s.activeItemError);
  const activeProgress = useMediaLibraryStore((s) => s.activeProgress);
  const resumePrompt = useMediaLibraryStore((s) => s.resumePrompt);
  const requestResume = useMediaLibraryStore((s) => s.requestResume);
  const clearResumePrompt = useMediaLibraryStore((s) => s.clearResumePrompt);
  const setActiveProgress = useMediaLibraryStore((s) => s.setActiveProgress);
  const pollItem = useMediaLibraryStore((s) => s.pollItem);
  const showVideo = useVideoStore((s) => s.showVideo);
  const userLevel = useAuthStore((s) => s.user?.user_level ?? 0);
  const env_mode = useSettingsStore((s) => s.environment.env_mode);
  const canEditMetadata = userLevel >= USER_LEVELS.ADMIN;

  const [startingPlayback, setStartingPlayback] = useState(false);
  const [resumeModalOpen, setResumeModalOpen] = useState(false);
  const [resumeMode, setResumeMode] = useState('start');
  const [editModalOpen, setEditModalOpen] = useState(false);
  const [trailerModalOpen, setTrailerModalOpen] = useState(false);
  const [trailerUrl, setTrailerUrl] = useState('');

  const [episodes, setEpisodes] = useState([]);
  const [episodesLoading, setEpisodesLoading] = useState(false);
  const [episodePlayLoadingId, setEpisodePlayLoadingId] = useState(null);
  const [episodeActionLoading, setEpisodeActionLoading] = useState({});
  const [itemActionLoading, setItemActionLoading] = useState(null);
  const [selectedSeason, setSelectedSeason] = useState(null);
  const [expandedEpisodeIds, setExpandedEpisodeIds] = useState(() => new Set());
  const [seasonManuallySelected, setSeasonManuallySelected] = useState(false);
  const lastResumeSeasonRef = useRef(null);

  const setEpisodeLoading = useCallback((episodeId, action) => {
    setEpisodeActionLoading((prev) => ({ ...prev, [episodeId]: action }));
  }, []);

  const clearEpisodeLoading = useCallback((episodeId) => {
    setEpisodeActionLoading((prev) => {
      const updated = { ...prev };
      delete updated[episodeId];
      return updated;
    });
  }, []);

  const loadEpisodes = useCallback(async () => {
    if (!activeItem || activeItem.item_type !== 'show') {
      setEpisodes([]);
      setEpisodesLoading(false);
      return;
    }
    setEpisodesLoading(true);
    try {
      const results = await API.getMediaItemEpisodes(activeItem.id);
      setEpisodes(Array.isArray(results) ? results : []);
      setExpandedEpisodeIds(new Set());
    } catch (error) {
      console.error('Failed to load episodes for show', error);
      notifications.show({
        title: 'Episodes unavailable',
        message: 'Unable to load episodes for this series right now.',
        color: 'red',
      });
      setEpisodes([]);
    } finally {
      setEpisodesLoading(false);
    }
  }, [activeItem]);

  const refreshActiveItem = useCallback(async () => {
    if (!activeItem) return null;
    return useMediaLibraryStore.getState().openItem(activeItem.id);
  }, [activeItem]);

  const handleEditSaved = useCallback(async () => {
    await refreshActiveItem();
  }, [refreshActiveItem]);

  const orderedEpisodes = useMemo(() => {
    if (!episodes || episodes.length === 0) return [];
    return [...episodes].sort((a, b) => {
      const seasonA = a.season_number ?? 0;
      const seasonB = b.season_number ?? 0;
      if (seasonA !== seasonB) return seasonA - seasonB;
      const episodeA = a.episode_number ?? 0;
      const episodeB = b.episode_number ?? 0;
      if (episodeA !== episodeB) return episodeA - episodeB;
      return (a.sort_title || '').localeCompare(b.sort_title || '');
    });
  }, [episodes]);

  const showWatchSummary = activeItem?.watch_summary || null;
  const itemWatchSummary =
    activeItem?.item_type === 'show' ? showWatchSummary : activeItem?.watch_summary || null;
  const itemStatus = itemWatchSummary?.status || 'unwatched';
  const itemIsWatched = itemStatus === 'watched';
  const itemInProgress = itemStatus === 'in_progress';

  useEffect(() => {
    setItemActionLoading(null);
  }, [activeItem?.id]);

  const handleMarkItemWatched = useCallback(async () => {
    if (!activeItem) return;
    setItemActionLoading('watch');
    try {
      if (activeItem.item_type === 'show') {
        const response = await API.markSeriesWatched(activeItem.id);
        if (response?.item) {
          useMediaLibraryStore.getState().upsertItems([response.item]);
        }
      } else {
        await API.markMediaItemWatched(activeItem.id);
      }
      await refreshActiveItem();
      notifications.show({
        title: 'Marked as watched',
        message: `${activeItem.title} marked as watched.`,
        color: 'green',
      });
    } catch (error) {
      console.error('Failed to mark media watched', error);
      notifications.show({
        title: 'Action failed',
        message: 'Unable to mark this item as watched right now.',
        color: 'red',
      });
    } finally {
      setItemActionLoading(null);
    }
  }, [activeItem, refreshActiveItem]);

  const handleClearItemProgress = useCallback(async () => {
    if (!activeItem) return;
    setItemActionLoading('clear');
    try {
      if (activeItem.item_type === 'show') {
        const response = await API.markSeriesUnwatched(activeItem.id);
        if (response?.item) {
          useMediaLibraryStore.getState().upsertItems([response.item]);
        }
      } else {
        await API.clearMediaItemProgress(activeItem.id);
      }
      await refreshActiveItem();
      notifications.show({
        title: 'Progress cleared',
        message:
          activeItem.item_type === 'show'
            ? 'Watch history cleared for this series.'
            : 'This title has been removed from Continue Watching.',
        color: 'blue',
      });
    } catch (error) {
      console.error('Failed to clear media progress', error);
      notifications.show({
        title: 'Action failed',
        message: 'Unable to update watch progress right now.',
        color: 'red',
      });
    } finally {
      setItemActionLoading(null);
    }
  }, [activeItem, refreshActiveItem]);

  const playbackPlan = useMemo(() => {
    if (!activeItem || activeItem.item_type !== 'show') return null;

    const sorted = orderedEpisodes;
    if (!sorted || sorted.length === 0) {
      return { sorted: [], resumeEpisode: null, nextEpisode: null };
    }

    const resumeId = showWatchSummary?.resume_episode_id;
    const nextId = showWatchSummary?.next_episode_id;
    let resumeEpisode = sorted.find((ep) => ep.id === resumeId) || null;
    let nextEpisode = sorted.find((ep) => ep.id === nextId) || null;

    if (!resumeEpisode) {
      resumeEpisode = sorted.find((ep) => ep.watch_summary?.status === 'in_progress') || null;
    }
    if (!resumeEpisode) {
      resumeEpisode = sorted.find((ep) => ep.watch_summary?.status !== 'watched') || sorted[0];
    }
    if (!nextEpisode && resumeEpisode) {
      const currentIndex = sorted.findIndex((ep) => ep.id === resumeEpisode.id);
      if (currentIndex >= 0 && currentIndex + 1 < sorted.length) {
        nextEpisode = sorted[currentIndex + 1];
      }
    }
    return { sorted, resumeEpisode, nextEpisode };
  }, [activeItem, orderedEpisodes, showWatchSummary]);

  const metadataPending = useMemo(() => {
    if (!activeItem) return false;
    if (activeItem.metadataPending) return true;
    if (activeItemError === 'metadata_pending') return true;
    if (activeItem.metadata_last_synced_at) return false;
    const hasDescriptiveDetails =
      Boolean(activeItem.synopsis) ||
      Boolean(activeItem.poster_url) ||
      (Array.isArray(activeItem.genres) && activeItem.genres.length > 0);
    return !hasDescriptiveDetails;
  }, [activeItem, activeItemError]);

  const canResume = useMemo(() => {
    if (!activeProgress || !activeProgress.position_ms || !activeProgress.duration_ms) return false;
    const remaining = activeProgress.duration_ms - activeProgress.position_ms;
    return remaining > activeProgress.duration_ms * 0.04;
  }, [activeProgress]);

  const activeProgressId = activeProgress?.id;

  useEffect(() => {
    if (canResume && activeProgressId && !resumePrompt) {
      requestResume(activeProgressId);
    }
  }, [canResume, activeProgressId, resumePrompt, requestResume]);

  useEffect(() => {
    if (!opened) {
      setEpisodes([]);
      setEpisodesLoading(false);
      setEpisodePlayLoadingId(null);
      setEditModalOpen(false);
      setTrailerModalOpen(false);
      setTrailerUrl('');
      return;
    }
    if (activeItem?.item_type === 'show') {
      void loadEpisodes();
    } else {
      setEpisodes([]);
    }
  }, [opened, activeItem?.id, activeItem?.item_type, loadEpisodes]);

  const castPeople = useMemo(() => {
    if (!activeItem?.cast) return [];
    return activeItem.cast
      .map((entry, index) => {
        if (!entry) return null;
        if (typeof entry === 'string') {
          return { key: `${entry}-${index}`, name: entry, role: null, profile: null };
        }
        const name = entry.name || entry.character || entry.job;
        if (!name) return null;
        return {
          key: `${name}-${index}`,
          name,
          role: entry.character || entry.role || entry.job || null,
          profile: entry.profile_url || entry.profile || null,
        };
      })
      .filter(Boolean);
  }, [activeItem]);

  const crewPeople = useMemo(() => {
    if (!activeItem?.crew) return [];
    return activeItem.crew
      .map((entry, index) => {
        if (!entry) return null;
        if (typeof entry === 'string') {
          return { key: `${entry}-${index}`, name: entry, role: null, profile: null };
        }
        const name = entry.name || entry.job || entry.department;
        if (!name) return null;
        return {
          key: `${name}-${index}`,
          name,
          role: entry.job || entry.department || entry.role || null,
          profile: entry.profile_url || entry.profile || null,
        };
      })
      .filter(Boolean);
  }, [activeItem]);
  const hasCredits = castPeople.length > 0 || crewPeople.length > 0;

  const handleStartPlayback = async (mode = 'start') => {
    if (!activeItem) return;
    const fileId = activeItem.files?.[0]?.id;
    if (!fileId) {
      notifications.show({
        title: 'Playback unavailable',
        message: 'No media file is linked to this item yet.',
        color: 'red',
      });
      return;
    }
    setResumeMode(mode);
    setStartingPlayback(true);
    try {
      const resumePositionMs =
        mode === 'resume'
          ? resumePrompt?.position_ms || activeProgress?.position_ms || 0
          : 0;

      const streamInfo = await API.streamMediaItem(activeItem.id, {
        fileId,
        startMs: resumePositionMs,
      });
      const playbackUrl = streamInfo?.url || streamInfo?.stream_url;
      if (!playbackUrl) {
        notifications.show({
          title: 'Playback error',
          message: 'Streaming endpoint did not return a playable URL.',
          color: 'red',
        });
        return;
      }

      const startOffsetMs = streamInfo?.start_offset_ms ?? 0;
      const resumeHandledByServer = startOffsetMs > 0;
      const primaryFile = activeItem.files?.[0];
      const requiresTranscode = Boolean(streamInfo?.requires_transcode);
      const transcodeStatus = streamInfo?.transcode_status ?? null;

      showVideo(playbackUrl, 'library', {
        mediaItemId: activeItem.id,
        mediaTitle: activeItem.title,
        name: activeItem.title,
        year: activeItem.release_year,
        logo: posterUrl ? { url: posterUrl } : undefined,
        progressId: activeProgress?.id,
        resumePositionMs,
        resumeHandledByServer,
        startOffsetMs,
        requiresTranscode,
        transcodeStatus,
        durationMs:
          streamInfo?.duration_ms ??
          resumePrompt?.duration_ms ??
          activeProgress?.duration_ms ??
          activeItem.runtime_ms ??
          primaryFile?.duration_ms ??
          null,
        fileId,
      });

      clearResumePrompt();
      setResumeModalOpen(false);
      onClose();
    } catch (error) {
      console.error('Failed to start playback', error);
      notifications.show({
        title: 'Playback error',
        message: 'Unable to start playback. Check server logs for details.',
        color: 'red',
      });
    } finally {
      setStartingPlayback(false);
    }
  };

  const primaryButtonLabel = useMemo(() => {
    if (!activeItem) return 'Play';
    if (activeItem.item_type === 'show') {
      if (showWatchSummary?.status === 'in_progress') return 'Continue Watching';
      if (showWatchSummary?.status === 'watched') return 'Watch Again';
      return 'Play';
    }
    if (canResume && (resumePrompt || activeProgress)) return 'Continue Watching';
    return 'Play';
  }, [activeItem, showWatchSummary, canResume, resumePrompt, activeProgress]);

  const handlePrimaryAction = () => {
    if (!activeItem) return;
    if (activeItem.item_type === 'show') {
      const candidateSequence =
        playbackPlan?.sorted?.length ? playbackPlan.sorted : orderedEpisodes;
      const targetEpisode =
        playbackPlan?.resumeEpisode ||
        playbackPlan?.nextEpisode ||
        (candidateSequence?.length ? candidateSequence[0] : null);

      if (targetEpisode) {
        const startIndex = candidateSequence?.findIndex((ep) => ep.id === targetEpisode.id);
        void handlePlayEpisode(targetEpisode, {
          sequence: candidateSequence,
          startIndex: startIndex ?? null,
        });
        return;
      }

      const fallbackEpisodeId =
        showWatchSummary?.resume_episode_id || showWatchSummary?.next_episode_id || null;
      if (fallbackEpisodeId) {
        void handlePlayEpisode({ id: fallbackEpisodeId }, { sequence: candidateSequence });
        return;
      }

      notifications.show({
        title: 'No episodes available',
        message: 'This series does not have any episodes to play yet.',
        color: 'yellow',
      });
      return;
    }
    if (canResume && (resumePrompt || activeProgress)) {
      setResumeMode('resume');
      setResumeModalOpen(true);
    } else {
      handleStartPlayback('start');
    }
  };

  const handleRefreshMetadata = useCallback(async () => {
    if (!activeItem) return;
    await API.refreshMediaItemMetadata(activeItem.id);
    pollItem(activeItem.id);
  }, [activeItem, pollItem]);

  const handlePlayEpisode = async (
    episode,
    { sequence = orderedEpisodes, startIndex = null } = {}
  ) => {
    if (!episode) return;
    setEpisodePlayLoadingId(episode.id);
    try {
      const episodeDetail = await API.getMediaItem(episode.id, {
        suppressErrorNotification: true,
      });
      const episodeFileId = episodeDetail.files?.[0]?.id;
      if (!episodeFileId) {
        notifications.show({
          title: 'Playback unavailable',
          message: 'No media file is linked to this episode yet.',
          color: 'red',
        });
        return;
      }

      const baseSequence =
        Array.isArray(sequence) && sequence.length ? sequence : orderedEpisodes;
      const effectiveSequence =
        baseSequence && baseSequence.length ? baseSequence : [episodeDetail];
      const episodeIds = effectiveSequence.map((ep) => ep.id);
      const computedIndex =
        startIndex ?? episodeIds.findIndex((id) => id === episodeDetail.id);

      const playbackSequence =
        episodeIds.length > 1
          ? { episodeIds, currentIndex: computedIndex >= 0 ? computedIndex : 0 }
          : null;

      const episodeProgress = episodeDetail.watch_progress;
      const episodeSummary = episodeDetail.watch_summary;
      const resumePositionMs =
        episodeSummary?.status === 'in_progress'
          ? episodeSummary.position_ms || 0
          : episodeProgress?.position_ms || 0;

      const streamInfo = await API.streamMediaItem(episodeDetail.id, {
        fileId: episodeFileId,
        startMs: resumePositionMs,
      });
      const playbackUrl = streamInfo?.url || streamInfo?.stream_url;
      if (!playbackUrl) {
        notifications.show({
          title: 'Playback error',
          message: 'Streaming endpoint did not return a playable URL.',
          color: 'red',
        });
        return;
      }

      const resumeHandledByServer = Boolean(streamInfo?.start_offset_ms);

      const durationMs =
        streamInfo?.duration_ms ??
        episodeSummary?.duration_ms ??
        episodeProgress?.duration_ms ??
        episodeDetail.runtime_ms ??
        episodeDetail.files?.[0]?.duration_ms ??
        null;
      const episodePosterUrl = resolveArtworkUrl(episodeDetail.poster_url, env_mode);

      showVideo(playbackUrl, 'library', {
        mediaItemId: episodeDetail.id,
        mediaTitle: episodeDetail.title,
        showId: activeItem?.id,
        showTitle: activeItem?.title,
        name: episodeDetail.title,
        year: episodeDetail.release_year,
        logo:
          episodePosterUrl
            ? { url: episodePosterUrl }
            : posterUrl
            ? { url: posterUrl }
            : undefined,
        showPoster: posterUrl,
        progressId: episodeProgress?.id,
        resumePositionMs,
        resumeHandledByServer,
        durationMs,
        fileId: episodeFileId,
        playbackSequence,
      });
    } catch (error) {
      console.error('Failed to play episode', error);
      notifications.show({
        title: 'Playback error',
        message: 'Unable to start playback for this episode.',
        color: 'red',
      });
    } finally {
      setEpisodePlayLoadingId(null);
    }
  };

  const episodesBySeason = useMemo(() => {
    const grouped = new Map();
    orderedEpisodes.forEach((episode) => {
      const season = episode.season_number || 1;
      if (!grouped.has(season)) grouped.set(season, []);
      grouped.get(season).push(episode);
    });
    return grouped;
  }, [orderedEpisodes]);

  const sortedSeasons = useMemo(
    () => Array.from(episodesBySeason.keys()).sort((a, b) => a - b),
    [episodesBySeason]
  );

  const visibleEpisodes = useMemo(() => {
    if (!selectedSeason) return [];
    return episodesBySeason.get(selectedSeason) || [];
  }, [episodesBySeason, selectedSeason]);

  const formatEpisodeCode = (episode) => {
    const season = episode.season_number || 0;
    const ep = episode.episode_number || 0;
    if (!season && !ep) return '';
    if (!season) return `E${ep.toString().padStart(2, '0')}`;
    if (!ep) return `S${season.toString().padStart(2, '0')}`;
    return `S${season.toString().padStart(2, '0')}E${ep.toString().padStart(2, '0')}`;
  };

  const handleEpisodeMarkWatched = async (episode) => {
    if (!episode) return;
    setEpisodeLoading(episode.id, 'watch');
    try {
      await API.markMediaItemWatched(episode.id);
      await refreshActiveItem();
      await loadEpisodes();
      notifications.show({
        title: 'Episode updated',
        message: `${episode.title} marked as watched.`,
        color: 'green',
      });
    } catch (error) {
      console.error('Failed to mark episode watched', error);
    } finally {
      clearEpisodeLoading(episode.id);
    }
  };

  const handleEpisodeMarkUnwatched = async (episode) => {
    if (!episode) return;
    setEpisodeLoading(episode.id, 'unwatch');
    try {
      await API.clearMediaItemProgress(episode.id);
      await refreshActiveItem();
      await loadEpisodes();
      notifications.show({
        title: 'Episode updated',
        message: `${episode.title} marked as unwatched.`,
        color: 'blue',
      });
    } catch (error) {
      console.error('Failed to clear episode progress', error);
    } finally {
      clearEpisodeLoading(episode.id);
    }
  };

  const handleEpisodeDelete = async (episode) => {
    if (!episode) return;
    if (!window.confirm(`Delete episode "${episode.title}"?`)) return;
    setEpisodeLoading(episode.id, 'delete');
    try {
      await API.deleteMediaItem(episode.id);
      useMediaLibraryStore.getState().removeItems(episode.id);
      await refreshActiveItem();
      await loadEpisodes();
      notifications.show({
        title: 'Episode deleted',
        message: `${episode.title} removed from the library.`,
        color: 'red',
      });
    } catch (error) {
      console.error('Failed to delete episode', error);
    } finally {
      clearEpisodeLoading(episode.id);
    }
  };

  const toggleEpisodeExpanded = useCallback((episodeId) => {
    setExpandedEpisodeIds((prev) => {
      const next = new Set(prev);
      if (next.has(episodeId)) {
        next.delete(episodeId);
      } else {
        next.add(episodeId);
      }
      return next;
    });
  }, []);

  const handleEpisodeCardClick = useCallback(
    (episodeId, event) => {
      if (!episodeId) return;
      if (event?.target?.closest('button')) return;
      toggleEpisodeExpanded(episodeId);
    },
    [toggleEpisodeExpanded]
  );

  const handleEpisodeCardKeyDown = useCallback(
    (episodeId, event) => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        toggleEpisodeExpanded(episodeId);
      }
    },
    [toggleEpisodeExpanded]
  );

  const files = activeItem?.files || [];
  const posterUrl = useMemo(
    () => resolveArtworkUrl(activeItem?.poster_url, env_mode),
    [activeItem?.poster_url, env_mode]
  );
  const backdropUrl = useMemo(() => {
    const fallback = activeItem?.id
      ? `/api/media-library/items/${activeItem.id}/artwork/backdrop/`
      : '';
    return resolveArtworkUrl(activeItem?.backdrop_url || fallback, env_mode);
  }, [activeItem?.backdrop_url, activeItem?.id, env_mode]);
  const modalBackgroundStyle = useMemo(() => {
    if (!backdropUrl) {
      return { backgroundColor: '#1f1f1f' };
    }
    return {
      backgroundImage: `linear-gradient(180deg, rgba(8, 10, 12, 0.92), rgba(8, 10, 12, 0.86) 45%, rgba(8, 10, 12, 0.92)), url('${backdropUrl}')`,
      backgroundSize: 'cover',
      backgroundPosition: 'center',
      backgroundRepeat: 'no-repeat',
    };
  }, [backdropUrl]);

  const seasonOptions = useMemo(
    () =>
      sortedSeasons.map((season) => ({
        value: String(season),
        label: `Season ${season}`,
      })),
    [sortedSeasons]
  );

  const resumeSeasonNumber = playbackPlan?.resumeEpisode?.season_number ?? null;

  useEffect(() => {
    if (!sortedSeasons.length) {
      if (selectedSeason !== null) {
        setSelectedSeason(null);
      }
      lastResumeSeasonRef.current = null;
      setSeasonManuallySelected(false);
      return;
    }

    if (resumeSeasonNumber && sortedSeasons.includes(resumeSeasonNumber)) {
      const resumeChanged = lastResumeSeasonRef.current !== resumeSeasonNumber;
      if (!seasonManuallySelected || resumeChanged) {
        lastResumeSeasonRef.current = resumeSeasonNumber;
        setSelectedSeason(resumeSeasonNumber);
        setSeasonManuallySelected(false);
        return;
      }
    } else {
      lastResumeSeasonRef.current = null;
    }

    if (selectedSeason === null || !sortedSeasons.includes(selectedSeason)) {
      const fallback = sortedSeasons[0];
      setSelectedSeason(fallback);
      setSeasonManuallySelected(false);
    }
  }, [sortedSeasons, resumeSeasonNumber, seasonManuallySelected, selectedSeason]);

  useEffect(() => {
    setExpandedEpisodeIds(new Set());
  }, [selectedSeason]);

  return (
    <>
      <Modal
        opened={opened}
        onClose={() => {
          clearResumePrompt();
          onClose();
        }}
        size="xl"
        overlayProps={{ backgroundOpacity: 0.55, blur: 4 }}
        padding="md"
        styles={{
          content: {
            ...modalBackgroundStyle,
          },
          header: {
            background: 'transparent',
          },
          body: {
            background: 'transparent',
          },
        }}
        title={
          <Group justify="space-between" align="center" gap="xs">
            <Text fw={600} truncate>
              {activeItem ? activeItem.title : 'Media details'}
            </Text>
            {canEditMetadata && activeItem && (
              <ActionIcon
                variant="subtle"
                color="blue"
                title="Edit metadata"
                onClick={() => setEditModalOpen(true)}
              >
                <Pencil size={16} />
              </ActionIcon>
            )}
          </Group>
        }
      >
        {activeItemLoading ? (
          <Group justify="center" py="xl">
            <Loader />
          </Group>
        ) : !activeItem ? (
          <Text c="dimmed">Select a media item to see its details.</Text>
        ) : (
          <ScrollArea h={DETAIL_SCROLL_HEIGHT} offsetScrollbars>
            <Stack spacing="xl">
              <Group align="flex-start" gap="xl" wrap="wrap">
                {posterUrl ? (
                  <Box w={{ base: '100%', sm: 240 }} style={{ flexShrink: 0, maxWidth: 260 }}>
                    <Box
                      style={{
                        borderRadius: 16,
                        overflow: 'hidden',
                        background: 'rgba(15, 23, 42, 0.75)',
                        maxHeight: DETAIL_POSTER_MAX_HEIGHT,
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                      }}
                    >
                      <Image
                        src={posterUrl}
                        alt={activeItem.title}
                        width="100%"
                        height="100%"
                        fit="contain"
                      />
                    </Box>
                  </Box>
                ) : null}

                <Stack
                  spacing={SECTION_STACK}
                  style={{ flex: 1, minWidth: 0 }}
                >
                  {metadataPending && (
                    <Alert
                      color="yellow"
                      variant="light"
                      icon={<AlertCircle size={18} />}
                      title="Metadata is still processing"
                    >
                      We&apos;re still gathering artwork and details for this title. Playback is available, but some information may be missing. Please check back in a few minutes for the full metadata.
                    </Alert>
                  )}
                  <Stack spacing={STACK_TIGHT} style={{ flex: 1 }}>
                    <Group justify="space-between" align="center">
                      <Title order={3}>{activeItem.title}</Title>
                      <Group gap="xs">
                        {activeItem.release_year && (
                          <Badge variant="outline">{activeItem.release_year}</Badge>
                        )}
                        {activeItem.rating && (
                          <Badge color="yellow" variant="outline">
                            {activeItem.rating}
                          </Badge>
                        )}
                        <Badge color="violet" variant="light">
                          {activeItem.item_type}
                        </Badge>
                        {activeItem.item_type === 'show' &&
                          showWatchSummary?.status === 'watched' && (
                            <Badge color="green">Watched</Badge>
                          )}
                        {activeItem.item_type === 'show' &&
                          showWatchSummary?.status === 'in_progress' && (
                            <Badge color="yellow" variant="light">
                              In progress
                            </Badge>
                          )}
                      </Group>
                    </Group>

                    {activeItem.synopsis && (
                      <Text size="sm" c="dimmed">
                        {activeItem.synopsis}
                      </Text>
                    )}

                    <Group gap="lg" mt="sm">
                      {runtimeLabel(activeItem.runtime_ms || files[0]?.duration_ms) && (
                        <Group gap={4} align="center">
                          <Clock size={18} />
                          <Text size="sm">
                            {runtimeLabel(activeItem.runtime_ms || files[0]?.duration_ms)}
                          </Text>
                        </Group>
                      )}
                      {activeItem.genres && (
                        <Group gap={6}>
                          {activeItem.genres.map((genre) => (
                            <Badge key={genre} variant="light">
                              {genre}
                            </Badge>
                          ))}
                        </Group>
                      )}
                    </Group>

                    {activeItem.item_type === 'show' && showWatchSummary?.total_episodes ? (
                      <Text size="sm" c="dimmed">
                        {showWatchSummary.completed_episodes || 0} of{' '}
                        {showWatchSummary.total_episodes} episodes watched
                      </Text>
                    ) : null}

                    <Group gap="sm" mt="md" align="center" wrap="wrap">
                      <Button
                        leftSection={<PlayCircle size={18} />}
                        onClick={handlePrimaryAction}
                        loading={
                          activeItem?.item_type === 'show'
                            ? episodePlayLoadingId !== null
                            : startingPlayback
                        }
                      >
                        {primaryButtonLabel}
                      </Button>
                      {activeItem?.youtube_trailer && (
                        <Button
                          variant="outline"
                          color="red"
                          onClick={() => {
                            setTrailerUrl(getEmbedUrl(activeItem.youtube_trailer));
                            setTrailerModalOpen(true);
                          }}
                        >
                          Watch Trailer
                        </Button>
                      )}
                      {canResume && activeItem?.item_type !== 'show' && (
                        <Text size="sm" c="dimmed">
                          Resume at{' '}
                          {runtimeLabel(
                            resumePrompt?.position_ms || activeProgress?.position_ms
                          )}{' '}
                          of{' '}
                          {runtimeLabel(
                            resumePrompt?.duration_ms || activeProgress?.duration_ms
                          )}
                        </Text>
                      )}
                    <ActionIcon
                      variant="light"
                      onClick={handleRefreshMetadata}
                      title="Refresh metadata"
                    >
                      <RefreshCcw size={18} />
                    </ActionIcon>
                    </Group>
                    {activeItem && (
                      <Group gap="sm" wrap="wrap">
                        {!itemIsWatched && (
                          <Button
                            variant="light"
                            color="green"
                            leftSection={<CheckCircle2 size={16} />}
                            loading={itemActionLoading === 'watch'}
                            onClick={handleMarkItemWatched}
                          >
                            Mark as watched
                          </Button>
                        )}
                        {itemInProgress && (
                          <Button
                            variant="subtle"
                            color="yellow"
                            leftSection={<XCircle size={16} />}
                            loading={itemActionLoading === 'clear'}
                            onClick={handleClearItemProgress}
                          >
                            Remove from Continue Watching
                          </Button>
                        )}
                        {itemIsWatched && (
                          <Button
                            variant="subtle"
                            leftSection={<Undo2 size={16} />}
                            loading={itemActionLoading === 'clear'}
                            onClick={handleClearItemProgress}
                          >
                            Mark unwatched
                          </Button>
                        )}
                      </Group>
                    )}
                  </Stack>
                </Stack>
              </Group>

              {activeItem.item_type === 'show' && (
                <Stack spacing={STACK_TIGHT} style={{ width: '100%' }}>
                  <Divider label="Episodes" labelPosition="center" />
                  {episodesLoading ? (
                    <Group justify="center" py="md">
                      <Loader size="sm" />
                    </Group>
                  ) : sortedSeasons.length === 0 ? (
                    <Text size="sm" c="dimmed">
                      No episodes discovered yet.
                    </Text>
                  ) : (
                    <Stack spacing="md">
                      <Group justify="space-between" align="center">
                        <Select
                          label="Season"
                          data={seasonOptions}
                          value={
                            selectedSeason != null ? String(selectedSeason) : null
                          }
                          onChange={(value) => {
                            setSeasonManuallySelected(true);
                            setSelectedSeason(value ? Number(value) : null);
                          }}
                          placeholder="Select season"
                          allowDeselect={false}
                          w={220}
                        />
                        <Badge variant="outline" size="xs">
                          {visibleEpisodes.length} episode
                          {visibleEpisodes.length === 1 ? '' : 's'}
                        </Badge>
                      </Group>
                      {visibleEpisodes.length === 0 ? (
                        <Text size="sm" c="dimmed">
                          No episodes available for this season.
                        </Text>
                      ) : (
                        <Stack spacing={STACK_TIGHT}>
                          {visibleEpisodes.map((episode) => {
                            const episodeProgress = episode.watch_progress;
                            const episodeStatus = episode.watch_summary?.status;
                            const progressPercent = episodeProgress?.percentage
                              ? Math.round(episodeProgress.percentage * 100)
                              : null;
                            const isWatched = episodeStatus === 'watched';
                            const isInProgress = episodeStatus === 'in_progress';
                            const episodeLoading = episodeActionLoading[episode.id];
                            const isExpanded = expandedEpisodeIds.has(episode.id);
                            const synopsisText = episode.synopsis?.trim();
                            return (
                              <Stack
                                key={episode.id}
                                spacing={STACK_TIGHT}
                                role="button"
                                tabIndex={0}
                                onClick={(event) => handleEpisodeCardClick(episode.id, event)}
                                onKeyDown={(event) => handleEpisodeCardKeyDown(episode.id, event)}
                                style={{
                                  border: '1px solid rgba(148, 163, 184, 0.15)',
                                  borderRadius: 12,
                                  padding: '10px 12px',
                                  cursor: 'pointer',
                                }}
                              >
                                <Group justify="space-between" align="flex-start" gap="md" wrap="wrap">
                                  <Stack spacing={STACK_TIGHT} style={{ flex: 1, minWidth: 0 }}>
                                    <Group justify="space-between" align="center">
                                      <Text fw={600} size="sm" lineClamp={1}>
                                        {[formatEpisodeCode(episode), episode.title]
                                          .filter(Boolean)
                                          .join(' ')}
                                      </Text>
                                      <Group gap={6}>
                                        {isWatched && (
                                          <Badge size="xs" color="green">
                                            Watched
                                          </Badge>
                                        )}
                                        {isInProgress && (
                                          <Badge size="xs" color="yellow" variant="light">
                                            In progress
                                          </Badge>
                                        )}
                                        {progressPercent !== null && (
                                          <Badge
                                            size="xs"
                                            color={episodeProgress?.completed ? 'green' : 'cyan'}
                                            variant="light"
                                          >
                                            {progressPercent}%
                                          </Badge>
                                        )}
                                      </Group>
                                    </Group>
                                    <Group gap={8} wrap="wrap">
                                      {runtimeLabel(episode.runtime_ms) && (
                                        <Group gap={4} align="center">
                                          <Clock size={14} />
                                          <Text size="xs" c="dimmed">
                                            {runtimeLabel(episode.runtime_ms)}
                                          </Text>
                                        </Group>
                                      )}
                                    </Group>
                                  </Stack>
                                  <Group gap={6}>
                                    <Button
                                      size="xs"
                                      variant="light"
                                      leftSection={<PlayCircle size={16} />}
                                      onClick={(event) => {
                                        event.stopPropagation();
                                        handlePlayEpisode(episode, {
                                          sequence: playbackPlan?.sorted ?? orderedEpisodes,
                                        });
                                      }}
                                      loading={episodePlayLoadingId === episode.id}
                                    >
                                      Play
                                    </Button>
                                    <Button
                                      size="xs"
                                      variant="subtle"
                                      leftSection={
                                        isWatched ? <Undo2 size={14} /> : <CheckCircle2 size={14} />
                                      }
                                      onClick={(event) => {
                                        event.stopPropagation();
                                        isWatched
                                          ? handleEpisodeMarkUnwatched(episode)
                                          : handleEpisodeMarkWatched(episode);
                                      }}
                                      loading={episodeLoading === 'watch' || episodeLoading === 'unwatch'}
                                    >
                                      {isWatched ? 'Unwatch' : 'Mark watched'}
                                    </Button>
                                    <ActionIcon
                                      color="red"
                                      variant="subtle"
                                      onClick={(event) => {
                                        event.stopPropagation();
                                        handleEpisodeDelete(episode);
                                      }}
                                      loading={episodeLoading === 'delete'}
                                      title="Delete episode"
                                    >
                                      <Trash2 size={16} />
                                    </ActionIcon>
                                  </Group>
                                </Group>
                                {synopsisText ? (
                                  <Text size="xs" c="dimmed" lineClamp={isExpanded ? undefined : 2}>
                                    {synopsisText}
                                  </Text>
                                ) : null}
                              </Stack>
                            );
                          })}
                        </Stack>
                      )}
                    </Stack>
                  )}
                </Stack>
              )}

              {hasCredits ? (
                <Stack spacing={STACK_TIGHT} style={{ width: '100%' }}>
                  {/* CAST */}
                  {castPeople.length > 0 && (
                    <Stack spacing={STACK_TIGHT}>
                      <Text fw={500}>Cast</Text>
                      <ScrollArea
                        type="auto"
                        scrollbarSize={8}
                        offsetScrollbars
                        styles={{ viewport: { paddingBottom: rem(14) } }}
                      >
                        <Group gap={CAST_GAP} wrap="nowrap">
                          {castPeople.map((person) => (
                            <Stack
                              key={person.key}
                              spacing={CAST_TILE_SPACING}
                              align="center"
                              style={{
                                width: rem(CAST_TILE_WIDTH),
                                height: rem(CAST_TILE_HEIGHT),
                                flex: `0 0 ${rem(CAST_TILE_WIDTH)}`,
                              }}
                            >
                              <Avatar
                                size={CAST_AVATAR_SIZE}
                                radius="md"
                                src={person.profile || undefined}
                                alt={person.name}
                                color="indigo"
                                styles={{ image: { objectFit: 'cover' } }}
                              >
                                {!person.profile && person.name?.[0]}
                              </Avatar>
                              <Text
                                size="xs"
                                fw={600}
                                ta="center"
                                lineClamp={2}
                                style={{ minHeight: 20, lineHeight: 1.15 }}
                              >
                                {person.name}
                              </Text>
                              {person.role && (
                                <Text
                                  size="xs"
                                  c="dimmed"
                                  ta="center"
                                  lineClamp={1}
                                  style={{ minHeight: 10, lineHeight: 1.1 }}
                                >
                                  {person.role}
                                </Text>
                              )}
                            </Stack>
                          ))}
                        </Group>
                      </ScrollArea>
                    </Stack>
                  )}

                  {/* CREW */}
                  {crewPeople.length > 0 && (
                    <Stack spacing={STACK_TIGHT}>
                      <Text fw={500}>Crew</Text>
                      <ScrollArea
                        type="auto"
                        scrollbarSize={8}
                        offsetScrollbars
                        styles={{ viewport: { paddingBottom: rem(14) } }}
                      >
                        <Group gap={CAST_GAP} wrap="nowrap">
                          {crewPeople.map((person) => (
                            <Stack
                              key={person.key}
                              spacing={CAST_TILE_SPACING}
                              align="center"
                              style={{
                                width: rem(CAST_TILE_WIDTH),
                                height: rem(CAST_TILE_HEIGHT),
                                flex: `0 0 ${rem(CAST_TILE_WIDTH)}`,
                              }}
                            >
                              <Avatar
                                size={CAST_AVATAR_SIZE}
                                radius="md"
                                src={person.profile || undefined}
                                alt={person.name}
                                color="grape"
                                styles={{ image: { objectFit: 'cover' } }}
                              >
                                {!person.profile && person.name?.[0]}
                              </Avatar>
                              <Text
                                size="xs"
                                fw={600}
                                ta="center"
                                lineClamp={2}
                                style={{ minHeight: 20, lineHeight: 1.15 }}
                              >
                                {person.name}
                              </Text>
                              {person.role && (
                                <Text
                                  size="xs"
                                  c="dimmed"
                                  ta="center"
                                  lineClamp={1}
                                  style={{ minHeight: 10, lineHeight: 1.1 }}
                                >
                                  {person.role}
                                </Text>
                              )}
                            </Stack>
                          ))}
                        </Group>
                      </ScrollArea>
                    </Stack>
                  )}
                </Stack>
              ) : null}
            </Stack>
          </ScrollArea>
        )}
      </Modal>
      {canEditMetadata && activeItem && (
        <MediaEditModal
          opened={editModalOpen}
          onClose={() => setEditModalOpen(false)}
          mediaItemId={activeItem.id}
          onSaved={handleEditSaved}
        />
      )}

      <Modal
        opened={resumeModalOpen}
        onClose={() => {
          setResumeModalOpen(false);
          setResumeMode('start');
        }}
        title="Resume playback?"
        centered
      >
        <Stack spacing="md">
          <Text>
            Resume from {runtimeLabel(resumePrompt?.position_ms || activeProgress?.position_ms)} of{' '}
            {runtimeLabel(resumePrompt?.duration_ms || activeProgress?.duration_ms)}?
          </Text>
          <Group justify="flex-end">
            <Button
              variant="default"
              leftSection={<DownloadCloud size={16} />}
              onClick={() => handleStartPlayback('resume')}
              loading={startingPlayback && resumeMode === 'resume'}
            >
              Resume
            </Button>
            <Button
              leftSection={<PlayCircle size={16} />}
              onClick={() => handleStartPlayback('start')}
              loading={startingPlayback && resumeMode === 'start'}
            >
              Start over
            </Button>
          </Group>
        </Stack>
      </Modal>

      <Modal
        opened={trailerModalOpen}
        onClose={() => setTrailerModalOpen(false)}
        title="Trailer"
        size="xl"
        centered
        withCloseButton
      >
        <Box style={{ position: 'relative', paddingBottom: '56.25%', height: 0 }}>
          {trailerUrl && (
            <iframe
              src={trailerUrl}
              title="YouTube Trailer"
              frameBorder="0"
              allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share"
              referrerPolicy="strict-origin-when-cross-origin"
              allowFullScreen
              style={{
                position: 'absolute',
                top: 0,
                left: 0,
                width: '100%',
                height: '100%',
                borderRadius: 8,
              }}
            />
          )}
        </Box>
      </Modal>
    </>
  );
};

export default MediaDetailModal;
