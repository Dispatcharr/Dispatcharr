import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import { MantineProvider } from '@mantine/core';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import M3UAccountEPG from '../M3UAccountEPG.jsx';
import API from '../../../api.js';
import { showNotification } from '../../../utils/notificationUtils.js';
import summaryClasses from '../M3UAccountSummary.module.css';

const mocks = vi.hoisted(() => ({ fetchEPGs: vi.fn(), epgs: {} }));
vi.mock('../../../api.js', () => ({
  default: { getM3UEPG: vi.fn(), createM3UEPG: vi.fn(), deleteEPG: vi.fn() },
}));
vi.mock('../EPG.jsx', () => ({
  default: ({ epg, onClose }) => (
    <div role="dialog" aria-label="EPG editor">
      <span>{epg.url}</span>
      <button onClick={onClose}>Close guide editor</button>
    </div>
  ),
}));
vi.mock('../../../store/epgs', () => ({
  default: Object.assign((selector) => selector(mocks), {
    getState: () => mocks,
  }),
}));
vi.mock('../../../utils/notificationUtils.js', () => ({
  showNotification: vi.fn(),
  hideNotification: vi.fn(),
}));

const account = { id: 7, account_type: 'XC' };
const show = (props) =>
  render(
    <MemoryRouter>
      <MantineProvider>
        <M3UAccountEPG account={account} {...props} />
      </MantineProvider>
    </MemoryRouter>
  );

describe('EPG in the account editor', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    API.getM3UEPG.mockResolvedValue({ source: null, can_create: true });
    API.createM3UEPG.mockReset();
    API.deleteEPG.mockReset();
    mocks.fetchEPGs.mockResolvedValue(undefined);
    mocks.epgs = {};
  });

  it('wraps the compact matching source and its actions in the shared section', async () => {
    API.getM3UEPG.mockResolvedValue({
      source: {
        id: 9,
        name: 'Matching guide',
        source_type: 'xmltv',
        status: 'success',
      },
    });
    show();
    const card = await screen.findByRole('article', {
      name: 'EPG source Matching guide',
    });
    const section = screen.getByRole('region', { name: 'EPG source' });
    expect(section).toContainElement(card);
    expect(section.style.getPropertyValue('--paper-radius')).toBe(
      'var(--mantine-radius-md)'
    );
    expect(card.style.getPropertyValue('--paper-radius')).toBe(
      'var(--mantine-radius-md)'
    );
    expect(
      within(card).getByRole('button', { name: 'Edit Matching guide' })
    ).toBeEnabled();
    expect(
      within(card).getByRole('button', { name: 'Delete Matching guide' })
    ).toBeEnabled();
  });

  it('loads complete saved details before editing and rechecks the match when closed', async () => {
    const guide = {
      id: 9,
      name: 'Matching guide',
      source_type: 'xmltv',
      status: 'success',
    };
    API.getM3UEPG.mockResolvedValue({ source: guide });
    mocks.fetchEPGs.mockImplementationOnce(async () => {
      mocks.epgs = {
        9: { ...guide, url: 'https://example.invalid/guide.xml' },
      };
    });
    const onOverlayChange = vi.fn();
    show({ onOverlayChange });
    fireEvent.click(
      await screen.findByRole('button', { name: 'Edit Matching guide' })
    );
    const editor = await screen.findByRole('dialog', { name: 'EPG editor' });
    expect(editor).toHaveTextContent('https://example.invalid/guide.xml');
    expect(mocks.fetchEPGs).toHaveBeenCalledOnce();
    await waitFor(() => expect(onOverlayChange).toHaveBeenLastCalledWith(true));
    fireEvent.click(screen.getByRole('button', { name: 'Close guide editor' }));
    await waitFor(() => expect(API.getM3UEPG).toHaveBeenCalledTimes(2));
    expect(onOverlayChange).toHaveBeenLastCalledWith(false);
  });

  it('does not open an editor with incomplete source details', async () => {
    API.getM3UEPG.mockResolvedValue({
      source: { id: 9, name: 'Matching guide' },
    });
    show();
    fireEvent.click(
      await screen.findByRole('button', { name: 'Edit Matching guide' })
    );
    await waitFor(() =>
      expect(showNotification).toHaveBeenCalledWith(
        expect.objectContaining({
          title: 'EPG source could not be opened',
          color: 'red',
        })
      )
    );
    expect(
      screen.queryByRole('dialog', { name: 'EPG editor' })
    ).not.toBeInTheDocument();
  });

  it('requires confirmation and keeps the source when deletion is cancelled', async () => {
    API.getM3UEPG.mockResolvedValue({
      source: { id: 9, name: 'Matching guide' },
    });
    const onOverlayChange = vi.fn();
    show({ onOverlayChange });
    fireEvent.click(
      await screen.findByRole('button', { name: 'Delete Matching guide' })
    );
    expect(
      await screen.findByRole('dialog', { name: 'Confirm EPG Source Deletion' })
    ).toHaveTextContent('all accounts using this source');
    expect(API.deleteEPG).not.toHaveBeenCalled();
    expect(onOverlayChange).toHaveBeenLastCalledWith(true);
    fireEvent.click(
      screen.getByRole('button', { name: 'Cancel', exact: true })
    );
    expect(onOverlayChange).toHaveBeenLastCalledWith(false);
    expect(API.deleteEPG).not.toHaveBeenCalled();
    expect(screen.getByRole('article')).toHaveTextContent('Matching guide');
  });

  it('rechecks the matching source after a confirmed deletion', async () => {
    API.getM3UEPG
      .mockResolvedValueOnce({ source: { id: 9, name: 'Matching guide' } })
      .mockResolvedValue({ source: null, can_create: true });
    API.deleteEPG.mockResolvedValue(undefined);
    const onBusyChange = vi.fn();
    show({ onBusyChange });
    fireEvent.click(
      await screen.findByRole('button', { name: 'Delete Matching guide' })
    );
    fireEvent.click(
      await screen.findByRole('button', { name: 'Delete', exact: true })
    );
    await screen.findByRole('button', { name: 'Create EPG' });
    expect(API.deleteEPG).toHaveBeenCalledExactlyOnceWith(9);
    expect(onBusyChange).toHaveBeenCalledWith(true);
    expect(onBusyChange).toHaveBeenLastCalledWith(false);
    expect(screen.queryByRole('article')).not.toBeInTheDocument();
  });

  it('does not optimistically remove a source when the shared API reports a failed deletion', async () => {
    API.getM3UEPG.mockResolvedValue({
      source: { id: 9, name: 'Matching guide' },
    });
    API.deleteEPG.mockResolvedValue(undefined);
    show();
    fireEvent.click(
      await screen.findByRole('button', { name: 'Delete Matching guide' })
    );
    fireEvent.click(
      await screen.findByRole('button', { name: 'Delete', exact: true })
    );
    await waitFor(() => expect(API.getM3UEPG).toHaveBeenCalledTimes(2));
    expect(await screen.findByRole('article')).toHaveTextContent(
      'Matching guide'
    );
    expect(
      screen.queryByRole('button', { name: 'Create EPG' })
    ).not.toBeInTheDocument();
  });
  it('does not request a guide from an inactive tab', () => {
    show({ active: false });
    expect(API.getM3UEPG).not.toHaveBeenCalled();
  });
  it('offers late creation without restarting account setup', async () => {
    show();
    await screen.findByText('No matching EPG source configured.');
    API.createM3UEPG.mockResolvedValue({
      source: { id: 9, name: 'Example guide', is_active: true },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Create EPG' }));
    await screen.findByText('Example guide');
    expect(API.createM3UEPG).toHaveBeenCalledExactlyOnceWith(7);
    expect(mocks.fetchEPGs).toHaveBeenCalledOnce();
    expect(
      screen.queryByRole('button', { name: 'Create EPG' })
    ).not.toBeInTheDocument();
  });

  it('centers late creation using the same action layout as category selection', async () => {
    show();
    const button = await screen.findByRole('button', { name: 'Create EPG' });
    const actions = screen.getByRole('region', { name: 'EPG source actions' });
    expect(actions).toContainElement(button);
    expect(actions).toHaveClass(summaryClasses.selectionActions);
    expect(screen.getByRole('region', { name: 'EPG source' })).toContainElement(
      actions
    );
  });

  it.each([false, true])(
    'shows saved EPG channel totals, including zero, in setup: %s',
    async (isInitialSetup) => {
      const guide = {
        id: 9,
        name: 'Counted guide',
        is_active: true,
        epg_data_count: 42,
      };
      API.getM3UEPG.mockResolvedValue({ source: guide, can_create: false });
      const view = show({ isInitialSetup });
      await screen.findByText('Counted guide');
      expect(screen.getByText('EPG channels').parentElement).toHaveTextContent(
        '42'
      );
      mocks.epgs = { 9: { ...guide, epg_data_count: 0 } };
      view.rerender(
        <MemoryRouter>
          <MantineProvider>
            <M3UAccountEPG account={account} isInitialSetup={isInitialSetup} />
          </MantineProvider>
        </MemoryRouter>
      );
      expect(screen.getByText('EPG channels').parentElement).toHaveTextContent(
        '0'
      );
      expect(API.getM3UEPG).toHaveBeenCalledOnce();
    }
  );
  it('shows an existing matching guide instead of another create action', async () => {
    API.getM3UEPG.mockResolvedValue({
      source: { id: 9, name: 'Existing guide', is_active: false },
    });
    show();
    await screen.findByText('Existing guide');
    expect(screen.getByText('Disabled')).toBeInTheDocument();
    expect(
      screen.queryByRole('link', { name: 'Manage EPG sources' })
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: 'Create EPG' })
    ).not.toBeInTheDocument();
  });
  it.each([
    null,
    { id: 9, name: 'Setup guide', is_active: true, status: 'idle' },
  ])(
    'keeps initial setup inside the dialog, with or without a source (%s)',
    async (source) => {
      API.getM3UEPG.mockResolvedValue({ source, can_create: !source });
      show({ isInitialSetup: true });
      await screen.findByText(
        source ? source.name : 'No matching EPG source configured.'
      );
      expect(screen.queryByRole('link')).not.toBeInTheDocument();
      expect(screen.queryByText('Manage EPG sources')).not.toBeInTheDocument();
    }
  );
  it('keeps failed late creation retryable', async () => {
    API.createM3UEPG.mockRejectedValueOnce(new Error('Name already exists'));
    show();
    fireEvent.click(await screen.findByRole('button', { name: 'Create EPG' }));
    await waitFor(() =>
      expect(showNotification).toHaveBeenCalledWith(
        expect.objectContaining({ color: 'red', autoClose: false })
      )
    );
    expect(screen.getByRole('button', { name: 'Create EPG' })).toBeEnabled();
  });
  it('does not create twice while a request is in flight', async () => {
    let finish;
    API.createM3UEPG.mockReturnValue(
      new Promise((resolve) => {
        finish = resolve;
      })
    );
    show();
    const button = await screen.findByRole('button', { name: 'Create EPG' });
    fireEvent.click(button);
    fireEvent.click(button);
    expect(API.createM3UEPG).toHaveBeenCalledOnce();
    finish({ source: { id: 9, name: 'New guide', is_active: true } });
    await screen.findByText('New guide');
  });
  it('does not render EPG setup for URL/file accounts', () => {
    show({ account: { ...account, account_type: 'STD' } });
    expect(screen.queryByText('EPG source')).not.toBeInTheDocument();
    expect(API.getM3UEPG).not.toHaveBeenCalled();
    expect(
      screen.queryByRole('button', { name: 'Create EPG' })
    ).not.toBeInTheDocument();
  });

  it('only offers creation for a complete saved provider connection', async () => {
    API.getM3UEPG.mockResolvedValue({ source: null, can_create: false });
    show();
    await screen.findByText(/Complete and save the account connection/);
    expect(
      screen.queryByRole('button', { name: 'Create EPG' })
    ).not.toBeInTheDocument();
  });

  it('shows a compact source card with type, status and dimmed last refresh', async () => {
    API.getM3UEPG.mockResolvedValue({
      source: {
        id: 9,
        name: 'Example XMLTV',
        is_active: true,
        status: 'success',
        source_type: 'xmltv',
        updated_at: null,
      },
      can_create: false,
    });
    show();
    const card = await screen.findByRole('article', {
      name: 'EPG source Example XMLTV',
    });
    expect(card).toHaveTextContent('XMLTV');
    expect(card).toHaveTextContent('Success');
    expect(card).toHaveTextContent('Last refresh');
    expect(screen.getByText('Never')).toHaveAttribute('data-size', 'xs');
    expect(screen.queryByRole('radio')).not.toBeInTheDocument();
  });

  it('prefers fresh detail data, then follows later store updates', async () => {
    const guide = {
      id: 9,
      name: 'Current guide',
      is_active: true,
      status: 'success',
    };
    mocks.epgs = {
      9: { ...guide, status: 'idle', last_message: 'Outdated source message' },
    };
    API.getM3UEPG.mockResolvedValue({ source: guide, can_create: false });
    const view = show();
    await screen.findByText('Success');
    expect(
      screen.queryByText('Outdated source message')
    ).not.toBeInTheDocument();
    mocks.epgs = { 9: { ...guide, status: 'fetching' } };
    view.rerender(
      <MemoryRouter>
        <MantineProvider>
          <M3UAccountEPG account={account} />
        </MantineProvider>
      </MemoryRouter>
    );
    expect(screen.getByText('Fetching')).toBeInTheDocument();
  });

  it('keeps unrelated sources hidden before and after creating the matching guide', async () => {
    const alternate = {
      id: 12,
      name: 'Unrelated guide',
      source_type: 'xmltv',
      is_active: true,
    };
    API.getM3UEPG.mockResolvedValue({
      source: null,
      can_create: true,
      other_sources: [alternate],
    });
    const onNext = vi.fn();
    show({ isInitialSetup: true, onNext });
    await screen.findByText('No matching EPG source configured.');
    expect(screen.queryByText('Unrelated guide')).not.toBeInTheDocument();
    expect(
      screen.queryByRole('region', { name: 'Other configured EPG sources' })
    ).not.toBeInTheDocument();
    API.createM3UEPG.mockResolvedValue({
      source: {
        id: 9,
        name: 'Account guide',
        source_type: 'xmltv',
        is_active: true,
      },
      can_create: false,
      other_sources: [alternate],
    });
    fireEvent.click(screen.getByRole('button', { name: 'Create EPG' }));
    await screen.findByText('Account guide');
    expect(screen.queryByText('Unrelated guide')).not.toBeInTheDocument();
    expect(onNext).toHaveBeenCalledOnce();
  });

  it('omits the entire alternative-source section when there are none', async () => {
    show({ isInitialSetup: true });
    await screen.findByText('No matching EPG source configured.');
    expect(
      screen.queryByRole('region', { name: 'Other configured EPG sources' })
    ).not.toBeInTheDocument();
  });

  it('keeps a created guide when advancing fails and retries without creating twice', async () => {
    const onNext = vi.fn().mockResolvedValue(false);
    API.createM3UEPG.mockResolvedValue({
      source: { id: 9, name: 'Saved guide', is_active: true },
      can_create: false,
    });
    show({ isInitialSetup: true, onNext });
    fireEvent.click(await screen.findByRole('button', { name: 'Create EPG' }));
    await screen.findByText('Saved guide');
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Next' })).toBeEnabled()
    );
    fireEvent.click(screen.getByRole('button', { name: 'Next' }));
    expect(onNext).toHaveBeenCalledTimes(2);
    expect(API.createM3UEPG).toHaveBeenCalledOnce();
  });

  it.each([false, true])(
    'only shows the account matching source (setup: %s)',
    async (isInitialSetup) => {
      API.getM3UEPG.mockResolvedValue({
        source: {
          id: 9,
          name: 'Matching guide',
          source_type: 'xmltv',
          is_active: true,
          status: 'success',
        },
        can_create: false,
        other_sources: [
          {
            id: 10,
            name: 'Unrelated guide',
            source_type: 'xmltv',
            is_active: true,
            status: 'idle',
          },
        ],
      });
      show({ isInitialSetup });
      const matching = await screen.findByRole('article', {
        name: 'EPG source Matching guide',
      });
      expect(matching).toHaveClass(summaryClasses.card);
      expect(screen.getAllByRole('article')).toHaveLength(1);
      expect(screen.queryByText('Unrelated guide')).not.toBeInTheDocument();
      expect(
        screen.queryByRole('region', { name: 'Other configured EPG sources' })
      ).not.toBeInTheDocument();
      expect(screen.getAllByText('Matching EPG source')).toHaveLength(1);
      expect(screen.queryByRole('link')).not.toBeInTheDocument();
      expect(API.createM3UEPG).not.toHaveBeenCalled();
    }
  );

  it('does not leave an empty alternative column in the normal editor', async () => {
    show();
    await screen.findByText('No matching EPG source configured.');
    expect(
      screen.queryByRole('region', { name: 'Other configured EPG sources' })
    ).not.toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'EPG source' })).toHaveClass(
      summaryClasses.card
    );
  });
});
