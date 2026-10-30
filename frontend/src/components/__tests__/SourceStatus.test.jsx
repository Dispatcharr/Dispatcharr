import { MantineProvider } from '@mantine/core';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';
import SourceStatus from '../SourceStatus.jsx';
import useScreenshotMode from '../../store/useScreenshotMode.js';

const show = (props) =>
  render(
    <MantineProvider>
      <SourceStatus label="Error" color="red" {...props} />
    </MantineProvider>
  );

describe('compact source status', () => {
  beforeEach(() => useScreenshotMode.setState({ enabled: false }));

  it('keeps the short cause next to the status and exposes full details on hover', async () => {
    const message =
      'Failed to authenticate with XC server: 403 Client Error: Forbidden for url: https://example.invalid/api?password=secret';
    show({ messages: [message, 'Auto-sync failed: channels unavailable'] });
    expect(
      screen.getByText('Failed to authenticate with XC server')
    ).toBeInTheDocument();
    expect(screen.queryByText(message)).not.toBeInTheDocument();
    const status = screen.getByRole('group', { name: 'Error status' });
    expect(status).toHaveTextContent(
      'ErrorFailed to authenticate with XC server'
    );
    expect(status).toHaveAttribute('tabindex', '0');
    fireEvent.mouseEnter(status);
    expect(await screen.findByRole('tooltip')).toHaveTextContent(message);
    expect(screen.getByRole('tooltip')).toHaveTextContent(
      'Auto-sync failed: channels unavailable'
    );
    act(() => useScreenshotMode.getState().toggle());
    expect(screen.getByRole('tooltip')).not.toHaveTextContent(
      'https://example.invalid'
    );
    expect(screen.getByRole('tooltip')).not.toHaveTextContent(
      'password=secret'
    );
  });

  it('limits long messages and keeps the details target keyboard-focusable', async () => {
    const message = 'A'.repeat(220) + '\nDetailed second line';
    show({ messages: [message] });
    expect(screen.getByText('A'.repeat(97) + '…')).toBeInTheDocument();
    const status = screen.getByRole('group', { name: 'Error status' });
    act(() => status.focus());
    expect(status).toHaveFocus();
    fireEvent.mouseEnter(status);
    expect(await screen.findByRole('tooltip')).toHaveTextContent(
      'Detailed second line'
    );
  });

  it('does not add an empty details target', () => {
    show({ messages: [null, undefined, '   '] });
    expect(
      screen.getByRole('group', { name: 'Error status' })
    ).not.toHaveAttribute('tabindex');
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
  });
});
