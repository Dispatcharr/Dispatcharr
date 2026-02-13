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
const CAST_TILE_SPACING = 0;
const STACK_TIGHT = 4;          // was 6
const SECTION_STACK = 12;       // was larger in some places
const CREDITS_SECTION_GAP = 2;
const CREDITS_INNER_GAP = 2;
const CREDITS_SCROLL_PADDING = 8;
const CREDIT_NAME_MIN_HEIGHT = 18;
const CREDIT_ROLE_MIN_HEIGHT = 8;
const DETAIL_LOWER_SCROLL_MAX_HEIGHT = '42vh';
const DETAIL_POSTER_MAX_HEIGHT = '72vh';
const EXTRAS_SEASON_KEY = 'extras';
const EXTRAS_SEASON_LABEL = 'Extras';
const isExtrasSeasonNumber = (seasonNumber) =>
  seasonNumber == null || seasonNumber === 0;
const seasonKeyFromNumber = (seasonNumber) =>
  isExtrasSeasonNumber(seasonNumber) ? EXTRAS_SEASON_KEY : String(seasonNumber);

const compareEpisodes = (a, b) => {
  const seasonA = isExtrasSeasonNumber(a.season_number)
    ? Number.POSITIVE_INFINITY
    : a.season_number ?? 0;
  const seasonB = isExtrasSeasonNumber(b.season_number)
    ? Number.POSITIVE_INFINITY
    : b.season_number ?? 0;
  if (seasonA !== seasonB) return seasonA - seasonB;
  const episodeA = a.episode_number ?? 0;
  const episodeB = b.episode_number ?? 0;
  if (episodeA !== episodeB) return episodeA - episodeB;
  return (a.sort_title || '').localeCompare(b.sort_title || '');
};

const sameEpisodeId = (a, b) => String(a) === String(b);

const primaryFileForEpisode = (episode) =>
  Array.isArray(episode?.files) && episode.files.length > 0
    ? episode.files[0]
    : null;

const episodeGroupKey = (episode) => {
  const file = primaryFileForEpisode(episode);
  if (file?.id != null) {
    return `file:${file.id}`;
  }
  if (file?.path) {
    return `path:${file.path}`;
  }
  return `episode:${episode.id}`;
};
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

const CreditStrip = ({ people, avatarColor }) => {
  const viewportRef = useRef(null);
  const contentRef = useRef(null);
  const [hasOverflow, setHasOverflow] = useState(false);

  const measureOverflow = useCallback(() => {
    const viewport = viewportRef.current;
    const content = contentRef.current;
    if (!viewport || !content) {
      setHasOverflow(false);
      return;
    }
    setHasOverflow(content.scrollWidth - viewport.clientWidth > 2);
  }, []);

  useEffect(() => {
    measureOverflow();
  }, [measureOverflow, people]);

  useEffect(() => {
    const viewport = viewportRef.current;
    const content = contentRef.current;
    if (!viewport || !content || typeof ResizeObserver === 'undefined') {
      return undefined;
    }

    const observer = new ResizeObserver(() => {
      measureOverflow();
    });
    observer.observe(viewport);
    observer.observe(content);

    return () => observer.disconnect();
  }, [measureOverflow, people]);

  if (!Array.isArray(people) || people.length === 0) {
    return null;
  }

  return (
    <ScrollArea
      w="100%"
      scrollbars="x"
      type={hasOverflow ? 'hover' : 'never'}
      scrollbarSize={hasOverflow ? 8 : 0}
      viewportRef={viewportRef}
      styles={{
        root: { width: '100%' },
        viewport: {
          paddingBottom: hasOverflow ? rem(CREDITS_SCROLL_PADDING) : 0,
          overflowY: 'hidden',
        },
      }}
    >
      <Group
        ref={contentRef}
        gap={CAST_GAP}
        wrap="nowrap"
        style={{ width: 'max-content', minWidth: '100%' }}
      >
        {people.map((person) => (
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
              color={avatarColor}
              styles={{ image: { objectFit: 'cover' } }}
            >
              {!person.profile && person.name?.[0]}
            </Avatar>
            <Text
              size="xs"
              fw={600}
              ta="center"
              lineClamp={2}
              style={{ minHeight: CREDIT_NAME_MIN_HEIGHT, lineHeight: 1.1 }}
            >
              {person.name}
            </Text>
            {person.role && (
              <Text
                size="xs"
                c="dimmed"
                ta="center"
                lineClamp={1}
                style={{ minHeight: CREDIT_ROLE_MIN_HEIGHT, lineHeight: 1.05 }}
              >
                {person.role}
              </Text>
            )}
          </Stack>
        ))}
      </Group>
    </ScrollArea>
  );
};

const MediaDetailModal = ({ opened, onClose }) => {
  const activeItem = useMediaLibraryStore((s) => s.activeItem);
  const activeItemLoading = useMediaLibraryStore((s) => s.activeItemLoading);
  const activeItemError = useMediaLibraryStore((s) => s.activeItemError);
  const activeProgress = useMediaLibraryStore((s) => s.activeProgress);
  const resumePrompt = useMediaLibraryStore((s) => s.resumePrompt);
  const requestResume = useMediaLibraryStore((s) => s.requestResume);
  const clearResumePrompt = useMediaLibraryStore((s) => s.clearResumePrompt);
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
      const loadedEpisodes = Array.isArray(results) ? results : [];
      setEpisodes(loadedEpisodes);
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
    return [...episodes].sort(compareEpisodes);
  }, [episodes]);

  const watchableEpisodes = useMemo(
    () => orderedEpisodes.filter((episode) => !isExtrasSeasonNumber(episode.season_number)),
    [orderedEpisodes]
  );

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

    const sorted = watchableEpisodes;
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
  }, [activeItem, watchableEpisodes, showWatchSummary]);

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
        playbackPlan?.sorted?.length ? playbackPlan.sorted : watchableEpisodes;
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
    { sequence = watchableEpisodes, startIndex = null } = {}
  ) => {
    if (!episode) return;
    setEpisodePlayLoadingId(episode.id);
    try {
      const episodeDetail = Array.isArray(episode.files)
        ? episode
        : await API.getMediaItem(episode.id, {
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

      let effectiveSequence = Array.isArray(sequence)
        ? sequence.filter((entry) => entry && entry.id != null)
        : [];
      if (
        effectiveSequence.length <= 1 &&
        activeItem?.item_type === 'show' &&
        activeItem?.id
      ) {
        const fallbackSequence = watchableEpisodes.length
          ? watchableEpisodes
          : orderedEpisodes;
        if (fallbackSequence.length > 0) {
          effectiveSequence = fallbackSequence;
        }
      }
      if (!effectiveSequence.length) {
        effectiveSequence = [episodeDetail];
      }

      let episodeIds = effectiveSequence.map((ep) => ep.id).filter((id) => id != null);
      if (!episodeIds.some((id) => sameEpisodeId(id, episodeDetail.id))) {
        const insertAt =
          Number.isInteger(startIndex) && startIndex >= 0
            ? Math.min(startIndex, episodeIds.length)
            : 0;
        episodeIds = [
          ...episodeIds.slice(0, insertAt),
          episodeDetail.id,
          ...episodeIds.slice(insertAt),
        ];
      }

      let computedIndex =
        Number.isInteger(startIndex) &&
        startIndex >= 0 &&
        startIndex < episodeIds.length
          ? startIndex
          : episodeIds.findIndex((id) => sameEpisodeId(id, episodeDetail.id));
      if (computedIndex < 0) {
        computedIndex = 0;
      }

      const playbackSequence =
        episodeIds.length > 1
          ? { episodeIds, currentIndex: computedIndex }
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
      const seasonKey = seasonKeyFromNumber(episode.season_number);
      if (!grouped.has(seasonKey)) grouped.set(seasonKey, []);
      grouped.get(seasonKey).push(episode);
    });
    return grouped;
  }, [orderedEpisodes]);

  const sortedSeasonKeys = useMemo(() => {
    const keys = Array.from(episodesBySeason.keys());
    const numeric = keys
      .filter((key) => key !== EXTRAS_SEASON_KEY)
      .map((key) => Number(key))
      .filter((value) => !Number.isNaN(value))
      .sort((a, b) => a - b)
      .map((value) => String(value));
    if (keys.includes(EXTRAS_SEASON_KEY)) {
      numeric.push(EXTRAS_SEASON_KEY);
    }
    return numeric;
  }, [episodesBySeason]);

  const nonExtrasSeasonKeys = useMemo(
    () => sortedSeasonKeys.filter((key) => key !== EXTRAS_SEASON_KEY),
    [sortedSeasonKeys]
  );

  const visibleEpisodes = useMemo(() => {
    if (selectedSeason == null) return [];
    return episodesBySeason.get(selectedSeason) || [];
  }, [episodesBySeason, selectedSeason]);

  const groupedVisibleEpisodes = useMemo(() => {
    if (!visibleEpisodes.length) return [];

    const grouped = new Map();
    visibleEpisodes.forEach((episode) => {
      const groupId = episodeGroupKey(episode);
      if (!grouped.has(groupId)) {
        grouped.set(groupId, []);
      }
      grouped.get(groupId).push(episode);
    });

    return Array.from(grouped.entries())
      .map(([groupId, groupEpisodes]) => {
        const episodes = [...groupEpisodes].sort(compareEpisodes);
        const representative = episodes[0];
        const watchedCount = episodes.filter(
          (entry) => entry.watch_summary?.status === 'watched'
        ).length;
        const inProgressCount = episodes.filter(
          (entry) => entry.watch_summary?.status === 'in_progress'
        ).length;
        const isMultiEpisode = episodes.length > 1;
        let status = 'unwatched';
        if (watchedCount === episodes.length) {
          status = 'watched';
        } else if (inProgressCount > 0 || watchedCount > 0) {
          status = 'in_progress';
        }
        return {
          id: groupId,
          episodes,
          representative,
          watchedCount,
          isMultiEpisode,
          status,
        };
      })
      .sort((a, b) => compareEpisodes(a.representative, b.representative));
  }, [visibleEpisodes]);

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
      sortedSeasonKeys.map((seasonKey) => ({
        value: seasonKey,
        label:
          seasonKey === EXTRAS_SEASON_KEY
            ? EXTRAS_SEASON_LABEL
            : `Season ${seasonKey}`,
      })),
    [sortedSeasonKeys]
  );

  const resumeCandidate =
    playbackPlan?.resumeEpisode || playbackPlan?.nextEpisode || null;
  const resumeSeasonKey =
    resumeCandidate && !isExtrasSeasonNumber(resumeCandidate.season_number)
      ? String(resumeCandidate.season_number)
      : null;

  useEffect(() => {
    if (!sortedSeasonKeys.length) {
      if (selectedSeason !== null) {
        setSelectedSeason(null);
      }
      lastResumeSeasonRef.current = null;
      setSeasonManuallySelected(false);
      return;
    }

    if (resumeSeasonKey && nonExtrasSeasonKeys.includes(resumeSeasonKey)) {
      const resumeChanged = lastResumeSeasonRef.current !== resumeSeasonKey;
      if (!seasonManuallySelected || resumeChanged) {
        lastResumeSeasonRef.current = resumeSeasonKey;
        setSelectedSeason(resumeSeasonKey);
        setSeasonManuallySelected(false);
        return;
      }
    } else {
      lastResumeSeasonRef.current = null;
    }

    const hasValidSelection =
      selectedSeason !== null && sortedSeasonKeys.includes(selectedSeason);
    if (seasonManuallySelected && hasValidSelection) {
      return;
    }

    if (!hasValidSelection || selectedSeason === EXTRAS_SEASON_KEY) {
      const fallback = nonExtrasSeasonKeys[0] || null;
      if (fallback) {
        setSelectedSeason(fallback);
        setSeasonManuallySelected(false);
      } else if (!seasonManuallySelected && selectedSeason !== null) {
        setSelectedSeason(null);
        setSeasonManuallySelected(false);
      }
    }
  }, [
    sortedSeasonKeys,
    nonExtrasSeasonKeys,
    resumeSeasonKey,
    seasonManuallySelected,
    selectedSeason,
  ]);

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
            overflowX: 'hidden',
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
          <Stack spacing="xl" style={{ width: '100%', minWidth: 0 }}>
              <Group align="flex-start" gap="xl" wrap="wrap" style={{ width: '100%', minWidth: 0 }}>
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
                    <Group justify="space-between" align="center" wrap="wrap" gap="xs">
                      <Title order={3} style={{ minWidth: 0, wordBreak: 'break-word' }}>
                        {activeItem.title}
                      </Title>
                      <Group gap="xs" wrap="wrap">
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
                      <Text size="sm" c="dimmed" style={{ overflowWrap: 'anywhere' }}>
                        {activeItem.synopsis}
                      </Text>
                    )}

                    <Group gap="lg" mt="sm" wrap="wrap">
                      {runtimeLabel(activeItem.runtime_ms || files[0]?.duration_ms) && (
                        <Group gap={4} align="center">
                          <Clock size={18} />
                          <Text size="sm">
                            {runtimeLabel(activeItem.runtime_ms || files[0]?.duration_ms)}
                          </Text>
                        </Group>
                      )}
                      {activeItem.genres && (
                        <Group gap={6} wrap="wrap">
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

	              {(activeItem.item_type === 'show' || hasCredits) ? (
	                <Box
	                  style={{
	                    width: '100%',
	                    maxHeight: DETAIL_LOWER_SCROLL_MAX_HEIGHT,
	                    overflowY: 'auto',
	                    overflowX: 'hidden',
	                    paddingRight: rem(4),
	                  }}
	                >
	                  <Stack spacing="xl" style={{ width: '100%', minWidth: 0 }}>
	              {activeItem.item_type === 'show' && (
	                <Stack spacing={STACK_TIGHT} style={{ width: '100%' }}>
	                  <Divider label="Episodes" labelPosition="center" />
	                  {episodesLoading ? (
                    <Group justify="center" py="md">
                      <Loader size="sm" />
                    </Group>
                  ) : sortedSeasonKeys.length === 0 ? (
                    <Text size="sm" c="dimmed">
                      No episodes discovered yet.
                    </Text>
                  ) : (
                    <Stack spacing="md">
	                      <Group justify="space-between" align="center" wrap="wrap" gap="sm">
	                        <Select
                          label="Season"
                          data={seasonOptions}
                          value={selectedSeason}
                          onChange={(value) => {
                            setSeasonManuallySelected(true);
                            setSelectedSeason(value || null);
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
                      {groupedVisibleEpisodes.length === 0 ? (
                        <Text size="sm" c="dimmed">
                          No episodes available for this season.
                        </Text>
                      ) : (
                        <Stack spacing={STACK_TIGHT}>
                          {groupedVisibleEpisodes.map((group) => {
                            const representative = group.representative;
                            const firstEpisode = group.episodes[0];
                            const lastEpisode =
                              group.episodes[group.episodes.length - 1];
                            const firstCode = firstEpisode
                              ? formatEpisodeCode(firstEpisode)
                              : '';
                            const lastCode = lastEpisode
                              ? formatEpisodeCode(lastEpisode)
                              : '';
                            const groupLabel = group.isMultiEpisode
                              ? [firstCode, lastCode]
                                  .filter(Boolean)
                                  .join(' - ')
                              : [formatEpisodeCode(representative), representative.title]
                                  .filter(Boolean)
                                  .join(' ');
                            const groupSynopsisText = group.isMultiEpisode
                              ? null
                              : representative.synopsis?.trim();
                            const representativeProgress =
                              representative.watch_progress;
                            const combinedRuntimeMs = group.episodes.reduce(
                              (total, entry) => total + (entry.runtime_ms || 0),
                              0
                            );
                            const representativeFileRuntimeMs =
                              representative.files?.[0]?.duration_ms || 0;
                            const displayRuntimeMs = group.isMultiEpisode
                              ? combinedRuntimeMs ||
                                representativeFileRuntimeMs ||
                                representative.runtime_ms ||
                                0
                              : representative.runtime_ms ||
                                representativeFileRuntimeMs ||
                                0;
                            const progressPercent = representativeProgress?.percentage
                              ? Math.round(representativeProgress.percentage * 100)
                              : null;
                            const isWatched = group.status === 'watched';
                            const isInProgress = group.status === 'in_progress';
                            const isExpanded = expandedEpisodeIds.has(group.id);
                            const playTarget =
                              group.episodes.find(
                                (entry) =>
                                  entry.watch_summary?.status === 'in_progress'
                              ) ||
                              group.episodes.find(
                                (entry) => entry.watch_summary?.status !== 'watched'
                              ) ||
                              representative;
                            const isGroupPlaying = group.episodes.some(
                              (entry) => entry.id === episodePlayLoadingId
                            );
                            const representativeLoading =
                              episodeActionLoading[representative.id];
                            return (
	                              <Stack
	                                key={group.id}
	                                spacing={STACK_TIGHT}
                                role="button"
                                tabIndex={0}
                                onClick={(event) =>
                                  handleEpisodeCardClick(group.id, event)
                                }
                                onKeyDown={(event) =>
                                  handleEpisodeCardKeyDown(group.id, event)
                                }
	                                style={{
	                                  border: '1px solid rgba(148, 163, 184, 0.15)',
	                                  borderRadius: 12,
	                                  padding: '8px 10px',
	                                  width: '100%',
	                                  boxSizing: 'border-box',
	                                  cursor: 'pointer',
	                                }}
	                              >
	                                <Group
	                                  justify="space-between"
	                                  align="flex-start"
	                                  gap="md"
	                                  wrap="wrap"
	                                  style={{ width: '100%', minWidth: 0 }}
	                                >
                                  <Stack spacing={STACK_TIGHT} style={{ flex: 1, minWidth: 0 }}>
                                    <Group justify="space-between" align="center">
                                      <Text fw={600} size="sm" lineClamp={1}>
                                        {groupLabel}
                                      </Text>
	                                  <Group gap={6} wrap="wrap">
                                        {group.isMultiEpisode && (
                                          <Badge size="xs" variant="outline">
                                            {group.episodes.length} episodes
                                          </Badge>
                                        )}
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
                                        {!group.isMultiEpisode &&
                                          progressPercent !== null && (
                                          <Badge
                                            size="xs"
                                            color={
                                              representativeProgress?.completed
                                                ? 'green'
                                                : 'cyan'
                                            }
                                            variant="light"
                                          >
                                            {progressPercent}%
                                          </Badge>
                                          )}
                                        {group.isMultiEpisode &&
                                          group.watchedCount > 0 && (
                                          <Badge size="xs" color="cyan" variant="light">
                                            {group.watchedCount}/
                                            {group.episodes.length} watched
                                          </Badge>
                                          )}
                                      </Group>
                                    </Group>
                                    <Group gap={8} wrap="wrap">
                                      {runtimeLabel(displayRuntimeMs) && (
                                        <Group gap={4} align="center">
                                          <Clock size={14} />
                                          <Text size="xs" c="dimmed">
                                            {runtimeLabel(displayRuntimeMs)}
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
                                        handlePlayEpisode(playTarget, {
                                          sequence:
                                            playbackPlan?.sorted ?? watchableEpisodes,
                                        });
                                      }}
                                      loading={isGroupPlaying}
                                    >
                                      Play
                                    </Button>
                                    {!group.isMultiEpisode && (
                                      <>
                                        <Button
                                          size="xs"
                                          variant="subtle"
                                          leftSection={
                                            isWatched ? (
                                              <Undo2 size={14} />
                                            ) : (
                                              <CheckCircle2 size={14} />
                                            )
                                          }
                                          onClick={(event) => {
                                            event.stopPropagation();
                                            isWatched
                                              ? handleEpisodeMarkUnwatched(
                                                  representative
                                                )
                                              : handleEpisodeMarkWatched(
                                                  representative
                                                );
                                          }}
                                          loading={
                                            representativeLoading === 'watch' ||
                                            representativeLoading === 'unwatch'
                                          }
                                        >
                                          {isWatched ? 'Unwatch' : 'Mark watched'}
                                        </Button>
                                        <ActionIcon
                                          color="red"
                                          variant="subtle"
                                          onClick={(event) => {
                                            event.stopPropagation();
                                            handleEpisodeDelete(representative);
                                          }}
                                          loading={representativeLoading === 'delete'}
                                          title="Delete episode"
                                        >
                                          <Trash2 size={16} />
                                        </ActionIcon>
                                      </>
                                    )}
                                  </Group>
                                </Group>
                                {group.isMultiEpisode ? (
                                  <Stack spacing={2}>
                                    {group.episodes.map((entry, index) => {
                                      const entrySynopsis = entry.synopsis?.trim();
                                      return (
                                        <Box key={entry.id}>
                                          <Text size="xs" fw={600} lineClamp={1}>
                                            {[formatEpisodeCode(entry), entry.title]
                                              .filter(Boolean)
                                              .join(' ')}
                                          </Text>
                                          {entrySynopsis ? (
                                            <Text
                                              size="xs"
                                              c="dimmed"
                                              lineClamp={isExpanded ? undefined : 1}
                                            >
                                              {entrySynopsis}
                                            </Text>
                                          ) : null}
                                          {index < group.episodes.length - 1 && (
                                            <Divider
                                              my="xs"
                                              color="rgba(148, 163, 184, 0.18)"
                                            />
                                          )}
                                        </Box>
                                      );
                                    })}
                                  </Stack>
                                ) : groupSynopsisText ? (
                                  <Text size="xs" c="dimmed" lineClamp={isExpanded ? undefined : 2}>
                                    {groupSynopsisText}
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
	                <Stack spacing={CREDITS_SECTION_GAP} style={{ width: '100%' }}>
	                  {/* CAST */}
	                  {castPeople.length > 0 && (
	                    <Stack spacing={CREDITS_INNER_GAP}>
                      <Text fw={500}>Cast</Text>
                      <CreditStrip people={castPeople} avatarColor="indigo" />
                    </Stack>
                  )}

                  {/* CREW */}
	                  {crewPeople.length > 0 && (
	                    <Stack spacing={CREDITS_INNER_GAP}>
	                      <Text fw={500}>Crew</Text>
	                      <CreditStrip people={crewPeople} avatarColor="grape" />
	                    </Stack>
	                  )}
	                </Stack>
	              ) : null}
	                  </Stack>
	                </Box>
	              ) : null}
	            </Stack>
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
