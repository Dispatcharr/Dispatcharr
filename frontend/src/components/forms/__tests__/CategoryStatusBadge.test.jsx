import { MantineProvider } from '@mantine/core';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import CategoryStatusBadge from '../CategoryStatusBadge.jsx';
import editorClasses from '../AccountEditor.module.css';

const renderStatus = (category, onToggle = vi.fn()) => {
  render(
    <MantineProvider env="test">
      <CategoryStatusBadge
        category={{ name: 'News', ...category }}
        onToggle={onToggle}
      />
    </MantineProvider>
  );
  return onToggle;
};

describe('CategoryStatusBadge', () => {
  it.each([true, false])(
    'labels the next action for enabled=%s',
    async (enabled) => {
      const user = userEvent.setup();
      const onToggle = renderStatus({ enabled });
      const button = screen.getByRole('button', {
        name: `${enabled ? 'Disable' : 'Enable'} category News`,
      });
      expect(button).toHaveTextContent(enabled ? 'Enabled' : 'Disabled');
      expect(button).toHaveClass(editorClasses.categoryStatusButton);
      expect(
        screen
          .getByText(enabled ? 'Enabled' : 'Disabled')
          .closest('.mantine-Badge-root')
      ).toHaveClass(editorClasses.categoryStatusBadge);
      await user.click(button);
      expect(onToggle).toHaveBeenCalledTimes(1);
      // The parent owns the draft; clicking does not persist or mutate the input.
      expect(button).toHaveTextContent(enabled ? 'Enabled' : 'Disabled');
    }
  );

  it.each(['{Enter}', ' '])(
    'supports keyboard activation with %s',
    async (key) => {
      const user = userEvent.setup();
      const onToggle = renderStatus({ enabled: false });
      const button = screen.getByRole('button', {
        name: 'Enable category News',
      });
      await user.tab();
      expect(button).toHaveFocus();
      await user.keyboard(key);
      expect(onToggle).toHaveBeenCalledTimes(1);
    }
  );

  it('explains the action on hover', async () => {
    const user = userEvent.setup();
    renderStatus({ enabled: false });
    await user.hover(
      screen.getByRole('button', { name: 'Enable category News' })
    );
    expect(await screen.findByRole('tooltip')).toHaveTextContent(
      'Enable category'
    );
  });

  it('leaves ignored categories as non-interactive status badges', async () => {
    const user = userEvent.setup();
    const onToggle = renderStatus({ enabled: false, ignored: true });
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
    await user.click(screen.getByText('Ignored'));
    expect(onToggle).not.toHaveBeenCalled();
  });

  it('does not submit an enclosing account form', async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn((event) => event.preventDefault());
    const onToggle = vi.fn();
    render(
      <MantineProvider env="test">
        <form onSubmit={onSubmit}>
          <CategoryStatusBadge
            category={{ name: 'News', enabled: true }}
            onToggle={onToggle}
          />
        </form>
      </MantineProvider>
    );
    await user.click(
      screen.getByRole('button', { name: 'Disable category News' })
    );
    expect(onToggle).toHaveBeenCalledOnce();
    expect(onSubmit).not.toHaveBeenCalled();
  });
});
