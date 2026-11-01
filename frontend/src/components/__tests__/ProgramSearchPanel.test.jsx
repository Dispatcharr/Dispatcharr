import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, fireEvent, act, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import ProgramSearchPanel from '../ProgramSearchPanel';
import API from '../../api';

vi.mock('../../api', () => ({
  default: {
    searchPrograms: vi.fn(),
  },
}));

vi.mock('../../utils/dateTimeUtils', async () => {
  const actual = await vi.importActual('../../utils/dateTimeUtils');
  return {
    ...actual,
    useDateTimeFormat: vi.fn(() => ({
      timeFormat: 'HH:mm',
      dateFormat: 'MMM D',
    })),
  };
});

describe('ProgramSearchPanel', () => {
  let onSelect;

  const makeResult = (overrides = {}) => ({
    id: 1,
    title: 'Evening News',
    sub_title: 'Headlines',
    description: 'The day in review.',
    start_time: '2024-01-15T11:30:00Z',
    end_time: '2024-01-15T12:30:00Z',
    tvg_id: 'news.us',
    custom_properties: {},
    epg_source: 'XMLTV',
    epg_name: 'News US',
    channels: [
      {
        id: 101,
        name: 'News One',
        channel_number: 101,
        channel_group: 'News',
        tvg_id: 'news.us',
      },
    ],
    ...overrides,
  });

  const makeResponse = (results, count = results.length) => ({
    count,
    next: null,
    previous: null,
    results,
  });

  // env="test" renders tooltips and dropdowns in place and skips transitions.
  const renderPanel = (props = {}) =>
    render(
      <ProgramSearchPanel
        visible
        recordingsByProgramId={new Map()}
        onSelect={onSelect}
        {...props}
      />,
      {
        wrapper: ({ children }) => (
          <MantineProvider env="test">{children}</MantineProvider>
        ),
      }
    );

  const flush = () => act(async () => {});

  const typeQuery = async (value) => {
    fireEvent.change(screen.getByPlaceholderText('Search programs...'), {
      target: { value },
    });
    await act(async () => {
      vi.advanceTimersByTime(400);
    });
    await flush();
  };

  const lastParams = () => API.searchPrograms.mock.calls.at(-1)[0];

  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2024-01-15T12:00:00Z'));

    onSelect = vi.fn();
    API.searchPrograms.mockResolvedValue(makeResponse([makeResult()]));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  describe('searching', () => {
    it('focuses the search input when shown', () => {
      const { rerender } = renderPanel({ visible: false });
      const input = screen.getByPlaceholderText('Search programs...');
      expect(input).not.toHaveFocus();

      rerender(
        <ProgramSearchPanel
          visible
          recordingsByProgramId={new Map()}
          onSelect={onSelect}
        />
      );

      expect(input).toHaveFocus();
    });

    it('shows search examples when the syntax button is clicked', () => {
      renderPanel();
      expect(screen.queryByText('SEARCH EXAMPLES')).not.toBeInTheDocument();

      fireEvent.click(screen.getByRole('button', { name: 'Search syntax' }));

      expect(screen.getByText('SEARCH EXAMPLES')).toBeInTheDocument();
      expect(screen.getByText('word1 AND word2')).toBeInTheDocument();
      expect(screen.getByText('Either word:')).toBeInTheDocument();
      expect(screen.getByText('"word1 word2"')).toBeInTheDocument();
      expect(
        screen.getByText('(word1 OR word2) AND word3')
      ).toBeInTheDocument();
    });

    it('shows regex examples when Regex is selected', () => {
      renderPanel();
      fireEvent.click(screen.getByLabelText('Regex'));

      fireEvent.click(screen.getByRole('button', { name: 'Search syntax' }));

      expect(screen.getByText('SEARCH EXAMPLES')).toBeInTheDocument();
      expect(screen.getByText('^word1')).toBeInTheDocument();
      expect(screen.getByText('word1$')).toBeInTheDocument();
      expect(screen.getByText('word1.*word2')).toBeInTheDocument();
      expect(screen.getByText('word1|word2')).toBeInTheDocument();
      expect(screen.queryByText('"word1 word2"')).not.toBeInTheDocument();
    });

    it('opens the search examples from the keyboard', async () => {
      vi.useRealTimers();
      const user = userEvent.setup();
      renderPanel();
      expect(screen.getByPlaceholderText('Search programs...')).toHaveFocus();

      await user.tab();
      expect(
        screen.getByRole('button', { name: 'Search syntax' })
      ).toHaveFocus();
      await user.keyboard('{Enter}');

      expect(screen.getByText('SEARCH EXAMPLES')).toBeInTheDocument();
    });

    it('clears the query with the clear button', async () => {
      renderPanel();
      await typeQuery('news');

      fireEvent.click(screen.getByRole('button', { name: 'Clear search' }));
      await flush();

      expect(screen.getByPlaceholderText('Search programs...')).toHaveValue('');
      expect(
        screen.getByText('Type at least 2 characters to search')
      ).toBeInTheDocument();
    });

    it('does not search until the query has 2 characters', async () => {
      renderPanel();

      await typeQuery('a');

      expect(API.searchPrograms).not.toHaveBeenCalled();
      expect(
        screen.getByText('Type at least 2 characters to search')
      ).toBeInTheDocument();
    });

    it('debounces typing into a single request', async () => {
      renderPanel();
      const input = screen.getByPlaceholderText('Search programs...');

      fireEvent.change(input, { target: { value: 'ne' } });
      await act(async () => {
        vi.advanceTimersByTime(200);
      });
      fireEvent.change(input, { target: { value: 'new' } });
      await act(async () => {
        vi.advanceTimersByTime(200);
      });
      expect(API.searchPrograms).not.toHaveBeenCalled();

      await act(async () => {
        vi.advanceTimersByTime(200);
      });
      await flush();

      expect(API.searchPrograms).toHaveBeenCalledTimes(1);
      expect(lastParams().get('title')).toBe('new');
    });

    it('searches immediately on Enter', async () => {
      renderPanel();
      const input = screen.getByPlaceholderText('Search programs...');

      fireEvent.change(input, { target: { value: 'news' } });
      fireEvent.keyDown(input, { key: 'Enter' });
      await flush();

      expect(API.searchPrograms).toHaveBeenCalledTimes(1);

      await act(async () => {
        vi.advanceTimersByTime(400);
      });
      expect(API.searchPrograms).toHaveBeenCalledTimes(1);
    });

    it('aborts a superseded request and ignores its response', async () => {
      let resolveFirst;
      API.searchPrograms
        .mockImplementationOnce(
          () =>
            new Promise((resolve) => {
              resolveFirst = resolve;
            })
        )
        .mockResolvedValueOnce(
          makeResponse([makeResult({ id: 2, title: 'Late Show' })])
        );
      renderPanel();

      await typeQuery('news');
      const firstSignal = API.searchPrograms.mock.calls[0][1].signal;
      await typeQuery('late');

      expect(firstSignal.aborted).toBe(true);
      expect(screen.getByText('Late Show')).toBeInTheDocument();

      await act(async () => {
        resolveFirst(makeResponse([makeResult({ title: 'Stale News' })]));
      });

      expect(screen.queryByText('Stale News')).not.toBeInTheDocument();
      expect(screen.getByText('Late Show')).toBeInTheDocument();
      expect(
        document.querySelector('.mantine-LoadingOverlay-root')
      ).not.toBeInTheDocument();
    });

    it('searches the description when selected', async () => {
      renderPanel();
      await typeQuery('news');

      fireEvent.click(screen.getByLabelText('Description'));
      await flush();

      expect(lastParams().get('description')).toBe('news');
      expect(lastParams().has('title')).toBe(false);
    });
  });

  describe('pagination', () => {
    beforeEach(() => {
      API.searchPrograms.mockResolvedValue(makeResponse([makeResult()], 42));
    });

    it('shows the result count and range', async () => {
      renderPanel();
      await typeQuery('news');

      expect(screen.getByText('42 programs')).toBeInTheDocument();
      expect(screen.getByText('Showing 1-25 of 42')).toBeInTheDocument();
      expect(screen.getByRole('button', { name: '2' })).toBeInTheDocument();
      expect(
        screen.queryByRole('button', { name: '3' })
      ).not.toBeInTheDocument();
    });

    it('keeps the anchor when changing pages', async () => {
      renderPanel();
      await typeQuery('news');
      const firstParams = lastParams();

      vi.setSystemTime(new Date('2024-01-15T12:05:00Z'));
      fireEvent.click(screen.getByRole('button', { name: '2' }));
      await flush();

      expect(API.searchPrograms).toHaveBeenCalledTimes(2);
      expect(lastParams().get('page')).toBe('2');
      expect(lastParams().get('end_after')).toBe(firstParams.get('end_after'));
      expect(screen.getByText('Showing 26-42 of 42')).toBeInTheDocument();
    });

    it('starts over at page 1 with a new anchor when the window changes', async () => {
      renderPanel();
      await typeQuery('news');
      fireEvent.click(screen.getByRole('button', { name: '2' }));
      await flush();

      vi.setSystemTime(new Date('2024-01-15T12:05:00Z'));
      fireEvent.click(screen.getByRole('textbox', { name: 'When' }));
      fireEvent.click(screen.getByRole('option', { name: 'Next 7 days' }));
      await flush();

      expect(API.searchPrograms).toHaveBeenCalledTimes(3);
      expect(lastParams().get('page')).toBe('1');
      expect(lastParams().get('end_after')).toBe('2024-01-15T12:05:00.000Z');
      expect(lastParams().get('start_before')).toBe('2024-01-22T12:05:00.000Z');
    });

    it('starts over at page 1 with a new anchor when the match mode changes', async () => {
      renderPanel();
      await typeQuery('news');
      fireEvent.click(screen.getByRole('button', { name: '2' }));
      await flush();

      vi.setSystemTime(new Date('2024-01-15T12:05:00Z'));
      fireEvent.click(screen.getByLabelText('Regex'));
      await flush();

      expect(API.searchPrograms).toHaveBeenCalledTimes(3);
      expect(lastParams().get('page')).toBe('1');
      expect(lastParams().get('end_after')).toBe('2024-01-15T12:05:00.000Z');
      expect(lastParams().get('title_regex')).toBe('true');
      expect(lastParams().has('title_whole_words')).toBe(false);
    });

    it('searches whole words when Whole word is selected', async () => {
      renderPanel();
      await typeQuery('news');
      expect(lastParams().has('title_whole_words')).toBe(false);

      fireEvent.click(screen.getByLabelText('Whole word'));
      await flush();

      expect(lastParams().get('title_whole_words')).toBe('true');
      expect(lastParams().has('title_regex')).toBe(false);
    });

    it('returns to page 1 when the requested page no longer exists', async () => {
      renderPanel();
      await typeQuery('news');
      API.searchPrograms.mockRejectedValueOnce({
        status: 404,
        body: { detail: 'Invalid page.' },
      });

      fireEvent.click(screen.getByRole('button', { name: '2' }));
      await flush();
      await flush();

      expect(API.searchPrograms).toHaveBeenCalledTimes(3);
      expect(API.searchPrograms.mock.calls[1][0].get('page')).toBe('2');
      expect(lastParams().get('page')).toBe('1');
      expect(screen.queryByRole('alert')).not.toBeInTheDocument();
      expect(screen.getByText('Showing 1-25 of 42')).toBeInTheDocument();
    });
  });

  describe('states', () => {
    it('shows a message when nothing matches', async () => {
      API.searchPrograms.mockResolvedValue(makeResponse([]));
      renderPanel();

      await typeQuery('news');

      expect(
        screen.getByText('No programs match "news" in the next 24 hours')
      ).toBeInTheDocument();
      expect(screen.queryByText(/^Showing/)).not.toBeInTheDocument();
    });

    it('shows an invalid pattern inline and clears it once valid', async () => {
      API.searchPrograms.mockRejectedValueOnce({
        status: 400,
        body: { error: 'Invalid search pattern: unbalanced parenthesis' },
      });
      renderPanel();

      await typeQuery('(news');

      expect(screen.getByRole('alert')).toHaveTextContent(/^Invalid regex$/);
      expect(screen.getByRole('alert')).not.toHaveTextContent(
        'unbalanced parenthesis'
      );
      expect(screen.queryByText('Retry')).not.toBeInTheDocument();

      await typeQuery('(news)');

      expect(screen.queryByRole('alert')).not.toBeInTheDocument();
      expect(screen.getByText('Evening News')).toBeInTheDocument();
    });

    it('shows other errors with a retry button', async () => {
      API.searchPrograms.mockRejectedValueOnce({
        status: 500,
        body: { detail: 'Server exploded' },
      });
      renderPanel();

      await typeQuery('news');

      expect(screen.getByRole('alert')).toHaveTextContent(
        'Search failed. Server exploded'
      );

      fireEvent.click(screen.getByText('Retry'));
      await flush();

      expect(API.searchPrograms).toHaveBeenCalledTimes(2);
      expect(screen.getByText('Evening News')).toBeInTheDocument();
    });
  });

  describe('results', () => {
    it('opens the first channel when the row is clicked', async () => {
      renderPanel();
      await typeQuery('news');

      fireEvent.click(screen.getByText('Evening News'));

      expect(onSelect).toHaveBeenCalledWith(
        expect.objectContaining({ id: 1, isLive: true }),
        expect.objectContaining({ id: 101 })
      );
    });

    it('opens the first channel with Enter on the row', async () => {
      renderPanel();
      await typeQuery('news');

      fireEvent.keyDown(screen.getByRole('button', { name: /Evening News/ }), {
        key: 'Enter',
      });

      expect(onSelect).toHaveBeenCalledWith(
        expect.objectContaining({ id: 1 }),
        expect.objectContaining({ id: 101 })
      );
    });

    it('passes the chip channel for programs on several channels', async () => {
      API.searchPrograms.mockResolvedValue(
        makeResponse([
          makeResult({
            channels: [
              { id: 101, name: 'News One', channel_number: 101 },
              { id: 202, name: 'News Two', channel_number: 202 },
            ],
          }),
        ])
      );
      renderPanel();
      await typeQuery('news');

      fireEvent.click(screen.getByText('202 · News Two'));

      expect(onSelect).toHaveBeenCalledTimes(1);
      expect(onSelect).toHaveBeenCalledWith(
        expect.objectContaining({ id: 1 }),
        expect.objectContaining({ id: 202 })
      );
    });

    it('lists programs with no channel and opens them without one', async () => {
      API.searchPrograms.mockResolvedValue(
        makeResponse([makeResult({ channels: [] })])
      );
      renderPanel();
      await typeQuery('news');

      expect(
        screen.getByText('No channel · News US (XMLTV)')
      ).toBeInTheDocument();
      vi.useRealTimers();
      const user = userEvent.setup();
      await user.hover(screen.getByText('No channel · News US (XMLTV)'));
      expect(
        screen.getByText(
          'No channel uses this EPG entry. Assign it to a channel to watch or record this program.'
        )
      ).toBeInTheDocument();

      fireEvent.click(screen.getByText('Evening News'));

      expect(onSelect).toHaveBeenCalledWith(
        expect.objectContaining({ id: 1 }),
        null
      );
    });

    it('shows only No channel when the EPG entry has no name or source', async () => {
      API.searchPrograms.mockResolvedValue(
        makeResponse([
          makeResult({ channels: [], epg_name: null, epg_source: null }),
        ])
      );
      renderPanel();
      await typeQuery('news');

      expect(screen.getByText('No channel')).toBeInTheDocument();
    });

    it('shows recording and program badges', async () => {
      API.searchPrograms.mockResolvedValue(
        makeResponse([
          makeResult({
            custom_properties: { new: true, season: 1, episode: 2 },
          }),
        ])
      );
      renderPanel({
        recordingsByProgramId: new Map([[1, { id: 9 }]]),
      });
      await typeQuery('news');

      const row = within(screen.getByRole('button', { name: /Evening News/ }));
      expect(row.getByText('Airing now')).toBeInTheDocument();
      expect(row.getByText('Recording')).toBeInTheDocument();
      expect(row.getByText('NEW')).toBeInTheDocument();
      expect(row.getByText('S01E02')).toBeInTheDocument();
      expect(row.queryByText('PREMIERE')).not.toBeInTheDocument();
    });
  });
});
