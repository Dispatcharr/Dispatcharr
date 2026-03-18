import {
  Badge,
  Box,
  Card,
  CardSection,
  Group,
  Image,
  Stack,
  Text,
} from '@mantine/core';
import { Calendar, Play, Star } from 'lucide-react';
import React from 'react';

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
      <CardSection>
        <Box pos="relative" h={300}>
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
          {/* Add Series badge in the same position as Movie badge */}
          <Badge pos="absolute" bottom={8} left={8} color="purple">
            Series
          </Badge>
        </Box>
      </CardSection>

      <Stack spacing={8} mt="md">
        <Text weight={500}>{series.name}</Text>

        <Group spacing={16}>
          {series.year && (
            <Group spacing={4}>
              <Calendar size={14} color="#666" />
              <Text size="xs" c="dimmed">
                {series.year}
              </Text>
            </Group>
          )}
          {series.rating && (
            <Group spacing={4}>
              <Star size={14} color="#666" />
              <Text size="xs" c="dimmed">
                {series.rating}
              </Text>
            </Group>
          )}
        </Group>

        {series.genre && (
          <Text size="xs" c="dimmed" lineClamp={1}>
            {series.genre}
          </Text>
        )}
      </Stack>
    </Card>
  );
};

export default SeriesCard;
