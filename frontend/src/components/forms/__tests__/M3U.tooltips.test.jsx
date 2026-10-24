import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import { describe, expect, it, vi } from 'vitest';
import M3U from '../M3U.jsx';

vi.mock('../../../store/userAgents', () => ({
  default: (selector) => selector({ userAgents: [] }),
}));
vi.mock('../../../store/serverGroups', () => ({
  default: (selector) => selector({ serverGroups: [] }),
}));
vi.mock('../../../store/playlists', () => ({
  default: (selector) => selector({ playlists: [] }),
}));
vi.mock('../../../store/channels', () => ({
  default: (selector) => selector({ fetchChannelGroups: vi.fn() }),
}));
vi.mock('../../../store/epgs', () => ({
  default: (selector) => selector({ fetchEPGs: vi.fn() }),
}));
vi.mock('../../../store/useVODStore', () => ({
  default: (selector) => selector({ fetchCategories: vi.fn() }),
}));
vi.mock('../../../utils/dateTimeUtils.js', () => ({
  useDateTimeFormat: () => ({
    timeFormat: 'HH:mm',
    dateYearFormat: 'DD.MM.YYYY',
    fullDateTimeFormat: 'DD.MM.YYYY HH:mm',
  }),
  useTimeHelpers: () => ({
    toUserTime: () => ({ format: () => '' }),
  }),
}));
vi.mock('../M3UProfiles', () => ({ default: () => null }));
vi.mock('../M3UGroupFilter', () => ({ default: () => null }));
vi.mock('../ScheduleInput', () => ({ default: () => null }));
vi.mock('../../ServerGroupsManagerModal', () => ({ default: () => null }));

const renderContent = (values = {}) => {
  render(
    <MantineProvider>
      <M3U
        isOpen
        onClose={vi.fn()}
        m3uAccount={{
          id: 1,
          name: 'Example account',
          server_url: 'https://example.invalid',
          account_type: 'XC',
          is_active: true,
          enable_vod: true,
          vod_refresh_after_live: false,
          ...values,
        }}
      />
    </MantineProvider>
  );
  fireEvent.click(screen.getByRole('tab', { name: 'Settings' }));
};

const tabTo = async (target) => {
  const user = userEvent.setup();
  for (
    let index = 0;
    index < 40 && document.activeElement !== target;
    index += 1
  ) {
    await user.tab();
  }
  expect(target).toHaveFocus();
};

describe('M3U content switch tooltips with Mantine controls', () => {
  it('shows guided Live and VOD settings together without losing drafts', () => {
    const onSetupBack = vi.fn();
    render(
      <MantineProvider>
        <M3U
          isOpen
          setupMode
          onClose={vi.fn()}
          onSetupBack={onSetupBack}
          m3uAccount={{
            id: 1,
            name: 'Example account',
            server_url: 'https://example.invalid',
            account_type: 'XC',
            is_active: true,
            enable_vod: true,
            setup_step: 'content',
          }}
        />
      </MantineProvider>
    );
    expect(
      screen.getByRole('group', { name: 'Live TV settings' })
    ).toBeVisible();
    expect(screen.getByRole('group', { name: 'VOD settings' })).toBeVisible();
    expect(screen.queryByRole('tablist')).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Stale Stream Retention (days)'), {
      target: { value: '14' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Back' }));
    expect(onSetupBack).toHaveBeenCalledOnce();
    expect(screen.getByLabelText('Stale Stream Retention (days)')).toHaveValue(
      '14'
    );
  });

  it.each([
    ['Enable VOD', 'Import movies and series from this Xtream Codes account.'],
    [
      'Enable separate VOD refresh schedule',
      'When disabled, VOD refresh runs after a successful scheduled Live TV refresh.',
    ],
  ])('shows %s help when hovering its visible label', async (name, help) => {
    renderContent();
    const input = screen.getByRole('switch', { name });
    fireEvent.mouseEnter(input.closest('.mantine-Switch-root').parentElement);
    expect(await screen.findByRole('tooltip')).toHaveTextContent(help);
    expect(input).toBeChecked();
  });

  it('shows help when an enabled switch receives keyboard focus', async () => {
    renderContent();
    await tabTo(screen.getByRole('switch', { name: 'Enable VOD' }));
    expect(await screen.findByRole('tooltip')).toHaveTextContent(
      'Import movies and series from this Xtream Codes account.'
    );
  });

  it('does not expose hidden VOD controls or focusable VOD help for standard accounts', () => {
    renderContent({ account_type: 'STD' });
    for (const name of ['Enable VOD', 'Enable separate VOD refresh schedule']) {
      const input = screen.getByRole('switch', { name, hidden: true });
      expect(input).not.toBeVisible();
      expect(
        input.closest('.mantine-Switch-root').parentElement
      ).not.toBeVisible();
    }
  });

  it('keeps disabled XC schedule help accessible', async () => {
    renderContent({ enable_vod: false });
    const input = screen.getByRole('switch', {
      name: 'Enable separate VOD refresh schedule',
    });
    expect(input).toBeDisabled();
    const target = input.closest('.mantine-Switch-root').parentElement;
    expect(target).toHaveAttribute('tabindex', '0');
    fireEvent.mouseEnter(target);
    expect(await screen.findByRole('tooltip')).toBeInTheDocument();
  });
});
