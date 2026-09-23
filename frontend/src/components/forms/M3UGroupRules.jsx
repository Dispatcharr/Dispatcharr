import React, { useCallback, useEffect, useState } from 'react';
import {
  ActionIcon,
  Alert,
  Button,
  Checkbox,
  Group,
  Modal,
  ScrollArea,
  Select,
  Stack,
  Table,
  TableTbody,
  TableTd,
  TableTh,
  TableThead,
  TableTr,
  Text,
  TextInput,
} from '@mantine/core';
import {
  closestCenter,
  DndContext,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
} from '@dnd-kit/core';
import {
  arrayMove,
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import { restrictToVerticalAxis } from '@dnd-kit/modifiers';
import { GripVertical, Play, Plus, Save, Trash2 } from 'lucide-react';
import API from '../../api';
import { showNotification } from '../../utils/notificationUtils';
import { normalizeLanguageCodes } from '../../utils/languageCodes.js';
import LanguagePicker from '../LanguagePicker.jsx';
import VideoFeaturePicker from '../VideoFeaturePicker.jsx';
import { RESOLUTION_VALUES } from '../../utils/vodMetadataOptions.js';
import { firstMatchingCategoryRule } from './VODProfileCategoryRules.utils.js';
import ListPagination from '../ListPagination.jsx';

const PREVIEW_PAGE_SIZE = 50;

const SortableRuleRow = ({ ruleId, error, children }) => {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: ruleId });
  return (
    <TableTr
      ref={setNodeRef}
      data-invalid={error ? 'true' : undefined}
      title={error || undefined}
      style={{
        transform: CSS.Transform.toString(transform),
        transition,
        opacity: isDragging ? 0.65 : 1,
        position: 'relative',
        zIndex: isDragging ? 2 : 0,
        backgroundColor: error ? 'rgba(250, 82, 82, 0.18)' : undefined,
        boxShadow: error ? 'inset 3px 0 var(--mantine-color-red-6)' : undefined,
      }}
    >
      <TableTd>
        <ActionIcon
          aria-label="Move import rule"
          variant="subtle"
          color="gray"
          style={{ cursor: isDragging ? 'grabbing' : 'grab' }}
          {...attributes}
          {...listeners}
        >
          <GripVertical size={16} />
        </ActionIcon>
      </TableTd>
      {children}
    </TableTr>
  );
};

const M3UGroupRules = ({
  accountId,
  scope,
  mode = 'account',
  value = [],
  onChange,
  accountOptions = [],
  categoryRows = [],
}) => {
  const profileMode = mode === 'profile';
  const [rules, setRules] = useState(profileMode ? value : []);
  const [loading, setLoading] = useState(false);
  const [preview, setPreview] = useState(null);
  const [previewRule, setPreviewRule] = useState(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewPage, setPreviewPage] = useState(1);
  const [previewPageSize, setPreviewPageSize] = useState(PREVIEW_PAGE_SIZE);
  const [ruleErrors, setRuleErrors] = useState({});
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates })
  );

  const load = useCallback(async () => {
    if (profileMode || !accountId) return;
    setLoading(true);
    try {
      setRules((await API.getM3UGroupRules(accountId, scope)) || []);
      setRuleErrors({});
    } finally {
      setLoading(false);
    }
  }, [accountId, profileMode, scope]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (!profileMode) return;
    setRules(value || []);
  }, [profileMode, value]);

  const commitRules = (next) => {
    setRules(next);
  };

  const updateLocal = (id, values) => {
    const next = rules.map((rule) =>
      rule.id === id ? { ...rule, ...values } : rule
    );
    commitRules(next);
    setRuleErrors({});
  };

  const addRule = () => {
    const prefix = profileMode ? 'profile-category' : 'new-group-rule';
    setRules((current) => [
      ...current,
      {
        id: `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
        isNew: true,
        m3u_account_id: null,
        scope,
        match_field: 'group_name',
        match_mode: 'any',
        regex_pattern: '',
        exclude_regex_pattern: '',
        action: 'disable',
        case_sensitive: false,
        enabled: true,
        order: profileMode ? current.length : current.length * 10,
        metadata_defaults: {},
      },
    ]);
  };

  const getValidationErrors = (candidateRules = rules) => {
    const errors = {};
    const identities = new Map();

    candidateRules.forEach((rule, index) => {
      const pattern = rule.regex_pattern || '';
      if (!pattern.trim()) {
        errors[rule.id] = 'Enter a regular expression.';
        return;
      }
      let compiledPattern;
      try {
        compiledPattern = new RegExp(pattern);
      } catch (error) {
        errors[rule.id] = `Invalid regular expression: ${error.message}`;
        return;
      }

      const laterRuleCanRun = candidateRules.slice(index + 1).some((later) => {
        if (later.enabled === false) return false;
        if (!profileMode) return true;
        return (
          String(later.m3u_account_id || '') ===
          String(rule.m3u_account_id || '')
        );
      });
      if (
        rule.enabled !== false &&
        compiledPattern.test('') &&
        laterRuleCanRun
      ) {
        errors[rule.id] =
          'This expression matches every group, so later active rules can never run. Move it to the last active position. To match the literal separator in DE|, use ^DE\\|.';
        return;
      }

      const identity = JSON.stringify([
        profileMode ? rule.m3u_account_id || null : rule.match_field,
        profileMode ? 'any' : rule.match_mode,
        pattern,
        Boolean(rule.case_sensitive),
      ]);
      const duplicateId = identities.get(identity);
      if (duplicateId !== undefined) {
        const message = 'An identical import rule already exists.';
        errors[duplicateId] = message;
        errors[rule.id] = message;
      } else {
        identities.set(identity, rule.id);
      }
    });

    return errors;
  };

  const validateRule = (rule) => {
    const errors = getValidationErrors();
    setRuleErrors(errors);
    if (!errors[rule.id]) return true;
    showNotification({
      title: 'Import rule was not saved',
      message: errors[rule.id],
      color: 'red',
    });
    return false;
  };

  const rulePayload = (rule) => {
    if (profileMode) {
      return {
        id: rule.id,
        scope,
        m3u_account_id: rule.m3u_account_id
          ? Number(rule.m3u_account_id)
          : null,
        match_field: 'group_name',
        regex_pattern: rule.regex_pattern || '',
        action: rule.action === 'enable' ? 'enable' : 'disable',
        case_sensitive: Boolean(rule.case_sensitive),
        enabled: rule.enabled !== false,
        order: rule.order || 0,
      };
    }
    const metadataDefaults = {
      ...(rule.metadata_defaults || {}),
      audio_languages: normalizeLanguageCodes(
        rule.metadata_defaults?.audio_languages || []
      ),
      subtitle_languages: normalizeLanguageCodes(
        rule.metadata_defaults?.subtitle_languages || []
      ),
    };
    return {
      scope,
      match_field: rule.match_field,
      match_mode: rule.match_mode,
      regex_pattern: rule.regex_pattern,
      exclude_regex_pattern: '',
      action: rule.action,
      case_sensitive: rule.case_sensitive,
      enabled: rule.enabled,
      order: rule.order,
      metadata_defaults: scope === 'live' ? {} : metadataDefaults,
    };
  };

  const saveProfileDraft = ({ apply = false } = {}) => {
    const errors = getValidationErrors();
    setRuleErrors(errors);
    if (Object.keys(errors).length) {
      showNotification({
        title: 'Import rules were not saved',
        message: 'Correct the highlighted import rules first.',
        color: 'red',
      });
      return false;
    }
    const applied = rules.map((rule, index) => ({
      ...rulePayload(rule),
      order: index,
    }));
    onChange?.(applied);
    setRules(applied.map((rule) => ({ ...rule, isNew: false })));
    showNotification({
      title: apply
        ? 'Import rules saved and applied'
        : 'Import rules saved to profile draft',
      message: apply
        ? 'The current source selection now reflects the ordered rules. Save the VOD profile to rebuild its output catalog.'
        : 'Preview a rule to review and apply its effect. Save the VOD profile to persist the draft.',
      color: 'green',
    });
    return true;
  };

  const saveRule = async (rule, notify = true) => {
    if (!validateRule(rule)) return null;
    const payload = rulePayload(rule);
    if (!payload) return null;
    try {
      const saved = rule.isNew
        ? await API.createM3UGroupRule(accountId, payload)
        : await API.updateM3UGroupRule(accountId, rule.id, payload);
      setRules((current) =>
        current.map((item) =>
          item.id === rule.id ? { ...saved, isNew: false } : item
        )
      );
      setRuleErrors({});
      if (notify) {
        showNotification({
          title: 'Import rule saved',
          message: 'The rule applies automatically during future scans.',
          color: 'green',
        });
      }
      return saved;
    } catch (error) {
      setRuleErrors((current) => ({
        ...current,
        [rule.id]: error?.message || 'The import rule could not be saved.',
      }));
      return null;
    }
  };

  const loadPreview = async (rule, page, pageSize) => {
    if (!validateRule(rule)) return;
    const payload = rulePayload(rule);
    if (!payload) return;
    setPreviewLoading(true);
    try {
      if (profileMode) {
        const normalizedRules = rules.map(rulePayload);
        const results = categoryRows
          .filter(
            (row) =>
              firstMatchingCategoryRule(normalizedRules, row)?.id === rule.id
          )
          .map((row) => ({
            relation_id: row.relation_id,
            name: row.categoryName,
            account_name: row.accountName,
            currently_enabled: row.enabled,
            would_enable: row.explicit
              ? row.enabled
              : payload.action === 'enable',
            item_count: row.item_count || 0,
          }));
        setPreview({ count: results.length, results });
      } else {
        setPreview(
          await API.previewM3UGroupRule(accountId, rule.id, payload, {
            page,
            page_size: pageSize,
          })
        );
      }
    } finally {
      setPreviewLoading(false);
    }
  };

  const openPreview = async (rule) => {
    if (rule.isNew) return;
    setPreviewRule(rule);
    setPreviewPage(1);
    await loadPreview(rule, 1, previewPageSize);
  };

  const changePreviewPage = async (page) => {
    setPreviewPage(page);
    if (!profileMode && previewRule) {
      await loadPreview(previewRule, page, previewPageSize);
    }
  };

  const changePreviewPageSize = async (pageSize) => {
    setPreviewPageSize(pageSize);
    setPreviewPage(1);
    if (!profileMode && previewRule) {
      await loadPreview(previewRule, 1, pageSize);
    }
  };

  const applyPreview = async () => {
    if (!previewRule) return;
    if (profileMode) {
      if (!saveProfileDraft({ apply: true })) return;
      setPreview(null);
      setPreviewRule(null);
      return;
    }
    setPreviewLoading(true);
    try {
      const saved = await saveRule(previewRule, false);
      if (!saved) return;
      const result = await API.applyM3UGroupRule(accountId, saved.id);
      showNotification({
        title: 'Import rule applied',
        message: `${result.updated || 0} existing entries were updated.`,
        color: 'green',
      });
      setPreview(null);
      setPreviewRule(null);
    } finally {
      setPreviewLoading(false);
    }
  };

  const updateMetadata = (rule, field, value) => {
    updateLocal(rule.id, {
      metadata_defaults: {
        ...(rule.metadata_defaults || {}),
        [field]: value,
      },
    });
  };

  const deleteRule = async (id) => {
    const rule = rules.find((item) => item.id === id);
    if (profileMode) {
      const next = rules.filter((rule) => rule.id !== id);
      commitRules(next);
      onChange?.(
        next.map((item, index) => ({
          ...rulePayload(item),
          order: index,
        }))
      );
      setRuleErrors({});
      return;
    }
    if (rule?.isNew) {
      commitRules(rules.filter((item) => item.id !== id));
      setRuleErrors({});
      return;
    }
    await API.deleteM3UGroupRule(accountId, id);
    setRules((current) => current.filter((rule) => rule.id !== id));
  };

  const reorderRules = async ({ active, over }) => {
    if (!over || active.id === over.id) return;
    const oldIndex = rules.findIndex((rule) => rule.id === active.id);
    const newIndex = rules.findIndex((rule) => rule.id === over.id);
    if (oldIndex < 0 || newIndex < 0) return;

    const previous = rules;
    const reordered = arrayMove(rules, oldIndex, newIndex).map(
      (rule, index) => ({
        ...rule,
        order: index,
      })
    );
    const changed = reordered.filter(
      (rule) =>
        !rule.isNew &&
        previous.find((item) => item.id === rule.id)?.order !== rule.order
    );
    commitRules(reordered);
    if (profileMode) {
      onChange?.(reordered.map((rule) => rulePayload(rule)));
      return;
    }
    setLoading(true);
    try {
      const saved = await Promise.all(
        changed.map((rule) =>
          API.updateM3UGroupRule(accountId, rule.id, rulePayload(rule))
        )
      );
      const savedById = new Map(saved.map((rule) => [rule.id, rule]));
      setRules((current) =>
        current.map((rule) => savedById.get(rule.id) || rule)
      );
      showNotification({
        title: 'Import rule order saved',
        message: 'First matching rule continues to win during future scans.',
        color: 'green',
      });
    } catch (error) {
      setRules(previous);
      showNotification({
        title: 'Import rule order was not saved',
        message: error?.message || 'Please retry.',
        color: 'red',
      });
    } finally {
      setLoading(false);
    }
  };

  return (
    <Stack gap="xs" mt="md">
      <Group justify="space-between">
        <div>
          <Text fw={600} size="sm">
            Import rules
          </Text>
          <Text c="dimmed" size="xs">
            {profileMode
              ? 'First matching rule wins. Save stores the ordered rule draft. Preview shows its effect, and Save and apply updates the current source selection. The main Save profile button persists the profile and starts one catalog rebuild.'
              : 'First matching rule wins. Use an earlier disable or ignore rule for exclusions. Existing choices and learned or manual metadata are not changed unless you preview and explicitly apply a rule.'}
          </Text>
        </div>
        <Group gap="xs">
          <Button
            size="xs"
            variant="default"
            leftSection={<Plus size={14} />}
            onClick={addRule}
            loading={loading}
          >
            Add rule
          </Button>
        </Group>
      </Group>

      {rules.length === 0 ? (
        <Alert color="gray" variant="light">
          {profileMode
            ? 'No rule configured. Categories stay blocked unless they are allowed directly in Sources.'
            : 'No rule configured. New unmatched groups are imported inactive.'}
        </Alert>
      ) : (
        <ScrollArea type="auto">
          <Table
            striped
            withTableBorder
            miw={profileMode ? 900 : scope === 'live' ? 1150 : 1650}
            verticalSpacing="xs"
          >
            <TableThead>
              <TableTr>
                <TableTh w={48} aria-label="Rule order" />
                {profileMode && <TableTh w={190}>M3U account</TableTh>}
                {!profileMode && <TableTh w={145}>Match</TableTh>}
                <TableTh>Regular expression</TableTh>
                {!profileMode && <TableTh w={120}>Item mode</TableTh>}
                <TableTh w={145}>Result</TableTh>
                {!profileMode && scope !== 'live' && (
                  <TableTh w={175}>DUB</TableTh>
                )}
                {!profileMode && scope !== 'live' && (
                  <TableTh w={175}>SUB</TableTh>
                )}
                {!profileMode && scope !== 'live' && (
                  <TableTh w={120}>Resolution</TableTh>
                )}
                {!profileMode && scope !== 'live' && (
                  <TableTh w={180}>Features</TableTh>
                )}
                <TableTh w={75}>Case</TableTh>
                <TableTh w={75}>Active</TableTh>
                <TableTh w={80}>Actions</TableTh>
              </TableTr>
            </TableThead>
            <DndContext
              sensors={sensors}
              collisionDetection={closestCenter}
              modifiers={[restrictToVerticalAxis]}
              onDragEnd={reorderRules}
            >
              <SortableContext
                items={rules.map((rule) => rule.id)}
                strategy={verticalListSortingStrategy}
              >
                <TableTbody>
                  {rules.map((rule) => (
                    <SortableRuleRow
                      key={rule.id}
                      ruleId={rule.id}
                      error={ruleErrors[rule.id]}
                    >
                      {profileMode && (
                        <TableTd>
                          <Select
                            size="xs"
                            clearable
                            searchable
                            placeholder="All accounts"
                            aria-label="M3U account for profile category rule"
                            value={
                              rule.m3u_account_id
                                ? String(rule.m3u_account_id)
                                : null
                            }
                            data={accountOptions}
                            onChange={(value) =>
                              updateLocal(rule.id, {
                                m3u_account_id: value || null,
                              })
                            }
                          />
                        </TableTd>
                      )}
                      {!profileMode && (
                        <TableTd>
                          <Select
                            size="xs"
                            value={rule.match_field}
                            data={[
                              { value: 'group_name', label: 'Group name' },
                              { value: 'item_name', label: 'Contained item' },
                            ]}
                            onChange={(value) =>
                              updateLocal(rule.id, { match_field: value })
                            }
                          />
                        </TableTd>
                      )}
                      <TableTd>
                        <TextInput
                          size="xs"
                          aria-label="Include regular expression"
                          value={rule.regex_pattern}
                          error={ruleErrors[rule.id] || null}
                          onChange={(event) =>
                            updateLocal(rule.id, {
                              regex_pattern: event.currentTarget.value,
                            })
                          }
                        />
                      </TableTd>
                      {!profileMode && (
                        <TableTd>
                          <Select
                            size="xs"
                            disabled={rule.match_field !== 'item_name'}
                            value={rule.match_mode}
                            data={[
                              { value: 'any', label: 'Any item' },
                              { value: 'all', label: 'All items' },
                            ]}
                            onChange={(value) =>
                              updateLocal(rule.id, { match_mode: value })
                            }
                          />
                        </TableTd>
                      )}
                      <TableTd>
                        <Select
                          size="xs"
                          value={rule.action}
                          data={[
                            {
                              value: 'enable',
                              label: profileMode
                                ? 'Allow in profile'
                                : 'Import enabled',
                            },
                            {
                              value: 'disable',
                              label: profileMode
                                ? 'Block in profile'
                                : 'Import disabled',
                            },
                            ...(!profileMode
                              ? [{ value: 'ignore', label: 'Ignore group' }]
                              : []),
                          ]}
                          onChange={(value) =>
                            updateLocal(rule.id, { action: value })
                          }
                        />
                      </TableTd>
                      {!profileMode && scope !== 'live' && (
                        <TableTd>
                          <LanguagePicker
                            size="xs"
                            value={
                              rule.metadata_defaults?.audio_languages || []
                            }
                            onChange={(value) =>
                              updateMetadata(
                                rule,
                                'audio_languages',
                                normalizeLanguageCodes(value)
                              )
                            }
                          />
                        </TableTd>
                      )}
                      {!profileMode && scope !== 'live' && (
                        <TableTd>
                          <LanguagePicker
                            size="xs"
                            value={
                              rule.metadata_defaults?.subtitle_languages || []
                            }
                            onChange={(value) =>
                              updateMetadata(
                                rule,
                                'subtitle_languages',
                                normalizeLanguageCodes(value)
                              )
                            }
                          />
                        </TableTd>
                      )}
                      {!profileMode && scope !== 'live' && (
                        <TableTd>
                          <Select
                            size="xs"
                            clearable
                            data={RESOLUTION_VALUES}
                            value={rule.metadata_defaults?.resolution || null}
                            onChange={(value) =>
                              updateMetadata(rule, 'resolution', value || '')
                            }
                          />
                        </TableTd>
                      )}
                      {!profileMode && scope !== 'live' && (
                        <TableTd>
                          <VideoFeaturePicker
                            size="xs"
                            label={null}
                            value={rule.metadata_defaults?.video_features || []}
                            onChange={(value) =>
                              updateMetadata(rule, 'video_features', value)
                            }
                          />
                        </TableTd>
                      )}
                      <TableTd>
                        <Checkbox
                          aria-label="Case sensitive"
                          checked={rule.case_sensitive}
                          onChange={(event) =>
                            updateLocal(rule.id, {
                              case_sensitive: event.currentTarget.checked,
                            })
                          }
                        />
                      </TableTd>
                      <TableTd>
                        <Checkbox
                          aria-label="Rule active"
                          checked={rule.enabled}
                          onChange={(event) =>
                            updateLocal(rule.id, {
                              enabled: event.currentTarget.checked,
                            })
                          }
                        />
                      </TableTd>
                      <TableTd>
                        <Group gap={4} wrap="nowrap">
                          <ActionIcon
                            aria-label="Save rule"
                            color="blue"
                            variant="subtle"
                            onClick={() =>
                              profileMode ? saveProfileDraft() : saveRule(rule)
                            }
                          >
                            <Save size={15} />
                          </ActionIcon>
                          <ActionIcon
                            aria-label={
                              profileMode
                                ? 'Preview rule'
                                : 'Preview and apply rule'
                            }
                            color="green"
                            variant="subtle"
                            disabled={rule.isNew}
                            onClick={() => openPreview(rule)}
                          >
                            <Play size={15} />
                          </ActionIcon>
                          <ActionIcon
                            aria-label="Delete rule"
                            color="red"
                            variant="subtle"
                            onClick={() => deleteRule(rule.id)}
                          >
                            <Trash2 size={15} />
                          </ActionIcon>
                        </Group>
                      </TableTd>
                    </SortableRuleRow>
                  ))}
                </TableTbody>
              </SortableContext>
            </DndContext>
          </Table>
        </ScrollArea>
      )}

      <Modal
        opened={!!previewRule}
        onClose={() => {
          setPreviewRule(null);
          setPreview(null);
        }}
        title="Import rule preview"
        size="xl"
      >
        <Stack>
          <Text size="sm" c="dimmed">
            This preview evaluates the complete ordered draft without changing
            the profile. Only rows for which this rule is the first match are
            shown.
          </Text>
          <Text fw={600}>
            {previewLoading
              ? 'Evaluating…'
              : `${preview?.count || 0} matching existing entries`}
          </Text>
          <ScrollArea h="45vh">
            <Table striped withTableBorder stickyHeader>
              <TableThead>
                <TableTr>
                  {profileMode && <TableTh>M3U account</TableTh>}
                  <TableTh>Name</TableTh>
                  <TableTh w={90}>Current</TableTh>
                  <TableTh w={110}>Result</TableTh>
                  <TableTh w={90}>Items</TableTh>
                </TableTr>
              </TableThead>
              <TableTbody>
                {(profileMode
                  ? (preview?.results || []).slice(
                      (previewPage - 1) * previewPageSize,
                      previewPage * previewPageSize
                    )
                  : preview?.results || []
                ).map((row) => (
                  <TableTr key={row.relation_id}>
                    {profileMode && <TableTd>{row.account_name}</TableTd>}
                    <TableTd>{row.name}</TableTd>
                    <TableTd>
                      {row.currently_enabled ? 'Active' : 'Inactive'}
                    </TableTd>
                    <TableTd>
                      {row.would_enable === null
                        ? 'No change'
                        : row.would_enable
                          ? 'Active'
                          : 'Inactive'}
                    </TableTd>
                    <TableTd>{row.item_count}</TableTd>
                  </TableTr>
                ))}
              </TableTbody>
            </Table>
          </ScrollArea>
          <ListPagination
            page={previewPage}
            pageSize={previewPageSize}
            total={preview?.count || 0}
            onPageChange={changePreviewPage}
            onPageSizeChange={changePreviewPageSize}
            pageSizes={[25, 50, 100, 200]}
          />
          <Group justify="flex-end">
            <Button
              variant="default"
              onClick={() => {
                setPreviewRule(null);
                setPreview(null);
              }}
            >
              Close
            </Button>
            <Button
              loading={previewLoading}
              disabled={
                !preview?.count ||
                (!profileMode && previewRule?.action === 'ignore')
              }
              onClick={applyPreview}
            >
              {profileMode ? 'Save and apply' : 'Save and apply to existing'}
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Stack>
  );
};

export default M3UGroupRules;
