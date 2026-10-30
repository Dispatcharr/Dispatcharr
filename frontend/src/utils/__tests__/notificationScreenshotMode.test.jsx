import { MantineProvider } from '@mantine/core';
import { act, render, screen } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { notifications } from '@mantine/notifications';
import { showNotification, updateNotification } from '../notificationUtils.js';
import useScreenshotMode from '../../store/useScreenshotMode.js';

vi.mock('@mantine/notifications', () => ({
  notifications: { show: vi.fn(), update: vi.fn(), hide: vi.fn() },
}));
beforeEach(() => {
  vi.clearAllMocks();
  useScreenshotMode.setState({ enabled: false });
});

it.each(['show', 'update'])(
  'masks URLs in an existing %s notification when the mode is switched',
  (method) => {
    const url = 'https://example.invalid?password=example-secret';
    const notification = {
      title: `Source ${url}`,
      message: (
        <>
          Failed <strong>{url}</strong> for ExampleUser
        </>
      ),
    };
    if (method === 'show') showNotification(notification);
    else updateNotification('source-1', notification);
    const result = notifications[method].mock.calls[0][0];
    render(
      <MantineProvider>
        <div>{result.title}</div>
        <div>{result.message}</div>
      </MantineProvider>
    );
    expect(screen.getByText(`Source ${url}`)).toBeInTheDocument();
    act(() => useScreenshotMode.getState().toggle());
    expect(screen.getByText('Source ••••••••')).toBeInTheDocument();
    expect(screen.getByText('••••••••')).toBeInTheDocument();
    expect(screen.getByText(/for ExampleUser/)).toBeInTheDocument();
    expect(screen.queryByText(url)).not.toBeInTheDocument();
    expect(notification.title).toBe(`Source ${url}`);
  }
);
