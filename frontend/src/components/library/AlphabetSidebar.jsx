import React, { useMemo, useRef, useState } from 'react';
import { Box, Stack, UnstyledButton, Text } from '@mantine/core';

const letters = ['#', 'A','B','C','D','E','F','G','H','I','J','K','L','M','N','O','P','Q','R','S','T','U','V','W','X','Y','Z'];

const HOTZONE_WIDTH = 20;      // px: invisible strip you hover to reveal
const HOTZONE_BOTTOM_OFFSET = 24; // px: keep a little margin from the bottom
const LETTER_GAP = 6;          // must match Stack spacing
const BASE_FONT_PX = 12;       // Mantine "xs" ~ 12px by default
const MAX_SCALE_BOOST = 0.35;  // how large letters grow at the cursor
const SIGMA_PX = 26;           // controls falloff steepness

export default function AlphabetSidebar({
  available = new Set(),
  onSelect,
  top = 120,
  right = 16,
}) {
  const [isHot, setIsHot] = useState(false);       // pointer inside hot zone or sidebar
  const [mouseY, setMouseY] = useState(null);      // y relative to sidebar
  const [hoveredLetter, setHoveredLetter] = useState(null);
  const sidebarRef = useRef(null);
  const hotZoneHeight = `calc(100vh - ${top}px - ${HOTZONE_BOTTOM_OFFSET}px)`;

  const handleMouseMove = (e) => {
    if (!sidebarRef.current) return;
    const rect = sidebarRef.current.getBoundingClientRect();
    setMouseY(e.clientY - rect.top);
  };

  const handleMouseLeave = () => {
    setIsHot(false);
    setMouseY(null);
  };

  // Precompute the center Y for each letter button (approx.)
  const centers = useMemo(() => {
    // each item height ≈ font + vertical padding (~6px top/bottom) + gap
    const itemH = BASE_FONT_PX + 12 + LETTER_GAP; // tweak if needed to match your Text styles
    return letters.map((_, i) => i * itemH + itemH / 2);
  }, []);

  // Visible when hovering the hot zone or the sidebar, unless idling.
  const visible = isHot;

  return (
    <>
      {/* Invisible hot zone on the far right edge */}
      <Box
        onMouseEnter={() => setIsHot(true)}
        onMouseLeave={handleMouseLeave}
        style={{
          position: 'fixed',
          top,
          right: 0,
          width: HOTZONE_WIDTH,
          height: hotZoneHeight,
          zIndex: 2,
        }}
      />

      {/* Sidebar itself */}
      <Stack
        ref={sidebarRef}
        spacing={LETTER_GAP}
        align="center"
        onMouseEnter={() => setIsHot(true)}
        onMouseLeave={handleMouseLeave}
        onMouseMove={handleMouseMove}
        style={{
          position: 'fixed',
          top,
          right,
          zIndex: 3,
          background: 'rgba(12, 12, 16, 0.75)',
          borderRadius: 12,
          padding: '10px 6px',
          backdropFilter: 'blur(4px)',
          // reveal/fade logic
          opacity: visible ? 1 : 0,
          pointerEvents: visible ? 'auto' : 'none', // click-through when hidden
          transform: visible ? 'translateX(0)' : 'translateX(8px)', // subtle slide
          transition: 'opacity 160ms ease, transform 160ms ease',
        }}
      >
        {letters.map((letter, idx) => {
          const isEnabled = available.has(letter);
          // proximity scale
          let scale = 1;
          if (mouseY != null) {
            const d = Math.abs(mouseY - centers[idx]);
            const boost = Math.exp(-(d * d) / (2 * SIGMA_PX * SIGMA_PX)); // 0..1
            scale = 1 + MAX_SCALE_BOOST * boost;
          }
          if (hoveredLetter === letter) {
            scale = Math.max(scale, 1.5);
          }

          return (
            <UnstyledButton
              key={letter}
              onClick={() => isEnabled && onSelect?.(letter)}
              onMouseEnter={() => setHoveredLetter(letter)}
              onMouseLeave={() => setHoveredLetter(null)}
              onFocus={() => setHoveredLetter(letter)}
              onBlur={() => setHoveredLetter(null)}
              style={{
                opacity: isEnabled ? 1 : 0.3,
                cursor: isEnabled ? 'pointer' : 'default',
                transform: `scale(${scale})`,
                transition: 'transform 80ms linear',
                willChange: 'transform',
              }}
            >
              <Text size="xs" fw={700} lh={1}>
                {letter}
              </Text>
            </UnstyledButton>
          );
        })}
      </Stack>
    </>
  );
}
