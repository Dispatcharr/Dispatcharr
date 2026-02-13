import React, { memo, useMemo } from 'react';
import {
  Badge,
  Box,
  Card,
  CardSection,
  Image,
  Group,
  Stack,
  Text,
} from '@mantine/core';
import { Film, Library as LibraryIcon, Tv2 } from 'lucide-react';
import useSettingsStore from '../../store/settings';

const typeIcon = {
  movie: <Film size={18} />,
  episode: <Tv2 size={18} />,
  show: <LibraryIcon size={18} />,
};

const typeLabel = {
  movie: 'Movie',
  episode: 'Episode',
  show: 'Series',
};

const typeColor = {
  movie: 'green',
  episode: 'blue',
  show: 'violet',
};

const POSTER_ASPECT_RATIO = 2 / 3;
const CARD_PADDING = 16;
const TMDB_CARD_POSTER_SIZE = 'w342';

const POSTER_HEIGHT = {
  sm: 180,
  md: 220,
  lg: 270,
};

const TITLE_BAR_HEIGHT = {
  sm: 0,
  md: 0,
  lg: 0,
};

const FOOTER_HEIGHT = {
  sm: 124,
  md: 128,
  lg: 132,
};

export const getMediaCardDimensions = (size = 'md') => {
  const posterHeight = POSTER_HEIGHT[size] ?? POSTER_HEIGHT.md;
  const titleBarHeight = TITLE_BAR_HEIGHT[size] ?? TITLE_BAR_HEIGHT.md;
  const footerHeight = FOOTER_HEIGHT[size] ?? FOOTER_HEIGHT.md;
  const posterWidth = Math.round(posterHeight * POSTER_ASPECT_RATIO);
  const cardWidth = posterWidth + CARD_PADDING * 2;
  // Account for Mantine Card vertical padding so virtualization row heights align
  // with the true rendered card box and rows do not overlap.
  const cardHeight = posterHeight + titleBarHeight + footerHeight + CARD_PADDING * 2;
  return {
    posterHeight,
    titleBarHeight,
    footerHeight,
    posterWidth,
    cardWidth,
    cardHeight,
  };
};

const formatRuntime = (runtimeMs) => {
  if (!runtimeMs) return null;
  const mins = Math.round(runtimeMs / 60000);
  if (mins < 60) return `${mins} min`;
  const hours = Math.floor(mins / 60);
  const minutes = mins % 60;
  return `${hours}h ${minutes}m`;
};

const resolveArtworkUrl = (url, envMode) => {
  if (!url) return url;
  if (envMode === 'dev' && url.startsWith('/')) {
    return `${window.location.protocol}//${window.location.hostname}:5656${url}`;
  }
  return url;
};

const toCardPosterUrl = (url) => {
  if (!url || typeof url !== 'string') return url;
  if (!/^https?:\/\/image\.tmdb\.org\/t\/p\//i.test(url)) {
    return url;
  }
  return url.replace(
    /\/t\/p\/(?:original|w\d+)\//i,
    `/t/p/${TMDB_CARD_POSTER_SIZE}/`
  );
};

const MediaCard = ({
  item,
  onClick,
  onContextMenu,
  size = 'md',
  showTypeBadge = true,
  style = {},
}) => {
  const envMode = useSettingsStore((s) => s.environment.env_mode);

  const handleClick = () => {
    onClick?.(item);
  };

  const handleKeyDown = (event) => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      handleClick();
    }
  };

  const handleContextMenu = (event) => {
    if (onContextMenu) {
      event.preventDefault();
      onContextMenu(event, item);
    }
  };

  const { posterHeight, footerHeight, cardWidth, cardHeight } =
    getMediaCardDimensions(size);
  const progress = item.watch_progress;
  const watchSummary = item.watch_summary;
  const status = watchSummary?.status;
  const runtimeText = formatRuntime(item.runtime_ms);
  const posterUrl = useMemo(
    () => resolveArtworkUrl(toCardPosterUrl(item.poster_url), envMode),
    [item.poster_url, envMode]
  );
  const hasGenres = Array.isArray(item.genres) && item.genres.length > 0;
  const hasPoster = Boolean(posterUrl);
  const showEpisodeBadge =
    item.item_type === 'show' && watchSummary?.total_episodes;
  const progressPercent = Number.isFinite(progress?.percentage)
    ? Math.max(0, Math.min(100, Math.round(progress.percentage * 100)))
    : null;
  const progressLabel = progress?.completed ? 'Watched' : 'In progress';
  const statusText =
    status === 'in_progress' ? 'In progress' : status === 'watched' ? 'Watched' : null;
  const metaText = useMemo(() => {
    const parts = [];
    if (hasGenres) {
      parts.push(item.genres[0]);
    }
    if (showEpisodeBadge) {
      parts.push(
        `${watchSummary?.completed_episodes || 0}/${watchSummary?.total_episodes} eps`
      );
    }
    if (statusText) {
      parts.push(statusText);
    }
    return parts.filter(Boolean).join(' • ');
  }, [
    hasGenres,
    item.genres,
    showEpisodeBadge,
    statusText,
    watchSummary,
  ]);
  const itemTypeLabel = typeLabel[item.item_type] || 'Media';
  const itemTypeColor = typeColor[item.item_type] || 'gray';

  return (
    <Card
      shadow="sm"
      padding="md"
      radius="md"
      withBorder
      tabIndex={0}
      role="button"
      style={{
        cursor: 'pointer',
        backgroundColor: '#27272A',
        display: 'flex',
        flexDirection: 'column',
        minHeight: cardHeight,
        width: cardWidth,
        maxWidth: cardWidth,
        margin: '0 auto',
        outline: 'none',
        ...style,
      }}
      onClick={handleClick}
      onContextMenu={handleContextMenu}
      onKeyDown={handleKeyDown}
    >
      <CardSection>
        <Box
          style={{
            position: 'relative',
            overflow: 'hidden',
            backgroundColor: '#3f3f46',
            height: posterHeight,
          }}
        >
          {hasPoster ? (
            <Image
              src={posterUrl}
              alt={item.title}
              height={posterHeight}
              fit="cover"
              loading="lazy"
              decoding="async"
            />
          ) : (
            <Stack
              align="center"
              justify="center"
              h={posterHeight}
              style={{
                color: '#a1a1aa',
                textAlign: 'center',
                backgroundColor: '#3f3f46',
              }}
            >
              {typeIcon[item.item_type] || <LibraryIcon size={24} />}
              <Text size="sm" fw={600} ta="center" px="sm" lineClamp={2} c="#e4e4e7">
                {item.title}
              </Text>
            </Stack>
          )}

          {showTypeBadge ? (
            <Badge pos="absolute" bottom={8} left={8} color={itemTypeColor}>
              {itemTypeLabel}
            </Badge>
          ) : null}

          {progressPercent !== null && progressPercent > 0 ? (
            <Badge
              pos="absolute"
              top={8}
              right={8}
              color={progress?.completed ? 'teal' : 'blue'}
            >
              {progressPercent}% {progressLabel}
            </Badge>
          ) : null}
        </Box>
      </CardSection>

      <Stack spacing={8} mt="md" style={{ flex: 1, minHeight: footerHeight }}>
        <Text fw={500} lineClamp={2}>
          {item.title}
        </Text>

        <Group spacing={10}>
          {item.release_year ? (
            <Text size="xs" c="dimmed">
              {item.release_year}
            </Text>
          ) : null}
          {runtimeText ? (
            <Text size="xs" c="dimmed">
              {runtimeText}
            </Text>
          ) : null}
        </Group>

        {metaText ? (
          <Text size="xs" c="dimmed" lineClamp={2}>
            {metaText}
          </Text>
        ) : (
          <Box h={16} />
        )}
      </Stack>
    </Card>
  );
};

export default memo(MediaCard);
