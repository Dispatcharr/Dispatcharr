import VODSourceMetadata from './VODSourceMetadata.jsx';
import useProviderDetailsPolling from '../hooks/useProviderDetailsPolling.jsx';
import React, { useState, useEffect, useRef } from 'react';
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
  Stack,
  ActionIcon,
  Modal,
  Tabs,
  Table,
  UnstyledButton,
  TableTbody,
  TableTd,
  TableTh,
  TableThead,
  TableTr,
  TabsList,
  TabsPanel,
  TabsTab,
} from '@mantine/core';
import { Play, Copy, ChevronDown } from 'lucide-react';
import { copyToClipboard } from '../utils';
import useVODStore from '../store/useVODStore';
import useVideoStore from '../store/useVideoStore';
import useSettingsStore from '../store/settings';
import {
  formatDuration,
  formatStreamLabel,
  getEpisodeAirdate,
  getEpisodeStreamUrl,
  getTmdbUrlLink,
  getYouTubeEmbedUrl,
  groupEpisodesBySeason,
  imdbUrl,
  sortBySeasonNumber,
  sortEpisodesList,
  tmdbUrl,
} from '../utils/components/SeriesModalUtils.js';
import { YouTubeTrailerModal } from './modals/YouTubeTrailerModal.jsx';
import {
  hideNotification,
  showNotification,
} from '../utils/notificationUtils.js';
import classes from './VODLayout.module.css';
import { vodLogoSrc } from '../utils/cards/VODCardUtils.js';

const Series = ({ displaySeries, onClickYouTubeTrailer, children }) => {
  const posterSrc =
    displaySeries.series_image || vodLogoSrc(displaySeries.logo);
  return (
    <div className={classes.summary}>
      {posterSrc ? (
        <Box className={classes.poster}>
          <Image
            src={posterSrc}
            w="100%"
            h="100%"
            alt={displaySeries.name}
            fit="contain"
            bdrs={8}
          />
        </Box>
      ) : (
        <Box className={`${classes.poster} ${classes.placeholder}`}>
          <Play size={48} aria-hidden="true" />
        </Box>
      )}

      <Stack gap="md" className={classes.details}>
        {/* Original name if different */}
        {displaySeries.o_name &&
          displaySeries.o_name !== displaySeries.name && (
            <Text size="sm" c="dimmed" fs="italic">
              Original: {displaySeries.o_name}
            </Text>
          )}

        <Group gap="xs">
          {displaySeries.year && (
            <Badge color="blue">{displaySeries.year}</Badge>
          )}
          {Number(displaySeries.rating) > 0 && (
            <Badge color="yellow">{displaySeries.rating}</Badge>
          )}
          {displaySeries.age && (
            <Badge color="orange">{displaySeries.age}</Badge>
          )}
          <Badge color="purple">Series</Badge>
          {displaySeries.episode_count > 0 && (
            <Badge color="gray">{displaySeries.episode_count} episodes</Badge>
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
          <Text size="sm" c="dimmed">
            <strong>Release Date:</strong> {displaySeries.release_date}
          </Text>
        )}

        {displaySeries.genre && (
          <Text size="sm" c="dimmed">
            <strong>Genre:</strong> {displaySeries.genre}
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

        {displaySeries.country && (
          <Text size="sm" c="dimmed">
            <strong>Country:</strong> {displaySeries.country}
          </Text>
        )}

        {/* Description */}
        {displaySeries.description && (
          <Box>
            <Text size="sm" fw={500} mb={8}>
              Description
            </Text>
            <Text size="sm">{displaySeries.description}</Text>
          </Box>
        )}

        {children}

        {displaySeries.youtube_trailer && (
          <Button
            variant="outline"
            color="red"
            style={{ alignSelf: 'flex-start' }}
            onClick={onClickYouTubeTrailer}
          >
            Watch Trailer
          </Button>
        )}
      </Stack>
    </div>
  );
};

const Episode = ({ episode, displaySeries }) => {
  return (
    <Stack gap="sm" className={classes.details}>
      <Group gap="md">
        {episode.duration_secs > 0 && (
          <Text size="sm" c="dimmed">
            Duration: {formatDuration(episode.duration_secs)}
          </Text>
        )}
        {getEpisodeAirdate(episode) && (
          <Text size="sm" c="dimmed">
            Air date: {getEpisodeAirdate(episode)}
          </Text>
        )}
      </Group>
      {/* Episode Image and Description Row */}
      <Flex gap="md" wrap="wrap">
        {/* Episode Image */}
        {episode.movie_image && (
          <Box style={{ flexShrink: 0 }}>
            <Image
              src={episode.movie_image}
              w={120}
              h={160}
              alt={episode.name}
              fit="cover"
              bdrs={4}
            />
          </Box>
        )}

        {/* Episode Description */}
        <Box flex={1} miw={0}>
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

const SeriesModal = ({ series, opened, onClose }) => {
  const { fetchSeriesInfo, fetchSeriesProviders } = useVODStore();
  const showVideo = useVideoStore((s) => s.showVideo);
  const env_mode = useSettingsStore((s) => s.environment.env_mode);

  const [detailedSeries, setDetailedSeries] = useState(null);
  const [loadingDetails, setLoadingDetails] = useState(false);
  const [detailsError, setDetailsError] = useState(false);
  const [activeTab, setActiveTab] = useState(null);
  const [expandedEpisode, setExpandedEpisode] = useState(null);
  const [trailerModalOpened, setTrailerModalOpened] = useState(false);
  const [trailerUrl, setTrailerUrl] = useState('');
  const [providers, setProviders] = useState([]);
  const [selectedProvider, setSelectedProvider] = useState(null);
  const [loadingProviders, setLoadingProviders] = useState(false);
  const detailsRequestIdRef = useRef(0);
  const { retry: retryProviderDetails, retrying: retryingProviderDetails } =
    useProviderDetailsPolling({
      opened,
      id: series?.id,
      relationId: selectedProvider?.id || series?.source_id,
      details: detailedSeries,
      load: fetchSeriesInfo,
      onResult: setDetailedSeries,
    });

  useEffect(() => {
    if (opened && series) {
      let cancelled = false;
      const requestId = ++detailsRequestIdRef.current;
      setDetailedSeries(null);
      setProviders([]);
      setSelectedProvider(null);
      setExpandedEpisode(null);
      setDetailsError(false);
      hideNotification('series-preview-details');
      hideNotification('series-preview-providers');
      setLoadingDetails(true);
      (series.source_id
        ? fetchSeriesInfo(series.id, series.source_id)
        : fetchSeriesInfo(series.id)
      )
        .then((details) => {
          if (detailsRequestIdRef.current !== requestId) return;
          setDetailedSeries(details);
        })
        .catch(() => {
          if (detailsRequestIdRef.current !== requestId) return;
          setDetailedSeries(series);
          setDetailsError(true);
          showNotification({
            id: 'series-preview-details',
            title: 'Series details unavailable',
            message:
              'Details and episodes could not be loaded. Imported series information is shown instead.',
            color: 'red',
            autoClose: false,
          });
        })
        .finally(() => {
          if (detailsRequestIdRef.current === requestId) {
            setLoadingDetails(false);
          }
        });

      // Fetch available providers (does not re-trigger series info fetch)
      setLoadingProviders(true);
      fetchSeriesProviders(series.id)
        .then((providersData) => {
          if (cancelled) return;
          setProviders(providersData);
          setSelectedProvider(
            series.source_id
              ? providersData.find(
                  (provider) => provider.id === series.source_id
                ) || null
              : providersData[0] || null
          );
        })
        .catch(() => {
          if (cancelled) return;
          showNotification({
            id: 'series-preview-providers',
            title: 'Series providers unavailable',
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
    }
  }, [opened, series, fetchSeriesInfo, fetchSeriesProviders]);

  useEffect(() => {
    if (!opened) {
      detailsRequestIdRef.current += 1;
      setDetailedSeries(null);
      setLoadingDetails(false);
      setProviders([]);
      setSelectedProvider(null);
      setLoadingProviders(false);
      setTrailerModalOpened(false);
      setTrailerUrl('');
    }
  }, [opened]);

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

  const onChangeSelectedProvider = (value) => {
    const provider = providers.find((p) => p.id.toString() === value);
    setSelectedProvider(provider);
    if (provider) {
      const requestId = ++detailsRequestIdRef.current;
      setLoadingDetails(true);
      setDetailsError(false);
      setExpandedEpisode(null);
      hideNotification('series-preview-details');
      // Clear episodes immediately so the previous provider's list cannot flash
      setDetailedSeries((prev) =>
        prev ? { ...prev, episodesList: [] } : prev
      );
      fetchSeriesInfo(series.id, provider.id)
        .then((details) => {
          if (detailsRequestIdRef.current !== requestId) return;
          setDetailedSeries(details);
        })
        .catch(() => {
          if (detailsRequestIdRef.current !== requestId) return;
          setDetailedSeries(series);
          setDetailsError(true);
          showNotification({
            id: 'series-preview-details',
            title: 'Series details unavailable',
            message:
              'Details and episodes for the selected stream could not be loaded. Reopen the preview to retry.',
            color: 'red',
            autoClose: false,
          });
        })
        .finally(() => {
          if (detailsRequestIdRef.current === requestId) {
            setLoadingDetails(false);
          }
        });
    }
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
        size="min(1000px, 94vw)"
        centered
        closeButtonProps={{ 'aria-label': 'Close series preview' }}
        classNames={{
          content: classes.content,
          body: classes.body,
          header: classes.header,
          title: classes.title,
        }}
      >
        <Box pos="relative">
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
            <Stack gap="md">
              {(loadingDetails ||
                detailedSeries?.refresh_status === 'pending') && (
                <Text size="sm" c="dimmed" role="status">
                  {detailedSeries?.refresh_status === 'pending'
                    ? 'Loading provider details and episodes in the background…'
                    : 'Loading series details and episodes...'}
                </Text>
              )}
              {['failed', 'unavailable'].includes(
                detailedSeries?.refresh_status
              ) && (
                <Group gap="xs">
                  <Text size="sm" c="dimmed">
                    Provider details unavailable. Imported information is shown.
                  </Text>
                  <Button
                    size="compact-xs"
                    variant="subtle"
                    loading={retryingProviderDetails}
                    onClick={retryProviderDetails}
                  >
                    Retry details
                  </Button>
                </Group>
              )}

              {/* Series poster and basic info */}
              <Series
                displaySeries={displaySeries}
                onClickYouTubeTrailer={onClickYouTubeTrailer}
              >
                {(loadingProviders ||
                  providers.length > 0 ||
                  displaySeries.m3u_account) && (
                  <Box className={classes.section}>
                    <Text size="sm" fw={500} mb="xs">
                      Stream Selection
                    </Text>
                    {loadingProviders ? (
                      <Text size="sm" c="dimmed" role="status">
                        Loading streams…
                      </Text>
                    ) : providers.length === 0 && displaySeries.m3u_account ? (
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
                    ) : null}
                    <VODSourceMetadata source={selectedProvider} />
                  </Box>
                )}
              </Series>

              <Title order={4}>
                Episodes
                {seriesEpisodes.length > 0 && <> ({seriesEpisodes.length})</>}
              </Title>

              {loadingDetails ? null : seasons.length > 0 ? (
                <Tabs value={activeTab} onChange={setActiveTab}>
                  <TabsList className={classes.seasonTabs}>
                    {seasons.map((season) => (
                      <TabsTab key={season} value={`season-${season}`}>
                        Season {season}
                      </TabsTab>
                    ))}
                  </TabsList>

                  {seasons.map((season) => (
                    <TabsPanel key={season} value={`season-${season}`} pt="md">
                      <div className={classes.tableFrame}>
                        <Table
                          striped
                          highlightOnHover
                          className={classes.episodes}
                        >
                          <TableThead>
                            <TableTr>
                              <TableTh w={48}>Ep</TableTh>
                              <TableTh>Title</TableTh>
                              <TableTh
                                w={85}
                                className={classes.episodeSecondary}
                              >
                                Duration
                              </TableTh>
                              <TableTh
                                w={110}
                                className={classes.episodeSecondary}
                              >
                                Date
                              </TableTh>
                              <TableTh w={85} ta="center">
                                Actions
                              </TableTh>
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
                                    <Stack gap={2}>
                                      <UnstyledButton
                                        className={classes.episodeTitle}
                                        aria-expanded={
                                          expandedEpisode === episode.id
                                        }
                                        aria-controls={`episode-details-${episode.id}`}
                                        onClick={(event) => {
                                          event.stopPropagation();
                                          handleEpisodeRowClick(episode);
                                        }}
                                      >
                                        <ChevronDown
                                          size={14}
                                          aria-hidden="true"
                                          style={{
                                            flexShrink: 0,
                                            transform:
                                              expandedEpisode === episode.id
                                                ? 'rotate(180deg)'
                                                : undefined,
                                          }}
                                        />
                                        {episode.name}
                                      </UnstyledButton>
                                      {episode.genre && (
                                        <Text size="xs" color="dimmed">
                                          {episode.genre}
                                        </Text>
                                      )}
                                    </Stack>
                                  </TableTd>
                                  <TableTd className={classes.episodeSecondary}>
                                    <Text size="xs" color="dimmed">
                                      {formatDuration(episode.duration_secs)}
                                    </Text>
                                  </TableTd>
                                  <TableTd className={classes.episodeSecondary}>
                                    <Text size="xs" color="dimmed">
                                      {getEpisodeAirdate(episode)}
                                    </Text>
                                  </TableTd>
                                  <TableTd>
                                    <Group
                                      gap="xs"
                                      justify="center"
                                      wrap="nowrap"
                                    >
                                      <ActionIcon
                                        variant="filled"
                                        color="blue"
                                        size="sm"
                                        aria-label={`Play ${episode.name}`}
                                        title={`Play ${episode.name}`}
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
                                        aria-label={`Copy link to ${episode.name}`}
                                        title={`Copy link to ${episode.name}`}
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
                                  <TableTr id={`episode-details-${episode.id}`}>
                                    <TableTd
                                      colSpan={5}
                                      p={16}
                                      className={classes.episodeDetail}
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
                      </div>
                    </TabsPanel>
                  ))}
                </Tabs>
              ) : (
                <Text c={detailsError ? 'red' : 'dimmed'} ta="center" py="xl">
                  {detailsError
                    ? 'Episodes could not be loaded.'
                    : 'No episodes found for this series.'}
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
    </>
  );
};

export default SeriesModal;
