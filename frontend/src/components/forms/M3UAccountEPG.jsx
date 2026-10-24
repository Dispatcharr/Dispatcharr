import { useEffect, useRef, useState } from 'react';
import {
  ActionIcon,
  Badge,
  Button,
  Group,
  Paper,
  Stack,
  Text,
  ThemeIcon,
  Tooltip,
} from '@mantine/core';
import { CalendarDays, SquarePen, Trash2 } from 'lucide-react';
import API from '../../api.js';
import useEPGsStore from '../../store/epgs';
import {
  hideNotification,
  showNotification,
} from '../../utils/notificationUtils.js';
import { formatApiError } from '../../utils';
import { format, useDateTimeFormat } from '../../utils/dateTimeUtils.js';
import {
  deleteEpg,
  formatStatusText,
} from '../../utils/tables/EPGsTableUtils.js';
import SourceStatus from '../SourceStatus.jsx';
import { SensitiveValue } from '../SensitiveFields.jsx';
import ConfirmationDialog from '../ConfirmationDialog.jsx';
import EPG from './EPG.jsx';
import cardClasses from '../tables/M3UsTable.module.css';
import editorClasses from './AccountEditor.module.css';
import summaryClasses from './M3UAccountSummary.module.css';

const EPGSourceSummary = ({
  source,
  dateFormat,
  onEdit,
  onDelete,
  disabled,
  opening,
}) => {
  const status = source.is_active === false ? 'disabled' : source.status;
  const statusColor =
    {
      fetching: 'blue.5',
      parsing: 'indigo.5',
      error: 'red.5',
      success: 'green.5',
    }[status] || 'gray.5';
  const type =
    {
      xmltv: 'XMLTV',
      schedules_direct: 'Schedules Direct',
      dummy: 'Custom Dummy',
    }[source.source_type] ||
    source.source_type ||
    'XMLTV';
  return (
    <Paper
      component="article"
      aria-label={`EPG source ${source.name}`}
      className={summaryClasses.card}
      withBorder
      radius="md"
      p="md"
    >
      <Stack gap="md">
        <Group justify="space-between" align="flex-start" wrap="nowrap">
          <Stack gap={4} style={{ minWidth: 0, flex: 1 }}>
            <Group gap="xs">
              <Text fw={600} truncate className={cardClasses.name}>
                {source.name}
              </Text>
              <Badge variant="light">{type}</Badge>
              <SourceStatus
                label={formatStatusText(status)}
                color={statusColor}
                messages={
                  ['error', 'idle', 'success'].includes(status)
                    ? [source.last_message]
                    : []
                }
                messageColor={status === 'error' ? 'red.4' : undefined}
              />
            </Group>
            {(source.url || source.file_path) && (
              <SensitiveValue size="sm" c="dimmed" truncate>
                {source.url || source.file_path}
              </SensitiveValue>
            )}
          </Stack>
          <Paper
            className={cardClasses.controls}
            withBorder
            px={6}
            py={4}
            radius="md"
            role="group"
            aria-label={`Actions for ${source.name}`}
          >
            <Group gap={4} wrap="nowrap">
              <Tooltip label="Edit EPG">
                <ActionIcon
                  variant="subtle"
                  size="md"
                  color="yellow"
                  aria-label={`Edit ${source.name}`}
                  onClick={onEdit}
                  disabled={disabled}
                  loading={opening}
                >
                  <SquarePen size={17} />
                </ActionIcon>
              </Tooltip>
              <Tooltip label="Delete EPG">
                <ActionIcon
                  variant="subtle"
                  size="md"
                  color="red"
                  aria-label={`Delete ${source.name}`}
                  onClick={onDelete}
                  disabled={disabled || opening}
                >
                  <Trash2 size={17} />
                </ActionIcon>
              </Tooltip>
            </Group>
          </Paper>
        </Group>
        <Group gap="xl" align="flex-start">
          <div>
            <Text size="xs" fw={600} mb={4}>
              EPG channels
            </Text>
            <Text size="xs" c="dimmed">
              {source.epg_data_count ?? '—'}
            </Text>
          </div>
          <div>
            <Text size="xs" fw={600} mb={4}>
              Last refresh
            </Text>
            <Text size="xs" c="dimmed">
              {source.updated_at
                ? format(source.updated_at, dateFormat)
                : 'Never'}
            </Text>
          </div>
        </Group>
      </Stack>
    </Paper>
  );
};

const M3UAccountEPG = ({
  account,
  active = true,
  isInitialSetup = false,
  disabled = false,
  onBusyChange,
  onBack,
  onNext,
  onOverlayChange,
}) => {
  const [source, setSource] = useState(null);
  const [canCreate, setCanCreate] = useState(false);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [creating, setCreating] = useState(false);
  const [reload, setReload] = useState(0);
  const [editingSource, setEditingSource] = useState(null);
  const [openingEditor, setOpeningEditor] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const openingRef = useRef(false);
  const deletingRef = useRef(false);
  const creatingRef = useRef(false);
  const sourceSnapshotRef = useRef(null);
  const fetchEPGs = useEPGsStore((s) => s.fetchEPGs);
  const liveSource = useEPGsStore((s) => s.epgs?.[source?.id]);
  // The detail response is fresher than a pre-existing store entry. Only
  // replace it when the store subsequently receives an actual update.
  const current =
    liveSource && liveSource !== sourceSnapshotRef.current
      ? liveSource
      : source;
  const { fullDateTimeFormat } = useDateTimeFormat();

  useEffect(() => {
    onOverlayChange?.(!!editingSource || deleteOpen);
    return () => onOverlayChange?.(false);
  }, [editingSource, deleteOpen, onOverlayChange]);

  const edit = async () => {
    if (openingRef.current || !current) return;
    openingRef.current = true;
    setOpeningEditor(true);
    try {
      // The matching-source response deliberately omits connection details.
      // Only open the existing editor with the complete saved source.
      if (!useEPGsStore.getState().epgs?.[current.id]) await fetchEPGs();
      const saved = useEPGsStore.getState().epgs?.[current.id];
      if (!saved)
        throw new Error(
          'EPG source details could not be loaded. Please retry.'
        );
      hideNotification(`m3u-epg-edit-${account.id}`);
      setEditingSource(saved);
    } catch (error) {
      showNotification({
        id: `m3u-epg-edit-${account.id}`,
        title: 'EPG source could not be opened',
        message: formatApiError(error),
        color: 'red',
        autoClose: false,
      });
    } finally {
      openingRef.current = false;
      setOpeningEditor(false);
    }
  };

  const remove = async () => {
    if (deletingRef.current || !current) return;
    deletingRef.current = true;
    setDeleting(true);
    onBusyChange?.(true);
    try {
      await deleteEpg(current.id);
      // Re-read the matching source: the shared API reports deletion failures
      // through notifications rather than rejecting its promise.
      setReload((value) => value + 1);
    } catch (error) {
      showNotification({
        id: `m3u-epg-delete-${account.id}`,
        title: 'EPG source was not deleted',
        message: formatApiError(error),
        color: 'red',
        autoClose: false,
      });
    } finally {
      setDeleteOpen(false);
      deletingRef.current = false;
      setDeleting(false);
      onBusyChange?.(false);
    }
  };

  useEffect(() => {
    if (!active || !account?.id || account.account_type !== 'XC') return;
    let cancelled = false;
    setLoading(true);
    setFailed(false);
    API.getM3UEPG(account.id)
      .then((result) => {
        if (!cancelled) {
          sourceSnapshotRef.current =
            useEPGsStore.getState().epgs?.[result.source?.id];
          setSource(result.source);
          setCanCreate(result.can_create === true);
          hideNotification(`m3u-epg-${account.id}`);
        }
      })
      .catch((error) => {
        if (cancelled) return;
        setFailed(true);
        showNotification({
          id: `m3u-epg-${account.id}`,
          title: 'EPG source could not be loaded',
          message: formatApiError(error),
          color: 'red',
          autoClose: false,
        });
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [active, account?.id, account?.account_type, reload]);

  const create = async () => {
    if (creatingRef.current || !canCreate || current) return;
    creatingRef.current = true;
    setCreating(true);
    onBusyChange?.(true);
    try {
      const result = await API.createM3UEPG(account.id);
      sourceSnapshotRef.current =
        useEPGsStore.getState().epgs?.[result.source?.id];
      setSource(result.source);
      setCanCreate(result.can_create === true);
      hideNotification(`m3u-epg-${account.id}`);
      fetchEPGs().catch(() => {});
      if (isInitialSetup) await onNext?.();
    } catch (error) {
      showNotification({
        id: `m3u-epg-${account.id}`,
        title: 'EPG source was not created',
        message: formatApiError(error),
        color: 'red',
        autoClose: false,
      });
    } finally {
      creatingRef.current = false;
      setCreating(false);
      onBusyChange?.(false);
    }
  };

  if (account.account_type !== 'XC') return null;

  const card = (
    <Paper
      component="section"
      aria-label="EPG source"
      className={summaryClasses.card}
      withBorder
      radius="md"
      p="md"
    >
      <Stack gap="md">
        <Group gap="sm" wrap="nowrap">
          <ThemeIcon variant="light" size="lg" radius="md">
            <CalendarDays size={20} aria-hidden="true" />
          </ThemeIcon>
          <Text fw={600} className={summaryClasses.cardHeading}>
            Matching EPG source
          </Text>
        </Group>
        {loading ? (
          <Text size="sm" c="dimmed">
            Loading EPG source…
          </Text>
        ) : failed ? (
          <Group>
            <Button
              variant="default"
              onClick={() => setReload((value) => value + 1)}
            >
              Retry
            </Button>
          </Group>
        ) : current ? (
          <EPGSourceSummary
            source={{
              ...liveSource,
              ...current,
              last_message:
                current.last_message ??
                (liveSource?.status === current.status
                  ? liveSource?.last_message
                  : undefined),
            }}
            dateFormat={fullDateTimeFormat}
            onEdit={edit}
            onDelete={() => setDeleteOpen(true)}
            disabled={disabled || creating || deleting}
            opening={openingEditor}
          />
        ) : (
          <>
            <Text size="sm" c="dimmed">
              {canCreate
                ? 'No matching EPG source configured.'
                : 'Complete and save the account connection before creating its EPG source.'}
            </Text>
            {canCreate && !isInitialSetup && (
              <section
                aria-label="EPG source actions"
                className={summaryClasses.selectionActions}
              >
                <Button onClick={create} loading={creating} disabled={disabled}>
                  Create EPG
                </Button>
              </section>
            )}
          </>
        )}
      </Stack>
    </Paper>
  );

  const overlays = (
    <>
      {editingSource && (
        <EPG
          epg={editingSource}
          isOpen
          onClose={() => {
            setEditingSource(null);
            setReload((value) => value + 1);
          }}
        />
      )}
      <ConfirmationDialog
        opened={deleteOpen}
        onClose={() => {
          if (!deleting) setDeleteOpen(false);
        }}
        onConfirm={remove}
        loading={deleting}
        title="Confirm EPG Source Deletion"
        message={`Delete EPG source "${current?.name}"? This removes its program information and channel associations for all accounts using this source. This action cannot be undone.`}
        confirmLabel="Delete"
        cancelLabel="Cancel"
      />
    </>
  );

  if (!isInitialSetup)
    return (
      <>
        {card}
        {overlays}
      </>
    );
  return (
    <>
      <div className={editorClasses.setupPanel}>{card}</div>
      <Group
        component="footer"
        aria-label="M3U setup actions"
        justify="space-between"
        gap="xs"
        mih={50}
        className={`${editorClasses.footer} ${editorClasses.plainFooter}`}
      >
        <Button
          variant="default"
          disabled={disabled || creating || deleting}
          onClick={onBack}
        >
          Back
        </Button>
        <Group gap="xs">
          {current ? (
            <Button
              disabled={disabled || creating || deleting || loading}
              onClick={onNext}
            >
              Next
            </Button>
          ) : (
            <>
              <Button
                variant="default"
                disabled={disabled || creating || deleting || loading}
                onClick={onNext}
              >
                Skip EPG
              </Button>
              <Button
                onClick={create}
                loading={creating}
                disabled={disabled || loading || failed || !canCreate}
              >
                Create EPG
              </Button>
            </>
          )}
        </Group>
      </Group>
      {overlays}
    </>
  );
};

export default M3UAccountEPG;
