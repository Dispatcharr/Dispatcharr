import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import { MantineProvider } from '@mantine/core';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import api from '../../api';
import useLibraryStore from '../../store/useLibraryStore';
import LibraryView from '../LibraryView.jsx';

vi.mock('../../store/auth', () => ({
  default: (selector) => selector({ user: { user_level: 10 } }),
}));
vi.mock('../../store/settings', () => ({
  default: (selector) => selector({ environment: { env_mode: 'production' } }),
}));
vi.mock('../../store/useVideoStore', () => ({
  default: (selector) => selector({ showVideo: vi.fn() }),
}));
vi.mock('../../utils/notificationUtils.js', () => ({
  showNotification: vi.fn(),
}));
vi.mock('../../api', () => ({
  default: {
    getVODLibrary: vi.fn(),
    getVODLibraryOptions: vi.fn(),
    getVODLibraryState: vi.fn(),
    getVODLibraryDetails: vi.fn(),
    getVODLibrarySettings: vi.fn(),
    getMovieProviderInfo: vi.fn(),
    vodLibraryAction: vi.fn(),
  },
}));

const item = {
  key: 'movie:1',
  content_id: 1,
  content_type: 'movie',
  name: 'Film',
  provider_name: 'Film (2020)',
  year: 2020,
  source_count: 1,
  metadata_summary: {},
};
beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  useLibraryStore.setState({
    filters: {
      type: 'all',
      view: 'titles',
      search: '',
      account: '3',
      category: '',
    },
    page: 1,
    pageSize: 24,
    rows: [],
    count: 0,
    loading: false,
    error: null,
    optionsError: null,
    job: { status: 'idle', progress: {} },
  });
  api.getVODLibrary.mockResolvedValue({ results: [item], count: 1 });
  api.getVODLibraryOptions.mockResolvedValue({ accounts: [], categories: [] });
  api.getVODLibraryState.mockResolvedValue({ status: 'idle', progress: {} });
  api.getVODLibrarySettings.mockResolvedValue({
    title_rules: [],
    year_rules: [],
    match_missing: false,
  });
  api.vodLibraryAction.mockResolvedValue({
    count: 1,
    results: [
      {
        content_type: 'movie',
        id: 1,
        before: item.provider_name,
        after: 'Film',
        year: 2020,
        locked: false,
      },
    ],
  });
  api.getVODLibraryDetails.mockResolvedValue({
    canonical: item,
    sources: [],
    selected_source_id: null,
  });
});
describe('shared Library preview stack', () => {
  it('keeps the cleanup preview visible and dimmed behind a nested title preview', async () => {
    render(
      <MantineProvider env="test">
        <LibraryView view="titles" displayMode="list" />
      </MantineProvider>
    );
    fireEvent.click(
      await screen.findByRole('checkbox', { name: 'Select Film' })
    );
    fireEvent.click(screen.getByRole('button', { name: 'Edit (1)' }));
    const cleanup = await screen.findByRole('dialog', {
      name: 'Edit selected titles (1)',
    });
    fireEvent.click(
      await within(cleanup).findByRole('button', {
        name: 'Preview Film',
        exact: true,
      })
    );
    expect(
      await screen.findByRole('dialog', { name: 'Movie preview' })
    ).toBeInTheDocument();
    expect(cleanup).toBeInTheDocument();
    expect(cleanup.closest('[inert]')).not.toBeNull();
    await waitFor(() => expect(api.getVODLibraryDetails).toHaveBeenCalled());
    expect(
      Object.fromEntries(api.getVODLibraryDetails.mock.calls[0][0])
    ).toMatchObject({ id: '1', preferred_account: '3' });
    fireEvent.click(
      screen.getByRole('button', { name: 'Close Movie preview' })
    );
    await waitFor(() =>
      expect(
        screen
          .getByRole('dialog', { name: 'Edit selected titles (1)' })
          .closest('[inert]')
      ).toBeNull()
    );
    expect(api.vodLibraryAction).toHaveBeenCalledExactlyOnceWith(
      'cleanup-preview',
      {
        items: [{ content_type: 'movie', id: 1 }],
        page: 1,
        page_size: 25,
        title_rules: [],
        year_rules: [],
      }
    );
    expect(api.getMovieProviderInfo).not.toHaveBeenCalled();
  });
});
