import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import CatchupIndicator, { formatCatchupTooltip } from '../CatchupIndicator';

vi.mock('@mantine/core', () => ({
  Badge: ({ children, leftSection }) => (
    <span data-testid="catchup-badge">
      {leftSection}
      {children}
    </span>
  ),
  Box: ({ children, ...props }) => <span {...props}>{children}</span>,
  Tooltip: ({ children, label }) => <div data-tooltip={label}>{children}</div>,
}));

vi.mock('lucide-react', () => ({
  History: () => <svg data-testid="icon-history" />,
}));

describe('formatCatchupTooltip', () => {
  it('includes archive days when known', () => {
    expect(formatCatchupTooltip(7)).toBe('Catch-up enabled (7 days archive)');
    expect(formatCatchupTooltip(1)).toBe('Catch-up enabled (1 day archive)');
  });

  it('falls back when days are zero', () => {
    expect(formatCatchupTooltip(0)).toBe('Catch-up enabled');
  });
});

describe('CatchupIndicator', () => {
  it('renders nothing when catch-up is disabled', () => {
    const { container } = render(
      <CatchupIndicator isCatchup={false} catchupDays={7} />
    );
    expect(container).toBeEmptyDOMElement();
  });

  it('renders a history icon in table rows', () => {
    render(<CatchupIndicator isCatchup catchupDays={3} />);
    expect(screen.getByTestId('icon-history')).toBeInTheDocument();
    expect(
      screen.getByLabelText('Catch-up enabled (3 days archive)')
    ).toBeInTheDocument();
  });

  it('renders a badge in expanded stream rows', () => {
    render(<CatchupIndicator isCatchup catchupDays={5} variant="badge" />);
    expect(screen.getByTestId('catchup-badge')).toHaveTextContent('Catch-up');
    expect(screen.getByTestId('icon-history')).toBeInTheDocument();
  });
});
