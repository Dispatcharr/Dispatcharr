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
  Modal,
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

const getTechnicalDetails = (selectedProvider, defaultVOD) => {
  let source = defaultVOD; // Default fallback

  // If a provider is selected, try to get technical details from various locations
  if (selectedProvider) {
    // 1. First try the movie/episode relation content
    const content = selectedProvider.movie || selectedProvider.episode;

    if (content && (content.bitrate || content.video || content.audio)) {
      source = content;
    }
    // 2. Try technical details directly on the relation object
    else if (
      selectedProvider.bitrate ||
      selectedProvider.video ||
      selectedProvider.audio
    ) {
      source = selectedProvider;
    }
    // 3. Try to extract from custom_properties detailed_info (where quality data is stored)
    else if (selectedProvider.custom_properties?.detailed_info) {
      const detailedInfo = selectedProvider.custom_properties.detailed_info;

      // Create a synthetic source from detailed_info
      const syntheticSource = {
        bitrate: detailedInfo.bitrate || null,
        video: detailedInfo.video || null,
        audio: detailedInfo.audio || null,
      };

      if (
        syntheticSource.bitrate ||
        syntheticSource.video ||
        syntheticSource.audio
      ) {
        source = syntheticSource;
      }
    }
  }

  return {
    bitrate: source?.bitrate,
    video: source?.video,
    audio: source?.audio,
  };
};

const VODModal = ({ vod, opened, onClose }) => {
  const [detailedVOD, setDetailedVOD] = useState(null);
  const [loadingDetails, setLoadingDetails] = useState(false);
  const [trailerModalOpened, setTrailerModalOpened] = useState(false);
  const [trailerUrl, setTrailerUrl] = useState('');
  const [providers, setProviders] = useState([]);
  const [selectedProvider, setSelectedProvider] = useState(null);
  const [loadingProviders, setLoadingProviders] = useState(false);
  const { fetchMovieDetailsFromProvider, fetchMovieProviders } = useVODStore();
  const showVideo = useVideoStore((s) => s.showVideo);
  const env_mode = useSettingsStore((s) => s.environment.env_mode);

  useEffect(() => {
    if (opened && vod) {
      // Fetch detailed VOD info if not already loaded
      if (!detailedVOD) {
        setLoadingDetails(true);
        fetchMovieDetailsFromProvider(vod.id)
          .then((details) => {
            setDetailedVOD(details);
          })
          .catch((error) => {
            console.warn(
              'Failed to fetch provider details, using basic info:',
              error
            );
            setDetailedVOD(vod); // Fallback to basic data
          })
          .finally(() => {
            setLoadingDetails(false);
          });
      }

      // Fetch available providers
      setLoadingProviders(true);
      fetchMovieProviders(vod.id)
        .then((providersData) => {
          setProviders(providersData);
          // Set the first provider as default if none selected
          if (providersData.length > 0 && !selectedProvider) {
            setSelectedProvider(providersData[0]);
          }
        })
        .catch((error) => {
          console.error('Failed to fetch providers:', error);
          setProviders([]);
        })
        .finally(() => {
          setLoadingProviders(false);
        });
    }
  }, [
    opened,
    vod,
    detailedVOD,
    fetchMovieDetailsFromProvider,
    fetchMovieProviders,
    selectedProvider,
  ]);

  useEffect(() => {
    if (!opened) {
      setDetailedVOD(null);
      setLoadingDetails(false);
      setTrailerModalOpened(false);
      setTrailerUrl('');
      setProviders([]);
      setSelectedProvider(null);
      setLoadingProviders(false);
    }
  }, [opened]);

  const getStreamUrl = () => {
    const vodToPlay = detailedVOD || vod;
    if (!vodToPlay) return null;

    let streamUrl = `/proxy/vod/movie/${vod.uuid}`;

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

  const handlePlayVOD = () => {
    const streamUrl = getStreamUrl();
    if (!streamUrl) return;
    const vodToPlay = detailedVOD || vod;
    showVideo(streamUrl, 'vod', vodToPlay);
  };

  const handleCopyLink = async () => {
    const streamUrl = getStreamUrl();
    if (!streamUrl) return;
    const success = await copyToClipboard(streamUrl);
    notifications.show({
      title: success ? 'Link Copied!' : 'Copy Failed',
      message: success
        ? 'Stream link copied to clipboard'
        : 'Failed to copy link to clipboard',
      color: success ? 'green' : 'red',
    });
  };

  // Helper to get embeddable YouTube URL
  const getEmbedUrl = (url) => {
    if (!url) return '';
    // Accepts full YouTube URLs or just IDs
    const match = url.match(/(?:youtube\.com\/watch\?v=|youtu\.be\/)([\w-]+)/);
    const videoId = match ? match[1] : url;
    return `https://www.youtube.com/embed/${videoId}`;
  };

  if (!vod) return null;

  // Use detailed data if available, otherwise use basic vod data
  const displayVOD = detailedVOD || vod;

  return (
    <>
      <Modal
        opened={opened}
        onClose={onClose}
        title={displayVOD.name}
        size="xl"
        centered
      >
        <Box style={{ position: 'relative', minHeight: 400 }}>
          {/* Backdrop image as background */}
          {displayVOD.backdrop_path && displayVOD.backdrop_path.length > 0 && (
            <>
              <Image
                src={displayVOD.backdrop_path[0]}
                alt={`${displayVOD.name} backdrop`}
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
                    Loading additional details...
                  </Text>
                </Group>
              )}

              {/* Movie poster and basic info */}
              <Flex gap="md">
                {/* Use movie_image or logo */}
                {displayVOD.movie_image || displayVOD.logo?.url ? (
                  <Box style={{ flexShrink: 0 }}>
                    <Image
                      src={displayVOD.movie_image || displayVOD.logo.url}
                      width={200}
                      height={300}
                      alt={displayVOD.name}
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
                  <Title order={3}>{displayVOD.name}</Title>

                  {/* Original name if different */}
                  {displayVOD.o_name &&
                    displayVOD.o_name !== displayVOD.name && (
                      <Text
                        size="sm"
                        color="dimmed"
                        style={{ fontStyle: 'italic' }}
                      >
                        Original: {displayVOD.o_name}
                      </Text>
                    )}

                  <Group spacing="md">
                    {displayVOD.year && (
                      <Badge color="blue">{displayVOD.year}</Badge>
                    )}
                    {displayVOD.duration_secs && (
                      <Badge color="gray">
                        {formatDuration(displayVOD.duration_secs)}
                      </Badge>
                    )}
                    {displayVOD.rating && (
                      <Badge color="yellow">{displayVOD.rating}</Badge>
                    )}
                    {displayVOD.age && (
                      <Badge color="orange">{displayVOD.age}</Badge>
                    )}
                    <Badge color="green">Movie</Badge>
                    {/* imdb_id and tmdb_id badges */}
                    {displayVOD.imdb_id && (
                      <Badge
                        color="yellow"
                        component="a"
                        href={imdbUrl(displayVOD.imdb_id)}
                        target="_blank"
                        rel="noopener noreferrer"
                        style={{ cursor: 'pointer' }}
                      >
                        IMDb
                      </Badge>
                    )}
                    {displayVOD.tmdb_id && (
                      <Badge
                        color="cyan"
                        component="a"
                        href={tmdbUrl(displayVOD.tmdb_id, 'movie')}
                        target="_blank"
                        rel="noopener noreferrer"
                        style={{ cursor: 'pointer' }}
                      >
                        TMDb
                      </Badge>
                    )}
                  </Group>

                  {/* Release date */}
                  {displayVOD.release_date && (
                    <Text size="sm" color="dimmed">
                      <strong>Release Date:</strong> {displayVOD.release_date}
                    </Text>
                  )}

                  {displayVOD.genre && (
                    <Text size="sm" color="dimmed">
                      <strong>Genre:</strong> {displayVOD.genre}
                    </Text>
                  )}

                  {displayVOD.director && (
                    <Text size="sm" color="dimmed">
                      <strong>Director:</strong> {displayVOD.director}
                    </Text>
                  )}

                  {displayVOD.actors && (
                    <Text size="sm" color="dimmed">
                      <strong>Cast:</strong> {displayVOD.actors}
                    </Text>
                  )}

                  {displayVOD.country && (
                    <Text size="sm" color="dimmed">
                      <strong>Country:</strong> {displayVOD.country}
                    </Text>
                  )}

                  {/* Description */}
                  {displayVOD.description && (
                    <Box>
                      <Text size="sm" weight={500} mb={8}>
                        Description
                      </Text>
                      <Text size="sm">{displayVOD.description}</Text>
                    </Box>
                  )}

                  {/* Play and Watch Trailer buttons */}
                  <Group spacing="xs" mt="sm">
                    <Button
                      leftSection={<Play size={16} />}
                      variant="filled"
                      color="blue"
                      size="sm"
                      onClick={handlePlayVOD}
                      disabled={providers.length > 0 && !selectedProvider}
                      style={{ alignSelf: 'flex-start' }}
                    >
                      Play Movie
                    </Button>
                    {displayVOD.youtube_trailer && (
                      <Button
                        variant="outline"
                        color="red"
                        size="sm"
                        onClick={() => {
                          setTrailerUrl(
                            getEmbedUrl(displayVOD.youtube_trailer)
                          );
                          setTrailerModalOpened(true);
                        }}
                        style={{ alignSelf: 'flex-start' }}
                      >
                        Watch Trailer
                      </Button>
                    )}
                    <Button
                      leftSection={<Copy size={16} />}
                      variant="outline"
                      color="gray"
                      size="sm"
                      onClick={handleCopyLink}
                      style={{ alignSelf: 'flex-start' }}
                    >
                      Copy Link
                    </Button>
                  </Group>
                </Stack>
              </Flex>

              {/* Provider Information & Play Button Row */}
              <Group spacing="md" align="flex-end" mt="md">
                {/* Provider Selection */}
                {providers.length > 0 && (
                  <Box style={{ minWidth: 200 }}>
                    <Text size="sm" weight={500} mb={8}>
                      Stream Selection
                      {loadingProviders && (
                        <Loader size="xs" style={{ marginLeft: 8 }} />
                      )}
                    </Text>
                    {providers.length === 1 ? (
                      <Group spacing="md">
                        <Badge color="blue" variant="light">
                          {providers[0].m3u_account.name}
                        </Badge>
                      </Group>
                    ) : (
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
                        style={{ minWidth: 250 }}
                        disabled={loadingProviders}
                      />
                    )}
                  </Box>
                )}

                {/* Fallback provider info if no providers loaded yet */}
                {providers.length === 0 &&
                  !loadingProviders &&
                  vod?.m3u_account && (
                    <Box>
                      <Text size="sm" weight={500} mb={8}>
                        Stream Selection
                      </Text>
                      <Group spacing="md">
                        <Badge color="blue" variant="light">
                          {vod.m3u_account.name}
                        </Badge>
                      </Group>
                    </Box>
                  )}

                {/* Play button moved to top next to Watch Trailer */}
              </Group>

              {/* Technical Details */}
              {(() => {
                const techDetails = getTechnicalDetails(
                  selectedProvider,
                  displayVOD
                );
                const hasDetails =
                  techDetails.bitrate || techDetails.video || techDetails.audio;

                return (
                  hasDetails && (
                    <Stack spacing={4} mt="xs">
                      <Text size="sm" weight={500}>
                        Technical Details:
                        {selectedProvider && (
                          <Text
                            size="xs"
                            color="dimmed"
                            weight="normal"
                            span
                            style={{ marginLeft: 8 }}
                          >
                            (from {selectedProvider.m3u_account.name}
                            {selectedProvider.stream_id &&
                              ` - Stream ${selectedProvider.stream_id}`}
                            )
                          </Text>
                        )}
                      </Text>
                      {techDetails.bitrate && techDetails.bitrate > 0 && (
                        <Text size="xs" color="dimmed">
                          <strong>Bitrate:</strong> {techDetails.bitrate} kbps
                        </Text>
                      )}
                      {techDetails.video &&
                        Object.keys(techDetails.video).length > 0 && (
                          <Text size="xs" color="dimmed">
                            <strong>Video:</strong>{' '}
                            {techDetails.video.codec_long_name &&
                            techDetails.video.codec_long_name !== 'unknown'
                              ? techDetails.video.codec_long_name
                              : techDetails.video.codec_name}
                            {techDetails.video.profile
                              ? ` (${techDetails.video.profile})`
                              : ''}
                            {techDetails.video.width && techDetails.video.height
                              ? `, ${techDetails.video.width}x${techDetails.video.height}`
                              : ''}
                            {techDetails.video.display_aspect_ratio
                              ? `, Aspect Ratio: ${techDetails.video.display_aspect_ratio}`
                              : ''}
                            {techDetails.video.bit_rate
                              ? `, Bitrate: ${Math.round(Number(techDetails.video.bit_rate) / 1000)} kbps`
                              : ''}
                            {techDetails.video.r_frame_rate
                              ? `, Frame Rate: ${techDetails.video.r_frame_rate.replace('/', '/')} fps`
                              : ''}
                            {techDetails.video.tags?.encoder
                              ? `, Encoder: ${techDetails.video.tags.encoder}`
                              : ''}
                          </Text>
                        )}
                      {techDetails.audio &&
                        Object.keys(techDetails.audio).length > 0 && (
                          <Text size="xs" color="dimmed">
                            <strong>Audio:</strong>{' '}
                            {techDetails.audio.codec_long_name &&
                            techDetails.audio.codec_long_name !== 'unknown'
                              ? techDetails.audio.codec_long_name
                              : techDetails.audio.codec_name}
                            {techDetails.audio.profile
                              ? ` (${techDetails.audio.profile})`
                              : ''}
                            {techDetails.audio.channel_layout
                              ? `, Channels: ${techDetails.audio.channel_layout}`
                              : techDetails.audio.channels
                                ? `, Channels: ${techDetails.audio.channels}`
                                : ''}
                            {techDetails.audio.sample_rate
                              ? `, Sample Rate: ${techDetails.audio.sample_rate} Hz`
                              : ''}
                            {techDetails.audio.bit_rate
                              ? `, Bitrate: ${Math.round(Number(techDetails.audio.bit_rate) / 1000)} kbps`
                              : ''}
                            {techDetails.audio.tags?.handler_name
                              ? `, Handler: ${techDetails.audio.tags.handler_name}`
                              : ''}
                          </Text>
                        )}
                    </Stack>
                  )
                );
              })()}
              {/* YouTube trailer if available */}
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
        withCloseButton
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

export default VODModal;
