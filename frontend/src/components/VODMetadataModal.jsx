import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import {
  ActionIcon,
  Alert,
  Button,
  Divider,
  Group,
  Loader,
  Modal,
  Pagination,
  Progress,
  ScrollArea,
  Stack,
  Table,
  TagsInput,
  Text,
  TextInput,
  Tooltip,
} from '@mantine/core';
import { Eye, LockKeyhole } from 'lucide-react';
import API from '../api';
import { showNotification } from '../utils/notificationUtils';
import { showVODProfileRebuildNotice } from '../utils/vodProfileUpdates.js';
import VODMetadataSettingsForm from './forms/settings/VODMetadataSettingsForm.jsx';

const SeriesModal = React.lazy(() => import('./SeriesModal.jsx'));
const VODModal = React.lazy(() => import('./VODModal.jsx'));

const prefixRule = (value) => ({
  match_type: 'starts_with',
  value: String(value || '').trim(),
  action: 'remove',
  replacement: '',
  enabled: true,
});

const normalizeRules = (rules) =>
  (Array.isArray(rules) ? rules : [])
    .map((rule) =>
      prefixRule(
        typeof rule === 'string' ? rule : (rule?.value ?? rule?.pattern ?? '')
      )
    )
    .filter((rule) => rule.value);

const PREVIEW_PAGE_SIZE = 50;

const tmdbResult = (row) => {
  const status = String(row?.tmdb_status || '');
  const tmdbId = String(row?.tmdb_id || '');
  const candidateCount = Number(row?.candidate_count || 0);
  if (status === 'matched') {
    return {
      color: 'teal.4',
      label: tmdbId ? `Matched · TMDB ${tmdbId}` : 'Matched',
    };
  }
  if (status === 'ambiguous') {
    return {
      color: 'orange.4',
      label: `${candidateCount || 'Multiple'} matches · select manually`,
    };
  }
  if (status === 'not_found') {
    return {
      color: 'red.4',
      label: tmdbId
        ? 'TMDB ID not found · select manually'
        : 'No result · select manually',
    };
  }
  if (status === 'manual') {
    return { color: 'blue.4', label: 'Manual metadata' };
  }
  if (status === 'missing_id') {
    return { color: 'yellow.4', label: 'No TMDB match' };
  }
  return { color: 'dimmed', label: 'Not checked' };
};

const VODMetadataModal = ({
  opened,
  onClose,
  initialStatus = null,
  selectionContext = null,
  onStatusChange,
  onCatalogChanged,
  embedded = false,
  settingsSection = 'all',
}) => {
  const [metadataStatus, setMetadataStatus] = useState(null);
  const [titleRules, setTitleRules] = useState([]);
  const [savedTitleRules, setSavedTitleRules] = useState([]);
  const [previewSearch, setPreviewSearch] = useState('');
  const [titlePreview, setTitlePreview] = useState([]);
  const [previewMode, setPreviewMode] = useState('');
  const [previewPage, setPreviewPage] = useState(1);
  const [previewTotal, setPreviewTotal] = useState(0);
  const [loadingRules, setLoadingRules] = useState(false);
  const [previewingTitles, setPreviewingTitles] = useState(false);
  const [savingTitleRules, setSavingTitleRules] = useState(false);
  const [titleRuleError, setTitleRuleError] = useState('');
  const [applyingSelection, setApplyingSelection] = useState(false);
  const [selectionRunState, setSelectionRunState] = useState(null);
  const [confirmationAction, setConfirmationAction] = useState('');
  const [detailContent, setDetailContent] = useState(null);
  const ruleSaveSequence = useRef(0);
  const selectionRunSequence = useRef(0);

  const hydrateStatus = useCallback((status) => {
    setMetadataStatus(status);
    const rules = normalizeRules(status?.settings?.title_rules);
    setTitleRules(rules);
    setSavedTitleRules(rules);
    setTitlePreview([]);
    setPreviewMode('');
    setPreviewPage(1);
    setPreviewTotal(0);
    setTitleRuleError('');
  }, []);

  const loadRules = useCallback(async () => {
    setLoadingRules(true);
    try {
      const status = await API.getVODMetadataStatus(true);
      hydrateStatus(status);
    } catch (error) {
      setMetadataStatus(null);
      setTitleRuleError(
        error?.body?.detail ||
          error?.message ||
          'The VOD metadata settings could not be loaded.'
      );
    } finally {
      setLoadingRules(false);
    }
  }, [hydrateStatus]);

  useEffect(() => {
    if (!opened) return;
    if (initialStatus) hydrateStatus(initialStatus);
    else loadRules();
  }, [hydrateStatus, initialStatus, loadRules, opened]);

  useEffect(() => {
    if (!opened) {
      selectionRunSequence.current += 1;
      setSelectionRunState(null);
      setDetailContent(null);
    }
  }, [opened]);

  const prefixes = useMemo(
    () => titleRules.map((rule) => rule.value),
    [titleRules]
  );

  const saveTitleRules = async (nextRules) => {
    const sequence = ++ruleSaveSequence.current;
    setSavingTitleRules(true);
    setTitleRuleError('');
    try {
      const next = await API.updateVODMetadataSettings({
        title_rules: nextRules,
      });
      if (sequence !== ruleSaveSequence.current) return;
      const saved = normalizeRules(next?.settings?.title_rules);
      setTitleRules(saved);
      setSavedTitleRules(saved);
      setMetadataStatus(next);
      onStatusChange?.(next);
    } catch (error) {
      if (sequence !== ruleSaveSequence.current) return;
      setTitleRules(savedTitleRules);
      setTitleRuleError(
        error?.body?.title_rules ||
          error?.body?.detail ||
          error?.message ||
          'The title-cleanup rules were not saved.'
      );
    } finally {
      if (sequence === ruleSaveSequence.current) setSavingTitleRules(false);
    }
  };

  const updatePrefixes = (values) => {
    const nextRules = normalizeRules(values);
    setTitleRules(nextRules);
    setTitlePreview([]);
    setPreviewMode('');
    setPreviewPage(1);
    setPreviewTotal(0);
    setTitleRuleError('');
    saveTitleRules(nextRules);
  };

  const previewTitleRules = async (
    rules = titleRules,
    search = previewSearch.trim(),
    options = {}
  ) => {
    const mode = selectionContext ? 'selection' : options.mode || 'search';
    const page = selectionContext ? 1 : options.page || 1;
    setPreviewingTitles(true);
    setTitleRuleError('');
    try {
      const response = await API.previewVODMetadataTitles(
        rules,
        selectionContext && !selectionContext.select_all
          ? selectionContext.selections.slice(0, 500)
          : null,
        search,
        selectionContext?.select_all
          ? {
              select_all: true,
              filters: selectionContext.filters,
              exclude_selections: selectionContext.exclude_selections,
            }
          : selectionContext
            ? {}
            : {
                missing_tmdb_only: mode === 'missing',
                page,
                page_size: PREVIEW_PAGE_SIZE,
              }
      );
      setTitlePreview(response.results || []);
      setPreviewMode(mode);
      setPreviewPage(response.page || page);
      setPreviewTotal(response.total ?? (response.results || []).length);
    } catch (error) {
      setTitlePreview([]);
      setPreviewTotal(0);
      setTitleRuleError(
        error?.body?.title_rules ||
          error?.body?.detail ||
          error?.message ||
          'The title-cleanup preview could not be created.'
      );
    } finally {
      setPreviewingTitles(false);
    }
  };

  useEffect(() => {
    if (!opened || !selectionContext || !metadataStatus || loadingRules) {
      return;
    }
    previewTitleRules(titleRules, '');
    // The selected rows and hydrated rules are the preview identity. Search is
    // intentionally absent in selection mode because the library selection is
    // already the user's scope.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [opened, selectionContext, metadataStatus, loadingRules, titleRules]);

  const monitorSelectionEnrichment = async (initialState) => {
    const sequence = ++selectionRunSequence.current;
    setSelectionRunState(initialState);
    let state = initialState;
    while (
      sequence === selectionRunSequence.current &&
      ['queued', 'running'].includes(state?.status)
    ) {
      await new Promise((resolve) => window.setTimeout(resolve, 1000));
      if (sequence !== selectionRunSequence.current) return;
      try {
        const response = await API.getVODMetadataStatus(false);
        if (sequence !== selectionRunSequence.current) return;
        if (!response?.state) continue;
        state = response.state;
        setSelectionRunState(state);
      } catch (error) {
        if (sequence !== selectionRunSequence.current) return;
        setSelectionRunState({
          status: 'failed',
          progress: {},
          error:
            error?.body?.detail ||
            error?.message ||
            'The TMDB metadata status could not be loaded.',
        });
        return;
      }
    }
    if (sequence !== selectionRunSequence.current) return;
    if (state?.status === 'complete') {
      await previewTitleRules(titleRules, '');
      onCatalogChanged?.(state);
      const progress = state.progress || {};
      showNotification({
        title: 'TMDB enrichment complete',
        message: `${progress.processed || 0} titles processed · ${progress.enriched || 0} enriched · ${progress.not_found || 0} not found · ${progress.ambiguous || 0} ambiguous.`,
        color: 'green',
      });
    } else if (state?.status === 'failed') {
      setTitleRuleError(state.error || 'The TMDB metadata refresh failed.');
    }
  };

  const runSelectionAction = async (action) => {
    if (!selectionContext) return;
    setApplyingSelection(true);
    setTitleRuleError('');
    try {
      let result;
      if (action === 'enrich') {
        result = await API.refreshVODMetadata([], {
          ...selectionContext,
          force: true,
        });
        showNotification({
          title: 'TMDB enrichment queued',
          message: `${selectionContext.count} selected titles will be processed.`,
          color: 'green',
        });
        if (result?.state) {
          void monitorSelectionEnrichment(result.state);
        }
      } else if (action === 'toggle-lock') {
        result = await API.lockVODMetadata(
          selectionContext.select_all ? [] : selectionContext.selections,
          {
            select_all: selectionContext.select_all,
            exclude_selections: selectionContext.exclude_selections,
            filters: selectionContext.filters,
            toggle: true,
          }
        );
        const unlocked = result.action === 'unlocked';
        showNotification({
          title: unlocked
            ? 'Automatic metadata matching unlocked'
            : 'Automatic metadata matching locked',
          message: unlocked
            ? `${result.unlocked || 0} titles can enter automatic cleanup and TMDB matching again.`
            : `${result.locked || 0} titles will be skipped until they are explicitly unlocked.`,
          color: 'green',
        });
      } else if (action === 'reset-provider') {
        result = await API.resetVODMetadata(
          'provider',
          selectionContext.selections
        );
        showNotification({
          title: 'Provider metadata restored',
          message: `${result.reloaded || 0} canonical titles were rebuilt from their stored provider sources.`,
          color: 'green',
        });
      } else {
        result = await API.applyVODTitleCleanup(titleRules, {
          ...selectionContext,
        });
        showNotification({
          title: 'Cleanup titles saved',
          message: `${result.updated || 0} canonical titles were updated.`,
          color: 'green',
        });
      }
      showVODProfileRebuildNotice(result);
      if (action !== 'enrich') {
        onCatalogChanged?.(result);
        await previewTitleRules(titleRules, '');
      }
    } catch (error) {
      setTitleRuleError(
        error?.body?.detail || error?.message || 'The selected action failed.'
      );
    } finally {
      setApplyingSelection(false);
    }
  };

  const confirmSelectionAction = async () => {
    const action = confirmationAction;
    setConfirmationAction('');
    await runSelectionAction(action);
  };

  const previewTable =
    titlePreview.length > 0 ? (
      <Stack gap={6}>
        <Text size="sm" fw={600}>
          Prefix cleanup preview
        </Text>
        <ScrollArea h="min(45vh, 460px)" offsetScrollbars>
          <Table striped withTableBorder stickyHeader>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Provider title</Table.Th>
                <Table.Th>Clean title</Table.Th>
                {selectionContext && <Table.Th>TMDB result</Table.Th>}
                <Table.Th w={72} ta="center">
                  Details
                </Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {titlePreview.map((row) => (
                <Table.Tr key={`${row.content_type}:${row.id}`}>
                  <Table.Td>{row.before || '—'}</Table.Td>
                  <Table.Td>
                    <Text c={row.changed ? 'teal.4' : 'dimmed'}>
                      {row.after || '—'}
                    </Text>
                  </Table.Td>
                  {selectionContext && (
                    <Table.Td>
                      <Text size="xs" c={tmdbResult(row).color} fw={600}>
                        {tmdbResult(row).label}
                      </Text>
                    </Table.Td>
                  )}
                  <Table.Td ta="center">
                    <ActionIcon
                      variant="subtle"
                      aria-label={`Open details for ${row.after || row.before || 'title'}`}
                      onClick={() =>
                        setDetailContent({
                          id: row.id,
                          name: row.after || row.before || '',
                          year: row.year || null,
                          contentType: row.content_type,
                          content_type: row.content_type,
                        })
                      }
                    >
                      <Eye size={16} />
                    </ActionIcon>
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </ScrollArea>
        {!selectionContext && previewTotal > 0 && (
          <Group justify="center" gap="md" wrap="wrap">
            {previewTotal > PREVIEW_PAGE_SIZE && (
              <Pagination
                value={previewPage}
                total={Math.ceil(previewTotal / PREVIEW_PAGE_SIZE)}
                onChange={(page) =>
                  previewTitleRules(
                    titleRules,
                    previewMode === 'search' ? previewSearch.trim() : '',
                    { mode: previewMode, page }
                  )
                }
              />
            )}
            <Text size="xs" c="dimmed">
              {(previewPage - 1) * PREVIEW_PAGE_SIZE + 1}–
              {Math.min(previewPage * PREVIEW_PAGE_SIZE, previewTotal)} of{' '}
              {previewTotal}
            </Text>
          </Group>
        )}
      </Stack>
    ) : null;

  const settingsCleanupContent = (
    <Stack gap="md">
      <Group align="end" wrap="wrap">
        <TagsInput
          label="Prefixes to remove"
          placeholder="Enter a prefix and press Enter"
          value={prefixes}
          onChange={updatePrefixes}
          disabled={savingTitleRules}
          clearable
          splitChars={[',']}
          style={{ flex: '1 1 420px' }}
        />
        {savingTitleRules && (
          <Group gap="xs" pb={7}>
            <Loader size="xs" />
            <Text size="xs" c="dimmed">
              Saving prefixes
            </Text>
          </Group>
        )}
      </Group>

      <Group align="end" wrap="wrap">
        <TextInput
          label="Preview titles containing"
          placeholder="Enter a title"
          value={previewSearch}
          onChange={(event) => {
            setPreviewSearch(event.currentTarget.value);
            setTitlePreview([]);
            setPreviewMode('');
            setPreviewPage(1);
            setPreviewTotal(0);
          }}
          style={{ flex: '1 1 300px' }}
          maw={420}
        />
        <Button
          variant="default"
          size="xs"
          leftSection={<Eye size={14} />}
          loading={previewingTitles}
          disabled={loadingRules || !previewSearch.trim()}
          onClick={() =>
            previewTitleRules(titleRules, previewSearch.trim(), {
              mode: 'search',
              page: 1,
            })
          }
        >
          Search
        </Button>
        <Button
          variant="default"
          size="xs"
          leftSection={<Eye size={14} />}
          loading={previewingTitles}
          disabled={loadingRules}
          onClick={() => {
            setPreviewSearch('');
            previewTitleRules(titleRules, '', {
              mode: 'missing',
              page: 1,
            });
          }}
        >
          Without TMDB ID
        </Button>
      </Group>

      {titleRuleError && (
        <Text size="sm" c="red">
          {titleRuleError}
        </Text>
      )}
      {previewTable}
    </Stack>
  );

  const selectionRunActive = ['queued', 'running'].includes(
    selectionRunState?.status
  );

  const selectionContent = (
    <Stack gap="md">
      <Group justify="space-between" wrap="wrap">
        <Text size="sm" fw={600}>
          {selectionContext?.count || 0} canonical titles selected
        </Text>
        <Group gap="xs">
          <Tooltip
            label="Unlock the selection when every title is locked; otherwise lock the whole selection against automatic cleanup and TMDB matching."
            withArrow
            multiline
            maw={320}
          >
            <Button
              size="xs"
              variant="default"
              leftSection={<LockKeyhole size={14} />}
              loading={applyingSelection}
              disabled={selectionRunActive}
              onClick={() => runSelectionAction('toggle-lock')}
            >
              Lock / Unlock
            </Button>
          </Tooltip>
          <Button
            size="xs"
            variant="default"
            loading={applyingSelection}
            disabled={selectionRunActive}
            onClick={() => runSelectionAction('cleanup')}
          >
            Apply cleanup
          </Button>
          <Button
            size="xs"
            loading={applyingSelection}
            disabled={selectionRunActive}
            onClick={() => setConfirmationAction('enrich')}
          >
            Get TMDB data
          </Button>
          <Button
            size="xs"
            color="red"
            variant="light"
            loading={applyingSelection}
            disabled={selectionContext?.select_all || selectionRunActive}
            title={
              selectionContext?.select_all
                ? 'Select individual titles to reset provider metadata.'
                : undefined
            }
            onClick={() => setConfirmationAction('reset-provider')}
          >
            Reset to provider
          </Button>
        </Group>
      </Group>

      {selectionRunState && (
        <Alert
          color={
            selectionRunState.status === 'failed'
              ? 'red'
              : selectionRunState.status === 'complete'
                ? 'green'
                : 'blue'
          }
          title={
            selectionRunState.progress?.phase ||
            (selectionRunState.status === 'failed'
              ? 'TMDB enrichment failed'
              : 'TMDB enrichment')
          }
        >
          <Stack gap={6}>
            {['queued', 'running'].includes(selectionRunState.status) && (
              <Progress
                value={selectionRunState.progress?.percent || 0}
                animated={selectionRunState.status === 'running'}
              />
            )}
            <Text size="xs">
              {selectionRunState.status === 'failed'
                ? selectionRunState.error || 'The metadata refresh failed.'
                : `${selectionRunState.progress?.processed || 0} of ${selectionRunState.progress?.total || selectionContext?.count || 0} processed`}
            </Text>
            {selectionRunState.status === 'complete' && (
              <Text size="xs" c="dimmed">
                {selectionRunState.progress?.enriched || 0} enriched ·{' '}
                {selectionRunState.progress?.not_found || 0} not found ·{' '}
                {selectionRunState.progress?.ambiguous || 0} ambiguous
              </Text>
            )}
          </Stack>
        </Alert>
      )}

      {titleRuleError && (
        <Text size="sm" c="red">
          {titleRuleError}
        </Text>
      )}
      {previewingTitles ? (
        <Group justify="center" gap="xs" py="xl">
          <Loader size="sm" />
          <Text size="sm" c="dimmed">
            Loading the selected title preview
          </Text>
        </Group>
      ) : (
        previewTable
      )}
    </Stack>
  );

  const metadataSettingsContent = (
    <Stack gap="sm">
      <Text fw={600}>TMDB settings</Text>
      <VODMetadataSettingsForm
        status={metadataStatus}
        loading={!metadataStatus && loadingRules}
        error={!metadataStatus ? titleRuleError : ''}
        onSaved={(next) => {
          hydrateStatus(next);
          onStatusChange?.(next);
        }}
      />
    </Stack>
  );

  const titleCleanupContent = (
    <Stack gap="sm">
      <Text fw={600}>Title cleanup</Text>
      {settingsCleanupContent}
    </Stack>
  );

  const settingsContent =
    settingsSection === 'metadata' ? (
      metadataSettingsContent
    ) : settingsSection === 'title-cleanup' ? (
      titleCleanupContent
    ) : (
      <Stack gap="xl">
        {metadataSettingsContent}
        <Divider />
        {titleCleanupContent}
      </Stack>
    );

  const content = selectionContext ? selectionContent : settingsContent;

  const detailModal = detailContent ? (
    <React.Suspense fallback={null}>
      {detailContent.contentType === 'series' ? (
        <SeriesModal
          series={detailContent}
          opened
          onClose={() => setDetailContent(null)}
        />
      ) : (
        <VODModal
          vod={detailContent}
          opened
          onClose={() => setDetailContent(null)}
        />
      )}
    </React.Suspense>
  ) : null;

  if (embedded) {
    return (
      <>
        {content}
        {detailModal}
      </>
    );
  }

  return (
    <>
      <Modal
        opened={opened}
        onClose={onClose}
        title={selectionContext ? 'Edit selected VOD titles' : 'VOD metadata'}
        size="70vw"
        centered
        styles={{ content: { maxWidth: 1150 } }}
      >
        {content}
      </Modal>
      <Modal
        opened={Boolean(confirmationAction)}
        onClose={() => setConfirmationAction('')}
        title={
          confirmationAction === 'reset-provider'
            ? 'Reset canonical metadata to provider data?'
            : 'Request TMDB data for the selected titles?'
        }
        centered
        size="md"
      >
        <Stack>
          <Text size="sm">
            {confirmationAction === 'reset-provider'
              ? 'TMDB enrichment and manual canonical values will be removed. The canonical records will be rebuilt from the stored provider sources.'
              : 'An existing TMDB ID is loaded directly. Titles without a TMDB ID are searched by their clean title and only one unambiguous result is accepted. Missing or ambiguous results remain marked for manual review.'}
          </Text>
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setConfirmationAction('')}>
              Cancel
            </Button>
            <Button
              color={
                confirmationAction === 'reset-provider' ? 'red' : undefined
              }
              onClick={confirmSelectionAction}
            >
              {confirmationAction === 'reset-provider'
                ? 'Reset to provider'
                : 'Get TMDB data'}
            </Button>
          </Group>
        </Stack>
      </Modal>
      {detailModal}
    </>
  );
};

export default VODMetadataModal;
