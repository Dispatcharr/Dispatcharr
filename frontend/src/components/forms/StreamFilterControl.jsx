import { useEffect, useRef, useState } from 'react';
import {
  Alert,
  Button,
  Group,
  Loader,
  Stack,
  Text,
  Tooltip,
} from '@mantine/core';
import API from '../../api.js';
import StackedModal from '../StackedModal.jsx';
import M3UFilters from './M3UFilters.jsx';
import { getM3UStreamLabel } from '../../utils/forms/M3uSetupUtils.js';

const StreamFilterControl = ({
  playlist,
  available,
  unavailableHint,
  selectionChanged,
  onSaveSelection,
  onOverlayChange,
  previewOnly = false,
  selectedGroupIds,
}) => {
  const streamLabel = getM3UStreamLabel(playlist.account_type);
  const refreshLabel = playlist.account_type === 'STD' ? 'stream' : 'Live';
  const [step, setStep] = useState(null);
  const [editorOpen, setEditorOpen] = useState(false);
  const [count, setCount] = useState(
    () => (playlist.filters || []).filter((row) => row.enabled !== false).length
  );
  const [error, setError] = useState('');
  const [previewGroupIds, setPreviewGroupIds] = useState();
  const [missingGroupIds, setMissingGroupIds] = useState([]);
  const [canLoadPreview, setCanLoadPreview] = useState(false);
  const request = useRef(0);
  const timer = useRef(null);
  const cancel = () => {
    if (step === 'saving') return;
    request.current += 1;
    clearTimeout(timer.current);
    setStep(null);
    setError('');
  };
  useEffect(() => {
    onOverlayChange?.(!!step || editorOpen);
    return () => onOverlayChange?.(false);
  }, [step, editorOpen, onOverlayChange]);
  useEffect(
    () => () => {
      request.current += 1;
      clearTimeout(timer.current);
    },
    []
  );

  const waitForCatalog = async (
    token,
    previous,
    started = Date.now(),
    sawBusy = false,
    refreshSavedSelection = false
  ) => {
    if (token !== request.current) return;
    try {
      const current = await API.getM3UStreamFilterAvailability(playlist.id);
      if (token !== request.current) return;
      if (
        current.ready &&
        (!previous || current.last_completed_refresh !== previous)
      ) {
        setStep(null);
        setEditorOpen(true);
      } else if (
        (current.refresh_failed && (sawBusy || Date.now() - started > 10000)) ||
        Date.now() - started > 300000
      ) {
        setError(
          `The ${refreshLabel} refresh did not complete successfully. Check the account status and retry.`
        );
        setStep('confirm');
      } else if (sawBusy && !current.refresh_in_progress && !current.ready) {
        if (refreshSavedSelection) {
          // An already-running refresh may have captured the old selection.
          await API.refreshLivePlaylist(playlist.id);
          if (token !== request.current) return;
          timer.current = setTimeout(
            () => void waitForCatalog(token, current.last_completed_refresh),
            1500
          );
        } else {
          setError(
            'The completed catalog does not cover the saved category selection. Refresh it before configuring filters.'
          );
          setStep('confirm');
        }
      } else {
        timer.current = setTimeout(
          () =>
            void waitForCatalog(
              token,
              previous,
              started,
              sawBusy || current.refresh_in_progress,
              refreshSavedSelection
            ),
          1500
        );
      }
    } catch {
      if (token !== request.current) return;
      setError(`Could not check the ${refreshLabel} refresh. Please retry.`);
      setStep('confirm');
    }
  };

  const open = async () => {
    if (!available || step) return;
    setError('');
    if (previewOnly) {
      const ids = [...selectedGroupIds].sort((a, b) => a - b);
      setPreviewGroupIds(ids);
      setCanLoadPreview(false);
      const token = ++request.current;
      setStep('checking');
      try {
        const current = await API.getM3UStreamFilterAvailability(
          playlist.id,
          ids
        );
        if (token !== request.current) return;
        setMissingGroupIds(current.missing_group_ids || []);
        setCanLoadPreview(current.can_load_provider === true);
        if (current.ready) {
          setStep(null);
          setEditorOpen(true);
        } else {
          if (!current.can_load_provider)
            setError(
              'Category preview data is unavailable. Reload categories before configuring stream filters.'
            );
          setStep('confirm');
        }
      } catch {
        if (token !== request.current) return;
        setError('Could not check category preview data. Please retry.');
        setStep('confirm');
      }
      return;
    }
    if (selectionChanged) {
      setStep('confirm');
      return;
    }
    const token = ++request.current;
    setStep('checking');
    try {
      const current = await API.getM3UStreamFilterAvailability(playlist.id);
      if (token !== request.current) return;
      if (current.ready) {
        setStep(null);
        setEditorOpen(true);
      } else if (current.refresh_in_progress) {
        setStep('refreshing');
        void waitForCatalog(token, null, Date.now(), true);
      } else setStep('confirm');
    } catch {
      if (token !== request.current) return;
      setError('Could not check the available stream data. Please retry.');
      setStep('confirm');
    }
  };

  const prepare = async () => {
    const token = ++request.current;
    setError('');
    setStep('saving');
    try {
      await onSaveSelection();
      if (token !== request.current) return;
      const previous = await API.getM3UStreamFilterAvailability(playlist.id);
      if (token !== request.current) return;
      if (!previous.refresh_in_progress)
        await API.refreshLivePlaylist(playlist.id);
      if (token !== request.current) return;
      setStep('refreshing');
      void waitForCatalog(
        token,
        previous.last_completed_refresh,
        Date.now(),
        previous.refresh_in_progress,
        previous.refresh_in_progress
      );
    } catch {
      if (token !== request.current) return;
      setError(
        `The selection could not be saved or the ${refreshLabel} refresh could not be started. Please retry.`
      );
      setStep('confirm');
    }
  };

  const preparePreview = async () => {
    const token = ++request.current;
    setError('');
    setStep('loading-preview');
    try {
      for (const groupId of missingGroupIds) {
        if (token !== request.current) return;
        await API.loadM3UGroupContent(playlist.id, 'live', groupId);
      }
      if (token !== request.current) return;
      const current = await API.getM3UStreamFilterAvailability(
        playlist.id,
        previewGroupIds
      );
      if (token !== request.current) return;
      if (!current.ready) throw new Error('Preview incomplete');
      setStep(null);
      setEditorOpen(true);
    } catch {
      if (token !== request.current) return;
      setError(
        'Category previews could not be loaded completely. Please retry. Nothing has been imported.'
      );
      setStep('confirm');
    }
  };

  return (
    <>
      <Tooltip
        label={unavailableHint}
        disabled={available}
        withArrow
        events={{ hover: true, focus: true, touch: true }}
      >
        <span
          style={{ display: 'inline-flex' }}
          tabIndex={available ? undefined : 0}
          aria-label={available ? undefined : unavailableHint}
        >
          <Button
            size="xs"
            variant={count ? 'light' : 'default'}
            disabled={!available || !!step}
            loading={step === 'checking'}
            onClick={() => void open()}
          >
            Stream filters{count ? ` (${count})` : ''}
          </Button>
        </span>
      </Tooltip>
      <StackedModal
        stackId="m3u-stream-filter-preparation"
        opened={!!step}
        onClose={cancel}
        title="Prepare stream filters"
        size="md"
        closeButtonProps={{
          'aria-label': 'Close stream filter preparation',
          disabled: step === 'saving',
        }}
      >
        <Stack gap="md">
          {error && (
            <Alert color="red" role="alert">
              {error}
            </Alert>
          )}
          <Text size="sm">
            {previewOnly
              ? step === 'confirm'
                ? `Load previews for the ${previewGroupIds?.length || 0} selected ${streamLabel} categories to configure stream filters? Existing cached previews will be reused. Nothing will be imported or selected categories saved.`
                : step === 'checking'
                  ? 'Checking category preview data…'
                  : 'Loading selected category previews. Nothing is being imported.'
              : step === 'confirm'
                ? `Stream filters need current data for the selected ${streamLabel} categories. Save the selection and run a ${refreshLabel} refresh before configuring filters?`
                : step === 'saving'
                  ? 'Saving category selection…'
                  : step === 'checking'
                    ? 'Checking available stream data…'
                    : `Refreshing ${streamLabel}. Stream filters will open when the complete catalog is ready.`}
          </Text>
          {step !== 'confirm' && (
            <Loader size="sm" aria-label="Preparing stream data" />
          )}
          <Group justify="flex-end">
            <Button
              variant="default"
              onClick={cancel}
              disabled={step === 'saving'}
            >
              Back to selection
            </Button>
            {step === 'confirm' && (!previewOnly || canLoadPreview) && (
              <Button
                onClick={() =>
                  void (previewOnly ? preparePreview() : prepare())
                }
              >
                {previewOnly
                  ? 'Load category previews'
                  : 'Save selection & refresh'}
              </Button>
            )}
          </Group>
        </Stack>
      </StackedModal>
      <M3UFilters
        playlist={playlist}
        isOpen={editorOpen}
        onClose={() => setEditorOpen(false)}
        previewGroupIds={previewOnly ? previewGroupIds : undefined}
        onRulesChanged={(rows) =>
          setCount(rows.filter((row) => row.enabled !== false).length)
        }
      />
    </>
  );
};

export default StreamFilterControl;
