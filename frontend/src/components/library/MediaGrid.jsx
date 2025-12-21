import React, { useMemo } from 'react';
import { Box, Group, Loader, SimpleGrid, Stack, Text } from '@mantine/core';
import AutoSizer from 'react-virtualized-auto-sizer';
import { FixedSizeGrid as VirtualGrid } from 'react-window';
import MediaCard, { getMediaCardDimensions } from './MediaCard';

const groupItemsByLetter = (items) => {
  const map = new Map();
  items.forEach((item) => {
    const name = item.sort_title || item.title || '';
    const firstChar = name.charAt(0).toUpperCase();
    const key = /[A-Z]/.test(firstChar) ? firstChar : '#';
    if (!map.has(key)) {
      map.set(key, []);
    }
    map.get(key).push(item);
  });
  return map;
};

const GRID_SPACING = 24;

const VirtualizedCell = ({ columnIndex, rowIndex, style, data }) => {
  const { items, columnCount, onSelect, onContextMenu, cardSize } = data;
  const index = rowIndex * columnCount + columnIndex;
  if (index >= items.length) {
    return null;
  }
  const item = items[index];
  return (
    <Box
      style={{
        ...style,
        padding: GRID_SPACING / 2,
        boxSizing: 'border-box',
      }}
    >
      <MediaCard
        item={item}
        onClick={onSelect}
        onContextMenu={onContextMenu}
        size={cardSize}
      />
    </Box>
  );
};

const MediaGrid = ({
  items,
  loading,
  onSelect,
  onContextMenu,
  groupByLetter = false,
  letterRefs,
  columns = { base: 1, sm: 2, md: 4, lg: 5 },
  cardSize = 'md',
}) => {
  const { cardHeight, cardWidth } = useMemo(
    () => getMediaCardDimensions(cardSize),
    [cardSize]
  );
  const rowHeight = useMemo(() => {
    return cardHeight + GRID_SPACING;
  }, [cardHeight]);

  if (loading) {
    return (
      <Group justify="center" py="xl">
        <Loader />
      </Group>
    );
  }

  if (!items || items.length === 0) {
    return (
      <Text c="dimmed" ta="center" py="xl">
        No media found.
      </Text>
    );
  }

  if (groupByLetter) {
    const grouped = groupItemsByLetter(items);
    const sortedKeys = Array.from(grouped.keys()).sort();
    return (
      <Stack spacing="xl">
        {sortedKeys.map((letter) => {
          const refCallback = (el) => {
            if (letterRefs && el) {
              letterRefs.current[letter] = el;
            }
          };
          return (
            <Stack key={letter} spacing="md" ref={refCallback}>
              <Text fw={700} size="lg">
                {letter}
              </Text>
              <SimpleGrid
                cols={columns}
                spacing="lg"
                style={{
                  gridTemplateColumns: `repeat(auto-fit, minmax(${cardWidth}px, ${cardWidth}px))`,
                  justifyContent: 'flex-start',
                }}
              >
                {grouped.get(letter).map((item) => (
                  <MediaCard
                    key={item.id}
                    item={item}
                    onClick={onSelect}
                    onContextMenu={onContextMenu}
                    size={cardSize}
                  />
                ))}
              </SimpleGrid>
            </Stack>
          );
        })}
      </Stack>
    );
  }

  return (
    <Box
      style={{
        width: '100%',
        height: '70vh',
        minHeight: 480,
      }}
    >
      <AutoSizer>
        {({ height, width }) => {
          if (!width || !height) {
            return null;
          }
          const columnWidth = cardWidth + GRID_SPACING;
          const columnCount = Math.max(1, Math.floor(width / columnWidth));
          const rowCount = Math.ceil(items.length / columnCount);
          return (
            <VirtualGrid
              columnCount={columnCount}
              columnWidth={columnWidth}
              height={height}
              rowCount={rowCount}
              rowHeight={rowHeight}
              width={width}
              itemData={{
                items,
                columnCount,
                onSelect,
                onContextMenu,
                cardSize,
              }}
            >
              {VirtualizedCell}
            </VirtualGrid>
          );
        }}
      </AutoSizer>
    </Box>
  );
};

export default MediaGrid;
