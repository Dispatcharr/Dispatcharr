import {
  ActionIcon,
  Badge,
  Box,
  Card,
  CardSection,
  Group,
  Image,
  Stack,
  Text,
} from '@mantine/core';
import { Calendar, Clock, Play, Star } from 'lucide-react';
import React from 'react';
import {
  formatDuration,
  getSeasonLabel,
} from '../../utils/cards/VODCardUtils.js';

const VODCard = ({ vod, onClick }) => {
  const isEpisode = vod.type === 'episode';

  const getDisplayTitle = () => {
    if (isEpisode && vod.series) {
      return (
        <Stack spacing={4}>
          <Text size="sm" c="dimmed">
            {vod.series.name}
          </Text>
          <Text weight={500}>
            {getSeasonLabel(vod)} - {vod.name}
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
      <CardSection>
        <Box pos="relative" h={300}>
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
                backgroundColor: '#404040',
                alignItems: 'center',
                justifyContent: 'center',
              }}
              h={300}
              display="flex"
            >
              <Play size={48} color="#666" />
            </Box>
          )}

          <ActionIcon
            style={{
              backgroundColor: 'rgba(0,0,0,0.7)',
            }}
            pos="absolute"
            top={8}
            right={8}
            onClick={(e) => {
              e.stopPropagation();
              onClick(vod);
            }}
          >
            <Play size={16} color="white" />
          </ActionIcon>

          <Badge
            pos="absolute"
            bottom={8}
            left={8}
            color={isEpisode ? 'blue' : 'green'}
          >
            {isEpisode ? 'Episode' : 'Movie'}
          </Badge>
        </Box>
      </CardSection>

      <Stack spacing={8} mt="md">
        {getDisplayTitle()}

        <Group spacing={16}>
          {vod.year && (
            <Group spacing={4}>
              <Calendar size={14} color="#666" />
              <Text size="xs" c="dimmed">
                {vod.year}
              </Text>
            </Group>
          )}

          {vod.duration && (
            <Group spacing={4}>
              <Clock size={14} color="#666" />
              <Text size="xs" c="dimmed">
                {formatDuration(vod.duration_secs)}
              </Text>
            </Group>
          )}

          {vod.rating && (
            <Group spacing={4}>
              <Star size={14} color="#666" />
              <Text size="xs" c="dimmed">
                {vod.rating}
              </Text>
            </Group>
          )}
        </Group>

        {vod.genre && (
          <Text size="xs" c="dimmed" lineClamp={1}>
            {vod.genre}
          </Text>
        )}
      </Stack>
    </Card>
  );
};

export default VODCard;