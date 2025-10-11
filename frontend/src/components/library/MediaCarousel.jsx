import React, { useMemo, useRef } from 'react';
import { ActionIcon, Box, Group, ScrollArea, Stack, Text, rem } from '@mantine/core';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import MediaCard from './MediaCard';

const CARD_WIDTH = {
  sm: 160,  // wider
  md: 200,  // wider
  lg: 240,  // wider
};

const SCROLL_STEP = 4;

const MediaCarousel = ({
  title,
  items,
  onSelect,
  onContextMenu,
  cardSize = 'sm',
  emptyMessage = null,
}) => {
  const viewportRef = useRef(null);
  const cardWidth = useMemo(() => CARD_WIDTH[cardSize], [cardSize]);
  const snapGap = 16;
  const bottomPad = 14; // extra space so card shadows/badges aren't clipped

  if (!items || items.length === 0) {
    if (!emptyMessage) return null;
    return (
      <Stack gap={4}>
        <Text fw={600} size="lg">{title}</Text>
        <Text size="sm" c="dimmed">{emptyMessage}</Text>
      </Stack>
    );
  }

  const scrollByCards = (dir) => {
    const vp = viewportRef.current;
    if (!vp) return;
    vp.scrollBy({
      left: dir * (cardWidth + snapGap) * SCROLL_STEP,
      behavior: 'smooth',
    });
  };

  return (
    <Stack gap="sm">
      <Group justify="space-between" align="center">
        <Text fw={600} size="lg">{title}</Text>
        <Group gap="xs">
          <ActionIcon variant="subtle" aria-label="Scroll left" onClick={() => scrollByCards(-1)}>
            <ChevronLeft size={18} />
          </ActionIcon>
          <ActionIcon variant="subtle" aria-label="Scroll right" onClick={() => scrollByCards(1)}>
            <ChevronRight size={18} />
          </ActionIcon>
        </Group>
      </Group>

      <ScrollArea
        type="auto"
        scrollbarSize={8}
        offsetScrollbars
        viewportRef={viewportRef}
        styles={{
          viewport: {
            paddingBottom: rem(bottomPad), // <- keep bottoms visible
            scrollSnapType: 'x proximity',
          },
        }}
      >
        <Box
          // add a touch of padding to the row too so shadows never collide
          style={{
            display: 'flex',
            flexWrap: 'nowrap',
            gap: rem(snapGap),
            alignItems: 'stretch',
            minWidth: 'max-content',
            paddingBottom: rem(2),
          }}
        >
          {items.map((item) => (
            <Box
              key={item.id}
              style={{
                flex: `0 0 ${rem(cardWidth)}`,
                width: rem(cardWidth),
                scrollSnapAlign: 'start',
              }}
            >
              <MediaCard
                item={item}
                onClick={onSelect}
                onContextMenu={onContextMenu}
                size={cardSize}
                showTypeBadge={false}
                // ensure the card fills the wrapper (prevents internal overflow)
                style={{ width: '100%', height: '100%' }}
              />
            </Box>
          ))}
        </Box>
      </ScrollArea>
    </Stack>
  );
};

export default MediaCarousel;
