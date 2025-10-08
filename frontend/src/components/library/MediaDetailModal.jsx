import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
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
  Stack,
  Text,
  Title,
  rem,
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import {
  CheckCircle2,
  Clock,
  DownloadCloud,
  Info,
  PlayCircle,
  RefreshCcw,
  Undo2,
  Trash2,
  Pencil,
} from 'lucide-react';

import API from '../../api';
import useMediaLibraryStore from '../../store/mediaLibrary';
import useVideoStore from '../../store/useVideoStore';
import useAuthStore from '../../store/auth';
import { USER_LEVELS } from '../../constants';
import MediaEditModal from './MediaEditModal';

// ---- quick tuning knobs ----
const CAST_TILE_WIDTH = 96;     // was 116
const CAST_TILE_HEIGHT = 148;   // was 160
const CAST_AVATAR_SIZE = 72;    // was 80
const CAST_GAP = 8;             // was "md" (~16)
const STACK_TIGHT = 4;          // was 6
const SECTION_STACK = 12;       // was larger in some places
// ----------------------------

const runtimeLabel = (runtimeMs) => {
  if (!runtimeMs) return null;
  const totalSeconds = Math.round(runtimeMs / 1000);
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  if (hours) return `${hours}h ${minutes}m`;
  return `${minutes}m`;
};

const MediaDetailModal = ({ opened, onClose }) => {
  const activeItem = useMediaLibraryStore((s) => s.activeItem);
  const activeItemLoading = useMediaLibraryStore((s) => s.activeItemLoading);
  const activeProgress = useMediaLibraryStore((s) => s.activeProgress);
  const resumePrompt = useMediaLibraryStore((s) => s.resumePrompt);
  const requestResume = useMediaLibraryStore((s) => s.requestResume);
  const clearResumePrompt = useMediaLibraryStore((s) => s.clearResumePrompt);
  const setActiveProgress = useMediaLibraryStore((s) => s.setActiveProgress);
  const showVideo = useVideoStore((s) => s.showVideo);
  const userLevel = useAuthStore((s) => s.user?.user_level ?? 0);
  const canEditMetadata = userLevel >= USER_LEVELS.ADMIN;

  const [startingPlayback, setStartingPlayback] = useState(false);
  const [resumeModalOpen, setResumeModalOpen] = useState(false);
  const [resumeMode, setResumeMode] = useState('start');
  const [editModalOpen, setEditModalOpen] = useState(false);

  const [episodes, setEpisodes] = useState([]);
  const [episodesLoading, setEpisodesLoading] = useState(false);
  const [episodePlayLoadingId, setEpisodePlayLoadingId] = useState(null);
  const [episodeActionLoading, setEpisodeActionLoading] = useState({});

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
      const streamInfo = await API.streamMediaItem(activeItem.id, { fileId });
      const playbackUrl = streamInfo?.url || streamInfo?.stream_url;
      if (!playbackUrl) {
        notifications.show({
          title: 'Playback error',
          message: 'Streaming endpoint did not return a playable URL.',
          color: 'red',
        });
        return;
      }

      const resumePositionMs =
        mode === 'resume'
          ? resumePrompt?.position_ms || activeProgress?.position_ms || 0
          : 0;

      showVideo(playbackUrl, 'library', {
        mediaItemId: activeItem.id,
        mediaTitle: activeItem.title,
        name: activeItem.title,
        year: activeItem.release_year,
        logo: activeItem.poster_url ? { url: activeItem.poster_url } : undefined,
        progressId: activeProgress?.id,
        resumePositionMs,
        durationMs:
          resumePrompt?.duration_ms || activeProgress?.duration_ms || activeItem.runtime_ms,
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
      const targetEpisode =
        playbackPlan?.resumeEpisode || playbackPlan?.nextEpisode || playbackPlan?.sorted?.[0];
      if (!targetEpisode) {
        notifications.show({
          title: 'No episodes available',
          message: 'This series does not have any episodes to play yet.',
          color: 'yellow',
        });
        return;
      }
      const startIndex = playbackPlan.sorted.findIndex((ep) => ep.id === targetEpisode.id);
      void handlePlayEpisode(targetEpisode, { sequence: playbackPlan.sorted, startIndex });
      return;
    }
    if (canResume && (resumePrompt || activeProgress)) {
      setResumeMode('resume');
      setResumeModalOpen(true);
    } else {
      handleStartPlayback('start');
    }
  };

  const handlePlayEpisode = async (
    episode,
    { sequence = orderedEpisodes, startIndex = null } = {}
  ) => {
    if (!episode) return;
    setEpisodePlayLoadingId(episode.id);
    try {
      const episodeDetail = await API.getMediaItem(episode.id);
      const episodeFileId = episodeDetail.files?.[0]?.id;
      if (!episodeFileId) {
        notifications.show({
          title: 'Playback unavailable',
          message: 'No media file is linked to this episode yet.',
          color: 'red',
        });
        return;
      }

      const streamInfo = await API.streamMediaItem(episodeDetail.id, { fileId: episodeFileId });
      const playbackUrl = streamInfo?.url || streamInfo?.stream_url;
      if (!playbackUrl) {
        notifications.show({
          title: 'Playback error',
          message: 'Streaming endpoint did not return a playable URL.',
          color: 'red',
        });
        return;
      }

      const resolvedSequence = Array.isArray(sequence) ? sequence : [];
      const episodeIds = resolvedSequence.length
        ? resolvedSequence.map((ep) => ep.id)
        : orderedEpisodes.map((ep) => ep.id);
      const computedIndex = startIndex ?? episodeIds.findIndex((id) => id === episode.id);

      const playbackSequence = episodeIds.length
        ? { episodeIds, currentIndex: computedIndex >= 0 ? computedIndex : 0 }
        : null;

      const episodeProgress = episodeDetail.watch_progress;
      const episodeSummary = episodeDetail.watch_summary;
      const resumePositionMs =
        episodeSummary?.status === 'in_progress'
          ? episodeSummary.position_ms || 0
          : episodeProgress?.position_ms || 0;

      const durationMs =
        episodeSummary?.duration_ms || episodeProgress?.duration_ms || episodeDetail.runtime_ms;

      showVideo(playbackUrl, 'library', {
        mediaItemId: episodeDetail.id,
        mediaTitle: episodeDetail.title,
        showId: activeItem?.id,
        showTitle: activeItem?.title,
        name: episodeDetail.title,
        year: episodeDetail.release_year,
        logo:
          episodeDetail.poster_url
            ? { url: episodeDetail.poster_url }
            : activeItem?.poster_url
            ? { url: activeItem.poster_url }
            : undefined,
        showPoster: activeItem?.poster_url,
        progressId: episodeProgress?.id,
        resumePositionMs,
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

  const files = activeItem?.files || [];

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
          <ScrollArea h="70vh" offsetScrollbars>
            <Group align="flex-start" gap="xl" wrap="wrap">
              {activeItem.poster_url ? (
                <Box w={{ base: '100%', sm: 240 }} style={{ flexShrink: 0, maxWidth: 260 }}>
                  <Box
                    style={{
                      borderRadius: 16,
                      overflow: 'hidden',
                      background: 'rgba(15, 23, 42, 0.75)',
                      maxHeight: '65vh',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                    }}
                  >
                    <Image
                      src={activeItem.poster_url}
                      alt={activeItem.title}
                      width="100%"
                      height="100%"
                      fit="contain"
                    />
                  </Box>
                </Box>
              ) : null}

              <Stack spacing={SECTION_STACK} style={{ flex: 1, minWidth: 0 }}>
                <Stack spacing={STACK_TIGHT}>
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
                      onClick={() => API.refreshMediaItemMetadata(activeItem.id)}
                      title="Refresh metadata"
                    >
                      <RefreshCcw size={18} />
                    </ActionIcon>
                  </Group>
                </Stack>

                {activeItem.item_type === 'show' && (
                  <>
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
                        {sortedSeasons.map((season) => {
                          const seasonEpisodes = episodesBySeason.get(season) || [];
                          return (
                            <Stack key={season} spacing={STACK_TIGHT}>
                              <Group justify="space-between" align="center">
                                <Group gap="xs" align="center">
                                  <Title order={5}>Season {season}</Title>
                                  <Badge variant="outline" size="xs">
                                    {seasonEpisodes.length} episode
                                    {seasonEpisodes.length === 1 ? '' : 's'}
                                  </Badge>
                                </Group>
                              </Group>
                              <Stack spacing={STACK_TIGHT}>
                                {seasonEpisodes.map((episode) => {
                                  const episodeProgress = episode.watch_progress;
                                  const episodeStatus = episode.watch_summary?.status;
                                  const progressPercent = episodeProgress?.percentage
                                    ? Math.round(episodeProgress.percentage * 100)
                                    : null;
                                  const isWatched = episodeStatus === 'watched';
                                  const isInProgress = episodeStatus === 'in_progress';
                                  const episodeLoading = episodeActionLoading[episode.id];
                                  return (
                                    <Group
                                      key={episode.id}
                                      justify="space-between"
                                      align="flex-start"
                                      gap="md"
                                      style={{
                                        border: '1px solid rgba(148, 163, 184, 0.15)',
                                        borderRadius: 12,
                                        padding: '10px 12px',
                                      }}
                                    >
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
                                        {(episode.synopsis || activeItem?.synopsis) && (
                                          <Text size="xs" c="dimmed" lineClamp={2}>
                                            {episode.synopsis || activeItem?.synopsis}
                                          </Text>
                                        )}
                                      </Stack>
                                      <Stack spacing={STACK_TIGHT} align="flex-end">
                                        <Group gap={6}>
                                          <Button
                                            size="xs"
                                            variant="light"
                                            leftSection={<PlayCircle size={16} />}
                                            onClick={() =>
                                              handlePlayEpisode(episode, {
                                                sequence: playbackPlan?.sorted,
                                              })
                                            }
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
                                            onClick={() =>
                                              isWatched
                                                ? handleEpisodeMarkUnwatched(episode)
                                                : handleEpisodeMarkWatched(episode)
                                            }
                                            loading={episodeLoading === 'watch' || episodeLoading === 'unwatch'}
                                          >
                                            {isWatched ? 'Unwatch' : 'Mark watched'}
                                          </Button>
                                          <ActionIcon
                                            color="red"
                                            variant="subtle"
                                            onClick={() => handleEpisodeDelete(episode)}
                                            loading={episodeLoading === 'delete'}
                                            title="Delete episode"
                                          >
                                            <Trash2 size={16} />
                                          </ActionIcon>
                                        </Group>
                                      </Stack>
                                    </Group>
                                  );
                                })}
                              </Stack>
                            </Stack>
                          );
                        })}
                      </Stack>
                    )}
                  </>
                )}

                <Divider label="Metadata" labelPosition="center" />

                <Stack spacing={STACK_TIGHT}>
                  <Group gap="xs">
                    {activeItem.tmdb_id && (
                      <Badge
                        component="a"
                        href={`https://www.themoviedb.org/${
                          activeItem.item_type === 'movie' ? 'movie' : 'tv'
                        }/${activeItem.tmdb_id}`}
                        target="_blank"
                        leftSection={<Info size={14} />}
                      >
                        TMDB {activeItem.tmdb_id}
                      </Badge>
                    )}
                    {activeItem.imdb_id && (
                      <Badge
                        component="a"
                        href={`https://www.imdb.com/title/${activeItem.imdb_id}`}
                        target="_blank"
                        leftSection={<Info size={14} />}
                      >
                        IMDB {activeItem.imdb_id}
                      </Badge>
                    )}
                  </Group>

                  {/* CAST */}
                  {castPeople.length > 0 && (
                    <Stack spacing={STACK_TIGHT}>
                      <Text fw={500}>Cast</Text>
                      <ScrollArea
                        type="auto"
                        offsetScrollbars
                        styles={{ viewport: { paddingBottom: rem(6) } }}
                      >
                        <Group gap={CAST_GAP} wrap="nowrap">
                          {castPeople.map((person) => (
                            <Stack
                              key={person.key}
                              spacing={STACK_TIGHT}
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
                              <Text size="xs" fw={600} ta="center" lineClamp={2} style={{ minHeight: 30 }}>
                                {person.name}
                              </Text>
                              {person.role && (
                                <Text size="xs" c="dimmed" ta="center" lineClamp={1} style={{ minHeight: 16 }}>
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
                        offsetScrollbars
                        styles={{ viewport: { paddingBottom: rem(6) } }}
                      >
                        <Group gap={CAST_GAP} wrap="nowrap">
                          {crewPeople.map((person) => (
                            <Stack
                              key={person.key}
                              spacing={STACK_TIGHT}
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
                              <Text size="xs" fw={600} ta="center" lineClamp={2} style={{ minHeight: 30 }}>
                                {person.name}
                              </Text>
                              {person.role && (
                                <Text size="xs" c="dimmed" ta="center" lineClamp={1} style={{ minHeight: 16 }}>
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
              </Stack>
            </Group>
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
    </>
  );
};

export default MediaDetailModal;
