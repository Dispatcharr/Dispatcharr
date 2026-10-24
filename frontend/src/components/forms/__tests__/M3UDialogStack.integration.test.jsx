import { useState } from 'react';
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider, Modal } from '@mantine/core';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import API from '../../../api.js';
import M3UGroupContentPreview from '../M3UGroupContentPreview.jsx';
import M3URulesModal from '../M3URulesModal.jsx';
import GroupConfigureModal from '../GroupConfigureModal.jsx';
import useM3URuleChecks from '../../../store/useM3URuleChecks.js';
import StackedModal from '../../StackedModal.jsx';
import ScheduleInput from '../ScheduleInput.jsx';
import stackClasses from '../../StackedModal.module.css';

vi.mock('../../../api.js', () => ({
  default: {
    getM3UGroupContent: vi.fn(),
    getM3URules: vi.fn(),
    analyzeM3URules: vi.fn(),
    previewM3URules: vi.fn(),
    saveM3URule: vi.fn(),
    saveApplyM3UGroupRules: vi.fn(),
    deleteM3URule: vi.fn(),
  },
}));
vi.mock('../../../utils/notificationUtils.js', () => ({
  showNotification: vi.fn(),
  hideNotification: vi.fn(),
}));

function Harness({ kind = 'preview', scope = 'movie', onParentClose }) {
  const [opened, setOpened] = useState(false);
  const group = { id: 9, name: 'Synthetic category' };
  return (
    <MantineProvider env="test">
      <Modal.Stack>
        <Modal
          opened
          stackId="m3u-account-editor"
          title="Account"
          onClose={onParentClose}
        />
        <StackedModal
          opened
          stackId="m3u-category-selection"
          keepVisibleInStack
          title="Categories"
          onClose={onParentClose}
        >
          <input aria-label="Category draft" defaultValue="Saved selection" />
          <button onClick={() => setOpened(true)}>Open child</button>
          {kind === 'preview' && (
            <M3UGroupContentPreview
              accountId={7}
              scope={scope}
              group={opened ? group : null}
              onClose={() => setOpened(false)}
            />
          )}
          {kind === 'rules' && (
            <M3URulesModal
              opened={opened}
              title="Category import rules"
              accountId={7}
              scope={scope}
              onClose={() => setOpened(false)}
            />
          )}
          {kind === 'settings' && (
            <GroupConfigureModal
              opened={opened}
              group={group}
              onCancel={() => setOpened(false)}
              onDone={() => setOpened(false)}
            >
              <input aria-label="Synthetic setting" />
            </GroupConfigureModal>
          )}
        </StackedModal>
      </Modal.Stack>
    </MantineProvider>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  useM3URuleChecks.setState({ checks: {} });
  API.getM3UGroupContent.mockResolvedValue({
    count: 1,
    results: [{ relation_id: 1, name: 'Imported title' }],
  });
  API.getM3URules.mockResolvedValue([
    {
      id: 1,
      scope: 'movie',
      match_field: 'group_name',
      match_mode: 'any',
      regex_pattern: '^News$',
      action: 'enable',
      enabled: true,
      order: 0,
      case_sensitive: false,
    },
  ]);
  API.analyzeM3URules.mockResolvedValue({ inventory_count: 1 });
  API.previewM3URules.mockResolvedValue({
    count: 1,
    inventory_count: 1,
    results: [{ name: 'News', currently_enabled: false, would_enable: true }],
  });
});

describe('source dialogs in the actual Mantine stack', () => {
  it.each(['M3U account', 'EPG source'])(
    'opens the cron builder above %s and returns after Escape without closing the source editor',
    async (title) => {
      const user = userEvent.setup();
      const onClose = vi.fn();
      render(
        <MantineProvider env="test">
          <Modal.Stack>
            <StackedModal
              opened
              stackId="source-editor"
              keepVisibleInStack
              title={title}
              onClose={onClose}
            >
              <ScheduleInput
                scheduleType="cron"
                cronValue="0 3 * * *"
                onCronChange={vi.fn()}
                onScheduleTypeChange={vi.fn()}
              />
            </StackedModal>
          </Modal.Stack>
        </MantineProvider>
      );
      const parent = screen.getByRole('dialog', { name: title, exact: true });
      await user.click(within(parent).getByText('Open Cron Builder'));
      const builder = await screen.findByRole('dialog', {
        name: 'Cron Expression Builder',
      });
      expect(builder).not.toHaveAttribute('data-hidden');
      expect(parent).toHaveAttribute('data-hidden', 'true');
      expect(parent.closest(`.${stackClasses.background}`)).not.toBeNull();
      expect(parent.closest('.mantine-Modal-root')).toHaveAttribute('inert');
      expect(
        within(builder).getByRole('button', { name: 'Close cron builder' })
      ).toBeVisible();
      await waitFor(() =>
        expect(builder).toContainElement(document.activeElement)
      );
      await user.keyboard('{Escape}');
      await waitFor(() => expect(builder).not.toBeInTheDocument());
      expect(parent).not.toHaveAttribute('data-hidden');
      expect(parent.closest(`.${stackClasses.background}`)).toBeNull();
      expect(parent.closest('.mantine-Modal-root')).not.toHaveAttribute(
        'inert'
      );
      expect(onClose).not.toHaveBeenCalled();
    }
  );
  it.each(['live', 'movie', 'series'])(
    'opens the %s category preview above Categories and returns focus to its parent after Escape',
    async (scope) => {
      const user = userEvent.setup();
      const onParentClose = vi.fn();
      render(<Harness scope={scope} onParentClose={onParentClose} />);
      const parent = screen.getByRole('dialog', {
        name: 'Categories',
        exact: true,
      });
      const trigger = within(parent).getByRole('button', {
        name: 'Open child',
      });
      await user.click(trigger);
      const preview = await screen.findByRole('dialog', {
        name: 'Synthetic category preview',
      });
      await within(preview).findByText('Imported title');
      expect(parent).toHaveAttribute('data-hidden', 'true');
      expect(preview).not.toHaveAttribute('data-hidden');
      await waitFor(() =>
        expect(preview).toContainElement(document.activeElement)
      );
      await user.keyboard('{Escape}');
      await waitFor(() => expect(preview).not.toBeInTheDocument());
      expect(parent).not.toHaveAttribute('data-hidden');
      expect(onParentClose).not.toHaveBeenCalled();
      await waitFor(() =>
        expect(parent).toContainElement(document.activeElement)
      );
      expect(API.getM3UGroupContent).toHaveBeenCalledWith(
        7,
        scope,
        9,
        1,
        50,
        ''
      );
      await user.click(trigger);
      const reopened = await screen.findByRole('dialog', {
        name: 'Synthetic category preview',
      });
      await waitFor(() => expect(reopened).not.toHaveAttribute('data-hidden'));
      await user.click(
        within(reopened).getByRole('button', { name: 'Close category preview' })
      );
      await waitFor(() => expect(reopened).not.toBeInTheDocument());
      expect(parent).not.toHaveAttribute('data-hidden');
      expect(onParentClose).not.toHaveBeenCalled();
    }
  );

  it('keeps the rule editor open when closing its own preview or delete confirmation', async () => {
    const user = userEvent.setup();
    const onParentClose = vi.fn();
    render(<Harness kind="rules" onParentClose={onParentClose} />);
    const draft = screen.getByRole('textbox', { name: 'Category draft' });
    await user.clear(draft);
    await user.type(draft, 'Unsaved category selection');
    await user.click(screen.getByRole('button', { name: 'Open child' }));
    const parent = screen.getByRole('dialog', {
      name: 'Categories',
      exact: true,
    });
    const rules = await screen.findByRole('dialog', {
      name: /^Category import rules/,
    });
    const previewButton = await within(rules).findByRole('button', {
      name: 'Preview rule',
    });
    await waitFor(() => expect(previewButton).toBeEnabled());
    expect(parent).toHaveAttribute('data-hidden', 'true');
    expect(parent.closest('[inert]')).not.toBeNull();
    await waitFor(() => expect(rules).not.toHaveAttribute('data-hidden'));
    for (let index = 0; index < 3; index += 1) {
      await user.tab();
      expect(rules).toContainElement(document.activeElement);
    }
    await user.click(previewButton);
    const preview = await screen.findByRole('dialog', {
      name: 'Import rules preview',
    });
    await within(preview).findByText('News');
    expect(rules).toHaveAttribute('data-hidden', 'true');
    expect(preview).not.toHaveAttribute('data-hidden');
    await user.click(
      within(preview).getByRole('button', { name: 'Apply to existing' })
    );
    const applyConfirmation = await screen.findByRole('dialog', {
      name: 'Apply import rule',
    });
    expect(applyConfirmation).toHaveTextContent('all 1 matching categories');
    expect(preview).toHaveAttribute('data-hidden', 'true');
    expect(preview.closest('.mantine-Modal-root')).toHaveAttribute('inert');
    await user.click(
      within(applyConfirmation).getByRole('button', { name: 'Cancel' })
    );
    await waitFor(() => expect(applyConfirmation).not.toBeInTheDocument());
    expect(preview).not.toHaveAttribute('data-hidden');
    expect(preview.closest('.mantine-Modal-root')).not.toHaveAttribute('inert');
    expect(API.saveApplyM3UGroupRules).not.toHaveBeenCalled();
    await user.keyboard('{Escape}');
    await waitFor(() => expect(preview).not.toBeInTheDocument());
    await waitFor(() => expect(rules).not.toHaveAttribute('data-hidden'));
    await user.click(
      within(rules).getByRole('button', { name: 'Delete rule' })
    );
    const confirmation = await screen.findByRole('dialog', {
      name: 'Delete import rule',
    });
    expect(rules).toHaveAttribute('data-hidden', 'true');
    expect(confirmation).not.toHaveAttribute('data-hidden');
    await user.keyboard('{Escape}');
    await waitFor(() => expect(confirmation).not.toBeInTheDocument());
    await waitFor(() => expect(rules).not.toHaveAttribute('data-hidden'));
    await user.click(within(rules).getByRole('button', { name: 'Edit rule' }));
    await user.click(
      within(rules).getByRole('textbox', { name: 'Rule result' })
    );
    expect(
      await screen.findByRole('option', { name: 'Enabled', exact: true })
    ).toBeVisible();
    await user.keyboard('{Escape}');
    expect(rules).toBeInTheDocument();
    expect(API.deleteM3URule).not.toHaveBeenCalled();
    expect(API.saveM3URule).not.toHaveBeenCalled();
    expect(onParentClose).not.toHaveBeenCalled();
    await user.keyboard('{Escape}');
    await waitFor(() => expect(rules).not.toBeInTheDocument());
    expect(parent).not.toHaveAttribute('data-hidden');
    expect(parent.closest('[inert]')).toBeNull();
    expect(draft).toHaveValue('Unsaved category selection');
    await user.click(draft);
    expect(draft).toHaveFocus();
  });

  it('returns from Live category settings without closing Categories', async () => {
    const user = userEvent.setup();
    const onParentClose = vi.fn();
    render(<Harness kind="settings" onParentClose={onParentClose} />);
    await user.click(screen.getByRole('button', { name: 'Open child' }));
    const settings = await screen.findByRole('dialog', {
      name: /^Configure: Synthetic category/,
    });
    const parent = screen.getByRole('dialog', {
      name: 'Categories',
      exact: true,
    });
    await waitFor(() => expect(parent).toHaveAttribute('data-hidden', 'true'));
    await waitFor(() => expect(settings).not.toHaveAttribute('data-hidden'));
    fireEvent.change(within(settings).getByLabelText('Synthetic setting'), {
      target: { value: 'Unsaved draft' },
    });
    await user.keyboard('{Escape}');
    await waitFor(() => expect(settings).not.toBeInTheDocument());
    expect(parent).not.toHaveAttribute('data-hidden');
    expect(onParentClose).not.toHaveBeenCalled();
  });
});
