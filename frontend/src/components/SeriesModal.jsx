import React, { useEffect, useState } from 'react';
import {
  ActionIcon,
  Badge,
  Box,
  Button,
  Divider,
  Flex,
  Group,
  Image,
  Loader,
  Modal,
  Select,
  Stack,
  Table,
  TableTbody,
  TableTd,
  TableTh,
  TableThead,
  TableTr,
  Tabs,
  TabsList,
  TabsPanel,
  TabsTab,
  Text,
  Title,
} from '@mantine/core';
import { Copy, Play } from 'lucide-react';
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

const Series = ({ displaySeries, onClickYouTubeTrailer }) => {
  return (
    <Flex gap="md">
      {displaySeries.series_image || displaySeries.logo?.url ? (
        <Box style={{ flexShrink: 0 }}>
          <Image
            src={displaySeries.series_image || displaySeries.logo.url}
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
        <Box pos="relative" mih={400}>
          {/* Backdrop image as background */}
          {displaySeries.backdrop_path &&
            displaySeries.backdrop_path.length > 0 && (
              <>
                <Image
                  src={displaySeries.backdrop_path[0]}
                  alt={`${displaySeries.name} backdrop`}
                  fit="cover"
                  pos="absolute"
                  top={0}
                  left={0}
                  w={'100%'}
                  h={'100%'}
                  bdrs={8}
                  style={{
                    objectFit: 'cover',
                    zIndex: 0,
                    filter: 'blur(2px) brightness(0.5)',
                  }}
                />
                {/* Overlay for readability */}
                <Box
                  pos="absolute"
                  top={0}
                  left={0}
                  w={'100%'}
                  h={'100%'}
                  bdrs={8}
                  style={{
                    background:
                      'linear-gradient(180deg, rgba(24,24,27,0.85) 60%, rgba(24,24,27,1) 100%)',
                    zIndex: 1,
                  }}
                />
              </>
            )}

          {/* Modal content above backdrop */}
          <Box pos="relative" style={{ zIndex: 2 }}>
            <Stack spacing="md">
              {loadingDetails && (
                <Group spacing="xs" mb={8}>
                  <Loader size="xs" />
                  <Text size="xs" c="dimmed">
                    Loading series details and episodes...
                  </Text>
                </Group>
              )}

              {/* Series poster and basic info */}
              <Series
                displaySeries={displaySeries}
                onClickYouTubeTrailer={onClickYouTubeTrailer}
              />

              {/* Provider Information */}
              <Box mt="md">
                <Text size="sm" weight={500} mb={4}>
                  Stream Selection
                  {loadingProviders && <Loader size="xs" ml={8} />}
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
                    onChange={(value) => onChangeSelectedProvider(value)}
                    placeholder="Select stream..."
                    maw={350}
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
                            <TableTh w={60}>Ep</TableTh>
                            <TableTh>Title</TableTh>
                            <TableTh w={80}>Duration</TableTh>
                            <TableTh w={60}>Date</TableTh>
                            <TableTh w={80}>Action</TableTh>
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
                                      <Text size="xs" c="dimmed">
                                        {episode.genre}
                                      </Text>
                                    )}
                                  </Stack>
                                </TableTd>
                                <TableTd>
                                  <Text size="xs" c="dimmed">
                                    {formatDuration(episode.duration_secs)}
                                  </Text>
                                </TableTd>
                                <TableTd>
                                  <Text size="xs" c="dimmed">
                                    {getEpisodeAirdate(episode)}
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
                <Text c="dimmed" align="center" py="xl">
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
    </>
  );
};

export default SeriesModal;
