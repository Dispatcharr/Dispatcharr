import React, { useState, useEffect } from 'react';
import {
  Box,
  Button,
  Flex,
  Group,
  Image,
  Text,
  Title,
  Select,
  Badge,
  Loader,
  Stack,
  ActionIcon,
  Modal,
  Tabs,
  Table,
  Divider,
} from '@mantine/core';
import { Play, Copy } from 'lucide-react';
import { notifications } from '@mantine/notifications';
import { copyToClipboard } from '../utils';
import useVODStore from '../store/useVODStore';
import useVideoStore from '../store/useVideoStore';
import useSettingsStore from '../store/settings';

const imdbUrl = (imdb_id) =>
  imdb_id ? `https://www.imdb.com/title/${imdb_id}` : '';
const tmdbUrl = (tmdb_id, type = 'movie') =>
  tmdb_id ? `https://www.themoviedb.org/${type}/${tmdb_id}` : '';
const formatDuration = (seconds) => {
  if (!seconds) return '';
  const hours = Math.floor(seconds / 3600);
  const mins = Math.floor((seconds % 3600) / 60);
  const secs = seconds % 60;
  return hours > 0 ? `${hours}h ${mins}m` : `${mins}m ${secs}s`;
};

const formatStreamLabel = (relation) => {
  // Create a label for the stream that includes provider name and stream-specific info
  const provider = relation.m3u_account.name;
  const streamId = relation.stream_id;

  // Try to extract quality info - prioritizing the new quality_info field from backend
  let qualityInfo = '';

  // 1. Check the new quality_info field from backend (PRIMARY)
  if (relation.quality_info) {
    if (relation.quality_info.quality) {
      qualityInfo = ` - ${relation.quality_info.quality}`;
    } else if (relation.quality_info.resolution) {
      qualityInfo = ` - ${relation.quality_info.resolution}`;
    } else if (relation.quality_info.bitrate) {
      qualityInfo = ` - ${relation.quality_info.bitrate}`;
    }
  }

  // 2. Fallback: Check custom_properties detailed info structure
  if (qualityInfo === '' && relation.custom_properties) {
    const props = relation.custom_properties;

    // Check detailed_info structure (where the real data is!)
    if (qualityInfo === '' && props.detailed_info) {
      const detailedInfo = props.detailed_info;

      // Extract from video resolution
      if (
        detailedInfo.video &&
        detailedInfo.video.width &&
        detailedInfo.video.height
      ) {
        const width = detailedInfo.video.width;
        const height = detailedInfo.video.height;

        // Prioritize width for quality detection (handles ultrawide/cinematic aspect ratios)
        if (width >= 3840) {
          qualityInfo = ' - 4K';
        } else if (width >= 1920) {
          qualityInfo = ' - 1080p';
        } else if (width >= 1280) {
          qualityInfo = ' - 720p';
        } else if (width >= 854) {
          qualityInfo = ' - 480p';
        } else {
          qualityInfo = ` - ${width}x${height}`;
        }
      }

      // Extract from movie name in detailed_info
      if (qualityInfo === '' && detailedInfo.name) {
        const name = detailedInfo.name;
        if (name.includes('4K') || name.includes('2160p')) {
          qualityInfo = ' - 4K';
        } else if (name.includes('1080p') || name.includes('FHD')) {
          qualityInfo = ' - 1080p';
        } else if (name.includes('720p') || name.includes('HD')) {
          qualityInfo = ' - 720p';
        } else if (name.includes('480p')) {
          qualityInfo = ' - 480p';
        }
      }
    }
  }

  // 3. Final fallback: Check stream name for quality markers
  if (qualityInfo === '' && relation.stream_name) {
    const streamName = relation.stream_name;
    if (streamName.includes('4K') || streamName.includes('2160p')) {
      qualityInfo = ' - 4K';
    } else if (streamName.includes('1080p') || streamName.includes('FHD')) {
      qualityInfo = ' - 1080p';
    } else if (streamName.includes('720p') || streamName.includes('HD')) {
      qualityInfo = ' - 720p';
    } else if (streamName.includes('480p')) {
      qualityInfo = ' - 480p';
    }
  }

  return `${provider}${qualityInfo}${streamId ? ` (Stream ${streamId})` : ''}`;
};

const SeriesModal = ({ series, opened, onClose }) => {
  const { fetchSeriesInfo, fetchSeriesProviders } = useVODStore();
  const showVideo = useVideoStore((s) => s.showVideo);
  const env_mode = useSettingsStore((s) => s.environment.env_mode);
  const [detailedSeries, setDetailedSeries] = useState(null);
  const [loadingDetails, setLoadingDetails] = useState(false);
  const [activeTab, setActiveTab] = useState(null);
  const [expandedEpisode, setExpandedEpisode] = useState(null);
  const [trailerModalOpened, setTrailerModalOpened] = useState(false);
  const [trailerUrl, setTrailerUrl] = useState('');
  const [providers, setProviders] = useState([]);
  const [selectedProvider, setSelectedProvider] = useState(null);
  const [loadingProviders, setLoadingProviders] = useState(false);

  useEffect(() => {
    if (opened && series) {
      // Fetch detailed series info which now includes episodes
      setLoadingDetails(true);
      fetchSeriesInfo(series.id)
        .then((details) => {
          setDetailedSeries(details);
          // Check if episodes were fetched
          if (!details.episodes_fetched) {
            // Episodes not yet fetched, may need to wait for background fetch
          }
        })
        .catch((error) => {
          console.warn(
            'Failed to fetch series details, using basic info:',
            error
          );
          setDetailedSeries(series); // Fallback to basic data
        })
        .finally(() => {
          setLoadingDetails(false);
        });

      // Fetch available providers
      setLoadingProviders(true);
      fetchSeriesProviders(series.id)
        .then((providersData) => {
          setProviders(providersData);
          // Set the first provider as default if none selected
          if (providersData.length > 0 && !selectedProvider) {
            setSelectedProvider(providersData[0]);
          }
        })
        .catch((error) => {
          console.error('Failed to fetch series providers:', error);
          setProviders([]);
        })
        .finally(() => {
          setLoadingProviders(false);
        });
    }
  }, [opened, series, fetchSeriesInfo, fetchSeriesProviders, selectedProvider]);

  useEffect(() => {
    if (!opened) {
      setDetailedSeries(null);
      setLoadingDetails(false);
      setProviders([]);
      setSelectedProvider(null);
      setLoadingProviders(false);
    }
  }, [opened]);

  // Get episodes from the store based on the series ID
  const seriesEpisodes = React.useMemo(() => {
    if (!detailedSeries) return [];

    // Try to get episodes from the fetched data
    if (detailedSeries.episodesList) {
      return detailedSeries.episodesList.sort((a, b) => {
        if (a.season_number !== b.season_number) {
          return (a.season_number || 0) - (b.season_number || 0);
        }
        return (a.episode_number || 0) - (b.episode_number || 0);
      });
    }

    // If no episodes in detailed series, return empty array
    return [];
  }, [detailedSeries]);

  // Group episodes by season
  const episodesBySeason = React.useMemo(() => {
    const grouped = {};
    seriesEpisodes.forEach((episode) => {
      const season = episode.season_number || 1;
      if (!grouped[season]) {
        grouped[season] = [];
      }
      grouped[season].push(episode);
    });
    return grouped;
  }, [seriesEpisodes]);

  // Get available seasons sorted
  const seasons = React.useMemo(() => {
    return Object.keys(episodesBySeason)
      .map(Number)
      .sort((a, b) => a - b);
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
    let streamUrl = `/proxy/vod/episode/${episode.uuid}`;

    // Add selected provider as query parameter if available
    if (selectedProvider) {
      // Use stream_id for most specific selection, fallback to account_id
      if (selectedProvider.stream_id) {
        streamUrl += `?stream_id=${encodeURIComponent(selectedProvider.stream_id)}`;
      } else {
        streamUrl += `?m3u_account_id=${selectedProvider.m3u_account.id}`;
      }
    }

    if (env_mode === 'dev') {
      streamUrl = `${window.location.protocol}//${window.location.hostname}:5656${streamUrl}`;
    } else {
      streamUrl = `${window.location.origin}${streamUrl}`;
    }
    showVideo(streamUrl, 'vod', episode);
  };

  const getEpisodeStreamUrl = (episode) => {
    let streamUrl = `/proxy/vod/episode/${episode.uuid}`;

    // Add selected provider as query parameter if available
    if (selectedProvider) {
      // Use stream_id for most specific selection, fallback to account_id
      if (selectedProvider.stream_id) {
        streamUrl += `?stream_id=${encodeURIComponent(selectedProvider.stream_id)}`;
      } else {
        streamUrl += `?m3u_account_id=${selectedProvider.m3u_account.id}`;
      }
    }

    if (env_mode === 'dev') {
      streamUrl = `${window.location.protocol}//${window.location.hostname}:5656${streamUrl}`;
    } else {
      streamUrl = `${window.location.origin}${streamUrl}`;
    }
    return streamUrl;
  };

  const handleCopyEpisodeLink = async (episode) => {
    const streamUrl = getEpisodeStreamUrl(episode);
    const success = await copyToClipboard(streamUrl);
    notifications.show({
      title: success ? 'Link Copied!' : 'Copy Failed',
      message: success
        ? 'Episode link copied to clipboard'
        : 'Failed to copy link to clipboard',
      color: success ? 'green' : 'red',
    });
  };

  const handleEpisodeRowClick = (episode) => {
    setExpandedEpisode(expandedEpisode === episode.id ? null : episode.id);
  };

  // Helper to get embeddable YouTube URL
  const getEmbedUrl = (url) => {
    if (!url) return '';
    // Accepts full YouTube URLs or just IDs
    const match = url.match(/(?:youtube\.com\/watch\?v=|youtu\.be\/)([\w-]+)/);
    const videoId = match ? match[1] : url;
    return `https://www.youtube.com/embed/${videoId}`;
  };

  if (!series) return null;

  // Use detailed data if available, otherwise use basic series data
  const displaySeries = detailedSeries || series;

  return (
    <>
      <Modal
        opened={opened}
        onClose={onClose}
        title={displaySeries.name}
        size="xl"
        centered
      >
        <Box style={{ position: 'relative', minHeight: 400 }}>
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
          <Box style={{ position: 'relative', zIndex: 2 }}>
            <Stack spacing="md">
              {loadingDetails && (
                <Group spacing="xs" mb={8}>
                  <Loader size="xs" />
                  <Text size="xs" color="dimmed">
                    Loading series details and episodes...
                  </Text>
                </Group>
              )}

              {/* Series poster and basic info */}
              <Flex gap="md">
                {displaySeries.series_image || displaySeries.logo?.url ? (
                  <Box style={{ flexShrink: 0 }}>
                    <Image
                      src={displaySeries.series_image || displaySeries.logo.url}
                      width={200}
                      height={300}
                      alt={displaySeries.name}
                      fit="contain"
                      style={{ borderRadius: '8px' }}
                    />
                  </Box>
                ) : (
                  <Box
                    style={{
                      width: 200,
                      height: 300,
                      backgroundColor: '#404040',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      borderRadius: '8px',
                      flexShrink: 0,
                    }}
                  >
                    <Play size={48} color="#666" />
                  </Box>
                )}

                <Stack spacing="md" style={{ flex: 1 }}>
                  <Title order={3}>{displaySeries.name}</Title>

                  {/* Original name if different */}
                  {displaySeries.o_name &&
                    displaySeries.o_name !== displaySeries.name && (
                      <Text
                        size="sm"
                        color="dimmed"
                        style={{ fontStyle: 'italic' }}
                      >
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
                      <Badge color="gray">
                        {displaySeries.episode_count} episodes
                      </Badge>
                    )}
                    {/* imdb_id and tmdb_id badges */}
                    {displaySeries.imdb_id && (
                      <Badge
                        color="yellow"
                        component="a"
                        href={imdbUrl(displaySeries.imdb_id)}
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
                        href={tmdbUrl(displaySeries.tmdb_id, 'tv')}
                        target="_blank"
                        rel="noopener noreferrer"
                        style={{ cursor: 'pointer' }}
                      >
                        TMDb
                      </Badge>
                    )}
                  </Group>

                  {/* Release date */}
                  {displaySeries.release_date && (
                    <Text size="sm" color="dimmed">
                      <strong>Release Date:</strong>{' '}
                      {displaySeries.release_date}
                    </Text>
                  )}

                  {displaySeries.genre && (
                    <Text size="sm" color="dimmed">
                      <strong>Genre:</strong> {displaySeries.genre}
                    </Text>
                  )}

                  {displaySeries.director && (
                    <Text size="sm" color="dimmed">
                      <strong>Director:</strong> {displaySeries.director}
                    </Text>
                  )}

                  {displaySeries.cast && (
                    <Text size="sm" color="dimmed">
                      <strong>Cast:</strong> {displaySeries.cast}
                    </Text>
                  )}

                  {displaySeries.country && (
                    <Text size="sm" color="dimmed">
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
                      style={{ marginTop: 'auto', alignSelf: 'flex-start' }}
                      onClick={() => {
                        setTrailerUrl(
                          getEmbedUrl(displaySeries.youtube_trailer)
                        );
                        setTrailerModalOpened(true);
                      }}
                    >
                      Watch Trailer
                    </Button>
                  )}
                </Stack>
              </Flex>

              {/* Provider Information */}
              <Box mt="md">
                <Text size="sm" weight={500} mb={4}>
                  Stream Selection
                  {loadingProviders && (
                    <Loader size="xs" style={{ marginLeft: 8 }} />
                  )}
                </Text>
                {providers.length === 0 &&
                !loadingProviders &&
                displaySeries.m3u_account ? (
                  <Group spacing="md">
                    <Badge color="blue" variant="light">
                      {displaySeries.m3u_account.name}
                    </Badge>
                  </Group>
                ) : providers.length === 1 ? (
                  <Group spacing="md">
                    <Badge color="blue" variant="light">
                      {providers[0].m3u_account.name}
                    </Badge>
                    {providers[0].stream_id && (
                      <Badge color="orange" variant="outline" size="xs">
                        Stream {providers[0].stream_id}
                      </Badge>
                    )}
                  </Group>
                ) : providers.length > 1 ? (
                  <Select
                    data={providers.map((provider) => ({
                      value: provider.id.toString(),
                      label: formatStreamLabel(provider),
                    }))}
                    value={selectedProvider?.id?.toString() || ''}
                    onChange={(value) => {
                      const provider = providers.find(
                        (p) => p.id.toString() === value
                      );
                      setSelectedProvider(provider);
                    }}
                    placeholder="Select stream..."
                    style={{ maxWidth: 350 }}
                    disabled={loadingProviders}
                  />
                ) : null}
              </Box>

              <Divider />

              <Title order={4}>
                Episodes
                {seriesEpisodes.length > 0 && <> ({seriesEpisodes.length})</>}
              </Title>

              {loadingDetails ? (
                <Flex justify="center" py="xl">
                  <Loader />
                </Flex>
              ) : seasons.length > 0 ? (
                <Tabs value={activeTab} onChange={setActiveTab}>
                  <Tabs.List>
                    {seasons.map((season) => (
                      <Tabs.Tab key={season} value={`season-${season}`}>
                        Season {season}
                      </Tabs.Tab>
                    ))}
                  </Tabs.List>

                  {seasons.map((season) => (
                    <Tabs.Panel key={season} value={`season-${season}`} pt="md">
                      <Table striped highlightOnHover>
                        <Table.Thead>
                          <Table.Tr>
                            <Table.Th style={{ width: '60px' }}>Ep</Table.Th>
                            <Table.Th>Title</Table.Th>
                            <Table.Th style={{ width: '80px' }}>
                              Duration
                            </Table.Th>
                            <Table.Th style={{ width: '60px' }}>Date</Table.Th>
                            <Table.Th style={{ width: '80px' }}>
                              Action
                            </Table.Th>
                          </Table.Tr>
                        </Table.Thead>
                        <Table.Tbody>
                          {episodesBySeason[season]?.map((episode) => (
                            <React.Fragment key={episode.id}>
                              <Table.Tr
                                style={{ cursor: 'pointer' }}
                                onClick={() => handleEpisodeRowClick(episode)}
                              >
                                <Table.Td>
                                  <Badge size="sm" variant="outline">
                                    {episode.episode_number || '?'}
                                  </Badge>
                                </Table.Td>
                                <Table.Td>
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
                                </Table.Td>
                                <Table.Td>
                                  <Text size="xs" color="dimmed">
                                    {formatDuration(episode.duration_secs)}
                                  </Text>
                                </Table.Td>
                                <Table.Td>
                                  <Text size="xs" color="dimmed">
                                    {episode.air_date
                                      ? new Date(
                                          episode.air_date
                                        ).toLocaleDateString()
                                      : 'N/A'}
                                  </Text>
                                </Table.Td>
                                <Table.Td>
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
                                </Table.Td>
                              </Table.Tr>
                              {expandedEpisode === episode.id && (
                                <Table.Tr>
                                  <Table.Td
                                    colSpan={5}
                                    style={{
                                      backgroundColor: '#2A2A2E',
                                      padding: '16px',
                                    }}
                                  >
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
                                              style={{ borderRadius: '4px' }}
                                            />
                                          </Box>
                                        )}

                                        {/* Episode Description */}
                                        <Box style={{ flex: 1 }}>
                                          {episode.description && (
                                            <Box>
                                              <Text
                                                size="sm"
                                                weight={500}
                                                mb={4}
                                              >
                                                Description
                                              </Text>
                                              <Text size="sm" color="dimmed">
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
                                            <Text
                                              size="xs"
                                              weight={500}
                                              color="dimmed"
                                              mb={2}
                                            >
                                              Rating
                                            </Text>
                                            <Badge color="yellow" size="sm">
                                              {episode.rating}
                                            </Badge>
                                          </Box>
                                        )}
                                        {/* IMDb and TMDb badges for episode */}
                                        {(episode.imdb_id ||
                                          displaySeries.tmdb_id) && (
                                          <Box>
                                            <Text
                                              size="xs"
                                              weight={500}
                                              color="dimmed"
                                              mb={2}
                                            >
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
                                                href={
                                                  tmdbUrl(
                                                    displaySeries.tmdb_id,
                                                    'tv'
                                                  ) +
                                                  (episode.season_number &&
                                                  episode.episode_number
                                                    ? `/season/${episode.season_number}/episode/${episode.episode_number}`
                                                    : '')
                                                }
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
                                            <Text
                                              size="xs"
                                              weight={500}
                                              color="dimmed"
                                              mb={2}
                                            >
                                              Director
                                            </Text>
                                            <Text size="sm">
                                              {episode.director}
                                            </Text>
                                          </Box>
                                        )}

                                        {episode.actors && (
                                          <Box>
                                            <Text
                                              size="xs"
                                              weight={500}
                                              color="dimmed"
                                              mb={2}
                                            >
                                              Cast
                                            </Text>
                                            <Text size="sm" lineClamp={2}>
                                              {episode.actors}
                                            </Text>
                                          </Box>
                                        )}
                                      </Group>

                                      {/* Technical Details */}
                                      {(episode.bitrate ||
                                        episode.video ||
                                        episode.audio) && (
                                        <Box>
                                          <Text
                                            size="xs"
                                            weight={500}
                                            color="dimmed"
                                            mb={4}
                                          >
                                            Technical Details
                                          </Text>
                                          <Stack spacing={2}>
                                            {episode.bitrate &&
                                              episode.bitrate > 0 && (
                                                <Text size="xs" color="dimmed">
                                                  <strong>Bitrate:</strong>{' '}
                                                  {episode.bitrate} kbps
                                                </Text>
                                              )}
                                            {episode.video &&
                                              Object.keys(episode.video)
                                                .length > 0 && (
                                                <Text size="xs" color="dimmed">
                                                  <strong>Video:</strong>{' '}
                                                  {episode.video
                                                    .codec_long_name ||
                                                    episode.video.codec_name}
                                                  {episode.video.width &&
                                                  episode.video.height
                                                    ? `, ${episode.video.width}x${episode.video.height}`
                                                    : ''}
                                                </Text>
                                              )}
                                            {episode.audio &&
                                              Object.keys(episode.audio)
                                                .length > 0 && (
                                                <Text size="xs" color="dimmed">
                                                  <strong>Audio:</strong>{' '}
                                                  {episode.audio
                                                    .codec_long_name ||
                                                    episode.audio.codec_name}
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
                                          <Text
                                            size="xs"
                                            weight={500}
                                            color="dimmed"
                                          >
                                            Provider:
                                          </Text>
                                          <Badge
                                            color="blue"
                                            variant="light"
                                            size="sm"
                                          >
                                            {episode.m3u_account.name ||
                                              episode.m3u_account}
                                          </Badge>
                                        </Group>
                                      )}
                                    </Stack>
                                  </Table.Td>
                                </Table.Tr>
                              )}
                            </React.Fragment>
                          ))}
                        </Table.Tbody>
                      </Table>
                    </Tabs.Panel>
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
      <Modal
        opened={trailerModalOpened}
        onClose={() => setTrailerModalOpened(false)}
        title="Trailer"
        size="xl"
        centered
      >
        <Box
          style={{ position: 'relative', paddingBottom: '56.25%', height: 0 }}
        >
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

export default SeriesModal;
