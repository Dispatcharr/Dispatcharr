import { useCallback, useState } from 'react';
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import { MantineProvider, Modal } from '@mantine/core';
import { describe, expect, it, vi } from 'vitest';
import VODCategoryFilter from '../VODCategoryFilter';
import MEDIA_LANGUAGE_OPTIONS from '../../../../../apps/vod/media_languages.json';

vi.mock('../../../store/useVODStore', () => ({
  default: (select) => select({ categories: {} }),
}));

function CategoryHarness({
  type,
  onChange,
  properties,
  count = 4,
  onClose = () => {},
}) {
  const [categories, setCategories] = useState(() =>
    Array.from({ length: count }, (_, index) => ({
      id: index + 1,
      name: `Synthetic category ${index}`,
      enabled: true,
      custom_properties: index === 0 ? properties : {},
    }))
  );
  const updateCategories = useCallback(
    (next) => {
      onChange(next);
      setCategories(next);
    },
    [onChange]
  );
  return (
    <MantineProvider env="test">
      <Modal.Stack>
        <Modal
          opened
          onClose={onClose}
          stackId="m3u-category-selection"
          title="Category selection"
        >
          <VODCategoryFilter
            playlist={{ id: 1 }}
            categoryStates={categories}
            setCategoryStates={updateCategories}
            type={type}
            autoEnableNewGroups={false}
            setAutoEnableNewGroups={vi.fn()}
          />
        </Modal>
      </Modal.Stack>
    </MantineProvider>
  );
}

async function renderCategories(
  type = 'movie',
  properties = { audio_languages: ['gmh'], provider_field: 'keep' }
) {
  const onChange = vi.fn();
  await act(async () => {
    render(
      <CategoryHarness
        type={type}
        onChange={onChange}
        properties={properties}
      />
    );
  });
  return onChange;
}

async function openEditor(index = 0) {
  fireEvent.click(
    screen.getByRole('button', {
      name: `Edit defaults for Synthetic category ${index}`,
    })
  );
  return screen.findByRole('dialog', {
    name: `Category defaults · Synthetic category ${index}`,
  });
}

async function openPicker(field) {
  fireEvent.click(screen.getByRole('button', { name: `Choose ${field}` }));
  return screen.findByRole('dialog', { name: `Select ${field}` });
}

async function applyPicker(dialog) {
  expect(
    within(dialog).queryByRole('button', { name: 'Apply selection' })
  ).not.toBeInTheDocument();
  fireEvent.keyDown(dialog, { key: 'Escape' });
  await waitFor(() => expect(dialog).not.toBeInTheDocument());
}

const setSelectedStatus = (status) => {
  fireEvent.click(screen.getByRole('button', { name: /^Edit settings/ }));
  const editor = screen.getByRole('dialog', { name: /^Edit settings/ });
  fireEvent.click(within(editor).getByRole('textbox', { name: 'Status' }));
  fireEvent.click(screen.getByRole('option', { name: status, exact: true }));
  fireEvent.click(
    within(editor).getByRole('button', { name: 'Apply to selected' })
  );
};

describe('VOD category metadata with real Mantine controls', () => {
  it.each(['movie', 'series'])(
    'shows Clear as a text link only when %s categories are selected',
    async (type) => {
      const onChange = await renderCategories(type);
      expect(
        screen.queryByRole('button', { name: 'Clear', exact: true })
      ).not.toBeInTheDocument();
      fireEvent.click(
        screen.getByRole('checkbox', { name: 'Select Synthetic category 0' })
      );
      const clear = screen.getByRole('button', { name: 'Clear', exact: true });
      expect(clear).toHaveClass('mantine-Anchor-root');
      expect(
        clear.compareDocumentPosition(
          screen.getByRole('button', { name: 'Edit settings (1)' })
        ) & Node.DOCUMENT_POSITION_FOLLOWING
      ).toBeTruthy();
      fireEvent.click(clear);
      expect(
        screen.queryByRole('button', { name: 'Clear', exact: true })
      ).not.toBeInTheDocument();
      expect(
        screen.getByRole('button', { name: 'Edit settings (0)' })
      ).toBeDisabled();
      expect(onChange).not.toHaveBeenCalled();
    }
  );
  it.each(['Ignored', 'Reset filters'])(
    'closes only the status filter with Escape from %s',
    async (control) => {
      const onClose = vi.fn();
      await act(async () => {
        render(
          <CategoryHarness type="movie" onChange={vi.fn()} onClose={onClose} />
        );
      });
      fireEvent.click(
        screen.getByRole('button', { name: 'Filter category status' })
      );
      fireEvent.keyDown(
        screen.getByRole(control === 'Ignored' ? 'checkbox' : 'button', {
          name: control,
          exact: true,
        }),
        { key: 'Escape' }
      );
      await waitFor(() =>
        expect(screen.queryByText('Show categories')).not.toBeInTheDocument()
      );
      expect(onClose).not.toHaveBeenCalled();
      expect(
        screen.getByRole('dialog', { name: 'Category selection' })
      ).toBeInTheDocument();
    }
  );

  it.each(['movie', 'series'])(
    'can hide, reveal and restore ignored %s categories without losing metadata',
    async (type) => {
      await renderCategories(type, {
        audio_languages: ['ger'],
        video_features: ['hdr'],
      });
      fireEvent.click(
        screen.getByRole('checkbox', { name: 'Select Synthetic category 0' })
      );
      setSelectedStatus('Ignored');
      expect(
        screen.queryByText('Synthetic category 0', { exact: true })
      ).not.toBeInTheDocument();
      expect(
        screen.getByRole('button', { name: 'Filter category status' })
      ).toHaveAttribute('data-hidden-count', '1');
      expect(
        screen.getByRole('button', { name: 'Filter category status' })
      ).toHaveTextContent('');
      fireEvent.click(
        screen.getByRole('button', { name: 'Filter category status' })
      );
      expect(
        screen.getByRole('checkbox', { name: 'Ignored', exact: true })
      ).not.toBeChecked();
      fireEvent.click(
        screen.getByRole('checkbox', { name: 'Ignored', exact: true })
      );
      expect(
        screen.getByText('Synthetic category 0').closest('tr')
      ).toHaveTextContent('Ignored');
      fireEvent.keyDown(
        screen.getByRole('checkbox', { name: 'Ignored', exact: true }),
        { key: 'Escape' }
      );
      setSelectedStatus('Enabled');
      const restored = screen.getByText('Synthetic category 0').closest('tr');
      expect(restored).toHaveTextContent('Enabled');
      expect(restored).toHaveTextContent('ger');
      expect(restored).toHaveTextContent('HDR');
      expect(
        screen.queryByRole('button', { name: 'Enable selected' })
      ).not.toBeInTheDocument();
      expect(
        screen.queryByRole('button', { name: 'Disable selected' })
      ).not.toBeInTheDocument();
      expect(
        screen
          .getByRole('button', { name: 'Clear', exact: true })
          .compareDocumentPosition(
            screen.getByRole('button', { name: 'Edit settings (1)' })
          ) & Node.DOCUMENT_POSITION_FOLLOWING
      ).toBeTruthy();
    }
  );

  it('explains empty filtered views and resets search and status filters', async () => {
    await renderCategories();
    fireEvent.change(screen.getByPlaceholderText('Filter categories...'), {
      target: { value: 'no such category' },
    });
    expect(
      screen.getByText('No categories match the current filters.')
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Reset filters' }));
    expect(screen.getByText('Synthetic category 0')).toBeInTheDocument();
  });
  it('centers the category actions and keeps disabled entries in the All view', async () => {
    await renderCategories();
    expect(screen.getByRole('columnheader', { name: 'Actions' })).toHaveStyle({
      textAlign: 'center',
    });
    const action = screen.getByRole('button', {
      name: 'Edit defaults for Synthetic category 0',
    });
    expect(action.closest('td').firstElementChild).toHaveStyle({
      justifyContent: 'center',
    });
    fireEvent.click(
      screen.getByRole('checkbox', { name: 'Select Synthetic category 0' })
    );
    fireEvent.click(screen.getByRole('button', { name: 'Edit settings (1)' }));
    const editor = await screen.findByRole('dialog', {
      name: 'Edit settings for 1 category',
    });
    fireEvent.click(within(editor).getByRole('textbox', { name: 'Status' }));
    fireEvent.click(
      screen.getByRole('option', { name: 'Disabled', exact: true })
    );
    fireEvent.click(
      within(editor).getByRole('button', { name: 'Apply to selected' })
    );
    expect(screen.getByText('Synthetic category 0')).toBeInTheDocument();
    expect(
      screen.getByText('Synthetic category 0').closest('tr')
    ).toHaveTextContent('Disabled');
  });
  it('paginates a large inventory without mounting per-row metadata controls', async () => {
    render(
      <CategoryHarness
        type="movie"
        onChange={vi.fn()}
        properties={{}}
        count={1500}
      />
    );
    expect(
      screen.getAllByRole('button', { name: /^Edit defaults for/ })
    ).toHaveLength(25);
    expect(
      screen.queryByRole('dialog', { name: /^Category defaults/ })
    ).not.toBeInTheDocument();
    expect(document.querySelectorAll('input[type="checkbox"]')).toHaveLength(
      26
    );
  });

  it('bulk resets and feature updates preserve other fields and apply only to selected enabled rows', async () => {
    expect(HTMLElement.prototype.scrollIntoView).toBeTypeOf('function');
    const onChange = await renderCategories('movie', {
      audio_languages: ['ger'],
      resolution: '1080p',
      provider_field: 'keep',
    });
    fireEvent.click(
      screen.getByRole('checkbox', { name: 'Select Synthetic category 0' })
    );
    fireEvent.click(screen.getByRole('button', { name: 'Edit settings (1)' }));
    const editor = await screen.findByRole('dialog', {
      name: 'Edit settings for 1 category',
    });
    expect(within(editor).getByText('Metadata')).toBeInTheDocument();
    fireEvent.click(
      within(editor).getByRole('button', { name: 'Clear Resolution defaults' })
    );
    const picker = await openPicker('Video features');
    fireEvent.click(within(picker).getByRole('checkbox', { name: 'HDR' }));
    await applyPicker(picker);
    fireEvent.click(
      within(editor).getByRole('button', { name: 'Apply to selected' })
    );
    const other = {
      id: 2,
      enabled: false,
      custom_properties: { audio_languages: ['fre'] },
    };
    const next = onChange.mock.calls.at(-1)[0]([
      {
        id: 1,
        enabled: true,
        custom_properties: {
          audio_languages: ['ger'],
          provider_field: 'keep',
          resolution: '1080p',
        },
      },
      other,
    ]);
    expect(next[0].custom_properties).toEqual({
      audio_languages: ['ger'],
      provider_field: 'keep',
      resolution: null,
      video_features: ['hdr'],
    });
    expect(next[1]).toBe(other);
  });
  it.each(['movie', 'series'])(
    'allows editing %s defaults only after enabling the category and retains their visual summary',
    async (type) => {
      await renderCategories(type, {
        audio_languages: ['ger'],
        video_features: ['hdr'],
      });
      let action = screen.getByRole('button', {
        name: 'Edit defaults for Synthetic category 0',
      });
      expect(action).toBeEnabled();
      expect(action).toHaveAttribute('data-variant', 'light');
      expect(action.querySelector('.lucide-settings')).not.toBeNull();
      const summary = screen.getByText('ger', { exact: true });
      expect(summary.style.color).not.toContain('blue');
      expect(summary.closest('.mantine-Badge-root')).not.toBeNull();
      expect(screen.getByText('HDR', { exact: true })).toBeInTheDocument();
      for (const name of ['DUB', 'SUB', 'Resolution', 'Features'])
        expect(
          screen.getByRole('columnheader', { name, exact: true })
        ).toBeInTheDocument();
      expect(
        screen.queryByRole('columnheader', { name: 'Source defaults' })
      ).not.toBeInTheDocument();
      fireEvent.click(
        screen.getByRole('checkbox', {
          name: 'Select Synthetic category 0',
          exact: true,
        })
      );
      setSelectedStatus('Disabled');
      action = screen.getByRole('button', {
        name: 'Edit defaults for Synthetic category 0',
      });
      expect(action).toBeDisabled();
      fireEvent.click(action);
      expect(
        screen.queryByRole('dialog', { name: /^Category defaults/ })
      ).not.toBeInTheDocument();
      expect(screen.getByText('ger', { exact: true })).toBeInTheDocument();
      expect(screen.getByText('HDR', { exact: true })).toBeInTheDocument();
      setSelectedStatus('Enabled');
      expect(
        screen.getByRole('button', {
          name: 'Edit defaults for Synthetic category 0',
        })
      ).toBeEnabled();
      await openEditor();
      expect(
        screen.getByRole('button', {
          name: 'Remove German (ger) from DUB languages',
        })
      ).toHaveTextContent('ger');
    }
  );

  it.each(['movie', 'series'])(
    'does not mount any editor or hidden option lists for closed %s categories',
    async (type) => {
      await renderCategories(type);
      expect(
        screen.getAllByRole('button', { name: /^Edit defaults for/ })
      ).toHaveLength(4);
      expect(
        screen.queryByRole('dialog', { name: /^Category defaults/ })
      ).not.toBeInTheDocument();
      // Only the four page-size options may exist; no per-row metadata lists.
      expect(
        document.querySelectorAll('[role="option"]').length
      ).toBeLessThanOrEqual(4);
      expect(document.querySelectorAll('input[type="checkbox"]')).toHaveLength(
        5
      );
    }
  );

  it.each(['DUB languages', 'SUB languages'])(
    'searches the limited %s choices and retains saved unlisted values without applying immediately',
    async (field) => {
      const onChange = await renderCategories();
      await openEditor();
      const picker = await openPicker(field);
      expect(
        within(picker).getByRole('checkbox', { name: 'German (ger)' })
      ).toBeInTheDocument();
      expect(within(picker).getAllByRole('checkbox')).toHaveLength(50);
      fireEvent.change(
        within(picker).getByRole('textbox', { name: 'Search languages' }),
        { target: { value: 'Slovak' } }
      );
      fireEvent.click(
        within(picker).getByRole('checkbox', { name: 'Slovak (slo)' })
      );
      await applyPicker(picker);
      expect(onChange).not.toHaveBeenCalled();
      fireEvent.click(
        screen.getByRole('button', { name: 'Apply', exact: true })
      );
      expect(onChange).toHaveBeenCalledOnce();
      await waitFor(() =>
        expect(
          screen.queryByRole('dialog', { name: /^Category defaults/ })
        ).not.toBeInTheDocument()
      );
      const editor = await openEditor();
      expect(
        within(editor).getByRole('button', {
          name: new RegExp(`Remove Slovak \\(slo\\) from ${field}`),
        })
      ).toBeInTheDocument();
      expect(
        within(editor).getByRole('button', {
          name: 'Remove GMH from DUB languages',
        })
      ).toBeInTheDocument();
    }
  );

  it('uses only codes in selected language chips but full names in the selection list', async () => {
    await renderCategories('movie', {
      audio_languages: ['eng', 'ger'],
      subtitle_languages: ['eng'],
    });
    const editor = await openEditor();
    const audio = within(editor).getByRole('button', {
      name: 'Remove English (eng) from DUB languages',
    });
    expect(audio).toHaveTextContent(/^eng ×$/);
    expect(audio).toHaveAttribute('title', 'English (eng)');
    expect(
      within(editor).getByRole('button', {
        name: 'Remove German (ger) from DUB languages',
      })
    ).toHaveTextContent(/^ger ×$/);
    expect(
      within(editor).getByRole('button', {
        name: 'Remove English (eng) from SUB languages',
      })
    ).toHaveTextContent(/^eng ×$/);
    const picker = await openPicker('DUB languages');
    expect(
      within(picker).getByRole('checkbox', { name: 'English (eng)' })
    ).toBeChecked();
    expect(
      within(picker).getByRole('checkbox', { name: 'German (ger)' })
    ).toBeChecked();
  });

  it('closes only the top dialog on Escape and keeps the category selection open', async () => {
    const onChange = await renderCategories();
    await openEditor();
    const picker = await openPicker('DUB languages');
    fireEvent.keyDown(
      within(picker).getByRole('textbox', { name: 'Search languages' }),
      { key: 'Escape' }
    );
    await waitFor(() => expect(picker).not.toBeInTheDocument());
    const editor = screen.getByRole('dialog', {
      name: 'Category defaults · Synthetic category 0',
    });
    fireEvent.keyDown(
      within(editor).getByRole('button', { name: 'Close category defaults' }),
      { key: 'Escape' }
    );
    await waitFor(() => expect(editor).not.toBeInTheDocument());
    expect(
      screen.getByRole('dialog', { name: 'Category selection' })
    ).toBeVisible();
    expect(onChange).not.toHaveBeenCalled();
  });

  it('never offers historical or collective codes, including through search', async () => {
    await renderCategories();
    await openEditor();
    const picker = await openPicker('DUB languages');
    expect(picker.querySelectorAll('input[type="checkbox"]')).toHaveLength(
      MEDIA_LANGUAGE_OPTIONS.length
    );
    expect(
      within(picker).queryByRole('button', { name: 'Show all languages' })
    ).not.toBeInTheDocument();
    for (const value of ['gmh', 'goh', 'gem', 'Middle High', 'Germanic']) {
      fireEvent.change(
        within(picker).getByRole('textbox', { name: 'Search languages' }),
        { target: { value } }
      );
      expect(within(picker).queryByRole('checkbox')).not.toBeInTheDocument();
    }
  });

  it('does not offer an unlisted saved value again after it is explicitly removed', async () => {
    const onChange = await renderCategories();
    await openEditor();
    fireEvent.click(
      screen.getByRole('button', { name: 'Remove GMH from DUB languages' })
    );
    const picker = await openPicker('DUB languages');
    fireEvent.change(
      within(picker).getByRole('textbox', { name: 'Search languages' }),
      { target: { value: 'gmh' } }
    );
    expect(within(picker).queryByRole('checkbox')).not.toBeInTheDocument();
    await applyPicker(picker);
    fireEvent.click(screen.getByRole('button', { name: 'Apply', exact: true }));
    const next = onChange.mock.calls[0][0]([{ id: 1, custom_properties: {} }]);
    expect(next[0].custom_properties.audio_languages).toEqual([]);
  });

  it('cancels pending picker and editor changes without touching category state', async () => {
    const onChange = await renderCategories();
    const editor = await openEditor();
    const picker = await openPicker('DUB languages');
    fireEvent.click(
      within(picker).getByRole('checkbox', { name: 'German (ger)' })
    );
    fireEvent.keyDown(picker, { key: 'Escape' });
    await waitFor(() => expect(picker).not.toBeInTheDocument());
    expect(
      within(editor).queryByRole('button', { name: /Remove German/ })
    ).toBeInTheDocument();
    fireEvent.click(
      within(editor).getByRole('button', { name: 'Close category defaults' })
    );
    await waitFor(() => expect(editor).not.toBeInTheDocument());
    expect(onChange).not.toHaveBeenCalled();
    await openEditor(1);
    expect(
      screen.queryByRole('button', { name: /Remove GMH/ })
    ).not.toBeInTheDocument();
  });

  it('offers numeric resolutions, supports custom tags and preserves unrelated properties', async () => {
    const onChange = await renderCategories();
    await openEditor();
    fireEvent.click(screen.getByRole('textbox', { name: 'Resolution' }));
    expect(
      screen.getAllByRole('option').map((option) => option.textContent)
    ).toEqual([
      '4320p',
      '2160p',
      '1440p',
      '1080p',
      '720p',
      '576p',
      '480p',
      '360p',
    ]);
    fireEvent.click(screen.getByRole('option', { name: '360p', exact: true }));
    const picker = await openPicker('Video features');
    fireEvent.click(within(picker).getByRole('checkbox', { name: 'HDR' }));
    fireEvent.change(
      within(picker).getByRole('textbox', { name: 'Custom tag' }),
      { target: { value: 'IMAX' } }
    );
    fireEvent.click(
      within(picker).getByRole('button', { name: 'Add', exact: true })
    );
    expect(
      within(picker).getByRole('checkbox', { name: 'imax' })
    ).toBeChecked();
    await applyPicker(picker);
    fireEvent.click(screen.getByRole('button', { name: 'Apply', exact: true }));
    const next = onChange.mock.calls[0][0]([
      { id: 1, custom_properties: { provider_field: 'keep' } },
      { id: 2, custom_properties: {} },
    ]);
    expect(next[0].custom_properties).toEqual({
      provider_field: 'keep',
      audio_languages: ['gmh'],
      subtitle_languages: [],
      resolution: '360p',
      video_features: ['hdr', 'custom:imax'],
    });
    expect(next[1].custom_properties).toEqual({});
  });

  it('preserves a legacy SD value without mapping it to an invented resolution', async () => {
    await renderCategories('movie', { resolution: 'SD' });
    await openEditor();
    expect(screen.getByRole('textbox', { name: 'Resolution' })).toHaveValue(
      'SD'
    );
    fireEvent.click(screen.getByRole('button', { name: 'Apply', exact: true }));
    await waitFor(() =>
      expect(
        screen.queryByRole('dialog', { name: /^Category defaults/ })
      ).not.toBeInTheDocument()
    );
    expect(screen.getByText('SD')).toBeInTheDocument();
  });

  it('clears languages explicitly and does not resurrect a cleared legacy quality', async () => {
    const onChange = await renderCategories('movie', {
      audio_languages: ['ger'],
      quality: '1080p',
      resolution: null,
    });
    await openEditor();
    expect(screen.getByRole('textbox', { name: 'Resolution' })).toHaveValue('');
    fireEvent.click(
      screen.getByRole('button', {
        name: 'Remove German (ger) from DUB languages',
      })
    );
    fireEvent.click(screen.getByRole('button', { name: 'Apply', exact: true }));
    const next = onChange.mock.calls[0][0]([{ id: 1, custom_properties: {} }]);
    expect(next[0].custom_properties.audio_languages).toEqual([]);
    expect(next[0].custom_properties.resolution).toBeNull();
  });
});
