import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import { MantineProvider } from '@mantine/core';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import M3U from '../M3U.jsx';
import M3UProfiles from '../M3UProfiles.jsx';
import API from '../../../api.js';
import { updatePlaylist } from '../../../utils/forms/M3uUtils.js';

const state = vi.hoisted(() => ({
  playlists: [],
  profiles: {},
  fetchPlaylist: vi.fn(),
}));
vi.mock('../../../api.js', () => ({
  default: {
    queryStreams: vi.fn(),
    addM3UProfile: vi.fn(),
    updateM3UProfile: vi.fn(),
  },
}));
vi.mock('../../../store/userAgents', () => ({
  default: (select) => select({ userAgents: [] }),
}));
vi.mock('../../../store/serverGroups', () => ({
  default: (select) => select({ serverGroups: [] }),
}));
vi.mock('../../../store/playlists', () => ({
  default: (select) => select(state),
}));
vi.mock('../../../WebSocket', () => ({ useWebSocket: () => [false, null] }));
vi.mock('../../../utils/forms/M3uUtils.js', async () => ({
  ...(await vi.importActual('../../../utils/forms/M3uUtils.js')),
  updatePlaylist: vi.fn(),
}));
vi.mock('../../../utils/dateTimeUtils.js', async () => ({
  ...(await vi.importActual('../../../utils/dateTimeUtils.js')),
  useDateTimeFormat: () => ({
    fullDateFormat: 'YYYY-MM-DD',
    fullDateTimeFormat: 'YYYY-MM-DD HH:mm',
    timeFormat: 'HH:mm',
    dateYearFormat: 'YYYY-MM-DD',
  }),
  useTimeHelpers: () => ({ toUserTime: () => ({ format: () => '' }) }),
}));
vi.mock('../AccountInfoModal', () => ({ default: () => null }));
vi.mock('../M3UGroupFilter', () => ({ default: () => null }));
vi.mock('../../ServerGroupsManagerModal', () => ({ default: () => null }));

const account = {
  id: 7,
  name: 'Example account',
  account_type: 'XC',
  server_url: 'https://example.invalid',
  username: 'example',
  password: 'synthetic',
  is_active: true,
  enable_vod: true,
  max_streams: 1,
  refresh_interval: 24,
};

beforeEach(() => {
  vi.clearAllMocks();
  HTMLElement.prototype.scrollIntoView = vi.fn();
  state.profiles = { 7: [] };
  API.queryStreams.mockResolvedValue({ results: [] });
  API.addM3UProfile.mockResolvedValue({ id: 71 });
  API.updateM3UProfile.mockResolvedValue({ id: 71 });
  updatePlaylist.mockResolvedValue(account);
});

const openProfile = async (existing = false) => {
  if (existing)
    state.profiles = {
      7: [
        {
          id: 71,
          name: 'Existing connection',
          max_streams: 1,
          search_pattern:
            existing === 'advanced' ? '^https?://([^/]+)' : 'example/synthetic',
          replace_pattern: existing === 'advanced' ? '$1' : 'alternate/secret',
          custom_properties: {
            xcMode: existing === 'advanced' ? 'advanced' : 'simple',
          },
        },
      ],
    };
  const onClose = vi.fn();
  render(
    <MantineProvider>
      <M3U isOpen m3uAccount={account} onClose={onClose} />
    </MantineProvider>
  );
  fireEvent.click(screen.getByRole('tab', { name: 'Profiles' }));
  fireEvent.click(
    await screen.findByRole('button', {
      name: existing ? 'Edit Existing connection' : 'Add connection profile',
    })
  );
  const dialog = await screen.findByRole('dialog', { name: 'M3U Profile' });
  return { dialog, onClose };
};

describe('profile submissions inside the M3U editor', () => {
  it.each(['keyboard focus', 'hover'])(
    'shows the complete profile note in a tooltip on %s',
    async (trigger) => {
      const notes =
        'Complete synthetic profile note: the overview excerpt must not replace or change this saved content.';
      state.profiles = {
        7: [
          {
            id: 71,
            name: 'Additional connection',
            max_streams: 1,
            is_active: true,
            custom_properties: { notes },
          },
        ],
      };
      render(
        <MantineProvider>
          <M3UProfiles embedded playlist={account} />
        </MantineProvider>
      );
      const note = await screen.findByText(notes);
      const matches = note.matches.bind(note);
      // jsdom does not infer keyboard :focus-visible for a focusable paragraph.
      const focusVisible = vi
        .spyOn(note, 'matches')
        .mockImplementation((selector) =>
          selector === ':focus-visible' ? true : matches(selector)
        );
      try {
        if (trigger === 'keyboard focus') {
          const user = userEvent.setup();
          await user.tab();
          expect(note).toHaveFocus();
        } else {
          fireEvent.mouseEnter(note);
        }
        expect(await screen.findByRole('tooltip')).toHaveTextContent(notes);
        expect(API.updateM3UProfile).not.toHaveBeenCalled();
        expect(API.addM3UProfile).not.toHaveBeenCalled();
      } finally {
        focusVisible.mockRestore();
      }
    }
  );
  it('preserves a saved advanced replacement that cannot be represented as simple credentials', async () => {
    const { dialog } = await openProfile('advanced');
    expect(within(dialog).getByLabelText('Replace Pattern')).toHaveValue('$1');
    fireEvent.click(within(dialog).getByRole('radio', { name: 'Simple' }));
    fireEvent.click(
      within(dialog).getByRole('radio', { name: 'Advanced (Regex)' })
    );
    expect(within(dialog).getByLabelText('Search Pattern (Regex)')).toHaveValue(
      '^https?://([^/]+)'
    );
    expect(within(dialog).getByLabelText('Replace Pattern')).toHaveValue('$1');
    expect(API.updateM3UProfile).not.toHaveBeenCalled();
  });
  it.each(['empty', 'username only', 'password only'])(
    'starts Advanced empty without errors for incomplete simple credentials (%s)',
    async (credentials) => {
      const { dialog, onClose } = await openProfile();
      fireEvent.change(within(dialog).getByLabelText('Name'), {
        target: { value: 'New connection' },
      });
      if (credentials === 'username only')
        fireEvent.change(within(dialog).getByLabelText('New Username'), {
          target: { value: 'alternate' },
        });
      if (credentials === 'password only')
        fireEvent.change(within(dialog).getByLabelText('New Password'), {
          target: { value: 'synthetic' },
        });
      fireEvent.click(
        within(dialog).getByRole('radio', { name: 'Advanced (Regex)' })
      );
      expect(
        within(dialog).getByLabelText('Search Pattern (Regex)')
      ).toHaveValue('');
      expect(within(dialog).getByLabelText('Replace Pattern')).toHaveValue('');
      expect(
        within(dialog).queryByText(/pattern is required/)
      ).not.toBeInTheDocument();
      expect(API.addM3UProfile).not.toHaveBeenCalled();
      fireEvent.click(within(dialog).getByRole('button', { name: 'Submit' }));
      expect(
        await within(dialog).findByText('Search pattern is required')
      ).toBeInTheDocument();
      expect(
        within(dialog).getByText('Replace pattern is required')
      ).toBeInTheDocument();
      expect(API.addM3UProfile).not.toHaveBeenCalled();
      expect(updatePlaylist).not.toHaveBeenCalled();
      expect(onClose).not.toHaveBeenCalled();
    }
  );

  it.each(['simple', 'advanced', 'name'])(
    'opens a fresh profile without errors from a previous %s validation attempt',
    async (mode) => {
      const { dialog } = await openProfile();
      if (mode !== 'name')
        fireEvent.change(within(dialog).getByLabelText('Name'), {
          target: { value: 'Unfinished connection' },
        });
      if (mode === 'advanced')
        fireEvent.click(
          within(dialog).getByRole('radio', { name: 'Advanced (Regex)' })
        );
      fireEvent.click(within(dialog).getByRole('button', { name: 'Submit' }));
      expect(
        await within(dialog).findByText(
          mode === 'name'
            ? 'Name is required'
            : mode === 'advanced'
              ? 'Search pattern is required'
              : 'New username is required'
        )
      ).toBeInTheDocument();
      fireEvent.click(
        within(dialog).getByRole('button', {
          name: 'Close connection profile editor',
        })
      );
      if (mode !== 'name') {
        const confirmation = await screen.findByRole('dialog', {
          name: 'Discard unsaved changes?',
        });
        fireEvent.click(
          within(confirmation).getByRole('button', { name: 'Discard' })
        );
      }
      await waitFor(() =>
        expect(
          screen.queryByRole('dialog', { name: 'M3U Profile' })
        ).not.toBeInTheDocument()
      );
      fireEvent.click(
        screen.getByRole('button', { name: 'Add connection profile' })
      );
      const reopened = await screen.findByRole('dialog', {
        name: 'M3U Profile',
      });
      expect(within(reopened).getByLabelText('Name')).toHaveValue('');
      expect(within(reopened).getByLabelText('New Username')).toHaveValue('');
      expect(within(reopened).getByLabelText('New Password')).toHaveValue('');
      expect(
        within(reopened).queryByText(/is required/)
      ).not.toBeInTheDocument();
      expect(API.addM3UProfile).not.toHaveBeenCalled();
      expect(updatePlaylist).not.toHaveBeenCalled();
    }
  );

  it('transfers complete simple credentials and saves the stream limit only through the editor', async () => {
    const { dialog, onClose } = await openProfile();
    fireEvent.change(within(dialog).getByLabelText('Name'), {
      target: { value: 'Additional connection' },
    });
    fireEvent.change(within(dialog).getByLabelText('New Username'), {
      target: { value: 'alternate' },
    });
    fireEvent.change(within(dialog).getByLabelText('New Password'), {
      target: { value: 'synthetic-secret' },
    });
    fireEvent.change(within(dialog).getByLabelText('Max Streams'), {
      target: { value: '5' },
    });
    fireEvent.click(
      within(dialog).getByRole('radio', { name: 'Advanced (Regex)' })
    );
    expect(within(dialog).getByLabelText('Search Pattern (Regex)')).toHaveValue(
      'example/synthetic'
    );
    expect(within(dialog).getByLabelText('Replace Pattern')).toHaveValue(
      'alternate/synthetic-secret'
    );
    expect(API.addM3UProfile).not.toHaveBeenCalled();
    fireEvent.click(within(dialog).getByRole('button', { name: 'Submit' }));
    await waitFor(() =>
      expect(API.addM3UProfile).toHaveBeenCalledWith(
        7,
        expect.objectContaining({
          max_streams: 5,
          search_pattern: 'example/synthetic',
          replace_pattern: 'alternate/synthetic-secret',
          custom_properties: { notes: '', xcMode: 'advanced' },
        })
      )
    );
    expect(updatePlaylist).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();
  });

  it('keeps a name-only profile open and never submits the account behind it', async () => {
    const { dialog, onClose } = await openProfile();
    fireEvent.change(within(dialog).getByLabelText('Name'), {
      target: { value: 'New connection' },
    });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Submit' }));
    expect(
      await within(dialog).findByText('New username is required')
    ).toBeInTheDocument();
    expect(
      within(dialog).getByText('New password is required')
    ).toBeInTheDocument();
    expect(within(dialog).getByLabelText('Name')).toHaveValue('New connection');
    expect(API.addM3UProfile).not.toHaveBeenCalled();
    expect(updatePlaylist).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();
  });

  it('also isolates schema validation failures', async () => {
    const { dialog, onClose } = await openProfile();
    fireEvent.click(within(dialog).getByRole('button', { name: 'Submit' }));
    expect(
      await within(dialog).findByText('Name is required')
    ).toBeInTheDocument();
    expect(updatePlaylist).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();
  });

  it.each([false, true])(
    'saves only the profile and closes only its dialog (existing=%s)',
    async (existing) => {
      const { dialog, onClose } = await openProfile(existing);
      fireEvent.change(within(dialog).getByLabelText('Name'), {
        target: { value: 'New connection' },
      });
      fireEvent.change(within(dialog).getByLabelText('New Username'), {
        target: { value: 'alternate' },
      });
      fireEvent.change(within(dialog).getByLabelText('New Password'), {
        target: { value: 'secret' },
      });
      fireEvent.click(within(dialog).getByRole('button', { name: 'Submit' }));
      const action = existing ? API.updateM3UProfile : API.addM3UProfile;
      await waitFor(() => expect(action).toHaveBeenCalledOnce());
      expect(action).toHaveBeenCalledWith(
        7,
        expect.objectContaining({
          name: 'New connection',
          search_pattern: 'example/synthetic',
          replace_pattern: 'alternate/secret',
        })
      );
      await waitFor(() =>
        expect(
          screen.queryByRole('dialog', { name: 'M3U Profile' })
        ).not.toBeInTheDocument()
      );
      expect(
        screen.getByRole('dialog', { name: 'Edit M3U account' })
      ).toBeInTheDocument();
      expect(updatePlaylist).not.toHaveBeenCalled();
      expect(onClose).not.toHaveBeenCalled();
      await new Promise((resolve) => setTimeout(resolve, 320));
    }
  );

  it.each([false, true])(
    'keeps the draft on a failed save (existing=%s)',
    async (existing) => {
      API.addM3UProfile.mockRejectedValue(new Error('Save failed'));
      API.updateM3UProfile.mockRejectedValue(new Error('Save failed'));
      const { dialog, onClose } = await openProfile(existing);
      fireEvent.change(within(dialog).getByLabelText('Name'), {
        target: { value: 'Keep this draft' },
      });
      fireEvent.change(within(dialog).getByLabelText('New Username'), {
        target: { value: 'alternate' },
      });
      fireEvent.change(within(dialog).getByLabelText('New Password'), {
        target: { value: 'secret' },
      });
      fireEvent.click(within(dialog).getByRole('button', { name: 'Submit' }));
      await waitFor(() =>
        expect(
          existing ? API.updateM3UProfile : API.addM3UProfile
        ).toHaveBeenCalledOnce()
      );
      expect(within(dialog).getByLabelText('Name')).toHaveValue(
        'Keep this draft'
      );
      expect(
        within(dialog).getByRole('button', { name: 'Submit' })
      ).toBeEnabled();
      expect(onClose).not.toHaveBeenCalled();
      expect(updatePlaylist).not.toHaveBeenCalled();
    }
  );
});
