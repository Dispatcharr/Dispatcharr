import {
  render,
  screen,
  fireEvent,
  waitFor,
  within,
  act,
} from '@testing-library/react';
import { MantineProvider } from '@mantine/core';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import userEvent from '@testing-library/user-event';
import M3URulesEditor from '../M3URulesEditor.jsx';
import classes from '../M3URulesEditor.module.css';
import API from '../../../api.js';
import useM3URuleChecks from '../../../store/useM3URuleChecks.js';
import {
  hideNotification,
  showNotification,
} from '../../../utils/notificationUtils.js';

const drag = vi.hoisted(() => ({ onEnd: null }));

vi.mock('../../../api.js', () => ({
  default: {
    getM3URules: vi.fn(),
    analyzeM3URules: vi.fn(),
    saveM3URule: vi.fn(),
    deleteM3URule: vi.fn(),
    previewM3URules: vi.fn(),
    reorderM3URules: vi.fn(),
    saveApplyM3UGroupRules: vi.fn(),
    refreshLivePlaylist: vi.fn(),
  },
}));
vi.mock('../../../utils/notificationUtils.js', () => ({
  showNotification: vi.fn(),
  hideNotification: vi.fn(),
}));
vi.mock('../../../utils/dateTimeUtils.js', () => ({
  useDateTimeFormat: () => ({
    dateYearFormat: 'DD.MM.YYYY',
    timeFormat: 'HH:mm',
  }),
  useTimeHelpers: () => ({
    toUserTime: () => ({ format: () => '14.10.2026 08:00' }),
  }),
}));
vi.mock('../../ConfirmationDialog.jsx', () => ({
  default: ({
    opened,
    onConfirm,
    onClose,
    confirmLabel,
    cancelLabel,
    message,
  }) =>
    opened ? (
      <div role="alertdialog">
        <p>{message}</p>
        <button onClick={onConfirm}>
          {confirmLabel === 'Delete' ? 'Confirm delete' : confirmLabel}
        </button>
        <button onClick={onClose}>{cancelLabel || 'Cancel delete'}</button>
      </div>
    ) : null,
}));
vi.mock('@dnd-kit/core', async (importOriginal) => ({
  ...(await importOriginal()),
  DndContext: ({ children, onDragEnd }) => {
    drag.onEnd = onDragEnd;
    return (
      <div>
        {children}
        <button
          onClick={() => onDragEnd({ active: { id: 2 }, over: { id: 1 } })}
        >
          Move second first
        </button>
      </div>
    );
  },
}));

const rule = (values = {}) => ({
  id: 1,
  scope: 'live',
  match_field: 'group_name',
  match_mode: 'any',
  regex_pattern: 'News',
  action: 'enable',
  case_sensitive: false,
  enabled: true,
  order: 0,
  ...values,
});
const renderEditor = (props = {}) =>
  render(
    <MantineProvider env="test">
      <M3URulesEditor accountId={7} scope="live" {...props} />
    </MantineProvider>
  );
const load = async (rows = [rule()]) => {
  API.getM3URules.mockResolvedValue(rows);
  renderEditor();
  await screen.findByDisplayValue(rows[0].regex_pattern);
  await waitFor(() =>
    expect(screen.getAllByLabelText(/^Edit (rule|filter)$/)[0]).toBeEnabled()
  );
};

const editRow = (index = 0) => {
  const inputs = screen.getAllByLabelText('Regular expression');
  const row = inputs[index].closest('tr');
  const edit = within(row).queryByLabelText(/^Edit (rule|filter)$/);
  if (edit) fireEvent.click(edit);
};

const changeField = (input, event) => {
  if (
    input.getAttribute('aria-label') === 'Regular expression' &&
    input.disabled
  ) {
    const edit = within(input.closest('tr')).queryByLabelText(
      /^Edit (rule|filter)$/
    );
    if (edit) fireEvent.click(edit);
  }
  if (
    input.getAttribute('aria-label') === 'Preview regular expression' &&
    input.readOnly
  ) {
    fireEvent.click(screen.getByLabelText('Edit preview expression'));
  }
  fireEvent.change(input, event);
};
const closePreview = (preview) => {
  fireEvent.click(
    (preview ? within(preview) : screen).getByLabelText('Close preview')
  );
  const discard = screen.queryByRole('button', {
    name: 'Discard',
    exact: true,
  });
  if (discard) fireEvent.click(discard);
};

describe('M3URulesEditor', () => {
  it.each(['live', 'movie', 'series', 'filters'])(
    'rebuilds saved %s validation errors after deletion without preserving draft state',
    async (scope) => {
      const streamFilters = scope === 'filters';
      const noun = streamFilters ? 'filter' : 'rule';
      API.getM3URules.mockResolvedValue([
        rule({ scope, filter_type: 'name' }),
        rule({
          id: 2,
          scope,
          filter_type: 'name',
          order: 1,
          regex_pattern: '[',
        }),
      ]);
      API.analyzeM3URules
        .mockRejectedValueOnce({
          status: 400,
          body: {
            rules: [{}, { regex_pattern: ['Invalid saved expression'] }],
          },
        })
        .mockRejectedValueOnce({
          status: 400,
          body: { rules: [{ regex_pattern: ['Invalid saved expression'] }] },
        });
      API.deleteM3URule.mockResolvedValue(undefined);
      renderEditor({ scope: streamFilters ? undefined : scope, streamFilters });
      await waitFor(() =>
        expect(screen.getAllByLabelText(`Delete ${noun}`)[0]).toBeEnabled()
      );
      expect(screen.getAllByLabelText('Regular expression')[1]).toHaveAttribute(
        'aria-invalid',
        'true'
      );
      fireEvent.click(screen.getAllByLabelText(`Delete ${noun}`)[0]);
      fireEvent.click(screen.getByText('Confirm delete'));
      await waitFor(() => expect(API.analyzeM3URules).toHaveBeenCalledTimes(2));
      await waitFor(() =>
        expect(screen.getByLabelText('Regular expression')).toHaveAttribute(
          'aria-invalid',
          'true'
        )
      );
      expect(screen.getByLabelText('Regular expression')).toHaveValue('[');
      expect(screen.getByLabelText(`Edit ${noun}`)).toBeEnabled();
      expect(API.deleteM3URule).toHaveBeenCalledExactlyOnceWith(
        7,
        streamFilters ? 'filters' : 'group-rules',
        1
      );
      expect(API.analyzeM3URules).toHaveBeenLastCalledWith(
        7,
        streamFilters ? 'filters' : 'group-rules',
        [expect.objectContaining({ preview_id: '2', regex_pattern: '[' })]
      );
      expect(API.saveM3URule).not.toHaveBeenCalled();
    }
  );

  it.each(['live', 'movie', 'series', 'filters'])(
    'keeps Preview in the middle action slot when editing or adding a %s row',
    async (scope) => {
      const streamFilters = scope === 'filters';
      const noun = streamFilters ? 'filter' : 'rule';
      API.getM3URules.mockResolvedValue([rule({ scope, filter_type: 'name' })]);
      renderEditor({ scope: streamFilters ? undefined : scope, streamFilters });
      await waitFor(() =>
        expect(screen.getByLabelText(`Edit ${noun}`)).toBeEnabled()
      );
      const actionLabels = (rowIndex = 0) => {
        const inputs = screen.getAllByLabelText('Regular expression');
        const row = inputs[rowIndex].closest('tr');
        return within(row.lastElementChild)
          .getAllByRole('button')
          .map((button) => button.getAttribute('aria-label'));
      };
      const savedActions = [
        `Edit ${noun}`,
        `Preview ${noun}`,
        `Delete ${noun}`,
      ];
      const editingActions = [
        `Save ${noun}`,
        `Preview ${noun}`,
        `Discard ${noun} changes`,
      ];
      expect(actionLabels()).toEqual(savedActions);
      editRow();
      expect(actionLabels()).toEqual(editingActions);
      fireEvent.click(screen.getByLabelText(`Discard ${noun} changes`));
      expect(actionLabels()).toEqual(savedActions);
      fireEvent.click(screen.getByRole('button', { name: `Add ${noun}` }));
      expect(actionLabels(1)).toEqual(editingActions);
      fireEvent.click(screen.getByLabelText(`Discard ${noun} changes`));
      expect(actionLabels()).toEqual(savedActions);
      expect(API.saveM3URule).not.toHaveBeenCalled();
      expect(API.deleteM3URule).not.toHaveBeenCalled();
    }
  );

  it.each(['live', 'movie', 'series', 'filters'])(
    'blocks other %s previews while an unchanged row is in edit mode',
    async (scope) => {
      const streamFilters = scope === 'filters';
      const noun = streamFilters ? 'filter' : 'rule';
      API.getM3URules.mockResolvedValue([
        rule({ scope, filter_type: 'name' }),
        rule({
          id: 2,
          scope,
          filter_type: 'name',
          regex_pattern: 'Sport',
          order: 1,
        }),
      ]);
      renderEditor({ scope: streamFilters ? undefined : scope, streamFilters });
      await waitFor(() =>
        expect(screen.getAllByLabelText(`Edit ${noun}`)[0]).toBeEnabled()
      );
      editRow();
      const otherPreview = screen.getAllByLabelText(`Preview ${noun}`)[1];
      expect(otherPreview).toBeDisabled();
      fireEvent.click(otherPreview);
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
      expect(API.previewM3URules).not.toHaveBeenCalled();
      fireEvent.click(screen.getByLabelText(`Discard ${noun} changes`));
      expect(otherPreview).toBeEnabled();
      fireEvent.click(otherPreview);
      const preview = await screen.findByRole('dialog');
      await within(preview).findByText(/1 matching/);
      expect(
        within(preview).getByLabelText('Edit preview expression')
      ).toBeEnabled();
      if (streamFilters)
        expect(
          within(preview).queryByText('Apply to existing')
        ).not.toBeInTheDocument();
      else expect(within(preview).getByText('Apply to existing')).toBeEnabled();
      expect(API.saveM3URule).not.toHaveBeenCalled();
      expect(API.saveApplyM3UGroupRules).not.toHaveBeenCalled();
    }
  );

  it('restores a saved validation marker when row changes are discarded', async () => {
    API.getM3URules.mockResolvedValue([rule({ regex_pattern: '[' })]);
    API.analyzeM3URules.mockRejectedValueOnce({
      status: 400,
      body: { rules: [{ regex_pattern: ['Invalid saved expression'] }] },
    });
    renderEditor();
    await screen.findByRole('img', { name: /Invalid saved expression/ });
    await waitFor(() =>
      expect(screen.getByLabelText('Edit rule')).toBeEnabled()
    );
    editRow();
    fireEvent.change(screen.getByLabelText('Regular expression'), {
      target: { value: 'Corrected draft' },
    });
    expect(screen.getByLabelText('Regular expression')).not.toHaveAttribute(
      'aria-invalid',
      'true'
    );
    fireEvent.click(screen.getByLabelText('Discard rule changes'));
    expect(screen.getByLabelText('Regular expression')).toHaveValue('[');
    expect(screen.getByLabelText('Regular expression')).toHaveAttribute(
      'aria-invalid',
      'true'
    );
    expect(API.analyzeM3URules).toHaveBeenCalledTimes(1);
    expect(API.saveM3URule).not.toHaveBeenCalled();
  });

  it('discards applied metadata draft changes together with the active row', async () => {
    API.getM3URules.mockResolvedValue([
      rule({
        scope: 'movie',
        metadata_defaults: { audio_languages: ['eng'], resolution: '1080p' },
      }),
    ]);
    renderEditor({ scope: 'movie' });
    await waitFor(() =>
      expect(screen.getByLabelText('Edit rule')).toBeEnabled()
    );
    editRow();
    fireEvent.click(screen.getByLabelText('Configure rule metadata'));
    const metadata = await screen.findByRole('dialog', {
      name: 'Rule metadata defaults',
    });
    fireEvent.click(
      within(metadata).getByRole('textbox', { name: 'Resolution' })
    );
    fireEvent.click(screen.getByRole('option', { name: '2160p' }));
    fireEvent.click(
      within(metadata).getByRole('button', { name: 'Apply', exact: true })
    );
    expect(screen.getByText('2160p', { exact: true })).toBeInTheDocument();
    expect(screen.getByLabelText('Save rule')).toBeEnabled();
    fireEvent.click(screen.getByLabelText('Discard rule changes'));
    expect(screen.getByText('1080p', { exact: true })).toBeInTheDocument();
    expect(screen.getByText('eng', { exact: true })).toBeInTheDocument();
    expect(
      screen.queryByText('2160p', { exact: true })
    ).not.toBeInTheDocument();
    expect(screen.getByLabelText('Configure rule metadata')).toBeDisabled();
    expect(API.saveM3URule).not.toHaveBeenCalled();
  });

  it.each(['live', 'movie', 'series', 'filters'])(
    'allows exactly one %s row to be edited and relocks it after Save',
    async (scope) => {
      const streamFilters = scope === 'filters';
      const noun = streamFilters ? 'filter' : 'rule';
      API.getM3URules.mockResolvedValue([
        rule({ scope, filter_type: 'name' }),
        rule({
          id: 2,
          scope,
          filter_type: 'name',
          regex_pattern: 'Sport',
          order: 1,
        }),
      ]);
      API.saveM3URule.mockImplementationOnce(
        async (_account, _kind, id, values) => ({ id, ...values })
      );
      renderEditor({ scope: streamFilters ? undefined : scope, streamFilters });
      await waitFor(() =>
        expect(screen.getAllByLabelText(`Edit ${noun}`)[0]).toBeEnabled()
      );
      const inputs = screen.getAllByLabelText('Regular expression');
      inputs.forEach((input) => expect(input).toBeDisabled());
      expect(screen.queryByLabelText(`Save ${noun}`)).not.toBeInTheDocument();
      editRow();
      expect(inputs[0]).toBeEnabled();
      expect(inputs[0]).toHaveFocus();
      expect(inputs[1]).toBeDisabled();
      expect(screen.getByLabelText(`Edit ${noun}`)).toBeDisabled();
      expect(
        screen.getByRole('button', { name: `Add ${noun}` })
      ).toBeDisabled();
      screen
        .getAllByLabelText(`Move ${noun}`)
        .forEach((handle) => expect(handle).toBeDisabled());
      expect(screen.getByLabelText(`Save ${noun}`)).toBeDisabled();
      expect(screen.getByLabelText(`Discard ${noun} changes`)).toBeEnabled();
      fireEvent.change(inputs[1], { target: { value: 'Blocked' } });
      expect(inputs[1]).toHaveValue('Sport');
      fireEvent.click(screen.getByLabelText(`Edit ${noun}`));
      expect(inputs[1]).toBeDisabled();
      if (!streamFilters && scope !== 'live') {
        expect(
          screen.getAllByLabelText('Configure rule metadata')[0]
        ).toBeEnabled();
        expect(
          screen.getAllByLabelText('Configure rule metadata')[1]
        ).toBeDisabled();
      }
      fireEvent.change(inputs[0], { target: { value: 'Saved change' } });
      fireEvent.click(screen.getByLabelText(`Save ${noun}`));
      await waitFor(() => expect(API.saveM3URule).toHaveBeenCalledTimes(1));
      await waitFor(() =>
        expect(screen.queryByLabelText(`Save ${noun}`)).not.toBeInTheDocument()
      );
      inputs.forEach((input) => expect(input).toBeDisabled());
      expect(inputs[0]).toHaveValue('Saved change');
      screen
        .getAllByLabelText(`Edit ${noun}`)
        .forEach((edit) => expect(edit).toBeEnabled());
      screen
        .getAllByLabelText(`Move ${noun}`)
        .forEach((handle) => expect(handle).toBeEnabled());
      expect(screen.getByRole('button', { name: `Add ${noun}` })).toBeEnabled();
    }
  );

  it.each(['live', 'movie', 'series', 'filters'])(
    'discards %s row edits and new rows locally without changing saved rules',
    async (scope) => {
      const streamFilters = scope === 'filters';
      const noun = streamFilters ? 'filter' : 'rule';
      API.getM3URules.mockResolvedValue([rule({ scope, filter_type: 'name' })]);
      renderEditor({ scope: streamFilters ? undefined : scope, streamFilters });
      await waitFor(() =>
        expect(screen.getByLabelText(`Edit ${noun}`)).toBeEnabled()
      );
      editRow();
      fireEvent.change(screen.getByLabelText('Regular expression'), {
        target: { value: 'Discarded' },
      });
      fireEvent.click(screen.getByLabelText('Case sensitive'));
      fireEvent.click(screen.getByLabelText(`Discard ${noun} changes`));
      expect(screen.getByLabelText('Regular expression')).toHaveValue('News');
      expect(screen.getByLabelText('Regular expression')).toBeDisabled();
      expect(screen.getByLabelText('Case sensitive').checked).toBe(
        streamFilters
      );
      fireEvent.click(screen.getByRole('button', { name: `Add ${noun}` }));
      const inputs = screen.getAllByLabelText('Regular expression');
      expect(inputs[1]).toBeEnabled();
      expect(inputs[1]).toHaveFocus();
      expect(inputs[0]).toBeDisabled();
      fireEvent.click(screen.getByLabelText(`Discard ${noun} changes`));
      expect(screen.getAllByLabelText('Regular expression')).toHaveLength(1);
      expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
      expect(screen.getByLabelText(`Edit ${noun}`)).toBeEnabled();
      expect(API.saveM3URule).not.toHaveBeenCalled();
      expect(API.deleteM3URule).not.toHaveBeenCalled();
    }
  );

  it.each(['live', 'movie', 'series', 'filters'])(
    'keeps other %s previews locked when a new row is completed but unsaved',
    async (scope) => {
      const streamFilters = scope === 'filters';
      const noun = streamFilters ? 'filter' : 'rule';
      API.getM3URules.mockResolvedValue([rule({ scope, filter_type: 'name' })]);
      renderEditor({ scope: streamFilters ? undefined : scope, streamFilters });
      await waitFor(() =>
        expect(screen.getByLabelText(`Edit ${noun}`)).toBeEnabled()
      );
      fireEvent.click(screen.getByRole('button', { name: `Add ${noun}` }));
      changeField(screen.getAllByLabelText('Regular expression')[1], {
        target: { value: 'New draft' },
      });
      expect(screen.getAllByLabelText(`Preview ${noun}`)[0]).toBeDisabled();
      expect(screen.getAllByLabelText(`Preview ${noun}`)[1]).toBeEnabled();
      fireEvent.click(screen.getAllByLabelText(`Preview ${noun}`)[0]);
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
      expect(API.previewM3URules).not.toHaveBeenCalled();
      expect(screen.getAllByLabelText('Regular expression')[1]).toBeEnabled();
      expect(screen.getAllByLabelText('Regular expression')[1]).toHaveValue(
        'New draft'
      );
      expect(API.saveM3URule).not.toHaveBeenCalled();
      expect(API.refreshLivePlaylist).not.toHaveBeenCalled();
    }
  );

  it.each(['live', 'movie', 'series', 'filters'])(
    'keeps Add in the compact %s table rather than opening a full editor',
    async (scope) => {
      const streamFilters = scope === 'filters';
      renderEditor({ scope: streamFilters ? undefined : scope, streamFilters });
      const add = screen.getByRole('button', {
        name: streamFilters ? 'Add filter' : 'Add rule',
      });
      await waitFor(() => expect(add).toBeEnabled());
      fireEvent.click(add);
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
      expect(screen.getByLabelText('Regular expression')).not.toHaveAttribute(
        'readonly'
      );
      expect(
        screen.getByRole('textbox', { name: 'Rule result', exact: true })
      ).toBeInTheDocument();
      expect(
        screen.getByLabelText(streamFilters ? 'Preview filter' : 'Preview rule')
      ).toBeDisabled();
      expect(
        screen.getByLabelText(streamFilters ? 'Save filter' : 'Save rule')
      ).toBeDisabled();
      expect(API.saveM3URule).not.toHaveBeenCalled();
    }
  );

  it.each(
    ['live', 'movie', 'series', 'filters'].flatMap((scope) =>
      [
        [0, 93, 500],
        [0, 9999],
        [0, 500, 5_000_000],
      ].map((counts) => ({ scope, counts }))
    )
  )(
    'keeps $scope match badges equally wide and fits at least four digits for $counts, including new rows',
    async ({ scope, counts }) => {
      const streamFilters = scope === 'filters';
      const noun = streamFilters ? 'filter' : 'rule';
      API.getM3URules.mockResolvedValue(
        counts.map((_, index) =>
          rule({
            id: index + 1,
            scope,
            filter_type: 'name',
            regex_pattern: `Category${index}`,
            order: index,
          })
        )
      );
      API.analyzeM3URules.mockResolvedValue({
        inventory_count: counts.reduce((total, count) => total + count, 0),
        rule_coverage: counts.map((count, index) => ({
          rule_id: String(index + 1),
          count,
        })),
      });
      renderEditor({ scope: streamFilters ? undefined : scope, streamFilters });
      const badges = await screen.findAllByLabelText(
        /^\d.* matching .*Last saved check/
      );
      expect(badges).toHaveLength(counts.length);
      const characters =
        Math.max(
          (9999).toLocaleString().length,
          ...counts.map((count) => count.toLocaleString().length)
        ) + 1;
      const width = `calc(${characters}ch + var(--badge-padding-x) + var(--badge-padding-x) + var(--badge-border-width) + var(--badge-border-width))`;
      badges.forEach((badge, index) => {
        expect(badge.style.width).toBe(width);
        expect(badge).toHaveTextContent(counts[index].toLocaleString());
        expect(badge.style.flexShrink).toBe('0');
        expect(badge.style.fontVariantNumeric).toBe('tabular-nums');
      });
      fireEvent.click(screen.getByRole('button', { name: `Add ${noun}` }));
      expect(
        screen.getByLabelText('No current check available.').style.width
      ).toBe(width);
      badges.forEach((badge) => expect(badge.style.width).toBe(width));
    }
  );

  it.each(['live', 'movie', 'series', 'filters'])(
    'reserves four-digit space before a %s match check is available',
    async (scope) => {
      const streamFilters = scope === 'filters';
      API.getM3URules.mockResolvedValue([rule({ scope, filter_type: 'name' })]);
      API.analyzeM3URules.mockResolvedValue({
        inventory_count: 0,
        rule_coverage: [],
      });
      renderEditor({ scope: streamFilters ? undefined : scope, streamFilters });
      const badge = await screen.findByLabelText('No current check available.');
      expect(badge.style.width).toBe(
        `calc(${(9999).toLocaleString().length + 1}ch + var(--badge-padding-x) + var(--badge-padding-x) + var(--badge-border-width) + var(--badge-border-width))`
      );
    }
  );

  it.each(['live', 'movie', 'series', 'filters'])(
    'preserves saved %s match counts while adding and editing drafts',
    async (scope) => {
      const streamFilters = scope === 'filters';
      API.getM3URules.mockResolvedValue([
        rule({ scope, filter_type: 'name' }),
        rule({
          id: 2,
          scope,
          filter_type: 'name',
          regex_pattern: 'Sport',
          order: 1,
        }),
      ]);
      API.analyzeM3URules.mockResolvedValue({
        inventory_count: 100,
        rule_coverage: [
          { rule_id: '1', count: 50 },
          { rule_id: '2', count: 0 },
        ],
      });
      renderEditor({ scope: streamFilters ? undefined : scope, streamFilters });
      const unit = streamFilters ? 'streams' : 'categories';
      expect(
        await screen.findByLabelText(new RegExp(`^50 matching ${unit}`))
      ).toHaveTextContent('50');
      expect(
        screen.getByLabelText(new RegExp(`^0 matching ${unit}`))
      ).toHaveTextContent('0');
      expect(API.analyzeM3URules).toHaveBeenCalledTimes(1);
      expect(API.previewM3URules).not.toHaveBeenCalled();
      fireEvent.click(
        screen.getByRole('button', {
          name: streamFilters ? 'Add filter' : 'Add rule',
        })
      );
      expect(
        screen.getByLabelText(new RegExp(`^50 matching ${unit}`))
      ).toHaveTextContent('50');
      expect(
        screen.getByLabelText(new RegExp(`^0 matching ${unit}`))
      ).toHaveTextContent('0');
      expect(
        screen.getAllByLabelText('No current check available.')
      ).toHaveLength(1);
      changeField(screen.getAllByLabelText('Regular expression')[2], {
        target: { value: 'New draft' },
      });
      expect(
        screen.getByLabelText(new RegExp(`^50 matching ${unit}`))
      ).toHaveTextContent('50');
      expect(
        screen.getByLabelText(new RegExp(`^0 matching ${unit}`))
      ).toHaveTextContent('0');
      expect(API.analyzeM3URules).toHaveBeenCalledTimes(1);
      fireEvent.click(screen.getAllByLabelText('Case sensitive')[0]);
      fireEvent.click(
        screen.getAllByLabelText(
          streamFilters ? 'Filter enabled' : 'Rule enabled'
        )[0]
      );
      changeField(screen.getAllByLabelText('Regular expression')[0], {
        target: { value: '[' },
      });
      expect(
        screen.getByLabelText(
          new RegExp(`^50 matching ${unit}.*Last saved check`)
        )
      ).toHaveTextContent('50');
      expect(
        screen.getByLabelText(
          new RegExp(`^0 matching ${unit}.*Last saved check`)
        )
      ).toHaveTextContent('0');
      expect(
        screen.getAllByLabelText('No current check available.')
      ).toHaveLength(1);
      expect(API.analyzeM3URules).toHaveBeenCalledTimes(1);
      expect(API.saveM3URule).not.toHaveBeenCalled();
    }
  );

  it.each(['live', 'movie', 'series', 'filters'])(
    'only enables Save for changed %s rows and disables it after saving or reverting',
    async (scope) => {
      const streamFilters = scope === 'filters';
      API.getM3URules.mockResolvedValue([
        rule({ scope, filter_type: 'name' }),
        rule({
          id: 2,
          scope,
          filter_type: 'name',
          regex_pattern: 'Sport',
          order: 1,
        }),
      ]);
      API.saveM3URule.mockImplementationOnce(
        async (_account, _kind, id, values) => ({ id, ...values })
      );
      renderEditor({ scope: streamFilters ? undefined : scope, streamFilters });
      const label = streamFilters ? 'Save filter' : 'Save rule';
      await waitFor(() =>
        expect(
          screen
            .getAllByLabelText('Regular expression')[0]
            .closest('[aria-busy]')
        ).toHaveAttribute('aria-busy', 'false')
      );
      expect(screen.queryByLabelText(label)).not.toBeInTheDocument();
      editRow();
      const save = screen.getByLabelText(label);
      expect(save).toBeDisabled();
      fireEvent.click(save);
      expect(API.saveM3URule).not.toHaveBeenCalled();
      const input = screen.getAllByLabelText('Regular expression')[0];
      changeField(input, { target: { value: 'News draft' } });
      expect(save).toBeEnabled();
      expect(screen.getByLabelText(/^Edit (rule|filter)$/)).toBeDisabled();
      changeField(input, { target: { value: 'News' } });
      expect(save).toBeDisabled();
      changeField(input, { target: { value: 'News saved' } });
      fireEvent.click(save);
      await waitFor(() => expect(API.saveM3URule).toHaveBeenCalledTimes(1));
      await waitFor(() =>
        expect(screen.queryByLabelText(label)).not.toBeInTheDocument()
      );
      expect(input.closest('tr')).not.toHaveAttribute('data-dirty');
      screen
        .getAllByLabelText(/^Edit (rule|filter)$/)
        .forEach((edit) => expect(edit).toBeEnabled());
    }
  );

  it.each(['live', 'movie', 'series', 'filters'])(
    'replaces preserved %s counts only after the appended draft is saved',
    async (scope) => {
      const streamFilters = scope === 'filters';
      API.getM3URules.mockResolvedValue([rule({ scope, filter_type: 'name' })]);
      API.analyzeM3URules
        .mockResolvedValueOnce({
          inventory_count: 100,
          rule_coverage: [{ rule_id: '1', count: 40 }],
        })
        .mockImplementationOnce(async (_account, _kind, rows) => ({
          inventory_count: 120,
          rule_coverage: rows.map((row, index) => ({
            rule_id: row.preview_id,
            count: index ? 20 : 45,
          })),
        }));
      API.saveM3URule.mockImplementationOnce(
        async (_account, _kind, _id, values) => ({ id: 3, ...values })
      );
      renderEditor({ scope: streamFilters ? undefined : scope, streamFilters });
      const unit = streamFilters ? 'streams' : 'categories';
      await screen.findByLabelText(new RegExp(`^40 matching ${unit}`));
      fireEvent.click(
        screen.getByRole('button', {
          name: streamFilters ? 'Add filter' : 'Add rule',
        })
      );
      changeField(screen.getAllByLabelText('Regular expression')[1], {
        target: { value: 'Sport' },
      });
      expect(
        screen.getByLabelText(new RegExp(`^40 matching ${unit}`))
      ).toHaveTextContent('40');
      fireEvent.click(
        screen.getByLabelText(streamFilters ? 'Save filter' : 'Save rule')
      );
      expect(
        await screen.findByLabelText(new RegExp(`^45 matching ${unit}`))
      ).toHaveTextContent('45');
      expect(
        screen.getByLabelText(new RegExp(`^20 matching ${unit}`))
      ).toHaveTextContent('20');
      expect(
        screen.queryByLabelText('No current check available.')
      ).not.toBeInTheDocument();
      expect(API.analyzeM3URules).toHaveBeenCalledTimes(2);
      expect(API.saveM3URule).toHaveBeenCalledTimes(1);
    }
  );

  it.each([false, true])(
    'keeps the last saved counts and blocks Add while editing a checked rule (filters=%s)',
    async (streamFilters) => {
      API.getM3URules.mockResolvedValue([rule({ filter_type: 'name' })]);
      API.analyzeM3URules.mockResolvedValue({
        inventory_count: 100,
        rule_coverage: [{ rule_id: '1', count: 40 }],
      });
      renderEditor({ streamFilters });
      await screen.findByLabelText(/^40 matching/);
      changeField(screen.getByLabelText('Regular expression'), {
        target: { value: 'Changed' },
      });
      fireEvent.click(
        screen.getByRole('button', {
          name: streamFilters ? 'Add filter' : 'Add rule',
        })
      );
      expect(
        screen.getByLabelText(/^40 matching.*Last saved check/)
      ).toHaveTextContent('40');
      expect(
        screen.queryByLabelText('No current check available.')
      ).not.toBeInTheDocument();
      expect(screen.getAllByLabelText('Regular expression')).toHaveLength(1);
      expect(API.analyzeM3URules).toHaveBeenCalledTimes(1);
    }
  );

  it.each(['live', 'movie', 'series', 'filters'])(
    'keeps saved %s counts through validation failure and pending Save, then updates after success',
    async (scope) => {
      const streamFilters = scope === 'filters';
      API.getM3URules.mockResolvedValue([
        rule({ scope, filter_type: 'name' }),
        rule({
          id: 2,
          scope,
          filter_type: 'name',
          regex_pattern: 'Sport',
          order: 1,
        }),
      ]);
      API.analyzeM3URules.mockResolvedValueOnce({
        inventory_count: 100,
        rule_coverage: [
          { rule_id: '1', count: 50 },
          { rule_id: '2', count: 20 },
        ],
      });
      renderEditor({ scope: streamFilters ? undefined : scope, streamFilters });
      const count = (value) =>
        screen.getByLabelText(new RegExp(`^${value} matching`));
      await screen.findByLabelText(/^50 matching/);
      changeField(screen.getAllByLabelText('Regular expression')[0], {
        target: { value: 'Changed' },
      });
      API.analyzeM3URules.mockRejectedValueOnce({
        status: 400,
        body: { rules: [{ regex_pattern: ['Validation failed'] }, {}] },
      });
      fireEvent.click(
        screen.getByLabelText(streamFilters ? 'Save filter' : 'Save rule')
      );
      await waitFor(() =>
        expect(
          screen.getAllByLabelText('Regular expression')[0]
        ).toHaveAttribute('aria-invalid', 'true')
      );
      expect(count(50)).toHaveTextContent('50');
      expect(count(20)).toHaveTextContent('20');
      expect(API.saveM3URule).not.toHaveBeenCalled();
      API.analyzeM3URules.mockResolvedValueOnce({
        inventory_count: 100,
        rule_coverage: [
          { rule_id: '1', count: 10 },
          { rule_id: '2', count: 60 },
        ],
      });
      let finish;
      API.saveM3URule.mockImplementationOnce(
        (_account, _kind, id, values) =>
          new Promise((resolve) => {
            finish = () => resolve({ id, ...values });
          })
      );
      await waitFor(() =>
        expect(
          screen.getByLabelText(streamFilters ? 'Save filter' : 'Save rule')
        ).toBeEnabled()
      );
      fireEvent.click(
        screen.getByLabelText(streamFilters ? 'Save filter' : 'Save rule')
      );
      await waitFor(() => expect(API.saveM3URule).toHaveBeenCalledTimes(1));
      expect(count(50)).toHaveTextContent('50');
      expect(count(20)).toHaveTextContent('20');
      await act(async () => finish());
      expect(count(10)).toHaveTextContent('10');
      expect(count(60)).toHaveTextContent('60');
      expect(screen.queryByLabelText(/^50 matching/)).not.toBeInTheDocument();
    }
  );

  it.each(['live', 'movie', 'series', 'filters'])(
    'locks all %s drag handles while a new row exists and unlocks after Save or discard',
    async (scope) => {
      const streamFilters = scope === 'filters';
      const noun = streamFilters ? 'filter' : 'rule';
      API.getM3URules.mockResolvedValue([
        rule({ scope, filter_type: 'name' }),
        rule({
          id: 2,
          scope,
          filter_type: 'name',
          regex_pattern: 'Sport',
          order: 1,
        }),
      ]);
      API.saveM3URule.mockImplementationOnce(
        async (_account, _kind, _id, values) => ({ id: 3, ...values })
      );
      renderEditor({ scope: streamFilters ? undefined : scope, streamFilters });
      const handles = () => screen.getAllByLabelText(`Move ${noun}`);
      await waitFor(() => expect(handles()[0]).toBeEnabled());
      fireEvent.click(screen.getByRole('button', { name: `Add ${noun}` }));
      expect(handles()).toHaveLength(3);
      handles().forEach((handle) => expect(handle).toBeDisabled());
      const newInput = screen.getAllByLabelText('Regular expression')[2];
      const newId = newInput.closest('tr').getAttribute('data-rule-id');
      await act(async () => {
        await drag.onEnd({ active: { id: 2 }, over: { id: 1 } });
        await drag.onEnd({ active: { id: newId }, over: { id: 1 } });
      });
      expect(API.reorderM3URules).not.toHaveBeenCalled();
      expect(screen.getAllByLabelText('Regular expression')[0]).toHaveValue(
        'News'
      );
      changeField(newInput, { target: { value: 'Saved new' } });
      fireEvent.click(screen.getByLabelText(`Save ${noun}`));
      await waitFor(() =>
        handles().forEach((handle) => expect(handle).toBeEnabled())
      );
      fireEvent.click(screen.getByRole('button', { name: `Add ${noun}` }));
      handles().forEach((handle) => expect(handle).toBeDisabled());
      fireEvent.click(screen.getByLabelText(`Discard ${noun} changes`));
      await waitFor(() =>
        handles().forEach((handle) => expect(handle).toBeEnabled())
      );
      expect(API.deleteM3URule).not.toHaveBeenCalled();
      expect(API.reorderM3URules).not.toHaveBeenCalled();
    }
  );

  it('keeps preview edits open on failed validation or write and allows Save to be retried', async () => {
    await load();
    fireEvent.click(screen.getByLabelText('Preview rule'));
    const preview = await screen.findByRole('dialog');
    await within(preview).findByText(/1 matching/);
    changeField(within(preview).getByLabelText('Preview regular expression'), {
      target: { value: '[' },
    });
    API.analyzeM3URules.mockRejectedValueOnce({
      status: 400,
      body: { rules: [{ regex_pattern: ['Invalid expression'] }] },
    });
    fireEvent.click(
      within(preview).getByRole('button', { name: 'Save', exact: true })
    );
    expect(await within(preview).findByRole('alert')).toHaveTextContent(
      'Invalid expression'
    );
    expect(API.saveM3URule).not.toHaveBeenCalled();
    expect(screen.getByLabelText('Regular expression')).toHaveValue('News');
    changeField(within(preview).getByLabelText('Preview regular expression'), {
      target: { value: 'Corrected' },
    });
    API.saveM3URule.mockRejectedValueOnce({
      status: 500,
      body: { detail: 'Write failed' },
    });
    fireEvent.click(
      within(preview).getByRole('button', { name: 'Save', exact: true })
    );
    expect(await within(preview).findByRole('alert')).toHaveTextContent(
      'Write failed'
    );
    expect(
      within(preview).getByLabelText('Preview regular expression')
    ).toHaveValue('Corrected');
    API.saveM3URule.mockResolvedValueOnce(rule({ regex_pattern: 'Corrected' }));
    fireEvent.click(
      within(preview).getByRole('button', { name: 'Save', exact: true })
    );
    await waitFor(() => expect(preview).not.toBeInTheDocument());
    expect(screen.getByLabelText('Regular expression')).toHaveValue(
      'Corrected'
    );
    expect(API.saveApplyM3UGroupRules).not.toHaveBeenCalled();
    expect(API.refreshLivePlaylist).not.toHaveBeenCalled();
  });

  it('blocks another row preview and preserves the active table draft', async () => {
    const onStateChange = vi.fn();
    API.getM3URules.mockResolvedValue([
      rule(),
      rule({ id: 2, regex_pattern: 'Sport', order: 1 }),
    ]);
    renderEditor({ onStateChange });
    await waitFor(() =>
      expect(screen.getAllByLabelText('Preview rule')[0]).toBeEnabled()
    );
    changeField(screen.getAllByLabelText('Regular expression')[1], {
      target: { value: 'Unrelated draft' },
    });
    const preview = screen.getAllByLabelText('Preview rule')[0];
    expect(preview).toBeDisabled();
    fireEvent.click(preview);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(API.previewM3URules).not.toHaveBeenCalled();
    expect(API.saveM3URule).not.toHaveBeenCalled();
    expect(screen.getAllByLabelText('Regular expression')[1]).toHaveValue(
      'Unrelated draft'
    );
    expect(
      screen.getAllByLabelText('Regular expression')[1].closest('tr')
    ).toHaveAttribute('data-dirty', 'true');
    expect(onStateChange).toHaveBeenLastCalledWith(
      expect.objectContaining({ dirty: true })
    );
  });

  it.each(['live', 'movie', 'series', 'filters'])(
    'restores the table and locks %s preview expressions until Edit, with Try and direct Save',
    async (scope) => {
      const streamFilters = scope === 'filters';
      API.getM3URules.mockResolvedValue([
        rule({
          scope,
          filter_type: 'name',
          exclude: true,
          custom_properties: { case_sensitive: false },
        }),
      ]);
      API.saveM3URule.mockImplementationOnce(
        async (_account, _kind, id, values) => ({ id, ...values })
      );
      renderEditor({ scope: streamFilters ? undefined : scope, streamFilters });
      const trigger = await screen.findByLabelText(
        `Preview ${streamFilters ? 'filter' : 'rule'}`
      );
      await waitFor(() => expect(trigger).toBeEnabled());
      const tableInput = screen.getByLabelText('Regular expression');
      expect(tableInput).not.toHaveAttribute('readonly');
      expect(
        screen.queryByLabelText(/Edit (rule|filter) expression/)
      ).not.toBeInTheDocument();
      fireEvent.click(trigger);
      const preview = await screen.findByRole('dialog');
      await within(preview).findByText(/1 matching/);
      const input = within(preview).getByLabelText(
        'Preview regular expression'
      );
      expect(input).toHaveAttribute('readonly');
      expect(input).toBeDisabled();
      input.focus();
      expect(input).not.toHaveFocus();
      expect(
        within(preview).getByRole('button', { name: 'Save', exact: true })
      ).toBeDisabled();
      expect(
        within(preview).getByLabelText('Preview case sensitive')
      ).toBeDisabled();
      fireEvent.click(
        within(preview).getByLabelText('Edit preview expression')
      );
      expect(input).not.toHaveAttribute('readonly');
      expect(input).toBeEnabled();
      expect(input).toHaveFocus();
      expect(
        within(preview).getByLabelText('Preview case sensitive')
      ).toBeEnabled();
      changeField(input, { target: { value: '^Sport$' } });
      fireEvent.click(within(preview).getByLabelText('Preview case sensitive'));
      expect(within(preview).getByText('Not tested')).toBeInTheDocument();
      expect(within(preview).queryByRole('table')).not.toBeInTheDocument();
      expect(API.saveM3URule).not.toHaveBeenCalled();
      expect(tableInput).toHaveValue('News');
      fireEvent.click(
        within(preview).getByRole('button', { name: 'Try', exact: true })
      );
      await within(preview).findByText(/1 matching/);
      expect(API.previewM3URules).toHaveBeenLastCalledWith(
        7,
        streamFilters ? 'filters' : 'group-rules',
        [
          expect.objectContaining({
            preview_id: '1',
            regex_pattern: '^Sport$',
          }),
        ],
        1,
        1,
        50,
        { notifyOnError: false }
      );
      expect(API.saveM3URule).not.toHaveBeenCalled();
      expect(
        within(preview).queryByRole('button', { name: 'Change', exact: true })
      ).not.toBeInTheDocument();
      if (streamFilters)
        expect(
          within(preview).queryByText(/Apply|Play/)
        ).not.toBeInTheDocument();
      fireEvent.click(
        within(preview).getByRole('button', { name: 'Save', exact: true })
      );
      await waitFor(() => expect(preview).not.toBeInTheDocument());
      expect(API.saveM3URule).toHaveBeenCalledTimes(1);
      expect(API.saveM3URule).toHaveBeenCalledWith(
        7,
        streamFilters ? 'filters' : 'group-rules',
        1,
        expect.objectContaining({
          regex_pattern: '^Sport$',
          ...(streamFilters
            ? { custom_properties: { case_sensitive: true } }
            : { case_sensitive: true }),
        })
      );
      expect(screen.getByLabelText('Regular expression')).toHaveValue(
        '^Sport$'
      );
      expect(
        screen.getByLabelText('Regular expression').closest('tr')
      ).not.toHaveAttribute('data-dirty');
      expect(API.saveApplyM3UGroupRules).not.toHaveBeenCalled();
      expect(API.refreshLivePlaylist).not.toHaveBeenCalled();
    }
  );

  it('discards preview-only edits on close, including a successfully tested expression', async () => {
    await load();
    fireEvent.click(screen.getByLabelText('Preview rule'));
    const preview = await screen.findByRole('dialog');
    await within(preview).findByText(/1 matching/);
    changeField(within(preview).getByLabelText('Preview regular expression'), {
      target: { value: 'Sport' },
    });
    fireEvent.click(
      within(preview).getByRole('button', { name: 'Try', exact: true })
    );
    await within(preview).findByText(/1 matching/);
    closePreview(preview);
    await waitFor(() =>
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    );
    expect(screen.getByLabelText('Regular expression')).toHaveValue('News');
    expect(
      screen.getByLabelText('Regular expression').closest('tr')
    ).not.toHaveAttribute('data-dirty');
    expect(API.saveM3URule).not.toHaveBeenCalled();
  });

  it('allows testing a first unsaved stream filter against the selected category cache', async () => {
    renderEditor({ streamFilters: true, previewGroupIds: [9] });
    await waitFor(() => expect(screen.getByText('Add filter')).toBeEnabled());
    fireEvent.click(screen.getByText('Add filter'));
    changeField(screen.getByLabelText('Regular expression'), {
      target: { value: 'Sport' },
    });
    expect(screen.getByLabelText('Preview filter')).toBeEnabled();
    fireEvent.click(screen.getByLabelText('Preview filter'));
    await screen.findByRole('dialog');
    await screen.findByText('1 matching streams from 1 streams');
    expect(API.previewM3URules).toHaveBeenLastCalledWith(
      7,
      'filters',
      [expect.objectContaining({ regex_pattern: 'Sport' })],
      expect.stringMatching(/^new-/),
      1,
      50,
      { notifyOnError: false, groupIds: [9] }
    );
    expect(API.saveM3URule).not.toHaveBeenCalled();
    expect(API.refreshLivePlaylist).not.toHaveBeenCalled();
  });

  it('shows backend regex errors once and permits correction and retry without saving', async () => {
    await load();
    fireEvent.click(screen.getByLabelText('Preview rule'));
    const preview = await screen.findByRole('dialog');
    await within(preview).findByText(/1 matching/);
    changeField(within(preview).getByLabelText('Preview regular expression'), {
      target: { value: '[' },
    });
    API.previewM3URules.mockRejectedValueOnce(
      new Error('Invalid regular expression.')
    );
    fireEvent.click(
      within(preview).getByRole('button', { name: 'Try', exact: true })
    );
    expect(await within(preview).findByRole('alert')).toHaveTextContent(
      'Invalid regular expression.'
    );
    expect(within(preview).queryByText(/0 matching/)).not.toBeInTheDocument();
    expect(
      within(preview).getByRole('button', { name: 'Save', exact: true })
    ).toBeEnabled();
    expect(
      within(preview).queryByText('Apply to existing')
    ).not.toBeInTheDocument();
    changeField(within(preview).getByLabelText('Preview regular expression'), {
      target: { value: 'Sport' },
    });
    expect(within(preview).queryByRole('alert')).not.toBeInTheDocument();
    fireEvent.click(
      within(preview).getByRole('button', { name: 'Try', exact: true })
    );
    await within(preview).findByText(/1 matching/);
    expect(within(preview).getByRole('button', { name: 'Save' })).toBeEnabled();
    expect(showNotification).not.toHaveBeenCalled();
    expect(API.saveM3URule).not.toHaveBeenCalled();
  });

  it('ignores a late test response after the expression has changed', async () => {
    await load();
    fireEvent.click(screen.getByLabelText('Preview rule'));
    const preview = await screen.findByRole('dialog');
    await within(preview).findByText(/1 matching/);
    let finishOld;
    API.previewM3URules.mockReturnValueOnce(
      new Promise((resolve) => {
        finishOld = resolve;
      })
    );
    const input = within(preview).getByLabelText('Preview regular expression');
    changeField(input, { target: { value: 'Old' } });
    fireEvent.click(
      within(preview).getByRole('button', { name: 'Try', exact: true })
    );
    changeField(input, { target: { value: 'New' } });
    await act(async () =>
      finishOld({
        count: 99,
        inventory_count: 100,
        results: [{ name: 'Stale result' }],
      })
    );
    expect(within(preview).getByText('Not tested')).toBeInTheDocument();
    expect(within(preview).queryByText('Stale result')).not.toBeInTheDocument();
    fireEvent.keyDown(input, { key: 'Enter' });
    await within(preview).findByText(/1 matching/);
    expect(API.previewM3URules).toHaveBeenLastCalledWith(
      7,
      'group-rules',
      [expect.objectContaining({ regex_pattern: 'New' })],
      1,
      1,
      50,
      { notifyOnError: false }
    );
  });

  it.each([false, true])(
    'shows nested backend regex validation as plain text (indexed object: %s)',
    async (indexed) => {
      await load();
      API.previewM3URules.mockRejectedValueOnce({
        status: 400,
        body: {
          rules: indexed
            ? {
                0: {
                  regex_pattern: [
                    'Invalid regular expression: unterminated character set.',
                  ],
                },
              }
            : [
                {
                  regex_pattern: [
                    'Invalid regular expression: unterminated character set.',
                  ],
                },
              ],
        },
      });
      fireEvent.click(screen.getByLabelText('Preview rule'));
      const preview = await screen.findByRole('dialog');
      expect(await within(preview).findByRole('alert')).toHaveTextContent(
        'Invalid regular expression: unterminated character set.'
      );
      expect(within(preview).getByRole('alert')).not.toHaveTextContent(
        /rules:|regex_pattern|\{"0"/
      );
      expect(API.saveM3URule).not.toHaveBeenCalled();
      expect(showNotification).not.toHaveBeenCalled();
    }
  );

  it('identifies another draft row when its regex prevents a complete ordered preview', async () => {
    await load([rule(), rule({ id: 2, order: 1, regex_pattern: '[' })]);
    API.previewM3URules.mockRejectedValueOnce({
      status: 400,
      body: {
        rules: { 1: { regex_pattern: ['Invalid regular expression.'] } },
      },
    });
    fireEvent.click(screen.getAllByLabelText('Preview rule')[0]);
    const preview = await screen.findByRole('dialog');
    expect(await within(preview).findByRole('alert')).toHaveTextContent(
      'Rule 2: Invalid regular expression.'
    );
    expect(API.saveM3URule).not.toHaveBeenCalled();
  });

  it('explains in preview when an earlier rule captures all matching categories', async () => {
    await load([
      rule({ regex_pattern: '.*' }),
      rule({ id: 2, order: 1, regex_pattern: 'News' }),
    ]);
    API.previewM3URules.mockResolvedValue({
      count: 0,
      inventory_count: 10,
      results: [],
      rule_coverage: [
        { rule_id: '1', count: 10 },
        { rule_id: '2', count: 0 },
      ],
    });
    fireEvent.click(screen.getAllByLabelText('Preview rule')[1]);
    const preview = await screen.findByRole('dialog');
    expect(await within(preview).findByRole('alert')).toHaveTextContent(
      'Covered by rule 1'
    );
    expect(
      within(preview).getByRole('button', { name: 'Apply to existing' })
    ).toBeDisabled();
  });

  it('resets pagination when testing a different regex and invalidates the previous Apply', async () => {
    await load();
    API.previewM3URules.mockResolvedValue({
      count: 250,
      inventory_count: 300,
      results: [],
    });
    fireEvent.click(screen.getByLabelText('Preview rule'));
    const preview = await screen.findByRole('dialog');
    await within(preview).findByText(
      '250 matching categories from 300 categories'
    );
    fireEvent.click(within(preview).getByRole('button', { name: '5' }));
    await waitFor(() => expect(API.previewM3URules).toHaveBeenCalledTimes(2));
    await within(preview).findByText(
      '250 matching categories from 300 categories'
    );
    changeField(within(preview).getByLabelText('Preview regular expression'), {
      target: { value: 'Sport' },
    });
    expect(
      within(preview).queryByText('Apply to existing')
    ).not.toBeInTheDocument();
    fireEvent.click(
      within(preview).getByRole('button', { name: 'Try', exact: true })
    );
    await within(preview).findByText(
      '250 matching categories from 300 categories'
    );
    expect(API.previewM3URules).toHaveBeenLastCalledWith(
      7,
      'group-rules',
      expect.any(Array),
      1,
      1,
      50,
      { notifyOnError: false }
    );
    expect(
      within(preview).queryByText('Apply to existing')
    ).not.toBeInTheDocument();
    expect(API.saveApplyM3UGroupRules).not.toHaveBeenCalled();
  });

  it.each([false, true])(
    'uses Streams in standard playlist previews (stream filters: %s)',
    async (streamFilters) => {
      API.getM3URules.mockResolvedValue([
        rule(streamFilters ? { filter_type: 'name', exclude: true } : {}),
      ]);
      renderEditor({ accountType: 'STD', streamFilters });
      const label = streamFilters ? 'Preview filter' : 'Preview rule';
      await waitFor(() => expect(screen.getByLabelText(label)).toBeEnabled());
      fireEvent.click(screen.getByLabelText(label));
      await screen.findByText(
        '1 matching ' +
          (streamFilters
            ? 'streams from 1 streams'
            : 'categories from 1 categories')
      );
      expect(screen.queryByText(/Live TV/)).not.toBeInTheDocument();
      if (streamFilters) {
        const preview = screen.getByRole('dialog', {
          name: 'Stream filters preview',
        });
        expect(
          within(preview).queryByRole('button', { name: /Refresh/ })
        ).not.toBeInTheDocument();
      }
      expect(API.refreshLivePlaylist).not.toHaveBeenCalled();
      expect(API.saveApplyM3UGroupRules).not.toHaveBeenCalled();
    }
  );
  it('tests setup filters against the draft selection without offering an early refresh', async () => {
    API.getM3URules.mockResolvedValue([
      rule({ filter_type: 'name', exclude: true }),
    ]);
    API.analyzeM3URules.mockResolvedValue({ inventory_count: 10 });
    renderEditor({ streamFilters: true, previewGroupIds: [9, 12] });
    await waitFor(() =>
      expect(screen.getByLabelText('Preview filter')).toBeEnabled()
    );
    expect(API.analyzeM3URules).toHaveBeenCalledWith(
      7,
      'filters',
      expect.any(Array),
      { groupIds: [9, 12] }
    );
    fireEvent.click(screen.getByLabelText('Preview filter'));
    const preview = await screen.findByRole('dialog', {
      name: 'Stream filters preview',
    });
    await within(preview).findByText('Category preview');
    expect(API.previewM3URules).toHaveBeenCalledWith(
      7,
      'filters',
      expect.any(Array),
      1,
      1,
      50,
      { groupIds: [9, 12], notifyOnError: false }
    );
    expect(
      within(preview).queryByRole('button', { name: 'Refresh Live TV' })
    ).not.toBeInTheDocument();
    expect(API.refreshLivePlaylist).not.toHaveBeenCalled();
  });
  it('never offers a refresh or applies category rules from the stream preview', async () => {
    API.getM3URules.mockResolvedValue([
      rule({ filter_type: 'name', exclude: true }),
    ]);
    API.analyzeM3URules.mockResolvedValue({ inventory_count: 10 });
    renderEditor({ streamFilters: true });
    await waitFor(() =>
      expect(screen.getByLabelText('Preview filter')).toBeEnabled()
    );
    fireEvent.click(screen.getByLabelText('Preview filter'));
    const preview = await screen.findByRole('dialog', {
      name: 'Stream filters preview',
    });
    await within(preview).findByText('1 matching streams from 1 streams');
    expect(
      within(preview).queryByRole('button', {
        name: /Refresh|Apply to existing/,
      })
    ).not.toBeInTheDocument();
    fireEvent.click(
      within(preview).getByRole('button', { name: 'Try', exact: true })
    );
    await waitFor(() => expect(API.previewM3URules).toHaveBeenCalledTimes(2));
    expect(API.refreshLivePlaylist).not.toHaveBeenCalled();
    expect(API.saveM3URule).not.toHaveBeenCalled();
    expect(API.saveApplyM3UGroupRules).not.toHaveBeenCalled();
  });
  it('shows zero filter matches without offering a refresh', async () => {
    API.getM3URules.mockResolvedValue([
      rule({ filter_type: 'name', exclude: true }),
    ]);
    API.analyzeM3URules.mockResolvedValue({ inventory_count: 10 });
    API.previewM3URules.mockResolvedValue({
      count: 0,
      inventory_count: 10,
      results: [],
    });
    renderEditor({ streamFilters: true });
    await waitFor(() =>
      expect(screen.getByLabelText('Preview filter')).toBeEnabled()
    );
    fireEvent.click(screen.getByLabelText('Preview filter'));
    const preview = await screen.findByRole('dialog', {
      name: 'Stream filters preview',
    });
    await within(preview).findByText('0 matching streams from 10 streams');
    expect(
      within(preview).queryByRole('button', { name: /Refresh/ })
    ).not.toBeInTheDocument();
    expect(API.refreshLivePlaylist).not.toHaveBeenCalled();
  });
  beforeEach(() => {
    vi.clearAllMocks();
    Object.values(API).forEach((mock) => mock.mockReset());
    useM3URuleChecks.setState({ checks: {} });
    API.getM3URules.mockResolvedValue([]);
    API.analyzeM3URules.mockResolvedValue({ inventory_count: 1 });
    API.previewM3URules.mockResolvedValue({
      count: 1,
      inventory_count: 1,
      results: [
        {
          name: 'News',
          currently_enabled: false,
          would_enable: true,
          item_count: 3,
        },
      ],
    });
    API.saveM3URule.mockResolvedValue(rule());
    API.saveApplyM3UGroupRules.mockResolvedValue({
      updated: 1,
      target_ids: [9],
      scope: 'live',
      enabled: true,
    });
  });

  it.each(['movie', 'series'])(
    'opens the shared %s metadata editor from one overlay spanning all four fields and discards with X',
    async (scope) => {
      const metadata = {
        audio_languages: ['ger'],
        subtitle_languages: ['eng'],
        resolution: '1080p',
        video_features: ['hdr'],
      };
      API.getM3URules.mockResolvedValue([
        rule({ scope, metadata_defaults: metadata }),
      ]);
      renderEditor({ scope });
      const trigger = await screen.findByRole('button', {
        name: 'Configure rule metadata',
      });
      await waitFor(() =>
        expect(screen.getByLabelText('Edit rule')).toBeEnabled()
      );
      editRow();
      await waitFor(() => expect(trigger).toBeEnabled());
      expect(trigger.closest('td')).toHaveAttribute('colspan', '4');
      expect(trigger).toHaveClass(classes.metadataOverlay);
      for (const field of ['DUB', 'SUB', 'Resolution', 'Features']) {
        expect(
          screen.getByRole('group', { name: field, exact: true })
        ).toBeInTheDocument();
        expect(
          screen.queryByLabelText(`Edit ${field} rule metadata`)
        ).not.toBeInTheDocument();
      }
      fireEvent.click(trigger);
      const editor = await screen.findByRole('dialog', {
        name: 'Rule metadata defaults',
      });
      expect(
        within(editor).getByRole('group', { name: 'Category content settings' })
      ).toBeInTheDocument();
      for (const field of ['DUB languages', 'SUB languages', 'Video features'])
        expect(within(editor).getByLabelText(`Choose ${field}`)).toBeEnabled();
      fireEvent.click(
        within(editor).getByRole('textbox', { name: 'Resolution' })
      );
      fireEvent.click(screen.getByRole('option', { name: '2160p' }));
      fireEvent.click(
        within(editor).getByRole('button', {
          name: 'Close rule metadata defaults',
        })
      );
      await waitFor(() =>
        expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
      );
      expect(screen.getByLabelText('Preview rule')).toBeEnabled();
      expect(screen.getByText('1080p', { exact: true })).toBeInTheDocument();
      expect(API.saveM3URule).not.toHaveBeenCalled();
    }
  );

  it('opens the shared metadata editor using the keyboard', async () => {
    const user = userEvent.setup();
    API.getM3URules.mockResolvedValue([
      rule({ scope: 'movie', metadata_defaults: {} }),
    ]);
    renderEditor({ scope: 'movie' });
    const trigger = await screen.findByRole('button', {
      name: 'Configure rule metadata',
    });
    await waitFor(() =>
      expect(screen.getByLabelText('Edit rule')).toBeEnabled()
    );
    editRow();
    await waitFor(() => expect(trigger).toBeEnabled());
    trigger.focus();
    await user.keyboard('{Enter}');
    expect(
      await screen.findByRole('dialog', { name: 'Rule metadata defaults' })
    ).toBeInTheDocument();
    expect(API.saveM3URule).not.toHaveBeenCalled();
  });

  it('leaves untouched empty rule metadata unset instead of assigning an empty default', async () => {
    API.getM3URules.mockResolvedValue([
      rule({ scope: 'movie', metadata_defaults: {} }),
    ]);
    renderEditor({ scope: 'movie' });
    const trigger = await screen.findByRole('button', {
      name: 'Configure rule metadata',
    });
    await waitFor(() =>
      expect(screen.getByLabelText('Edit rule')).toBeEnabled()
    );
    editRow();
    await waitFor(() => expect(trigger).toBeEnabled());
    fireEvent.click(trigger);
    const editor = await screen.findByRole('dialog', {
      name: 'Rule metadata defaults',
    });
    fireEvent.click(
      within(editor).getByRole('button', { name: 'Apply', exact: true })
    );
    expect(screen.getByLabelText('Preview rule')).toBeEnabled();
    expect(API.saveM3URule).not.toHaveBeenCalled();
  });

  it.each(['live', 'movie', 'series'])(
    'only offers category-name matching for new %s import rules',
    async (scope) => {
      renderEditor({ scope });
      await waitFor(() =>
        expect(screen.getByRole('button', { name: 'Add rule' })).toBeEnabled()
      );
      fireEvent.click(screen.getByRole('button', { name: 'Add rule' }));
      expect(
        screen.getByRole('columnheader', { name: 'Category name (regex)' })
      ).toBeInTheDocument();
      expect(
        screen.queryByRole('columnheader', { name: 'Match', exact: true })
      ).not.toBeInTheDocument();
      expect(
        screen.queryByRole('columnheader', { name: 'Item mode' })
      ).not.toBeInTheDocument();
      expect(
        screen.queryByLabelText('Rule match field')
      ).not.toBeInTheDocument();
      expect(
        screen.queryByLabelText('Item matching mode')
      ).not.toBeInTheDocument();
      expect(screen.queryByText(/Legacy item names/)).not.toBeInTheDocument();
      changeField(screen.getByLabelText('Regular expression'), {
        target: { value: 'News' },
      });
      fireEvent.click(screen.getByLabelText('Save rule'));
      await waitFor(() =>
        expect(API.saveM3URule).toHaveBeenCalledWith(
          7,
          'group-rules',
          null,
          expect.objectContaining({
            scope,
            regex_pattern: 'News',
          })
        )
      );
    }
  );

  it('keeps stream filter fields without exposing category-only controls or legacy import notices', async () => {
    API.getM3URules.mockResolvedValue([
      {
        id: 1,
        filter_type: 'name',
        regex_pattern: 'News',
        exclude: true,
        order: 0,
      },
    ]);
    renderEditor({ streamFilters: true });
    await waitFor(() =>
      expect(screen.getByLabelText('Edit filter')).toBeEnabled()
    );
    expect(
      screen.getByRole('columnheader', { name: 'Field' })
    ).toBeInTheDocument();
    expect(
      screen.getByRole('columnheader', { name: 'Regular expression' })
    ).toBeInTheDocument();
    expect(
      screen.queryByText(/Existing contained-item rules/)
    ).not.toBeInTheDocument();
  });

  it.each([
    { scope: 'live' },
    { scope: 'movie' },
    { scope: 'series' },
    { scope: 'live', streamFilters: true },
  ])('centers the actions header and controls for %o', async (props) => {
    API.getM3URules.mockResolvedValue([
      props.streamFilters
        ? {
            id: 1,
            filter_type: 'name',
            regex_pattern: 'News',
            order: 0,
            exclude: true,
          }
        : rule({ scope: props.scope }),
    ]);
    renderEditor(props);
    const save = await screen.findByRole('button', {
      name: props.streamFilters ? 'Edit filter' : 'Edit rule',
    });
    expect(screen.getByRole('columnheader', { name: 'Actions' })).toHaveClass(
      classes.centeredCell
    );
    expect(save.closest('td')).toHaveClass(classes.centeredCell);
    expect(save.parentElement.style.getPropertyValue('--group-justify')).toBe(
      'center'
    );
  });

  it.each(['movie', 'series'])(
    'shows one regex warning rather than repeating it for each %s metadata field',
    async (scope) => {
      const metadata_defaults = {
        audio_languages: ['eng'],
        subtitle_languages: ['ger'],
        resolution: '1080p',
        video_features: ['hdr'],
      };
      API.getM3URules.mockResolvedValue([
        rule({ scope, regex_pattern: '.*', metadata_defaults }),
      ]);
      API.analyzeM3URules.mockResolvedValue({
        inventory_count: 500,
        rule_coverage: [
          {
            rule_id: '1',
            count: 500,
            field_counts: Object.fromEntries(
              ['import', ...Object.keys(metadata_defaults)].map((field) => [
                field,
                500,
              ])
            ),
          },
        ],
      });
      renderEditor({ scope });
      const marker = await screen.findByRole('img', {
        name: /Matches all 500/,
      });
      for (const label of ['DUB', 'SUB', 'Resolution', 'Features'])
        expect(marker.getAttribute('aria-label')).toContain(label);
      await waitFor(() =>
        expect(showNotification).toHaveBeenCalledWith(
          expect.objectContaining({
            title: 'Import rule warning',
            message:
              'Matches all 500 categories from the last refresh. Check whether this is intended. Later rules may have no effect.',
          })
        )
      );
      expect(API.saveM3URule).not.toHaveBeenCalled();
    }
  );

  it.each(['movie', 'series'])(
    'edits shared %s rule metadata while preserving explicit empty values and removing only unset fields',
    async (scope) => {
      const row = rule({
        scope,
        metadata_defaults: {
          audio_languages: [],
          resolution: '1080p',
          video_features: [],
        },
      });
      const next = { audio_languages: ['eng'], video_features: [] };
      API.getM3URules.mockResolvedValue([row]);
      API.saveM3URule.mockResolvedValue({ ...row, metadata_defaults: next });
      renderEditor({ scope });
      const trigger = await screen.findByRole('button', {
        name: 'Configure rule metadata',
      });
      await waitFor(() =>
        expect(screen.getByLabelText('Edit rule')).toBeEnabled()
      );
      editRow();
      await waitFor(() => expect(trigger).toBeEnabled());
      fireEvent.click(trigger);
      const editor = await screen.findByRole('dialog', {
        name: 'Rule metadata defaults',
      });
      expect(within(editor).getAllByText('Empty default')).toHaveLength(2);
      fireEvent.click(
        within(editor).getByRole('button', {
          name: 'Do not set Resolution with this rule',
        })
      );
      fireEvent.click(within(editor).getByLabelText('Choose DUB languages'));
      const picker = await screen.findByRole('dialog', {
        name: 'Select DUB languages',
      });
      fireEvent.click(
        within(picker).getByRole('checkbox', { name: 'English (eng)' })
      );
      fireEvent.keyDown(picker, { key: 'Escape' });
      fireEvent.click(
        within(editor).getByRole('button', { name: 'Apply', exact: true })
      );
      expect(API.saveM3URule).not.toHaveBeenCalled();
      fireEvent.click(screen.getByLabelText('Save rule'));
      await waitFor(() =>
        expect(API.saveM3URule).toHaveBeenCalledWith(
          7,
          'group-rules',
          1,
          expect.objectContaining({ scope, metadata_defaults: next })
        )
      );
    }
  );

  it('applies all shared metadata fields only to the rule draft and saves them with the rule', async () => {
    const metadata = {
      audio_languages: ['ger'],
      subtitle_languages: ['eng'],
      resolution: '1080p',
      video_features: ['hdr'],
    };
    const row = rule({
      scope: 'movie',
      action: 'enable',
      metadata_defaults: metadata,
    });
    const next = {
      ...metadata,
      audio_languages: ['ger', 'eng'],
      resolution: '2160p',
    };
    API.getM3URules.mockResolvedValue([row]);
    API.saveM3URule.mockResolvedValue({ ...row, metadata_defaults: next });
    renderEditor({ scope: 'movie' });
    const trigger = await screen.findByRole('button', {
      name: 'Configure rule metadata',
    });
    await waitFor(() =>
      expect(screen.getByLabelText('Edit rule')).toBeEnabled()
    );
    editRow();
    await waitFor(() => expect(trigger).toBeEnabled());
    fireEvent.click(trigger);
    const editor = await screen.findByRole('dialog', {
      name: 'Rule metadata defaults',
    });
    fireEvent.click(within(editor).getByLabelText('Choose DUB languages'));
    const picker = await screen.findByRole('dialog', {
      name: 'Select DUB languages',
    });
    fireEvent.click(
      within(picker).getByRole('checkbox', { name: 'English (eng)' })
    );
    fireEvent.keyDown(picker, { key: 'Escape' });
    fireEvent.click(
      within(editor).getByRole('textbox', { name: 'Resolution' })
    );
    fireEvent.click(screen.getByRole('option', { name: '2160p' }));
    fireEvent.click(
      within(editor).getByRole('button', { name: 'Apply', exact: true })
    );
    expect(API.saveM3URule).not.toHaveBeenCalled();
    const dub = screen.getByRole('group', { name: 'DUB', exact: true });
    expect(within(dub).getByText('ger', { exact: true })).toBeInTheDocument();
    expect(within(dub).getByText('eng', { exact: true })).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText('Save rule'));
    await waitFor(() =>
      expect(API.saveM3URule).toHaveBeenCalledWith(
        7,
        'group-rules',
        1,
        expect.objectContaining({ action: 'enable', metadata_defaults: next })
      )
    );
  });

  it.each(['live', 'movie', 'series'])(
    'offers compact Enabled, Disabled and Ignore results for %s',
    async (scope) => {
      renderEditor({ scope });
      await waitFor(() =>
        expect(screen.getByRole('button', { name: 'Add rule' })).toBeEnabled()
      );
      fireEvent.click(screen.getByRole('button', { name: 'Add rule' }));
      fireEvent.click(screen.getByRole('textbox', { name: 'Rule result' }));
      expect(
        (await screen.findAllByRole('option')).map(
          (option) => option.textContent
        )
      ).toEqual(['Enabled', 'Disabled', 'Ignore']);
      expect(
        screen.getByRole('option', { name: 'Disabled', exact: true })
      ).toHaveStyle({ whiteSpace: 'nowrap' });
      expect(
        screen.queryByRole('option', { name: 'Ignore category' })
      ).not.toBeInTheDocument();
      expect(
        screen.queryByRole('option', { name: 'Keep import selection' })
      ).not.toBeInTheDocument();
    }
  );

  it.each(['keep'])(
    'retains the metadata of a paused %s rule until the import result is explicitly reviewed',
    async (action) => {
      const user = userEvent.setup();
      const row = rule({
        scope: 'movie',
        action,
        requires_review: true,
        metadata_defaults: { audio_languages: ['eng'] },
      });
      API.getM3URules.mockResolvedValue([row]);
      API.saveM3URule.mockResolvedValue({
        ...row,
        action: 'disable',
        requires_review: false,
        enabled: false,
      });
      renderEditor({ scope: 'movie' });
      await waitFor(() =>
        expect(
          screen.getByLabelText('Regular expression').closest('[aria-busy]')
        ).toHaveAttribute('aria-busy', 'false')
      );
      editRow();
      expect(screen.getByLabelText('Save rule')).toBeDisabled();
      expect(screen.getByText('Paused · review result')).toBeInTheDocument();
      expect(screen.getByLabelText('Rule enabled')).toBeDisabled();
      expect(screen.getByLabelText('Rule enabled')).not.toBeChecked();
      expect(screen.getByLabelText('Preview rule')).toBeDisabled();
      expect(API.saveM3URule).not.toHaveBeenCalled();
      expect(showNotification).not.toHaveBeenCalled();
      await user.click(screen.getByRole('textbox', { name: 'Rule result' }));
      expect(
        screen.getByRole('textbox', { name: 'Rule result' })
      ).toHaveAttribute('data-expanded', 'true');
      expect(
        (await screen.findAllByRole('option')).map(
          (option) => option.textContent
        )
      ).toEqual(['Enabled', 'Disabled', 'Ignore']);
      fireEvent.click(screen.getByRole('option', { name: 'Disabled' }));
      expect(screen.getByLabelText('Rule enabled')).toBeEnabled();
      expect(screen.getByLabelText('Rule enabled')).not.toBeChecked();
      expect(screen.getByText('eng', { exact: true })).toBeInTheDocument();
      fireEvent.click(screen.getByLabelText('Save rule'));
      await waitFor(() =>
        expect(API.saveM3URule).toHaveBeenCalledWith(
          7,
          'group-rules',
          1,
          expect.objectContaining({
            action: 'disable',
            enabled: false,
            metadata_defaults: { audio_languages: ['eng'] },
          })
        )
      );
    }
  );

  it('keeps a retired result paused and only shows save validation when Save is pressed', async () => {
    API.getM3URules.mockResolvedValue([
      rule({ scope: 'series', action: 'keep', metadata_defaults: {} }),
    ]);
    renderEditor({ scope: 'series' });
    await waitFor(() =>
      expect(
        screen.getByLabelText('Regular expression').closest('[aria-busy]')
      ).toHaveAttribute('aria-busy', 'false')
    );
    expect(showNotification).not.toHaveBeenCalled();
    editRow();
    expect(screen.getByLabelText('Save rule')).toBeDisabled();
    changeField(screen.getByLabelText('Regular expression'), {
      target: { value: 'Changed' },
    });
    fireEvent.click(screen.getByLabelText('Save rule'));
    await waitFor(() =>
      expect(showNotification).toHaveBeenCalledWith(
        expect.objectContaining({
          color: 'red',
          message:
            'Choose Enabled, Disabled or Ignore before saving this paused rule.',
        })
      )
    );
    expect(API.saveM3URule).not.toHaveBeenCalled();
  });

  it('keeps metadata controls out of Live TV import rules', async () => {
    await load();
    expect(
      screen.queryByLabelText('Configure rule metadata')
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole('columnheader', { name: 'DUB' })
    ).not.toBeInTheDocument();
  });
  it.each(['movie', 'series'])(
    'shows configured %s metadata above the preview table without adding per-row columns',
    async (scope) => {
      API.getM3URules.mockResolvedValue([
        rule({
          scope,
          metadata_defaults: {
            audio_languages: ['ger', 'eng'],
            subtitle_languages: [],
            resolution: '2160p',
            video_features: ['hdr', 'dv'],
          },
        }),
      ]);
      renderEditor({ scope });
      await waitFor(() =>
        expect(screen.getByLabelText('Preview rule')).toBeEnabled()
      );
      fireEvent.click(screen.getByLabelText('Preview rule'));
      const preview = await screen.findByRole('dialog', {
        name: 'Import rules preview',
      });
      const defaults = await within(preview).findByRole('group', {
        name: 'Rule metadata defaults',
      });
      for (const text of [
        'DUB',
        'SUB',
        'Resolution',
        'Features',
        'ger',
        'eng',
        'None',
        '2160p',
        'HDR',
        'Dolby Vision',
      ])
        expect(
          within(defaults).getByText(text, { exact: true })
        ).toBeInTheDocument();
      expect(
        within(preview)
          .getAllByRole('columnheader')
          .map((el) => el.textContent)
      ).toEqual(['Name', 'Current', 'Result', 'Items']);
      expect(
        defaults.compareDocumentPosition(within(preview).getByRole('table')) &
          Node.DOCUMENT_POSITION_FOLLOWING
      ).toBeTruthy();
      expect(API.saveM3URule).not.toHaveBeenCalled();
    }
  );
  it('loads only the selected account and scope', async () => {
    await load();
    expect(API.getM3URules).toHaveBeenCalledWith(7, 'group-rules', 'live');
  });
  it.each([false, true])(
    'allows only one unsaved new row and unlocks Add after save or delete (filters=%s)',
    async (streamFilters) => {
      renderEditor({ streamFilters });
      const add = await screen.findByRole('button', {
        name: streamFilters ? 'Add filter' : 'Add rule',
      });
      await waitFor(() => expect(add).toBeEnabled());
      fireEvent.click(add);
      expect(add).toBeDisabled();
      fireEvent.click(add);
      fireEvent.click(add);
      expect(screen.getAllByLabelText('Regular expression')).toHaveLength(1);
      expect(
        screen.getByLabelText(streamFilters ? 'Save filter' : 'Save rule')
      ).toBeDisabled();
      changeField(screen.getByLabelText('Regular expression'), {
        target: { value: ' ' },
      });
      fireEvent.click(
        screen.getByLabelText(streamFilters ? 'Save filter' : 'Save rule')
      );
      await waitFor(() =>
        expect(screen.getByLabelText('Regular expression')).toHaveAttribute(
          'aria-invalid',
          'true'
        )
      );
      expect(add).toBeDisabled();
      changeField(screen.getByLabelText('Regular expression'), {
        target: { value: 'AFR' },
      });
      expect(API.analyzeM3URules).not.toHaveBeenCalled();
      API.saveM3URule.mockResolvedValue(
        rule({ id: 9, regex_pattern: 'AFR', filter_type: 'name' })
      );
      fireEvent.click(
        screen.getByLabelText(streamFilters ? 'Save filter' : 'Save rule')
      );
      await waitFor(() => expect(add).toBeEnabled());
      expect(API.saveM3URule).toHaveBeenCalledTimes(1);
      fireEvent.click(add);
      expect(add).toBeDisabled();
      fireEvent.click(
        screen.getByLabelText(
          streamFilters ? 'Discard filter changes' : 'Discard rule changes'
        )
      );
      await waitFor(() => expect(add).toBeEnabled());
      expect(API.deleteM3URule).not.toHaveBeenCalled();
    }
  );
  it.each([false, true])(
    'keeps loading, saving and deleting quiet without a flashing loader (stream filters=%s)',
    async (streamFilters) => {
      let finish;
      API.getM3URules.mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            finish = resolve;
          })
      );
      const saved = streamFilters
        ? rule({ filter_type: 'name', exclude: false })
        : rule();
      const { container } = renderEditor({ streamFilters });
      const add = screen.getByRole('button', {
        name: streamFilters ? 'Add filter' : 'Add rule',
      });
      const expectQuietBusy = () => {
        expect(container.querySelector('[aria-busy="true"]')).not.toBeNull();
        expect(container.querySelector('.mantine-Loader-root')).toBeNull();
        expect(add).toBeDisabled();
      };
      expectQuietBusy();
      await act(async () => finish([saved]));
      await screen.findByDisplayValue('News');
      API.saveM3URule.mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            finish = resolve;
          })
      );
      changeField(screen.getByLabelText('Regular expression'), {
        target: { value: 'Sport' },
      });
      fireEvent.click(
        screen.getByLabelText(streamFilters ? 'Save filter' : 'Save rule')
      );
      expectQuietBusy();
      await waitFor(() => expect(API.saveM3URule).toHaveBeenCalledTimes(1));
      await act(async () => finish({ ...saved, regex_pattern: 'Sport' }));
      API.deleteM3URule.mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            finish = resolve;
          })
      );
      fireEvent.click(
        screen.getByLabelText(streamFilters ? 'Delete filter' : 'Delete rule')
      );
      fireEvent.click(screen.getByText('Confirm delete'));
      expectQuietBusy();
      await act(async () => finish());
      expect(add).not.toBeDisabled();
    }
  );
  it.each([false, true])(
    'keeps only order guidance and a quiet empty state without table headings (stream filters=%s)',
    async (streamFilters) => {
      renderEditor({ streamFilters });
      const empty = await screen.findByText(
        streamFilters ? 'No stream filters' : 'No import rules'
      );
      expect(empty.closest('[role="alert"]')).toBeNull();
      const guidance = screen
        .getByText('Order matters.')
        .closest('[role="alert"]');
      expect(guidance).toHaveAttribute('data-variant', 'light');
      expect(guidance).toHaveStyle({
        '--alert-color': 'var(--mantine-color-blue-light-color)',
      });
      expect(screen.queryByRole('table')).not.toBeInTheDocument();
      expect(screen.queryByRole('columnheader')).not.toBeInTheDocument();
      const add = screen.getByRole('button', {
        name: streamFilters ? 'Add filter' : 'Add rule',
      });
      expect(guidance.parentElement).toContainElement(add);
      expect(guidance.parentElement).toHaveStyle({
        '--group-align': 'flex-end',
      });
      expect(
        guidance.compareDocumentPosition(add) & Node.DOCUMENT_POSITION_FOLLOWING
      ).toBeTruthy();
      expect(
        add.compareDocumentPosition(empty) & Node.DOCUMENT_POSITION_FOLLOWING
      ).toBeTruthy();
      expect(guidance).not.toHaveTextContent(
        /category import rules remain separate|Without filters|Existing selections|Filters decide|New unmatched/
      );
      fireEvent.click(
        screen.getByRole('button', {
          name: streamFilters ? 'Add filter' : 'Add rule',
        })
      );
      expect(screen.getByRole('table')).toBeInTheDocument();
      expect(empty).not.toBeInTheDocument();
      expect(
        add.compareDocumentPosition(screen.getByRole('table')) &
          Node.DOCUMENT_POSITION_FOLLOWING
      ).toBeTruthy();
      expect(
        screen.queryByText(
          'Save all changes before previewing. The complete ordered list affects the result.'
        )
      ).not.toBeInTheDocument();
      expect(
        screen.getByRole('button', {
          name: streamFilters ? 'Preview filter' : 'Preview rule',
        })
      ).toBeDisabled();
    }
  );
  it('saves future policy without applying it or refreshing', async () => {
    await load();
    changeField(screen.getByLabelText('Regular expression'), {
      target: { value: 'Sport' },
    });
    fireEvent.click(screen.getByLabelText('Save rule'));
    await waitFor(() =>
      expect(API.saveM3URule).toHaveBeenCalledWith(
        7,
        'group-rules',
        1,
        expect.objectContaining({ regex_pattern: 'Sport' })
      )
    );
    expect(API.saveApplyM3UGroupRules).not.toHaveBeenCalled();
  });
  it('notifies about a blank pattern, marks its row and never submits it', async () => {
    renderEditor();
    await waitFor(() => expect(API.getM3URules).toHaveBeenCalled());
    fireEvent.click(screen.getByText('Add rule'));
    changeField(screen.getByLabelText('Regular expression'), {
      target: { value: ' ' },
    });
    fireEvent.click(screen.getByLabelText('Save rule'));
    expect(showNotification).toHaveBeenCalledWith(
      expect.objectContaining({
        title: 'Import rule was not saved',
        message: 'Enter a regular expression before saving.',
        color: 'red',
        autoClose: false,
      })
    );
    expect(
      screen.queryByText('Enter a regular expression before saving.')
    ).not.toBeInTheDocument();
    expect(screen.getByLabelText('Regular expression')).toHaveAttribute(
      'aria-invalid',
      'true'
    );
    expect(
      screen.getByLabelText('Regular expression').closest('tr')
    ).toHaveAttribute('data-invalid', 'true');
    expect(API.saveM3URule).not.toHaveBeenCalled();
    await waitFor(() =>
      expect(screen.getByLabelText('Save rule')).toBeEnabled()
    );
  });
  it('previews only the active row draft while another saved row stays locked', async () => {
    await load([rule(), rule({ id: 2, order: 1, regex_pattern: 'Sport' })]);
    changeField(screen.getAllByLabelText('Regular expression')[0], {
      target: { value: '^Changed$' },
    });
    expect(screen.getAllByLabelText('Preview rule')[0]).toBeEnabled();
    expect(screen.getAllByLabelText('Preview rule')[1]).toBeDisabled();
    expect(API.previewM3URules).not.toHaveBeenCalled();
    fireEvent.click(screen.getAllByLabelText('Preview rule')[0]);
    await screen.findByText('1 matching categories from 1 categories');
    expect(API.previewM3URules).toHaveBeenCalledWith(
      7,
      'group-rules',
      [
        expect.objectContaining({
          preview_id: '1',
          regex_pattern: '^Changed$',
        }),
        expect.objectContaining({ preview_id: '2', regex_pattern: 'Sport' }),
      ],
      1,
      1,
      50,
      { notifyOnError: false }
    );
    expect(API.saveM3URule).not.toHaveBeenCalled();
    expect(screen.queryByText('Apply to existing')).not.toBeInTheDocument();
  });
  it('tests a newly added rule without saving it first', async () => {
    renderEditor();
    await waitFor(() => expect(API.getM3URules).toHaveBeenCalled());
    fireEvent.click(screen.getByText('Add rule'));
    expect(screen.getByLabelText('Preview rule')).toBeDisabled();
    changeField(screen.getByLabelText('Regular expression'), {
      target: { value: '###' },
    });
    expect(screen.getByLabelText('Preview rule')).toBeEnabled();
    fireEvent.click(screen.getByLabelText('Preview rule'));
    await screen.findByText('1 matching categories from 1 categories');
    expect(API.previewM3URules.mock.calls[0][2][0]).toEqual(
      expect.objectContaining({
        preview_id: expect.stringMatching(/^new-/),
        regex_pattern: '###',
      })
    );
    expect(API.saveM3URule).not.toHaveBeenCalled();
    expect(screen.queryByText('Apply to existing')).not.toBeInTheDocument();
  });
  it('saves and applies precisely the previewed snapshot', async () => {
    await load();
    fireEvent.click(screen.getByLabelText('Preview rule'));
    await screen.findByText('1 matching categories from 1 categories');
    fireEvent.click(screen.getByText('Apply to existing'));
    expect(API.saveApplyM3UGroupRules).not.toHaveBeenCalled();
    const confirmation = screen.getByRole('alertdialog');
    expect(confirmation).toHaveTextContent('all 1 matching categories');
    expect(confirmation).toHaveTextContent(
      'Apply this rule to all 1 matching categories?'
    );
    fireEvent.click(within(confirmation).getByText('Apply'));
    await waitFor(() =>
      expect(API.saveApplyM3UGroupRules).toHaveBeenCalledWith(
        7,
        [expect.objectContaining({ preview_id: '1', regex_pattern: 'News' })],
        1
      )
    );
  });
  it('does not preview or apply retired results to existing selections', async () => {
    await load([rule({ action: 'keep' })]);
    expect(screen.getByLabelText('Preview rule')).toBeDisabled();
    expect(API.previewM3URules).not.toHaveBeenCalled();
  });
  it.each(['live', 'movie', 'series', 'filters'])(
    'uses a switch, keeps Case next to regex and blocks disabled %s previews',
    async (scope) => {
      const streamFilters = scope === 'filters';
      API.getM3URules.mockResolvedValue([
        rule({ scope, filter_type: 'name', enabled: false }),
      ]);
      renderEditor({ scope: streamFilters ? 'live' : scope, streamFilters });
      await waitFor(() =>
        expect(
          screen.getByLabelText('Regular expression').closest('[aria-busy]')
        ).toHaveAttribute('aria-busy', 'false')
      );
      const toggle = screen.getByRole('switch', {
        name: streamFilters ? 'Filter enabled' : 'Rule enabled',
      });
      expect(toggle).not.toBeChecked();
      expect(
        screen.getByLabelText(`Preview ${streamFilters ? 'filter' : 'rule'}`)
      ).toBeDisabled();
      const regexCell = screen
        .getByLabelText('Regular expression')
        .closest('td');
      expect(regexCell.nextElementSibling).toContainElement(
        screen.getByLabelText('Case sensitive')
      );
      const headers = screen.getAllByRole('columnheader');
      const regexIndex = headers.findIndex((header) =>
        /regex|Regular expression/.test(header.textContent)
      );
      expect(headers[regexIndex + 1]).toHaveTextContent('Case');
      expect(API.previewM3URules).not.toHaveBeenCalled();
      editRow();
      fireEvent.click(toggle);
      fireEvent.click(
        screen.getByLabelText(`Save ${streamFilters ? 'filter' : 'rule'}`)
      );
      await waitFor(() =>
        expect(API.saveM3URule).toHaveBeenCalledWith(
          7,
          streamFilters ? 'filters' : 'group-rules',
          1,
          expect.objectContaining({ enabled: true })
        )
      );
    }
  );

  it('requires confirmation for all disable matches and leaves the preview read-only on cancel', async () => {
    API.previewM3URules.mockResolvedValue({
      count: 500,
      inventory_count: 500,
      results: [
        {
          name: 'Movie category',
          currently_enabled: true,
          would_enable: false,
          item_count: 2,
          metadata_defaults: { audio_languages: ['eng'], resolution: '1080p' },
        },
      ],
    });
    API.getM3URules.mockResolvedValue([
      rule({
        scope: 'movie',
        regex_pattern: '.*',
        action: 'disable',
        metadata_defaults: { audio_languages: ['eng'] },
      }),
    ]);
    renderEditor({ scope: 'movie' });
    await waitFor(() =>
      expect(screen.getByLabelText('Preview rule')).toBeEnabled()
    );
    fireEvent.click(screen.getByLabelText('Preview rule'));
    const preview = await screen.findByRole('dialog', {
      name: 'Import rules preview',
    });
    await within(preview).findByText('Movie category');
    expect(
      within(preview).queryByRole('columnheader', {
        name: /DUB|SUB|Resolution|Features/,
      })
    ).not.toBeInTheDocument();
    fireEvent.click(within(preview).getByText('Apply to existing'));
    const confirmation = screen.getByRole('alertdialog');
    expect(confirmation).toHaveTextContent('all 500 matching categories');
    expect(confirmation).toHaveTextContent(
      'Apply this rule to all 500 matching categories?'
    );
    fireEvent.click(within(confirmation).getByText('Cancel'));
    expect(API.saveApplyM3UGroupRules).not.toHaveBeenCalled();
    expect(preview).toBeInTheDocument();
    fireEvent.click(within(preview).getByText('Apply to existing'));
    fireEvent.click(within(screen.getByRole('alertdialog')).getByText('Apply'));
    await waitFor(() =>
      expect(API.saveApplyM3UGroupRules).toHaveBeenCalledTimes(1)
    );
  });
  it('blocks reordering while a row is being edited and allows it after discard', async () => {
    await load([rule(), rule({ id: 2, order: 1, regex_pattern: 'Sport' })]);
    changeField(screen.getAllByLabelText('Regular expression')[0], {
      target: { value: 'Unsaved' },
    });
    fireEvent.click(screen.getByText('Move second first'));
    expect(API.reorderM3URules).not.toHaveBeenCalled();
    fireEvent.click(screen.getByLabelText('Discard rule changes'));
    fireEvent.click(screen.getByText('Move second first'));
    await waitFor(() =>
      expect(API.reorderM3URules).toHaveBeenCalledWith(
        7,
        'group-rules',
        [2, 1],
        'live',
        [0, 1]
      )
    );
    expect(API.saveM3URule).not.toHaveBeenCalled();
    expect(screen.getAllByLabelText('Regular expression')[1]).toHaveValue(
      'News'
    );
  });
  it('requires confirmation before deleting a saved rule', async () => {
    await load();
    fireEvent.click(screen.getByLabelText('Delete rule'));
    expect(API.deleteM3URule).not.toHaveBeenCalled();
    fireEvent.click(screen.getByText('Confirm delete'));
    await waitFor(() =>
      expect(API.deleteM3URule).toHaveBeenCalledWith(7, 'group-rules', 1)
    );
  });
  it.each([false, true])(
    'rechecks remaining saved rows and updates or clears coverage after deletion (filters=%s)',
    async (streamFilters) => {
      const rows = [
        rule({ filter_type: 'name' }),
        rule({ id: 2, order: 1, regex_pattern: '(?:)', filter_type: 'name' }),
        rule({ id: 3, order: 2, regex_pattern: 'Sport', filter_type: 'name' }),
      ];
      API.getM3URules.mockResolvedValue(rows);
      API.deleteM3URule.mockResolvedValue(undefined);
      API.analyzeM3URules
        .mockResolvedValueOnce({
          inventory_count: 100,
          rule_coverage: [
            { rule_id: '1', count: 10 },
            { rule_id: '2', count: 90 },
            { rule_id: '3', count: 0 },
          ],
        })
        .mockResolvedValueOnce({
          inventory_count: 100,
          rule_coverage: [
            { rule_id: '2', count: 100 },
            { rule_id: '3', count: 0 },
          ],
        })
        .mockResolvedValueOnce({
          inventory_count: 100,
          rule_coverage: [{ rule_id: '3', count: 20 }],
        });
      const { container } = renderEditor({ streamFilters });
      await screen.findByRole('img', { name: /Matches all 90 remaining/ });
      showNotification.mockClear();
      const deleteFirst = async () => {
        fireEvent.click(
          screen.getAllByLabelText(
            streamFilters ? 'Delete filter' : 'Delete rule'
          )[0]
        );
        fireEvent.click(screen.getByText('Confirm delete'));
      };
      await deleteFirst();
      await screen.findByRole('img', { name: /Matches all 100/ });
      expect(
        container.querySelectorAll('tr[data-warning="true"]')
      ).toHaveLength(1);
      expect(
        container.querySelectorAll('tr[data-covered="true"]')
      ).toHaveLength(1);
      expect(showNotification).toHaveBeenCalledWith(
        expect.objectContaining({
          message: expect.stringContaining('Matches all 100'),
          color: 'yellow',
        })
      );
      expect(API.analyzeM3URules).toHaveBeenLastCalledWith(
        7,
        streamFilters ? 'filters' : 'group-rules',
        expect.arrayContaining([
          expect.objectContaining({ preview_id: '2' }),
          expect.objectContaining({ preview_id: '3' }),
        ])
      );
      await deleteFirst();
      await waitFor(() =>
        expect(
          container.querySelectorAll(
            'tr[data-warning="true"],tr[data-covered="true"]'
          )
        ).toHaveLength(0)
      );
      expect(hideNotification).toHaveBeenCalledWith(
        `account-rules-7-${streamFilters ? 'filters' : 'group-rules'}-coverage`
      );
      await deleteFirst();
      await screen.findByText(
        streamFilters ? 'No stream filters' : 'No import rules'
      );
      expect(API.analyzeM3URules).toHaveBeenCalledTimes(3);
    }
  );

  it.each([false, true])(
    'blocks deleting a saved row while an invalid new draft is active (filters=%s)',
    async (streamFilters) => {
      API.getM3URules.mockResolvedValue([rule({ filter_type: 'name' })]);
      API.deleteM3URule.mockResolvedValue(undefined);
      renderEditor({ streamFilters });
      await waitFor(() =>
        expect(
          screen.getByLabelText('Regular expression').closest('[aria-busy]')
        ).toHaveAttribute('aria-busy', 'false')
      );
      fireEvent.click(
        screen.getByRole('button', {
          name: streamFilters ? 'Add filter' : 'Add rule',
        })
      );
      changeField(screen.getAllByLabelText('Regular expression')[1], {
        target: { value: ' ' },
      });
      fireEvent.click(
        screen.getByLabelText(streamFilters ? 'Save filter' : 'Save rule')
      );
      await waitFor(() =>
        expect(
          screen.getAllByLabelText('Regular expression')[1]
        ).toHaveAttribute('aria-invalid', 'true')
      );
      const deletion = screen.getByLabelText(
        streamFilters ? 'Delete filter' : 'Delete rule'
      );
      expect(deletion).toBeDisabled();
      fireEvent.click(deletion);
      expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
      expect(API.deleteM3URule).not.toHaveBeenCalled();
      expect(screen.getAllByLabelText('Regular expression')).toHaveLength(2);
      expect(
        screen.getByRole('button', {
          name: streamFilters ? 'Add filter' : 'Add rule',
        })
      ).toBeDisabled();
      expect(showNotification).toHaveBeenLastCalledWith(
        expect.objectContaining({
          color: 'red',
          autoClose: false,
          message: 'Enter a regular expression before saving.',
        })
      );
    }
  );
  it('paginates beyond the former first-200 limit', async () => {
    await load();
    API.previewM3URules.mockResolvedValue({
      count: 250,
      inventory_count: 250,
      results: [],
    });
    fireEvent.click(screen.getByLabelText('Preview rule'));
    await screen.findByText('250 matching categories from 250 categories');
    expect(
      screen.getByText('250 matching categories from 250 categories')
    ).not.toHaveStyle({ color: 'var(--mantine-color-yellow-light-color)' });
    fireEvent.click(
      within(screen.getByRole('dialog')).getByRole('button', { name: '5' })
    );
    await waitFor(() =>
      expect(API.previewM3URules).toHaveBeenLastCalledWith(
        7,
        'group-rules',
        expect.any(Array),
        1,
        5,
        50,
        { notifyOnError: false }
      )
    );
  });
  it('uses the persisted pre-filter catalog for stream filters', async () => {
    API.getM3URules.mockResolvedValue([
      {
        id: 1,
        filter_type: 'name',
        regex_pattern: '###',
        exclude: true,
        order: 0,
        custom_properties: { case_sensitive: false },
      },
    ]);
    API.previewM3URules.mockResolvedValue({
      count: 1,
      inventory_count: 10,
      catalog_complete: true,
      last_completed_refresh: '2026-10-14T06:00:00Z',
      results: [{ name: '### Event', group: 'Events', result: 'exclude' }],
    });
    renderEditor({ streamFilters: true, scope: undefined });
    await screen.findByDisplayValue('###');
    fireEvent.click(screen.getByLabelText('Preview filter'));
    expect(
      await screen.findByText('Data: 14.10.2026 08:00')
    ).toBeInTheDocument();
    expect(screen.getByText('### Event')).toBeInTheDocument();
    expect(screen.queryByText('Apply to existing')).not.toBeInTheDocument();
  });
  it('checks Live category rules without requiring category contents', async () => {
    API.getM3URules.mockResolvedValue([
      rule({ scope: 'live', regex_pattern: '.*' }),
    ]);
    API.analyzeM3URules.mockResolvedValue({
      inventory_count: 3,
      rule_coverage: [{ rule_id: '1', count: 1 }],
    });
    renderEditor({ scope: 'live' });
    await waitFor(() =>
      expect(screen.getByLabelText('Preview rule')).toBeEnabled()
    );
    expect(
      screen.queryByText(/Item-name checks|contained-item|Legacy item/)
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText('Checked against 3 available streams.')
    ).not.toBeInTheDocument();
  });

  it('keeps missing stream data in the disabled preview tooltip, not a status line', async () => {
    API.getM3URules.mockResolvedValue([
      rule({ filter_type: 'name', exclude: true }),
    ]);
    API.analyzeM3URules.mockResolvedValue({
      inventory_count: 0,
      rule_coverage: [{ rule_id: '1', count: 0 }],
    });
    renderEditor({ streamFilters: true });
    await waitFor(() =>
      expect(screen.getByLabelText('Preview filter')).toBeDisabled()
    );
    expect(
      screen.queryByText(/Effect not yet checked|Checked against/)
    ).not.toBeInTheDocument();
    const preview = screen.getByLabelText('Preview filter');
    expect(preview).toBeDisabled();
    expect(preview.parentElement).toHaveAttribute('tabindex', '0');
    expect(preview.parentElement).toHaveAttribute(
      'aria-label',
      'No stream data available for preview.'
    );
    fireEvent.click(preview);
    expect(API.previewM3URules).not.toHaveBeenCalled();
    expect(showNotification).not.toHaveBeenCalled();
  });
  it('allows preparing a filter before the first import without claiming its effect was checked', async () => {
    API.analyzeM3URules.mockResolvedValue({ inventory_count: 0 });
    API.saveM3URule.mockResolvedValue(
      rule({ filter_type: 'name', regex_pattern: 'Sports', exclude: true })
    );
    renderEditor({ streamFilters: true });
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Add filter' })).toBeEnabled()
    );
    fireEvent.click(screen.getByRole('button', { name: 'Add filter' }));
    changeField(screen.getByLabelText('Regular expression'), {
      target: { value: 'Sports' },
    });
    expect(API.analyzeM3URules).not.toHaveBeenCalled();
    fireEvent.click(screen.getByLabelText('Save filter'));
    await waitFor(() => expect(API.saveM3URule).toHaveBeenCalled());
    expect(API.saveM3URule).toHaveBeenCalledWith(
      7,
      'filters',
      null,
      expect.objectContaining({ regex_pattern: 'Sports', exclude: true })
    );
    expect(screen.getByLabelText('Preview filter')).toBeDisabled();
    expect(showNotification).toHaveBeenCalledWith(
      expect.objectContaining({
        title: 'Stream filter saved',
        color: 'gray',
        message: 'Saved. No stream data available for testing.',
      })
    );
    expect(API.previewM3URules).not.toHaveBeenCalled();
  });
  it('unlocks preview after reopening with stream inventory even when every stream is excluded', async () => {
    API.getM3URules.mockResolvedValue([
      rule({ filter_type: 'name', regex_pattern: '^', exclude: true }),
    ]);
    API.analyzeM3URules.mockResolvedValue({ inventory_count: 0 });
    const first = renderEditor({ streamFilters: true });
    await waitFor(() =>
      expect(screen.getByLabelText('Preview filter')).toBeDisabled()
    );
    first.unmount();
    API.analyzeM3URules.mockResolvedValue({
      inventory_count: 10,
      rule_coverage: [{ rule_id: '1', count: 10 }],
    });
    renderEditor({ streamFilters: true });
    await waitFor(() =>
      expect(screen.getByLabelText('Preview filter')).toBeEnabled()
    );
    expect(
      screen.queryByText(/Checked against|Effect not yet checked/)
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole('img', { name: /Matches all 10/ })
    ).toBeInTheDocument();
  });
  it('requires saving new stream filters and reports validation errors in a notification', async () => {
    renderEditor({ streamFilters: true });
    await waitFor(() => expect(API.getM3URules).toHaveBeenCalled());
    fireEvent.click(screen.getByText('Add filter'));
    expect(screen.getByLabelText('Preview filter')).toBeDisabled();
    changeField(screen.getByLabelText('Regular expression'), {
      target: { value: ' ' },
    });
    fireEvent.click(screen.getByLabelText('Save filter'));
    expect(showNotification).toHaveBeenCalledWith(
      expect.objectContaining({
        title: 'Stream filter was not saved',
        message: 'Enter a regular expression before saving.',
        color: 'red',
        autoClose: false,
      })
    );
    expect(
      screen.queryByText('Enter a regular expression before saving.')
    ).not.toBeInTheDocument();
    expect(screen.getByLabelText('Regular expression')).toHaveAttribute(
      'aria-invalid',
      'true'
    );
    expect(API.previewM3URules).not.toHaveBeenCalled();
    expect(API.saveM3URule).not.toHaveBeenCalled();
    await waitFor(() =>
      expect(
        screen.getByLabelText('Regular expression').closest('[aria-busy]')
      ).toHaveAttribute('aria-busy', 'false')
    );
    changeField(screen.getByLabelText('Regular expression'), {
      target: { value: '(?i)News' },
    });
    API.saveM3URule.mockResolvedValue({
      id: 3,
      filter_type: 'name',
      regex_pattern: '(?i)News',
      exclude: true,
      order: 0,
      custom_properties: { case_sensitive: false },
    });
    fireEvent.click(screen.getByLabelText('Save filter'));
    await waitFor(() =>
      expect(screen.getByLabelText('Preview filter')).toBeEnabled()
    );
    expect(API.saveM3URule).toHaveBeenCalledWith(
      7,
      'filters',
      null,
      expect.objectContaining({ regex_pattern: '(?i)News' })
    );
  });
  it('keeps the server validation marker while allowing a read-only preview to correct the expression', async () => {
    await load();
    changeField(screen.getByLabelText('Regular expression'), {
      target: { value: '[' },
    });
    API.saveM3URule.mockRejectedValue({
      status: 400,
      body: { regex_pattern: ['Invalid regular expression.'] },
    });
    fireEvent.click(screen.getByLabelText('Save rule'));
    await waitFor(() =>
      expect(screen.getByLabelText('Regular expression')).toHaveAttribute(
        'aria-invalid',
        'true'
      )
    );
    expect(
      screen.queryByText(/Invalid regular expression/)
    ).not.toBeInTheDocument();
    expect(showNotification).not.toHaveBeenCalled();
    expect(screen.getByLabelText('Regular expression')).toHaveAttribute(
      'aria-invalid',
      'true'
    );
    expect(screen.getByLabelText('Preview rule')).toBeEnabled();
    expect(screen.getAllByRole('alert')).toHaveLength(1);
    expect(screen.getByRole('alert')).toHaveTextContent('Order matters.');
  });
  it('does not show a failed evaluation as zero matches or duplicate its error', async () => {
    await load();
    API.previewM3URules.mockRejectedValue(new Error('Preview unavailable'));
    fireEvent.click(screen.getByLabelText('Preview rule'));
    const preview = await screen.findByRole('dialog');
    expect(await within(preview).findByRole('alert')).toHaveTextContent(
      'Preview unavailable'
    );
    expect(showNotification).not.toHaveBeenCalled();
    expect(
      screen.queryByText('0 matching categories from 0 categories')
    ).not.toBeInTheDocument();
    expect(screen.getByText('Preview unavailable')).toBeInTheDocument();
  });
  it.each(['live', 'movie', 'series', 'filters'])(
    'locks saved %s previews until the new row is saved or discarded',
    async (scope) => {
      const streamFilters = scope === 'filters';
      const noun = streamFilters ? 'filter' : 'rule';
      API.getM3URules.mockResolvedValue([rule({ scope, filter_type: 'name' })]);
      renderEditor({ scope: streamFilters ? undefined : scope, streamFilters });
      await waitFor(() =>
        expect(screen.getByLabelText(`Edit ${noun}`)).toBeEnabled()
      );
      fireEvent.click(screen.getByText(`Add ${noun}`));
      const savedPreview = screen.getAllByLabelText(`Preview ${noun}`)[0];
      expect(savedPreview).toBeDisabled();
      fireEvent.click(savedPreview);
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
      expect(API.previewM3URules).not.toHaveBeenCalled();
      fireEvent.click(screen.getByLabelText(`Discard ${noun} changes`));
      await waitFor(() =>
        expect(screen.getByLabelText(`Preview ${noun}`)).toBeEnabled()
      );
      expect(API.deleteM3URule).not.toHaveBeenCalled();
    }
  );

  it.each(['live', 'movie', 'series', 'filters'])(
    'shows the saved %s enabled state while keeping its switch locked until Edit',
    async (scope) => {
      const streamFilters = scope === 'filters';
      const noun = streamFilters ? 'filter' : 'rule';
      API.getM3URules.mockResolvedValue([
        rule({ scope, filter_type: 'name' }),
        rule({
          id: 2,
          scope,
          filter_type: 'name',
          enabled: false,
          regex_pattern: 'Sport',
          order: 1,
        }),
      ]);
      renderEditor({ scope: streamFilters ? undefined : scope, streamFilters });
      await waitFor(() =>
        expect(screen.getAllByLabelText(`Edit ${noun}`)[0]).toBeEnabled()
      );
      const [enabled, disabled] = screen.getAllByRole('switch');
      expect(enabled).toBeVisible();
      expect(enabled).toBeChecked();
      expect(enabled).toBeDisabled();
      expect(
        enabled.nextElementSibling.style.getPropertyValue('--switch-bg')
      ).toBe('var(--switch-color)');
      expect(disabled).not.toBeChecked();
      expect(disabled).toBeDisabled();
      expect(
        disabled.nextElementSibling.style.getPropertyValue('--switch-bg')
      ).toBe('');
      fireEvent.click(enabled);
      expect(enabled).toBeChecked();
      expect(API.saveM3URule).not.toHaveBeenCalled();
      editRow();
      expect(enabled).toBeEnabled();
      expect(disabled).toBeDisabled();
      fireEvent.click(enabled);
      expect(enabled).not.toBeChecked();
      fireEvent.click(screen.getByLabelText(`Discard ${noun} changes`));
      expect(enabled).toBeChecked();
      expect(enabled).toBeDisabled();
    }
  );
  it('keeps inputs locked while saving so later edits cannot be discarded', async () => {
    await load();
    let finish;
    API.saveM3URule.mockReturnValue(
      new Promise((resolve) => {
        finish = resolve;
      })
    );
    changeField(screen.getByLabelText('Regular expression'), {
      target: { value: 'Sport' },
    });
    fireEvent.click(screen.getByLabelText('Save rule'));
    expect(screen.getByLabelText('Regular expression')).toBeDisabled();
    expect(
      screen
        .getAllByLabelText('Rule result')
        .find((element) => element.tagName === 'INPUT')
    ).toBeDisabled();
    await waitFor(() => expect(API.saveM3URule).toHaveBeenCalledTimes(1));
    finish(rule({ regex_pattern: 'Sport' }));
    await waitFor(() =>
      expect(
        screen.getByLabelText('Regular expression').closest('[aria-busy]')
      ).toHaveAttribute('aria-busy', 'false')
    );
  });

  it.each([false, true])(
    'detects saved duplicates on opening, then rejects a new duplicate only on Save (stream filters=%s)',
    async (streamFilters) => {
      API.getM3URules.mockResolvedValue([
        rule({ filter_type: 'name' }),
        rule({ id: 2, order: 1, filter_type: 'name' }),
      ]);
      const { container } = renderEditor({ streamFilters });
      await screen.findAllByDisplayValue('News');
      await waitFor(() =>
        expect(
          screen.getAllByLabelText('Regular expression')[1]
        ).toHaveAttribute('aria-invalid', 'true')
      );
      expect(API.analyzeM3URules).toHaveBeenCalledTimes(1);
      expect(
        container.querySelectorAll('tr[data-invalid="true"]')
      ).toHaveLength(1);
      expect(
        screen.getAllByLabelText('Regular expression')[0]
      ).not.toHaveAttribute('aria-invalid', 'true');
      showNotification.mockClear();
      changeField(screen.getAllByLabelText('Regular expression')[1], {
        target: { value: 'Sports' },
      });
      expect(showNotification).not.toHaveBeenCalled();
      changeField(screen.getAllByLabelText('Regular expression')[1], {
        target: { value: 'News' },
      });
      expect(
        container.querySelectorAll('tr[data-warning="true"]')
      ).toHaveLength(0);
      expect(
        screen.queryByText(/An identical match already exists/)
      ).not.toBeInTheDocument();
      expect(screen.queryByRole('note')).not.toBeInTheDocument();
      expect(
        screen.getByLabelText(streamFilters ? 'Save filter' : 'Save rule')
      ).toBeDisabled();
      fireEvent.click(
        screen.getAllByRole('textbox', { name: 'Rule result', exact: true })[1]
      );
      fireEvent.click(
        await screen.findByRole('option', {
          name: streamFilters ? 'Exclude' : 'Disabled',
          exact: true,
        })
      );
      fireEvent.click(
        screen.getByLabelText(streamFilters ? 'Save filter' : 'Save rule')
      );
      await waitFor(() =>
        expect(
          screen
            .getAllByLabelText('Regular expression')[0]
            .closest('[aria-busy]')
        ).toHaveAttribute('aria-busy', 'false')
      );
      expect(API.saveM3URule).not.toHaveBeenCalled();
      expect(API.analyzeM3URules).toHaveBeenCalledTimes(1);
      expect(showNotification).toHaveBeenCalledWith(
        expect.objectContaining({
          color: 'red',
          autoClose: false,
          message: expect.stringContaining('identical active match'),
        })
      );
      expect(
        screen.getAllByLabelText('Regular expression')[1].closest('tr')
      ).toHaveAttribute('data-invalid', 'true');
      expect(
        screen.getAllByLabelText('Regular expression')[0].closest('tr')
      ).not.toHaveAttribute('data-invalid');
    }
  );

  it('uses a shared metadata header without irrelevant catalog notices', async () => {
    await load();
    API.previewM3URules.mockResolvedValue({
      count: 250,
      inventory_count: 300,
      results: [],
      catalog_complete: false,
      last_completed_refresh: '2026-10-14T06:00:00Z',
    });
    fireEvent.click(screen.getByLabelText('Preview rule'));
    await screen.findByText('250 matching categories from 300 categories');
    expect(screen.getByText('Data: 14.10.2026 08:00')).toBeInTheDocument();
    expect(
      screen.queryByText(
        /complete saved ordered list|No complete group inventory/
      )
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: 'Close' })
    ).not.toBeInTheDocument();
    expect(showNotification).not.toHaveBeenCalled();
    fireEvent.click(
      within(screen.getByRole('dialog')).getByRole('button', { name: '5' })
    );
    await waitFor(() => expect(API.previewM3URules).toHaveBeenCalledTimes(2));
    expect(showNotification).not.toHaveBeenCalled();
  });

  it('does not validate while typing and highlights only actual unsaved changes', async () => {
    const onStateChange = vi.fn();
    API.getM3URules.mockResolvedValue([
      rule(),
      rule({ id: 2, order: 1, regex_pattern: 'Sport' }),
    ]);
    renderEditor({ onStateChange });
    const pattern = (await screen.findAllByLabelText('Regular expression'))[0];
    await waitFor(() =>
      expect(onStateChange).toHaveBeenLastCalledWith({
        dirty: false,
        busy: false,
        overlayOpen: false,
        inventoryCount: 1,
      })
    );
    changeField(pattern, { target: { value: 'Sport' } });
    expect(pattern.closest('tr')).toHaveAttribute('data-dirty', 'true');
    expect(onStateChange).toHaveBeenLastCalledWith({
      dirty: true,
      busy: false,
      overlayOpen: false,
      inventoryCount: 1,
    });
    expect(showNotification).not.toHaveBeenCalled();
    expect(API.analyzeM3URules).toHaveBeenCalledTimes(1);
    hideNotification.mockClear();
    changeField(pattern, { target: { value: 'News' } });
    expect(pattern.closest('tr')).not.toHaveAttribute('data-dirty');
    expect(onStateChange).toHaveBeenLastCalledWith({
      dirty: false,
      busy: false,
      overlayOpen: false,
      inventoryCount: 1,
    });
    expect(hideNotification).toHaveBeenCalledWith(
      'account-rules-7-group-rules-error'
    );
  });

  it.each([false, true])(
    'checks on opening and saving, and rechecks fresh inventory after reopening (filters=%s)',
    async (streamFilters) => {
      API.getM3URules.mockResolvedValue([
        rule({ filter_type: 'name' }),
        rule({ id: 2, order: 1, regex_pattern: 'Sport', filter_type: 'name' }),
      ]);
      API.analyzeM3URules.mockResolvedValue({
        inventory_count: 100,
        rule_coverage: [
          { rule_id: '1', count: 100 },
          { rule_id: '2', count: 0 },
        ],
      });
      API.saveM3URule.mockResolvedValue(
        rule({ regex_pattern: 'News|Sport', filter_type: 'name' })
      );
      const { container, unmount } = renderEditor({ streamFilters });
      await screen.findByDisplayValue('News');
      await screen.findByRole('img', { name: /Matches all 100/ });
      expect(API.analyzeM3URules).toHaveBeenCalledTimes(1);
      showNotification.mockClear();
      const saveLabel = streamFilters ? 'Save filter' : 'Save rule';
      changeField(screen.getAllByLabelText('Regular expression')[0], {
        target: { value: 'News|Sport' },
      });
      fireEvent.click(screen.getByLabelText(saveLabel));
      await waitFor(() => expect(API.saveM3URule).toHaveBeenCalledTimes(1));
      await waitFor(() =>
        expect(showNotification).toHaveBeenCalledWith(
          expect.objectContaining({
            color: 'yellow',
            autoClose: false,
            message: expect.stringContaining('Matches all 100'),
          })
        )
      );
      expect(
        container.querySelectorAll('tr[data-warning="true"]')
      ).toHaveLength(1);
      expect(
        container.querySelectorAll('tr[data-covered="true"]')
      ).toHaveLength(1);
      expect(
        screen.getByRole('img', { name: /Covered by rule 1/ })
      ).toBeInTheDocument();
      expect(screen.queryByText(/Matches all 100/)).not.toBeInTheDocument();
      expect(showNotification).toHaveBeenCalledTimes(1);
      expect(
        screen.getAllByLabelText('Regular expression')[1].closest('tr')
      ).not.toHaveAttribute('data-warning');
      expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
      expect(API.analyzeM3URules).toHaveBeenCalledTimes(2);
      API.getM3URules.mockResolvedValue([
        rule({ regex_pattern: 'News|Sport', filter_type: 'name' }),
        rule({ id: 2, order: 1, regex_pattern: 'Sport', filter_type: 'name' }),
      ]);
      unmount();
      showNotification.mockClear();
      renderEditor({ streamFilters });
      await screen.findByRole('img', { name: /Matches all 100/ });
      await waitFor(() => expect(API.analyzeM3URules).toHaveBeenCalledTimes(3));
      await waitFor(() => expect(showNotification).toHaveBeenCalledTimes(1));
    }
  );

  it.each([false, true])(
    'checks the successfully saved order immediately (filters=%s)',
    async (streamFilters) => {
      API.getM3URules.mockResolvedValue([
        rule({ filter_type: 'name' }),
        rule({
          id: 2,
          order: 1,
          regex_pattern: 'News|Sport',
          filter_type: 'name',
        }),
      ]);
      renderEditor({ streamFilters });
      await screen.findByDisplayValue('News');
      await waitFor(() =>
        expect(
          screen
            .getAllByLabelText('Regular expression')[0]
            .closest('[aria-busy]')
        ).toHaveAttribute('aria-busy', 'false')
      );
      API.analyzeM3URules.mockResolvedValue({
        inventory_count: 100,
        rule_coverage: [
          { rule_id: '2', count: 100 },
          { rule_id: '1', count: 0 },
        ],
      });
      fireEvent.click(screen.getByText('Move second first'));
      await waitFor(() =>
        expect(API.reorderM3URules).toHaveBeenCalledWith(
          7,
          streamFilters ? 'filters' : 'group-rules',
          [2, 1],
          'live',
          [0, 1]
        )
      );
      await screen.findByRole('img', { name: /Matches all 100/ });
      expect(API.analyzeM3URules).toHaveBeenCalledTimes(2);
      expect(API.analyzeM3URules).toHaveBeenLastCalledWith(
        7,
        streamFilters ? 'filters' : 'group-rules',
        expect.arrayContaining([
          expect.objectContaining({ preview_id: '2', order: 0 }),
          expect.objectContaining({ preview_id: '1', order: 1 }),
        ])
      );
      expect(API.saveM3URule).not.toHaveBeenCalled();
      expect(
        screen.getAllByLabelText('Regular expression')[0].closest('tr')
      ).toHaveAttribute('data-warning', 'true');
      expect(
        screen.getAllByLabelText('Regular expression')[1].closest('tr')
      ).toHaveAttribute('data-covered', 'true');
      expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
    }
  );

  it('does not repeat the notice when two already-covered rows are swapped', async () => {
    API.getM3URules.mockResolvedValue([
      rule({ regex_pattern: 'News|Sport|Events' }),
      rule({ id: 2, order: 1, regex_pattern: 'Sport' }),
      rule({ id: 3, order: 2, regex_pattern: 'Events' }),
    ]);
    API.analyzeM3URules.mockResolvedValue({
      inventory_count: 10,
      rule_coverage: [
        { rule_id: '1', count: 10 },
        { rule_id: '2', count: 0 },
        { rule_id: '3', count: 0 },
      ],
    });
    renderEditor();
    await screen.findByDisplayValue('News|Sport|Events');
    await screen.findByRole('img', { name: /Matches all 10/ });
    showNotification.mockClear();
    await act(async () => drag.onEnd({ active: { id: 3 }, over: { id: 2 } }));
    expect(API.analyzeM3URules).toHaveBeenCalledTimes(2);
    expect(showNotification).not.toHaveBeenCalled();
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
    expect(screen.getAllByLabelText('Regular expression')[1]).toHaveValue(
      'Events'
    );
  });

  it('reports an unsuccessful save-time check in red without writing anything', async () => {
    await load();
    changeField(screen.getByLabelText('Regular expression'), {
      target: { value: 'Sport' },
    });
    expect(API.analyzeM3URules).toHaveBeenCalledTimes(1);
    API.analyzeM3URules.mockRejectedValue(new Error('Analysis unavailable'));
    API.saveM3URule.mockResolvedValue(rule({ regex_pattern: 'Sport' }));
    fireEvent.click(screen.getByLabelText('Save rule'));
    await waitFor(() =>
      expect(showNotification).toHaveBeenCalledWith(
        expect.objectContaining({ color: 'red', autoClose: false })
      )
    );
    expect(screen.getByLabelText('Regular expression')).toHaveAttribute(
      'aria-invalid',
      'true'
    );
    expect(API.saveM3URule).not.toHaveBeenCalled();
    expect(screen.getByLabelText('Preview rule')).toBeEnabled();
  });

  it('offers generic regex help without sending expressions or account data to the helper site', async () => {
    await load();
    fireEvent.click(
      screen.getByRole('button', { name: 'Regular expression help' })
    );
    const link = await screen.findByRole('link', { name: 'regex101 (Python)' });
    expect(link).toHaveAttribute('href', 'https://regex101.com/');
    expect(link).toHaveAttribute('rel', 'noopener noreferrer');
    expect(screen.getByText(/Avoid empty alternatives/)).toBeInTheDocument();
    expect(screen.getByText('^News(?: HD)?$')).toBeInTheDocument();
    expect(screen.queryByText('KI')).not.toBeInTheDocument();
    expect(screen.queryByText('DE|')).not.toBeInTheDocument();
    fireEvent.keyDown(
      screen.getByRole('button', { name: 'Regular expression help' }),
      { key: 'Escape' }
    );
    await waitFor(() =>
      expect(
        screen.queryByRole('link', { name: 'regex101 (Python)' })
      ).not.toBeInTheDocument()
    );
  });

  it.each(['live', 'movie', 'series', 'filters'])(
    'centers row markers in a separate fixed-width status column (%s)',
    async (scope) => {
      const streamFilters = scope === 'filters';
      API.getM3URules.mockResolvedValue([
        rule({ filter_type: 'name' }),
        rule({ id: 2, regex_pattern: 'Sports', order: 1, filter_type: 'name' }),
      ]);
      API.analyzeM3URules.mockResolvedValue({
        inventory_count: 10,
        rule_coverage: [
          { rule_id: '1', count: 10 },
          { rule_id: '2', count: 0 },
        ],
      });
      renderEditor({ scope: streamFilters ? 'live' : scope, streamFilters });
      const marker = await screen.findByRole('img', { name: /Matches all 10/ });
      const row = marker.closest('tr');
      expect(row.cells[1]).toContainElement(marker);
      expect(row.cells[1]).toHaveClass(classes.centeredCell);
      expect(row.cells[0]).not.toContainElement(marker);
      expect(row.cells[0]).toContainElement(
        screen.getAllByLabelText(streamFilters ? 'Move filter' : 'Move rule')[0]
      );
      expect(row.cells[streamFilters ? 3 : 2]).toContainElement(
        screen.getAllByLabelText('Regular expression')[0]
      );
      expect(
        screen.getByRole('columnheader', {
          name: streamFilters ? 'Filter status' : 'Rule status',
        })
      ).toBeInTheDocument();
      expect(row.closest('table').querySelectorAll('col')[1]).toHaveStyle({
        width: '32px',
      });
      const coveredMarker = screen.getByRole('img', {
        name: /Covered by rule 1/,
      });
      expect(coveredMarker.closest('td')).toHaveClass(classes.centeredCell);
      expect(coveredMarker.closest('tr').cells[1]).toContainElement(
        coveredMarker
      );
      expect(screen.getByRole('columnheader', { name: 'Case' })).toHaveClass(
        classes.centeredCell
      );
      expect(
        screen.getAllByLabelText('Case sensitive')[0].closest('td')
      ).toHaveClass(classes.centeredCell);
      if (!streamFilters) {
        expect(
          screen.getByRole('columnheader', { name: 'Enabled' })
        ).toBeInTheDocument();
        expect(
          screen.queryByRole('columnheader', { name: 'Status' })
        ).not.toBeInTheDocument();
        expect(
          screen.getAllByLabelText('Rule enabled')[0].closest('td')
        ).toHaveClass(classes.centeredCell);
      }
    }
  );

  it('maps persisted regex validation errors to their row when opening', async () => {
    API.getM3URules.mockResolvedValue([
      rule(),
      rule({ id: 2, regex_pattern: '[', order: 1 }),
    ]);
    API.analyzeM3URules.mockRejectedValue({
      status: 400,
      body: { rules: [{}, { regex_pattern: ['Invalid regular expression.'] }] },
    });
    renderEditor();
    const marker = await screen.findByRole('img', {
      name: /Invalid regular expression/,
    });
    expect(marker.closest('tr')).toHaveAttribute('data-rule-id', '2');
    expect(marker.closest('td')).toHaveClass(classes.centeredCell);
    expect(marker.closest('tr').cells[1]).toContainElement(marker);
    expect(
      screen.getAllByLabelText('Regular expression')[0]
    ).not.toHaveAttribute('aria-invalid', 'true');
    expect(showNotification).toHaveBeenCalledTimes(1);
    expect(API.saveM3URule).not.toHaveBeenCalled();
  });

  it('clears a saved duplicate marker when saving an earlier rule disabled resolves it', async () => {
    API.getM3URules.mockResolvedValue([rule(), rule({ id: 2, order: 1 })]);
    API.saveM3URule.mockResolvedValue(rule({ enabled: false }));
    renderEditor();
    await waitFor(() =>
      expect(screen.getAllByLabelText('Regular expression')[1]).toHaveAttribute(
        'aria-invalid',
        'true'
      )
    );
    editRow();
    fireEvent.click(screen.getAllByLabelText('Rule enabled')[0]);
    fireEvent.click(screen.getByLabelText('Save rule'));
    await waitFor(() => expect(API.saveM3URule).toHaveBeenCalledTimes(1));
    await waitFor(() =>
      expect(
        screen.getAllByLabelText('Regular expression')[1]
      ).not.toHaveAttribute('aria-invalid', 'true')
    );
    expect(
      screen.queryByRole('img', { name: /identical active match/ })
    ).not.toBeInTheDocument();
  });

  it('does not roll back a saved order when the following coverage check fails', async () => {
    await load([rule(), rule({ id: 2, regex_pattern: 'Sports', order: 1 })]);
    API.analyzeM3URules.mockRejectedValue(new Error('Analysis unavailable'));
    fireEvent.click(screen.getByText('Move second first'));
    await waitFor(() =>
      expect(showNotification).toHaveBeenCalledWith(
        expect.objectContaining({
          title: 'Check import rules',
          color: 'red',
          message: 'Analysis unavailable',
        })
      )
    );
    expect(screen.getAllByLabelText('Regular expression')[0]).toHaveValue(
      'Sports'
    );
    expect(API.reorderM3URules).toHaveBeenCalledTimes(1);
    expect(API.saveM3URule).not.toHaveBeenCalled();
  });

  it('allows reordering a new row beside a catch-all only after saving it', async () => {
    await load([rule({ regex_pattern: '.*' })]);
    fireEvent.click(screen.getByText('Add rule'));
    expect(screen.getByRole('button', { name: 'Add rule' })).toBeDisabled();
    const newRow = screen.getAllByLabelText('Regular expression')[1];
    changeField(newRow, { target: { value: 'Sport' } });
    const newId = newRow.closest('tr').getAttribute('data-rule-id');
    await act(async () =>
      drag.onEnd({ active: { id: newId }, over: { id: 1 } })
    );
    expect(screen.getAllByLabelText('Regular expression')[0]).toHaveValue('.*');
    expect(API.reorderM3URules).not.toHaveBeenCalled();
    API.saveM3URule.mockResolvedValue(
      rule({ id: 3, regex_pattern: 'Sport', order: 1 })
    );
    fireEvent.click(screen.getByLabelText('Save rule'));
    await waitFor(() =>
      expect(API.saveM3URule).toHaveBeenCalledWith(
        7,
        'group-rules',
        null,
        expect.objectContaining({ regex_pattern: 'Sport', order: 1 })
      )
    );
    await waitFor(() =>
      expect(screen.getAllByLabelText('Move rule')[0]).toBeEnabled()
    );
    await act(async () => drag.onEnd({ active: { id: 3 }, over: { id: 1 } }));
    expect(API.reorderM3URules).toHaveBeenCalledWith(
      7,
      'group-rules',
      [3, 1],
      'live',
      [0, 1]
    );
    expect(screen.getAllByLabelText('Regular expression')[0]).toHaveValue(
      'Sport'
    );
  });

  it('does not show a failed load as an empty configured list or repeat the API error inline', async () => {
    API.getM3URules.mockRejectedValue(new Error('Load unavailable'));
    const { container } = renderEditor();
    await waitFor(() =>
      expect(container.querySelector('[aria-busy="true"]')).toBeNull()
    );
    expect(screen.queryByText('Load unavailable')).not.toBeInTheDocument();
    expect(screen.queryByText('No import rules')).not.toBeInTheDocument();
    expect(showNotification).not.toHaveBeenCalled();
  });
});
