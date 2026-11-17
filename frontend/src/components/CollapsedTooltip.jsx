import React, { useEffect, useRef, useState } from 'react';
import { Tooltip } from '@mantine/core';

export default function CollapsedTooltip({ label, textSelector, children }) {
  const ref = useRef(null);
  const [collapsed, setCollapsed] = useState(false);

  useEffect(() => {
    const wrapper = ref.current;
    const container = wrapper?.closest('.available-plugin-card');
    if (!container) return;
    const update = () => {
      const text = wrapper.querySelector(textSelector);
      setCollapsed(!!text && (getComputedStyle(text).display === 'none' || text.scrollWidth > text.clientWidth));
    };
    update();
    if (typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(update);
    observer.observe(container);
    return () => observer.disconnect();
  }, [label, textSelector]);

  return (
    <Tooltip label={label} disabled={!collapsed}>
      <div ref={ref} style={{ display: 'inline-flex', minWidth: 0 }}>{children}</div>
    </Tooltip>
  );
}
