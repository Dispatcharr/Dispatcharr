import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MantineProvider } from '@mantine/core';
import { describe, expect, it, vi } from 'vitest';
import User from '../User.jsx';
import editorClasses from '../AccountEditor.module.css';
vi.mock('../UserAppData', () => ({
  default: () => <div>App data content</div>,
}));

vi.mock('../../../store/channels', () => ({
  default: (selector) => selector({ profiles: {} }),
}));
vi.mock('../../../store/playlists', () => ({
  default: (selector) => selector({ profiles: {} }),
}));
vi.mock('../../../store/outputProfiles', () => ({
  default: (selector) => selector({ profiles: [] }),
}));
vi.mock('../../../store/auth', () => ({
  default: (selector) =>
    selector({ user: { id: 1, user_level: 10 }, setUser: vi.fn() }),
}));

const sampleUser = {
  id: 2,
  username: 'sample-user',
  email: 'user@example.invalid',
  user_level: 1,
  channel_profiles: [],
  custom_properties: {},
};
const renderUser = (props = {}) => (
  <MantineProvider>
    <User isOpen onClose={vi.fn()} user={sampleUser} {...props} />
  </MantineProvider>
);

describe('User stable-height tabs with Mantine controls', () => {
  it('keeps every available panel in the shared grid and makes only the active panel interactive', () => {
    render(renderUser());
    expect(screen.getByRole('tablist').parentElement).toHaveClass(
      editorClasses.accountTabs
    );
    const panels = screen.getAllByRole('tabpanel', { hidden: true });
    expect(panels).toHaveLength(5);
    for (const name of [
      'Account',
      'Permissions',
      'EPG Defaults',
      'API & XC',
      'App Data',
    ]) {
      fireEvent.click(screen.getByRole('tab', { name, exact: true }));
      const active = screen.getByRole('tabpanel', { name, exact: true });
      for (const panel of panels) {
        expect(panel).toHaveClass(
          editorClasses.panel,
          editorClasses.accountPanel
        );
        expect(panel).toHaveAttribute(
          'data-editor-active',
          String(panel === active)
        );
        expect(panel).toHaveAttribute('aria-hidden', String(panel !== active));
        if (panel === active) expect(panel).not.toHaveAttribute('inert');
        else expect(panel).toHaveAttribute('inert');
      }
      expect(screen.getAllByRole('tabpanel')).toHaveLength(1);
    }
  });

  it('preserves unsaved form values when switching tabs', () => {
    render(renderUser());
    fireEvent.change(screen.getByLabelText('Username', { exact: true }), {
      target: { value: 'edited-user' },
    });
    fireEvent.click(screen.getByRole('tab', { name: 'EPG Defaults' }));
    fireEvent.change(screen.getByLabelText('Days forward', { exact: true }), {
      target: { value: '4' },
    });
    fireEvent.click(screen.getByRole('tab', { name: 'Account', exact: true }));
    expect(screen.getByLabelText('Username', { exact: true })).toHaveValue(
      'edited-user'
    );
    fireEvent.click(screen.getByRole('tab', { name: 'EPG Defaults' }));
    expect(screen.getByLabelText('Days forward', { exact: true })).toHaveValue(
      '4'
    );
  });

  it('starts on Account again after reopening or switching to another user', async () => {
    const { rerender } = render(renderUser());
    fireEvent.click(screen.getByRole('tab', { name: 'API & XC' }));
    rerender(renderUser({ isOpen: false }));
    rerender(renderUser());
    await waitFor(() =>
      expect(
        screen.getByRole('tab', { name: 'Account', exact: true })
      ).toHaveAttribute('aria-selected', 'true')
    );
    fireEvent.click(screen.getByRole('tab', { name: 'EPG Defaults' }));
    rerender(
      renderUser({ user: { ...sampleUser, id: 3, username: 'another-user' } })
    );
    await waitFor(() =>
      expect(
        screen.getByRole('tab', { name: 'Account', exact: true })
      ).toHaveAttribute('aria-selected', 'true')
    );
    expect(screen.getByLabelText('Username', { exact: true })).toHaveValue(
      'another-user'
    );
  });

  it('does not add an unavailable Permissions panel when editing yourself', () => {
    render(renderUser({ user: { ...sampleUser, id: 1, user_level: 10 } }));
    expect(
      screen.queryByRole('tab', { name: 'Permissions' })
    ).not.toBeInTheDocument();
    expect(screen.getAllByRole('tabpanel', { hidden: true })).toHaveLength(4);
  });
});
