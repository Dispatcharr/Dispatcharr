import React, { useLayoutEffect, useRef, useState } from 'react';
import { Box, Group } from '@mantine/core';
import { useElementSize } from '@mantine/hooks';

/**
 * Renders `items` (an array of { key, node }) the way natural flex-wrap
 * would, except once wrapping actually happens, the same items are
 * re-distributed evenly across however many rows resulted (e.g. 4 pills
 * needing 2 rows becomes 2+2, not left-packed 3+1).
 *
 * Two-pass: a hidden measurement copy renders with real flex-wrap so we can
 * read each item's `offsetTop` and count distinct rows, then the visible
 * copy renders that same item count split into that many even-sized rows.
 * Re-measures whenever the item count or the container's width changes
 * (window resize, sidebar collapse, etc).
 */
const EvenlyWrappedPills = ({ items, gap = 'xs', justify = 'center' }) => {
  const { ref: containerRef, width } = useElementSize();
  const measureRefs = useRef([]);
  const [rowCount, setRowCount] = useState(1);

  useLayoutEffect(() => {
    const tops = measureRefs.current
      .slice(0, items.length)
      .map((el) => el?.offsetTop ?? 0);
    const uniqueTops = new Set(tops);
    setRowCount(Math.max(1, uniqueTops.size));
    // width triggers re-measure on resize; item count triggers it when the
    // pill set itself changes (e.g. manifest data finishes loading).
  }, [items.length, width]);

  const perRow = Math.max(1, Math.ceil(items.length / rowCount));
  const rows = [];
  for (let i = 0; i < items.length; i += perRow) {
    rows.push(items.slice(i, i + perRow));
  }

  return (
    <Box ref={containerRef} style={{ width: '100%' }}>
      {/* Measurement-only pass: natural wrap, invisible, not part of layout
          flow (position: absolute keeps it from affecting visible height). */}
      <Group
        gap={gap}
        wrap="wrap"
        style={{ position: 'absolute', visibility: 'hidden', pointerEvents: 'none', width: width || undefined }}
        aria-hidden="true"
      >
        {items.map((item, i) => (
          <span key={item.key} ref={(el) => (measureRefs.current[i] = el)}>
            {item.node}
          </span>
        ))}
      </Group>

      {rows.map((row, i) => (
        <Group key={i} gap={gap} wrap="nowrap" justify={justify} mt={i > 0 ? gap : 0}>
          {row.map((item) => item.node)}
        </Group>
      ))}
    </Box>
  );
};

export default EvenlyWrappedPills;
