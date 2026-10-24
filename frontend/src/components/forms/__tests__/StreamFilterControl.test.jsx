import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react';
import { MantineProvider } from '@mantine/core';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import API from '../../../api.js';
import StreamFilterControl from '../StreamFilterControl.jsx';

vi.mock('../../../api.js', () => ({
  default: {
    getM3UStreamFilterAvailability: vi.fn(),
    refreshLivePlaylist: vi.fn(),
    loadM3UGroupContent: vi.fn(),
  },
}));
vi.mock('../M3UFilters.jsx', () => ({
  default: ({ isOpen, onRulesChanged, previewGroupIds }) =>
    isOpen ? (
      <div
        role="region"
        aria-label="Stream filter editor"
        data-preview-groups={previewGroupIds?.join(',')}
      >
        <button onClick={() => onRulesChanged([{ enabled: false }])}>
          Disable last filter
        </button>
      </div>
    ) : null,
}));
vi.mock('../../StackedModal.jsx', () => ({
  default: ({ opened, title, children, onClose }) =>
    opened ? (
      <div role="dialog" aria-label={title}>
        <button onClick={onClose}>Close preparation</button>
        {children}
      </div>
    ) : null,
}));

const ready = {
  ready: true,
  selected_count: 1,
  refresh_in_progress: false,
  refresh_failed: false,
  last_completed_refresh: 'new',
};
const renderControl = (props = {}) => {
  const onSaveSelection = vi.fn().mockResolvedValue();
  render(
    <MantineProvider env="test">
      <StreamFilterControl
        playlist={{ id: 7, filters: [{ enabled: true }] }}
        available
        onSaveSelection={onSaveSelection}
        {...props}
      />
    </MantineProvider>
  );
  return onSaveSelection;
};
beforeEach(() => {
  vi.clearAllMocks();
  API.getM3UStreamFilterAvailability.mockResolvedValue(ready);
  API.refreshLivePlaylist.mockResolvedValue({});
});

describe('Stream filter entry workflow', () => {
  it('uses Streams in standard playlist refresh confirmation without starting it', () => {
    const save = renderControl({
      playlist: { id: 7, account_type: 'STD' },
      selectionChanged: true,
    });
    fireEvent.click(screen.getByRole('button', { name: 'Stream filters' }));
    expect(screen.getByText(/selected Streams categories/)).toHaveTextContent(
      'run a stream refresh'
    );
    expect(screen.queryByText(/Live TV|Live refresh/)).not.toBeInTheDocument();
    expect(save).not.toHaveBeenCalled();
    expect(API.refreshLivePlaylist).not.toHaveBeenCalled();
  });
  it('opens a current pre-filter catalog directly, even with zero imported streams', async () => {
    const save = renderControl();
    fireEvent.click(screen.getByRole('button', { name: 'Stream filters (1)' }));
    await screen.findByRole('region', { name: 'Stream filter editor' });
    expect(save).not.toHaveBeenCalled();
    expect(API.refreshLivePlaylist).not.toHaveBeenCalled();
    fireEvent.click(
      screen.getByRole('button', { name: 'Disable last filter' })
    );
    expect(
      screen.getByRole('button', { name: 'Stream filters' })
    ).toHaveAttribute('data-variant', 'default');
  });
  it('does not save or refresh a changed draft until explicitly confirmed', async () => {
    const save = renderControl({ selectionChanged: true });
    fireEvent.click(screen.getByRole('button', { name: 'Stream filters (1)' }));
    expect(
      screen.getByRole('button', { name: 'Save selection & refresh' })
    ).toBeInTheDocument();
    expect(save).not.toHaveBeenCalled();
    expect(API.getM3UStreamFilterAvailability).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Back to selection' }));
    expect(API.refreshLivePlaylist).not.toHaveBeenCalled();
    expect(screen.queryByRole('region')).not.toBeInTheDocument();
  });
  it('saves first, refreshes only Live, and waits for the newly completed catalog', async () => {
    API.getM3UStreamFilterAvailability
      .mockResolvedValueOnce({
        ...ready,
        ready: false,
        last_completed_refresh: 'old',
      })
      .mockResolvedValueOnce(ready);
    const save = renderControl({ selectionChanged: true });
    fireEvent.click(screen.getByRole('button', { name: 'Stream filters (1)' }));
    fireEvent.click(
      screen.getByRole('button', { name: 'Save selection & refresh' })
    );
    await screen.findByRole('region', { name: 'Stream filter editor' });
    expect(save).toHaveBeenCalledOnce();
    expect(API.refreshLivePlaylist).toHaveBeenCalledExactlyOnceWith(7);
    expect(save.mock.invocationCallOrder[0]).toBeLessThan(
      API.refreshLivePlaylist.mock.invocationCallOrder[0]
    );
  });
  it('asks before refreshing a saved selection whose catalog is missing', async () => {
    API.getM3UStreamFilterAvailability.mockResolvedValue({
      ...ready,
      ready: false,
    });
    renderControl();
    fireEvent.click(screen.getByRole('button', { name: 'Stream filters (1)' }));
    await screen.findByRole('button', { name: 'Save selection & refresh' });
    expect(API.refreshLivePlaylist).not.toHaveBeenCalled();
  });
  it('does not refresh after a save failure', async () => {
    renderControl({
      selectionChanged: true,
      onSaveSelection: vi.fn().mockRejectedValue(new Error('save failed')),
    });
    fireEvent.click(screen.getByRole('button', { name: 'Stream filters (1)' }));
    fireEvent.click(
      screen.getByRole('button', { name: 'Save selection & refresh' })
    );
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'could not be saved'
    );
    expect(API.refreshLivePlaylist).not.toHaveBeenCalled();
    expect(screen.queryByRole('region')).not.toBeInTheDocument();
  });
  it('does not open late after preparation was canceled', async () => {
    let complete;
    API.getM3UStreamFilterAvailability.mockReturnValue(
      new Promise((resolve) => {
        complete = resolve;
      })
    );
    renderControl();
    fireEvent.click(screen.getByRole('button', { name: 'Stream filters (1)' }));
    fireEvent.click(screen.getByRole('button', { name: 'Back to selection' }));
    await act(async () => complete(ready));
    expect(screen.queryByRole('region')).not.toBeInTheDocument();
  });
  it('waits for an existing refresh instead of starting another one', async () => {
    API.getM3UStreamFilterAvailability
      .mockResolvedValueOnce({
        ...ready,
        ready: false,
        refresh_in_progress: true,
      })
      .mockResolvedValueOnce(ready);
    renderControl();
    fireEvent.click(screen.getByRole('button', { name: 'Stream filters (1)' }));
    await screen.findByRole('region', { name: 'Stream filter editor' });
    expect(API.refreshLivePlaylist).not.toHaveBeenCalled();
  });
  it('refreshes the explicitly saved selection after an older in-flight refresh finishes', async () => {
    API.getM3UStreamFilterAvailability
      .mockResolvedValueOnce({
        ...ready,
        ready: false,
        refresh_in_progress: true,
        last_completed_refresh: 'old',
      })
      .mockResolvedValueOnce({
        ...ready,
        ready: false,
        last_completed_refresh: 'old-completed',
      })
      .mockResolvedValueOnce(ready);
    renderControl({ selectionChanged: true });
    fireEvent.click(screen.getByRole('button', { name: 'Stream filters (1)' }));
    fireEvent.click(
      screen.getByRole('button', { name: 'Save selection & refresh' })
    );
    await waitFor(() => expect(API.refreshLivePlaylist).toHaveBeenCalledOnce());
    await screen.findByRole(
      'region',
      { name: 'Stream filter editor' },
      { timeout: 3000 }
    );
    expect(API.refreshLivePlaylist).toHaveBeenCalledExactlyOnceWith(7);
  });
  it('reports a failed refresh without opening stale data', async () => {
    API.getM3UStreamFilterAvailability
      .mockResolvedValueOnce({
        ...ready,
        ready: false,
        refresh_in_progress: true,
      })
      .mockResolvedValueOnce({ ...ready, ready: false, refresh_failed: true });
    renderControl();
    fireEvent.click(screen.getByRole('button', { name: 'Stream filters (1)' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'did not complete successfully'
    );
    expect(screen.queryByRole('region')).not.toBeInTheDocument();
  });
  it('keeps stream filters unavailable without Live categories', () => {
    renderControl({ available: false, unavailableHint: 'Finish setup first.' });
    expect(
      screen.getByRole('button', { name: 'Stream filters (1)' })
    ).toBeDisabled();
    expect(API.getM3UStreamFilterAvailability).not.toHaveBeenCalled();
  });

  it('uses a complete cached draft selection during setup without saving or refreshing', async () => {
    const save = renderControl({
      previewOnly: true,
      selectedGroupIds: [12, 9],
    });
    fireEvent.click(screen.getByRole('button', { name: 'Stream filters (1)' }));
    const editor = await screen.findByRole('region', {
      name: 'Stream filter editor',
    });
    expect(editor).toHaveAttribute('data-preview-groups', '9,12');
    expect(API.getM3UStreamFilterAvailability).toHaveBeenCalledExactlyOnceWith(
      7,
      [9, 12]
    );
    expect(save).not.toHaveBeenCalled();
    expect(API.refreshLivePlaylist).not.toHaveBeenCalled();
    expect(API.loadM3UGroupContent).not.toHaveBeenCalled();
  });

  it('asks before loading only missing setup previews, then checks completeness', async () => {
    API.getM3UStreamFilterAvailability
      .mockResolvedValueOnce({
        ...ready,
        ready: false,
        missing_group_ids: [12],
        can_load_provider: true,
      })
      .mockResolvedValueOnce(ready);
    const save = renderControl({
      previewOnly: true,
      selectedGroupIds: [9, 12],
    });
    fireEvent.click(screen.getByRole('button', { name: 'Stream filters (1)' }));
    await screen.findByRole('button', { name: 'Load category previews' });
    expect(API.loadM3UGroupContent).not.toHaveBeenCalled();
    fireEvent.click(
      screen.getByRole('button', { name: 'Load category previews' })
    );
    await screen.findByRole('region', { name: 'Stream filter editor' });
    expect(API.loadM3UGroupContent).toHaveBeenCalledExactlyOnceWith(
      7,
      'live',
      12
    );
    expect(API.getM3UStreamFilterAvailability).toHaveBeenLastCalledWith(
      7,
      [9, 12]
    );
    expect(save).not.toHaveBeenCalled();
    expect(API.refreshLivePlaylist).not.toHaveBeenCalled();
  });

  it('does not open a partial setup preview after loading fails', async () => {
    API.getM3UStreamFilterAvailability.mockResolvedValue({
      ...ready,
      ready: false,
      missing_group_ids: [9, 12],
      can_load_provider: true,
    });
    API.loadM3UGroupContent.mockRejectedValueOnce(
      new Error('provider failure')
    );
    const save = renderControl({
      previewOnly: true,
      selectedGroupIds: [9, 12],
    });
    fireEvent.click(screen.getByRole('button', { name: 'Stream filters (1)' }));
    fireEvent.click(
      await screen.findByRole('button', { name: 'Load category previews' })
    );
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Nothing has been imported'
    );
    expect(screen.queryByRole('region')).not.toBeInTheDocument();
    expect(API.loadM3UGroupContent).toHaveBeenCalledTimes(1);
    expect(save).not.toHaveBeenCalled();
    expect(API.refreshLivePlaylist).not.toHaveBeenCalled();
  });

  it('never fetches a Standard playlist when its discovery preview is unavailable', async () => {
    API.getM3UStreamFilterAvailability.mockResolvedValue({
      ...ready,
      ready: false,
      can_load_provider: false,
    });
    const save = renderControl({
      playlist: { id: 7, account_type: 'STD' },
      previewOnly: true,
      selectedGroupIds: [9],
    });
    fireEvent.click(screen.getByRole('button', { name: 'Stream filters' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Reload categories'
    );
    expect(
      screen.queryByRole('button', { name: 'Load category previews' })
    ).not.toBeInTheDocument();
    expect(save).not.toHaveBeenCalled();
    expect(API.loadM3UGroupContent).not.toHaveBeenCalled();
    expect(API.refreshLivePlaylist).not.toHaveBeenCalled();
  });
});
