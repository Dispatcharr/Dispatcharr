import { useCallback, useEffect, useRef, useState } from 'react';
import { Button, Stack, Text } from '@mantine/core';
import api from '../api';
import useAuthStore from '../store/auth';
import useLibraryStore from '../store/useLibraryStore';
import {
  hideNotification,
  showNotification,
  updateNotification,
} from '../utils/notificationUtils.js';
import { notifyLibraryError } from '../utils/libraryFeedback.js';
import { ScreenshotText } from './SensitiveFields.jsx';

const active = (status) => ['queued', 'running'].includes(status);

function JobMessage({ job, onAction }) {
  const [busy, setBusy] = useState(false);
  const progress = job.progress || {};
  const running = active(job.status);
  const resumable = ['failed', 'cancelled'].includes(job.status);
  return (
    <Stack gap={6}>
      <Text size="sm">
        <ScreenshotText>
          {job.error ||
            `${progress.processed || 0} / ${progress.total || 0} titles processed${!running ? ` · ${progress.failed || 0} failed · ${progress.skipped || 0} skipped` : ''}`}
        </ScreenshotText>
      </Text>
      {(running || resumable) && (
        <Button
          size="compact-xs"
          variant="light"
          loading={busy}
          onClick={async () => {
            setBusy(true);
            try {
              await onAction(running ? 'cancel' : 'resume', job.task_id);
            } catch (error) {
              notifyLibraryError(error, 'Library job');
            } finally {
              setBusy(false);
            }
          }}
        >
          {running ? 'Cancel job' : 'Resume remaining'}
        </Button>
      )}
    </Stack>
  );
}

export default function LibraryJobNotification() {
  const admin = useAuthStore((state) => state.user?.user_level >= 10);
  const job = useLibraryStore((state) => state.job);
  const trackedJobId = useLibraryStore((state) => state.trackedJobId);
  const fetchJob = useLibraryStore((state) => state.fetchJob);
  const fetchContent = useLibraryStore((state) => state.fetchContent);
  const previous = useRef(null);
  const visible = useRef(new Set());
  const signature = useRef('');
  const onAction = useCallback(
    async (operation, previousId) => {
      const current = await fetchJob();
      if (!current || current.task_id !== previousId) {
        hideNotification(`library-job-${previousId}`);
        visible.current.delete(`library-job-${previousId}`);
        throw new Error('This Library job is no longer current.');
      }
      const state = await api.vodLibraryAction(operation);
      if (state?.task_id) {
        if (state.task_id !== previousId) {
          hideNotification(`library-job-${previousId}`);
          visible.current.delete(`library-job-${previousId}`);
        }
        useLibraryStore.getState().trackJob(state);
      }
      await fetchJob();
    },
    [fetchJob]
  );
  useEffect(
    () => () => {
      for (const id of visible.current) hideNotification(id);
      visible.current.clear();
      signature.current = '';
    },
    [admin]
  );
  useEffect(() => {
    if (!admin) return undefined;
    let cancelled = false;
    let timer;
    const poll = async () => {
      const state = await fetchJob();
      if (cancelled) return;
      if (state && active(previous.current?.status) && !active(state.status))
        fetchContent();
      if (state) previous.current = state;
      if (
        (!state && active(useLibraryStore.getState().job.status)) ||
        (state &&
          (active(state.status) ||
            (state.pending_enrichment_count > 0 &&
              !['failed', 'cancelled'].includes(state.status))))
      )
        timer = setTimeout(poll, 2000);
    };
    poll();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [admin, fetchJob, fetchContent, job.task_id]);
  useEffect(() => {
    if (!admin || !job.task_id || job.status === 'idle') return;
    const id = `library-job-${job.task_id}`;
    const running = active(job.status);
    const resumable = ['failed', 'cancelled'].includes(job.status);
    if (
      !running &&
      !resumable &&
      trackedJobId !== job.task_id &&
      !visible.current.has(id)
    )
      return;
    const current = JSON.stringify(job);
    if (signature.current === current) return;
    signature.current = current;
    const operation =
      job.progress?.operation === 'cleanup'
        ? 'Title cleanup'
        : job.progress?.operation === 'reset'
          ? 'Metadata reset'
          : 'TMDB enrichment';
    const options = {
      id,
      title: `${operation}: ${job.status.replaceAll('_', ' ')}`,
      message: <JobMessage job={job} onAction={onAction} />,
      color:
        job.status === 'failed'
          ? 'red'
          : job.status === 'cancelled' || job.progress?.failed > 0
            ? 'orange'
            : running
              ? 'blue'
              : 'green',
      loading: running,
      autoClose: running || resumable ? false : 5000,
      withCloseButton: !running,
      onClose: () => {
        visible.current.delete(id);
        if (resumable) signature.current = '';
        else if (useLibraryStore.getState().trackedJobId === job.task_id)
          useLibraryStore.setState({ trackedJobId: '' });
      },
    };
    if (visible.current.has(id)) updateNotification(id, options);
    else {
      visible.current.add(id);
      showNotification(options);
    }
  }, [admin, job, trackedJobId, onAction]);
  return null;
}
