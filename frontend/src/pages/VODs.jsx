import React, { useState, useEffect } from 'react';
import {
  Box,
  Button,
  Card,
  Flex,
  Group,
  Image,
  Text,
  Title,
  Select,
  TextInput,
  Pagination,
  Badge,
  Grid,
  Loader,
  Stack,
  SegmentedControl,
  ActionIcon,
} from '@mantine/core';
import { Search, Play, Calendar, Clock, Star } from 'lucide-react';
import { useDisclosure } from '@mantine/hooks';
import useVODStore from '../store/useVODStore';
import SeriesModal from '../components/SeriesModal';
import VODModal from '../components/VODModal';

const formatDuration = (seconds) => {
  if (!seconds) return '';
  const hours = Math.floor(seconds / 3600);
  const mins = Math.floor((seconds % 3600) / 60);
  const secs = seconds % 60;
  return hours > 0 ? `${hours}h ${mins}m` : `${mins}m ${secs}s`;
};

const VODCard = ({ vod, onClick }) => {
  const isEpisode = vod.type === 'episode';

  const getDisplayTitle = () => {
    if (isEpisode && vod.series) {
      const seasonEp =
        vod.season_number && vod.episode_number
          ? `S${vod.season_number.toString().padStart(2, '0')}E${vod.episode_number.toString().padStart(2, '0')}`
          : '';
      return (
        <Stack spacing={4}>
          <Text size="sm" color="dimmed">
            {vod.series.name}
          </Text>
          <Text weight={500}>
            {seasonEp} - {vod.name}
          </Text>
        </Stack>
      );
    }
    return <Text weight={500}>{vod.name}</Text>;
  };

  const handleCardClick = async () => {
    // Just pass the basic vod info to the parent handler
    onClick(vod);
  };

  return (
    <Card
      shadow="sm"
      padding="md"
      radius="md"
      withBorder
      style={{ cursor: 'pointer', backgroundColor: '#27272A' }}
      onClick={handleCardClick}
    >
      <Card.Section>
        <Box style={{ position: 'relative', height: 300 }}>
          {vod.logo?.url ? (
            <Image
              src={vod.logo.url}
              height={300}
              alt={vod.name}
              fit="contain"
            />
          ) : (
            <Box
              style={{
                height: 300,
                backgroundColor: '#404040',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
            >
              <Play size={48} color="#666" />
            </Box>
          )}

          <ActionIcon
            style={{
              position: 'absolute',
              top: 8,
              right: 8,
              backgroundColor: 'rgba(0,0,0,0.7)',
            }}
            onClick={(e) => {
              e.stopPropagation();
              onClick(vod);
            }}
          >
            <Play size={16} color="white" />
          </ActionIcon>

          <Badge
            style={{
              position: 'absolute',
              bottom: 8,
              left: 8,
            }}
            color={isEpisode ? 'blue' : 'green'}
          >
            {isEpisode ? 'Episode' : 'Movie'}
          </Badge>
        </Box>
      </Card.Section>

      <Stack spacing={8} mt="md">
        {getDisplayTitle()}

        <Group spacing={16}>
          {vod.year && (
            <Group spacing={4}>
              <Calendar size={14} color="#666" />
              <Text size="xs" color="dimmed">
                {vod.year}
              </Text>
            </Group>
          )}

          {vod.duration && (
            <Group spacing={4}>
              <Clock size={14} color="#666" />
              <Text size="xs" color="dimmed">
                {formatDuration(vod.duration_secs)}
              </Text>
            </Group>
          )}

          {vod.rating && (
            <Group spacing={4}>
              <Star size={14} color="#666" />
              <Text size="xs" color="dimmed">
                {vod.rating}
              </Text>
            </Group>
          )}
        </Group>

        {vod.genre && (
          <Text size="xs" color="dimmed" lineClamp={1}>
            {vod.genre}
          </Text>
        )}
      </Stack>
    </Card>
  );
};

const SeriesCard = ({ series, onClick }) => {
  return (
    <Card
      shadow="sm"
      padding="md"
      radius="md"
      withBorder
      style={{ cursor: 'pointer', backgroundColor: '#27272A' }}
      onClick={() => onClick(series)}
    >
      <Card.Section>
        <Box style={{ position: 'relative', height: 300 }}>
          {series.logo?.url ? (
            <Image
              src={series.logo.url}
              height={300}
              alt={series.name}
              fit="contain"
            />
          ) : (
            <Box
              style={{
                height: 300,
                backgroundColor: '#404040',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
            >
              <Play size={48} color="#666" />
            </Box>
          )}
          {/* Add Series badge in the same position as Movie badge */}
          <Badge
            style={{
              position: 'absolute',
              bottom: 8,
              left: 8,
            }}
            color="purple"
          >
            Series
          </Badge>
        </Box>
      </Card.Section>

      <Stack spacing={8} mt="md">
        <Text weight={500}>{series.name}</Text>

        <Group spacing={16}>
          {series.year && (
            <Group spacing={4}>
              <Calendar size={14} color="#666" />
              <Text size="xs" color="dimmed">
                {series.year}
              </Text>
            </Group>
          )}
          {series.rating && (
            <Group spacing={4}>
              <Star size={14} color="#666" />
              <Text size="xs" color="dimmed">
                {series.rating}
              </Text>
            </Group>
          )}
        </Group>

        {series.genre && (
          <Text size="xs" color="dimmed" lineClamp={1}>
            {series.genre}
          </Text>
        )}
      </Stack>
    </Card>
  );
};

const MIN_CARD_WIDTH = 260;
const MAX_CARD_WIDTH = 320;

const useCardColumns = () => {
  const [columns, setColumns] = useState(4);

  useEffect(() => {
    const calcColumns = () => {
      const container = document.getElementById('vods-container');
      const width = container ? container.offsetWidth : window.innerWidth;
      let colCount = Math.floor(width / MIN_CARD_WIDTH);
      if (colCount < 1) colCount = 1;
      if (colCount > 6) colCount = 6;
      setColumns(colCount);
    };
    calcColumns();
    window.addEventListener('resize', calcColumns);
    return () => window.removeEventListener('resize', calcColumns);
  }, []);

  return columns;
};

const VODsPage = () => {
  const currentPageContent = useVODStore((s) => s.currentPageContent); // Direct subscription
  const allCategories = useVODStore((s) => s.categories);
  const filters = useVODStore((s) => s.filters);
  const currentPage = useVODStore((s) => s.currentPage);
  const totalCount = useVODStore((s) => s.totalCount);
  const pageSize = useVODStore((s) => s.pageSize);
  const setFilters = useVODStore((s) => s.setFilters);
  const setPage = useVODStore((s) => s.setPage);
  const setPageSize = useVODStore((s) => s.setPageSize);

  // Persist page size in localStorage
  useEffect(() => {
    const stored = localStorage.getItem('vodsPageSize');
    if (stored && !isNaN(Number(stored)) && Number(stored) !== pageSize) {
      setPageSize(Number(stored));
    }
    // eslint-disable-next-line
  }, []);

  const handlePageSizeChange = (value) => {
    setPageSize(Number(value));
    localStorage.setItem('vodsPageSize', value);
  };
  const fetchContent = useVODStore((s) => s.fetchContent);
  const fetchCategories = useVODStore((s) => s.fetchCategories);

  // const showVideo = useVideoStore((s) => s.showVideo); - removed as unused
  const [selectedSeries, setSelectedSeries] = useState(null);
  const [selectedVOD, setSelectedVOD] = useState(null);
  const [
    seriesModalOpened,
    { open: openSeriesModal, close: closeSeriesModal },
  ] = useDisclosure(false);
  const [vodModalOpened, { open: openVODModal, close: closeVODModal }] =
    useDisclosure(false);
  const [initialLoad, setInitialLoad] = useState(true);
  const columns = useCardColumns();
  const [categories, setCategories] = useState({});

  // Helper function to get display data based on current filters
  const getDisplayData = () => {
    return (currentPageContent || []).map((item) => ({
      ...item,
      _vodType: item.contentType === 'movie' ? 'movie' : 'series',
    }));
  };

  useEffect(() => {
    // setCategories(allCategories)
    setCategories(
      Object.keys(allCategories).reduce((acc, key) => {
        const enabled = allCategories[key].m3u_accounts.find(
          (account) => account.enabled === true
        );
        if (enabled) {
          acc[key] = allCategories[key];
        }

        return acc;
      }, {})
    );
  }, [allCategories]);

  useEffect(() => {
    fetchCategories();
  }, [fetchCategories]);

  useEffect(() => {
    fetchContent().finally(() => setInitialLoad(false));
  }, [filters, currentPage, pageSize, fetchContent]);

  const handleVODCardClick = (vod) => {
    setSelectedVOD(vod);
    openVODModal();
  };

  const handleSeriesClick = (series) => {
    setSelectedSeries(series);
    openSeriesModal();
  };

  const onCategoryChange = (value) => {
    setFilters({ category: value });
    setPage(1);
  };

  // When type changes, reset category to all
  const handleTypeChange = (value) => {
    setFilters({ type: value, category: '' });
    setPage(1);
  };

  const categoryOptions = [
    { value: '', label: 'All Categories' },
    ...Object.values(categories)
      .filter((cat) => {
        if (filters.type === 'movies') return cat.category_type === 'movie';
        if (filters.type === 'series') return cat.category_type === 'series';
        return true; // 'all' shows all
      })
      .map((cat) => ({
        value: `${cat.name}|${cat.category_type}`,
        label: `${cat.name} (${cat.category_type})`,
      })),
  ];

  const totalPages = Math.ceil(totalCount / pageSize);

  return (
    <Box p="md" id="vods-container">
      <Stack spacing="md">
        <Group position="apart">
          <Title order={2}>Video on Demand</Title>
        </Group>

        {/* Filters */}
        <Group spacing="md" align="end">
          <SegmentedControl
            value={filters.type}
            onChange={handleTypeChange}
            data={[
              { label: 'All', value: 'all' },
              { label: 'Movies', value: 'movies' },
              { label: 'Series', value: 'series' },
            ]}
          />

          <TextInput
            placeholder="Search VODs..."
            icon={<Search size={16} />}
            value={filters.search}
            onChange={(e) => setFilters({ search: e.target.value })}
            style={{ minWidth: 200 }}
          />

          <Select
            placeholder="Category"
            data={categoryOptions}
            value={filters.category}
            onChange={onCategoryChange}
            clearable
            style={{ minWidth: 150 }}
          />

          <Select
            label="Page Size"
            value={String(pageSize)}
            onChange={handlePageSizeChange}
            data={['12', '24', '48', '96'].map((v) => ({
              value: v,
              label: v,
            }))}
            style={{ width: 110 }}
          />
        </Group>

        {/* Content */}
        {initialLoad ? (
          <Flex justify="center" py="xl">
            <Loader size="lg" />
          </Flex>
        ) : (
          <>
            <Grid gutter="md">
              {getDisplayData().map((item) => (
                <Grid.Col
                  span={12 / columns}
                  key={`${item.contentType}_${item.id}`}
                  style={{
                    minWidth: MIN_CARD_WIDTH,
                    maxWidth: MAX_CARD_WIDTH,
                    margin: '0 auto',
                  }}
                >
                  {item.contentType === 'series' ? (
                    <SeriesCard series={item} onClick={handleSeriesClick} />
                  ) : (
                    <VODCard vod={item} onClick={handleVODCardClick} />
                  )}
                </Grid.Col>
              ))}
            </Grid>

            {/* Pagination */}
            {totalPages > 1 && (
              <Flex justify="center" mt="md">
                <Pagination
                  page={currentPage}
                  onChange={setPage}
                  total={totalPages}
                />
              </Flex>
            )}
          </>
        )}
      </Stack>

      {/* Series Episodes Modal */}
      <SeriesModal
        series={selectedSeries}
        opened={seriesModalOpened}
        onClose={closeSeriesModal}
      />

      {/* VOD Details Modal */}
      <VODModal
        vod={selectedVOD}
        opened={vodModalOpened}
        onClose={closeVODModal}
      />
    </Box>
  );
};

export default VODsPage;
