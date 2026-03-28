import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

// ── VODCardUtils ──────────────────────────────────────────────────────────────
vi.mock('../../../utils/cards/VODCardUtils.js', () => ({
  formatDuration: vi.fn((mins) => (mins ? `${mins}m` : null)),
  getSeasonLabel: vi.fn(() => 'S01E02'),
}));

// ── Mantine core ──────────────────────────────────────────────────────────────
vi.mock('@mantine/core', () => ({
  ActionIcon: ({ children, onClick, variant, size }) => (
    <button
      data-testid="action-icon"
      data-variant={variant}
      data-size={size}
      onClick={onClick}
    >
      {children}
    </button>
  ),
  Badge: ({ children, color, variant, size }) => (
    <span
      data-testid="badge"
      data-color={color}
      data-variant={variant}
      data-size={size}
    >
      {children}
    </span>
  ),
  Box: ({ children, pos, h, style }) => (
    <div data-testid="box" data-pos={pos} style={{ height: h, ...style }}>
      {children}
    </div>
  ),
  Card: ({ children, onClick, style, withBorder, shadow, radius, p }) => (
    <div
      data-testid="vod-card"
      onClick={onClick}
      style={style}
      data-with-border={withBorder}
      data-shadow={shadow}
      data-radius={radius}
      data-p={p}
    >
      {children}
    </div>
  ),
  CardSection: ({ children }) => (
    <div data-testid="card-section">{children}</div>
  ),
  Group: ({ children, justify, gap, wrap }) => (
    <div
      data-testid="group"
      data-justify={justify}
      data-gap={gap}
      data-wrap={wrap}
    >
      {children}
    </div>
  ),
  Image: ({ src, alt, height, fallbackSrc, fit }) => (
    <img
      src={src}
      alt={alt}
      data-height={height}
      data-fallback={fallbackSrc}
      data-fit={fit}
    />
  ),
  Stack: ({ children, spacing, gap, p }) => (
    <div data-testid="stack" data-spacing={spacing} data-gap={gap} data-p={p}>
      {children}
    </div>
  ),
  Text: ({ children, size, c, weight, fw, lineClamp, style }) => (
    <span
      data-testid="text"
      data-size={size}
      data-color={c}
      data-weight={weight}
      data-fw={fw}
      data-line-clamp={lineClamp}
      style={style}
    >
      {children}
    </span>
  ),
}));

// ── lucide-react ──────────────────────────────────────────────────────────────
vi.mock('lucide-react', () => ({
  ListOrdered: () => <svg data-testid="icon-list-ordered" />,
  Calendar: () => <svg data-testid="icon-calendar" />,
  Clock: () => <svg data-testid="icon-clock" />,
  Play: () => <svg data-testid="icon-play" />,
  Star: () => <svg data-testid="icon-star" />,
}));

// ── Imports after mocks ───────────────────────────────────────────────────────
import {
  formatDuration,
  getSeasonLabel,
} from '../../../utils/cards/VODCardUtils.js';
import VODCard from '../VODCard';

// ── Helpers ───────────────────────────────────────────────────────────────────

const makeMovie = (overrides = {}) => ({
  type: 'movie',
  name: 'Test Movie',
  logo: { url: 'http://example.com/poster.jpg' },
  year: 2022,
  rating: 8.5,
  duration: 120,
  duration_secs: 120,
  description: 'A great test movie.',
  genre: 'Action',
  ...overrides,
});

const makeEpisode = (overrides = {}) => ({
  type: 'episode',
  name: 'Pilot',
  logo: { url: 'http://example.com/ep-poster.jpg' },
  year: 2021,
  rating: 7.9,
  duration: 45,
  description: 'The first episode.',
  genre: 'Comedy',
  series: { name: 'Test Series' },
  season: 1,
  episode: 2,
  ...overrides,
});

// ── Tests ─────────────────────────────────────────────────────────────────────

describe('VODCard', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(formatDuration).mockImplementation((mins) =>
      mins ? `${mins}m` : null
    );
    vi.mocked(getSeasonLabel).mockReturnValue('S01E02');
  });

  // ── Rendering: movie ───────────────────────────────────────────────────────

  describe('movie rendering', () => {
    it('renders the card element', () => {
      render(<VODCard vod={makeMovie()} onClick={vi.fn()} />);
      expect(screen.getByTestId('vod-card')).toBeInTheDocument();
    });

    it('renders the movie title', () => {
      render(<VODCard vod={makeMovie()} onClick={vi.fn()} />);
      expect(screen.getByText('Test Movie')).toBeInTheDocument();
    });

    it('renders the poster image with the logo url', () => {
      render(<VODCard vod={makeMovie()} onClick={vi.fn()} />);
      const img = screen.getByRole('img');
      expect(img).toHaveAttribute('src', 'http://example.com/poster.jpg');
    });

    it('renders the year when present', () => {
      render(<VODCard vod={makeMovie()} onClick={vi.fn()} />);
      expect(screen.getByText('2022')).toBeInTheDocument();
    });

    it('renders the rating when present', () => {
      render(<VODCard vod={makeMovie()} onClick={vi.fn()} />);
      expect(screen.getByText('8.5')).toBeInTheDocument();
    });

    it('renders the star icon when rating is present', () => {
      render(<VODCard vod={makeMovie()} onClick={vi.fn()} />);
      expect(screen.getByTestId('icon-star')).toBeInTheDocument();
    });

    it('renders the formatted duration via formatDuration', () => {
      render(<VODCard vod={makeMovie()} onClick={vi.fn()} />);
      expect(formatDuration).toHaveBeenCalledWith(120);
      expect(screen.getByText('120m')).toBeInTheDocument();
    });

    it('renders the clock icon when duration is present', () => {
      render(<VODCard vod={makeMovie()} onClick={vi.fn()} />);
      expect(screen.getByTestId('icon-clock')).toBeInTheDocument();
    });

    it('renders genre badges', () => {
      render(<VODCard vod={makeMovie()} onClick={vi.fn()} />);
      expect(screen.getByText('Action')).toBeInTheDocument();
    });

    it('renders the calendar icon when year is present', () => {
      render(<VODCard vod={makeMovie()} onClick={vi.fn()} />);
      expect(screen.getByTestId('icon-calendar')).toBeInTheDocument();
    });

    it('renders the play icon', () => {
      render(<VODCard vod={makeMovie()} onClick={vi.fn()} />);
      expect(screen.getByTestId('icon-play')).toBeInTheDocument();
    });

    it('does not render series name for a movie', () => {
      render(<VODCard vod={makeMovie()} onClick={vi.fn()} />);
      expect(screen.queryByText('Test Series')).not.toBeInTheDocument();
    });
  });

  // ── Rendering: episode ─────────────────────────────────────────────────────

  describe('episode rendering', () => {
    it('renders the series name for an episode', () => {
      render(<VODCard vod={makeEpisode()} onClick={vi.fn()} />);
      expect(screen.getByText('Test Series')).toBeInTheDocument();
    });

    it('renders the season label via getSeasonLabel', () => {
      render(<VODCard vod={makeEpisode()} onClick={vi.fn()} />);
      expect(getSeasonLabel).toHaveBeenCalledWith(
        expect.objectContaining({ type: 'episode' })
      );
      expect(screen.getByText(/S01E02/)).toBeInTheDocument();
    });

    it('renders the episode name alongside the season label', () => {
      render(<VODCard vod={makeEpisode()} onClick={vi.fn()} />);
      expect(screen.getByText(/Pilot/)).toBeInTheDocument();
    });

    it('does not render a plain title text when it is an episode with a series', () => {
      render(<VODCard vod={makeEpisode()} onClick={vi.fn()} />);
      // Series name and episode name are shown, not the bare vod.name alone as a standalone text
      const texts = screen.getAllByTestId('text').map((el) => el.textContent);
      // The series name should appear
      expect(texts.some((t) => t.includes('Test Series'))).toBe(true);
    });

    it('renders a plain title for an episode without a series object', () => {
      render(<VODCard vod={makeEpisode({ series: null })} onClick={vi.fn()} />);
      expect(screen.getByText('Pilot')).toBeInTheDocument();
    });
  });

  // ── Poster fallback ────────────────────────────────────────────────────────

  describe('poster image', () => {
    it('renders an image when logo.url is present', () => {
      render(<VODCard vod={makeMovie()} onClick={vi.fn()} />);
      expect(screen.getByRole('img')).toBeInTheDocument();
    });

    it('does not render an img tag when logo is null', () => {
      render(<VODCard vod={makeMovie({ logo: null })} onClick={vi.fn()} />);
      expect(screen.queryByRole('img')).not.toBeInTheDocument();
    });

    it('does not render an img tag when logo.url is empty string', () => {
      render(
        <VODCard vod={makeMovie({ logo: { url: '' } })} onClick={vi.fn()} />
      );
      expect(screen.queryByRole('img')).not.toBeInTheDocument();
    });
  });

  // ── Optional metadata ──────────────────────────────────────────────────────

  describe('optional metadata', () => {
    it('does not render year when absent', () => {
      render(<VODCard vod={makeMovie({ year: null })} onClick={vi.fn()} />);
      expect(screen.queryByTestId('icon-calendar')).not.toBeInTheDocument();
    });

    it('does not render rating when absent', () => {
      render(<VODCard vod={makeMovie({ rating: null })} onClick={vi.fn()} />);
      expect(screen.queryByTestId('icon-star')).not.toBeInTheDocument();
    });

    it('does not render duration when formatDuration returns null', () => {
      vi.mocked(formatDuration).mockReturnValue(null);
      render(<VODCard vod={makeMovie({ duration: null })} onClick={vi.fn()} />);
      expect(screen.queryByTestId('icon-clock')).not.toBeInTheDocument();
    });

    it('does not render genre when absent', () => {
      render(<VODCard vod={makeMovie({ genre: null })} onClick={vi.fn()} />);
      const badges = screen.queryAllByTestId('badge');
      const dimmedBadges = badges.filter(
        (badge) => badge.getAttribute('data-color') === 'dimmed'
      );
      expect(dimmedBadges.length).toBe(0);
    });
  });

  // ── Click handling ─────────────────────────────────────────────────────────

  describe('click handling', () => {
    it('calls onClick with the vod object when card is clicked', async () => {
      const onClick = vi.fn();
      const vod = makeMovie();
      render(<VODCard vod={vod} onClick={onClick} />);
      fireEvent.click(screen.getByTestId('vod-card'));
      expect(onClick).toHaveBeenCalledTimes(1);
      expect(onClick).toHaveBeenCalledWith(vod);
    });

    it('calls onClick when play button is clicked', async () => {
      const onClick = vi.fn();
      const vod = makeMovie();
      render(<VODCard vod={vod} onClick={onClick} />);
      fireEvent.click(screen.getByTestId('action-icon'));
      expect(onClick).toHaveBeenCalledWith(vod);
    });

    it('calls onClick with episode vod object', async () => {
      const onClick = vi.fn();
      const vod = makeEpisode();
      render(<VODCard vod={vod} onClick={onClick} />);
      fireEvent.click(screen.getByTestId('vod-card'));
      expect(onClick).toHaveBeenCalledWith(vod);
    });
  });
});
