import { act, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import CollapsedTooltip from '../CollapsedTooltip.jsx';

vi.mock('@mantine/core', () => ({
  Tooltip: ({ children, disabled }) => <div data-testid="tooltip" data-disabled={String(disabled)}>{children}</div>,
}));

describe('CollapsedTooltip', () => {
  it('enables the tooltip only when its text is collapsed', () => {
    let resize;
    const original = globalThis.ResizeObserver;
    globalThis.ResizeObserver = class {
      constructor(callback) { resize = callback; }
      observe() {}
      disconnect() {}
    };
    try {
      render(<div className="available-plugin-card"><CollapsedTooltip label="Repository" textSelector=".text"><span className="text">Repository</span></CollapsedTooltip></div>);
      expect(screen.getByTestId('tooltip')).toHaveAttribute('data-disabled', 'true');
      screen.getByText('Repository').style.display = 'none';
      act(() => resize());
      expect(screen.getByTestId('tooltip')).toHaveAttribute('data-disabled', 'false');
      screen.getByText('Repository').style.display = '';
      act(() => resize());
      expect(screen.getByTestId('tooltip')).toHaveAttribute('data-disabled', 'true');
    } finally {
      globalThis.ResizeObserver = original;
    }
  });
});
