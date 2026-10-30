import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import M3U from '../M3U.jsx';
import EPG from '../EPG.jsx';
import API from '../../../api.js';
import { addPlaylist, updatePlaylist } from '../../../utils/forms/M3uUtils.js';
import { addEPG, updateEPG } from '../../../utils/forms/DummyEpgUtils.js';

const mocks = vi.hoisted(() => ({ playlists: [], epgs: {} }));
vi.mock('../../../api.js', () => ({
  default: { updateEpgSourceSettings: vi.fn(), getSDLineups: vi.fn() },
}));
vi.mock('../../../store/userAgents', () => ({
  default: (selector) => selector({ userAgents: [] }),
}));
vi.mock('../../../store/serverGroups', () => ({
  default: (selector) => selector({ serverGroups: [] }),
}));
vi.mock('../../../store/playlists', () => ({
  default: (selector) => selector(mocks),
}));
vi.mock('../../../store/epgs', () => ({
  default: Object.assign((selector) => selector(mocks), {
    getState: () => mocks,
  }),
}));
vi.mock('../../../utils/forms/M3uUtils.js', async () => ({
  ...(await vi.importActual('../../../utils/forms/M3uUtils.js')),
  addPlaylist: vi.fn(),
  updatePlaylist: vi.fn(),
}));
vi.mock('../../../utils/forms/DummyEpgUtils.js', () => ({
  addEPG: vi.fn(),
  updateEPG: vi.fn(),
}));
vi.mock('../../../utils/notificationUtils.js', () => ({
  showNotification: vi.fn(),
  hideNotification: vi.fn(),
}));
vi.mock('../../../utils/dateTimeUtils.js', async () => ({
  ...(await vi.importActual('../../../utils/dateTimeUtils.js')),
  useDateTimeFormat: () => ({
    timeFormat: 'HH:mm',
    dateYearFormat: 'DD.MM.YYYY',
    fullDateTimeFormat: 'DD.MM.YYYY HH:mm',
  }),
  useTimeHelpers: () => ({ toUserTime: () => ({ format: () => '' }) }),
}));
vi.mock('../M3UProfiles', () => ({ default: () => null }));
vi.mock('../M3UGroupFilter', () => ({ default: () => null }));
vi.mock('../../ServerGroupsManagerModal', () => ({ default: () => null }));
vi.mock('../ScheduleInput', () => ({
  default: ({ intervalLabel, intervalValue, onIntervalChange }) => (
    <input
      aria-label={intervalLabel}
      value={intervalValue ?? 0}
      onChange={(event) => onIntervalChange(Number(event.target.value))}
    />
  ),
}));

const account = {
  id: 7,
  name: 'Example account',
  account_type: 'XC',
  server_url: 'https://example.invalid',
  username: 'example',
  is_active: true,
  enable_vod: true,
  refresh_interval: 24,
  max_streams: 1,
};
const guide = {
  id: 9,
  name: 'Example guide',
  source_type: 'xmltv',
  url: 'https://example.invalid/guide.xml',
  is_active: true,
  refresh_interval: 24,
  priority: 0,
};
const show = (element) => render(<MantineProvider>{element}</MantineProvider>);

beforeEach(() => {
  vi.clearAllMocks();
  HTMLElement.prototype.scrollIntoView = vi.fn();
  mocks.playlists = [];
  mocks.epgs = {};
  addPlaylist.mockResolvedValue({ ...account, id: 8 });
  updatePlaylist.mockResolvedValue(account);
  addEPG.mockResolvedValue(guide);
  updateEPG.mockResolvedValue(guide);
  API.updateEpgSourceSettings.mockResolvedValue({});
});

describe('M3U unsaved changes with real form controls', () => {
  it('closes a loaded account without a false dirty warning', () => {
    const onClose = vi.fn();
    show(<M3U isOpen m3uAccount={account} onClose={onClose} />);
    fireEvent.click(
      screen.getByRole('button', { name: 'Close M3U account editor' })
    );
    expect(onClose).toHaveBeenCalledOnce();
    expect(
      screen.queryByText('Discard unsaved changes?')
    ).not.toBeInTheDocument();
  });

  it.each(['X', 'Escape', 'outside'])(
    'guards %s, keeps the draft and only discards after confirmation',
    async (method) => {
      const user = userEvent.setup();
      const onClose = vi.fn();
      show(<M3U isOpen m3uAccount={account} onClose={onClose} />);
      fireEvent.change(screen.getByLabelText('Name'), {
        target: { value: 'Changed account' },
      });
      if (method === 'X')
        await user.click(
          screen.getByRole('button', { name: 'Close M3U account editor' })
        );
      else if (method === 'Escape') await user.keyboard('{Escape}');
      else await user.click(document.querySelector('.mantine-Modal-overlay'));
      const confirmation = await screen.findByRole('dialog', {
        name: 'Discard unsaved changes?',
      });
      expect(onClose).not.toHaveBeenCalled();
      await user.click(
        within(confirmation).getByRole('button', { name: 'Keep editing' })
      );
      expect(screen.getByLabelText('Name')).toHaveValue('Changed account');
      await user.click(
        screen.getByRole('button', { name: 'Close M3U account editor' })
      );
      await user.click(
        await screen.findByRole('button', { name: 'Discard', exact: true })
      );
      expect(onClose).toHaveBeenCalledOnce();
      expect(updatePlaylist).not.toHaveBeenCalled();
    }
  );

  it('recognizes reverting a changed value to its saved value', () => {
    const onClose = vi.fn();
    show(<M3U isOpen m3uAccount={account} onClose={onClose} />);
    fireEvent.change(screen.getByLabelText('Name'), {
      target: { value: 'Draft' },
    });
    fireEvent.change(screen.getByLabelText('Name'), {
      target: { value: account.name },
    });
    fireEvent.click(
      screen.getByRole('button', { name: 'Close M3U account editor' })
    );
    expect(onClose).toHaveBeenCalledOnce();
  });

  it('guards VOD settings changed on a different tab', async () => {
    show(<M3U isOpen m3uAccount={account} onClose={vi.fn()} />);
    fireEvent.click(screen.getByRole('tab', { name: 'Settings' }));
    fireEvent.click(screen.getByRole('switch', { name: 'Enable VOD' }));
    fireEvent.click(
      screen.getByRole('button', { name: 'Close M3U account editor' })
    );
    expect(
      await screen.findByRole('dialog', { name: 'Discard unsaved changes?' })
    ).toBeInTheDocument();
  });

  it('guards switching between URL and file even though both use the STD account type', async () => {
    const user = userEvent.setup();
    show(
      <M3U
        isOpen
        m3uAccount={{ ...account, account_type: 'STD', enable_vod: false }}
        onClose={vi.fn()}
      />
    );
    fireEvent.click(screen.getByRole('textbox', { name: 'Account Type' }));
    await user.click(
      await screen.findByRole('option', { name: 'M3U File', exact: true })
    );
    await user.click(
      screen.getByRole('button', { name: 'Close M3U account editor' })
    );
    expect(
      await screen.findByRole('dialog', { name: 'Discard unsaved changes?' })
    ).toBeInTheDocument();
  });

  it('guards a newly selected replacement file', async () => {
    const user = userEvent.setup();
    const view = show(
      <M3U
        isOpen
        m3uAccount={{
          ...account,
          account_type: 'STD',
          server_url: null,
          file_path: '/data/uploads/saved.m3u',
        }}
        onClose={vi.fn()}
      />
    );
    await user.upload(
      view.container.ownerDocument.querySelector('input[type="file"]'),
      new File(['#EXTM3U'], 'replacement.m3u', { type: 'audio/x-mpegurl' })
    );
    await user.click(
      screen.getByRole('button', { name: 'Close M3U account editor' })
    );
    expect(
      await screen.findByRole('dialog', { name: 'Discard unsaved changes?' })
    ).toBeInTheDocument();
  });

  it('does not treat a saved profile expiration update as an unsaved account edit', () => {
    mocks.playlists = [account];
    const onClose = vi.fn();
    const view = show(<M3U isOpen m3uAccount={account} onClose={onClose} />);
    mocks.playlists = [{ ...account, exp_date: '2027-10-18T12:00:00Z' }];
    view.rerender(
      <MantineProvider>
        <M3U isOpen m3uAccount={account} onClose={onClose} />
      </MantineProvider>
    );
    fireEvent.click(
      screen.getByRole('button', { name: 'Close M3U account editor' })
    );
    expect(onClose).toHaveBeenCalledOnce();
  });

  it('saves normally without a discard warning', async () => {
    const onClose = vi.fn();
    show(<M3U isOpen m3uAccount={account} onClose={onClose} />);
    fireEvent.change(screen.getByLabelText('Name'), {
      target: { value: 'Saved account' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Save', exact: true }));
    await waitFor(() => expect(onClose).toHaveBeenCalledOnce());
    expect(updatePlaylist).toHaveBeenCalledOnce();
    expect(
      screen.queryByText('Discard unsaved changes?')
    ).not.toBeInTheDocument();
  });
});

describe('EPG unsaved changes with real form controls', () => {
  it.each([null, guide])(
    'closes an unchanged new or saved source (%s)',
    (epg) => {
      const onClose = vi.fn();
      show(<EPG isOpen epg={epg} onClose={onClose} />);
      fireEvent.click(
        screen.getByRole('button', { name: 'Close EPG source editor' })
      );
      expect(onClose).toHaveBeenCalledOnce();
    }
  );

  it.each(['X', 'Cancel', 'Escape', 'outside'])(
    'guards %s and preserves inputs when editing continues',
    async (method) => {
      const user = userEvent.setup();
      const onClose = vi.fn();
      show(<EPG isOpen epg={guide} onClose={onClose} />);
      fireEvent.change(screen.getByLabelText('Name'), {
        target: { value: 'Changed guide' },
      });
      if (method === 'X')
        await user.click(
          screen.getByRole('button', { name: 'Close EPG source editor' })
        );
      else if (method === 'Cancel')
        await user.click(
          screen.getByRole('button', { name: 'Cancel', exact: true })
        );
      else if (method === 'Escape') await user.keyboard('{Escape}');
      else await user.click(document.querySelector('.mantine-Modal-overlay'));
      const confirmation = await screen.findByRole('dialog', {
        name: 'Discard unsaved changes?',
      });
      expect(onClose).not.toHaveBeenCalled();
      await user.click(
        within(confirmation).getByRole('button', { name: 'Keep editing' })
      );
      expect(screen.getByLabelText('Name')).toHaveValue('Changed guide');
      await user.click(
        screen.getByRole('button', { name: 'Cancel', exact: true })
      );
      await user.click(
        await screen.findByRole('button', { name: 'Discard', exact: true })
      );
      expect(onClose).toHaveBeenCalledOnce();
      expect(updateEPG).not.toHaveBeenCalled();
    }
  );

  it('does not warn when an edited value is restored', () => {
    const onClose = vi.fn();
    show(<EPG isOpen epg={guide} onClose={onClose} />);
    fireEvent.change(screen.getByLabelText('Name'), {
      target: { value: 'Draft guide' },
    });
    fireEvent.change(screen.getByLabelText('Name'), {
      target: { value: guide.name },
    });
    fireEvent.click(
      screen.getByRole('button', { name: 'Cancel', exact: true })
    );
    expect(onClose).toHaveBeenCalledOnce();
  });

  it('keeps failed updates retryable and guards their unsaved draft', async () => {
    updateEPG.mockResolvedValue(undefined);
    const onClose = vi.fn();
    show(<EPG isOpen epg={guide} onClose={onClose} />);
    fireEvent.change(screen.getByLabelText('Name'), {
      target: { value: 'Failed update draft' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Update EPG Source' }));
    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: 'Cancel', exact: true })
      ).toBeEnabled()
    );
    expect(onClose).not.toHaveBeenCalled();
    fireEvent.click(
      screen.getByRole('button', { name: 'Cancel', exact: true })
    );
    expect(
      await screen.findByRole('dialog', { name: 'Discard unsaved changes?' })
    ).toBeInTheDocument();
  });

  it('resets the dirty baseline after creating a source without deleting that source on close', async () => {
    const onClose = vi.fn();
    show(<EPG isOpen onClose={onClose} />);
    fireEvent.change(screen.getByLabelText('Name'), {
      target: { value: guide.name },
    });
    fireEvent.change(screen.getByLabelText('URL'), {
      target: { value: guide.url },
    });
    fireEvent.click(
      screen.getByRole('button', { name: 'Create', exact: true })
    );
    await screen.findByRole('button', { name: 'Update EPG Source' });
    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: 'Cancel', exact: true })
      ).toBeEnabled()
    );
    fireEvent.click(
      screen.getByRole('button', { name: 'Cancel', exact: true })
    );
    expect(onClose).toHaveBeenCalledOnce();
    expect(
      screen.queryByText('Discard unsaved changes?')
    ).not.toBeInTheDocument();
  });

  it('closes after a successful update without a second warning', async () => {
    const onClose = vi.fn();
    show(<EPG isOpen epg={guide} onClose={onClose} />);
    fireEvent.change(screen.getByLabelText('Name'), {
      target: { value: 'Saved guide' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Update EPG Source' }));
    await waitFor(() => expect(onClose).toHaveBeenCalledOnce());
    expect(
      screen.queryByText('Discard unsaved changes?')
    ).not.toBeInTheDocument();
  });

  it('does not close or allow another save while an update is in flight', async () => {
    let finish;
    updateEPG.mockReturnValue(
      new Promise((resolve) => {
        finish = resolve;
      })
    );
    const onClose = vi.fn();
    show(<EPG isOpen epg={guide} onClose={onClose} />);
    fireEvent.click(screen.getByRole('button', { name: 'Update EPG Source' }));
    expect(
      screen.getByRole('button', { name: 'Cancel', exact: true })
    ).toBeDisabled();
    fireEvent.click(
      screen.getByRole('button', { name: 'Close EPG source editor' })
    );
    expect(onClose).not.toHaveBeenCalled();
    expect(updateEPG).toHaveBeenCalledOnce();
    finish(guide);
    await waitFor(() => expect(onClose).toHaveBeenCalledOnce());
  });

  it('does not claim that directly saved logo options are unsaved', async () => {
    const onClose = vi.fn();
    show(<EPG isOpen epg={guide} onClose={onClose} />);
    fireEvent.click(
      screen.getByRole('switch', { name: /Auto-Apply EPG Logos/ })
    );
    await waitFor(() =>
      expect(API.updateEpgSourceSettings).toHaveBeenCalledOnce()
    );
    fireEvent.click(
      screen.getByRole('button', { name: 'Cancel', exact: true })
    );
    expect(onClose).toHaveBeenCalledOnce();
    expect(
      screen.queryByText('Discard unsaved changes?')
    ).not.toBeInTheDocument();
  });
});
