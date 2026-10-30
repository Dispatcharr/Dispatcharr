import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { StrictMode } from 'react';
import { MantineProvider } from '@mantine/core';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import M3UGroupContentPreview from '../M3UGroupContentPreview.jsx';
import API from '../../../api.js';
import editorClasses from '../AccountEditor.module.css';
import { showNotification } from '../../../utils/notificationUtils.js';

vi.mock('../../../api.js', () => ({
  default: { getM3UGroupContent: vi.fn(), loadM3UGroupContent: vi.fn() },
}));
vi.mock('../../../utils/notificationUtils.js', () => ({
  showNotification: vi.fn(),
  hideNotification: vi.fn(),
}));
const previewElement = (props = {}) => (
  <MantineProvider>
    <M3UGroupContentPreview
      accountId={7}
      scope="live"
      group={{ channel_group: 9, name: 'Events' }}
      onClose={vi.fn()}
      {...props}
    />
  </MantineProvider>
);
const renderPreview = (props = {}) => render(previewElement(props));

describe('M3UGroupContentPreview', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    API.loadM3UGroupContent.mockReset();
    API.getM3UGroupContent.mockResolvedValue({
      count: 250,
      results: [{ relation_id: 1, name: 'Event stream' }],
    });
  });
  it('loads precisely the selected account, scope and group', async () => {
    renderPreview();
    await screen.findByText('Event stream');
    expect(API.getM3UGroupContent).toHaveBeenCalledWith(
      7,
      'live',
      9,
      1,
      50,
      ''
    );
  });
  it('shares the full category count but not a filtered search count with Configure', async () => {
    const onContentLoaded = vi.fn();
    renderPreview({ onContentLoaded });
    await screen.findByText('Event stream');
    expect(onContentLoaded).toHaveBeenCalledWith(
      9,
      expect.objectContaining({ count: 250 })
    );
    onContentLoaded.mockClear();
    API.getM3UGroupContent.mockResolvedValue({
      count: 1,
      results: [{ relation_id: 2, name: 'Filtered stream' }],
    });
    fireEvent.change(screen.getByLabelText('Search'), {
      target: { value: 'Filtered' },
    });
    await screen.findByText('Filtered stream');
    expect(onContentLoaded).not.toHaveBeenCalled();
  });
  it('uses a narrower responsive preview layout', () => {
    renderPreview();
    expect(screen.getByRole('dialog')).toHaveClass(
      editorClasses.previewContent
    );
  });
  it('paginates all content', async () => {
    renderPreview();
    await screen.findByText('Event stream');
    fireEvent.click(screen.getByRole('button', { name: '5' }));
    await waitFor(() =>
      expect(API.getM3UGroupContent).toHaveBeenLastCalledWith(
        7,
        'live',
        9,
        5,
        50,
        ''
      )
    );
  });
  it('searches and resets to the first page', async () => {
    renderPreview();
    await screen.findByText('Event stream');
    fireEvent.change(screen.getByLabelText('Search'), {
      target: { value: 'Football' },
    });
    await waitFor(() =>
      expect(API.getM3UGroupContent).toHaveBeenLastCalledWith(
        7,
        'live',
        9,
        1,
        50,
        'Football'
      )
    );
  });
  it('reports failures and stops loading', async () => {
    API.getM3UGroupContent.mockRejectedValue(
      new Error('Provider content unavailable')
    );
    renderPreview();
    await screen.findByText('Content could not be loaded.');
    expect(showNotification).toHaveBeenCalledWith(
      expect.objectContaining({
        message: 'Provider content unavailable',
        color: 'red',
        autoClose: false,
      })
    );
    expect(
      screen.queryByText('Provider content unavailable')
    ).not.toBeInTheDocument();
  });
  it('does not request content for a closed preview', () => {
    renderPreview({ group: null });
    expect(API.getM3UGroupContent).not.toHaveBeenCalled();
  });
  it('does not flash a spinner or zero count before loading finishes', async () => {
    API.getM3UGroupContent.mockImplementation(() => new Promise(() => {}));
    renderPreview();
    await screen.findByText('Loading category…');
    expect(screen.queryByText('0 imported entries')).not.toBeInTheDocument();
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
  });
  it('frames the table with a sticky header and no extra footer divider', async () => {
    renderPreview({ scope: 'movie' });
    await screen.findByText('Event stream');
    expect(screen.getByRole('table')).toHaveClass(editorClasses.categoryTable);
    expect(
      screen.getByRole('table').closest(`.${editorClasses.categoryTableFrame}`)
    ).not.toBeNull();
    expect(
      screen.getByRole('button', { name: 'Close category preview' })
    ).toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: 'Close' })
    ).not.toBeInTheDocument();
  });
  it('explains an empty category', async () => {
    API.getM3UGroupContent.mockResolvedValue({ count: 0, results: [] });
    renderPreview();
    await screen.findByText('No imported entries in this category.');
    expect(screen.getByText('0 imported entries')).toBeInTheDocument();
  });
  it.each(['movie', 'series'])(
    'does not display source metadata in a %s category preview',
    async (scope) => {
      API.getM3UGroupContent.mockResolvedValue({
        count: 1,
        results: [
          {
            relation_id: 1,
            name: 'Film title',
            source_metadata: { audio_languages: ['eng'], resolution: '1080p' },
          },
        ],
      });
      renderPreview({ scope });
      await screen.findByText('Film title');
      expect(screen.getAllByRole('columnheader')).toHaveLength(1);
      expect(screen.queryByText('Source metadata')).not.toBeInTheDocument();
      expect(screen.queryByText('1080p')).not.toBeInTheDocument();
    }
  );
  it('retries a failed request', async () => {
    API.getM3UGroupContent.mockRejectedValueOnce(new Error('Unavailable'));
    renderPreview();
    await screen.findByText('Content could not be loaded.');
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    await screen.findByText('Event stream');
    expect(API.getM3UGroupContent).toHaveBeenCalledTimes(2);
  });
  it('ignores a response after the preview closes', async () => {
    let resolve;
    API.getM3UGroupContent.mockImplementation(
      () =>
        new Promise((done) => {
          resolve = done;
        })
    );
    const { unmount } = renderPreview();
    await waitFor(() => expect(API.getM3UGroupContent).toHaveBeenCalled());
    unmount();
    resolve({ count: 1, results: [{ relation_id: 1, name: 'Late result' }] });
    expect(showNotification).not.toHaveBeenCalled();
  });

  it.each(['live', 'movie', 'series'])(
    'automatically loads a missing %s category on opening without importing',
    async (scope) => {
      API.getM3UGroupContent.mockResolvedValue({
        count: 0,
        results: [],
        content_source: 'imported',
        can_load_provider: true,
      });
      API.loadM3UGroupContent.mockResolvedValue({
        count: 2,
        results: [{ relation_id: 0, name: 'Provider title' }],
        content_source: 'provider',
        can_load_provider: false,
      });
      renderPreview({ scope });
      await screen.findByText('Provider title');
      expect(API.loadM3UGroupContent).toHaveBeenCalledExactlyOnceWith(
        7,
        scope,
        9,
        50,
        ''
      );
      expect(screen.getByText('2 provider entries')).toBeInTheDocument();
      expect(
        screen.getByText('Provider preview. Nothing has been imported.')
      ).toBeInTheDocument();
      expect(
        screen.queryByRole('button', { name: 'Load category preview' })
      ).not.toBeInTheDocument();
      expect(
        screen.queryByRole('button', { name: /save|import|apply/i })
      ).not.toBeInTheDocument();
    }
  );

  it('does not offer provider loading for standard playlists or imported content', async () => {
    renderPreview();
    await screen.findByText('Event stream');
    expect(
      screen.queryByRole('button', { name: 'Load category preview' })
    ).not.toBeInTheDocument();
    expect(API.loadM3UGroupContent).not.toHaveBeenCalled();
  });

  it('uses the cached server preview for subsequent searches without contacting the provider again', async () => {
    API.getM3UGroupContent.mockResolvedValueOnce({
      count: 0,
      results: [],
      can_load_provider: true,
    });
    const provider = {
      count: 2,
      results: [{ relation_id: 0, name: 'Cached title' }],
      content_source: 'provider',
    };
    API.loadM3UGroupContent.mockResolvedValue(provider);
    API.getM3UGroupContent.mockResolvedValue(provider);
    renderPreview();
    await screen.findByText('Cached title');
    fireEvent.change(screen.getByLabelText('Search'), {
      target: { value: 'Cached' },
    });
    await waitFor(() =>
      expect(API.getM3UGroupContent).toHaveBeenLastCalledWith(
        7,
        'live',
        9,
        1,
        50,
        'Cached'
      )
    );
    expect(API.loadM3UGroupContent).toHaveBeenCalledOnce();
    expect(
      screen.getByText('Provider preview. Nothing has been imported.')
    ).toBeInTheDocument();
  });

  it('retries a failed provider load after checking imported data and the cache again', async () => {
    API.getM3UGroupContent.mockResolvedValue({
      count: 0,
      results: [],
      can_load_provider: true,
    });
    API.loadM3UGroupContent
      .mockRejectedValueOnce(new Error('Connection unavailable'))
      .mockResolvedValue({
        count: 1,
        results: [{ relation_id: 0, name: 'Retry title' }],
        content_source: 'provider',
      });
    renderPreview();
    fireEvent.click(await screen.findByRole('button', { name: 'Retry' }));
    await screen.findByText('Retry title');
    expect(API.loadM3UGroupContent).toHaveBeenCalledTimes(2);
    expect(API.getM3UGroupContent).toHaveBeenCalledTimes(2);
  });

  it('does not flash zero entries while automatically loading and ignores a late failure after closing', async () => {
    let reject;
    API.getM3UGroupContent.mockResolvedValue({
      count: 0,
      results: [],
      can_load_provider: true,
    });
    API.loadM3UGroupContent.mockImplementation(
      () =>
        new Promise((_, fail) => {
          reject = fail;
        })
    );
    const { unmount } = renderPreview();
    await waitFor(() => expect(API.loadM3UGroupContent).toHaveBeenCalledOnce());
    expect(
      screen.queryByRole('button', { name: 'Load category preview' })
    ).not.toBeInTheDocument();
    expect(screen.queryByText('0 imported entries')).not.toBeInTheDocument();
    expect(
      screen.queryByText('No imported entries in this category.')
    ).not.toBeInTheDocument();
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: 'Close category preview' })
    ).toBeEnabled();
    expect(screen.getByLabelText('Search')).toBeDisabled();
    expect(screen.getByText('Loading category…')).toBeInTheDocument();
    expect(API.loadM3UGroupContent).toHaveBeenCalledOnce();
    unmount();
    reject(new Error('Late provider error'));
    await Promise.resolve();
    expect(showNotification).not.toHaveBeenCalled();
  });

  it.each([0, 2])(
    'uses an existing provider cache with %s entries without loading it again',
    async (count) => {
      API.getM3UGroupContent.mockResolvedValue({
        count,
        results: count ? [{ relation_id: 0, name: 'Cached title' }] : [],
        content_source: 'provider',
        can_load_provider: false,
      });
      renderPreview();
      await screen.findByText(`${count} provider entries`);
      expect(API.loadM3UGroupContent).not.toHaveBeenCalled();
      expect(
        screen.queryByRole('button', { name: 'Load category preview' })
      ).not.toBeInTheDocument();
    }
  );

  it('does not start a provider request if the preview closes before its database lookup finishes', async () => {
    let resolve;
    API.getM3UGroupContent.mockImplementation(
      () =>
        new Promise((done) => {
          resolve = done;
        })
    );
    const { unmount } = renderPreview();
    await waitFor(() => expect(API.getM3UGroupContent).toHaveBeenCalled());
    unmount();
    resolve({ count: 0, results: [], can_load_provider: true });
    await Promise.resolve();
    expect(API.loadM3UGroupContent).not.toHaveBeenCalled();
  });

  it('ignores provider results from a previous category when switching categories', async () => {
    let resolve;
    API.getM3UGroupContent
      .mockResolvedValueOnce({ count: 0, results: [], can_load_provider: true })
      .mockResolvedValue({
        count: 1,
        results: [{ relation_id: 1, name: 'Current category' }],
        content_source: 'imported',
      });
    API.loadM3UGroupContent.mockImplementation(
      () =>
        new Promise((done) => {
          resolve = done;
        })
    );
    const { rerender } = renderPreview();
    await waitFor(() => expect(API.loadM3UGroupContent).toHaveBeenCalled());
    rerender(
      previewElement({
        group: { id: 10, name: 'Other category' },
        scope: 'movie',
      })
    );
    await screen.findByText('Current category');
    resolve({
      count: 1,
      results: [{ relation_id: 0, name: 'Outdated category' }],
      content_source: 'provider',
    });
    await Promise.resolve();
    expect(screen.queryByText('Outdated category')).not.toBeInTheDocument();
    expect(screen.getByText('Current category')).toBeInTheDocument();
    expect(API.loadM3UGroupContent).toHaveBeenCalledOnce();
  });

  it('loads the provider once in Strict Mode without a second action or duplicate effect request', async () => {
    API.getM3UGroupContent.mockResolvedValue({
      count: 0,
      results: [],
      can_load_provider: true,
    });
    API.loadM3UGroupContent.mockResolvedValue({
      count: 1,
      results: [{ relation_id: 0, name: 'Automatic title' }],
      content_source: 'provider',
    });
    render(<StrictMode>{previewElement()}</StrictMode>);
    await screen.findByText('Automatic title');
    expect(API.getM3UGroupContent).toHaveBeenCalledOnce();
    expect(API.loadM3UGroupContent).toHaveBeenCalledOnce();
  });

  it('returns to page one before reloading a provider cache that expired during pagination', async () => {
    API.getM3UGroupContent
      .mockResolvedValueOnce({
        count: 250,
        results: [{ relation_id: 0, name: 'Old cached title' }],
        content_source: 'provider',
      })
      .mockResolvedValue({ count: 0, results: [], can_load_provider: true });
    API.loadM3UGroupContent.mockResolvedValue({
      count: 1,
      results: [{ relation_id: 0, name: 'Fresh cached title' }],
      content_source: 'provider',
    });
    renderPreview();
    await screen.findByText('Old cached title');
    fireEvent.click(screen.getByRole('button', { name: '5' }));
    await screen.findByText('Fresh cached title');
    expect(API.getM3UGroupContent).toHaveBeenLastCalledWith(
      7,
      'live',
      9,
      1,
      50,
      ''
    );
    expect(API.loadM3UGroupContent).toHaveBeenCalledOnce();
  });
});
