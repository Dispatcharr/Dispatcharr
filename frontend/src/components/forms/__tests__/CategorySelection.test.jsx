import { StrictMode, useState } from 'react';
import { MantineProvider } from '@mantine/core';
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import LiveGroupFilter from '../LiveGroupFilter';
import VODCategoryFilter from '../VODCategoryFilter';
import editorClasses from '../AccountEditor.module.css';

const groups = Array.from({ length: 40 }, (_, index) => ({
  channel_group: index + 1,
  name: `Category ${String(index + 1).padStart(2, '0')}`,
  enabled: false,
  auto_channel_sync: false,
  custom_properties: {},
}));
vi.mock('../../../store/channels', () => ({
  default: (selector) =>
    selector({
      channelGroups: Object.fromEntries(
        groups.map((group) => [group.channel_group, group])
      ),
    }),
}));
vi.mock('../../../store/streamProfiles', () => ({
  default: (selector) => selector({ profiles: [], fetchProfiles: vi.fn() }),
}));
vi.mock('../../../store/useVODStore', () => ({
  default: (selector) => selector({ categories: {} }),
}));
vi.mock('../../../hooks/useSmartLogos', () => ({
  useChannelLogoSelection: () => ({
    logos: {},
    ensureLogosLoaded: vi.fn(),
    isLoading: false,
  }),
}));
vi.mock('../../../utils/forms/LiveGroupFilterUtils.js', async (original) => ({
  ...(await original()),
  getEPGs: vi.fn().mockResolvedValue([]),
  getChannelsInRange: vi.fn().mockResolvedValue({ occupants: [] }),
}));
vi.mock('../M3UGroupContentPreview.jsx', () => ({ default: () => null }));
vi.mock('../M3UFilters.jsx', () => ({ default: () => null }));
vi.mock('../AutoSyncBasic.jsx', () => ({ default: () => null }));
vi.mock('../AutoSyncAdvanced.jsx', () => ({ default: () => null }));

function Categories({
  vod = false,
  previewAvailableIds,
  type = 'movie',
  initialGroups = groups,
}) {
  const [paginationContainer, setPaginationContainer] = useState(null);
  const [rows, setRows] = useState(
    vod
      ? initialGroups.map((group) => ({ ...group, id: group.channel_group }))
      : []
  );
  const playlist = { id: 1, channel_groups: initialGroups };
  const content = vod ? (
    <VODCategoryFilter
      playlist={playlist}
      categoryStates={rows}
      setCategoryStates={setRows}
      type={type}
      paginationContainer={paginationContainer}
      previewAvailableIds={previewAvailableIds}
      previewUnavailableHint="Enable this category and refresh to load content."
    />
  ) : (
    <LiveGroupFilter
      playlist={playlist}
      groupStates={rows}
      setGroupStates={setRows}
      paginationContainer={paginationContainer}
      previewAvailableIds={previewAvailableIds}
      previewUnavailableHint="Enable this category and refresh to load content."
    />
  );
  return (
    <>
      {content}
      <output data-testid="category-draft">{JSON.stringify(rows)}</output>
      <footer aria-label="Category actions" ref={setPaginationContainer} />
    </>
  );
}

describe('Category selection with Mantine controls', () => {
  it.each(['live', 'movie', 'series'])(
    'quickly toggles only the %s draft status and preserves settings and bulk selection',
    async (scope) => {
      const original = {
        ...groups[0],
        enabled: true,
        original_enabled: true,
        ignored: false,
        original_ignored: false,
        auto_channel_sync: true,
        auto_sync_channel_start: 100,
        auto_sync_channel_end: 199,
        custom_properties: { audio_languages: ['ger'], provider_field: 'keep' },
      };
      render(
        <MantineProvider env="test">
          <Categories
            vod={scope !== 'live'}
            type={scope}
            initialGroups={[original, groups[1]]}
          />
        </MantineProvider>
      );
      const selection = await screen.findByRole('checkbox', {
        name: 'Select Category 01',
      });
      fireEvent.click(selection);
      fireEvent.click(
        screen.getByRole('button', { name: 'Disable category Category 01' })
      );
      expect(
        screen.getByRole('button', { name: 'Enable category Category 01' })
      ).toHaveTextContent('Disabled');
      expect(selection).toBeChecked();
      expect(
        screen.getByRole('button', { name: 'Edit settings (1)' })
      ).toBeEnabled();
      const [disabled, untouched] = JSON.parse(
        screen.getByTestId('category-draft').textContent
      );
      expect(disabled).toMatchObject({ ...original, enabled: false });
      expect(untouched.enabled).toBe(false);
      const row = selection.closest('tr');
      expect(
        within(row).getByRole('button', {
          name:
            scope === 'live'
              ? 'Configure category'
              : 'Edit defaults for Category 01',
        })
      ).toBeDisabled();
      fireEvent.click(
        screen.getByRole('button', { name: 'Enable category Category 01' })
      );
      expect(
        screen.getByRole('button', { name: 'Disable category Category 01' })
      ).toHaveTextContent('Enabled');
      expect(
        JSON.parse(screen.getByTestId('category-draft').textContent)[0]
      ).toMatchObject(original);
      expect(selection).toBeChecked();
    }
  );

  it.each(['live', 'movie', 'series'])(
    'does not offer the quick toggle for ignored %s categories',
    async (scope) => {
      const ignored = { ...groups[0], ignored: true, original_ignored: true };
      render(
        <MantineProvider env="test">
          <Categories
            vod={scope !== 'live'}
            type={scope}
            initialGroups={[ignored]}
          />
        </MantineProvider>
      );
      fireEvent.click(
        screen.getByRole('button', { name: 'Filter category status' })
      );
      fireEvent.click(
        screen.getByRole('checkbox', { name: 'Ignored', exact: true })
      );
      fireEvent.keyDown(
        screen.getByRole('checkbox', { name: 'Ignored', exact: true }),
        { key: 'Escape' }
      );
      const row = (
        await screen.findByRole('checkbox', { name: 'Select Category 01' })
      ).closest('tr');
      expect(within(row).getByText('Ignored')).toBeInTheDocument();
      expect(
        within(row).queryByRole('button', {
          name: /^(Enable|Disable) category/,
        })
      ).not.toBeInTheDocument();
      fireEvent.click(within(row).getByText('Ignored'));
      expect(
        JSON.parse(screen.getByTestId('category-draft').textContent)[0]
      ).toMatchObject(ignored);
    }
  );

  it.each([false, true])(
    'frames the scrolling viewport instead of the long table (VOD=%s)',
    async (vod) => {
      render(
        <MantineProvider>
          <Categories vod={vod} />
        </MantineProvider>
      );
      await screen.findByRole('checkbox', { name: 'Select Category 01' });
      const table = screen.getByRole('table');
      expect(table).toHaveClass(editorClasses.categoryTable);
      expect(table).not.toHaveAttribute('data-with-table-border');
      expect(
        table.closest(`.${editorClasses.categoryTableFrame}`)
      ).toBeInTheDocument();
    }
  );
  it.each([false, true])(
    'groups bulk settings and omits numbering (VOD=%s)',
    async (vod) => {
      render(
        <MantineProvider>
          <Categories vod={vod} />
        </MantineProvider>
      );
      fireEvent.click(
        await screen.findByRole('checkbox', { name: 'Select Category 01' })
      );
      fireEvent.click(
        screen.getByRole('button', { name: 'Edit settings (1)' })
      );
      const dialog = await screen.findByRole('dialog', {
        name: 'Edit settings for 1 category',
      });
      expect(
        within(dialog).getByRole('group', { name: 'Category status settings' })
      ).toContainElement(within(dialog).getByLabelText('Status'));
      expect(
        within(
          within(dialog).getByRole('group', {
            name: 'Category status settings',
          })
        ).getByText('General')
      ).toBeInTheDocument();
      expect(
        within(dialog).queryByText(/Keep unchanged preserves/)
      ).not.toBeInTheDocument();
      expect(
        within(dialog).queryByLabelText('Numbering mode')
      ).not.toBeInTheDocument();
      expect(
        within(dialog).queryByText(/Numbering and channel ranges/)
      ).not.toBeInTheDocument();
      const content = within(dialog).getByRole('group', {
        name: vod ? 'Category content settings' : 'Channel sync settings',
      });
      expect(
        within(content).getByText(vod ? 'Metadata' : 'Channel sync')
      ).toBeInTheDocument();
      expect(content).not.toContainElement(
        within(dialog).getByRole('button', { name: 'Apply to selected' })
      );
      fireEvent.click(
        within(dialog).getByRole('button', { name: 'Apply to selected' })
      );
      expect(
        screen.getByRole('checkbox', { name: 'Select Category 01' })
      ).toBeChecked();
    }
  );
  it.each([false, true])(
    'disables preview only for categories without imported content (VOD=%s)',
    async (vod) => {
      render(
        <MantineProvider>
          <Categories vod={vod} previewAvailableIds={new Set([1])} />
        </MantineProvider>
      );
      await screen.findByRole('checkbox', { name: 'Select Category 01' });
      const imported = screen
        .getByRole('checkbox', { name: 'Select Category 01' })
        .closest('tr');
      const empty = screen
        .getByRole('checkbox', { name: 'Select Category 02' })
        .closest('tr');
      expect(
        within(imported).getByRole('button', { name: 'Preview category' })
      ).toBeEnabled();
      expect(
        within(empty).getByRole('button', { name: 'Preview category' })
      ).toBeDisabled();
    }
  );
  it.each([false, true])(
    'selects matching Live/VOD rows across pages (VOD=%s)',
    async (vod) => {
      render(
        <StrictMode>
          <MantineProvider env="test">
            <Categories vod={vod} />
          </MantineProvider>
        </StrictMode>
      );
      await waitFor(() =>
        expect(
          screen.getByRole('checkbox', { name: 'Select Category 01' })
        ).toBeInTheDocument()
      );
      fireEvent.click(
        screen.getByRole('checkbox', { name: 'Select visible categories' })
      );
      await waitFor(() =>
        expect(
          screen.getByRole('button', { name: 'Edit settings (40)' })
        ).toBeEnabled()
      );
      expect(
        screen.getByRole('checkbox', { name: 'Select Category 01' })
      ).toBeChecked();
      expect(
        screen
          .getByRole('checkbox', { name: 'Select Category 01' })
          .closest('tr')
      ).toHaveAttribute('data-selected', 'true');
      expect(
        screen.queryByRole('button', { name: 'Category 01' })
      ).not.toBeInTheDocument();
      fireEvent.click(screen.getByRole('button', { name: /^Edit settings/ }));
      const editor = screen.getByRole('dialog', { name: /^Edit settings/ });
      fireEvent.click(within(editor).getByRole('textbox', { name: 'Status' }));
      fireEvent.click(
        screen.getByRole('option', { name: 'Enabled', exact: true })
      );
      fireEvent.click(
        within(editor).getByRole('button', { name: 'Apply to selected' })
      );
      expect(
        screen.getByRole('columnheader', { name: 'Status' })
      ).toBeInTheDocument();
      expect(
        within(screen.getByRole('table')).getAllByText('Enabled')
      ).toHaveLength(25);
      expect(
        screen.getByRole('contentinfo', { name: 'Category actions' })
      ).toContainElement(screen.getByRole('button', { name: '2' }));
      fireEvent.click(screen.getByRole('button', { name: '2' }));
      expect(
        screen.getByRole('checkbox', { name: 'Select Category 26' })
      ).toBeChecked();
      expect(
        within(screen.getByRole('table')).getAllByText('Enabled')
      ).toHaveLength(15);
    },
    15000
  );
});
