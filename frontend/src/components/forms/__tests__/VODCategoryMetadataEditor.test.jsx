import {
  fireEvent,
  render,
  screen,
  within,
  waitFor,
} from '@testing-library/react';
import { MantineProvider, Modal } from '@mantine/core';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import VODCategoryMetadataEditor from '../VODCategoryMetadataEditor.jsx';

const fields = [
  ['audio_languages', 'DUB languages'],
  ['subtitle_languages', 'SUB languages'],
  ['resolution', 'Resolution'],
  ['video_features', 'Video features'],
];

const open = (props = {}) => {
  const onApply = vi.fn();
  const onClose = vi.fn();
  render(
    <MantineProvider env="test">
      <Modal.Stack>
        <Modal
          opened
          title="Metadata editor"
          onClose={onClose}
          closeButtonProps={{ 'aria-label': 'Close metadata editor' }}
        >
          <VODCategoryMetadataEditor
            bulk
            value={{
              audio_languages: [],
              subtitle_languages: [],
              resolution: '',
              video_features: [],
            }}
            languages={[
              { value: 'eng', label: 'English (eng)' },
              { value: 'ger', label: 'German (ger)' },
            ]}
            resolutions={['1080p', '2160p']}
            pickerStackId="bulk-picker"
            {...props}
            onApply={onApply}
          />
        </Modal>
      </Modal.Stack>
    </MantineProvider>
  );
  return { onApply, onClose };
};

const choose = (label, values) => {
  fireEvent.click(screen.getByRole('button', { name: `Choose ${label}` }));
  const picker = screen.getByRole('dialog', { name: `Select ${label}` });
  for (const name of values)
    fireEvent.click(
      within(picker).getByRole('checkbox', { name, exact: true })
    );
  expect(
    within(picker).queryByRole('button', { name: 'Apply selection' })
  ).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: `Choose ${label}` }));
};

describe('direct VOD bulk metadata editing with real Mantine controls', () => {
  it.each(['category', 'bulk', 'rule'])(
    'shares the same metadata frame and compact fields in %s mode',
    (mode) => {
      const { onApply } = open({
        bulk: mode === 'bulk',
        ruleMode: mode === 'rule',
      });
      const frame = screen.getByRole('group', {
        name: 'Category content settings',
      });
      expect(within(frame).getByText('Metadata')).toBeInTheDocument();
      expect(
        screen.queryByText(/Import defaults only/)
      ).not.toBeInTheDocument();
      expect(
        screen.queryByRole('button', { name: 'Cancel', exact: true })
      ).not.toBeInTheDocument();
      expect(
        screen.getByRole('button', { name: 'Choose DUB languages' })
          .parentElement
      ).toHaveStyle({ minHeight: 'calc(2.25rem * var(--mantine-scale))' });
      fireEvent.click(
        screen.getByRole('button', {
          name: 'Close metadata editor',
          exact: true,
        })
      );
      expect(onApply).not.toHaveBeenCalled();
    }
  );
  it('shows all fields immediately and applies no metadata patch when nothing changes', () => {
    const { onApply } = open();
    for (const [, label] of fields) {
      expect(
        screen.queryByLabelText(`${label} update`)
      ).not.toBeInTheDocument();
      expect(
        screen.getByRole('button', { name: `Clear ${label} defaults` })
      ).toHaveAttribute('aria-pressed', 'false');
      expect(
        screen.queryByRole('button', { name: `Undo ${label} change` })
      ).not.toBeInTheDocument();
    }
    expect(screen.getByRole('textbox', { name: 'Resolution' })).toHaveAttribute(
      'placeholder',
      'Keep unchanged'
    );
    expect(screen.queryByText(/Import defaults only/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Apply to selected' }));
    expect(onApply).toHaveBeenCalledExactlyOnceWith({});
  });

  it('automatically marks selected languages and resolution without changing other fields', () => {
    const { onApply } = open();
    choose('DUB languages', ['English (eng)', 'German (ger)']);
    fireEvent.click(screen.getByRole('textbox', { name: 'Resolution' }));
    fireEvent.click(screen.getByRole('option', { name: '1080p', exact: true }));
    expect(
      screen.getByRole('button', { name: 'Clear DUB languages defaults' })
    ).toHaveAttribute('aria-pressed', 'false');
    expect(onApply).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Apply to selected' }));
    expect(onApply).toHaveBeenCalledExactlyOnceWith({
      audio_languages: ['eng', 'ger'],
      resolution: '1080p',
    });
  });

  it.each(fields)(
    'retains the blue outline for %s without a redundant Changed label',
    (field, label) => {
      const { onApply } = open();
      const control =
        field === 'resolution'
          ? screen.getByRole('textbox', { name: 'Resolution' })
          : screen.getByRole('button', { name: `Choose ${label}` })
              .parentElement;
      expect(control.getAttribute('style') || '').not.toContain(
        'var(--mantine-color-blue-5)'
      );
      if (field === 'resolution') {
        fireEvent.click(control);
        fireEvent.click(
          screen.getByRole('option', { name: '1080p', exact: true })
        );
      } else {
        choose(label, [field === 'video_features' ? 'HDR' : 'English (eng)']);
      }
      expect(screen.queryByText('Changed')).not.toBeInTheDocument();
      expect(control.getAttribute('style')).toContain(
        'var(--mantine-color-blue-5)'
      );
      expect(onApply).not.toHaveBeenCalled();
    }
  );

  it.each(fields)(
    'toggles only %s from unchanged to clear and back with the same button',
    (field, label) => {
      const { onApply } = open();
      const clear = screen.getByRole('button', {
        name: `Clear ${label} defaults`,
      });
      fireEvent.click(clear);
      expect(clear).toHaveAttribute('aria-pressed', 'true');
      expect(clear).toHaveAccessibleName(`Keep ${label} unchanged`);
      if (field === 'resolution')
        expect(
          screen.getByRole('textbox', { name: 'Resolution' })
        ).toHaveAttribute('placeholder', 'Clear');
      else expect(screen.getByRole('status')).toHaveTextContent('Clear');
      fireEvent.click(
        screen.getByRole('button', { name: 'Apply to selected' })
      );
      expect(onApply).toHaveBeenLastCalledWith({ [field]: null });
      fireEvent.click(clear);
      expect(clear).toHaveAttribute('aria-pressed', 'false');
      expect(clear).toHaveAccessibleName(`Clear ${label} defaults`);
      expect(screen.queryByRole('status')).not.toBeInTheDocument();
      fireEvent.click(
        screen.getByRole('button', { name: 'Apply to selected' })
      );
      expect(onApply).toHaveBeenLastCalledWith({});
    }
  );

  it('returns a cleared language field to unchanged without affecting another field', () => {
    const { onApply } = open();
    choose('DUB languages', ['English (eng)']);
    choose('Video features', ['HDR']);
    fireEvent.click(
      screen.getByRole('button', {
        name: 'Remove English (eng) from DUB languages',
      })
    );
    fireEvent.click(screen.getByRole('button', { name: 'Apply to selected' }));
    expect(onApply).toHaveBeenLastCalledWith({
      audio_languages: null,
      video_features: ['hdr'],
    });
    fireEvent.click(
      screen.getByRole('button', { name: 'Keep DUB languages unchanged' })
    );
    fireEvent.click(screen.getByRole('button', { name: 'Apply to selected' }));
    expect(onApply).toHaveBeenLastCalledWith({ video_features: ['hdr'] });
  });

  it('drops a pending selection when clear is toggled on and then back to unchanged', () => {
    const { onApply } = open();
    choose('DUB languages', ['English (eng)']);
    fireEvent.click(
      screen.getByRole('button', { name: 'Clear DUB languages defaults' })
    );
    fireEvent.click(
      screen.getByRole('button', { name: 'Keep DUB languages unchanged' })
    );
    expect(
      screen.queryByRole('button', { name: /Remove English/ })
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Apply to selected' }));
    expect(onApply).toHaveBeenCalledExactlyOnceWith({});
  });

  it.each(fields)('replaces clear with a new value for %s', (field, label) => {
    const { onApply } = open();
    fireEvent.click(
      screen.getByRole('button', { name: `Clear ${label} defaults` })
    );
    if (field === 'resolution') {
      fireEvent.click(screen.getByRole('textbox', { name: 'Resolution' }));
      fireEvent.click(
        screen.getByRole('option', { name: '2160p', exact: true })
      );
    } else {
      choose(label, [field === 'video_features' ? 'HDR' : 'English (eng)']);
    }
    expect(
      screen.getByRole('button', { name: `Clear ${label} defaults` })
    ).toHaveAttribute('aria-pressed', 'false');
    fireEvent.click(screen.getByRole('button', { name: 'Apply to selected' }));
    expect(onApply).toHaveBeenCalledExactlyOnceWith({
      [field]:
        field === 'resolution'
          ? '2160p'
          : [field === 'video_features' ? 'hdr' : 'eng'],
    });
  });

  it.each(fields.filter(([field]) => field !== 'resolution'))(
    'preserves explicit clear when the unchanged empty %s picker is confirmed',
    (field, label) => {
      const { onApply } = open();
      fireEvent.click(
        screen.getByRole('button', { name: `Clear ${label} defaults` })
      );
      choose(label, []);
      expect(
        screen.getByRole('button', { name: `Keep ${label} unchanged` })
      ).toHaveAttribute('aria-pressed', 'true');
      fireEvent.click(
        screen.getByRole('button', { name: 'Apply to selected' })
      );
      expect(onApply).toHaveBeenCalledExactlyOnceWith({ [field]: null });
    }
  );

  it('supports keyboard toggling without a separate undo control', async () => {
    const { onApply } = open();
    const user = userEvent.setup();
    const clear = screen.getByRole('button', {
      name: 'Clear Resolution defaults',
    });
    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: 'Close metadata editor' })
      ).toHaveFocus()
    );
    clear.focus();
    await user.keyboard(' ');
    expect(clear).toHaveAttribute('aria-pressed', 'true');
    await user.keyboard('{Enter}');
    expect(clear).toHaveAttribute('aria-pressed', 'false');
    fireEvent.click(screen.getByRole('button', { name: 'Apply to selected' }));
    expect(onApply).toHaveBeenCalledExactlyOnceWith({});
  });

  it('does not clear untouched defaults when an empty picker is closed', () => {
    const { onApply } = open();
    choose('DUB languages', []);
    fireEvent.click(
      screen.getByRole('button', { name: 'Choose SUB languages' })
    );
    const picker = screen.getByRole('dialog', { name: 'Select SUB languages' });
    expect(
      within(picker).getByRole('checkbox', { name: 'English (eng)' })
    ).not.toBeChecked();
    fireEvent.click(
      screen.getByRole('button', { name: 'Choose SUB languages' })
    );
    fireEvent.click(screen.getByRole('button', { name: 'Apply to selected' }));
    expect(onApply).toHaveBeenCalledExactlyOnceWith({});
  });

  it('cancels edited fields without applying a patch', () => {
    const { onApply, onClose } = open();
    choose('Video features', ['Dolby Vision']);
    fireEvent.click(
      screen.getByRole('button', { name: 'Close metadata editor' })
    );
    expect(onClose).toHaveBeenCalledOnce();
    expect(onApply).not.toHaveBeenCalled();
  });
});

describe('direct rule metadata editing with real Mantine controls', () => {
  const openRule = (value = {}) => open({ bulk: false, ruleMode: true, value });

  it('shows every field immediately without update selectors and leaves unset fields out of the rule', () => {
    const { onApply } = openRule();
    expect(screen.getByText('Metadata')).toBeInTheDocument();
    for (const [, label] of fields) {
      expect(
        screen.queryByLabelText(`${label} update`)
      ).not.toBeInTheDocument();
      expect(
        screen.getByRole('button', {
          name: `Do not set ${label} with this rule`,
        })
      ).toBeDisabled();
    }
    expect(screen.queryByText('Set default')).not.toBeInTheDocument();
    expect(screen.getAllByText('Not set by this rule')).toHaveLength(3);
    expect(screen.getByRole('textbox', { name: 'Resolution' })).toHaveAttribute(
      'placeholder',
      'Not set by this rule'
    );
    expect(screen.queryByText(/Import defaults only/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Apply', exact: true }));
    expect(onApply).toHaveBeenCalledExactlyOnceWith({});
  });

  it.each(fields)(
    'automatically assigns %s and removes only that assignment on reset',
    (field, label) => {
      const { onApply } = openRule({ video_features: ['custom:imax'] });
      if (field === 'resolution') {
        fireEvent.click(screen.getByRole('textbox', { name: 'Resolution' }));
        fireEvent.click(
          screen.getByRole('option', { name: '1080p', exact: true })
        );
      } else {
        choose(label, [field === 'video_features' ? 'HDR' : 'English (eng)']);
      }
      const reset = screen.getByRole('button', {
        name: `Do not set ${label} with this rule`,
      });
      expect(reset).toBeEnabled();
      expect(screen.queryByText('Changed')).not.toBeInTheDocument();
      fireEvent.click(
        screen.getByRole('button', { name: 'Apply', exact: true })
      );
      const chosen =
        field === 'resolution'
          ? '1080p'
          : field === 'video_features'
            ? ['custom:imax', 'hdr']
            : ['eng'];
      expect(onApply).toHaveBeenLastCalledWith({
        video_features: ['custom:imax'],
        [field]: chosen,
      });
      fireEvent.click(reset);
      expect(reset).toBeDisabled();
      fireEvent.click(
        screen.getByRole('button', { name: 'Apply', exact: true })
      );
      expect(onApply).toHaveBeenLastCalledWith(
        field === 'video_features' ? {} : { video_features: ['custom:imax'] }
      );
    }
  );

  it.each(fields.filter(([field]) => field !== 'resolution'))(
    'preserves a stored explicitly empty %s assignment until it is deliberately removed',
    (field, label) => {
      const { onApply } = openRule({ [field]: [], resolution: '2160p' });
      expect(screen.getByText('Empty default')).toBeInTheDocument();
      choose(label, []);
      fireEvent.click(
        screen.getByRole('button', { name: 'Apply', exact: true })
      );
      expect(onApply).toHaveBeenLastCalledWith({
        [field]: [],
        resolution: '2160p',
      });
      fireEvent.click(
        screen.getByRole('button', {
          name: `Do not set ${label} with this rule`,
        })
      );
      fireEvent.click(
        screen.getByRole('button', { name: 'Apply', exact: true })
      );
      expect(onApply).toHaveBeenLastCalledWith({ resolution: '2160p' });
    }
  );

  it('keeps explicit empty assignments distinct from unset when the last language is removed', () => {
    const { onApply } = openRule({
      audio_languages: ['eng'],
      subtitle_languages: ['ger'],
    });
    fireEvent.click(
      screen.getByRole('button', {
        name: 'Remove English (eng) from DUB languages',
      })
    );
    expect(screen.getByText('Empty default')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Apply', exact: true }));
    expect(onApply).toHaveBeenLastCalledWith({
      audio_languages: [],
      subtitle_languages: ['ger'],
    });
    fireEvent.click(
      screen.getByRole('button', {
        name: 'Do not set DUB languages with this rule',
      })
    );
    fireEvent.click(screen.getByRole('button', { name: 'Apply', exact: true }));
    expect(onApply).toHaveBeenLastCalledWith({ subtitle_languages: ['ger'] });
  });

  it('keeps the selection in the draft when the popover closes without another Apply', () => {
    const { onApply } = openRule();
    choose('DUB languages', []);
    fireEvent.click(
      screen.getByRole('button', { name: 'Choose Video features' })
    );
    const picker = screen.getByRole('dialog', {
      name: 'Select Video features',
    });
    fireEvent.click(
      within(picker).getByRole('checkbox', { name: 'HDR', exact: true })
    );
    expect(onApply).not.toHaveBeenCalled();
    fireEvent.click(
      screen.getByRole('button', { name: 'Choose Video features' })
    );
    fireEvent.click(screen.getByRole('button', { name: 'Apply', exact: true }));
    expect(onApply).toHaveBeenCalledExactlyOnceWith({
      video_features: ['hdr'],
    });
  });

  it('preserves stored languages, resolution and custom features without rewriting them', () => {
    const value = {
      audio_languages: ['xyz'],
      subtitle_languages: [],
      resolution: '1080p',
      video_features: ['hdr', 'custom:cinema'],
    };
    const { onApply, onClose } = openRule(value);
    fireEvent.click(screen.getByRole('button', { name: 'Apply', exact: true }));
    expect(onApply).toHaveBeenCalledExactlyOnceWith(value);
    fireEvent.click(
      screen.getByRole('button', {
        name: 'Do not set Resolution with this rule',
      })
    );
    fireEvent.click(
      screen.getByRole('button', { name: 'Close metadata editor', exact: true })
    );
    expect(onClose).toHaveBeenCalledOnce();
    expect(onApply).toHaveBeenCalledTimes(1);
  });
});
