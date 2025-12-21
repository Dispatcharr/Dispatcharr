import React, { memo, useEffect, useMemo, useState } from 'react';
import {
  Badge,
  Box,
  Card,
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

const POSTER_ASPECT_RATIO = 2 / 3;
const CARD_PADDING = 10;

const POSTER_HEIGHT = {
  sm: 180,
  md: 220,
  lg: 270,
};

const TITLE_BAR_HEIGHT = {
  sm: 28,
  md: 30,
  lg: 32,
};

const FOOTER_HEIGHT = {
  sm: 30,
  md: 32,
  lg: 34,
};

export const getMediaCardDimensions = (size = 'md') => {
  const posterHeight = POSTER_HEIGHT[size] ?? POSTER_HEIGHT.md;
  const titleBarHeight = TITLE_BAR_HEIGHT[size] ?? TITLE_BAR_HEIGHT.md;
  const footerHeight = FOOTER_HEIGHT[size] ?? FOOTER_HEIGHT.md;
  const posterWidth = Math.round(posterHeight * POSTER_ASPECT_RATIO);
  const cardWidth = posterWidth + CARD_PADDING * 2;
  const cardHeight = posterHeight + footerHeight;
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

const MediaCard = ({
  item,
  onClick,
  onContextMenu,
  size = 'md',
  showTypeBadge = true,
  style = {},
}) => {
  const [isTouch, setIsTouch] = useState(false);
  const [isExpanded, setIsExpanded] = useState(false);
  const [isHovered, setIsHovered] = useState(false);
  const [isFocused, setIsFocused] = useState(false);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    const mediaQuery = window.matchMedia('(hover: none)');
    const updateTouchState = () => {
      setIsTouch(mediaQuery.matches || navigator.maxTouchPoints > 0);
    };
    updateTouchState();
    if (mediaQuery.addEventListener) {
      mediaQuery.addEventListener('change', updateTouchState);
      return () => mediaQuery.removeEventListener('change', updateTouchState);
    }
    mediaQuery.addListener(updateTouchState);
    return () => mediaQuery.removeListener(updateTouchState);
  }, []);

  const handleClick = (event) => {
    if (isTouch && !isExpanded) {
      event.preventDefault();
      event.stopPropagation();
      setIsExpanded(true);
      return;
    }
    setIsExpanded(false);
    onClick?.(item);
  };

  const handleKeyDown = (event) => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      handleClick(event);
    }
  };

  const handleBlur = () => {
    setIsFocused(false);
    if (!isTouch) return;
    setIsExpanded(false);
  };

  const handleMouseLeave = () => {
    setIsHovered(false);
    if (!isTouch) {
      setIsExpanded(false);
    }
  };

  const handleContextMenu = (event) => {
    if (onContextMenu) {
      event.preventDefault();
      onContextMenu(event, item);
    }
  };

  const { posterHeight, titleBarHeight, cardWidth, cardHeight } =
    getMediaCardDimensions(size);
  const minCardHeight = cardHeight;
  const progress = item.watch_progress;
  const watchSummary = item.watch_summary;
  const status = watchSummary?.status;
  const runtimeText = formatRuntime(item.runtime_ms);
  const hasGenres = Array.isArray(item.genres) && item.genres.length > 0;
  const hasPoster = Boolean(item.poster_url);
  const showEpisodeBadge =
    item.item_type === 'show' && watchSummary?.total_episodes;
  const isActive = isExpanded || (!isTouch && isHovered) || isFocused;
  const titleBarExpandedHeight = Math.round(posterHeight * 0.55);
  const metaText = useMemo(() => {
    const parts = [];
    if (hasGenres) {
      parts.push(item.genres[0]);
    }
    if (runtimeText) {
      parts.push(runtimeText);
    }
    if (showEpisodeBadge) {
      parts.push(
        `${watchSummary?.completed_episodes || 0}/${watchSummary?.total_episodes} eps`
      );
    }
    if (status === 'in_progress') {
      parts.push('In progress');
    } else if (status === 'watched') {
      parts.push('Watched');
    }
    if (showTypeBadge && item.item_type) {
      parts.push(item.item_type);
    }
    return parts.filter(Boolean).join(' | ');
  }, [
    hasGenres,
    item.genres,
    item.item_type,
    runtimeText,
    showEpisodeBadge,
    showTypeBadge,
    status,
    watchSummary,
  ]);

  return (
    <Card
      shadow="sm"
      padding={CARD_PADDING}
      radius="md"
      withBorder
      tabIndex={0}
      role="button"
      style={{
        cursor: 'pointer',
        background: 'rgba(12, 15, 27, 0.75)',
        display: 'flex',
        flexDirection: 'column',
        minHeight: minCardHeight,
        width: cardWidth,
        maxWidth: cardWidth,
        margin: '0 auto',
        outline: 'none',
        ...style,
      }}
      onClick={handleClick}
      onContextMenu={handleContextMenu}
      onFocus={() => setIsFocused(true)}
      onBlur={handleBlur}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={handleMouseLeave}
      onKeyDown={handleKeyDown}
    >
      <Stack spacing={8} style={{ flex: 1 }}>
        <Box
          style={{
            position: 'relative',
            borderRadius: 12,
            overflow: 'hidden',
            background: 'rgba(12, 17, 32, 0.75)',
            height: posterHeight,
          }}
        >
          <Box
            style={{
              position: 'absolute',
              inset: 0,
              background: 'rgba(5, 7, 12, 0.2)',
              opacity: isActive ? 0.08 : 0,
              transition: 'opacity 180ms cubic-bezier(0.2, 0, 0, 1)',
              zIndex: 1,
              pointerEvents: 'none',
            }}
          />
          {hasPoster ? (
            <Image
              src={item.poster_url}
              alt={item.title}
              height="100%"
              width="100%"
              fit="contain"
              style={{ position: 'absolute', inset: 0 }}
            />
          ) : (
            <Stack
              align="center"
              justify="center"
              h="100%"
              style={{
                position: 'relative',
                zIndex: 2,
                color: '#e2e8f0',
                textAlign: 'center',
                background:
                  'linear-gradient(160deg, rgba(59, 130, 246, 0.3), rgba(15, 23, 42, 0.8))',
              }}
            >
              {typeIcon[item.item_type] || <LibraryIcon size={24} />}
              <Text size="sm" fw={600} ta="center" px="sm" lineClamp={2}>
                {item.title}
              </Text>
            </Stack>
          )}
          {progress && progress.percentage ? (
            <RingProgress
              style={{ position: 'absolute', top: 10, right: 10, zIndex: 3 }}
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
          {hasPoster ? (
            <Box
              style={{
                position: 'absolute',
                left: 0,
                right: 0,
                bottom: 0,
                zIndex: 2,
                padding: '6px 10px 8px',
                background: isActive
                  ? 'rgba(6, 8, 12, 0.88)'
                  : 'rgba(9, 11, 16, 0.78)',
                backdropFilter: 'blur(6px)',
                height: isActive ? 'auto' : titleBarHeight,
                maxHeight: isActive ? titleBarExpandedHeight : titleBarHeight,
                display: 'flex',
                flexDirection: 'column',
                gap: 4,
                overflow: 'hidden',
                transition:
                  'max-height 200ms cubic-bezier(0.2, 0, 0, 1), background 200ms cubic-bezier(0.2, 0, 0, 1)',
              }}
            >
              <Box style={{ position: 'relative' }}>
                <Text
                  fw={600}
                  lineClamp={isActive ? 4 : 1}
                  style={{
                    fontSize: 13,
                    lineHeight: 1.2,
                    color: '#f8fafc',
                  }}
                >
                  {item.title}
                </Text>
                <Box
                  style={{
                    position: 'absolute',
                    right: 0,
                    top: 0,
                    height: '100%',
                    width: '30%',
                    opacity: isActive ? 0 : 1,
                    transition: 'opacity 160ms cubic-bezier(0.2, 0, 0, 1)',
                    background:
                      'linear-gradient(90deg, rgba(9, 11, 16, 0) 0%, rgba(9, 11, 16, 0.9) 65%, rgba(9, 11, 16, 1) 100%)',
                    pointerEvents: 'none',
                  }}
                />
              </Box>
              {metaText ? (
                <Text
                  size="xs"
                  c="dimmed"
                  lineClamp={2}
                  style={{
                    opacity: isActive ? 1 : 0,
                    maxHeight: isActive ? 48 : 0,
                    overflow: 'hidden',
                    transition:
                      'opacity 160ms cubic-bezier(0.2, 0, 0, 1), max-height 160ms cubic-bezier(0.2, 0, 0, 1)',
                  }}
                >
                  {metaText}
                </Text>
              ) : null}
            </Box>
          ) : null}
        </Box>
        <Box
          style={{
            display: 'flex',
            justifyContent: 'center',
            minHeight: 22,
          }}
        >
          {item.release_year ? (
            <Badge
              size="xs"
              radius="xl"
              variant="outline"
              color="gray"
              style={{
                fontSize: 11,
                letterSpacing: 0.3,
                color: '#cbd5f5',
                borderColor: 'rgba(148, 163, 184, 0.6)',
              }}
            >
              {item.release_year}
            </Badge>
          ) : (
            <Box style={{ height: 22 }} />
          )}
        </Box>
      </Stack>
    </Card>
  );
};

export default memo(MediaCard);
