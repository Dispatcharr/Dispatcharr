import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import ProgramDetailModal from '../ProgramDetailModal';
import API from '../../api';
import useVideoStore from '../../store/useVideoStore';
import useSettingsStore from '../../store/settings';

vi.mock('../../api');
vi.mock('../../store/useVideoStore');
vi.mock('../../store/settings');
vi.mock('../../utils/cards/RecordingCardUtils.js', () => ({
  getShowVideoUrl: vi.fn(() => 'http://video.test'),
}));

vi.mock('../../images/logo.png', () => ({ default: 'default-logo.png' }));

vi.mock('../../utils/dateTimeUtils.js', () => ({
  format: vi.fn(() => '12:00 PM'),
  initializeTime: vi.fn((v) => v),
  diff: vi.fn(() => 60),
  useDateTimeFormat: vi.fn(() => ({ timeFormat: 'h:mm A' })),
}));

vi.mock('../../utils/guideUtils', () => ({
  formatSeasonEpisode: vi.fn((s, e) => {
    if (s != null && e != null)
      return `S${String(s).padStart(2, '0')}E${String(e).padStart(2, '0')}`;
    if (s != null) return `S${String(s).padStart(2, '0')}`;
    if (e != null) return `E${String(e).padStart(2, '0')}`;
    return null;
  }),
}));

vi.mock('@mantine/core', async () => {
  const actual = await vi.importActual('@mantine/core');
  return {
    ...actual,
    Modal: ({ children, opened, onClose, title }) =>
      opened ? (
        <div data-testid="modal">
          <div data-testid="modal-title">{title}</div>
          <button data-testid="modal-close" onClick={onClose}>
            Close
          </button>
          {children}
        </div>
      ) : null,
    Stack: ({ children }) => <div>{children}</div>,
    Flex: ({ children }) => <div>{children}</div>,
    Group: ({ children }) => <div>{children}</div>,
    Text: ({ children }) => <span>{children}</span>,
    Title: ({ children }) => <h3>{children}</h3>,
    Badge: ({ children, component, href }) =>
      component === 'a' ? (
        <a href={href}>{children}</a>
      ) : (
        <span>{children}</span>
      ),
    Button: ({ children, onClick }) => (
      <button onClick={onClick}>{children}</button>
    ),
    Image: ({ src }) => <img src={src} alt="" />,
    Divider: () => <hr />,
    Loader: () => <div data-testid="loader">Loading...</div>,
  };
});

describe('ProgramDetailModal', () => {
  const baseProgram = {
    id: 1,
    title: 'Breaking Bad',
    sub_title: 'Pilot',
    description: 'A chemistry teacher turns to crime.',
    season: 1,
    episode: 1,
    start_time: '2024-01-15T20:00:00Z',
    end_time: '2024-01-15T21:00:00Z',
    startMs: 1705348800000,
    endMs: 1705352400000,
    is_live: false,
    is_new: true,
    is_premiere: true,
    is_finale: false,
    isLive: true,
    isPast: false,
  };

  const baseChannel = {
    id: 'ch-1',
    name: 'AMC',
    channel_number: 4,
    logo: { url: 'http://logo.test/amc.png' },
  };

  beforeEach(() => {
    vi.clearAllMocks();
    useVideoStore.mockImplementation((selector) =>
      selector({ showVideo: vi.fn() })
    );
    useSettingsStore.mockImplementation((selector) => {
      const state = {
        environment: { env_mode: 'production' },
      };
      return selector ? selector(state) : state;
    });
    API.getProgramDetail = vi.fn().mockResolvedValue(null);
  });

  it('renders nothing when program is null', () => {
    const { container } = render(
      <ProgramDetailModal
        program={null}
        channel={baseChannel}
        opened={true}
        onClose={vi.fn()}
      />
    );
    expect(container.innerHTML).toBe('');
  });

  it('renders modal with program title', async () => {
    render(
      <ProgramDetailModal
        program={baseProgram}
        channel={baseChannel}
        opened={true}
        onClose={vi.fn()}
      />
    );

    expect(screen.getByTestId('modal')).toBeInTheDocument();
    expect(screen.getByTestId('modal-title')).toHaveTextContent('4 - AMC');
    expect(screen.getByText('Breaking Bad')).toBeInTheDocument();
  });

  it('displays subtitle when present', async () => {
    render(
      <ProgramDetailModal
        program={baseProgram}
        channel={baseChannel}
        opened={true}
        onClose={vi.fn()}
      />
    );

    expect(screen.getByText('Pilot')).toBeInTheDocument();
  });

  it('displays season/episode badge', async () => {
    render(
      <ProgramDetailModal
        program={baseProgram}
        channel={baseChannel}
        opened={true}
        onClose={vi.fn()}
      />
    );

    expect(screen.getByText('S01E01')).toBeInTheDocument();
  });

  it('displays NEW badge when program is new', async () => {
    render(
      <ProgramDetailModal
        program={baseProgram}
        channel={baseChannel}
        opened={true}
        onClose={vi.fn()}
      />
    );

    expect(screen.getByText('NEW')).toBeInTheDocument();
  });

  it('displays PREMIERE badge when program is premiere', async () => {
    render(
      <ProgramDetailModal
        program={baseProgram}
        channel={baseChannel}
        opened={true}
        onClose={vi.fn()}
      />
    );

    expect(screen.getByText('PREMIERE')).toBeInTheDocument();
  });

  it('displays description', async () => {
    render(
      <ProgramDetailModal
        program={baseProgram}
        channel={baseChannel}
        opened={true}
        onClose={vi.fn()}
      />
    );

    expect(
      screen.getByText('A chemistry teacher turns to crime.')
    ).toBeInTheDocument();
  });

  it('shows Record button for non-past programs', async () => {
    render(
      <ProgramDetailModal
        program={baseProgram}
        channel={baseChannel}
        opened={true}
        onClose={vi.fn()}
        onRecord={vi.fn()}
      />
    );

    expect(screen.getByText('Record')).toBeInTheDocument();
  });

  it('hides Record button for past programs', async () => {
    const pastProgram = { ...baseProgram, isPast: true, isLive: false };
    render(
      <ProgramDetailModal
        program={pastProgram}
        channel={baseChannel}
        opened={true}
        onClose={vi.fn()}
        onRecord={vi.fn()}
      />
    );

    expect(screen.queryByText('Record')).not.toBeInTheDocument();
  });

  it('shows Watch Live button for live programs', async () => {
    render(
      <ProgramDetailModal
        program={baseProgram}
        channel={baseChannel}
        opened={true}
        onClose={vi.fn()}
      />
    );

    expect(screen.getByText('Watch Live')).toBeInTheDocument();
  });

  it('hides Watch Live button for non-live programs', async () => {
    const futureProgram = { ...baseProgram, isLive: false };
    render(
      <ProgramDetailModal
        program={futureProgram}
        channel={baseChannel}
        opened={true}
        onClose={vi.fn()}
      />
    );

    expect(screen.queryByText('Watch Live')).not.toBeInTheDocument();
  });

  it('calls onClose when modal close is triggered', async () => {
    const onClose = vi.fn();
    render(
      <ProgramDetailModal
        program={baseProgram}
        channel={baseChannel}
        opened={true}
        onClose={onClose}
      />
    );

    fireEvent.click(screen.getByTestId('modal-close'));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('calls onRecord when Record button is clicked', async () => {
    const onRecord = vi.fn();
    render(
      <ProgramDetailModal
        program={baseProgram}
        channel={baseChannel}
        opened={true}
        onClose={vi.fn()}
        onRecord={onRecord}
      />
    );

    fireEvent.click(screen.getByText('Record'));
    expect(onRecord).toHaveBeenCalledWith(baseProgram);
  });

  it('fetches program detail on open', async () => {
    API.getProgramDetail.mockResolvedValue({
      description: 'Enriched description',
      categories: ['Drama'],
    });

    render(
      <ProgramDetailModal
        program={baseProgram}
        channel={baseChannel}
        opened={true}
        onClose={vi.fn()}
      />
    );

    await waitFor(() => {
      expect(API.getProgramDetail).toHaveBeenCalledWith(1);
    });
  });

  it('skips detail fetch for dummy programs with string IDs', async () => {
    const dummyProgram = {
      ...baseProgram,
      id: 'dummy-uuid-1234',
    };

    render(
      <ProgramDetailModal
        program={dummyProgram}
        channel={baseChannel}
        opened={true}
        onClose={vi.fn()}
      />
    );

    expect(API.getProgramDetail).not.toHaveBeenCalled();
  });

  it('renders with minimal data (title + time only)', async () => {
    const minimalProgram = {
      id: 2,
      title: 'Sports Event',
      start_time: '2024-01-15T18:00:00Z',
      end_time: '2024-01-15T20:00:00Z',
      startMs: 1705341600000,
      endMs: 1705348800000,
      isLive: false,
      isPast: false,
    };

    render(
      <ProgramDetailModal
        program={minimalProgram}
        channel={baseChannel}
        opened={true}
        onClose={vi.fn()}
      />
    );

    expect(screen.getByTestId('modal-title')).toHaveTextContent('4 - AMC');
    expect(screen.getByText('Sports Event')).toBeInTheDocument();
  });

  it('displays enriched detail data after fetch', async () => {
    API.getProgramDetail.mockResolvedValue({
      description: 'Enriched description from API',
      categories: ['Drama', 'Crime'],
      credits: {
        actors: [{ name: 'Bryan Cranston', role: 'Walter White' }],
        directors: ['Vince Gilligan'],
      },
      imdb_id: 'tt0903747',
      tmdb_id: '1396',
    });

    render(
      <ProgramDetailModal
        program={baseProgram}
        channel={baseChannel}
        opened={true}
        onClose={vi.fn()}
      />
    );

    await waitFor(() => {
      expect(
        screen.getByText('Enriched description from API')
      ).toBeInTheDocument();
    });

    expect(screen.getByText(/Bryan Cranston/)).toBeInTheDocument();
    expect(screen.getByText(/Vince Gilligan/)).toBeInTheDocument();
  });

  it('displays channel name and number', async () => {
    render(
      <ProgramDetailModal
        program={baseProgram}
        channel={baseChannel}
        opened={true}
        onClose={vi.fn()}
      />
    );

    expect(screen.getByText(/4 - AMC/)).toBeInTheDocument();
  });

  it('displays channel name without number when not available', async () => {
    const channelNoNumber = { ...baseChannel, channel_number: null };
    render(
      <ProgramDetailModal
        program={baseProgram}
        channel={channelNoNumber}
        opened={true}
        onClose={vi.fn()}
      />
    );

    expect(screen.getByText('AMC')).toBeInTheDocument();
  });

  it('displays external links when IDs are available', async () => {
    API.getProgramDetail.mockResolvedValue({
      imdb_id: 'tt0903747',
      tmdb_id: '1396',
    });

    render(
      <ProgramDetailModal
        program={baseProgram}
        channel={baseChannel}
        opened={true}
        onClose={vi.fn()}
      />
    );

    await waitFor(() => {
      const imdbLink = screen.getByText(/IMDb/);
      expect(imdbLink).toBeInTheDocument();
      expect(imdbLink.closest('a')).toHaveAttribute(
        'href',
        'https://www.imdb.com/title/tt0903747'
      );
    });
  });
});
