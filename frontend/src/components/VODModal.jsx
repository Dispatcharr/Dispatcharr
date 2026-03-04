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
import { copyToClipboard } from '../utils';
import useVODStore from '../store/useVODStore';
import useVideoStore from '../store/useVideoStore';
import useSettingsStore from '../store/settings';
import {
  formatDuration,
  formatStreamLabel,
  getYouTubeEmbedUrl,
  imdbUrl,
  tmdbUrl
} from '../utils/components/SeriesModalUtils.js';
import { YouTubeTrailerModal } from './modals/YouTubeTrailerModal.jsx';
import {
  formatAudioDetails,
  formatVideoDetails,
  getMovieStreamUrl,
  getTechnicalDetails,
} from '../utils/components/VODModalUtils.js';

const Movie = ({
  onClickYouTubeTrailer,
  hasMultipleProviders,
  selectedProvider,
  detailedVOD,
  vod
}) => {
  const showVideo = useVideoStore((s) => s.showVideo);
  const env_mode = useSettingsStore((s) => s.environment.env_mode);

  const displayVOD = detailedVOD || vod;

  const getStreamUrl = () => {
    if (!displayVOD) return null;

    return getMovieStreamUrl(vod, selectedProvider, env_mode);
  };

  const handlePlayVOD = () => {
    const streamUrl = getStreamUrl();
    if (!streamUrl) return;
    showVideo(streamUrl, 'vod', displayVOD);
  };

  const handleCopyLink = async () => {
    const streamUrl = getStreamUrl();
    if (!streamUrl) return;
    await copyToClipboard(streamUrl, {
      successTitle: 'Link Copied!',
      successMessage: 'Stream link copied to clipboard',
    });
  };

  return (
    <Stack spacing="md" flex={1}>
      <Title order={3}>{displayVOD.name}</Title>

      {/* Original name if different */}
      {displayVOD.o_name &&
        displayVOD.o_name !== displayVOD.name && (
          <Text size="sm" c="dimmed" fs="italic">
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
        <Text size="sm" c="dimmed">
          <strong>Release Date:</strong> {displayVOD.release_date}
        </Text>
      )}

      {displayVOD.genre && (
        <Text size="sm" c="dimmed">
          <strong>Genre:</strong> {displayVOD.genre}
        </Text>
      )}

      {displayVOD.director && (
        <Text size="sm" c="dimmed">
          <strong>Director:</strong> {displayVOD.director}
        </Text>
      )}

      {displayVOD.actors && (
        <Text size="sm" c="dimmed">
          <strong>Cast:</strong> {displayVOD.actors}
        </Text>
      )}

      {displayVOD.country && (
        <Text size="sm" c="dimmed">
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
          disabled={hasMultipleProviders && !selectedProvider}
          style={{ alignSelf: 'flex-start' }}
        >
          Play Movie
        </Button>
        {displayVOD.youtube_trailer && (
          <Button
            variant="outline"
            color="red"
            size="sm"
            onClick={onClickYouTubeTrailer}
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
  );
};

const MovieTechnicalDetails = ({ selectedProvider, displayVOD }) => {
  const techDetails = getTechnicalDetails(selectedProvider, displayVOD);
  const hasDetails = techDetails.bitrate || techDetails.video || techDetails.audio;

  if (!hasDetails) return null;

  const hasVideo = techDetails.video && Object.keys(techDetails.video).length > 0;
  const hasAudio = techDetails.audio && Object.keys(techDetails.audio).length > 0;

  return (
    <Stack spacing={4} mt="xs">
      <Text size="sm" weight={500}>
        Technical Details:
        {selectedProvider && (
          <Text size="xs" c="dimmed" weight="normal" span ml={8}>
            (from {selectedProvider.m3u_account.name}
            {selectedProvider.stream_id && ` - Stream ${selectedProvider.stream_id}`})
          </Text>
        )}
      </Text>

      {techDetails.bitrate && techDetails.bitrate > 0 && (
        <Text size="xs" c="dimmed">
          <strong>Bitrate:</strong> {techDetails.bitrate} kbps
        </Text>
      )}

      {hasVideo && (
        <Text size="xs" c="dimmed">
          <strong>Video:</strong> {formatVideoDetails(techDetails.video)}
        </Text>
      )}

      {hasAudio && (
        <Text size="xs" c="dimmed">
          <strong>Audio:</strong> {formatAudioDetails(techDetails.audio)}
        </Text>
      )}
    </Stack>
  );
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

  const onClickYouTubeTrailer = () => {
    setTrailerUrl(
      getYouTubeEmbedUrl(displayVOD.youtube_trailer)
    );
    setTrailerModalOpened(true);
  }

  const onChangeSelectedProvider = (value) => {
    const provider = providers.find((p) => p.id.toString() === value);
    setSelectedProvider(provider);
  }

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

                <Movie
                  detailedVOD={detailedVOD}
                  vod={vod}
                  hasMultipleProviders={providers.length > 0}
                  selectedProvider={selectedProvider}
                  onClickYouTubeTrailer={onClickYouTubeTrailer}
                />
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
                        onChange={(value) => onChangeSelectedProvider(value)}
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
              <MovieTechnicalDetails
                selectedProvider={selectedProvider}
                displayVOD={displayVOD}
              />
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
    </>
  );
};

export default VODModal;
