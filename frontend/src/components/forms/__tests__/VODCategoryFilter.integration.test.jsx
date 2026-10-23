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

function CategoryHarness({ type, onChange, properties }) {
  const [categories, setCategories] = useState(() =>
    Array.from({ length: 4 }, (_, index) => ({
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
          onClose={() => {}}
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
  fireEvent.click(
    within(dialog).getByRole('button', { name: 'Apply selection' })
  );
  await waitFor(() => expect(dialog).not.toBeInTheDocument());
}

describe('VOD category metadata with real Mantine controls', () => {
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
      const summary = screen.getByText('DUB: GER · HDR');
      expect(summary.style.color).toContain('blue');
      fireEvent.click(
        screen.getByRole('button', {
          name: 'Synthetic category 0',
          exact: true,
        })
      );
      action = screen.getByRole('button', {
        name: 'Edit defaults for Synthetic category 0',
      });
      expect(action).toBeDisabled();
      fireEvent.click(action);
      expect(
        screen.queryByRole('dialog', { name: /^Category defaults/ })
      ).not.toBeInTheDocument();
      expect(screen.getByText('DUB: GER · HDR')).toBeInTheDocument();
      fireEvent.click(
        screen.getByRole('button', {
          name: 'Synthetic category 0',
          exact: true,
        })
      );
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
      expect(document.querySelectorAll('[role="option"]')).toHaveLength(0);
      expect(document.querySelectorAll('input[type="checkbox"]')).toHaveLength(
        1
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
      within(picker).getByRole('button', { name: 'Close metadata selection' }),
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
    fireEvent.click(within(picker).getByRole('button', { name: 'Cancel' }));
    await waitFor(() => expect(picker).not.toBeInTheDocument());
    expect(
      within(editor).queryByRole('button', { name: /Remove German/ })
    ).not.toBeInTheDocument();
    fireEvent.click(within(editor).getByRole('button', { name: 'Cancel' }));
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
