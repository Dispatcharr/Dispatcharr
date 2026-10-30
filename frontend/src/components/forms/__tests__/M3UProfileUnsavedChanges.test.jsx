import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import { MantineProvider, Modal } from '@mantine/core';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import M3UProfile from '../M3UProfile.jsx';
import API from '../../../api.js';

vi.mock('../../../api.js', () => ({
  default: {
    queryStreams: vi.fn(),
    addM3UProfile: vi.fn(),
    updateM3UProfile: vi.fn(),
  },
}));
vi.mock('../../../WebSocket', () => ({ useWebSocket: () => [false, null] }));
vi.mock('../../../utils/dateTimeUtils.js', () => ({
  useDateTimeFormat: () => ({
    timeFormat: 'HH:mm',
    dateYearFormat: 'YYYY-MM-DD',
  }),
}));
vi.mock('@mantine/dates', () => ({
  DateTimePicker: ({ label, value, onChange }) => (
    <label>
      {label}
      <input
        value={value instanceof Date ? value.toISOString() : value || ''}
        onChange={(event) => onChange(event.target.value || null)}
      />
    </label>
  ),
}));

const account = {
  id: 7,
  account_type: 'XC',
  username: 'example',
  password: 'synthetic',
};
const savedProfile = {
  id: 17,
  name: 'Saved profile',
  max_streams: 2,
  search_pattern: 'example/synthetic',
  replace_pattern: 'alternate/secret',
  exp_date: '2030-01-01T12:00:00Z',
  custom_properties: { xcMode: 'simple', notes: 'Saved note' },
};

beforeEach(() => {
  vi.clearAllMocks();
  API.queryStreams.mockResolvedValue({ results: [] });
  API.addM3UProfile.mockResolvedValue({ id: 17 });
  API.updateM3UProfile.mockResolvedValue({ id: 17 });
});

const openEditor = (profile = null, accountType = 'XC') => {
  const onClose = vi.fn();
  const rendered = render(
    <MantineProvider env="test">
      <Modal.Stack>
        <M3UProfile
          m3u={{ ...account, account_type: accountType }}
          profile={profile}
          isOpen
          onClose={onClose}
        />
      </Modal.Stack>
    </MantineProvider>
  );
  const dialog = screen.getByRole('dialog', {
    name: profile?.is_default ? 'Edit Default Profile' : 'M3U Profile',
  });
  return { ...rendered, dialog, onClose };
};

const closeEditor = (dialog) =>
  fireEvent.click(
    within(dialog).getByRole('button', {
      name: 'Close connection profile editor',
    })
  );

describe('connection profile unsaved changes', () => {
  it.each([
    ['new XC', null, 'XC'],
    ['saved XC', savedProfile, 'XC'],
    [
      'advanced XC',
      { ...savedProfile, custom_properties: { xcMode: 'advanced' } },
      'XC',
    ],
    ['default XC', { ...savedProfile, is_default: true }, 'XC'],
    ['saved M3U', savedProfile, 'STD'],
  ])('closes an unchanged %s editor without a warning', (_, profile, type) => {
    const { dialog, onClose } = openEditor(profile, type);
    closeEditor(dialog);
    expect(onClose).toHaveBeenCalledOnce();
    expect(
      screen.queryByRole('dialog', { name: 'Discard unsaved changes?' })
    ).not.toBeInTheDocument();
  });

  it.each([
    ['Name', 'Unsaved profile', null, 'XC'],
    ['Max Streams', '4', savedProfile, 'XC'],
    ['New Username', 'changed-user', savedProfile, 'XC'],
    ['New Password', 'changed-password', savedProfile, 'XC'],
    ['Notes', 'Unsaved note', savedProfile, 'XC'],
    [
      'Search Pattern (Regex)',
      '^changed',
      { ...savedProfile, is_default: true },
      'XC',
    ],
    ['Replace Pattern', '$1-new', { ...savedProfile, is_default: true }, 'XC'],
    ['Expiration Date', '2031-02-03T12:00:00.000Z', savedProfile, 'STD'],
    ['Expiration Date', '', savedProfile, 'STD'],
  ])(
    'guards changes to %s and keeps the draft',
    async (label, value, profile, type) => {
      const { dialog, onClose } = openEditor(profile, type);
      fireEvent.change(within(dialog).getByLabelText(label), {
        target: { value },
      });
      closeEditor(dialog);
      const confirmation = await screen.findByRole('dialog', {
        name: 'Discard unsaved changes?',
      });
      expect(dialog).toBeInTheDocument();
      expect(onClose).not.toHaveBeenCalled();
      fireEvent.click(
        within(confirmation).getByRole('button', { name: 'Keep editing' })
      );
      await waitFor(() =>
        expect(
          screen.queryByRole('dialog', { name: 'Discard unsaved changes?' })
        ).not.toBeInTheDocument()
      );
      const field = within(dialog).getByLabelText(label);
      expect(field.value).toBe(value);
      expect(API.addM3UProfile).not.toHaveBeenCalled();
      expect(API.updateM3UProfile).not.toHaveBeenCalled();
    }
  );

  it('keeps mode changes until the discard is explicitly confirmed', async () => {
    const { dialog, onClose } = openEditor(savedProfile);
    fireEvent.click(
      within(dialog).getByRole('radio', { name: 'Advanced (Regex)' })
    );
    closeEditor(dialog);
    let confirmation = await screen.findByRole('dialog', {
      name: 'Discard unsaved changes?',
    });
    fireEvent.click(
      within(confirmation).getByRole('button', {
        name: 'Close confirmation dialog',
      })
    );
    await waitFor(() =>
      expect(
        within(dialog).getByRole('radio', { name: 'Advanced (Regex)' })
      ).toBeChecked()
    );
    closeEditor(dialog);
    confirmation = await screen.findByRole('dialog', {
      name: 'Discard unsaved changes?',
    });
    fireEvent.click(
      within(confirmation).getByRole('button', { name: 'Discard' })
    );
    expect(onClose).toHaveBeenCalledOnce();
    expect(API.updateM3UProfile).not.toHaveBeenCalled();
  });

  it('recognizes when a field is reverted to its saved value', () => {
    const { dialog, onClose } = openEditor(savedProfile);
    const name = within(dialog).getByLabelText('Name');
    fireEvent.change(name, { target: { value: 'Temporary edit' } });
    fireEvent.change(name, { target: { value: savedProfile.name } });
    closeEditor(dialog);
    expect(onClose).toHaveBeenCalledOnce();
  });

  it('does not warn after returning to an unchanged advanced profile', () => {
    const { dialog, onClose } = openEditor({
      ...savedProfile,
      search_pattern: '^https?://([^/]+)',
      replace_pattern: '$1',
      custom_properties: { xcMode: 'advanced' },
    });
    fireEvent.click(within(dialog).getByRole('radio', { name: 'Simple' }));
    fireEvent.click(
      within(dialog).getByRole('radio', { name: 'Advanced (Regex)' })
    );
    closeEditor(dialog);
    expect(onClose).toHaveBeenCalledOnce();
  });

  it('guards Escape without losing the draft', async () => {
    const { dialog, onClose } = openEditor();
    const name = within(dialog).getByLabelText('Name');
    fireEvent.change(name, { target: { value: 'Keep this draft' } });
    fireEvent.keyDown(name, { key: 'Escape' });
    expect(
      await screen.findByRole('dialog', { name: 'Discard unsaved changes?' })
    ).toBeInTheDocument();
    expect(name).toHaveValue('Keep this draft');
    expect(onClose).not.toHaveBeenCalled();
  });

  it('does not treat regex sample text as a saved profile change', () => {
    const { dialog, onClose } = openEditor({
      ...savedProfile,
      is_default: true,
    });
    fireEvent.change(
      within(dialog).getByPlaceholderText('Enter a sample URL to test with'),
      {
        target: { value: 'https://example.invalid/sample' },
      }
    );
    closeEditor(dialog);
    expect(onClose).toHaveBeenCalledOnce();
  });

  it('prevents closing during a save and guards the draft again after failure', async () => {
    let rejectSave;
    API.updateM3UProfile.mockReturnValueOnce(
      new Promise((_, reject) => {
        rejectSave = reject;
      })
    );
    const { dialog, onClose } = openEditor(savedProfile);
    fireEvent.change(within(dialog).getByLabelText('Name'), {
      target: { value: 'Unsaved profile' },
    });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Submit' }));
    await waitFor(() => expect(API.updateM3UProfile).toHaveBeenCalledOnce());
    expect(
      within(dialog).getByRole('button', {
        name: 'Close connection profile editor',
      })
    ).toBeDisabled();
    fireEvent.keyDown(dialog, { key: 'Escape' });
    expect(onClose).not.toHaveBeenCalled();
    rejectSave(new Error('Synthetic save failure'));
    await waitFor(() =>
      expect(
        within(dialog).getByRole('button', { name: 'Submit' })
      ).toBeEnabled()
    );
    closeEditor(dialog);
    expect(
      await screen.findByRole('dialog', { name: 'Discard unsaved changes?' })
    ).toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();
  });
});
