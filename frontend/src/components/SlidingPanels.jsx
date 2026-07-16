import { useState, useRef } from 'react';
import { Box } from '@mantine/core';

/**
 * Manages drill-down panel navigation for a two-level sidebar.
 *
 * Usage:
 *   const nav = usePanelNav();
 *   nav.push({ type: 'settings' })   // open secondary panel
 *   nav.close()                       // return to primary
 *   nav.displayed                     // safe to read during exit animation
 */
export function usePanelNav() {
  const [panel, setPanel] = useState(null);

  // Retain last non-null value so secondary content stays visible
  // during the slide-out exit animation (when panel is already null).
  const lastRef = useRef(null);
  if (panel !== null) lastRef.current = panel;

  return {
    panel,                          // null = primary visible
    displayed: panel ?? lastRef.current,
    isOpen: panel !== null,
    push: setPanel,                 // React's setPanel is stable, safe in deps
    close: () => setPanel(null),
  };
}

/**
 * Animated two-panel container.
 *
 * When isOpen is false: primary is visible (translateX 0), secondary is off-screen right.
 * When isOpen is true:  secondary slides in from the right, primary slides out left.
 *
 * Props:
 *   isOpen    {boolean}  drives the transition
 *   primary   {ReactNode} root panel content
 *   secondary {ReactNode} drill-down panel content
 */
export function SlidingPanels({ isOpen, primary, secondary }) {
  return (
    <Box style={{ flex: 1, position: 'relative', overflow: 'hidden', minHeight: 0 }}>
      <Box
        style={{
          position: 'absolute',
          inset: 0,
          transform: isOpen ? 'translateX(-100%)' : 'translateX(0%)',
          transition: 'transform 0.22s ease',
        }}
      >
        {primary}
      </Box>
      <Box
        style={{
          position: 'absolute',
          inset: 0,
          transform: isOpen ? 'translateX(0%)' : 'translateX(100%)',
          transition: 'transform 0.22s ease',
        }}
      >
        {secondary}
      </Box>
    </Box>
  );
}
