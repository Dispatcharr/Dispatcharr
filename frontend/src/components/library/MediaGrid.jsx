import React, { useMemo } from 'react';
import { Box, Group, Loader, SimpleGrid, Stack, Text } from '@mantine/core';
import AutoSizer from 'react-virtualized-auto-sizer';
import { FixedSizeGrid as VirtualGrid } from 'react-window';
import MediaCard from './MediaCard';

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

const getColumnCount = (width, columns) => {
  if (!width) return columns.base || 1;
  if (width >= 1400 && columns.xl) return columns.xl;
  if (width >= 1200 && columns.lg) return columns.lg;
  if (width >= 992 && columns.md) return columns.md;
  if (width >= 768 && columns.sm) return columns.sm;
  return columns.base || 1;
};

const CARD_HEIGHT_MAP = {
  sm: 220,
  md: 260,
  lg: 320,
};

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
  const rowHeight = useMemo(() => {
    const base = CARD_HEIGHT_MAP[cardSize] ?? CARD_HEIGHT_MAP.md;
    return base + GRID_SPACING;
  }, [cardSize]);

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
              <SimpleGrid cols={columns} spacing="lg">
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
          const columnCount = getColumnCount(width, columns);
          const rowCount = Math.ceil(items.length / columnCount);
          const columnWidth = width / columnCount;
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
