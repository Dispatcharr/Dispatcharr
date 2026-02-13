import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Box, Group, Loader, Stack, Text } from '@mantine/core';
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
const LETTER_GRID_GAP = 16;
const LETTER_SECTION_OVERSCAN_PX = 1200;
const LETTER_ROW_OVERSCAN = 3;

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

const WindowedLetterSection = ({
  letter,
  letterItems,
  cardSize,
  cardWidth,
  cardHeight,
  columnCount,
  onSelect,
  onContextMenu,
  letterRefs,
}) => {
  const sectionRef = useRef(null);
  const gridViewportRef = useRef(null);
  const [renderCards, setRenderCards] = useState(true);
  const [visibleWindow, setVisibleWindow] = useState({ start: 0, end: -1 });
  const rowHeight = cardHeight + LETTER_GRID_GAP;
  const rows = useMemo(() => {
    const chunks = [];
    const safeColumnCount = Math.max(columnCount, 1);
    for (let index = 0; index < letterItems.length; index += safeColumnCount) {
      chunks.push(letterItems.slice(index, index + safeColumnCount));
    }
    return chunks;
  }, [letterItems, columnCount]);

  const totalRows = rows.length;
  const estimatedGridHeight = Math.max(totalRows * rowHeight, rowHeight);
  const placeholderHeight = estimatedGridHeight;

  const sectionRefCallback = useCallback((node) => {
    sectionRef.current = node;
    if (!letterRefs) return;
    if (node) {
      letterRefs.current[letter] = node;
      return;
    }
    delete letterRefs.current[letter];
  }, [letter, letterRefs]);

  useEffect(() => {
    const sectionNode = sectionRef.current;
    if (!sectionNode || typeof IntersectionObserver === 'undefined') {
      setRenderCards(true);
      return undefined;
    }

    const observer = new IntersectionObserver(
      (entries) => {
        const isVisible = entries.some((entry) => entry.isIntersecting);
        setRenderCards(isVisible);
      },
      {
        root: null,
        rootMargin: `${LETTER_SECTION_OVERSCAN_PX}px 0px`,
      }
    );
    observer.observe(sectionNode);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (!renderCards) {
      setVisibleWindow({ start: 0, end: -1 });
      return undefined;
    }
    if (typeof window === 'undefined') {
      setVisibleWindow({ start: 0, end: Math.max(0, totalRows - 1) });
      return undefined;
    }
    const gridNode = gridViewportRef.current;
    if (!gridNode) {
      setVisibleWindow({ start: 0, end: Math.max(0, totalRows - 1) });
      return undefined;
    }

    let rafId = null;
    const updateVisibleWindow = () => {
      const rect = gridNode.getBoundingClientRect();
      const viewportHeight = window.innerHeight || 0;
      if (viewportHeight <= 0 || totalRows === 0) {
        setVisibleWindow({ start: 0, end: totalRows - 1 });
        return;
      }

      const relativeTop = Math.max(0, -rect.top);
      const relativeBottom = Math.max(0, Math.min(rect.height, viewportHeight - rect.top));
      const windowStart = Math.max(
        0,
        Math.floor(relativeTop / Math.max(rowHeight, 1)) - LETTER_ROW_OVERSCAN
      );
      const windowEnd = Math.min(
        totalRows - 1,
        Math.ceil(relativeBottom / Math.max(rowHeight, 1)) + LETTER_ROW_OVERSCAN
      );
      setVisibleWindow((prev) => {
        if (prev.start === windowStart && prev.end === windowEnd) {
          return prev;
        }
        return { start: windowStart, end: windowEnd };
      });
    };

    const onScrollOrResize = () => {
      if (rafId != null) return;
      rafId = window.requestAnimationFrame(() => {
        rafId = null;
        updateVisibleWindow();
      });
    };

    updateVisibleWindow();
    window.addEventListener('scroll', onScrollOrResize, { passive: true });
    window.addEventListener('resize', onScrollOrResize);
    return () => {
      window.removeEventListener('scroll', onScrollOrResize);
      window.removeEventListener('resize', onScrollOrResize);
      if (rafId != null) {
        window.cancelAnimationFrame(rafId);
      }
    };
  }, [renderCards, totalRows, rowHeight]);

  const visibleStart = Math.max(0, visibleWindow.start);
  const visibleEnd = Math.min(totalRows - 1, visibleWindow.end);
  const hasVisibleRows = visibleEnd >= visibleStart;
  const topSpacerHeight = hasVisibleRows ? visibleStart * rowHeight : estimatedGridHeight;
  const bottomSpacerHeight = hasVisibleRows
    ? Math.max(0, (totalRows - visibleEnd - 1) * rowHeight)
    : 0;
  const visibleRows = hasVisibleRows ? rows.slice(visibleStart, visibleEnd + 1) : [];

  return (
    <Stack spacing="md" ref={sectionRefCallback}>
      <Text fw={700} size="lg">
        {letter}
      </Text>
      {renderCards ? (
        <Box ref={gridViewportRef}>
          {topSpacerHeight > 0 ? <Box h={topSpacerHeight} /> : null}
          {visibleRows.map((rowItems, rowOffset) => (
            <Box
              key={`${letter}-row-${visibleStart + rowOffset}`}
              h={rowHeight}
              style={{ display: 'flex', alignItems: 'flex-start' }}
            >
              <Group align="flex-start" wrap="nowrap" gap="lg">
                {rowItems.map((item) => (
                  <Box
                    key={item.id}
                    data-media-item-id={item.id}
                    style={{ width: cardWidth, flex: '0 0 auto' }}
                  >
                    <MediaCard
                      item={item}
                      onClick={onSelect}
                      onContextMenu={onContextMenu}
                      size={cardSize}
                    />
                  </Box>
                ))}
                {Array.from({ length: Math.max(0, columnCount - rowItems.length) }).map((_, index) => (
                  <Box
                    key={`${letter}-placeholder-${visibleStart + rowOffset}-${index}`}
                    style={{ width: cardWidth, flex: '0 0 auto' }}
                  />
                ))}
              </Group>
            </Box>
          ))}
          {bottomSpacerHeight > 0 ? <Box h={bottomSpacerHeight} /> : null}
        </Box>
      ) : (
        <Box h={placeholderHeight} />
      )}
    </Stack>
  );
};

const MediaGrid = ({
  items,
  loading,
  onSelect,
  onContextMenu,
  groupByLetter = false,
  letterRefs,
  cardSize = 'md',
}) => {
  const { cardHeight, cardWidth } = useMemo(
    () => getMediaCardDimensions(cardSize),
    [cardSize]
  );
  const rowHeight = useMemo(() => {
    return cardHeight + GRID_SPACING;
  }, [cardHeight]);
  const alphaContainerRef = useRef(null);
  const [alphaContainerWidth, setAlphaContainerWidth] = useState(0);

  useEffect(() => {
    if (!groupByLetter) return undefined;
    const containerNode = alphaContainerRef.current;
    if (!containerNode) {
      setAlphaContainerWidth(0);
      return undefined;
    }

    const updateWidth = () => {
      setAlphaContainerWidth(containerNode.clientWidth || 0);
    };
    updateWidth();

    if (typeof ResizeObserver === 'undefined') {
      window.addEventListener('resize', updateWidth);
      return () => window.removeEventListener('resize', updateWidth);
    }

    const observer = new ResizeObserver(() => {
      updateWidth();
    });
    observer.observe(containerNode);
    return () => observer.disconnect();
  }, [groupByLetter, loading, items.length]);

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
    const alphaColumnCount = Math.max(
      1,
      Math.floor((alphaContainerWidth + LETTER_GRID_GAP) / (cardWidth + LETTER_GRID_GAP))
    );

    return (
      <Box ref={alphaContainerRef}>
        <Stack spacing="xl">
          {sortedKeys.map((letter) => (
            <WindowedLetterSection
              key={letter}
              letter={letter}
              letterItems={grouped.get(letter) || []}
              cardSize={cardSize}
              cardWidth={cardWidth}
              cardHeight={cardHeight}
              columnCount={alphaColumnCount}
              onSelect={onSelect}
              onContextMenu={onContextMenu}
              letterRefs={letterRefs}
            />
          ))}
        </Stack>
      </Box>
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
