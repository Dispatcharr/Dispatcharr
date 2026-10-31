import { useCallback, useEffect, useState } from 'react';
import {
  ActionIcon,
  Button,
  Checkbox,
  Group,
  Loader,
  Paper,
  Stack,
  Text,
  Tooltip,
} from '@mantine/core';
import {
  Eraser,
  Ban,
  Lock,
  Settings,
  Sparkles,
  Unlock,
  WandSparkles,
} from 'lucide-react';
import api from '../api';
import {
  notifyLibraryError,
  notifyLibrarySuccess,
} from '../utils/libraryFeedback.js';
import { LibraryDialog } from './LibraryDialogs.jsx';
import CleanupPreviewTable from './CleanupPreviewTable.jsx';
import ConfirmationDialog from './ConfirmationDialog.jsx';
import ListPagination from './ListPagination.jsx';
import useLibraryStore from '../store/useLibraryStore';
import CleanupRulesEditor from './forms/settings/CleanupRulesEditor.jsx';
import classes from './LibraryWorkspace.module.css';

const cleanupRules = (settings) => ({
  title_rules: settings.title_rules,
  ...(settings.removal_rules !== undefined
    ? { removal_rules: settings.removal_rules }
    : {}),
  year_rules: settings.year_rules,
});
const ACTION_LABELS = {
  cleanup: 'Clean up',
  enrich: 'Enrich',
  lock: 'Protect',
  unlock: 'Unlock',
  block: 'Block',
  unblock: 'Unblock',
};

export default function LibraryMetadataDialog({
  selection,
  items = [],
  selectionCount = items.length,
  job,
  onClose,
  onChanged,
  onPreview,
}) {
  const [cleanup, setCleanup] = useState(null);
  const count = selection?.all_matching
    ? (cleanup?.count ?? selectionCount)
    : selectionCount;
  const fetchJob = useLibraryStore((state) => state.fetchJob);
  const [busy, setBusy] = useState(false);
  const [confirmation, setConfirmation] = useState(null);
  const [previewLoading, setPreviewLoading] = useState(!!count);
  const [previewVersion, setPreviewVersion] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);
  const [settings, setSettings] = useState(null);
  const [previewRules, setPreviewRules] = useState(null);
  const [showSettings, setShowSettings] = useState(false);
  const [editorDirty, setEditorDirty] = useState(false);
  const [searchMissing, setSearchMissing] = useState(false);
  const [initialSearch, setInitialSearch] = useState(false);
  const resetFeedback = useCallback(() => {}, []);
  const updatePreviewRules = useCallback((value) => {
    setPreviewRules((current) =>
      JSON.stringify(current) === JSON.stringify(value) ? current : value
    );
  }, []);
  const loadSettings = useCallback(async () => {
    try {
      const value = await api.getVODLibrarySettings();
      const rules = cleanupRules(value);
      setSettings(rules);
      setPreviewRules(rules);
      setSearchMissing(value.match_missing);
      setInitialSearch(value.match_missing);
    } catch (error) {
      notifyLibraryError(error, 'Cleanup settings');
      setPreviewLoading(false);
    }
  }, []);
  useEffect(() => {
    loadSettings();
  }, [loadSettings]);
  const saveRules = useCallback(async (values) => {
    setBusy(true);
    try {
      const saved = cleanupRules(await api.updateVODLibrarySettings(values));
      setSettings(saved);
      notifyLibrarySuccess('Cleanup settings saved.');
      return true;
    } catch (error) {
      notifyLibraryError(error, 'Cleanup settings');
      return false;
    } finally {
      setBusy(false);
    }
  }, []);
  const dirty = editorDirty || searchMissing !== initialSearch;
  const protectedCount =
    cleanup?.protected_count ??
    items.filter((item) => item.metadata_locked).length;
  const protection = protectedCount === count ? 'unlock' : 'lock';
  const ProtectionIcon = protection === 'unlock' ? Unlock : Lock;
  const blockedCount =
    cleanup?.blocked_count ??
    items.filter((item) => item.library_blocked).length;
  const availability = blockedCount === count ? 'unblock' : 'block';
  useEffect(() => {
    if (!selection || !selectionCount || !previewRules) return undefined;
    let cancelled = false;
    setPreviewLoading(true);
    setCleanup(null);
    const timer = setTimeout(
      () =>
        api
          .vodLibraryAction('cleanup-preview', {
            ...selection,
            page,
            page_size: pageSize,
            ...previewRules,
          })
          .then((value) => {
            if (!cancelled) setCleanup(value);
          })
          .catch((error) => {
            if (!cancelled) notifyLibraryError(error, 'Cleanup preview');
          })
          .finally(() => {
            if (!cancelled) setPreviewLoading(false);
          }),
      250
    );
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [selection, selectionCount, previewVersion, page, pageSize, previewRules]);
  const running = ['queued', 'running'].includes(job.status);
  const disabled =
    busy || previewLoading || running || !count || !settings || editorDirty;
  const action = async (callback) => {
    setBusy(true);
    try {
      await callback();
    } catch (error) {
      notifyLibraryError(error);
    } finally {
      setBusy(false);
    }
  };
  const bulk = (operation) =>
    action(async () => {
      const result = await api.vodLibraryAction('bulk', {
        ...selection,
        operation,
        ...(['cleanup', 'enrich'].includes(operation)
          ? {
              include_protected: protectedCount > 0,
              ...settings,
              ...(operation === 'enrich'
                ? { search_missing: searchMissing }
                : {}),
            }
          : {}),
      });
      const protection = operation === 'lock' || operation === 'unlock';
      if (result?.state) {
        useLibraryStore.getState().trackJob(result.state);
        await fetchJob();
      } else
        notifyLibrarySuccess(
          protection
            ? 'Metadata protection updated.'
            : ['block', 'unblock'].includes(operation)
              ? operation === 'block'
                ? 'Titles blocked globally.'
                : 'Titles unblocked.'
              : operation === 'reset'
                ? 'Library metadata reset to provider data.'
                : 'Library job queued.'
        );
      setConfirmation(null);
      onChanged();
      onClose();
    });
  return (
    <LibraryDialog
      title={`Edit selected titles (${count})`}
      onClose={onClose}
      busy={busy}
      size="xl"
      dirty={dirty}
    >
      <Stack gap="md">
        <Group justify="space-between" gap="sm">
          <Tooltip label="Edit global cleanup settings">
            <ActionIcon
              variant={showSettings ? 'light' : 'default'}
              aria-label="Cleanup options"
              aria-expanded={showSettings}
              aria-controls="library-cleanup-options"
              className={showSettings ? classes.cleanupButtonActive : undefined}
              disabled={busy || !settings || editorDirty}
              onClick={() => setShowSettings((value) => !value)}
            >
              <Settings size={16} />
            </ActionIcon>
          </Tooltip>
          <Group gap="xs">
            <Tooltip
              label={
                availability === 'block'
                  ? 'Block selected titles for every client'
                  : 'Allow selected titles for clients again'
              }
            >
              <ActionIcon
                variant={blockedCount ? 'light' : 'default'}
                color={blockedCount ? 'red' : 'gray'}
                aria-label={
                  availability === 'block'
                    ? 'Block selected titles'
                    : 'Unblock selected titles'
                }
                aria-pressed={blockedCount > 0}
                disabled={disabled}
                onClick={() => setConfirmation(availability)}
              >
                <Ban size={16} />
              </ActionIcon>
            </Tooltip>
            <Tooltip
              label={
                protection === 'unlock'
                  ? 'Unlock selected titles'
                  : 'Protect selected titles'
              }
            >
              <ActionIcon
                variant="default"
                aria-label={
                  protection === 'unlock'
                    ? 'Unlock selected titles'
                    : 'Protect selected titles'
                }
                disabled={disabled}
                onClick={() => setConfirmation(protection)}
              >
                <ProtectionIcon size={16} />
              </ActionIcon>
            </Tooltip>
            <Tooltip label="Apply the previewed cleanup rules to the selected titles">
              <Button
                size="xs"
                variant="default"
                leftSection={<WandSparkles size={15} />}
                disabled={disabled || !cleanup}
                onClick={() => setConfirmation('cleanup')}
              >
                Cleanup
              </Button>
            </Tooltip>
            <Tooltip label="Fetch TMDB metadata for the selected titles">
              <Button
                variant="light"
                size="xs"
                leftSection={<Sparkles size={15} />}
                disabled={disabled}
                onClick={() => setConfirmation('enrich')}
              >
                Enrich
              </Button>
            </Tooltip>
            <Tooltip label="Remove Library edits and TMDB metadata; keep provider data">
              <Button
                variant="light"
                size="xs"
                color="red"
                leftSection={<Eraser size={15} />}
                disabled={disabled}
                onClick={() => setConfirmation('reset')}
              >
                Reset
              </Button>
            </Tooltip>
          </Group>
        </Group>
        {showSettings && settings && (
          <Paper
            withBorder
            p="md"
            className={classes.cleanupOptions}
            component="section"
            aria-label="Cleanup settings"
            id="library-cleanup-options"
          >
            <CleanupRulesEditor
              settings={settings}
              busy={busy || running}
              onSave={saveRules}
              onDirtyChange={setEditorDirty}
              onResetFeedback={resetFeedback}
              onPreviewChange={updatePreviewRules}
              showPreview={false}
            />
          </Paper>
        )}
        {!settings && !previewLoading && (
          <Button variant="subtle" onClick={loadSettings}>
            Retry settings
          </Button>
        )}
        {previewLoading && (
          <Group gap="xs" justify="center" py="xl" role="status">
            <Loader size="sm" />
            <Text size="sm">Loading selected title preview…</Text>
          </Group>
        )}
        {count > 0 && !previewLoading && !cleanup && (
          <Button
            variant="subtle"
            size="compact-sm"
            onClick={() => setPreviewVersion((value) => value + 1)}
          >
            Retry preview
          </Button>
        )}
        {cleanup && (
          <Stack gap="sm">
            <CleanupPreviewTable
              rows={cleanup.results || []}
              items={items}
              onPreview={onPreview}
            />
            <ListPagination
              page={page}
              pageSize={pageSize}
              total={cleanup.count}
              onPageChange={setPage}
              onPageSizeChange={(value) => {
                setPageSize(value);
                setPage(1);
              }}
              pageSizeOptions={[10, 25, 50]}
              disabled={busy || previewLoading}
              itemLabel="Titles"
            />
          </Stack>
        )}
      </Stack>
      <ConfirmationDialog
        opened={!!confirmation && confirmation !== 'enrich'}
        onClose={() => setConfirmation(null)}
        onConfirm={() => bulk(confirmation)}
        loading={busy}
        title={
          confirmation === 'reset'
            ? 'Reset library metadata?'
            : `${ACTION_LABELS[confirmation]} titles?`
        }
        message={
          confirmation === 'reset'
            ? `Reset library edits, cleanup and TMDB metadata for ${count} ${count === 1 ? 'title' : 'titles'}? Metadata is unlocked. Provider data, source metadata and global output blocks are kept.`
            : `${ACTION_LABELS[confirmation]} ${count} ${count === 1 ? 'title' : 'titles'}?${confirmation === 'block' ? ' They will not be listed or playable by any client. Metadata and provider data stay unchanged.' : confirmation === 'unblock' ? ' They can be listed and played by clients again.' : ''}${['cleanup', 'enrich'].includes(confirmation) && protectedCount ? ` Process ${protectedCount} protected ${protectedCount === 1 ? 'title' : 'titles'} once for this operation. Their protection remains enabled.` : ''}`
        }
        confirmLabel="Confirm"
        confirmColor={
          ['reset', 'block'].includes(confirmation) ? 'red' : 'blue'
        }
      />
      {confirmation === 'enrich' && (
        <LibraryDialog
          title="Enrich titles?"
          onClose={() => setConfirmation(null)}
          busy={busy}
        >
          <Stack gap="md">
            <Text size="sm">
              Enrich {count} {count === 1 ? 'title' : 'titles'}?
              {protectedCount
                ? ` Process ${protectedCount} protected ${protectedCount === 1 ? 'title' : 'titles'} once. Their protection remains enabled.`
                : ''}
            </Text>
            <Checkbox
              label="Search TMDB for titles without an ID"
              checked={searchMissing}
              disabled={busy}
              onChange={(event) =>
                setSearchMissing(event.currentTarget.checked)
              }
            />
            <Group justify="flex-end">
              <Button onClick={() => bulk('enrich')} loading={busy}>
                Confirm
              </Button>
            </Group>
          </Stack>
        </LibraryDialog>
      )}
    </LibraryDialog>
  );
}
