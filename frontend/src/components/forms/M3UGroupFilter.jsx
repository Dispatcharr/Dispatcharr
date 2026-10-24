// Modal.js
import React, { useEffect, useRef, useState } from 'react';
import {
  Button,
  Flex,
  LoadingOverlay,
  Stack,
  Tabs,
  TabsList,
  TabsPanel,
  TabsTab,
} from '@mantine/core';
import useChannelsStore from '../../store/channels';
import useVODStore from '../../store/useVODStore';
import LiveGroupFilter from './LiveGroupFilter';
import VODCategoryFilter from './VODCategoryFilter';
import { showNotification } from '../../utils/notificationUtils.js';
import {
  buildGroupStates,
  saveAndRefreshPlaylist,
  savePlaylistGroupSettings,
} from '../../utils/forms/M3uGroupFilterUtils.js';
import { detectGroupReservationOverlaps } from '../../utils/forms/GroupSyncUtils';
import M3URulesModal from './M3URulesModal.jsx';
import editorClasses from './AccountEditor.module.css';
import useCategoryPreviewAvailability from '../../hooks/useCategoryPreviewAvailability.jsx';
import ConfirmationDialog from '../ConfirmationDialog.jsx';
import StackedModal from '../StackedModal.jsx';
import { getM3UStreamLabel } from '../../utils/forms/M3uSetupUtils.js';

const groupSettingsSnapshot = (groups = []) =>
  JSON.stringify(
    groups.map((row) => ({
      channel_group: row.channel_group,
      enabled: !!row.enabled,
      ignored: !!row.ignored,
      auto_channel_sync: !!row.auto_channel_sync,
      auto_sync_channel_start: row.auto_sync_channel_start || 1,
      auto_sync_channel_end: row.auto_sync_channel_end ?? null,
      custom_properties: row.custom_properties || {},
    }))
  );

const M3UGroupFilter = ({
  playlist = null,
  isOpen,
  onClose,
  isInitialSetup = false,
  onSetupSave,
  onEditAccount,
}) => {
  const streamLabel = getM3UStreamLabel(playlist?.account_type);
  const channelGroups = useChannelsStore((s) => s.channelGroups);
  const fetchCategories = useVODStore((s) => s.fetchCategories);
  const vodAvailable =
    playlist?.account_type === 'XC' && !!playlist?.enable_vod;

  const [groupStates, setGroupStates] = useState([]);
  const [isLoading, setIsLoading] = useState(false);
  const [movieCategoryStates, setMovieCategoryStates] = useState([]);
  const [seriesCategoryStates, setSeriesCategoryStates] = useState([]);
  const [activeTab, setActiveTab] = useState('live');
  const [rulesScope, setRulesScope] = useState(null);
  const [childOverlayOpen, setChildOverlayOpen] = useState(false);
  const [activeAction, setActiveAction] = useState(null);
  const [paginationContainer, setPaginationContainer] = useState(null);
  const groupsAccount = useRef(null);
  const savedGroups = useRef('[]');
  const [discardAction, setDiscardAction] = useState(null);
  const [emptySelectionOpen, setEmptySelectionOpen] = useState(false);
  const [ruleCounts, setRuleCounts] = useState(
    playlist?.group_rule_counts || {}
  );
  const saving = useRef(false);
  const { availability, hint: previewHint } = useCategoryPreviewAvailability(
    playlist?.id,
    isOpen
  );

  useEffect(() => {
    if (!isOpen) {
      setActiveTab('live');
      setRulesScope(null);
      groupsAccount.current = null;
      setEmptySelectionOpen(false);
    }
  }, [isOpen]);

  useEffect(() => {
    setEmptySelectionOpen(false);
    setRuleCounts(playlist?.group_rule_counts || {});
  }, [playlist?.id, playlist?.group_rule_counts]);

  useEffect(() => {
    if (!vodAvailable) {
      setActiveTab('live');
      setRulesScope(null);
    }
  }, [vodAvailable]);

  useEffect(() => {
    if (
      !isOpen ||
      !playlist ||
      groupsAccount.current === playlist.id ||
      Object.keys(channelGroups).length === 0
    )
      return;
    groupsAccount.current = playlist.id;
    const groups = buildGroupStates(channelGroups, playlist.channel_groups);
    savedGroups.current = groupSettingsSnapshot(groups);
    setGroupStates(groups);
  }, [playlist, channelGroups, isOpen]);

  // Fetch VOD categories when modal opens for XC accounts with VOD enabled
  useEffect(() => {
    if (
      isOpen &&
      playlist &&
      playlist.account_type === 'XC' &&
      playlist.enable_vod
    ) {
      fetchCategories();
    }
  }, [isOpen, playlist, fetchCategories]);

  const markSelectionSaved = () => {
    savedGroups.current = groupSettingsSnapshot(groupStates);
    const mark = (current) =>
      current.map((category) => ({
        ...category,
        original_enabled: category.enabled,
        original_ignored: !!category.ignored,
        original_custom_properties: { ...(category.custom_properties || {}) },
      }));
    setMovieCategoryStates(mark);
    setSeriesCategoryStates(mark);
  };

  const saveSelectionForFilters = async () => {
    await savePlaylistGroupSettings(
      playlist,
      groupStates,
      vodAvailable ? movieCategoryStates : [],
      vodAvailable ? seriesCategoryStates : [],
      {}
    );
    markSelectionSaved();
  };

  const liveSelection = (rows) =>
    JSON.stringify(
      rows
        .filter((row) => row.enabled)
        .map((row) => row.channel_group)
        .sort((a, b) => a - b)
    );
  const liveSelectionChanged =
    liveSelection(groupStates) !==
    liveSelection(JSON.parse(savedGroups.current));

  const submit = async () => {
    if (saving.current) return;
    saving.current = true;
    const refreshIncludesVod =
      playlist.account_type === 'XC' &&
      playlist.enable_vod &&
      playlist.is_active !== false &&
      (isInitialSetup || playlist.vod_refresh_after_live !== false);

    // Advisory only: overlapping ranges are sometimes intentional (for
    // example, two providers carrying the same category that should
    // merge into one shared number range). The form already shows a
    // warning triangle on each affected group with the specific overlap
    // names on hover, so the toast just confirms the save proceeded.
    const overlaps = detectGroupReservationOverlaps(groupStates);
    if (overlaps.length > 0) {
      showNotification({
        title: 'Overlapping channel number ranges',
        message: `Saved with ${overlaps.length} overlapping range pair${overlaps.length === 1 ? '' : 's'}. Hover the warning icon on each group for details. Sync will assign whichever numbers are free at run time.`,
        color: 'yellow',
        autoClose: 6000,
      });
    }

    setIsLoading(true);
    setActiveAction('save');
    try {
      const save =
        isInitialSetup && !onSetupSave
          ? saveAndRefreshPlaylist
          : savePlaylistGroupSettings;
      await save(
        playlist,
        groupStates,
        vodAvailable ? movieCategoryStates : [],
        vodAvailable ? seriesCategoryStates : [],
        {},
        isInitialSetup
      );

      markSelectionSaved();

      if (onSetupSave) {
        await onSetupSave();
        return;
      }

      showNotification({
        title: 'Category Settings Updated',
        message: isInitialSetup
          ? 'Settings saved. The initial refresh has been requested.'
          : 'Settings saved. Refresh actions use the saved settings.',
        color: 'green',
        autoClose: 3000,
      });

      if (isInitialSetup)
        showNotification({
          title: `${streamLabel} Refresh Started`,
          message: refreshIncludesVod
            ? 'Live TV is refreshing now. VOD will be queued in the background after Live TV completes; its progress is shown separately.'
            : `The saved ${streamLabel} settings are being applied. Channel sync runs after parsing completes.`,
          color: 'blue',
          autoClose: 5000,
        });

      if (isInitialSetup) onClose();
    } catch (error) {
      showNotification({
        title: 'Settings were not saved',
        message: error.message || 'Please retry.',
        color: 'red',
      });
    } finally {
      saving.current = false;
      setIsLoading(false);
      setActiveAction(null);
    }
  };

  const hasSelectedCategories = () => {
    if (
      (groupStates.length ? groupStates : playlist.channel_groups || []).some(
        (row) => row.enabled
      )
    )
      return true;
    if (!vodAvailable) return false;
    // Keep saved counts until the VOD panels have initialized their rows.
    return [
      [movieCategoryStates, 'movie'],
      [seriesCategoryStates, 'series'],
    ].some(([rows, scope]) =>
      rows.length
        ? rows.some((row) => row.enabled)
        : (playlist.category_selection_counts?.[scope]?.selected || 0) > 0
    );
  };

  const requestSave = () => {
    if (isLoading || saving.current || emptySelectionOpen) return;
    if (!hasSelectedCategories()) {
      setEmptySelectionOpen(true);
      return;
    }
    void submit();
  };

  const applyRuleResult = (result) => {
    const ids = new Set(result.target_ids || []);
    const metadataUpdates = new Map(
      (result.category_updates || []).map((row) => [row.target_id, row])
    );
    const update = (current) =>
      current.map((row) => {
        if (!ids.has(result.scope === 'live' ? row.channel_group : row.id))
          return row;
        const applied = metadataUpdates.get(
          result.scope === 'live' ? row.channel_group : row.id
        );
        const enabled = applied ? applied.enabled : result.enabled;
        const ignored = applied ? applied.ignored : result.ignored;
        return {
          ...row,
          ...(enabled != null ? { enabled, original_enabled: enabled } : {}),
          ...(ignored != null ? { ignored, original_ignored: ignored } : {}),
          ...(applied
            ? {
                custom_properties: {
                  ...(row.custom_properties || {}),
                  ...applied.metadata_defaults,
                },
                original_custom_properties: {
                  ...(row.original_custom_properties || {}),
                  ...applied.metadata_defaults,
                },
              }
            : {}),
        };
      });
    if (result.scope === 'live') {
      savedGroups.current = groupSettingsSnapshot(
        update(JSON.parse(savedGroups.current))
      );
      setGroupStates(update);
    } else if (result.scope === 'movie') setMovieCategoryStates(update);
    else setSeriesCategoryStates(update);
  };

  const requestExit = (action) => {
    if (isLoading || emptySelectionOpen) return;
    const changed =
      savedGroups.current !== groupSettingsSnapshot(groupStates) ||
      (vodAvailable
        ? [...movieCategoryStates, ...seriesCategoryStates]
        : []
      ).some(
        (row) =>
          row.enabled !== row.original_enabled ||
          !!row.ignored !== !!row.original_ignored ||
          JSON.stringify(row.custom_properties || {}) !==
            JSON.stringify(row.original_custom_properties || {})
      );
    if (changed) setDiscardAction(() => action);
    else action();
  };

  if (!isOpen) {
    return <></>;
  }

  return (
    <StackedModal
      stackId="m3u-category-selection"
      keepVisibleInStack
      opened={isOpen}
      onClose={() => requestExit(onClose)}
      title="Categories"
      closeButtonProps={{ 'aria-label': 'Close categories' }}
      size="94vw"
      classNames={{
        content: editorClasses.content,
        body: editorClasses.body,
        header: editorClasses.header,
      }}
      styles={{
        content: { '--mantine-color-body': '#27272A' },
      }}
      lockScroll={false}
      withinPortal={true}
      trapFocus={
        !rulesScope &&
        !childOverlayOpen &&
        !discardAction &&
        !emptySelectionOpen
      }
      closeOnEscape={
        !rulesScope &&
        !childOverlayOpen &&
        !discardAction &&
        !emptySelectionOpen &&
        !isLoading
      }
      yOffset="2vh"
      xOffset="3vw"
    >
      <LoadingOverlay visible={isLoading} overlayBlur={2} />
      <Stack className={editorClasses.form} gap={0} inert={emptySelectionOpen}>
        <Tabs
          className={editorClasses.tabs}
          value={activeTab}
          onChange={(value) => {
            if (!isLoading) setActiveTab(value);
          }}
        >
          <TabsList className={editorClasses.tabList}>
            <TabsTab value="live">{streamLabel}</TabsTab>
            {vodAvailable && (
              <>
                <TabsTab value="vod-movie">VOD - Movies</TabsTab>
                <TabsTab value="vod-series">VOD - Series</TabsTab>
              </>
            )}
          </TabsList>

          <TabsPanel
            value="live"
            className={`${editorClasses.panel} ${editorClasses.categoryPanel}`}
          >
            <LiveGroupFilter
              isInitialSetup={isInitialSetup}
              playlist={playlist}
              groupStates={groupStates}
              setGroupStates={setGroupStates}
              onOpenRules={() => setRulesScope('live')}
              ruleCount={ruleCounts.live || 0}
              selectionChanged={liveSelectionChanged}
              onSaveSelection={saveSelectionForFilters}
              onOverlayChange={setChildOverlayOpen}
              paginationContainer={paginationContainer}
              paginationVisible={activeTab === 'live'}
              previewAvailableIds={
                playlist.account_type === 'XC'
                  ? undefined
                  : (availability?.live ?? null)
              }
              previewUnavailableHint={previewHint}
            />
          </TabsPanel>

          {vodAvailable && (
            <>
              <TabsPanel
                value="vod-movie"
                className={`${editorClasses.panel} ${editorClasses.categoryPanel}`}
              >
                <VODCategoryFilter
                  playlist={playlist}
                  categoryStates={movieCategoryStates}
                  setCategoryStates={setMovieCategoryStates}
                  type="movie"
                  onOpenRules={() => setRulesScope('movie')}
                  ruleCount={ruleCounts.movie || 0}
                  onOverlayChange={setChildOverlayOpen}
                  paginationContainer={paginationContainer}
                  paginationVisible={activeTab === 'vod-movie'}
                  previewUnavailableHint={previewHint}
                />
              </TabsPanel>
              <TabsPanel
                value="vod-series"
                className={`${editorClasses.panel} ${editorClasses.categoryPanel}`}
              >
                <VODCategoryFilter
                  playlist={playlist}
                  categoryStates={seriesCategoryStates}
                  setCategoryStates={setSeriesCategoryStates}
                  type="series"
                  onOpenRules={() => setRulesScope('series')}
                  ruleCount={ruleCounts.series || 0}
                  onOverlayChange={setChildOverlayOpen}
                  paginationContainer={paginationContainer}
                  paginationVisible={activeTab === 'vod-series'}
                  previewUnavailableHint={previewHint}
                />
              </TabsPanel>
            </>
          )}
        </Tabs>

        <Flex
          component="footer"
          aria-label="Category actions"
          className={`${editorClasses.footer} ${editorClasses.plainFooter} ${editorClasses.categoryFooter}`}
          mih={50}
          gap="xs"
          justify="flex-end"
          align="center"
          wrap="wrap"
        >
          <div
            ref={setPaginationContainer}
            className={editorClasses.paginationSlot}
          />
          <div className={editorClasses.categoryFooterActions}>
            {onEditAccount && (
              <Button
                variant="default"
                disabled={isLoading}
                onClick={() => requestExit(onEditAccount)}
              >
                Edit account
              </Button>
            )}
            <Button
              type="submit"
              variant="filled"
              color="blue"
              disabled={isLoading}
              loading={activeAction === 'save'}
              onClick={requestSave}
            >
              {onSetupSave
                ? 'Save selection'
                : isInitialSetup
                  ? 'Save and Refresh'
                  : 'Save'}
            </Button>
          </div>
        </Flex>
      </Stack>
      <ConfirmationDialog
        opened={emptySelectionOpen}
        onClose={() => setEmptySelectionOpen(false)}
        onConfirm={() => {
          setEmptySelectionOpen(false);
          void submit();
        }}
        title="No categories selected"
        message="No categories are selected across the available content types. No content from this account is selected for import. Save this empty selection anyway?"
        confirmLabel="Save anyway"
        cancelLabel="Back to selection"
        confirmColor="orange"
      />
      <M3URulesModal
        opened={!!rulesScope}
        onClose={() => setRulesScope(null)}
        title={`${rulesScope === 'live' ? streamLabel : rulesScope === 'movie' ? 'Movie' : 'Series'} import rules`}
        accountId={playlist.id}
        accountType={playlist.account_type}
        scope={rulesScope}
        categoryCount={
          rulesScope === 'live'
            ? groupStates.length
            : rulesScope === 'movie'
              ? movieCategoryStates.length
              : seriesCategoryStates.length
        }
        onApplied={applyRuleResult}
        onRulesChanged={(rows) =>
          setRuleCounts((current) => ({
            ...current,
            [rulesScope]: rows.filter(
              (row) =>
                row.enabled &&
                ['enable', 'disable', 'ignore'].includes(row.action)
            ).length,
          }))
        }
      />
      <ConfirmationDialog
        opened={!!discardAction}
        onClose={() => setDiscardAction(null)}
        onConfirm={() => {
          const action = discardAction;
          setDiscardAction(null);
          action?.();
        }}
        title="Discard category changes?"
        message="These category changes have not been saved. Previously saved selections will be kept."
        confirmLabel="Discard"
        cancelLabel="Keep editing"
      />
    </StackedModal>
  );
};

export default M3UGroupFilter;
