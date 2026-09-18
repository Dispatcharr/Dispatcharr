import React, { useState, useEffect, useRef } from 'react';
import {
  Box,
  Button,
  Flex,
  Group,
  Image,
  Text,
  Title,
  Badge,
  Loader,
  Stack,
  ActionIcon,
  Modal,
  Tabs,
  Table,
  Divider,
  TableTbody,
  TableTd,
  TableTh,
  TableThead,
  TableTr,
  TabsList,
  TabsPanel,
  TabsTab,
  Alert,
} from '@mantine/core';
import { Play, Copy } from 'lucide-react';
import { copyToClipboard } from '../utils';
import useVODStore from '../store/useVODStore';
import useVideoStore from '../store/useVideoStore';
import useSettingsStore from '../store/settings';
import {
  formatDuration,
  getEpisodeAirdate,
  getEpisodeStreamUrl,
  getTmdbUrlLink,
  getYouTubeEmbedUrl,
  groupEpisodesBySeason,
  imdbUrl,
  sortBySeasonNumber,
  sortEpisodesList,
} from '../utils/components/SeriesModalUtils.js';
import { YouTubeTrailerModal } from './modals/YouTubeTrailerModal.jsx';
import VODSourceList from './VODSourceList.jsx';
import VODSourceMetadataModal from './VODSourceMetadataModal.jsx';
import VODExternalIds from './VODExternalIds.jsx';
import VODEnrichmentButton from './VODEnrichmentButton.jsx';
import VODCanonicalMetadataModal from './VODCanonicalMetadataModal.jsx';
import API from '../api';
import { showNotification } from '../utils/notificationUtils';

const Series = ({ displaySeries, onClickYouTubeTrailer }) => {
  return (
    <Flex gap="md" wrap="wrap">
      {displaySeries.series_image ||
      displaySeries.logo?.cache_url ||
      displaySeries.logo?.url ? (
        <Box style={{ flexShrink: 0 }}>
          <Image
            src={
              displaySeries.series_image ||
              displaySeries.logo?.cache_url ||
              displaySeries.logo?.url
            }
            width={200}
            height={300}
            alt={displaySeries.name}
            fit="contain"
            bdrs={8}
          />
        </Box>
      ) : (
        <Box
          w={200}
          h={300}
          display="flex"
          bdrs={8}
          style={{
            backgroundColor: '#404040',
            alignItems: 'center',
            justifyContent: 'center',
            flexShrink: 0,
          }}
        >
          <Play size={48} color="#666" />
        </Box>
      )}

      <Stack spacing="md" flex={1}>
        <Title order={3}>{displaySeries.name}</Title>

        {/* Original name if different */}
        {displaySeries.o_name &&
          displaySeries.o_name !== displaySeries.name && (
            <Text size="sm" c="dimmed" fs="italic">
              Original: {displaySeries.o_name}
            </Text>
          )}

        <Group spacing="md">
          {displaySeries.year && (
            <Badge color="blue">{displaySeries.year}</Badge>
          )}
          {displaySeries.rating && (
            <Badge color="yellow">{displaySeries.rating}</Badge>
          )}
          {displaySeries.age && (
            <Badge color="orange">{displaySeries.age}</Badge>
          )}
          <Badge color="purple">Series</Badge>
          {displaySeries.episode_count && (
            <Badge color="gray">{displaySeries.episode_count} episodes</Badge>
          )}
          {displaySeries.is_anime && <Badge color="pink">Anime</Badge>}
          {displaySeries.adult && <Badge color="red">Adult</Badge>}
        </Group>

        <VODExternalIds
          contentType="series"
          contentId={displaySeries.id}
          tmdb={displaySeries.tmdb}
          tmdbId={displaySeries.tmdb_id}
          imdbId={displaySeries.imdb_id}
        />

        {/* Release date */}
        {displaySeries.release_date && (
          <Text size="sm" c="dimmed">
            <strong>Release Date:</strong> {displaySeries.release_date}
          </Text>
        )}

        {displaySeries.genre && (
          <Text size="sm" c="dimmed">
            <strong>Genre:</strong> {displaySeries.genre}
          </Text>
        )}

        {displaySeries.keywords?.length > 0 && (
          <Text size="sm" c="dimmed">
            <strong>Keywords:</strong>{' '}
            {displaySeries.keywords
              .map((row) => (typeof row === 'string' ? row : row?.name))
              .filter(Boolean)
              .join(', ')}
          </Text>
        )}

        {displaySeries.director && (
          <Text size="sm" c="dimmed">
            <strong>Director:</strong> {displaySeries.director}
          </Text>
        )}

        {displaySeries.cast && (
          <Text size="sm" c="dimmed">
            <strong>Cast:</strong> {displaySeries.cast}
          </Text>
        )}

        {displaySeries.crew && (
          <Text size="sm" c="dimmed">
            <strong>Crew:</strong> {displaySeries.crew}
          </Text>
        )}

        {displaySeries.country && (
          <Text size="sm" c="dimmed">
            <strong>Country:</strong> {displaySeries.country}
          </Text>
        )}

        {/* Description */}
        {displaySeries.description && (
          <Box>
            <Text size="sm" weight={500} mb={8}>
              Description
            </Text>
            <Text size="sm">{displaySeries.description}</Text>
          </Box>
        )}

        {/* Watch Trailer button if available */}
        {displaySeries.youtube_trailer && (
          <Button
            variant="outline"
            color="red"
            mt="auto"
            style={{ alignSelf: 'flex-start' }}
            onClick={onClickYouTubeTrailer}
          >
            Watch Trailer
          </Button>
        )}
      </Stack>
    </Flex>
  );
};

const Episode = ({ episode, displaySeries }) => {
  return (
    <Stack spacing="sm">
      {/* Episode Image and Description Row */}
      <Flex gap="md">
        {/* Episode Image */}
        {episode.movie_image && (
          <Box style={{ flexShrink: 0 }}>
            <Image
              src={episode.movie_image}
              width={120}
              height={160}
              alt={episode.name}
              fit="cover"
              bdrs={4}
            />
          </Box>
        )}

        {/* Episode Description */}
        <Box flex={1}>
          {episode.description && (
            <Box>
              <Text size="sm" weight={500} mb={4}>
                Description
              </Text>
              <Text size="sm" c="dimmed">
                {episode.description}
              </Text>
            </Box>
          )}
        </Box>
      </Flex>

      {/* Additional Episode Details */}
      <Group spacing="xl">
        {episode.rating && (
          <Box>
            <Text size="xs" weight={500} c="dimmed" mb={2}>
              Rating
            </Text>
            <Badge color="yellow" size="sm">
              {episode.rating}
            </Badge>
          </Box>
        )}
        {/* IMDb and TMDb badges for episode */}
        {(episode.imdb_id || displaySeries.tmdb_id) && (
          <Box>
            <Text size="xs" weight={500} c="dimmed" mb={2}>
              Links
            </Text>
            {episode.imdb_id && (
              <Badge
                color="yellow"
                component="a"
                href={imdbUrl(episode.imdb_id)}
                target="_blank"
                rel="noopener noreferrer"
                style={{ cursor: 'pointer' }}
              >
                IMDb
              </Badge>
            )}
            {displaySeries.tmdb_id && (
              <Badge
                color="cyan"
                component="a"
                href={getTmdbUrlLink(displaySeries, episode)}
                target="_blank"
                rel="noopener noreferrer"
                style={{ cursor: 'pointer' }}
              >
                TMDb
              </Badge>
            )}
          </Box>
        )}

        {episode.director && (
          <Box>
            <Text size="xs" weight={500} c="dimmed" mb={2}>
              Director
            </Text>
            <Text size="sm">{episode.director}</Text>
          </Box>
        )}

        {episode.actors && (
          <Box>
            <Text size="xs" weight={500} c="dimmed" mb={2}>
              Cast
            </Text>
            <Text size="sm" lineClamp={2}>
              {episode.actors}
            </Text>
          </Box>
        )}
      </Group>

      {/* Technical Details */}
      {(episode.bitrate || episode.video || episode.audio) && (
        <Box>
          <Text size="xs" weight={500} c="dimmed" mb={4}>
            Technical Details
          </Text>
          <Stack spacing={2}>
            {episode.bitrate && episode.bitrate > 0 && (
              <Text size="xs" c="dimmed">
                <strong>Bitrate:</strong> {episode.bitrate} kbps
              </Text>
            )}
            {episode.video && Object.keys(episode.video).length > 0 && (
              <Text size="xs" c="dimmed">
                <strong>Video:</strong>{' '}
                {episode.video.codec_long_name || episode.video.codec_name}
                {episode.video.width && episode.video.height
                  ? `, ${episode.video.width}x${episode.video.height}`
                  : ''}
              </Text>
            )}
            {episode.audio && Object.keys(episode.audio).length > 0 && (
              <Text size="xs" c="dimmed">
                <strong>Audio:</strong>{' '}
                {episode.audio.codec_long_name || episode.audio.codec_name}
                {episode.audio.channels
                  ? `, ${episode.audio.channels} channels`
                  : ''}
              </Text>
            )}
          </Stack>
        </Box>
      )}

      {/* Provider Information */}
      {episode.m3u_account && (
        <Group spacing="md">
          <Text size="xs" weight={500} c="dimmed">
            Provider:
          </Text>
          <Badge color="blue" variant="light" size="sm">
            {episode.m3u_account.name || episode.m3u_account}
          </Badge>
        </Group>
      )}
    </Stack>
  );
};

const SeriesModal = ({
  series,
  opened,
  onClose,
  onMetadataChanged,
  onCanonicalMoved,
  initialRelationId = null,
  allowSourceEditing = true,
  profileCandidates = null,
  profileCandidatesLoading = false,
  profileCandidatesError = '',
}) => {
  const fetchSeriesInfo = useVODStore((state) => state.fetchSeriesInfo);
  const fetchSeriesProviders = useVODStore(
    (state) => state.fetchSeriesProviders
  );
  const showVideo = useVideoStore((s) => s.showVideo);
  const env_mode = useSettingsStore((s) => s.environment.env_mode);

  const [detailedSeries, setDetailedSeries] = useState(null);
  const [canonicalSeriesDetails, setCanonicalSeriesDetails] = useState(null);
  const [detailedSeriesProviderId, setDetailedSeriesProviderId] =
    useState(null);
  const [loadingDetails, setLoadingDetails] = useState(false);
  const [activeTab, setActiveTab] = useState(null);
  const [expandedEpisode, setExpandedEpisode] = useState(null);
  const [trailerModalOpened, setTrailerModalOpened] = useState(false);
  const [trailerUrl, setTrailerUrl] = useState('');
  const [providers, setProviders] = useState([]);
  const [selectedProvider, setSelectedProvider] = useState(null);
  const [editingProvider, setEditingProvider] = useState(null);
  const [editingCanonical, setEditingCanonical] = useState(false);
  const [unlockingMetadata, setUnlockingMetadata] = useState(false);
  const [dataView, setDataView] = useState('primary');
  const [loadingProviders, setLoadingProviders] = useState(false);
  const providersRequestIdRef = useRef(0);
  const detailsRequestIdRef = useRef(0);
  const profilePreferenceAppliedRef = useRef('');
  const seriesRef = useRef(series);
  seriesRef.current = series;

  useEffect(() => {
    if (opened && series?.id) {
      const providersRequestId = ++providersRequestIdRef.current;
      const detailsRequestId = ++detailsRequestIdRef.current;
      setLoadingDetails(true);
      setLoadingProviders(true);
      fetchSeriesProviders(series.id)
        .then((providersData) => {
          if (providersRequestIdRef.current !== providersRequestId) return null;
          setProviders(providersData);
          // Profile ordering can supersede only the detail/episode request.
          // The provider list itself is already complete at this point.
          setLoadingProviders(false);
          const provider =
            providersData.find(
              (item) => String(item.id) === String(initialRelationId)
            ) ||
            providersData[0] ||
            null;
          setSelectedProvider(provider);
          return (
            provider
              ? fetchSeriesInfo(series.id, provider.id)
              : fetchSeriesInfo(series.id)
          ).then((details) => ({ details, providerId: provider?.id || null }));
        })
        .then((result) => {
          if (
            !result?.details ||
            detailsRequestIdRef.current !== detailsRequestId
          ) {
            return;
          }
          const { details, providerId } = result;
          setDetailedSeries(details);
          setCanonicalSeriesDetails(details);
          setDetailedSeriesProviderId(providerId);
          if (providerId && details.source_metadata) {
            setProviders((current) =>
              current.map((provider) =>
                String(provider.id) === String(providerId)
                  ? { ...provider, source_metadata: details.source_metadata }
                  : provider
              )
            );
          }
        })
        .catch((error) => {
          if (detailsRequestIdRef.current !== detailsRequestId) return;
          console.error('Failed to fetch series providers:', error);
          setDetailedSeries(seriesRef.current);
        })
        .finally(() => {
          if (providersRequestIdRef.current === providersRequestId) {
            setLoadingProviders(false);
          }
          if (detailsRequestIdRef.current === detailsRequestId) {
            setLoadingDetails(false);
          }
        });
    }
  }, [
    initialRelationId,
    opened,
    series?.id,
    fetchSeriesInfo,
    fetchSeriesProviders,
  ]);

  useEffect(() => {
    if (!opened) {
      providersRequestIdRef.current += 1;
      detailsRequestIdRef.current += 1;
      profilePreferenceAppliedRef.current = '';
      setDetailedSeries(null);
      setCanonicalSeriesDetails(null);
      setDetailedSeriesProviderId(null);
      setLoadingDetails(false);
      setProviders([]);
      setSelectedProvider(null);
      setEditingProvider(null);
      setEditingCanonical(false);
      setDataView('primary');
      setLoadingProviders(false);
    }
  }, [opened]);

  useEffect(() => {
    if (!opened || !providers.length || !profileCandidates?.results?.length) {
      return;
    }
    const preferred = profileCandidates.results.find(
      (row) => row.allowed && row.position === 1
    );
    const signature = `${profileCandidates.profile_id}:${profileCandidates.canonical_id}:${profileCandidates.edition_key || ''}:${preferred?.relation_id || ''}`;
    if (!preferred || profilePreferenceAppliedRef.current === signature) return;
    const provider = providers.find(
      (candidate) => String(candidate.id) === String(preferred.relation_id)
    );
    if (!provider) return;
    profilePreferenceAppliedRef.current = signature;
    setSelectedProvider(provider);
    setDetailedSeriesProviderId(null);
    const requestId = ++detailsRequestIdRef.current;
    setLoadingDetails(true);
    setDetailedSeries((current) =>
      current
        ? { ...current, episodesList: [], source_metadata: null }
        : current
    );
    fetchSeriesInfo(series.id, provider.id)
      .then((details) => {
        if (detailsRequestIdRef.current !== requestId) return;
        setCanonicalSeriesDetails((current) => current || details);
        setDetailedSeries(details);
        setDetailedSeriesProviderId(provider.id);
        if (details.source_metadata) {
          setProviders((current) =>
            current.map((candidate) =>
              String(candidate.id) === String(provider.id)
                ? { ...candidate, source_metadata: details.source_metadata }
                : candidate
            )
          );
        }
      })
      .catch(() => {})
      .finally(() => {
        if (detailsRequestIdRef.current === requestId) setLoadingDetails(false);
      });
  }, [fetchSeriesInfo, opened, profileCandidates, providers, series?.id]);

  // Get episodes from the store based on the series ID
  const seriesEpisodes = React.useMemo(() => {
    if (!detailedSeries) return [];

    // Try to get episodes from the fetched data
    if (detailedSeries.episodesList) {
      return sortEpisodesList(detailedSeries.episodesList);
    }

    // If no episodes in detailed series, return empty array
    return [];
  }, [detailedSeries]);

  // Group episodes by season
  const episodesBySeason = React.useMemo(() => {
    return groupEpisodesBySeason(seriesEpisodes);
  }, [seriesEpisodes]);

  // Get available seasons sorted
  const seasons = React.useMemo(() => {
    return sortBySeasonNumber(episodesBySeason);
  }, [episodesBySeason]);

  // Update active tab when seasons change or modal opens
  React.useEffect(() => {
    if (seasons.length > 0) {
      if (
        !activeTab ||
        !seasons.includes(parseInt(activeTab.replace('season-', '')))
      ) {
        setActiveTab(`season-${seasons[0]}`);
      }
    }
  }, [seasons, activeTab]);

  // Reset tab when modal closes
  React.useEffect(() => {
    if (!opened) {
      setActiveTab(null);
    }
  }, [opened]);

  const handlePlayEpisode = (episode) => {
    const streamUrl = getEpisodeStreamUrl(episode, selectedProvider, env_mode);
    showVideo(streamUrl, 'vod', episode);
  };

  const handleCopyEpisodeLink = async (episode) => {
    const streamUrl = getEpisodeStreamUrl(episode, selectedProvider, env_mode);
    await copyToClipboard(streamUrl, {
      successTitle: 'Link Copied!',
      successMessage: 'Episode link copied to clipboard',
    });
  };

  const handleEpisodeRowClick = (episode) => {
    setExpandedEpisode(expandedEpisode === episode.id ? null : episode.id);
  };

  const onClickYouTubeTrailer = () => {
    setTrailerUrl(getYouTubeEmbedUrl(displaySeries.youtube_trailer));
    setTrailerModalOpened(true);
  };

  const onChangeSelectedProvider = (provider) => {
    if (!provider || provider.id === selectedProvider?.id) return;
    setSelectedProvider(provider);
    if (provider) {
      setDetailedSeriesProviderId(null);
      const requestId = ++detailsRequestIdRef.current;
      setLoadingDetails(true);
      // Clear episodes immediately so the previous provider's list cannot flash
      setDetailedSeries((prev) =>
        prev ? { ...prev, episodesList: [], source_metadata: null } : prev
      );
      fetchSeriesInfo(series.id, provider.id)
        .then((details) => {
          if (detailsRequestIdRef.current !== requestId) return;
          setCanonicalSeriesDetails((current) => current || details);
          setDetailedSeries(details);
          setDetailedSeriesProviderId(provider.id);
          if (details.source_metadata) {
            setProviders((current) =>
              current.map((candidate) =>
                String(candidate.id) === String(provider.id)
                  ? { ...candidate, source_metadata: details.source_metadata }
                  : candidate
              )
            );
          }
        })
        .catch(() => {})
        .finally(() => {
          if (detailsRequestIdRef.current === requestId) {
            setLoadingDetails(false);
          }
        });
    }
  };

  const updateProvider = (updatedProvider) => {
    setProviders((current) =>
      current.map((provider) =>
        provider.id === updatedProvider.id ? updatedProvider : provider
      )
    );
    setSelectedProvider((current) =>
      current?.id === updatedProvider.id ? updatedProvider : current
    );
    setDetailedSeries((current) =>
      String(detailedSeriesProviderId || '') ===
        String(updatedProvider.id || '') && current
        ? { ...current, source_metadata: updatedProvider.source_metadata }
        : current
    );
    onMetadataChanged?.();
  };

  const reloadAfterEnrichment = async (result = null) => {
    if (result?.target && Number(result.target.id) !== Number(series.id)) {
      await onMetadataChanged?.();
      if (onCanonicalMoved) {
        onCanonicalMoved({
          ...result.target,
          name: result.target.title,
          contentType: 'series',
        });
      } else {
        onClose();
      }
      return;
    }
    const requestId = ++detailsRequestIdRef.current;
    const details = await fetchSeriesInfo(
      series.id,
      selectedProvider?.id || null
    );
    if (detailsRequestIdRef.current === requestId) {
      setDetailedSeries(details);
      setCanonicalSeriesDetails(details);
      setDetailedSeriesProviderId(selectedProvider?.id || null);
    }
    await onMetadataChanged?.();
  };

  const unlockMetadata = async () => {
    setUnlockingMetadata(true);
    try {
      await API.unlockVODMetadata([
        { id: series.id, content_type: 'series' },
      ]);
      await reloadAfterEnrichment();
      showNotification({
        title: 'Automatic metadata matching unlocked',
        message: 'This title can be processed by automatic cleanup and TMDB matching again.',
        color: 'green',
      });
    } catch (error) {
      showNotification({
        title: 'Metadata matching could not be unlocked',
        message: error?.body?.detail || error?.message || 'Please retry.',
        color: 'red',
      });
    } finally {
      setUnlockingMetadata(false);
    }
  };

  if (!series) return null;

  const canonicalDetails = canonicalSeriesDetails || detailedSeries;
  const tmdb = canonicalDetails?.tmdb || series.tmdb || {};
  const metadataAutoLocked = Boolean(
    tmdb.metadata_auto_locked ?? series.metadata_auto_locked
  );
  const primaryLanguage = tmdb.primary_language || tmdb.languages?.[0] || '';
  const secondaryLanguage =
    tmdb.secondary_language || tmdb.languages?.[1] || '';
  const localized = tmdb.localized || {};
  const metadataMatched = (tmdb.status || series.tmdb_status) === 'matched';
  const metadataAvailable =
    metadataMatched ||
    (tmdb.status || series.tmdb_status) === 'manual' ||
    Object.keys(localized).length > 0;
  const canonicalSeries = canonicalDetails?.canonical || series;
  const localizedCanonical = (language, secondary = false) => {
    const values = localized[language] || {};
    return {
      ...series,
      ...canonicalSeries,
      name: values.title || canonicalSeries.name || series.name,
      description:
        values.overview ||
        (secondary ? '' : canonicalSeries.description || series.description),
      genre:
        (tmdb.genres || [])
          .map((row) => row.name)
          .filter(Boolean)
          .join(', ') ||
        canonicalSeries.genre ||
        series.genre,
      rating: tmdb.rating || canonicalSeries.rating || series.rating,
      release_date: tmdb.release_date || canonicalSeries.release_date || '',
      director: tmdb.director || canonicalSeries.director || '',
      cast: tmdb.actors || canonicalSeries.cast || '',
      crew: tmdb.crew || canonicalSeries.crew || '',
      country: tmdb.country || canonicalSeries.country || '',
      age: tmdb.age_rating || canonicalSeries.age || '',
      youtube_trailer:
        tmdb.youtube_trailer || canonicalSeries.youtube_trailer || '',
      keywords: tmdb.keywords || [],
      is_anime: Boolean(tmdb.is_anime),
      adult: Boolean(tmdb.adult),
      series_image:
        series.artwork_url ||
        tmdb.poster_url ||
        canonicalSeries.movie_image ||
        series.series_image ||
        '',
      backdrop_path: tmdb.backdrop_url
        ? [tmdb.backdrop_url]
        : canonicalSeries.backdrop_path || series.backdrop_path || [],
      tmdb,
      tmdb_id: tmdb.id || series.tmdb_id,
      imdb_id: tmdb.external_ids?.imdb_id || series.imdb_id,
      o_name: series.o_name || '',
    };
  };
  const providerIds = selectedProvider?.provider_external_ids || {};
  const activeProviderDetails =
    String(detailedSeriesProviderId || '') ===
    String(selectedProvider?.id || '')
      ? detailedSeries
      : null;
  const providerSeries = activeProviderDetails
    ? {
        ...activeProviderDetails,
        tmdb_id: providerIds.tmdb_id || '',
        imdb_id: providerIds.imdb_id || '',
        tmdb: {
          id: providerIds.tmdb_id || '',
          external_ids: { imdb_id: providerIds.imdb_id || '' },
        },
      }
    : series;
  const displaySeries =
    dataView === 'provider'
      ? providerSeries
      : localizedCanonical(
          dataView === 'secondary' ? secondaryLanguage : primaryLanguage,
          dataView === 'secondary'
        );
  const secondaryValues = localized[secondaryLanguage] || {};
  const secondaryTranslationAvailable = Boolean(
    secondaryValues.title || secondaryValues.overview || secondaryValues.tagline
  );

  return (
    <>
      <Modal
        opened={opened}
        onClose={onClose}
        size="96vw"
        centered
        yOffset="2vh"
        lockScroll={false}
        scrollAreaComponent={Modal.NativeScrollArea}
        styles={{
          content: {
            maxWidth: 1400,
            maxHeight: '96vh',
            backgroundColor: 'var(--mantine-color-body)',
          },
          header: {
            position: 'absolute',
            top: 0,
            right: 0,
            zIndex: 10,
            background: 'transparent',
            padding: 'var(--mantine-spacing-md)',
          },
          body: {
            padding: 0,
            backgroundColor: 'var(--mantine-color-body)',
          },
        }}
      >
        <Box
          style={{
            position: 'relative',
            minHeight: 400,
            backgroundColor: 'var(--mantine-color-body)',
          }}
        >
          {/* Backdrop image as background */}
          {displaySeries.backdrop_path &&
            displaySeries.backdrop_path.length > 0 && (
              <>
                <Image
                  src={displaySeries.backdrop_path[0]}
                  alt={`${displaySeries.name} backdrop`}
                  fit="cover"
                  style={{
                    position: 'absolute',
                    top: 0,
                    left: 0,
                    width: '100%',
                    height: '100%',
                    objectFit: 'cover',
                    zIndex: 0,
                    borderRadius: 8,
                    filter: 'blur(2px) brightness(0.5)',
                  }}
                />
                {/* Overlay for readability */}
                <Box
                  style={{
                    position: 'absolute',
                    top: 0,
                    left: 0,
                    width: '100%',
                    height: '100%',
                    background:
                      'linear-gradient(180deg, rgba(24,24,27,0.85) 60%, rgba(24,24,27,1) 100%)',
                    zIndex: 1,
                    borderRadius: 8,
                  }}
                />
              </>
            )}

          {/* Modal content above backdrop */}
          <Box p="md" pt="xl" style={{ position: 'relative', zIndex: 2 }}>
            <Stack spacing="md">
              <Group
                justify="space-between"
                align="flex-start"
                wrap="wrap"
                pr="xl"
              >
                {allowSourceEditing ? (
                  <VODEnrichmentButton
                    onClick={() => setEditingCanonical(true)}
                    loading={loadingDetails}
                    locked={metadataAutoLocked}
                    unlocking={unlockingMetadata}
                    onUnlock={unlockMetadata}
                  />
                ) : (
                  <Box />
                )}
                <Group gap={2} wrap="wrap" aria-label="Metadata source">
                  <Button
                    size="xs"
                    variant={dataView === 'primary' ? 'filled' : 'default'}
                    onClick={() => setDataView('primary')}
                  >
                    {metadataAvailable ? 'Primary' : 'Canonical'}
                    {metadataAvailable && primaryLanguage
                      ? ` · ${primaryLanguage}`
                      : ''}
                  </Button>
                  {metadataAvailable && secondaryLanguage && (
                    <Button
                      size="xs"
                      variant={dataView === 'secondary' ? 'filled' : 'default'}
                      onClick={() => setDataView('secondary')}
                    >
                      Secondary · {secondaryLanguage}
                    </Button>
                  )}
                  <Button
                    size="xs"
                    variant={dataView === 'provider' ? 'filled' : 'default'}
                    onClick={() => setDataView('provider')}
                  >
                    Provider
                  </Button>
                </Group>
              </Group>
              {dataView === 'secondary' && !secondaryTranslationAvailable && (
                <Alert color="yellow" py="xs">
                  TMDB returned no separate {secondaryLanguage} translation for
                  this title. Shared facts remain visible, but primary text is
                  not copied into the secondary view.
                </Alert>
              )}
              {loadingDetails && !canonicalSeriesDetails && (
                <Group spacing="xs" mb={8}>
                  <Loader size="xs" />
                  <Text size="xs" color="dimmed">
                    Loading series details and episodes...
                  </Text>
                </Group>
              )}

              {/* Series poster and basic info */}
              <Series
                displaySeries={displaySeries}
                onClickYouTubeTrailer={onClickYouTubeTrailer}
              />

              <Group gap="xs" mt="md">
                <Title order={4}>Sources ({providers.length})</Title>
                {(loadingProviders || loadingDetails) && <Loader size="xs" />}
              </Group>
              {providers.length > 0 ? (
                <VODSourceList
                  providers={providers}
                  selectedProvider={selectedProvider}
                  selectedSourceMetadata={
                    activeProviderDetails?.source_metadata
                  }
                  contentType="series"
                  disabled={loadingProviders || loadingDetails}
                  onSelect={onChangeSelectedProvider}
                  onEdit={allowSourceEditing ? setEditingProvider : undefined}
                  profileCandidates={profileCandidates}
                  profileCandidatesLoading={profileCandidatesLoading}
                  profileCandidatesError={profileCandidatesError}
                />
              ) : !loadingProviders ? (
                <Text c="dimmed" ta="center" py="md">
                  No exact source relation is available for this series.
                </Text>
              ) : null}

              <Divider />

              <Title order={4}>
                Episodes
                {seriesEpisodes.length > 0 && <> ({seriesEpisodes.length})</>}
              </Title>

              {!selectedProvider ? (
                <Text color="dimmed" align="center" py="xl">
                  Select an exact source above to load its seasons and episodes.
                </Text>
              ) : loadingDetails ? (
                <Flex justify="center" py="xl">
                  <Loader />
                </Flex>
              ) : seasons.length > 0 ? (
                <Tabs value={activeTab} onChange={setActiveTab}>
                  <TabsList>
                    {seasons.map((season) => (
                      <TabsTab key={season} value={`season-${season}`}>
                        Season {season}
                      </TabsTab>
                    ))}
                  </TabsList>

                  {seasons.map((season) => (
                    <TabsPanel key={season} value={`season-${season}`} pt="md">
                      <Table striped highlightOnHover>
                        <TableThead>
                          <TableTr>
                            <TableTh style={{ width: '60px' }}>Ep</TableTh>
                            <TableTh>Title</TableTh>
                            <TableTh style={{ width: '80px' }}>
                              Duration
                            </TableTh>
                            <TableTh style={{ width: '60px' }}>Date</TableTh>
                            <TableTh style={{ width: '70px' }}>Format</TableTh>
                            <TableTh style={{ width: '80px' }}>Action</TableTh>
                          </TableTr>
                        </TableThead>
                        <TableTbody>
                          {episodesBySeason[season]?.map((episode) => (
                            <React.Fragment key={episode.id}>
                              <TableTr
                                style={{ cursor: 'pointer' }}
                                onClick={() => handleEpisodeRowClick(episode)}
                              >
                                <TableTd>
                                  <Badge size="sm" variant="outline">
                                    {episode.episode_number || '?'}
                                  </Badge>
                                </TableTd>
                                <TableTd>
                                  <Stack spacing={2}>
                                    <Text size="sm" weight={500}>
                                      {episode.name}
                                    </Text>
                                    {episode.genre && (
                                      <Text size="xs" color="dimmed">
                                        {episode.genre}
                                      </Text>
                                    )}
                                  </Stack>
                                </TableTd>
                                <TableTd>
                                  <Text size="xs" color="dimmed">
                                    {formatDuration(episode.duration_secs)}
                                  </Text>
                                </TableTd>
                                <TableTd>
                                  <Text size="xs" color="dimmed">
                                    {getEpisodeAirdate(episode)}
                                  </Text>
                                </TableTd>
                                <TableTd>
                                  <Text size="xs" color="dimmed">
                                    {episode.container_extension || '—'}
                                  </Text>
                                </TableTd>
                                <TableTd>
                                  <Group spacing="xs">
                                    <ActionIcon
                                      variant="filled"
                                      color="blue"
                                      size="sm"
                                      disabled={
                                        providers.length > 0 &&
                                        !selectedProvider
                                      }
                                      onClick={(e) => {
                                        e.stopPropagation();
                                        handlePlayEpisode(episode);
                                      }}
                                    >
                                      <Play size={12} />
                                    </ActionIcon>
                                    <ActionIcon
                                      variant="outline"
                                      color="gray"
                                      size="sm"
                                      onClick={(e) => {
                                        e.stopPropagation();
                                        handleCopyEpisodeLink(episode);
                                      }}
                                    >
                                      <Copy size={12} />
                                    </ActionIcon>
                                  </Group>
                                </TableTd>
                              </TableTr>
                              {expandedEpisode === episode.id && (
                                <TableTr>
                                  <TableTd
                                    colSpan={5}
                                    p={16}
                                    style={{
                                      backgroundColor: '#2A2A2E',
                                    }}
                                  >
                                    <Episode
                                      episode={episode}
                                      displaySeries={displaySeries}
                                    />
                                  </TableTd>
                                </TableTr>
                              )}
                            </React.Fragment>
                          ))}
                        </TableTbody>
                      </Table>
                    </TabsPanel>
                  ))}
                </Tabs>
              ) : (
                <Text color="dimmed" align="center" py="xl">
                  No episodes found for this series.
                </Text>
              )}
            </Stack>
          </Box>
        </Box>
      </Modal>

      {/* YouTube Trailer Modal */}
      <YouTubeTrailerModal
        opened={trailerModalOpened}
        onClose={() => setTrailerModalOpened(false)}
        trailerUrl={trailerUrl}
      />
      <VODSourceMetadataModal
        provider={editingProvider}
        contentType="series"
        opened={Boolean(editingProvider)}
        onClose={() => setEditingProvider(null)}
        onSaved={updateProvider}
        onMoved={(result) => {
          setEditingProvider(null);
          onMetadataChanged?.();
          if (result?.target && onCanonicalMoved) {
            onCanonicalMoved({
              ...result.target,
              name: result.target.title,
              contentType: 'series',
            });
          } else {
            onClose();
          }
        }}
      />
      <VODCanonicalMetadataModal
        opened={editingCanonical}
        onClose={() => setEditingCanonical(false)}
        content={localizedCanonical(primaryLanguage, false)}
        contentId={series.id}
        contentType="series"
        onSaved={reloadAfterEnrichment}
      />
    </>
  );
};

export default SeriesModal;
