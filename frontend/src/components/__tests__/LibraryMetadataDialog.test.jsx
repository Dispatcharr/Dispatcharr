import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react';
import { MantineProvider, Modal } from '@mantine/core';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import api from '../../api';
import useLibraryStore from '../../store/useLibraryStore';
import { showNotification } from '../../utils/notificationUtils.js';
import LibraryMetadataDialog from '../LibraryMetadataDialog.jsx';

vi.mock('../../api', () => ({
  default: {
    vodLibraryAction: vi.fn(),
    getVODLibraryState: vi.fn(),
    getVODLibrarySettings: vi.fn(),
    updateVODLibrarySettings: vi.fn(),
  },
}));
vi.mock('../../utils/notificationUtils.js', () => ({
  showNotification: vi.fn(),
}));
const item = {
  content_type: 'movie',
  content_id: 1,
  provider_name: 'EN Film (2020)',
  metadata_status: 'matched',
  tmdb_id: '42',
};
const selection = { items: [{ content_type: 'movie', id: 1 }] };
const rules = { title_rules: [], year_rules: [] };
const onClose = vi.fn();
const onChanged = vi.fn();
const onPreview = vi.fn();
const preview = {
  count: 1,
  results: [
    {
      content_type: 'movie',
      id: 1,
      before: 'Old title',
      after: 'Film',
      year: 2020,
      locked: false,
    },
  ],
};
const queued = {
  task_id: 'cleanup-1',
  status: 'queued',
  progress: { operation: 'cleanup', total: 1 },
};
const renderDialog = (props = {}) =>
  render(
    <MantineProvider env="test">
      <Modal.Stack>
        <LibraryMetadataDialog
          selection={selection}
          items={[item]}
          job={{ status: 'idle', progress: {} }}
          onClose={onClose}
          onChanged={onChanged}
          onPreview={onPreview}
          {...props}
        />
      </Modal.Stack>
    </MantineProvider>
  );
beforeEach(() => {
  vi.clearAllMocks();
  useLibraryStore.setState({
    trackedJobId: '',
    job: { status: 'idle', progress: {} },
  });
  api.vodLibraryAction.mockImplementation(async (operation, body) =>
    operation === 'cleanup-preview'
      ? preview
      : ['cleanup', 'enrich'].includes(body?.operation)
        ? { state: queued }
        : { count: 1 }
  );
  api.getVODLibraryState.mockResolvedValue(queued);
  api.getVODLibrarySettings.mockResolvedValue({
    ...rules,
    match_missing: false,
  });
  api.updateVODLibrarySettings.mockImplementation(async (values) => ({
    ...rules,
    ...values,
  }));
});
describe('selected Library metadata management', () => {
  it.each([false, true])(
    'confirms global output blocking separately from metadata protection (blocked=%s)',
    async (blocked) => {
      api.vodLibraryAction.mockResolvedValue({
        ...preview,
        blocked_count: blocked ? 1 : 0,
      });
      renderDialog({ items: [{ ...item, library_blocked: blocked }] });
      await screen.findByText('EN Film (2020)');
      fireEvent.click(
        screen.getByRole('button', {
          name: blocked ? 'Unblock selected titles' : 'Block selected titles',
        })
      );
      expect(api.vodLibraryAction).toHaveBeenCalledTimes(1);
      expect(
        screen.getByRole('dialog', {
          name: blocked ? 'Unblock titles?' : 'Block titles?',
        })
      ).toBeInTheDocument();
      if (!blocked)
        expect(
          screen.getByText(/not be listed or playable by any client/)
        ).toBeInTheDocument();
      fireEvent.click(
        screen.getByRole('button', { name: 'Confirm', exact: true })
      );
      await waitFor(() =>
        expect(api.vodLibraryAction).toHaveBeenCalledWith('bulk', {
          ...selection,
          operation: blocked ? 'unblock' : 'block',
        })
      );
    }
  );
  it('saves anywhere text globally only on Enter and retains the accepted field in preview and cleanup', async () => {
    api.getVODLibrarySettings.mockResolvedValue({
      ...rules,
      removal_rules: [],
      match_missing: false,
    });
    api.updateVODLibrarySettings.mockImplementation(async (values) => ({
      ...rules,
      removal_rules: [],
      ...values,
    }));
    renderDialog();
    await screen.findByText('EN Film (2020)');
    fireEvent.click(screen.getByRole('button', { name: 'Cleanup options' }));
    const input = screen.getByRole('textbox', { name: 'New text to remove' });
    fireEvent.change(input, { target: { value: '(ES)' } });
    expect(api.updateVODLibrarySettings).not.toHaveBeenCalled();
    expect(
      screen.getByRole('textbox', { name: 'New title prefix' })
    ).toBeDisabled();
    fireEvent.keyDown(input, { key: 'Enter' });
    await waitFor(() => expect(input).toHaveValue(''));
    expect(api.updateVODLibrarySettings).toHaveBeenCalledWith({
      removal_rules: [{ value: '(ES)', enabled: true }],
    });
    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: 'Cleanup', exact: true })
      ).toBeEnabled()
    );
    expect(api.vodLibraryAction).toHaveBeenLastCalledWith('cleanup-preview', {
      ...selection,
      ...rules,
      removal_rules: [{ value: '(ES)', enabled: true }],
      page: 1,
      page_size: 25,
    });
    fireEvent.click(
      screen.getByRole('button', { name: 'Cleanup', exact: true })
    );
    fireEvent.click(
      screen.getByRole('button', { name: 'Confirm', exact: true })
    );
    await waitFor(() =>
      expect(api.vodLibraryAction).toHaveBeenCalledWith('bulk', {
        ...selection,
        ...rules,
        removal_rules: [{ value: '(ES)', enabled: true }],
        operation: 'cleanup',
        include_protected: false,
      })
    );
  });
  it('shows the production cleanup columns and opens the exact title without changing it', async () => {
    renderDialog();
    await screen.findByText('EN Film (2020)');
    expect(
      screen.getAllByRole('columnheader').map((cell) => cell.textContent)
    ).toEqual([
      'Provider title',
      'Clean title',
      'Year',
      'TMDB result',
      'Details',
    ]);
    expect(screen.getByText('TMDB 42')).toBeInTheDocument();
    expect(screen.getByLabelText('Metadata unlocked')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Preview Film' }));
    expect(onPreview).toHaveBeenCalledExactlyOnceWith(item);
    expect(api.vodLibraryAction).toHaveBeenCalledExactlyOnceWith(
      'cleanup-preview',
      { ...selection, ...rules, page: 1, page_size: 25 }
    );
    fireEvent.click(
      screen.getByRole('button', { name: 'Close Edit selected titles (1)' })
    );
    expect(onClose).toHaveBeenCalledOnce();
    expect(onChanged).not.toHaveBeenCalled();
  });
  it('queues cleanup only after confirmation, tracks the notification and closes the dialog', async () => {
    let resolve;
    api.vodLibraryAction.mockImplementation(async (operation) =>
      operation === 'cleanup-preview'
        ? preview
        : new Promise((done) => {
            resolve = done;
          })
    );
    renderDialog();
    await screen.findByText('EN Film (2020)');
    const apply = screen.getByRole('button', { name: 'Cleanup' });
    fireEvent.click(apply);
    expect(api.vodLibraryAction).toHaveBeenCalledTimes(1);
    const confirm = screen.getByRole('button', {
      name: 'Confirm',
      exact: true,
    });
    fireEvent.click(confirm);
    expect(confirm).toBeDisabled();
    fireEvent.click(confirm);
    expect(api.vodLibraryAction).toHaveBeenCalledTimes(2);
    await act(async () => resolve({ state: queued }));
    expect(api.vodLibraryAction).toHaveBeenLastCalledWith('bulk', {
      ...selection,
      operation: 'cleanup',
      include_protected: false,
      ...rules,
    });
    expect(useLibraryStore.getState().trackedJobId).toBe('cleanup-1');
    expect(api.getVODLibraryState).toHaveBeenCalledOnce();
    expect(onChanged).toHaveBeenCalledOnce();
    expect(onClose).toHaveBeenCalledOnce();
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument();
  });
  it.each([
    ['Enrich', 'enrich'],
    ['Protect selected titles', 'lock'],
    ['Reset', 'reset'],
  ])(
    'confirms %s and keeps the explicit selected references',
    async (label, operation) => {
      const snapshot = {
        items: [
          { content_type: 'movie', id: 1 },
          { content_type: 'series', id: 8 },
        ],
      };
      renderDialog({
        selection: snapshot,
        items: [item, { ...item, content_id: 8, content_type: 'series' }],
      });
      await screen.findByText('EN Film (2020)');
      fireEvent.click(screen.getByRole('button', { name: label, exact: true }));
      expect(
        api.vodLibraryAction.mock.calls.every(
          ([name]) => name === 'cleanup-preview'
        )
      ).toBe(true);
      expect(
        screen
          .getByRole('dialog', {
            name: 'Edit selected titles (2)',
            hidden: true,
          })
          .closest('[inert]')
      ).not.toBeNull();
      fireEvent.click(
        screen.getByRole('button', { name: 'Confirm', exact: true })
      );
      await waitFor(() =>
        expect(api.vodLibraryAction).toHaveBeenCalledWith('bulk', {
          ...snapshot,
          operation,
          ...(operation === 'enrich'
            ? { include_protected: false, ...rules, search_missing: false }
            : {}),
        })
      );
      expect(onClose).toHaveBeenCalledOnce();
      if (operation === 'reset')
        expect(showNotification).toHaveBeenCalledWith(
          expect.objectContaining({
            message: 'Library metadata reset to provider data.',
            color: 'green',
          })
        );
    }
  );
  it.each(['queued', 'running'])(
    'prevents a competing action while a job is %s without an inline progress panel',
    async (status) => {
      renderDialog({ job: { ...queued, status } });
      await screen.findByText('EN Film (2020)');
      expect(screen.getByRole('button', { name: 'Cleanup' })).toBeDisabled();
      expect(screen.queryByRole('progressbar')).not.toBeInTheDocument();
      expect(
        screen.queryByRole('button', { name: 'Cancel job' })
      ).not.toBeInTheDocument();
    }
  );
  it('reports failures through notifications and allows retry without losing the selection', async () => {
    api.vodLibraryAction.mockRejectedValueOnce(
      new Error('Preview unavailable')
    );
    renderDialog();
    fireEvent.click(
      await screen.findByRole('button', { name: 'Retry preview' })
    );
    await screen.findByText('EN Film (2020)');
    expect(showNotification).toHaveBeenCalledWith(
      expect.objectContaining({ message: 'Preview unavailable', color: 'red' })
    );
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    api.vodLibraryAction.mockRejectedValueOnce(new Error('Queue unavailable'));
    fireEvent.click(screen.getByRole('button', { name: 'Cleanup' }));
    fireEvent.click(
      screen.getByRole('button', { name: 'Confirm', exact: true })
    );
    await waitFor(() =>
      expect(showNotification).toHaveBeenCalledWith(
        expect.objectContaining({ message: 'Queue unavailable', color: 'red' })
      )
    );
    expect(
      screen.getByRole('button', { name: 'Confirm', exact: true })
    ).toBeEnabled();
    expect(onChanged).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();
  });
  it('ignores a preview response after closing', async () => {
    let resolve;
    api.vodLibraryAction.mockImplementation(
      () =>
        new Promise((done) => {
          resolve = done;
        })
    );
    const { unmount } = renderDialog();
    await waitFor(() => expect(resolve).toBeTypeOf('function'));
    unmount();
    await act(async () => resolve({ results: [] }));
    expect(onChanged).not.toHaveBeenCalled();
    expect(showNotification).not.toHaveBeenCalled();
  });
  it('offers one Unlock control for an entirely protected selection and asks explicitly before processing it', async () => {
    renderDialog({ items: [{ ...item, metadata_locked: true }] });
    await screen.findByText('EN Film (2020)');
    expect(
      screen.getByRole('button', { name: 'Unlock selected titles' })
    ).toBeEnabled();
    expect(
      screen.queryByRole('button', { name: 'Protect selected titles' })
    ).not.toBeInTheDocument();
    fireEvent.click(
      screen.getByRole('button', { name: 'Enrich', exact: true })
    );
    expect(
      screen.getByText(/Process 1 protected title once/)
    ).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole('button', { name: 'Confirm', exact: true })
    );
    await waitFor(() =>
      expect(api.vodLibraryAction).toHaveBeenCalledWith('bulk', {
        ...selection,
        operation: 'enrich',
        include_protected: true,
        ...rules,
        search_missing: false,
      })
    );
  });
  it('saves global prefixes on Enter and previews only the accepted rules', async () => {
    renderDialog();
    await screen.findByText('EN Film (2020)');
    fireEvent.click(screen.getByRole('button', { name: 'Cleanup options' }));
    expect(
      screen.getByRole('table', { name: 'Cleanup preview' })
    ).toBeInTheDocument();
    expect(
      screen.queryByText('Loading selected title preview…')
    ).not.toBeInTheDocument();
    const prefix = screen.getByRole('textbox', { name: 'New title prefix' });
    const previewCalls = api.vodLibraryAction.mock.calls.length;
    fireEvent.change(prefix, { target: { value: 'EN ' } });
    expect(screen.getByRole('button', { name: 'Cleanup' })).toBeDisabled();
    expect(
      screen.getByRole('button', { name: 'Cleanup options' })
    ).toBeDisabled();
    await act(async () => new Promise((resolve) => setTimeout(resolve, 300)));
    expect(api.vodLibraryAction).toHaveBeenCalledTimes(previewCalls);
    expect(api.updateVODLibrarySettings).not.toHaveBeenCalled();
    let resolveSave;
    api.updateVODLibrarySettings.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolveSave = resolve;
        })
    );
    fireEvent.keyDown(prefix, { key: 'Enter' });
    expect(api.updateVODLibrarySettings).toHaveBeenCalledExactlyOnceWith({
      title_rules: [{ value: 'EN ', enabled: true }],
    });
    expect(api.vodLibraryAction).toHaveBeenCalledTimes(previewCalls);
    await act(async () =>
      resolveSave({ ...rules, title_rules: [{ value: 'EN ', enabled: true }] })
    );
    await waitFor(() =>
      expect(api.vodLibraryAction).toHaveBeenLastCalledWith(
        'cleanup-preview',
        expect.objectContaining({
          title_rules: [{ value: 'EN ', enabled: true }],
        })
      )
    );
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Cleanup' })).toBeEnabled()
    );
    fireEvent.click(screen.getByRole('button', { name: 'Cleanup' }));
    fireEvent.click(
      screen.getByRole('button', { name: 'Confirm', exact: true })
    );
    await waitFor(() =>
      expect(api.vodLibraryAction).toHaveBeenCalledWith('bulk', {
        ...selection,
        operation: 'cleanup',
        include_protected: false,
        title_rules: [{ value: 'EN ', enabled: true }],
        year_rules: [],
      })
    );
  });
  it('keeps a failed global save editable without changing the cleanup preview', async () => {
    api.updateVODLibrarySettings.mockRejectedValueOnce(
      new Error('Settings unavailable')
    );
    renderDialog();
    await screen.findByText('EN Film (2020)');
    fireEvent.click(screen.getByRole('button', { name: 'Cleanup options' }));
    expect(
      screen.getByRole('region', { name: 'Cleanup settings' }).className
    ).toContain('cleanupOptions');
    expect(
      screen.queryByText('Cleanup options for this selection')
    ).not.toBeInTheDocument();
    const prefix = screen.getByRole('textbox', { name: 'New title prefix' });
    fireEvent.change(prefix, { target: { value: 'EN ' } });
    fireEvent.keyDown(prefix, { key: 'Enter' });
    await waitFor(() =>
      expect(showNotification).toHaveBeenCalledWith(
        expect.objectContaining({
          message: 'Settings unavailable',
          color: 'red',
        })
      )
    );
    expect(prefix).toHaveValue('EN ');
    expect(api.vodLibraryAction).toHaveBeenCalledTimes(1);
    fireEvent.keyDown(prefix, { key: 'Enter' });
    await waitFor(() => expect(prefix).toHaveValue(''));
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Cleanup' })).toBeEnabled()
    );
    fireEvent.click(
      screen.getByRole('button', { name: 'Close Edit selected titles (1)' })
    );
    expect(onClose).toHaveBeenCalledOnce();
    expect(
      screen.queryByRole('dialog', { name: 'Discard unsaved changes?' })
    ).not.toBeInTheDocument();
  });
  it('uses the complete filtered selection and server protection count, not only the visible page', async () => {
    const all = {
      all_matching: true,
      filters: { view: 'titles', search: 'Film' },
      excluded: [{ content_type: 'movie', id: 2 }],
    };
    api.vodLibraryAction.mockResolvedValue({
      ...preview,
      count: 59,
      protected_count: 20,
    });
    renderDialog({ selection: all, items: [], selectionCount: 59 });
    await screen.findByText('Old title');
    expect(
      screen.getByRole('dialog', { name: 'Edit selected titles (59)' })
    ).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole('button', { name: 'Cleanup', exact: true })
    );
    expect(
      screen.getByText(/Process 20 protected titles once/)
    ).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole('button', { name: 'Confirm', exact: true })
    );
    await waitFor(() =>
      expect(api.vodLibraryAction).toHaveBeenCalledWith('bulk', {
        ...all,
        operation: 'cleanup',
        include_protected: true,
        ...rules,
      })
    );
  });
  it('offers missing-ID search per enrichment run without changing Settings', async () => {
    renderDialog();
    await screen.findByText('EN Film (2020)');
    fireEvent.click(
      screen.getByRole('button', { name: 'Enrich', exact: true })
    );
    const search = screen.getByRole('checkbox', {
      name: 'Search TMDB for titles without an ID',
    });
    expect(search).not.toBeChecked();
    fireEvent.click(search);
    fireEvent.click(
      screen.getByRole('button', { name: 'Confirm', exact: true })
    );
    await waitFor(() =>
      expect(api.vodLibraryAction).toHaveBeenCalledWith('bulk', {
        ...selection,
        operation: 'enrich',
        include_protected: false,
        ...rules,
        search_missing: true,
      })
    );
  });
  it('paginates the whole selection, keeping protected entries visible', async () => {
    const items = Array.from({ length: 61 }, (_, index) => ({
      ...item,
      content_id: index + 1,
      provider_name: `Provider ${index + 1}`,
    }));
    const selection = {
      items: items.map((row) => ({
        content_type: row.content_type,
        id: row.content_id,
      })),
    };
    api.vodLibraryAction.mockImplementation(async (_, body) => ({
      count: 61,
      page: body.page,
      results: [
        { ...preview.results[0], id: body.page === 1 ? 1 : 26, locked: true },
      ],
    }));
    renderDialog({ items, selection });
    await screen.findByText('Provider 1');
    expect(
      screen.getByRole('dialog', { name: 'Edit selected titles (61)' })
    ).toBeInTheDocument();
    expect(screen.getByText('1–25 of 61')).toBeInTheDocument();
    expect(screen.getByLabelText('Metadata locked')).toBeInTheDocument();
    expect(screen.queryByText(/Showing up to/)).not.toBeInTheDocument();
    fireEvent.click(
      screen.getByRole('button', { name: 'Next page', exact: true })
    );
    await screen.findByText('Provider 26');
    expect(api.vodLibraryAction).toHaveBeenLastCalledWith('cleanup-preview', {
      ...selection,
      page: 2,
      page_size: 25,
      ...rules,
    });
    expect(screen.getByText('26–50 of 61')).toBeInTheDocument();
  });
});
