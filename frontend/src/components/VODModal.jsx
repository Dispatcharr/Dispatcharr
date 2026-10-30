import VODSourceMetadata from './VODSourceMetadata.jsx';
import React, { useState, useEffect, useRef } from 'react';
import {
  Box,
  Button,
  Group,
  Image,
  Text,
  Select,
  Badge,
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
  tmdbUrl,
} from '../utils/components/SeriesModalUtils.js';
import { YouTubeTrailerModal } from './modals/YouTubeTrailerModal.jsx';
import {
  formatAudioDetails,
  formatVideoDetails,
  getMovieStreamUrl,
  getTechnicalDetails,
} from '../utils/components/VODModalUtils.js';
import {
  hideNotification,
  showNotification,
} from '../utils/notificationUtils.js';
import classes from './VODLayout.module.css';
import { vodLogoSrc } from '../utils/cards/VODCardUtils.js';

const Movie = ({
  onClickYouTubeTrailer,
  hasMultipleProviders,
  selectedProvider,
  detailedVOD,
  vod,
  children,
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
    <Stack gap="md" className={classes.details}>
      {/* Original name if different */}
      {displayVOD.o_name && displayVOD.o_name !== displayVOD.name && (
        <Text size="sm" c="dimmed" fs="italic">
          Original: {displayVOD.o_name}
        </Text>
      )}

      <Group gap="xs">
        {displayVOD.year && <Badge color="blue">{displayVOD.year}</Badge>}
        {displayVOD.duration_secs > 0 && (
          <Badge color="gray">{formatDuration(displayVOD.duration_secs)}</Badge>
        )}
        {Number(displayVOD.rating) > 0 && (
          <Badge color="yellow">{displayVOD.rating}</Badge>
        )}
        {displayVOD.age && <Badge color="orange">{displayVOD.age}</Badge>}
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
          <Text size="sm" fw={500} mb={8}>
            Description
          </Text>
          <Text size="sm">{displayVOD.description}</Text>
        </Box>
      )}

      {children}

      <Group gap="xs">
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
  const hasDetails =
    techDetails.bitrate || techDetails.video || techDetails.audio;

  if (!hasDetails) return null;

  const hasVideo =
    techDetails.video && Object.keys(techDetails.video).length > 0;
  const hasAudio =
    techDetails.audio && Object.keys(techDetails.audio).length > 0;

  return (
    <Stack gap={4} className={classes.section}>
      <Text size="sm" fw={500}>
        Technical Details
        {selectedProvider && (
          <Text size="xs" c="dimmed" fw="normal" span ml={8}>
            (from {selectedProvider.m3u_account?.name}
            {selectedProvider.stream_id &&
              ` - Stream ${selectedProvider.stream_id}`}
            )
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
  const detailsRequestIdRef = useRef(0);

  const { fetchMovieDetailsFromProvider, fetchMovieProviders } = useVODStore();

  useEffect(() => {
    if (!opened || !vod) return;
    let cancelled = false;
    const requestId = ++detailsRequestIdRef.current;
    setDetailedVOD(null);
    setProviders([]);
    setSelectedProvider(null);
    setLoadingDetails(true);
    hideNotification('movie-preview-details');
    hideNotification('movie-preview-providers');
    fetchMovieDetailsFromProvider(vod.id)
      .then((details) => {
        if (detailsRequestIdRef.current === requestId) setDetailedVOD(details);
      })
      .catch(() => {
        if (detailsRequestIdRef.current !== requestId) return;
        setDetailedVOD(vod);
        showNotification({
          id: 'movie-preview-details',
          title: 'Movie details unavailable',
          message:
            'Additional details could not be loaded. Imported movie information is shown instead.',
          color: 'red',
          autoClose: false,
        });
      })
      .finally(() => {
        if (detailsRequestIdRef.current === requestId) setLoadingDetails(false);
      });

    setLoadingProviders(true);
    fetchMovieProviders(vod.id)
      .then((providersData) => {
        if (cancelled) return;
        setProviders(providersData);
        setSelectedProvider(providersData[0] || null);
      })
      .catch(() => {
        if (cancelled) return;
        showNotification({
          id: 'movie-preview-providers',
          title: 'Movie providers unavailable',
          message:
            'Available streams could not be loaded. Reopen the preview to retry.',
          color: 'red',
          autoClose: false,
        });
      })
      .finally(() => {
        if (!cancelled) setLoadingProviders(false);
      });
    return () => {
      cancelled = true;
      detailsRequestIdRef.current += 1;
    };
  }, [opened, vod, fetchMovieDetailsFromProvider, fetchMovieProviders]);

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
    setTrailerUrl(getYouTubeEmbedUrl(displayVOD.youtube_trailer));
    setTrailerModalOpened(true);
  };

  const onChangeSelectedProvider = (value) => {
    const provider = providers.find((p) => p.id.toString() === value);
    setSelectedProvider(provider);
    if (provider) {
      const requestId = ++detailsRequestIdRef.current;
      setLoadingDetails(true);
      hideNotification('movie-preview-details');
      fetchMovieDetailsFromProvider(vod.id, provider.id)
        .then((details) => {
          if (detailsRequestIdRef.current === requestId)
            setDetailedVOD(details);
        })
        .catch(() => {
          if (detailsRequestIdRef.current !== requestId) return;
          setDetailedVOD(vod);
          showNotification({
            id: 'movie-preview-details',
            title: 'Movie details unavailable',
            message:
              'Details for the selected stream could not be loaded. Imported movie information is shown instead.',
            color: 'red',
            autoClose: false,
          });
        })
        .finally(() => {
          if (detailsRequestIdRef.current === requestId)
            setLoadingDetails(false);
        });
    }
  };

  if (!vod) return null;

  // Use detailed data if available, otherwise use basic vod data
  const displayVOD = detailedVOD || vod;
  const posterSrc =
    displayVOD.movie_image ||
    vodLogoSrc(displayVOD.logo) ||
    vodLogoSrc(vod.logo);

  return (
    <>
      <Modal
        opened={opened}
        onClose={onClose}
        title={displayVOD.name}
        size="min(900px, 94vw)"
        centered
        closeButtonProps={{ 'aria-label': 'Close movie preview' }}
        classNames={{
          content: classes.content,
          body: classes.body,
          header: classes.header,
          title: classes.title,
        }}
      >
        <Box pos="relative">
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
            <Stack gap="md">
              {loadingDetails && (
                <Text size="sm" c="dimmed" role="status">
                  Loading additional details...
                </Text>
              )}

              {/* Movie poster and basic info */}
              <div className={classes.summary}>
                {/* Use movie_image or logo */}
                {posterSrc ? (
                  <Box className={classes.poster}>
                    <Image
                      src={posterSrc}
                      w="100%"
                      h="100%"
                      alt={displayVOD.name}
                      fit="contain"
                      style={{ borderRadius: '8px' }}
                    />
                  </Box>
                ) : (
                  <Box className={`${classes.poster} ${classes.placeholder}`}>
                    <Play size={48} aria-hidden="true" />
                  </Box>
                )}

                <Movie
                  detailedVOD={detailedVOD}
                  vod={vod}
                  hasMultipleProviders={providers.length > 0}
                  selectedProvider={selectedProvider}
                  onClickYouTubeTrailer={onClickYouTubeTrailer}
                >
                  {(loadingProviders ||
                    providers.length > 0 ||
                    vod.m3u_account) && (
                    <Box className={classes.section}>
                      <Text size="sm" fw={500} mb="xs">
                        Stream Selection
                      </Text>
                      {loadingProviders ? (
                        <Text size="sm" c="dimmed" role="status">
                          Loading streams…
                        </Text>
                      ) : providers.length === 1 ? (
                        <Badge color="blue" variant="light">
                          {providers[0].m3u_account.name}
                        </Badge>
                      ) : providers.length > 1 ? (
                        <Select
                          aria-label="Stream Selection"
                          data={providers.map((provider) => ({
                            value: provider.id.toString(),
                            label: formatStreamLabel(provider),
                          }))}
                          value={selectedProvider?.id?.toString() || ''}
                          onChange={(value) => onChangeSelectedProvider(value)}
                          placeholder="Select stream..."
                          disabled={loadingProviders}
                          allowDeselect={false}
                        />
                      ) : (
                        <Badge color="blue" variant="light">
                          {vod.m3u_account?.name}
                        </Badge>
                      )}
                      <VODSourceMetadata source={selectedProvider} />
                    </Box>
                  )}
                  <MovieTechnicalDetails
                    selectedProvider={selectedProvider}
                    displayVOD={displayVOD}
                  />
                </Movie>
              </div>
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
