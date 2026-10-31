import { MantineProvider } from '@mantine/core';
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import api from '../../../../api';
import { showNotification } from '../../../../utils/notificationUtils.js';
import {
  CleanupSettingsForm,
  MetadataSettingsForm,
} from '../VODSettingsForm.jsx';

vi.mock('../../../../api', () => ({
  default: {
    getVODLibrarySettings: vi.fn(),
    updateVODLibrarySettings: vi.fn(),
    vodLibraryAction: vi.fn(),
  },
}));
vi.mock('../../../../utils/notificationUtils.js', () => ({
  showNotification: vi.fn(),
}));

const initial = {
  languages: ['en-US'],
  token_configured: true,
  token_source: 'stored',
  auto_enrich: false,
  match_missing: false,
  prefer_artwork: true,
  title_rules: [],
  year_rules: [{ value: '(YYYY)', position: 'end', enabled: true }],
};
const renderUI = (element) =>
  render(<MantineProvider env="test">{element}</MantineProvider>);
const save = () => screen.getByRole('button', { name: 'Save', exact: true });
const expectSaved = async () => {
  await waitFor(() =>
    expect(showNotification).toHaveBeenCalledWith(
      expect.objectContaining({
        message: 'Settings saved successfully',
        color: 'green',
        autoClose: 2000,
      })
    )
  );
  expect(screen.queryByText('Saved Successfully')).not.toBeInTheDocument();
};

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  api.getVODLibrarySettings.mockResolvedValue(initial);
  api.updateVODLibrarySettings.mockImplementation(async (patch) => ({
    ...initial,
    ...patch,
  }));
});

describe('Metadata settings', () => {
  const edit = async () => {
    fireEvent.click(await screen.findByRole('button', { name: 'Edit TMDB' }));
    return screen.getByLabelText('API Read Access Token');
  };

  it('shows only TMDB with Status and Actions, no Add or inline credentials', async () => {
    renderUI(<MetadataSettingsForm />);
    const table = await screen.findByRole('table', {
      name: 'Metadata providers',
    });
    expect(
      within(table)
        .getAllByRole('columnheader')
        .map((cell) => cell.textContent)
    ).toEqual(['Provider', 'Status', 'Actions']);
    expect(within(table).getByText('TMDB')).toBeInTheDocument();
    expect(within(table).getByText('Not checked')).toBeInTheDocument();
    expect(
      screen.queryByLabelText('API Read Access Token')
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: /Add/ })
    ).not.toBeInTheDocument();
    expect(save()).toBeDisabled();
    expect(api.updateVODLibrarySettings).not.toHaveBeenCalled();
    expect(showNotification).not.toHaveBeenCalled();
  });

  it('saves translations in Library display order without a client primary language', async () => {
    renderUI(<MetadataSettingsForm />);
    const languages = await screen.findByRole('textbox', {
      name: 'Metadata languages',
      exact: true,
    });
    for (const name of ['German (de-DE)', 'Spanish (es-ES)']) {
      fireEvent.click(languages);
      fireEvent.click(await screen.findByRole('option', { name, exact: true }));
    }
    expect(
      screen.queryByLabelText('Preferred language')
    ).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Primary language')).not.toBeInTheDocument();
    fireEvent.click(save());
    await waitFor(() =>
      expect(api.updateVODLibrarySettings).toHaveBeenCalledWith({
        languages: ['en-US', 'de-DE', 'es-ES'],
        auto_enrich: false,
        match_missing: false,
        prefer_artwork: true,
      })
    );
    await expectSaved();
    expect(showNotification).toHaveBeenCalledWith(
      expect.objectContaining({ title: 'Metadata' })
    );
    expect(save()).toBeDisabled();
  });

  it('keeps a stored selection above five when saving unrelated metadata settings', async () => {
    const languages = ['en-US', 'de-DE', 'es-ES', 'fr-FR', 'it-IT', 'ja-JP'];
    api.getVODLibrarySettings.mockResolvedValue({ ...initial, languages });
    api.updateVODLibrarySettings.mockImplementation(async (patch) => ({
      ...initial,
      languages,
      ...patch,
    }));
    renderUI(<MetadataSettingsForm />);
    await screen.findByRole('textbox', {
      name: 'Metadata languages',
      exact: true,
    });
    fireEvent.click(
      screen.getByRole('switch', {
        name: 'Enrich new imported titles automatically',
      })
    );
    fireEvent.click(save());
    await waitFor(() =>
      expect(api.updateVODLibrarySettings).toHaveBeenCalledWith({
        auto_enrich: true,
        match_missing: false,
        prefer_artwork: true,
      })
    );
    expect(
      screen.getByRole('button', { name: 'Remove Japanese (ja-JP)' })
    ).toBeInTheDocument();
  });

  it('preserves an existing language outside the suggestions', async () => {
    api.getVODLibrarySettings.mockResolvedValue({
      ...initial,
      languages: ['ca-ES', 'en-US'],
    });
    renderUI(<MetadataSettingsForm />);
    await screen.findAllByText('ca-ES', { exact: true });
    fireEvent.click(
      screen.getByRole('switch', {
        name: 'Enrich new imported titles automatically',
      })
    );
    fireEvent.click(save());
    await waitFor(() =>
      expect(api.updateVODLibrarySettings).toHaveBeenCalledWith(
        expect.objectContaining({ languages: ['ca-ES', 'en-US'] })
      )
    );
  });

  it('does not permit an empty language selection', async () => {
    renderUI(<MetadataSettingsForm />);
    const languages = await screen.findByRole('textbox', {
      name: 'Metadata languages',
      exact: true,
    });
    fireEvent.keyDown(languages, { key: 'Backspace', code: 'Backspace' });
    expect(
      await screen.findByText('Choose at least one metadata language.')
    ).toBeInTheDocument();
    expect(save()).toBeDisabled();
    expect(api.updateVODLibrarySettings).not.toHaveBeenCalled();
  });

  it('does not unlock an environment-managed token', async () => {
    api.getVODLibrarySettings.mockResolvedValue({
      ...initial,
      token_source: 'environment',
    });
    renderUI(<MetadataSettingsForm />);
    expect(
      await screen.findByRole('button', { name: 'Edit TMDB' })
    ).toBeDisabled();
    expect(screen.queryByLabelText('API token')).not.toBeInTheDocument();
    expect(api.updateVODLibrarySettings).not.toHaveBeenCalled();
  });

  it('starts blank, saves only an explicit token change and clears its draft', async () => {
    renderUI(<MetadataSettingsForm />);
    const token = await edit();
    expect(token).toHaveValue('');
    expect(token).toHaveAttribute('type', 'password');
    expect(screen.getByRole('button', { name: 'Save TMDB' })).toBeDisabled();
    fireEvent.change(token, { target: { value: 'synthetic-token' } });
    expect(save()).toBeDisabled();
    expect(api.updateVODLibrarySettings).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Save TMDB' }));
    await expectSaved();
    expect(api.updateVODLibrarySettings).toHaveBeenCalledWith({
      api_token: 'synthetic-token',
    });
    expect(screen.queryByLabelText('API token')).not.toBeInTheDocument();
    expect(await edit()).toHaveValue('');
  });

  it('discards credential changes without writing and removes tokens only explicitly', async () => {
    renderUI(<MetadataSettingsForm />);
    fireEvent.change(await edit(), { target: { value: 'synthetic-token' } });
    fireEvent.click(
      screen.getByRole('button', { name: 'Close Configure TMDB' })
    );
    fireEvent.click(
      await screen.findByRole('button', { name: 'Discard', exact: true })
    );
    expect(api.updateVODLibrarySettings).not.toHaveBeenCalled();
    await edit();
    fireEvent.click(
      screen.getByRole('checkbox', { name: 'Remove stored token' })
    );
    fireEvent.click(screen.getByRole('button', { name: 'Save TMDB' }));
    await waitFor(() =>
      expect(api.updateVODLibrarySettings).toHaveBeenCalledWith({
        clear_api_token: true,
      })
    );
  });

  it('preserves pending settings when saving the independent provider row', async () => {
    renderUI(<MetadataSettingsForm />);
    const auto = await screen.findByRole('switch', {
      name: 'Enrich new imported titles automatically',
    });
    fireEvent.click(auto);
    fireEvent.change(await edit(), { target: { value: 'synthetic-token' } });
    expect(auto).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'Save TMDB' }));
    await expectSaved();
    expect(auto).toBeChecked();
    expect(save()).toBeEnabled();
    fireEvent.click(save());
    await waitFor(() =>
      expect(api.updateVODLibrarySettings).toHaveBeenLastCalledWith({
        languages: ['en-US'],
        auto_enrich: true,
        match_missing: false,
        prefer_artwork: true,
      })
    );
  });

  it('retains credential changes on write failure and allows retry', async () => {
    api.updateVODLibrarySettings.mockRejectedValueOnce(
      new Error('Unavailable')
    );
    renderUI(<MetadataSettingsForm />);
    fireEvent.change(await edit(), { target: { value: 'synthetic-token' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save TMDB' }));
    await waitFor(() =>
      expect(showNotification).toHaveBeenCalledWith(
        expect.objectContaining({ message: 'Unavailable', color: 'red' })
      )
    );
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(screen.getByLabelText('API Read Access Token')).toHaveValue(
      'synthetic-token'
    );
    expect(showNotification).not.toHaveBeenCalledWith(
      expect.objectContaining({ color: 'green' })
    );
    expect(save()).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'Save TMDB' }));
    await expectSaved();
    expect(api.updateVODLibrarySettings).toHaveBeenCalledTimes(2);
  });

  it('tests a stored credential without changing pending settings', async () => {
    api.vodLibraryAction.mockResolvedValue({
      status: 'connected',
      detail: 'TMDB connection verified.',
      checked_at: '2026-10-31T12:00:00Z',
    });
    renderUI(<MetadataSettingsForm />);
    fireEvent.click(
      await screen.findByRole('switch', {
        name: 'Enrich new imported titles automatically',
      })
    );
    fireEvent.click(
      screen.getByRole('button', { name: 'Test TMDB connection' })
    );
    await screen.findByText('Connected');
    expect(api.vodLibraryAction).toHaveBeenCalledWith('test-connection', {});
    expect(api.updateVODLibrarySettings).not.toHaveBeenCalled();
    expect(
      screen.getByRole('switch', {
        name: 'Enrich new imported titles automatically',
      })
    ).toBeChecked();
    expect(save()).toBeEnabled();
  });
  it('tests a draft without saving and marks a rejected credential in the field', async () => {
    api.vodLibraryAction.mockResolvedValue({
      status: 'error',
      detail: 'TMDB rejected the credential.',
    });
    renderUI(<MetadataSettingsForm />);
    const token = await edit();
    fireEvent.change(token, { target: { value: 'synthetic-draft' } });
    fireEvent.click(
      screen.getByRole('button', { name: 'Test connection', exact: true })
    );
    await waitFor(() =>
      expect(showNotification).toHaveBeenCalledWith(
        expect.objectContaining({
          color: 'red',
          message: 'TMDB rejected the credential.',
        })
      )
    );
    expect(token).toHaveAttribute('aria-invalid', 'true');
    expect(token).toHaveValue('synthetic-draft');
    expect(api.updateVODLibrarySettings).not.toHaveBeenCalled();
    fireEvent.change(token, { target: { value: 'replacement-draft' } });
    expect(token).toHaveAttribute('aria-invalid', 'false');
    expect(screen.queryByText('Connected')).not.toBeInTheDocument();
  });
  it('keeps metadata protection fixed instead of offering a setting', async () => {
    renderUI(<MetadataSettingsForm />);
    await screen.findByRole('switch', {
      name: 'Enrich new imported titles automatically',
    });
    expect(
      screen.queryByRole('switch', { name: /^Protect metadata/ })
    ).not.toBeInTheDocument();
  });
  it('keeps other settings valid when the connection check fails', async () => {
    api.vodLibraryAction.mockRejectedValue(new Error('Network unavailable'));
    renderUI(<MetadataSettingsForm />);
    fireEvent.click(
      await screen.findByRole('button', { name: 'Test TMDB connection' })
    );
    await waitFor(() =>
      expect(showNotification).toHaveBeenCalledWith(
        expect.objectContaining({ color: 'red', title: 'TMDB connection' })
      )
    );
    expect(
      screen.getByRole('textbox', { name: 'Metadata languages' })
    ).toHaveAttribute('aria-invalid', 'false');
  });
  it('can retry reading settings without writing them', async () => {
    api.getVODLibrarySettings
      .mockRejectedValueOnce(new Error('Unavailable'))
      .mockResolvedValueOnce(initial);
    renderUI(<MetadataSettingsForm />);
    fireEvent.click(await screen.findByRole('button', { name: 'Retry' }));
    await screen.findByRole('button', { name: 'Edit TMDB' });
    expect(api.updateVODLibrarySettings).not.toHaveBeenCalled();
  });
});

describe('Cleanup settings', () => {
  it('saves literal anywhere removals on Enter without changing prefixes or years', async () => {
    mountCleanup({ removal_rules: [] });
    const input = await screen.findByRole('textbox', {
      name: 'New text to remove',
    });
    fireEvent.change(input, { target: { value: '(IT)' } });
    expect(api.updateVODLibrarySettings).not.toHaveBeenCalled();
    fireEvent.keyDown(input, { key: 'Enter' });
    await expectSaved();
    expect(api.updateVODLibrarySettings).toHaveBeenCalledWith({
      removal_rules: [{ value: '(IT)', enabled: true }],
    });
    fireEvent.change(input, { target: { value: '(IT)' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(
      await screen.findByText('This text removal already exists.')
    ).toBeInTheDocument();
    expect(api.updateVODLibrarySettings).toHaveBeenCalledTimes(1);
  });
  const mountCleanup = (overrides = {}) => {
    let settings = { ...initial, ...overrides };
    api.getVODLibrarySettings.mockResolvedValue(settings);
    api.updateVODLibrarySettings.mockImplementation(async (patch) => {
      settings = { ...settings, ...patch };
      return settings;
    });
    return renderUI(<CleanupSettingsForm />);
  };
  const rowAction = (name) => screen.getByRole('button', { name, exact: true });
  const enter = (label, value) =>
    fireEvent.change(
      screen.getByRole('textbox', { name: label, exact: true }),
      {
        target: { value },
      }
    );
  const choosePosition = async (index, label) => {
    fireEvent.click(
      screen.getByRole('textbox', { name: `Year position ${index}` })
    );
    fireEvent.click(
      await screen.findByRole('option', { name: label, exact: true })
    );
  };

  it('uses compact prefix tags and preserves the locked year table', async () => {
    mountCleanup({ title_rules: [{ value: 'NF - ', enabled: true }] });
    const years = await screen.findByRole('table', {
      name: 'Release-year formats',
    });
    expect(
      screen.queryByRole('table', { name: 'Title prefixes' })
    ).not.toBeInTheDocument();
    expect(screen.getByText('NF -', { exact: true })).toBeInTheDocument();
    expect(
      within(years)
        .getAllByRole('columnheader')
        .map((cell) => cell.textContent)
    ).toEqual(['Format', 'Position', 'Actions']);
    expect(
      screen.getByRole('textbox', { name: 'Year format 1' })
    ).toBeDisabled();
    expect(screen.queryByRole('switch')).not.toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: 'Save', exact: true })
    ).not.toBeInTheDocument();
    expect(api.updateVODLibrarySettings).not.toHaveBeenCalled();
  });

  it('keeps help icons close to headings without reducing their click targets', async () => {
    mountCleanup();
    for (const name of ['About title prefixes', 'About release-year formats']) {
      const help = await screen.findByRole('button', { name, exact: true });
      expect(help.parentElement).toHaveStyle({ '--group-gap': '0rem' });
      expect(help).not.toHaveAttribute('data-size');
      fireEvent.focus(help);
      expect(help).toBeEnabled();
    }
    expect(api.updateVODLibrarySettings).not.toHaveBeenCalled();
  });

  it('saves literal prefix tags immediately on Enter without an extra Save button', async () => {
    mountCleanup();
    const prefix = await screen.findByRole('textbox', {
      name: 'New title prefix',
    });
    fireEvent.keyDown(prefix, { key: 'Enter' });
    expect(screen.queryByText('Enter a value.')).not.toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: 'Add prefix' })
    ).not.toBeInTheDocument();
    expect(rowAction('Add format')).toBeEnabled();
    enter('New title prefix', 'NF - ');
    expect(rowAction('Add format')).toBeDisabled();
    expect(rowAction('Edit year format 1')).toBeDisabled();
    fireEvent.keyDown(prefix, { key: 'Enter' });
    await waitFor(() =>
      expect(api.updateVODLibrarySettings).toHaveBeenCalledWith({
        title_rules: [{ value: 'NF - ', enabled: true }],
      })
    );
    await expectSaved();
    expect(prefix).toHaveValue('');
    expect(showNotification).toHaveBeenCalledWith(
      expect.objectContaining({ title: 'Cleanup' })
    );
    expect(
      screen.queryByRole('button', { name: 'Save prefixes' })
    ).not.toBeInTheDocument();
    expect(rowAction('Add format')).toBeEnabled();
  });

  it('requires an actual change before saving an existing year format', async () => {
    mountCleanup();
    fireEvent.click(
      await screen.findByRole('button', { name: 'Edit year format 1' })
    );
    expect(rowAction('Save year format 1')).toBeDisabled();
    expect(
      screen.getByRole('textbox', { name: 'Year format 1' })
    ).toHaveFocus();
    await choosePosition(1, 'Anywhere');
    expect(rowAction('Save year format 1')).toBeEnabled();
    await choosePosition(1, 'At end');
    expect(rowAction('Save year format 1')).toBeDisabled();
    enter('Year format 1', '[YYYY]');
    fireEvent.click(rowAction('Save year format 1'));
    await waitFor(() =>
      expect(api.updateVODLibrarySettings).toHaveBeenCalledWith({
        year_rules: [{ value: '[YYYY]', position: 'end', enabled: true }],
      })
    );
    await expectSaved();
    expect(
      screen.getByRole('textbox', { name: 'Year format 1' })
    ).toBeDisabled();
  });

  it('previews only entered prefixes but includes valid pending year edits', async () => {
    mountCleanup();
    await screen.findByRole('textbox', { name: 'New title prefix' });
    api.vodLibraryAction.mockResolvedValue({ count: 0, results: [], page: 1 });
    enter('New title prefix', 'NF - ');
    fireEvent.click(rowAction('Without TMDB ID'));
    await screen.findByText('No matching titles');
    expect(api.vodLibraryAction).toHaveBeenLastCalledWith(
      'cleanup-preview',
      expect.objectContaining({
        title_rules: [],
      })
    );
    enter('New title prefix', '');
    fireEvent.click(rowAction('Edit year format 1'));
    enter('Year format 1', '[YYYY]');
    fireEvent.click(rowAction('Without TMDB ID'));
    await screen.findByText('No matching titles');
    expect(api.vodLibraryAction).toHaveBeenLastCalledWith(
      'cleanup-preview',
      expect.objectContaining({
        title_rules: [],
        year_rules: [{ value: '[YYYY]', position: 'end', enabled: true }],
      })
    );
    expect(api.updateVODLibrarySettings).not.toHaveBeenCalled();
  });

  it('rejects duplicates and keeps disabled prefixes and their order', async () => {
    const rules = [
      { value: 'One', enabled: false },
      { value: 'Two', enabled: true },
    ];
    mountCleanup({ title_rules: rules });
    await screen.findByRole('textbox', { name: 'New title prefix' });
    enter('New title prefix', 'One');
    fireEvent.keyDown(
      screen.getByRole('textbox', { name: 'New title prefix' }),
      { key: 'Enter' }
    );
    expect(
      await screen.findByText('This prefix already exists.')
    ).toBeInTheDocument();
    expect(api.updateVODLibrarySettings).not.toHaveBeenCalled();
    enter('New title prefix', 'Three');
    fireEvent.keyDown(
      screen.getByRole('textbox', { name: 'New title prefix' }),
      { key: 'Enter' }
    );
    await waitFor(() =>
      expect(api.updateVODLibrarySettings).toHaveBeenCalledWith({
        title_rules: [...rules, { value: 'Three', enabled: true }],
      })
    );
  });

  it('saves prefix removals immediately and preserves remaining flags and order', async () => {
    const remaining = [
      { value: 'Two', enabled: false },
      { value: 'Three', enabled: true },
    ];
    mountCleanup({
      title_rules: [{ value: 'One', enabled: true }, ...remaining],
    });
    await screen.findByRole('textbox', { name: 'New title prefix' });
    fireEvent.click(rowAction('Remove prefix 1'));
    await expectSaved();
    expect(api.updateVODLibrarySettings).toHaveBeenCalledExactlyOnceWith({
      title_rules: remaining,
    });
    expect(screen.queryByText('One', { exact: true })).not.toBeInTheDocument();
    expect(screen.getByText('Two', { exact: true })).toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: 'Save prefixes' })
    ).not.toBeInTheDocument();
  });

  it('keeps prefix changes on a failed save and permits retry', async () => {
    mountCleanup();
    api.updateVODLibrarySettings.mockRejectedValueOnce(
      new Error('Unavailable')
    );
    await screen.findByRole('textbox', { name: 'New title prefix' });
    enter('New title prefix', 'NF - ');
    fireEvent.keyDown(
      screen.getByRole('textbox', { name: 'New title prefix' }),
      { key: 'Enter' }
    );
    await waitFor(() =>
      expect(showNotification).toHaveBeenCalledWith(
        expect.objectContaining({ message: 'Unavailable', color: 'red' })
      )
    );
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(
      screen.getByRole('textbox', { name: 'New title prefix' })
    ).toHaveValue('NF - ');
    expect(showNotification).not.toHaveBeenCalledWith(
      expect.objectContaining({ color: 'green' })
    );
    expect(rowAction('Add format')).toBeDisabled();
    fireEvent.keyDown(
      screen.getByRole('textbox', { name: 'New title prefix' }),
      { key: 'Enter' }
    );
    await expectSaved();
    expect(screen.getByText('NF -', { exact: true })).toBeInTheDocument();
    expect(api.updateVODLibrarySettings).toHaveBeenCalledTimes(2);
  });

  it('keeps a prefix tag when removal fails and allows retry', async () => {
    mountCleanup({ title_rules: [{ value: 'NF - ', enabled: true }] });
    api.updateVODLibrarySettings.mockRejectedValueOnce(
      new Error('Unavailable')
    );
    fireEvent.click(
      await screen.findByRole('button', { name: 'Remove prefix 1' })
    );
    await waitFor(() =>
      expect(showNotification).toHaveBeenCalledWith(
        expect.objectContaining({ message: 'Unavailable', color: 'red' })
      )
    );
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(screen.getByText('NF -', { exact: true })).toBeInTheDocument();
    expect(showNotification).not.toHaveBeenCalledWith(
      expect.objectContaining({ color: 'green' })
    );
    fireEvent.click(rowAction('Remove prefix 1'));
    await expectSaved();
    expect(screen.queryByText('NF -', { exact: true })).not.toBeInTheDocument();
    expect(api.updateVODLibrarySettings).toHaveBeenLastCalledWith({
      title_rules: [],
    });
  });

  it('blocks overlapping prefix writes and clears the unsaved warning only after success', async () => {
    mountCleanup({ title_rules: [{ value: 'Existing', enabled: false }] });
    let finish;
    api.updateVODLibrarySettings.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        })
    );
    const prefix = await screen.findByRole('textbox', {
      name: 'New title prefix',
    });
    enter('New title prefix', 'NF - ');
    fireEvent.keyDown(prefix, { key: 'Enter' });
    fireEvent.keyDown(prefix, { key: 'Enter' });
    expect(api.updateVODLibrarySettings).toHaveBeenCalledTimes(1);
    expect(prefix).toBeDisabled();
    expect(rowAction('Remove prefix 1')).toBeDisabled();
    expect(rowAction('Add format')).toBeDisabled();
    expect(showNotification).not.toHaveBeenCalled();
    const pending = new Event('beforeunload', { cancelable: true });
    window.dispatchEvent(pending);
    expect(pending.defaultPrevented).toBe(true);
    finish({
      ...initial,
      title_rules: [
        { value: 'Existing', enabled: false },
        { value: 'NF - ', enabled: true },
      ],
    });
    await expectSaved();
    expect(prefix).toHaveValue('');
    expect(prefix).toBeEnabled();
    expect(rowAction('Add format')).toBeEnabled();
    const saved = new Event('beforeunload', { cancelable: true });
    window.dispatchEvent(saved);
    expect(saved.defaultPrevented).toBe(false);
  });

  it('does not auto-save typing, empty Enter or unfinished prefixes when removing a tag', async () => {
    mountCleanup({ title_rules: [{ value: 'Existing', enabled: true }] });
    const prefix = await screen.findByRole('textbox', {
      name: 'New title prefix',
    });
    enter('New title prefix', '   ');
    fireEvent.keyDown(prefix, { key: 'Enter' });
    expect(api.updateVODLibrarySettings).not.toHaveBeenCalled();
    enter('New title prefix', 'Pending ');
    expect(api.updateVODLibrarySettings).not.toHaveBeenCalled();
    fireEvent.click(rowAction('Remove prefix 1'));
    await expectSaved();
    expect(api.updateVODLibrarySettings).toHaveBeenCalledExactlyOnceWith({
      title_rules: [],
    });
    expect(prefix).toHaveValue('Pending ');
  });

  it('requires exactly one YYYY token and prevents duplicate year formats independently of position', async () => {
    mountCleanup();
    fireEvent.click(await screen.findByRole('button', { name: 'Add format' }));
    expect(
      screen.queryByText('Include YYYY exactly once.')
    ).not.toBeInTheDocument();
    enter('Year format 2', 'Year');
    fireEvent.click(rowAction('Save year format 2'));
    expect(
      await screen.findByText('Include YYYY exactly once.')
    ).toBeInTheDocument();
    enter('Year format 2', 'YYYY YYYY');
    fireEvent.click(rowAction('Save year format 2'));
    expect(screen.getByText('Include YYYY exactly once.')).toBeInTheDocument();
    enter('Year format 2', ' ({year}) ');
    await choosePosition(2, 'Anywhere');
    fireEvent.click(rowAction('Save year format 2'));
    expect(
      await screen.findByText('This year format already exists.')
    ).toBeInTheDocument();
    expect(api.updateVODLibrarySettings).not.toHaveBeenCalled();
    enter('Year format 2', '{YYYY}');
    fireEvent.click(rowAction('Save year format 2'));
    await waitFor(() =>
      expect(api.updateVODLibrarySettings).toHaveBeenCalledWith({
        year_rules: [
          ...initial.year_rules,
          { value: '{YYYY}', position: 'anywhere', enabled: true },
        ],
      })
    );
  });

  it.each(['mouseEnter', 'focus'])(
    'explains only the plain YYYY format on %s without saving',
    async (event) => {
      mountCleanup({
        year_rules: [
          ...initial.year_rules,
          { value: 'YYYY', position: 'end', enabled: true },
          { value: '[YYYY]', position: 'end', enabled: true },
        ],
      });
      const help = await screen.findByRole('button', {
        name: 'About plain YYYY year format',
      });
      expect(
        screen.getAllByRole('button', { name: 'About plain YYYY year format' })
      ).toHaveLength(1);
      expect(
        within(help.closest('tr')).getByRole('textbox', {
          name: 'Year format 2',
        })
      ).toHaveValue('YYYY');
      if (event === 'focus') {
        // JSDOM does not model keyboard :focus-visible for Floating UI.
        const matches = help.matches.bind(help);
        vi.spyOn(help, 'matches').mockImplementation((selector) =>
          selector === ':focus-visible'
            ? document.activeElement === help
            : matches(selector)
        );
        const user = userEvent.setup();
        for (
          let index = 0;
          index < 20 && document.activeElement !== help;
          index++
        )
          await user.tab();
        expect(help).toHaveFocus();
      } else {
        fireEvent.mouseEnter(help);
      }
      expect(await screen.findByRole('tooltip')).toHaveTextContent(
        'Plain YYYY is removed only when the release year is known from provider data or title metadata. Unmarked numbers in titles are not used to guess the release year.'
      );
      expect(api.updateVODLibrarySettings).not.toHaveBeenCalled();
    }
  );

  it('shows the plain YYYY help for an unsaved draft only while that format is entered', async () => {
    mountCleanup();
    fireEvent.click(
      await screen.findByRole('button', { name: 'Edit year format 1' })
    );
    expect(
      screen.queryByRole('button', { name: 'About plain YYYY year format' })
    ).not.toBeInTheDocument();
    enter('Year format 1', 'YYYY');
    expect(
      screen.getByRole('button', { name: 'About plain YYYY year format' })
    ).toBeInTheDocument();
    enter('Year format 1', '(YYYY)');
    expect(
      screen.queryByRole('button', { name: 'About plain YYYY year format' })
    ).not.toBeInTheDocument();
    expect(api.updateVODLibrarySettings).not.toHaveBeenCalled();
  });

  it('keeps the row draft and blocks other rows after a failed save, then supports retry', async () => {
    mountCleanup();
    api.updateVODLibrarySettings.mockRejectedValueOnce(
      new Error('Unavailable')
    );
    fireEvent.click(
      await screen.findByRole('button', { name: 'Edit year format 1' })
    );
    enter('Year format 1', '{YYYY}');
    fireEvent.click(rowAction('Save year format 1'));
    await waitFor(() =>
      expect(showNotification).toHaveBeenCalledWith(
        expect.objectContaining({ message: 'Unavailable', color: 'red' })
      )
    );
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(screen.getByRole('textbox', { name: 'Year format 1' })).toHaveValue(
      '{YYYY}'
    );
    expect(
      screen.getByRole('textbox', { name: 'Year format 1' })
    ).toBeEnabled();
    expect(
      screen.getByRole('textbox', { name: 'New title prefix' })
    ).toBeDisabled();
    fireEvent.click(rowAction('Save year format 1'));
    await expectSaved();
    expect(
      screen.getByRole('textbox', { name: 'New title prefix' })
    ).toBeEnabled();
    expect(api.updateVODLibrarySettings).toHaveBeenCalledTimes(2);
  });

  it('blocks controls while a row save is in flight', async () => {
    mountCleanup();
    let finish;
    api.updateVODLibrarySettings.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        })
    );
    fireEvent.click(
      await screen.findByRole('button', { name: 'Edit year format 1' })
    );
    enter('Year format 1', '{YYYY}');
    fireEvent.click(rowAction('Save year format 1'));
    expect(rowAction('Save year format 1')).toBeDisabled();
    expect(rowAction('Discard year format 1 changes')).toBeDisabled();
    expect(
      screen.getByRole('textbox', { name: 'Year format 1' })
    ).toBeDisabled();
    expect(
      screen.getByRole('textbox', { name: 'New title prefix' })
    ).toBeDisabled();
    finish({
      ...initial,
      year_rules: [{ value: '{YYYY}', position: 'end', enabled: true }],
    });
    await expectSaved();
    expect(rowAction('Edit year format 1')).toBeEnabled();
  });

  it('confirms deletion and persists only the affected table', async () => {
    mountCleanup();
    fireEvent.click(
      await screen.findByRole('button', { name: 'Delete year format 1' })
    );
    expect(await screen.findByRole('dialog')).toHaveTextContent(
      'Existing Library titles will not be changed.'
    );
    expect(api.updateVODLibrarySettings).not.toHaveBeenCalled();
    fireEvent.click(rowAction('Cancel'));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    fireEvent.click(rowAction('Delete year format 1'));
    fireEvent.click(rowAction('Delete'));
    await waitFor(() =>
      expect(api.updateVODLibrarySettings).toHaveBeenCalledWith({
        year_rules: [],
      })
    );
    await screen.findByText('No year formats configured');
    expect(rowAction('Add format')).toBeEnabled();
  });

  it('retains a rule and shows an error if deletion fails', async () => {
    mountCleanup();
    api.updateVODLibrarySettings.mockRejectedValueOnce(
      new Error('Unavailable')
    );
    fireEvent.click(
      await screen.findByRole('button', { name: 'Delete year format 1' })
    );
    fireEvent.click(rowAction('Delete'));
    await waitFor(() =>
      expect(showNotification).toHaveBeenCalledWith(
        expect.objectContaining({ message: 'Unavailable', color: 'red' })
      )
    );
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(screen.getByRole('textbox', { name: 'Year format 1' })).toHaveValue(
      '(YYYY)'
    );
    expect(rowAction('Edit year format 1')).toBeEnabled();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('preserves saved disabled year formats and provides no year sorting or toggle', async () => {
    const disabled = { value: '[YYYY]', position: 'anywhere', enabled: false };
    mountCleanup({ year_rules: [disabled] });
    await screen.findByRole('textbox', { name: 'Year format 1' });
    expect(screen.getByText('Disabled', { exact: true })).toBeInTheDocument();
    expect(
      screen.queryByRole('switch', { name: /Enable year format/ })
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: /Move year format/ })
    ).not.toBeInTheDocument();
    fireEvent.click(rowAction('Edit year format 1'));
    enter('Year format 1', '{YYYY}');
    fireEvent.click(rowAction('Save year format 1'));
    await waitFor(() =>
      expect(api.updateVODLibrarySettings).toHaveBeenCalledWith({
        year_rules: [{ ...disabled, value: '{YYYY}' }],
      })
    );
  });

  it('honors the prefix limit without disabling year formats', async () => {
    mountCleanup({
      title_rules: Array.from({ length: 20 }, (_, i) => ({
        value: `Prefix ${i}`,
        enabled: true,
      })),
    });
    await screen.findByRole('textbox', { name: 'New title prefix' });
    expect(
      screen.getByRole('textbox', { name: 'New title prefix' })
    ).toBeDisabled();
    expect(rowAction('Add format')).toBeEnabled();
  });

  it('warns before reload only for a changed or new row and clears the warning after discard', async () => {
    const view = mountCleanup();
    await screen.findByRole('textbox', { name: 'Year format 1' });
    const clean = new Event('beforeunload', { cancelable: true });
    window.dispatchEvent(clean);
    expect(clean.defaultPrevented).toBe(false);
    fireEvent.click(rowAction('Edit year format 1'));
    const unchanged = new Event('beforeunload', { cancelable: true });
    window.dispatchEvent(unchanged);
    expect(unchanged.defaultPrevented).toBe(false);
    enter('Year format 1', '{YYYY}');
    const dirty = new Event('beforeunload', { cancelable: true });
    window.dispatchEvent(dirty);
    expect(dirty.defaultPrevented).toBe(true);
    fireEvent.click(rowAction('Discard year format 1 changes'));
    const discarded = new Event('beforeunload', { cancelable: true });
    window.dispatchEvent(discarded);
    expect(discarded.defaultPrevented).toBe(false);
    enter('New title prefix', 'NF - ');
    const added = new Event('beforeunload', { cancelable: true });
    window.dispatchEvent(added);
    expect(added.defaultPrevented).toBe(true);
    view.unmount();
    const after = new Event('beforeunload', { cancelable: true });
    window.dispatchEvent(after);
    expect(after.defaultPrevented).toBe(false);
  });
});
