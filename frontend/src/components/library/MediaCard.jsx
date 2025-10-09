import React, { memo } from 'react';
import {
  Badge,
  Box,
  Card,
  Group,
  Image,
  RingProgress,
  Stack,
  Text,
} from '@mantine/core';
import { Film, Library as LibraryIcon, Tv2 } from 'lucide-react';

const typeIcon = {
  movie: <Film size={18} />,
  episode: <Tv2 size={18} />,
  show: <LibraryIcon size={18} />,
};

const formatRuntime = (runtimeMs) => {
  if (!runtimeMs) return null;
  const mins = Math.round(runtimeMs / 60000);
  if (mins < 60) return `${mins} min`;
  const hours = Math.floor(mins / 60);
  const minutes = mins % 60;
  return `${hours}h ${minutes}m`;
};

const MediaCard = ({
  item,
  onClick,
  onContextMenu,
  size = 'md',
  showTypeBadge = true,
}) => {
  const handleContextMenu = (event) => {
    if (onContextMenu) {
      event.preventDefault();
      onContextMenu(event, item);
    }
  };

  const height = size === 'sm' ? 220 : size === 'lg' ? 320 : 260;
  const progress = item.watch_progress;
  const watchSummary = item.watch_summary;
  const status = watchSummary?.status;

  return (
    <Card
      shadow="sm"
      padding="sm"
      radius="md"
      withBorder
      style={{ cursor: 'pointer', background: 'rgba(12, 15, 27, 0.75)' }}
      onClick={() => onClick?.(item)}
      onContextMenu={handleContextMenu}
    >
      <Stack spacing="xs">
        <Box style={{ position: 'relative' }}>
          {item.poster_url ? (
            <Box
              h={height}
              style={{
                borderRadius: 12,
                background: 'rgba(12, 17, 32, 0.65)',
                overflow: 'hidden',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
            >
              <Image
                src={item.poster_url}
                alt={item.title}
                height="100%"
                width="100%"
                fit="contain"
              />
            </Box>
          ) : (
            <Stack
              align="center"
              justify="center"
              h={height}
              style={{
                borderRadius: 12,
                background: 'rgba(30, 41, 59, 0.6)',
              }}
            >
              {typeIcon[item.item_type] || <LibraryIcon size={24} />}
            </Stack>
          )}
          {progress && progress.percentage ? (
            <RingProgress
              style={{ position: 'absolute', top: 10, right: 10 }}
              size={48}
              thickness={4}
              sections={[
                {
                  value: Math.min(100, progress.percentage * 100),
                  color: progress.completed ? 'green' : 'cyan',
                },
              ]}
              label={
                <Text size="xs" c="white">
                  {Math.round(progress.percentage * 100)}%
                </Text>
              }
            />
          ) : null}
        </Box>
        <Stack spacing={4}>
          <Group justify="space-between" align="flex-start" gap="xs">
            <Text fw={600} size="sm" lineClamp={2}>
              {item.title}
            </Text>
            {item.release_year && (
              <Badge variant="outline" size="xs">
                {item.release_year}
              </Badge>
            )}
          </Group>
          <Group gap={6} wrap="wrap">
            {showTypeBadge && (
              <Badge size="xs" color="violet" variant="light" tt="capitalize">
                {item.item_type}
              </Badge>
            )}
            {status === 'watched' && (
              <Badge size="xs" color="green" variant="filled">
                Watched
              </Badge>
            )}
            {status === 'in_progress' && (
              <Badge size="xs" color="yellow" variant="light">
                In progress
              </Badge>
            )}
            {item.item_type === 'show' && watchSummary?.total_episodes ? (
              <Badge size="xs" color="blue" variant="outline">
                {watchSummary.completed_episodes || 0}/
                {watchSummary.total_episodes} episodes
              </Badge>
            ) : null}
          </Group>
          {Array.isArray(item.genres) && item.genres.length > 0 ? (
            <Group gap={4} wrap="wrap">
              {item.genres.slice(0, 3).map((genre) => (
                <Badge key={`${item.id}-${genre}`} size="xs" color="blue" variant="light">
                  {genre}
                </Badge>
              ))}
            </Group>
          ) : null}
          {formatRuntime(item.runtime_ms) && (
            <Text size="xs" c="dimmed">
              {formatRuntime(item.runtime_ms)}
            </Text>
          )}
        </Stack>
      </Stack>
    </Card>
  );
};

export default memo(MediaCard);
