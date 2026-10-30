import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import { MantineProvider } from '@mantine/core';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import M3USetup from '../M3USetup.jsx';
import { MemoryRouter } from 'react-router-dom';
import API from '../../../api.js';
import { showNotification } from '../../../utils/notificationUtils.js';
import StackedModal from '../../StackedModal.jsx';
import stackClasses from '../../StackedModal.module.css';

const mocks = vi.hoisted(() => ({
  fetchChannelGroups: vi.fn(),
  fetchEPGs: vi.fn(),
  fetchCategories: vi.fn(),
  updatePlaylist: vi.fn(),
  channelGroups: { 1: { id: 1, name: 'Example category' } },
  categories: {},
}));
vi.mock('../../../api.js', () => ({
  default: {
    getPlaylist: vi.fn(),
    advanceM3USetup: vi.fn(),
    getM3UEPG: vi.fn(),
    createM3UEPG: vi.fn(),
  },
}));
vi.mock('../../../store/channels', () => ({
  default: Object.assign((selector) => selector(mocks), {
    getState: () => mocks,
  }),
}));
vi.mock('../../../store/epgs', () => ({
  default: Object.assign((selector) => selector(mocks), {
    getState: () => mocks,
  }),
}));
vi.mock('../../../store/useVODStore', () => ({
  default: Object.assign((selector) => selector(mocks), {
    getState: () => mocks,
  }),
}));
vi.mock('../../../store/playlists', () => ({
  default: { getState: () => mocks },
}));
vi.mock('../../../utils/notificationUtils.js', () => ({
  showNotification: vi.fn(),
  hideNotification: vi.fn(),
}));
vi.mock('../M3UGroupFilter.jsx', () => ({
  default: ({ onSetupSave, onClose }) => (
    <StackedModal opened title="Category setup" onClose={onClose}>
      <button onClick={onSetupSave}>Save categories</button>
      <button onClick={onClose}>Close categories</button>
    </StackedModal>
  ),
}));
vi.mock('../M3U.jsx', () => ({
  default: ({ m3uAccount, onSetupNext, onSetupBack, onClose }) => (
    <div role="dialog" aria-label="Guided account editor">
      <span>Step: {m3uAccount.setup_step}</span>
      {m3uAccount.setup_step === 'content' && (
        <button onClick={onSetupBack}>Back</button>
      )}
      <button onClick={() => onSetupNext(m3uAccount)}>Next</button>
      <button onClick={onClose}>Close guided editor</button>
    </div>
  ),
}));

const account = {
  id: 7,
  name: 'Example setup',
  account_type: 'XC',
  setup_step: 'epg',
  status: 'pending_setup',
  channel_groups: [],
};
const renderSetup = (overrides = {}) => {
  const props = {
    account,
    onClose: vi.fn(),
    ...overrides,
  };
  return {
    ...render(
      <MemoryRouter>
        <MantineProvider>
          <M3USetup {...props} />
        </MantineProvider>
      </MemoryRouter>
    ),
    ...props,
  };
};

describe('persisted M3U setup', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    API.advanceM3USetup.mockReset();
    API.getPlaylist.mockReset();
    mocks.fetchEPGs.mockResolvedValue(undefined);
    mocks.fetchChannelGroups.mockResolvedValue(undefined);
    mocks.fetchCategories.mockResolvedValue(undefined);
    mocks.categories = {};
    API.getPlaylist.mockResolvedValue(account);
    API.getM3UEPG.mockResolvedValue({ source: null, can_create: true });
    API.createM3UEPG.mockReset();
  });

  it.each([
    ['XC', 'categories', 'back_to_epg', 'epg'],
    ['XC', 'epg', 'back_to_content', 'content'],
    ['STD', 'categories', 'back_to_content', 'content'],
    ['XC', 'content', 'back_to_account', 'account'],
  ])(
    'moves %s %s back exactly one step',
    async (kind, stage, action, target) => {
      let current = { ...account, account_type: kind, setup_step: stage };
      API.getPlaylist.mockImplementation(async () => current);
      API.advanceM3USetup.mockImplementation(async () => {
        current = { ...current, setup_step: target };
        return current;
      });
      renderSetup({ account: current });
      fireEvent.click(await screen.findByRole('button', { name: 'Back' }));
      await waitFor(() =>
        expect(API.advanceM3USetup).toHaveBeenCalledExactlyOnceWith(7, action)
      );
      if (target !== 'epg') await screen.findByText(`Step: ${target}`);
      expect(showNotification).not.toHaveBeenCalled();
    }
  );

  it.each([
    ['XC', 'account', 'continue_content', 'content'],
    ['XC', 'content', 'continue_epg', 'epg'],
    ['XC', 'epg', 'continue_categories', 'categories'],
    ['STD', 'content', 'continue_categories', 'categories'],
  ])(
    'continues %s %s to its next step',
    async (kind, stage, action, target) => {
      let current = { ...account, account_type: kind, setup_step: stage };
      API.getPlaylist.mockImplementation(async () => current);
      API.advanceM3USetup.mockImplementation(async () => {
        current = { ...current, setup_step: target };
        return current;
      });
      renderSetup({ account: current });
      fireEvent.click(
        await screen.findByRole('button', {
          name: stage === 'epg' ? 'Skip EPG' : 'Next',
        })
      );
      await waitFor(() =>
        expect(API.advanceM3USetup).toHaveBeenCalledExactlyOnceWith(7, action)
      );
    }
  );

  it('groups the EPG decisions on the right and Back separately on the left', async () => {
    renderSetup();
    await screen.findByText('No matching EPG source configured.');
    const actions = within(
      screen.getByRole('contentinfo', { name: 'M3U setup actions' })
    );
    expect(
      actions.getAllByRole('button').map((button) => button.textContent)
    ).toEqual(['Back', 'Skip EPG', 'Create EPG']);
    expect(
      actions.getByRole('button', { name: 'Back' }).parentElement
    ).not.toBe(
      actions.getByRole('button', { name: 'Create EPG' }).parentElement
    );
  });

  it.each([false, true])(
    'continues after an explicit EPG decision (create EPG: %s)',
    async (createEPG) => {
      const { onClose } = renderSetup();
      await screen.findByText('No matching EPG source configured.');
      expect(
        screen.queryByRole('button', { name: 'Next' })
      ).not.toBeInTheDocument();
      expect(screen.queryByRole('radio')).not.toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Skip EPG' })).toBeEnabled();
      expect(
        within(
          screen.getByRole('contentinfo', { name: 'M3U setup actions' })
        ).getByRole('button', { name: 'Create EPG' })
      ).toBeInTheDocument();
      const categories = {
        ...account,
        setup_step: 'categories',
        channel_groups: [{ channel_group: 1 }],
        enable_vod: true,
      };
      API.advanceM3USetup.mockResolvedValue(categories);
      API.getPlaylist.mockResolvedValue(categories);
      if (createEPG) {
        API.createM3UEPG.mockResolvedValue({
          source: {
            id: 9,
            name: 'Example guide',
            is_active: true,
            status: 'idle',
          },
          can_create: false,
        });
        fireEvent.click(screen.getByRole('button', { name: 'Create EPG' }));
      } else {
        expect(API.advanceM3USetup).not.toHaveBeenCalled();
        fireEvent.click(screen.getByRole('button', { name: 'Skip EPG' }));
      }
      await screen.findByRole('button', { name: 'Select categories' });
      expect(API.createM3UEPG).toHaveBeenCalledTimes(createEPG ? 1 : 0);
      expect(API.advanceM3USetup).toHaveBeenCalledExactlyOnceWith(
        7,
        'continue_categories'
      );
      expect(mocks.fetchEPGs).toHaveBeenCalledTimes(createEPG ? 1 : 0);
      expect(mocks.fetchCategories).toHaveBeenCalled();
      expect(showNotification).not.toHaveBeenCalled();
      expect(onClose).not.toHaveBeenCalled();
    }
  );

  it('resumes category setup without repeating the EPG decision', async () => {
    const categories = {
      ...account,
      setup_step: 'categories',
      channel_groups: [{ channel_group: 1 }],
    };
    API.getPlaylist.mockResolvedValue(categories);
    renderSetup({ account: categories });
    await screen.findByRole('button', { name: 'Select categories' });
    expect(API.advanceM3USetup).not.toHaveBeenCalled();
    expect(
      screen.queryByText('Create matching EPG source?')
    ).not.toBeInTheDocument();
  });
  it('shows the existing EPG card without a route out of guided setup', async () => {
    API.getM3UEPG.mockResolvedValue({
      source: {
        id: 9,
        name: 'Existing setup guide',
        is_active: true,
        status: 'success',
      },
      can_create: false,
    });
    renderSetup();
    await screen.findByRole('article', {
      name: 'EPG source Existing setup guide',
    });
    expect(screen.queryByRole('link')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Next' })).toBeEnabled();
  });

  it('does not show an EPG step for standard accounts', async () => {
    const standard = {
      ...account,
      account_type: 'STD',
      setup_step: 'categories',
    };
    API.getPlaylist.mockResolvedValue(standard);
    renderSetup({ account: standard });
    expect(
      screen.queryByRole('button', { name: 'EPG' })
    ).not.toBeInTheDocument();
    expect(API.getM3UEPG).not.toHaveBeenCalled();
  });

  it('blocks navigation while an EPG source is being created', async () => {
    let finish;
    API.createM3UEPG.mockReturnValue(
      new Promise((resolve) => {
        finish = resolve;
      })
    );
    const categories = { ...account, setup_step: 'categories' };
    API.advanceM3USetup.mockResolvedValue(categories);
    API.getPlaylist
      .mockResolvedValueOnce(account)
      .mockResolvedValue(categories);
    const { onClose } = renderSetup();
    fireEvent.click(await screen.findByRole('button', { name: 'Create EPG' }));
    expect(screen.getByRole('button', { name: 'Skip EPG' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Back' })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'Close M3U setup' }));
    expect(onClose).not.toHaveBeenCalled();
    finish({
      source: { id: 9, name: 'New guide', is_active: true, status: 'idle' },
      can_create: false,
    });
    await waitFor(() =>
      expect(API.advanceM3USetup).toHaveBeenCalledExactlyOnceWith(
        7,
        'continue_categories'
      )
    );
  });

  it('shows a resumable error and retries discovery', async () => {
    const failed = { ...account, setup_step: 'categories', status: 'error' };
    API.getPlaylist.mockResolvedValue(failed);
    renderSetup({ account: failed });
    await screen.findByText(/Categories could not be loaded/);
    const categories = {
      ...failed,
      status: 'pending_setup',
      channel_groups: [{ channel_group: 1 }],
    };
    API.advanceM3USetup.mockResolvedValue(categories);
    API.getPlaylist.mockResolvedValue(categories);
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    await screen.findByRole('button', { name: 'Select categories' });
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument();
    expect(screen.getByText('Settings')).toBeInTheDocument();
    expect(screen.getByText('Content').closest('button')).toHaveAttribute(
      'aria-current',
      'step'
    );
    expect(API.advanceM3USetup).toHaveBeenCalledExactlyOnceWith(
      7,
      'retry_categories'
    );
  });

  it('retains the account after an EPG failure and allows continuing', async () => {
    renderSetup();
    await screen.findByText('No matching EPG source configured.');
    API.createM3UEPG.mockRejectedValueOnce(
      new Error('EPG name already exists')
    );
    fireEvent.click(screen.getByRole('button', { name: 'Create EPG' }));
    await waitFor(() =>
      expect(showNotification).toHaveBeenCalledWith(
        expect.objectContaining({ color: 'red', autoClose: false })
      )
    );
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Skip EPG' })).toBeEnabled()
    );
    API.advanceM3USetup.mockResolvedValue(account);
    fireEvent.click(screen.getByRole('button', { name: 'Skip EPG' }));
    await waitFor(() =>
      expect(API.advanceM3USetup).toHaveBeenLastCalledWith(
        7,
        'continue_categories'
      )
    );
  });

  it('keeps waiting after slow discovery and opens categories when it completes', async () => {
    vi.useFakeTimers();
    try {
      const loading = {
        ...account,
        setup_step: 'categories',
        status: 'fetching',
      };
      API.getPlaylist.mockResolvedValue(loading);
      renderSetup({ account: loading });
      await act(async () => {
        await vi.advanceTimersByTimeAsync(100000);
      });
      expect(screen.getByText(/taking longer than usual/)).toBeInTheDocument();
      expect(screen.queryByText(/could not be loaded/)).not.toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Retry' })).toBeEnabled();
      expect(API.advanceM3USetup).not.toHaveBeenCalled();
      API.getPlaylist.mockResolvedValue({
        ...loading,
        status: 'pending_setup',
        channel_groups: [{ channel_group: 1 }],
      });
      await act(async () => {
        await vi.advanceTimersByTimeAsync(2000);
      });
      expect(
        screen.getByRole('button', { name: 'Select categories' })
      ).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it('still shows an actual error after prolonged loading', async () => {
    vi.useFakeTimers();
    try {
      const loading = {
        ...account,
        setup_step: 'categories',
        status: 'parsing',
      };
      API.getPlaylist.mockResolvedValue(loading);
      renderSetup({ account: loading });
      await act(async () => {
        await vi.advanceTimersByTimeAsync(100000);
      });
      API.getPlaylist.mockResolvedValue({ ...loading, status: 'error' });
      await act(async () => {
        await vi.advanceTimersByTimeAsync(2000);
      });
      expect(
        screen.getByText(/Categories could not be loaded/)
      ).toBeInTheDocument();
      expect(
        screen.queryByText(/taking longer than usual/)
      ).not.toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it('refreshes persisted progress after an interrupted response', async () => {
    renderSetup();
    await screen.findByText('No matching EPG source configured.');
    API.advanceM3USetup.mockRejectedValueOnce(
      new Error('Connection interrupted')
    );
    API.getPlaylist.mockResolvedValue({
      ...account,
      setup_step: 'categories',
      channel_groups: [{ channel_group: 1 }],
    });
    fireEvent.click(screen.getByRole('button', { name: 'Skip EPG' }));
    await screen.findByRole('button', { name: 'Select categories' });
    expect(API.advanceM3USetup).toHaveBeenCalledTimes(1);
  });

  it('handles a failed category store load without getting stuck', async () => {
    const categories = {
      ...account,
      setup_step: 'categories',
      channel_groups: [{ channel_group: 1 }],
    };
    API.getPlaylist.mockResolvedValue(categories);
    mocks.fetchChannelGroups.mockRejectedValueOnce(new Error('Unavailable'));
    renderSetup({ account: categories });
    await screen.findByText(/Categories could not be loaded/);
    expect(screen.getByRole('button', { name: 'Retry' })).toBeEnabled();
  });

  it('starts the initial import once despite repeated clicks', async () => {
    const categories = {
      ...account,
      setup_step: 'categories',
      channel_groups: [{ channel_group: 1 }],
      setup_categories_reviewed: true,
    };
    API.getPlaylist.mockResolvedValue(categories);
    const { onClose } = renderSetup({ account: categories });
    await screen.findByRole('button', { name: 'Edit selection' });
    let complete;
    API.advanceM3USetup.mockReturnValue(
      new Promise((resolve) => {
        complete = resolve;
      })
    );
    fireEvent.click(screen.getByRole('button', { name: 'Finish & import' }));
    fireEvent.click(screen.getByRole('button', { name: 'Finish & import' }));
    expect(API.advanceM3USetup).toHaveBeenCalledExactlyOnceWith(7, 'complete');
    complete({ ...categories, setup_step: '' });
    await waitFor(() => expect(onClose).toHaveBeenCalledOnce());
    expect(showNotification).toHaveBeenCalledWith(
      expect.objectContaining({ title: 'Setup complete', color: 'green' })
    );
  });

  it('edits categories without a second stepper and saves back without importing', async () => {
    const categories = {
      ...account,
      setup_step: 'categories',
      channel_groups: [{ channel_group: 1 }],
    };
    API.getPlaylist.mockResolvedValue(categories);
    renderSetup({ account: categories });
    const actions = await screen.findByRole('region', {
      name: 'Category selection actions',
    });
    expect(
      within(actions).getByRole('button', { name: 'Select categories' })
    ).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: 'Finish & import' })
    ).toBeDisabled();
    const hint =
      'Select the categories you want to import before finishing setup.';
    expect(screen.queryByText(hint)).not.toBeInTheDocument();
    fireEvent.mouseEnter(
      screen.getByRole('button', { name: 'Finish & import' }).parentElement
    );
    expect(await screen.findByRole('tooltip')).toHaveTextContent(hint);
    fireEvent.mouseLeave(
      screen.getByRole('button', { name: 'Finish & import' }).parentElement
    );
    fireEvent.click(
      await screen.findByRole('button', { name: 'Select categories' })
    );
    expect(
      screen.getByRole('dialog', { name: 'Category setup' })
    ).toBeInTheDocument();
    expect(
      within(
        screen.getByRole('dialog', { name: 'Category setup' })
      ).queryByLabelText('M3U setup progress')
    ).not.toBeInTheDocument();
    API.advanceM3USetup.mockResolvedValue({
      ...categories,
      setup_categories_reviewed: true,
    });
    fireEvent.click(screen.getByRole('button', { name: 'Save categories' }));
    await screen.findByRole('button', { name: 'Edit selection' });
    expect(screen.queryByText(/Selection saved/)).not.toBeInTheDocument();
    expect(
      screen.queryByRole('dialog', { name: 'Category setup' })
    ).not.toBeInTheDocument();
    expect(API.advanceM3USetup).toHaveBeenCalledExactlyOnceWith(
      7,
      'confirm_categories'
    );
    expect(
      screen.getByRole('button', { name: 'Finish & import' })
    ).toBeEnabled();
  });

  it('returns to the setup step when category editing is closed', async () => {
    const categories = {
      ...account,
      setup_step: 'categories',
      channel_groups: [{ channel_group: 1 }],
    };
    API.getPlaylist.mockResolvedValue(categories);
    const { onClose } = renderSetup({ account: categories });
    const parent = screen.getByRole('dialog', { name: 'Set up Example setup' });
    fireEvent.click(
      await screen.findByRole('button', { name: 'Select categories' })
    );
    await screen.findByRole('dialog', { name: 'Category setup' });
    expect(parent.closest(`.${stackClasses.background}`)).not.toBeNull();
    expect(parent.closest('.mantine-Modal-root')).toHaveAttribute('inert');
    fireEvent.click(screen.getByRole('button', { name: 'Close categories' }));
    await screen.findByRole('button', { name: 'Select categories' });
    expect(parent.closest(`.${stackClasses.background}`)).toBeNull();
    expect(parent.closest('.mantine-Modal-root')).not.toHaveAttribute('inert');
    expect(
      screen.queryByRole('button', { name: 'Finish & import' })
    ).toBeDisabled();
    expect(onClose).not.toHaveBeenCalled();
  });

  it('closes when another request has already completed setup', async () => {
    API.getPlaylist.mockResolvedValue({ ...account, setup_step: '' });
    const { onClose } = renderSetup();
    await waitFor(() => expect(onClose).toHaveBeenCalledOnce());
    expect(API.advanceM3USetup).not.toHaveBeenCalled();
  });

  it.each(['epg', 'categories'])(
    'offers Continue later without changing the saved %s setup',
    async (setup_step) => {
      const current = { ...account, setup_step };
      API.getPlaylist.mockResolvedValue(current);
      const { onClose } = renderSetup({ account: current });
      await screen.findByRole('button', { name: 'Close M3U setup' });
      fireEvent.click(screen.getByRole('button', { name: 'Close M3U setup' }));
      const dialog = await screen.findByRole('dialog', {
        name: 'Continue setup later?',
      });
      expect(dialog).toHaveTextContent(
        'Your account and saved setup progress will be kept.'
      );
      expect(onClose).not.toHaveBeenCalled();
      fireEvent.click(
        within(dialog).getByRole('button', { name: 'Keep editing' })
      );
      expect(onClose).not.toHaveBeenCalled();
      fireEvent.click(screen.getByRole('button', { name: 'Close M3U setup' }));
      fireEvent.click(screen.getByRole('button', { name: 'Continue later' }));
      expect(onClose).toHaveBeenCalledOnce();
      expect(API.advanceM3USetup).not.toHaveBeenCalled();
      expect(API.createM3UEPG).not.toHaveBeenCalled();
    }
  );

  it('resumes a saved all-disabled selection with Finish & import', async () => {
    const categories = {
      ...account,
      setup_step: 'categories',
      setup_categories_reviewed: true,
      channel_groups: [{ channel_group: 1, enabled: false }],
    };
    API.getPlaylist.mockResolvedValue(categories);
    renderSetup({ account: categories });
    expect(
      await screen.findByText('0 of 1 categories selected')
    ).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: 'Finish & import' })
    ).toBeEnabled();
    expect(
      screen.getByRole('button', { name: 'Edit selection' })
    ).toBeEnabled();
    expect(screen.queryByText(/Selection saved/)).not.toBeInTheDocument();
    expect(API.advanceM3USetup).not.toHaveBeenCalled();
  });

  it('summarizes only this account and enabled content types', async () => {
    const categories = {
      ...account,
      setup_step: 'categories',
      enable_vod: true,
      channel_groups: [{ channel_group: 1, enabled: true }],
      category_selection_counts: {
        live: { selected: 1, total: 1 },
        movie: { selected: 1, total: 2 },
        series: { selected: 0, total: 0 },
      },
    };
    mocks.categories = {
      1: {
        category_type: 'movie',
        m3u_accounts: [{ m3u_account: 7, enabled: true }],
      },
      2: {
        category_type: 'movie',
        m3u_accounts: [{ m3u_account: 7, enabled: false }],
      },
      3: {
        category_type: 'series',
        m3u_accounts: [{ m3u_account: 99, enabled: true }],
      },
    };
    API.getPlaylist.mockResolvedValue(categories);
    renderSetup({ account: categories });
    await screen.findByRole('button', { name: 'Select categories' });
    expect(screen.getByText('1 of 1 categories selected')).toBeInTheDocument();
    expect(screen.getByText('1 of 2 categories selected')).toBeInTheDocument();
    expect(screen.getByText('0 of 0 categories selected')).toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: 'Finish & import' })
    ).toBeDisabled();
  });
});
