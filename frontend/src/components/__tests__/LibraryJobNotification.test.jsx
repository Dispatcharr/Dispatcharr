import { act, fireEvent, render, screen } from '@testing-library/react';
import { MantineProvider } from '@mantine/core';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import api from '../../api';
import useLibraryStore from '../../store/useLibraryStore';
import {
  hideNotification,
  showNotification,
  updateNotification,
} from '../../utils/notificationUtils.js';
import LibraryJobNotification from '../LibraryJobNotification.jsx';

const auth = vi.hoisted(() => ({ user: { user_level: 10 } }));
vi.mock('../../store/auth', () => ({ default: (selector) => selector(auth) }));
vi.mock('../SensitiveFields.jsx', () => ({
  ScreenshotText: ({ children }) => (
    <span data-testid="masked-job-message">{children}</span>
  ),
}));
vi.mock('../../api', () => ({
  default: {
    getVODLibraryState: vi.fn(),
    vodLibraryAction: vi.fn(),
    getVODLibrary: vi.fn(),
  },
}));
vi.mock('../../utils/notificationUtils.js', () => ({
  showNotification: vi.fn(),
  updateNotification: vi.fn(),
  hideNotification: vi.fn(),
}));

const running = {
  task_id: 'one',
  status: 'running',
  progress: { operation: 'cleanup', processed: 2, total: 8 },
};
let current;
const mount = async () => {
  const result = render(
    <MantineProvider env="test">
      <LibraryJobNotification />
    </MantineProvider>
  );
  await act(async () => {});
  return result;
};
const latest = () =>
  updateNotification.mock.calls.at(-1)?.[1] ||
  showNotification.mock.calls.at(-1)?.[0];
beforeEach(() => {
  vi.clearAllMocks();
  vi.useFakeTimers();
  auth.user = { user_level: 10 };
  current = { status: 'idle', progress: {} };
  useLibraryStore.setState({ job: current, trackedJobId: '' });
  api.getVODLibraryState.mockImplementation(async () => ({ ...current }));
  api.getVODLibrary.mockResolvedValue({ results: [], count: 0 });
});
afterEach(() => vi.useRealTimers());

describe('global Library job notifications', () => {
  it('does not show historical completed jobs or poll while idle', async () => {
    current = { ...running, status: 'complete' };
    await mount();
    const requests = api.getVODLibraryState.mock.calls.length;
    await act(async () => vi.advanceTimersByTimeAsync(5000));
    expect(api.getVODLibraryState).toHaveBeenCalledTimes(requests);
    expect(showNotification).not.toHaveBeenCalled();
  });
  it('updates one notification, refreshes the Library after completion and stops polling', async () => {
    current = running;
    await mount();
    expect(showNotification).toHaveBeenCalledOnce();
    expect(latest()).toMatchObject({
      id: 'library-job-one',
      loading: true,
      autoClose: false,
    });
    current = { ...running, progress: { ...running.progress, processed: 5 } };
    await act(async () => vi.advanceTimersByTimeAsync(2000));
    expect(showNotification).toHaveBeenCalledOnce();
    expect(updateNotification).toHaveBeenLastCalledWith(
      'library-job-one',
      expect.objectContaining({ loading: true })
    );
    current = {
      ...running,
      status: 'complete',
      progress: { ...running.progress, processed: 8 },
    };
    await act(async () => vi.advanceTimersByTimeAsync(2000));
    expect(latest()).toMatchObject({
      color: 'green',
      loading: false,
      autoClose: 5000,
    });
    expect(api.getVODLibrary).toHaveBeenCalledOnce();
    const count = api.getVODLibraryState.mock.calls.length;
    await act(async () => vi.advanceTimersByTimeAsync(6000));
    expect(api.getVODLibraryState).toHaveBeenCalledTimes(count);
  });
  it('reports a tracked job even if it completes before the first poll', async () => {
    current = { ...running, status: 'complete' };
    useLibraryStore.getState().trackJob(current);
    await mount();
    expect(showNotification).toHaveBeenCalledOnce();
    expect(latest()).toMatchObject({ loading: false, color: 'green' });
  });
  it('marks a completed job with failed items as a warning rather than a clean success', async () => {
    current = {
      ...running,
      status: 'complete',
      progress: { ...running.progress, failed: 1 },
    };
    useLibraryStore.getState().trackJob(current);
    await mount();
    expect(latest()).toMatchObject({ loading: false, color: 'orange' });
  });
  it.each([
    ['running', 'Cancel job', 'cancel', 'one'],
    ['failed', 'Resume remaining', 'resume', 'two'],
    ['cancelled', 'Resume remaining', 'resume', 'two'],
  ])(
    'only performs the %s job action on request',
    async (status, label, operation, nextId) => {
      current = {
        ...running,
        status,
        error:
          status === 'failed'
            ? 'Provider https://example.invalid/private failed'
            : '',
      };
      api.vodLibraryAction.mockImplementation(async () => {
        current = {
          ...running,
          task_id: nextId,
          status: operation === 'cancel' ? 'cancelled' : 'queued',
        };
        return current;
      });
      await mount();
      expect(api.vodLibraryAction).not.toHaveBeenCalled();
      const message = latest().message;
      render(<MantineProvider env="test">{message}</MantineProvider>);
      expect(screen.getByTestId('masked-job-message')).toBeInTheDocument();
      await act(async () =>
        fireEvent.click(screen.getByRole('button', { name: label }))
      );
      expect(api.vodLibraryAction).toHaveBeenCalledExactlyOnceWith(operation);
      expect(useLibraryStore.getState().trackedJobId).toBe(nextId);
      if (operation === 'resume')
        expect(hideNotification).toHaveBeenCalledWith('library-job-one');
    }
  );
  it('retries transient polling failures for an active job and cleans up on unmount', async () => {
    current = running;
    const { unmount } = await mount();
    api.getVODLibraryState.mockRejectedValueOnce(new Error('Offline'));
    await act(async () => vi.advanceTimersByTimeAsync(2000));
    expect(useLibraryStore.getState().job.status).toBe('running');
    await act(async () => vi.advanceTimersByTimeAsync(2000));
    const count = api.getVODLibraryState.mock.calls.length;
    unmount();
    await act(async () => vi.advanceTimersByTimeAsync(6000));
    expect(api.getVODLibraryState).toHaveBeenCalledTimes(count);
    expect(hideNotification).toHaveBeenCalledWith('library-job-one');
  });
  it('does not query job state or show notifications to non-admin users', async () => {
    auth.user = { user_level: 1 };
    useLibraryStore.setState({ job: running });
    await mount();
    expect(api.getVODLibraryState).not.toHaveBeenCalled();
    expect(showNotification).not.toHaveBeenCalled();
  });
  it('does not cancel a newer job from a stale notification', async () => {
    current = running;
    await mount();
    render(<MantineProvider env="test">{latest().message}</MantineProvider>);
    current = { ...running, task_id: 'newer' };
    await act(async () =>
      fireEvent.click(screen.getByRole('button', { name: 'Cancel job' }))
    );
    expect(api.vodLibraryAction).not.toHaveBeenCalled();
    expect(hideNotification).toHaveBeenCalledWith('library-job-one');
    expect(showNotification).toHaveBeenCalledWith(
      expect.objectContaining({
        message: 'This Library job is no longer current.',
        color: 'red',
      })
    );
  });
  it('allows a dismissed failed job to be resumed after the next Library state check', async () => {
    current = { ...running, status: 'failed' };
    await mount();
    act(() => latest().onClose());
    await act(async () => useLibraryStore.getState().fetchJob());
    expect(showNotification).toHaveBeenCalledTimes(2);
    expect(latest()).toMatchObject({ color: 'red', autoClose: false });
  });
  it('does not redisplay a completed tracked job after its notification closes', async () => {
    current = { ...running, status: 'complete' };
    useLibraryStore.getState().trackJob(current);
    await mount();
    act(() => latest().onClose());
    await act(async () => useLibraryStore.getState().fetchJob());
    expect(useLibraryStore.getState().trackedJobId).toBe('');
    expect(showNotification).toHaveBeenCalledOnce();
  });
});
