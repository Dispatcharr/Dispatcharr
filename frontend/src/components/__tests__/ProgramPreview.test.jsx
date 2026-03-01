import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import ProgramPreview from '../ProgramPreview';

// Mock Mantine components as lightweight stubs
vi.mock('@mantine/core', () => {
  const React = require('react');
  return {
    ActionIcon: ({ children, onClick, ...props }) => (
      <button onClick={onClick} {...props}>
        {children}
      </button>
    ),
    Box: ({ children, ...props }) => <div {...props}>{children}</div>,
    Group: ({ children }) => <div>{children}</div>,
    Progress: ({ value }) => (
      <div data-testid="progress" data-value={value} />
    ),
    Stack: ({ children }) => <div>{children}</div>,
    Text: ({ children }) => <span>{children}</span>,
    Tooltip: ({ children }) => <>{children}</>,
  };
});

vi.mock('lucide-react', () => ({
  ChevronDown: () => <span data-testid="chevron-down" />,
  ChevronRight: () => <span data-testid="chevron-right" />,
  Radio: () => <span data-testid="radio-icon" />,
}));

afterEach(() => {
  vi.useRealTimers();
});

describe('ProgramPreview', () => {
  it('renders nothing when loading=false, fetched=false, program=null', () => {
    const { container } = render(
      <ProgramPreview loading={false} fetched={false} program={null} />
    );
    expect(container.innerHTML).toBe('');
  });

  it('shows loading text when loading=true', () => {
    render(<ProgramPreview loading={true} fetched={false} program={null} />);
    expect(screen.getByText('Loading EPG data...')).toBeTruthy();
  });

  it('shows no current program message when fetched=true and program=null', () => {
    render(<ProgramPreview loading={false} fetched={true} program={null} />);
    expect(
      screen.getByText('No current program (EPG may need refresh)')
    ).toBeTruthy();
  });

  it('shows program title when program is provided', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-01-01T12:00:00.000Z'));

    const now = Date.now();
    const program = {
      title: 'Test Show',
      start_time: new Date(now - 1800000).toISOString(),
      end_time: new Date(now + 1800000).toISOString(),
    };
    render(
      <ProgramPreview
        loading={false}
        fetched={true}
        program={program}
      />
    );
    expect(screen.getByText('Test Show')).toBeTruthy();
  });

  it('shows custom label when label prop is overridden', () => {
    const program = { title: 'Show', start_time: null, end_time: null };
    render(
      <ProgramPreview
        loading={false}
        fetched={true}
        program={program}
        label="Currently Airing:"
      />
    );
    expect(screen.getByText('Currently Airing:')).toBeTruthy();
  });

  it('shows default label "Now Playing:"', () => {
    const program = { title: 'Show', start_time: null, end_time: null };
    render(
      <ProgramPreview
        loading={false}
        fetched={true}
        program={program}
      />
    );
    expect(screen.getByText('Now Playing:')).toBeTruthy();
  });

  it('expand/collapse reveals description and time details', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-01-01T12:00:00.000Z'));

    const now = Date.now();
    const program = {
      title: 'Expandable Show',
      description: 'A detailed description',
      start_time: new Date(now - 3600000).toISOString(),
      end_time: new Date(now + 3600000).toISOString(),
    };
    render(
      <ProgramPreview
        loading={false}
        fetched={true}
        program={program}
      />
    );

    // Description not visible initially
    expect(screen.queryByText('A detailed description')).toBeNull();

    // Click chevron to expand
    const expandButton = screen.getByTestId('chevron-right').closest('button');
    fireEvent.click(expandButton);

    // Description should now be visible
    expect(screen.getByText('A detailed description')).toBeTruthy();

    // Time info visible
    expect(screen.getByText(/elapsed/)).toBeTruthy();
    expect(screen.getByText(/remaining/)).toBeTruthy();

    // Click again to collapse
    const collapseButton = screen.getByTestId('chevron-down').closest('button');
    fireEvent.click(collapseButton);

    // Description and time should be hidden again
    expect(screen.queryByText('A detailed description')).toBeNull();
    expect(screen.queryByText(/elapsed/)).toBeNull();
  });

  it('does not render description block when program has no description', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-01-01T12:00:00.000Z'));

    const now = Date.now();
    const program = {
      title: 'No Desc Show',
      description: null,
      start_time: new Date(now - 3600000).toISOString(),
      end_time: new Date(now + 3600000).toISOString(),
    };
    render(
      <ProgramPreview
        loading={false}
        fetched={true}
        program={program}
      />
    );

    // Expand
    const expandButton = screen.getByTestId('chevron-right').closest('button');
    fireEvent.click(expandButton);

    // Time info should be visible, but no italic description block
    expect(screen.getByText(/elapsed/)).toBeTruthy();
    expect(screen.queryByText('null')).toBeNull();
  });
});

describe('formatProgramTime', () => {
  // We need to test the exported helper; import it via the module
  // Since it's not exported, we test it indirectly through rendered output
  it('formats time with hours correctly', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-01-01T12:00:00.000Z'));

    const now = Date.now();
    const program = {
      title: 'Long Show',
      description: 'desc',
      start_time: new Date(now - 2 * 3600000 - 30 * 60000).toISOString(), // 2h30m ago
      end_time: new Date(now + 30 * 60000).toISOString(), // 30m from now
    };
    render(
      <ProgramPreview
        loading={false}
        fetched={true}
        program={program}
      />
    );

    // Expand to see time
    const expandButton = screen.getByTestId('chevron-right').closest('button');
    fireEvent.click(expandButton);

    // Elapsed should show ~2:30:xx format (with hours)
    const elapsedEl = screen.getByText(/elapsed/);
    expect(elapsedEl.textContent).toMatch(/2:30:\d{2} elapsed/);
  });

  it('formats time without hours correctly', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-01-01T12:00:00.000Z'));

    const now = Date.now();
    const program = {
      title: 'Short Show',
      description: 'desc',
      start_time: new Date(now - 5 * 60000).toISOString(), // 5m ago
      end_time: new Date(now + 25 * 60000).toISOString(), // 25m from now
    };
    render(
      <ProgramPreview
        loading={false}
        fetched={true}
        program={program}
      />
    );

    const expandButton = screen.getByTestId('chevron-right').closest('button');
    fireEvent.click(expandButton);

    // Elapsed should show ~5:xx format (no hours)
    const elapsedEl = screen.getByText(/elapsed/);
    expect(elapsedEl.textContent).toMatch(/5:\d{2} elapsed/);

    // With pinned time, remaining should be exactly 25:00
    const remainingEl = screen.getByText(/remaining/);
    expect(remainingEl.textContent).toBe('25:00 remaining');
  });
});
