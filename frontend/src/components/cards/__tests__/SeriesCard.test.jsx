import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import SeriesCard from '../SeriesCard';

// ── Mantine core ───────────────────────────────────────────────────────────────
vi.mock('@mantine/core', async () => ({
  Tooltip: ({ label, children }) => <div data-tooltip={label}>{children}</div>,
  Badge: ({ children, color, variant }) => (
    <span data-testid="badge" data-color={color} data-variant={variant}>
      {children}
    </span>
  ),
  Box: ({ children, pos, h, style }) => (
    <div data-testid="box" style={{ height: h, ...style }} data-pos={pos}>
      {children}
    </div>
  ),
  Card: ({
    children,
    onClick,
    style,
    withBorder,
    shadow,
    padding,
    radius,
    ...props
  }) => (
    <div
      data-testid="series-card"
      onClick={onClick}
      style={style}
      data-with-border={withBorder}
      data-shadow={shadow}
      data-padding={padding}
      data-radius={radius}
      {...props}
    >
      {children}
    </div>
  ),
  CardSection: ({ children }) => (
    <div data-testid="card-section">{children}</div>
  ),
  Group: ({ children, gap, justify }) => (
    <div data-testid="group" data-gap={gap} data-justify={justify}>
      {children}
    </div>
  ),
  Image: ({ src, alt, fallbackSrc, height, fit, loading, onError }) => (
    <img
      src={src}
      alt={alt}
      data-fallback={fallbackSrc}
      data-fit={fit}
      data-height={height}
      loading={loading}
      onError={onError}
    />
  ),
  Stack: ({ children, gap }) => (
    <div data-testid="stack" data-gap={gap}>
      {children}
    </div>
  ),
  Text: ({ children, size, fw, c, lineClamp, style, title, lh }) => (
    <span
      data-testid="text"
      data-size={size}
      data-line-height={lh}
      data-fw={fw}
      data-color={c}
      data-line-clamp={lineClamp}
      style={style}
      title={title}
    >
      {children}
    </span>
  ),
}));

// ── lucide-react ───────────────────────────────────────────────────────────────
vi.mock('lucide-react', () => ({
  ListOrdered: () => <svg data-testid="icon-list-ordered" />,
  Calendar: () => <svg data-testid="icon-calendar" />,
  Play: () => <svg data-testid="icon-play" />,
  Star: () => <svg data-testid="icon-star" />,
}));

const makeSeries = (overrides = {}) => ({
  id: 'series-1',
  name: 'Breaking Bad',
  logo: { url: '/posters/breaking-bad.jpg' },
  year: 2008,
  rating: 9.5,
  genre: 'Drama',
  ...overrides,
});

describe('SeriesCard', () => {
  it('rounds series poster ratings to one decimal', () => {
    render(<SeriesCard series={makeSeries({ rating: '7.787' })} compact />);
    expect(screen.getByText('7.8')).toBeInTheDocument();
  });
  it('keeps the compact Library caption one line and reserves a rating row', () => {
    render(<SeriesCard series={makeSeries({ rating: null })} compact />);
    const title = screen.getByText('Breaking Bad');
    expect(title).toHaveAttribute('data-line-clamp', '1');
    expect(title).toHaveAttribute('data-size', '13');
    expect(title).toHaveAttribute('data-line-height', '1.4');
    expect(title.closest('[data-tooltip]')).toHaveAttribute(
      'data-tooltip',
      'Breaking Bad'
    );
    expect(screen.getByText(/^Series ·/)).toHaveTextContent('Series · 2008');
    expect(screen.getByText('2008')).toBeInTheDocument();
    expect(screen.getByText('—')).toBeInTheDocument();
    expect(screen.queryByText('Drama')).not.toBeInTheDocument();
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
  });
  it('falls back after a failed poster and retries when the artwork changes', () => {
    const { rerender } = render(
      <SeriesCard series={makeSeries()} onClick={vi.fn()} />
    );
    fireEvent.error(screen.getByRole('img'));
    expect(screen.queryByRole('img')).not.toBeInTheDocument();
    expect(screen.getByTestId('icon-play')).toBeInTheDocument();
    rerender(
      <SeriesCard
        series={makeSeries({ logo: { cache_url: '/new-poster' } })}
        onClick={vi.fn()}
      />
    );
    expect(screen.getByRole('img')).toHaveAttribute('src', '/new-poster');
  });
  it.each([0, '0', '0.0', null, undefined, ''])(
    'does not render an empty rating (%s) as a stray number',
    (rating) => {
      render(<SeriesCard series={makeSeries({ rating })} onClick={vi.fn()} />);
      expect(screen.queryByTestId('icon-star')).not.toBeInTheDocument();
      expect(screen.queryByText('0', { exact: true })).not.toBeInTheDocument();
      expect(
        screen.queryByText('0.0', { exact: true })
      ).not.toBeInTheDocument();
    }
  );

  beforeEach(() => {
    vi.clearAllMocks();
  });
  it('opens its preview with Space or Enter', () => {
    const onClick = vi.fn();
    const series = makeSeries();
    render(<SeriesCard series={series} onClick={onClick} />);
    const card = screen.getByRole('button', { name: 'Preview Breaking Bad' });
    fireEvent.keyDown(card, { key: ' ' });
    fireEvent.keyDown(card, { key: 'Enter' });
    expect(onClick).toHaveBeenCalledTimes(2);
    expect(onClick).toHaveBeenLastCalledWith(series);
  });

  // ── Rendering ──────────────────────────────────────────────────────────────

  describe('rendering', () => {
    it('renders the series card', () => {
      render(<SeriesCard series={makeSeries()} onClick={vi.fn()} />);
      expect(screen.getByTestId('series-card')).toBeInTheDocument();
    });

    it('renders the series title', () => {
      render(<SeriesCard series={makeSeries()} onClick={vi.fn()} />);
      expect(screen.getByText('Breaking Bad')).toBeInTheDocument();
    });

    it('renders the poster image with correct src', () => {
      render(<SeriesCard series={makeSeries()} onClick={vi.fn()} />);
      const img = screen.getByAltText('Breaking Bad');
      expect(img).toHaveAttribute('src', '/posters/breaking-bad.jpg');
    });

    it('renders a fallback image when poster_url is missing', () => {
      render(
        <SeriesCard
          series={makeSeries({ poster_url: null })}
          onClick={vi.fn()}
        />
      );
      const img = screen.getByRole('img');
      expect(img).toBeInTheDocument();
    });

    it('renders the year when provided', () => {
      render(<SeriesCard series={makeSeries()} onClick={vi.fn()} />);
      expect(screen.getByText('2008')).toBeInTheDocument();
    });

    it('renders the genre when provided', () => {
      render(<SeriesCard series={makeSeries()} onClick={vi.fn()} />);
      expect(screen.getByText('Drama')).toBeInTheDocument();
    });

    it('renders the rating when provided', () => {
      render(<SeriesCard series={makeSeries()} onClick={vi.fn()} />);
      expect(screen.getByText('9.5')).toBeInTheDocument();
    });

    it('shows the type and year below the poster without an overlay badge', () => {
      render(<SeriesCard series={makeSeries()} onClick={vi.fn()} />);
      expect(screen.getByText(/Series ·/)).toHaveTextContent('Series · 2008');
      expect(screen.getByTestId('card-section')).not.toHaveTextContent(
        'Series'
      );
      expect(screen.queryByTestId('badge')).not.toBeInTheDocument();
    });

    it('fills the responsive poster frame and loads artwork lazily', () => {
      render(<SeriesCard series={makeSeries()} onClick={vi.fn()} />);
      const image = screen.getByRole('img');
      expect(image).toHaveAttribute('data-fit', 'cover');
      expect(image).toHaveAttribute('loading', 'lazy');
      expect(image).not.toHaveAttribute('data-height');
    });

    it('keeps long titles compact while exposing their full text', () => {
      const name = 'A very long series title that needs more than one line';
      render(<SeriesCard series={makeSeries({ name })} onClick={vi.fn()} />);
      expect(screen.getByText(name)).toHaveAttribute('data-line-clamp', '2');
      expect(screen.getByText(name)).toHaveAttribute('title', name);
    });

    it('renders play icon', () => {
      //this only renders when logo.url is missing, but we want to test that the icon itself renders correctly
      render(
        <SeriesCard
          series={makeSeries({ logo: { url: null } })}
          onClick={vi.fn()}
        />
      );
      expect(screen.getByTestId('icon-play')).toBeInTheDocument();
    });

    it('renders star icon', () => {
      render(<SeriesCard series={makeSeries()} onClick={vi.fn()} />);
      expect(screen.getByTestId('icon-star')).toBeInTheDocument();
    });
  });

  // ── Missing/optional fields ────────────────────────────────────────────────

  describe('optional fields', () => {
    it('does not crash when year is missing', () => {
      render(
        <SeriesCard
          series={makeSeries({ year: undefined })}
          onClick={vi.fn()}
        />
      );
      expect(screen.getByTestId('series-card')).toBeInTheDocument();
    });

    it('does not crash when rating is missing', () => {
      render(
        <SeriesCard
          series={makeSeries({ rating: undefined })}
          onClick={vi.fn()}
        />
      );
      expect(screen.getByTestId('series-card')).toBeInTheDocument();
    });

    it('does not crash when genre is missing', () => {
      render(
        <SeriesCard
          series={makeSeries({ genre: undefined })}
          onClick={vi.fn()}
        />
      );
      expect(screen.getByTestId('series-card')).toBeInTheDocument();
    });

    it('does not crash when description is missing', () => {
      render(
        <SeriesCard
          series={makeSeries({ description: undefined })}
          onClick={vi.fn()}
        />
      );
      expect(screen.getByTestId('series-card')).toBeInTheDocument();
    });

    it('does not crash when seasons is missing', () => {
      render(
        <SeriesCard
          series={makeSeries({ seasons: undefined })}
          onClick={vi.fn()}
        />
      );
      expect(screen.getByTestId('series-card')).toBeInTheDocument();
    });

    it('renders without onClick prop', () => {
      render(<SeriesCard series={makeSeries()} />);
      expect(screen.getByTestId('series-card')).toBeInTheDocument();
    });
  });

  // ── Click behavior ─────────────────────────────────────────────────────────

  describe('click behavior', () => {
    it('calls onClick when card is clicked', () => {
      const onClick = vi.fn();
      const series = makeSeries();
      render(<SeriesCard series={series} onClick={onClick} />);
      fireEvent.click(screen.getByTestId('series-card'));
      expect(onClick).toHaveBeenCalledTimes(1);
      expect(onClick).toHaveBeenCalledWith(series);
    });
  });
});
