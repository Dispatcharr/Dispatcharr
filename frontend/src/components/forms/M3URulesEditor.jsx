import { useCallback, useEffect, useRef, useState } from 'react';
import {
  ActionIcon,
  Alert,
  Anchor,
  Badge,
  Button,
  Checkbox,
  Group,
  Popover,
  ScrollArea,
  Select,
  Stack,
  Switch,
  Table,
  TableTbody,
  TableTd,
  TableTh,
  TableThead,
  TableTr,
  Text,
  Tooltip,
  UnstyledButton,
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
import { restrictToVerticalAxis } from '@dnd-kit/modifiers';
import { CSS } from '@dnd-kit/utilities';
import {
  Ban,
  CircleHelp,
  Eye,
  GripVertical,
  Info,
  Plus,
  Save,
  SquarePen,
  Settings,
  Trash2,
  TriangleAlert,
  X,
} from 'lucide-react';
import API from '../../api.js';
import {
  hideNotification,
  showNotification,
} from '../../utils/notificationUtils.js';
import {
  useDateTimeFormat,
  useTimeHelpers,
} from '../../utils/dateTimeUtils.js';
import ConfirmationDialog from '../ConfirmationDialog.jsx';
import ListPagination from '../ListPagination.jsx';
import { SensitiveTextInput as TextInput } from '../SensitiveFields.jsx';
import { formatApiError } from '../../utils.js';
import {
  findDuplicateRule,
  getRuleCoverage,
  ruleCheckSignature,
  isRetiredImportRule,
  isRuleEnabled,
} from './M3URulesEditor.utils.js';
import useM3URuleChecks from '../../store/useM3URuleChecks.js';
import editorClasses from './AccountEditor.module.css';
import classes from './M3URulesEditor.module.css';
import StackedModal from '../StackedModal.jsx';
import VODCategoryMetadataEditor from './VODCategoryMetadataEditor.jsx';
import VODMetadataCell from './VODMetadataCell.jsx';
import MEDIA_LANGUAGE_OPTIONS from '../../../../apps/vod/media_languages.json';
import { getM3UStreamLabel } from '../../utils/forms/M3uSetupUtils.js';
import {
  VOD_METADATA_FIELDS,
  VOD_METADATA_LABELS,
  VOD_RESOLUTIONS,
  metadataSummary,
} from '../../utils/vodSourceMetadata.js';

const SortableRow = ({
  id,
  children,
  error,
  warning,
  covered,
  dirty,
  editing,
  inactive,
  disabled,
  noun,
  marker,
}) => {
  const { attributes, listeners, setNodeRef, transform, transition } =
    useSortable({ id, disabled });
  return (
    <TableTr
      ref={setNodeRef}
      data-invalid={error ? 'true' : undefined}
      data-rule-id={id}
      data-warning={warning ? 'true' : undefined}
      data-covered={covered ? 'true' : undefined}
      className={classes.ruleRow}
      data-dirty={dirty ? 'true' : undefined}
      data-editing={editing ? 'true' : undefined}
      data-inactive={inactive ? 'true' : undefined}
      title={dirty ? 'Unsaved changes' : undefined}
      style={{
        transform: CSS.Transform.toString(transform),
        transition,
        boxShadow:
          dirty || editing
            ? 'inset 3px 0 var(--mantine-color-blue-5)'
            : undefined,
        backgroundColor: error
          ? 'var(--mantine-color-red-light)'
          : warning
            ? 'var(--mantine-color-yellow-light)'
            : dirty || editing
              ? 'var(--mantine-color-blue-light)'
              : covered
                ? 'var(--mantine-color-default-hover)'
                : undefined,
      }}
    >
      <TableTd className={classes.centeredCell}>
        <ActionIcon
          aria-label={`Move ${noun}`}
          variant="default"
          size="sm"
          color="gray"
          disabled={disabled}
          {...attributes}
          {...listeners}
        >
          <GripVertical size={16} />
        </ActionIcon>
      </TableTd>
      <TableTd className={classes.centeredCell}>{marker}</TableTd>
      {children}
    </TableTr>
  );
};

const RuleMarker = ({ error, cause, coveredBy }) => {
  const message = error || cause?.details || cause?.message || coveredBy;
  if (!message) return null;
  return (
    <Tooltip
      label={message}
      events={{ hover: true, focus: true, touch: true }}
      multiline
      w={280}
      withArrow
    >
      <span
        tabIndex={0}
        role="img"
        aria-label={message}
        className={classes.coverageMarker}
        style={{
          color: error
            ? 'var(--mantine-color-red-6)'
            : cause
              ? 'var(--mantine-color-yellow-6)'
              : undefined,
        }}
      >
        {error || cause ? (
          <TriangleAlert size={15} aria-hidden="true" />
        ) : (
          <Ban size={15} aria-hidden="true" />
        )}
      </span>
    </Tooltip>
  );
};

const savedRuleErrors = (rows, streamFilters) => {
  const errors = {};
  rows.forEach((row, index) => {
    const duplicate = findDuplicateRule(
      row,
      rows.slice(0, index),
      streamFilters
    );
    if (!row.regex_pattern?.trim())
      errors[row.id] = 'Enter a regular expression before saving.';
    else if (duplicate)
      errors[row.id] =
        `An identical active match already exists (rule ${rows.findIndex((item) => item.id === duplicate.id) + 1}). Edit or remove the duplicate.`;
  });
  return errors;
};

const M3URulesEditor = ({
  accountId,
  accountType = 'XC',
  scope,
  streamFilters = false,
  onApplied,
  onStateChange,
  onRulesChanged,
  previewGroupIds,
}) => {
  const streamLabel = getM3UStreamLabel(accountType);
  const kind = streamFilters ? 'filters' : 'group-rules';
  const [rules, setRules] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [rowErrors, setRowErrors] = useState({});
  const [dirtyIds, setDirtyIds] = useState(new Set());
  const [activeRuleId, setActiveRuleId] = useState(null);
  const activeInput = useRef(null);
  const originalRowError = useRef(null);
  const [previewError, setPreviewError] = useState(null);
  const [previewTarget, setPreviewTarget] = useState(null);
  const [previewEditing, setPreviewEditing] = useState(false);
  const [discardPreview, setDiscardPreview] = useState(false);
  const previewInput = useRef(null);
  const [previewDraft, setPreviewDraft] = useState([]);
  const [preview, setPreview] = useState(null);
  const [testedPreviewSignature, setTestedPreviewSignature] = useState(null);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const [previewBusy, setPreviewBusy] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [confirmApply, setConfirmApply] = useState(false);
  const [regexHelpOpen, setRegexHelpOpen] = useState(false);
  const [metadataTarget, setMetadataTarget] = useState(null);
  const vodRules = !streamFilters && ['movie', 'series'].includes(scope);
  const [coverage, setCoverage] = useState({ causes: {}, coveredBy: {} });
  const [matchCheck, setMatchCheck] = useState(null);
  const [inventoryCount, setInventoryCount] = useState(null);
  const coverageRequest = useRef(0);
  const previewRequest = useRef(0);
  const saving = useRef(false);
  const savedRules = useRef(new Map());
  const rulesLoaded = useRef(false);
  const onRulesChangedRef = useRef(onRulesChanged);
  onRulesChangedRef.current = onRulesChanged;
  useEffect(() => {
    if (rulesLoaded.current)
      onRulesChangedRef.current?.([...savedRules.current.values()]);
  }, [rules]);
  const lastCoverageNotice = useRef(null);
  const errorNotificationId = `account-rules-${accountId}-${kind}-error`;
  const coverageNotificationId = `account-rules-${accountId}-${kind}-coverage`;
  const checkKey = `${accountId}-${kind}-${scope || 'live'}${previewGroupIds ? `-preview-${previewGroupIds.join(',')}` : ''}`;
  const { dateYearFormat, timeFormat } = useDateTimeFormat();
  const { toUserTime } = useTimeHelpers();
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates })
  );

  const payload = useCallback(
    (rule) =>
      streamFilters
        ? {
            filter_type: rule.filter_type,
            regex_pattern: rule.regex_pattern,
            exclude: rule.exclude,
            enabled: isRuleEnabled(rule, true),
            order: rule.order,
            custom_properties: {
              ...(rule.custom_properties || {}),
              case_sensitive: rule.custom_properties?.case_sensitive !== false,
            },
          }
        : {
            scope,
            regex_pattern: rule.regex_pattern,
            action: rule.action,
            case_sensitive: rule.case_sensitive,
            enabled: !isRetiredImportRule(rule) && rule.enabled,
            order: rule.order,
            ...(vodRules
              ? { metadata_defaults: rule.metadata_defaults || {} }
              : {}),
          },
    [streamFilters, scope, vodRules]
  );

  const rememberMatches = useCallback(
    (rows, response) => {
      const checkedIds = new Set(
        rows
          .filter((row) => isRuleEnabled(row, streamFilters))
          .map((row) => String(row.id))
      );
      setMatchCheck({
        counts:
          response.inventory_count > 0
            ? Object.fromEntries(
                (response.rule_coverage || [])
                  .filter(
                    (row) =>
                      checkedIds.has(String(row.rule_id)) &&
                      Number.isInteger(row.count) &&
                      row.count >= 0
                  )
                  .map((row) => [String(row.rule_id), row.count])
              )
            : {},
      });
    },
    [streamFilters]
  );

  const acceptCoverage = useCallback(
    (rows, response, forceNotice = false, notify = true) => {
      rememberMatches(rows, response);
      setInventoryCount(response.inventory_count ?? null);
      const found = getRuleCoverage(rows, response, streamFilters);
      const causes = Object.values(found.causes);
      setCoverage(found);
      useM3URuleChecks
        .getState()
        .remember(checkKey, ruleCheckSignature(rows, streamFilters), found);
      const noticeKey = JSON.stringify(causes.map((cause) => cause.key));
      if (!causes.length) hideNotification(coverageNotificationId);
      else if (
        notify &&
        (forceNotice || noticeKey !== lastCoverageNotice.current)
      ) {
        hideNotification(coverageNotificationId);
        showNotification({
          id: coverageNotificationId,
          title: streamFilters
            ? 'Stream filter warning'
            : 'Import rule warning',
          message: causes.map((cause) => cause.message).join('\n'),
          color: 'yellow',
          autoClose: false,
        });
      }
      lastCoverageNotice.current = noticeKey;
      return found;
    },
    [coverageNotificationId, streamFilters, checkKey, rememberMatches]
  );

  const checkSavedRows = useCallback(
    async (rows, requestId) => {
      if (!rows.length) {
        setMatchCheck(null);
        setInventoryCount(null);
        setCoverage({ causes: {}, coveredBy: {} });
        hideNotification(coverageNotificationId);
        lastCoverageNotice.current = null;
      }
      const errors = savedRuleErrors(rows, streamFilters);
      try {
        if (rows.length) {
          const response = await API.analyzeM3URules(
            accountId,
            kind,
            rows.map((row) => ({
              ...payload(row),
              preview_id: String(row.id),
            })),
            ...(previewGroupIds ? [{ groupIds: previewGroupIds }] : [])
          );
          if (requestId !== coverageRequest.current) return;
          acceptCoverage(rows, response, false, !Object.keys(errors).length);
        }
      } catch (error) {
        if (requestId !== coverageRequest.current) return;
        setMatchCheck(null);
        setInventoryCount(null);
        setCoverage({ causes: {}, coveredBy: {} });
        hideNotification(coverageNotificationId);
        error.body?.rules?.forEach?.((fields, index) => {
          if (fields && Object.keys(fields).length && rows[index])
            errors[rows[index].id] = formatApiError({
              status: error.status,
              body: fields,
            });
        });
        if (!Object.keys(errors).length) errors._check = formatApiError(error);
      }
      if (requestId !== coverageRequest.current) return;
      const { _check, ...rowIssues } = errors;
      setRowErrors(rowIssues);
      if (Object.keys(errors).length) {
        hideNotification(coverageNotificationId);
        hideNotification(errorNotificationId);
        showNotification({
          id: errorNotificationId,
          title: streamFilters ? 'Check stream filters' : 'Check import rules',
          message: _check || Object.values(rowIssues).join('\n'),
          color: 'red',
          autoClose: false,
        });
      } else hideNotification(errorNotificationId);
    },
    [
      accountId,
      kind,
      payload,
      streamFilters,
      acceptCoverage,
      coverageNotificationId,
      errorNotificationId,
      previewGroupIds,
    ]
  );

  const load = useCallback(async () => {
    const requestId = ++coverageRequest.current;
    setBusy(true);
    setMatchCheck(null);
    setInventoryCount(null);
    try {
      const loaded = await API.getM3URules(accountId, kind, scope);
      if (requestId !== coverageRequest.current) return;
      savedRules.current = new Map(loaded.map((rule) => [rule.id, rule]));
      rulesLoaded.current = true;
      setRules(loaded);
      setDirtyIds(new Set());
      setActiveRuleId(null);
      setRowErrors({});
      setError(null);
      const checked = useM3URuleChecks.getState().checks[checkKey];
      const restored =
        checked?.signature === ruleCheckSignature(loaded, streamFilters)
          ? checked.coverage
          : { causes: {}, coveredBy: {} };
      setCoverage(restored);
      await checkSavedRows(loaded, requestId);
    } catch (error) {
      if (requestId === coverageRequest.current)
        setError(error.message || 'Rules could not be loaded.');
    } finally {
      if (requestId === coverageRequest.current) setBusy(false);
    }
  }, [accountId, kind, scope, checkKey, streamFilters, checkSavedRows]);

  useEffect(() => {
    load();
  }, [load]);
  useEffect(
    () => () => {
      previewRequest.current += 1;
      coverageRequest.current += 1;
    },
    []
  );

  useEffect(
    () => () => {
      hideNotification(errorNotificationId);
      hideNotification(coverageNotificationId);
    },
    [errorNotificationId, coverageNotificationId]
  );

  const update = (id, values) => {
    if (busy || activeRuleId !== id) return;
    const updated = { ...rules.find((rule) => rule.id === id), ...values };
    setRules((current) =>
      current.map((rule) => (rule.id === id ? updated : rule))
    );
    setError(null);
    setDirtyIds((current) => {
      const next = new Set(current);
      const original = savedRules.current.get(id);
      // Order is persisted separately; reverting field edits is not dirty.
      const fields = (rule) => ({ ...payload(rule), order: 0 });
      if (
        original &&
        JSON.stringify(fields(updated)) === JSON.stringify(fields(original))
      )
        next.delete(id);
      else next.add(id);
      return next;
    });
    setRowErrors((current) => ({ ...current, [id]: undefined }));
    hideNotification(errorNotificationId);
    coverageRequest.current += 1;
  };

  const notifyError = (message) => {
    hideNotification(errorNotificationId);
    showNotification({
      id: errorNotificationId,
      title: streamFilters
        ? 'Stream filter was not saved'
        : 'Import rule was not saved',
      message,
      color: 'red',
      autoClose: false,
    });
  };

  const persistedRows = (ordered = rules, replacement) =>
    ordered.flatMap((rule) => {
      const saved =
        replacement?.id === rule.id
          ? replacement
          : savedRules.current.get(rule.id);
      return saved ? [{ ...saved, order: rule.order }] : [];
    });

  const startEditing = (rule) => {
    if (busy || activeRuleId !== null || previewTarget || metadataTarget)
      return;
    originalRowError.current = rowErrors[rule.id];
    setActiveRuleId(rule.id);
  };

  const discardRow = (rule) => {
    if (busy || activeRuleId !== rule.id) return;
    coverageRequest.current += 1;
    setRules((current) =>
      rule.isNew
        ? current.filter((item) => item.id !== rule.id)
        : current.map((item) =>
            item.id === rule.id
              ? { ...savedRules.current.get(rule.id), order: item.order }
              : item
          )
    );
    setDirtyIds((current) => {
      const next = new Set(current);
      next.delete(rule.id);
      return next;
    });
    setRowErrors((current) => ({
      ...current,
      [rule.id]: originalRowError.current,
    }));
    setActiveRuleId(null);
    hideNotification(errorNotificationId);
  };

  const add = () => {
    if (busy || activeRuleId !== null || previewTarget || metadataTarget)
      return;
    const rule = {
      id: `new-${crypto.randomUUID()}`,
      isNew: true,
      order: Math.max(-1, ...rules.map((item) => item.order)) + 1,
      regex_pattern: '',
      filter_type: 'name',
      exclude: true,
      custom_properties: { case_sensitive: false },
      scope,
      action: 'disable',
      case_sensitive: false,
      enabled: true,
    };
    const next = [...rules, rule];
    setRules(next);
    originalRowError.current = undefined;
    setActiveRuleId(rule.id);
  };

  const save = async (rule) => {
    const saved = await API.saveM3URule(
      accountId,
      kind,
      rule.isNew ? null : rule.id,
      payload(rule)
    );
    savedRules.current.delete(rule.id);
    savedRules.current.set(saved.id, saved);
    hideNotification(errorNotificationId);
    setRules((current) =>
      current.map((item) => (item.id === rule.id ? saved : item))
    );
    setDirtyIds((current) => {
      const next = new Set(current);
      next.delete(rule.id);
      return next;
    });
    setRowErrors((current) => ({ ...current, [rule.id]: undefined }));
    setActiveRuleId(null);
    return saved;
  };

  const saveRow = async (rule, fromPreview = false) => {
    if (
      busy ||
      saving.current ||
      previewBusy ||
      (activeRuleId !== rule.id && !(fromPreview && activeRuleId === null))
    )
      return null;
    saving.current = true;
    setBusy(true);
    hideNotification(errorNotificationId);
    hideNotification(coverageNotificationId);
    const requestId = ++coverageRequest.current;
    const fail = (message) => {
      if (fromPreview) setPreviewError(message);
      else {
        setRowErrors((current) => ({ ...current, [rule.id]: message }));
        notifyError(message);
      }
      return null;
    };
    try {
      if (!rule.regex_pattern?.trim()) {
        return fail('Enter a regular expression before saving.');
      }
      if (!streamFilters && isRetiredImportRule(rule)) {
        const message =
          'Choose Enabled, Disabled or Ignore before saving this paused rule.';
        return fail(message);
      }
      const duplicate = findDuplicateRule(rule, persistedRows(), streamFilters);
      if (duplicate) {
        const message = `An identical active match already exists (rule ${rules.findIndex((item) => item.id === duplicate.id) + 1}). Edit that rule instead.`;
        return fail(message);
      }
      const checkedRows = persistedRows(rules, rule);
      let response;
      try {
        response = await API.analyzeM3URules(
          accountId,
          kind,
          checkedRows.map((item) => ({
            ...payload(item),
            preview_id: String(item.id),
          })),
          ...(previewGroupIds ? [{ groupIds: previewGroupIds }] : [])
        );
      } catch (error) {
        return fail(ruleError(error, checkedRows, rule));
      }
      if (requestId !== coverageRequest.current) return;
      const saved = await save(rule);
      if (saved) {
        setError(null);
        const checkedSavedRows = checkedRows.map((item) =>
          item.id === rule.id ? saved : item
        );
        setRowErrors(savedRuleErrors(checkedSavedRows, streamFilters));
        const checked = acceptCoverage(
          checkedSavedRows,
          {
            ...response,
            rule_coverage: response.rule_coverage?.map((row) => ({
              ...row,
              rule_id:
                String(row.rule_id) === String(rule.id)
                  ? String(saved.id)
                  : row.rule_id,
            })),
          },
          true
        );
        if (!Object.keys(checked.causes).length) {
          const effectUnchecked = streamFilters && !response.inventory_count;
          showNotification({
            id: coverageNotificationId,
            title: streamFilters ? 'Stream filter saved' : 'Import rule saved',
            message: effectUnchecked
              ? 'Saved. No stream data available for testing.'
              : 'Saved.',
            color: effectUnchecked ? 'gray' : 'green',
          });
        }
        return saved;
      }
    } catch (error) {
      const message = formatApiError(error);
      if (fromPreview) setPreviewError(message);
      else setRowErrors((current) => ({ ...current, [rule.id]: message }));
      return null;
    } finally {
      saving.current = false;
      setBusy(false);
    }
    return null;
  };

  const ruleError = (error, draft, target) => {
    const targetIndex = draft.findIndex((rule) => rule.id === target.id);
    const invalidPatterns = Object.entries(error.body?.rules || {}).flatMap(
      ([index, fields]) =>
        fields?.regex_pattern
          ? [
              `${Number(index) === targetIndex ? '' : `Rule ${Number(index) + 1}: `}${[fields.regex_pattern].flat().join(' ')}`,
            ]
          : []
    );
    return invalidPatterns.join(' ') || formatApiError(error);
  };

  const loadPreview = async (draft, target, nextPage, nextPageSize) => {
    const requestId = ++previewRequest.current;
    setPreviewBusy(true);
    setPreviewError(null);
    setPreview(null);
    setTestedPreviewSignature(null);
    try {
      const response = await API.previewM3URules(
        accountId,
        kind,
        draft.map((rule) => ({
          ...payload(rule),
          preview_id: String(rule.id),
        })),
        target.id,
        nextPage,
        nextPageSize,
        {
          notifyOnError: false,
          ...(previewGroupIds ? { groupIds: previewGroupIds } : {}),
        }
      );
      if (requestId === previewRequest.current) {
        setPreview(response);
        setTestedPreviewSignature(ruleCheckSignature(draft, streamFilters));
        setInventoryCount(response.inventory_count ?? null);
        hideNotification(errorNotificationId);
      }
    } catch (error) {
      if (requestId === previewRequest.current) {
        setPreviewError(ruleError(error, draft, target));
      }
    } finally {
      if (requestId === previewRequest.current) setPreviewBusy(false);
    }
  };

  const openPreview = (rule) => {
    if (
      busy ||
      (activeRuleId !== null && activeRuleId !== rule.id) ||
      !isRuleEnabled(rule, streamFilters)
    )
      return;
    const draft = rules.map((item) => ({
      ...item,
      custom_properties: { ...(item.custom_properties || {}) },
    }));
    setPreviewTarget(rule);
    setPreviewEditing(false);
    setDiscardPreview(false);
    setPreviewDraft(draft);
    previewRequest.current += 1;
    setPreview(null);
    setPreviewError(null);
    setTestedPreviewSignature(null);
    setPreviewBusy(false);
    setConfirmApply(false);
    setPage(1);
    if (
      draft.every((item) => item.regex_pattern?.trim()) &&
      hasPreviewData &&
      isRuleEnabled(rule, streamFilters)
    )
      loadPreview(draft, rule, 1, pageSize);
  };

  const closePreview = () => {
    previewRequest.current += 1;
    setPreviewTarget(null);
    setPreviewEditing(false);
    setDiscardPreview(false);
    setPreview(null);
    setTestedPreviewSignature(null);
    setPreviewBusy(false);
    hideNotification(errorNotificationId);
    setPreviewError(null);
    setConfirmApply(false);
  };

  const updatePreview = (values) => {
    if (!previewEditing || busy || !canEditPreview) return;
    previewRequest.current += 1;
    setPreviewBusy(false);
    setPreview(null);
    setTestedPreviewSignature(null);
    setPreviewError(null);
    setConfirmApply(false);
    setPreviewTarget((current) => ({ ...current, ...values }));
    setPreviewDraft((current) =>
      current.map((row) =>
        row.id === previewTarget.id ? { ...row, ...values } : row
      )
    );
    setPage(1);
  };

  const savePreview = async () => {
    if (await saveRow(previewTarget, true)) closePreview();
  };

  const requestClosePreview = () => {
    if (busy) return;
    if (previewHasChanges) setDiscardPreview(true);
    else closePreview();
  };

  useEffect(() => {
    if (previewEditing) previewInput.current?.focus();
  }, [previewEditing]);

  useEffect(() => {
    if (activeRuleId !== null && !previewTarget) activeInput.current?.focus();
  }, [activeRuleId, previewTarget]);

  const apply = async () => {
    if (
      streamFilters ||
      !confirmApply ||
      !previewChecked ||
      previewHasChanges ||
      !rules.some((rule) => rule.id === previewTarget?.id) ||
      hasUnsavedChanges ||
      activeRuleId !== null ||
      !preview.count ||
      !isRuleEnabled(previewTarget || {}, streamFilters)
    )
      return;
    setPreviewBusy(true);
    try {
      const result = await API.saveApplyM3UGroupRules(
        accountId,
        previewDraft.map((rule) => ({
          ...payload(rule),
          preview_id: String(rule.id),
        })),
        previewTarget.id
      );
      showNotification({
        title: 'Import rule applied',
        message: `${result.updated} existing entries updated.`,
        color: 'green',
      });
      await onApplied?.(result);
      await load();
      closePreview();
    } catch (error) {
      setConfirmApply(false);
      setPreviewError(formatApiError(error));
    } finally {
      setPreviewBusy(false);
    }
  };

  const reorder = async ({ active, over }) => {
    if (busy || activeRuleId !== null || !over || active.id === over.id) return;
    if (
      !rules.some((rule) => rule.id === active.id) ||
      !rules.some((rule) => rule.id === over.id)
    )
      return;
    const reordered = arrayMove(
      rules,
      rules.findIndex((rule) => rule.id === active.id),
      rules.findIndex((rule) => rule.id === over.id)
    ).map((rule, order) => ({ ...rule, order }));
    await persistOrder(reordered);
  };

  const persistOrder = async (reordered) => {
    const previous = rules;
    setBusy(true);
    const requestId = ++coverageRequest.current;
    try {
      setRules(reordered);
      const saved = reordered.filter((rule) => !rule.isNew);
      await API.reorderM3URules(
        accountId,
        kind,
        saved.map((rule) => rule.id),
        scope,
        saved.map((rule) => rule.order)
      );
      for (const rule of saved) {
        savedRules.current.set(rule.id, {
          ...savedRules.current.get(rule.id),
          order: rule.order,
        });
      }
      hideNotification(errorNotificationId);
      setCoverage({ causes: {}, coveredBy: {} });
      useM3URuleChecks.getState().forget(checkKey);
      await checkSavedRows(persistedRows(reordered), requestId);
    } catch (error) {
      setRules(previous);
      setError(error.message || 'Order could not be saved.');
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    if (busy || activeRuleId !== null || !deleteTarget) return;
    setBusy(true);
    const requestId = ++coverageRequest.current;
    try {
      await API.deleteM3URule(accountId, kind, deleteTarget.id);
      savedRules.current.delete(deleteTarget.id);
      hideNotification(errorNotificationId);
      const remaining = rules.filter((rule) => rule.id !== deleteTarget.id);
      setRules(remaining);
      setDirtyIds((current) => {
        const next = new Set(current);
        next.delete(deleteTarget.id);
        return next;
      });
      setRowErrors((current) => ({ ...current, [deleteTarget.id]: undefined }));
      setDeleteTarget(null);
      setCoverage({ causes: {}, coveredBy: {} });
      useM3URuleChecks.getState().forget(checkKey);
      await checkSavedRows(persistedRows(remaining), requestId);
    } catch (error) {
      setError(error.message || 'Rule could not be deleted.');
    } finally {
      setBusy(false);
    }
  };

  const noun = streamFilters ? 'filter' : 'rule';
  const hasUnsavedChanges =
    dirtyIds.size > 0 || rules.some((rule) => rule.isNew);
  const previewHasChanges =
    !!previewTarget &&
    rules.some((rule) => rule.id === previewTarget.id) &&
    JSON.stringify(payload(previewTarget)) !==
      JSON.stringify(
        payload(rules.find((rule) => rule.id === previewTarget.id))
      );
  const hasActiveEdit = activeRuleId !== null;
  const canEditPreview = !hasActiveEdit || activeRuleId === previewTarget?.id;
  const hasPreviewData = !streamFilters || inventoryCount !== 0;
  const previewUnavailableHint = (rule) =>
    hasActiveEdit && activeRuleId !== rule.id
      ? `Save or discard the current ${noun} before previewing another.`
      : !isRuleEnabled(rule, streamFilters)
        ? `Enable this ${noun} before previewing.`
        : rules.some((row) => !row.regex_pattern?.trim())
          ? 'Enter a regular expression in each rule before previewing.'
          : !hasPreviewData
            ? 'No stream data available for preview.'
            : null;
  const previewHint = (rule) =>
    previewUnavailableHint(rule) || `Preview ${noun}`;
  const testUnavailableHint = !isRuleEnabled(previewTarget || {}, streamFilters)
    ? `Enable this ${noun} before testing.`
    : !hasPreviewData
      ? 'No stream data available for testing.'
      : previewDraft.some((rule) => !rule.regex_pattern?.trim())
        ? 'Enter a regular expression in each rule before testing.'
        : null;
  const visibleCoverage =
    hasActiveEdit || hasUnsavedChanges
      ? { causes: {}, coveredBy: {} }
      : coverage;
  // Keep the last saved check visible while editing; drafts are not checked here.
  const matchCount = (rule) => matchCheck?.counts[String(rule.id)];
  // Reserve four digits plus locale separators, spacing, padding and borders.
  const matchCountWidth = `calc(${
    Math.max(
      (9999).toLocaleString().length,
      ...Object.values(matchCheck?.counts || {}).map(
        (count) => count.toLocaleString().length
      )
    ) + 1
  }ch + var(--badge-padding-x) + var(--badge-padding-x) + var(--badge-border-width) + var(--badge-border-width))`;
  const matchLabel = (rule) => {
    const count = matchCount(rule);
    if (count == null)
      return !isRuleEnabled(rule, streamFilters)
        ? `Enable this ${noun} to test its effect.`
        : 'No current check available.';
    return streamFilters
      ? `${count.toLocaleString()} matching streams after earlier enabled filters. Last saved check.`
      : `${count.toLocaleString()} matching categories${vodRules ? ' for at least one assigned field' : ''} after earlier enabled rules. Last saved check.`;
  };
  const coveredByMessage = (id, checked = visibleCoverage, ordered = rules) => {
    const blockers = [checked.coveredBy[id]].flat();
    const positions = blockers.map(
      (blocker) =>
        ordered.findIndex((rule) => String(rule.id) === String(blocker)) + 1
    );
    return `Covered by ${positions.length > 1 ? 'rules' : 'rule'} ${positions.join(', ')} in the last refresh snapshot. Move this rule earlier or narrow the earlier expression to give it matches.`;
  };

  useEffect(() => {
    onStateChange?.({
      dirty: hasUnsavedChanges || previewHasChanges,
      busy: busy || previewBusy,
      inventoryCount,
      overlayOpen:
        !!previewTarget || !!deleteTarget || regexHelpOpen || !!metadataTarget,
    });
  }, [
    hasUnsavedChanges,
    previewHasChanges,
    busy,
    previewBusy,
    previewTarget,
    deleteTarget,
    regexHelpOpen,
    metadataTarget,
    streamFilters,
    inventoryCount,
    onStateChange,
  ]);

  useEffect(() => {
    if (!hasUnsavedChanges && !previewHasChanges) return;
    const warn = (event) => {
      event.preventDefault();
      event.returnValue = '';
    };
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [hasUnsavedChanges, previewHasChanges]);
  const previewRows = preview?.results || [];
  const previewChecked =
    !!preview &&
    !previewError &&
    testedPreviewSignature === ruleCheckSignature(previewDraft, streamFilters);
  const previewCoverage = getRuleCoverage(previewDraft, preview, streamFilters);
  const previewWarning = previewCoverage.coveredBy[previewTarget?.id]
    ? coveredByMessage(previewTarget.id, previewCoverage, previewDraft)
    : previewCoverage.causes[previewTarget?.id]?.message;
  const refreshedAt = preview?.last_completed_refresh
    ? toUserTime(preview.last_completed_refresh).format(
        `${dateYearFormat} ${timeFormat}`
      )
    : 'Never';

  return (
    <Stack gap="sm" aria-busy={busy}>
      <Group align="flex-end" wrap="nowrap" gap="sm">
        <Alert
          icon={<Info size={16} />}
          color="blue"
          variant="light"
          p={6}
          mih={30}
          style={{ flex: 1, minWidth: 0 }}
          styles={{
            icon: { width: 16, height: 16, marginInlineEnd: 8 },
            wrapper: { alignItems: 'center' },
          }}
        >
          <Text size="xs" lh="16px">
            <strong>Order matters.</strong>{' '}
            {vodRules
              ? 'The first match wins for the import result and each metadata field separately.'
              : 'The first matching rule wins.'}
          </Text>
        </Alert>
        <Tooltip
          label={`Save or discard the current ${noun} before adding another.`}
          disabled={!hasActiveEdit}
          events={{ hover: true, focus: true, touch: true }}
          withArrow
        >
          <span
            style={{ display: 'inline-flex' }}
            tabIndex={hasActiveEdit ? 0 : undefined}
          >
            <Button
              size="xs"
              leftSection={<Plus size={14} />}
              onClick={add}
              disabled={busy || hasActiveEdit}
            >
              Add {streamFilters ? 'filter' : 'rule'}
            </Button>
          </span>
        </Tooltip>
      </Group>
      {!streamFilters && rules.some(isRetiredImportRule) && (
        <Alert color="yellow" variant="light" icon={<Info size={16} />} p="xs">
          <Text size="xs">
            Rules using removed import results are paused. Choose Enabled,
            Disabled or Ignore and enable the rule to use it again. Saved
            category selections have not been changed.
          </Text>
        </Alert>
      )}
      {!rules.length && !busy && !error && (
        <Text size="sm" c="dimmed">
          {streamFilters ? 'No stream filters' : 'No import rules'}
        </Text>
      )}
      {rules.length > 0 && (
        <ScrollArea>
          <DndContext
            sensors={sensors}
            collisionDetection={closestCenter}
            modifiers={[restrictToVerticalAxis]}
            onDragEnd={reorder}
          >
            <SortableContext
              items={rules.map((rule) => rule.id)}
              strategy={verticalListSortingStrategy}
            >
              <Table
                striped
                withTableBorder
                miw={vodRules ? 1100 : 760}
                className={classes.ruleTable}
              >
                <colgroup>
                  <col style={{ width: 40 }} />
                  <col style={{ width: 32 }} />
                  {streamFilters && <col style={{ width: 140 }} />}
                  <col />
                  <col style={{ width: 48 }} />
                  <col style={{ width: 116 }} />
                  {vodRules &&
                    VOD_METADATA_FIELDS.map((field) => (
                      <col
                        key={field}
                        style={{ width: field === 'video_features' ? 110 : 90 }}
                      />
                    ))}
                  <col style={{ width: 76 }} />
                  <col style={{ width: 106 }} />
                </colgroup>
                <TableThead>
                  <TableTr>
                    <TableTh
                      aria-label={`${streamFilters ? 'Filter' : 'Rule'} order`}
                    />
                    <TableTh
                      aria-label={`${streamFilters ? 'Filter' : 'Rule'} status`}
                    />
                    {streamFilters && <TableTh>Field</TableTh>}
                    <TableTh>
                      <Group gap={4} wrap="nowrap">
                        {streamFilters
                          ? 'Regular expression'
                          : 'Category name (regex)'}
                        <Popover
                          opened={regexHelpOpen}
                          onChange={setRegexHelpOpen}
                          width={320}
                          position="bottom"
                          withArrow
                          trapFocus
                          returnFocus
                        >
                          <Popover.Target>
                            <ActionIcon
                              aria-label="Regular expression help"
                              variant="subtle"
                              color="gray"
                              size="xs"
                              onClick={() =>
                                setRegexHelpOpen((opened) => !opened)
                              }
                              onKeyDown={(event) => {
                                if (event.key === 'Escape') {
                                  event.stopPropagation();
                                  setRegexHelpOpen(false);
                                }
                              }}
                            >
                              <CircleHelp size={14} />
                            </ActionIcon>
                          </Popover.Target>
                          <Popover.Dropdown>
                            <Stack gap="xs">
                              <Text size="xs">
                                <code>News</code> matches anywhere in a name.{' '}
                                <code>^News</code> matches its start;{' '}
                                <code>^News(?: HD)?$</code> matches only{' '}
                                <code>News</code> or <code>News HD</code>.
                              </Text>
                              <Text size="xs">
                                Escape literal characters such as{' '}
                                <code>{'\\+'}</code> and <code>{'\\.'}</code>.
                                Avoid empty alternatives such as{' '}
                                <code>News|</code>, which can match any name.
                              </Text>
                              <Text size="xs">
                                Try sample names on{' '}
                                <Anchor
                                  href="https://regex101.com/"
                                  target="_blank"
                                  rel="noopener noreferrer"
                                  size="xs"
                                >
                                  regex101 (Python)
                                </Anchor>
                                . Do not paste credentials or private URLs. The
                                app preview is authoritative; the backend uses
                                Python&apos;s regex engine.
                              </Text>
                            </Stack>
                          </Popover.Dropdown>
                        </Popover>
                      </Group>
                    </TableTh>
                    <TableTh className={classes.centeredCell}>Case</TableTh>
                    <TableTh>Result</TableTh>
                    {vodRules &&
                      VOD_METADATA_FIELDS.map((field) => (
                        <TableTh key={field}>
                          {VOD_METADATA_LABELS[field]}
                        </TableTh>
                      ))}
                    <TableTh className={classes.centeredCell}>Enabled</TableTh>
                    <TableTh className={classes.centeredCell}>Actions</TableTh>
                  </TableTr>
                </TableThead>
                <TableTbody>
                  {rules.map((rule) => (
                    <SortableRow
                      key={rule.id}
                      id={rule.id}
                      error={rowErrors[rule.id]}
                      warning={!!visibleCoverage.causes[rule.id]}
                      covered={visibleCoverage.coveredBy[rule.id] !== undefined}
                      dirty={dirtyIds.has(rule.id) || rule.isNew}
                      editing={activeRuleId === rule.id}
                      inactive={hasActiveEdit && activeRuleId !== rule.id}
                      disabled={busy || hasActiveEdit}
                      noun={noun}
                      marker={
                        <RuleMarker
                          error={rowErrors[rule.id]}
                          cause={visibleCoverage.causes[rule.id]}
                          coveredBy={
                            visibleCoverage.coveredBy[rule.id] !== undefined
                              ? coveredByMessage(rule.id)
                              : undefined
                          }
                        />
                      }
                    >
                      {streamFilters && (
                        <TableTd>
                          <Select
                            size="xs"
                            aria-label="Filter field"
                            allowDeselect={false}
                            value={rule.filter_type}
                            disabled={busy || activeRuleId !== rule.id}
                            data={[
                              { value: 'name', label: 'Stream name' },
                              { value: 'url', label: 'Stream URL' },
                              ...(rule.filter_type === 'group'
                                ? [
                                    {
                                      value: 'group',
                                      label: 'Group name (legacy)',
                                    },
                                  ]
                                : []),
                            ]}
                            onChange={(value) =>
                              update(rule.id, {
                                filter_type: value,
                              })
                            }
                          />
                        </TableTd>
                      )}
                      <TableTd>
                        {!streamFilters && isRetiredImportRule(rule) && (
                          <Tooltip
                            label={`Previous result: ${rule.action === 'ignore' ? 'Ignore category' : 'Keep import selection'}. This rule cannot run until you choose a supported result and enable it.`}
                            multiline
                            w={280}
                            withArrow
                            events={{ hover: true, focus: true, touch: true }}
                          >
                            <Badge
                              size="xs"
                              color="yellow"
                              variant="light"
                              mb={4}
                              tabIndex={0}
                            >
                              Paused · review result
                            </Badge>
                          </Tooltip>
                        )}
                        <Group gap={6} wrap="nowrap">
                          <div style={{ flex: 1, minWidth: 0 }}>
                            <TextInput
                              size="xs"
                              ref={
                                activeRuleId === rule.id
                                  ? activeInput
                                  : undefined
                              }
                              aria-label="Regular expression"
                              aria-description={
                                !streamFilters
                                  ? 'Matches category names only.'
                                  : undefined
                              }
                              sensitive={
                                streamFilters && rule.filter_type === 'url'
                              }
                              value={rule.regex_pattern}
                              onChange={(event) =>
                                update(rule.id, {
                                  regex_pattern: event.currentTarget.value,
                                })
                              }
                              error={!!rowErrors[rule.id]}
                              disabled={busy || activeRuleId !== rule.id}
                            />
                          </div>
                          <Tooltip
                            label={matchLabel(rule)}
                            events={{ hover: true, focus: true, touch: true }}
                            withArrow
                          >
                            <Badge
                              size="sm"
                              variant="light"
                              color="gray"
                              w={matchCountWidth}
                              style={{
                                flexShrink: 0,
                                fontVariantNumeric: 'tabular-nums',
                              }}
                              tabIndex={0}
                              aria-label={matchLabel(rule)}
                            >
                              {matchCount(rule)?.toLocaleString() ?? '—'}
                            </Badge>
                          </Tooltip>
                        </Group>
                      </TableTd>
                      <TableTd className={classes.centeredCell}>
                        <Checkbox
                          className={classes.centeredCheckbox}
                          aria-label="Case sensitive"
                          disabled={busy || activeRuleId !== rule.id}
                          checked={
                            streamFilters
                              ? rule.custom_properties?.case_sensitive !== false
                              : rule.case_sensitive
                          }
                          onChange={(event) =>
                            update(
                              rule.id,
                              streamFilters
                                ? {
                                    custom_properties: {
                                      ...(rule.custom_properties || {}),
                                      case_sensitive:
                                        event.currentTarget.checked,
                                    },
                                  }
                                : {
                                    case_sensitive: event.currentTarget.checked,
                                  }
                            )
                          }
                        />
                      </TableTd>
                      <TableTd>
                        <Select
                          size="xs"
                          aria-label="Rule result"
                          allowDeselect={false}
                          disabled={busy || activeRuleId !== rule.id}
                          value={
                            streamFilters
                              ? rule.exclude
                                ? 'exclude'
                                : 'include'
                              : isRetiredImportRule(rule)
                                ? null
                                : rule.action
                          }
                          placeholder="Choose import result"
                          comboboxProps={{ width: 128 }}
                          styles={{ option: { whiteSpace: 'nowrap' } }}
                          data={
                            streamFilters
                              ? [
                                  { value: 'exclude', label: 'Exclude' },
                                  { value: 'include', label: 'Include' },
                                ]
                              : [
                                  { value: 'enable', label: 'Enabled' },
                                  {
                                    value: 'disable',
                                    label: 'Disabled',
                                  },
                                  { value: 'ignore', label: 'Ignore' },
                                ]
                          }
                          onChange={(value) =>
                            update(
                              rule.id,
                              streamFilters
                                ? { exclude: value === 'exclude' }
                                : {
                                    action: value,
                                    ...(isRetiredImportRule(rule)
                                      ? { enabled: false }
                                      : {}),
                                  }
                            )
                          }
                        />
                      </TableTd>
                      {vodRules && (
                        <TableTd colSpan={4} className={classes.metadataCell}>
                          <div
                            className={classes.metadataFields}
                            role="group"
                            aria-label="Rule metadata"
                          >
                            {VOD_METADATA_FIELDS.map((field) => (
                              <div
                                key={field}
                                role="group"
                                aria-label={VOD_METADATA_LABELS[field]}
                              >
                                <VODMetadataCell
                                  values={rule.metadata_defaults || {}}
                                  field={field}
                                  emptyLabel={
                                    Object.hasOwn(
                                      rule.metadata_defaults || {},
                                      field
                                    )
                                      ? 'None'
                                      : '—'
                                  }
                                  title={
                                    Object.hasOwn(
                                      rule.metadata_defaults || {},
                                      field
                                    )
                                      ? undefined
                                      : 'Not set by this rule'
                                  }
                                />
                              </div>
                            ))}
                          </div>
                          <UnstyledButton
                            className={classes.metadataOverlay}
                            aria-label="Configure rule metadata"
                            title={
                              metadataSummary(rule.metadata_defaults || {}) ||
                              'Configure metadata defaults'
                            }
                            disabled={
                              busy ||
                              activeRuleId !== rule.id ||
                              isRetiredImportRule(rule)
                            }
                            onClick={() => setMetadataTarget(rule)}
                          >
                            <Settings size={20} aria-hidden="true" />
                          </UnstyledButton>
                        </TableTd>
                      )}
                      <TableTd className={classes.centeredCell}>
                        <Tooltip
                          label={
                            isRuleEnabled(rule, streamFilters)
                              ? `Disable ${noun}`
                              : `Enable ${noun}`
                          }
                        >
                          <span className={classes.centeredCheckbox}>
                            <Switch
                              aria-label={
                                streamFilters
                                  ? 'Filter enabled'
                                  : 'Rule enabled'
                              }
                              disabled={
                                busy ||
                                activeRuleId !== rule.id ||
                                (!streamFilters && isRetiredImportRule(rule))
                              }
                              checked={isRuleEnabled(rule, streamFilters)}
                              styles={{
                                track: isRuleEnabled(rule, streamFilters)
                                  ? { '--switch-bg': 'var(--switch-color)' }
                                  : undefined,
                                thumb: {
                                  '--switch-thumb-bg':
                                    'var(--mantine-color-white)',
                                },
                              }}
                              onChange={(event) =>
                                update(rule.id, {
                                  enabled: event.currentTarget.checked,
                                })
                              }
                            />
                          </span>
                        </Tooltip>
                      </TableTd>
                      <TableTd className={classes.centeredCell}>
                        <Group gap={4} wrap="nowrap" justify="center">
                          {activeRuleId === rule.id ? (
                            <Tooltip label={`Save ${noun}`}>
                              <ActionIcon
                                aria-label={`Save ${noun}`}
                                variant="subtle"
                                disabled={busy || !dirtyIds.has(rule.id)}
                                onClick={() => saveRow(rule)}
                              >
                                <Save size={16} />
                              </ActionIcon>
                            </Tooltip>
                          ) : (
                            <Tooltip label={`Edit ${noun}`}>
                              <ActionIcon
                                aria-label={`Edit ${noun}`}
                                color="yellow"
                                variant="subtle"
                                disabled={busy || hasActiveEdit}
                                onClick={() => startEditing(rule)}
                              >
                                <SquarePen size={16} />
                              </ActionIcon>
                            </Tooltip>
                          )}
                          <Tooltip
                            label={previewHint(rule)}
                            events={{ hover: true, focus: true, touch: true }}
                            withArrow
                          >
                            <span
                              style={{ display: 'inline-flex' }}
                              tabIndex={
                                previewUnavailableHint(rule) ? 0 : undefined
                              }
                              aria-label={
                                previewUnavailableHint(rule)
                                  ? previewHint(rule)
                                  : undefined
                              }
                            >
                              <ActionIcon
                                aria-label={`Preview ${noun}`}
                                variant="subtle"
                                disabled={
                                  busy || !!previewUnavailableHint(rule)
                                }
                                onClick={() => openPreview(rule)}
                              >
                                <Eye size={16} />
                              </ActionIcon>
                            </span>
                          </Tooltip>
                          {activeRuleId === rule.id ? (
                            <Tooltip label={`Discard ${noun} changes`}>
                              <ActionIcon
                                aria-label={`Discard ${noun} changes`}
                                color="gray"
                                variant="subtle"
                                disabled={busy}
                                onClick={() => discardRow(rule)}
                              >
                                <X size={16} />
                              </ActionIcon>
                            </Tooltip>
                          ) : (
                            <Tooltip label={`Delete ${noun}`}>
                              <ActionIcon
                                aria-label={`Delete ${noun}`}
                                color="red"
                                variant="subtle"
                                disabled={busy || hasActiveEdit}
                                onClick={() => setDeleteTarget(rule)}
                              >
                                <Trash2 size={16} />
                              </ActionIcon>
                            </Tooltip>
                          )}
                        </Group>
                      </TableTd>
                    </SortableRow>
                  ))}
                </TableTbody>
              </Table>
            </SortableContext>
          </DndContext>
        </ScrollArea>
      )}
      <StackedModal
        stackId={`m3u-rule-metadata-${scope}`}
        opened={!!metadataTarget}
        onClose={() => setMetadataTarget(null)}
        title="Rule metadata defaults"
        closeButtonProps={{ 'aria-label': 'Close rule metadata defaults' }}
        size="md"
      >
        {metadataTarget && (
          <VODCategoryMetadataEditor
            ruleMode
            value={metadataTarget.metadata_defaults || {}}
            languages={MEDIA_LANGUAGE_OPTIONS}
            resolutions={VOD_RESOLUTIONS}
            pickerStackId={`m3u-rule-metadata-picker-${scope}`}
            onApply={(metadata_defaults) => {
              if (
                JSON.stringify(metadata_defaults) !==
                JSON.stringify(metadataTarget.metadata_defaults || {})
              )
                update(metadataTarget.id, { metadata_defaults });
              setMetadataTarget(null);
            }}
          />
        )}
      </StackedModal>
      <StackedModal
        stackId={`m3u-rule-preview-${streamFilters ? 'streams' : scope}`}
        keepVisibleInStack
        opened={!!previewTarget}
        onClose={requestClosePreview}
        title={
          streamFilters ? 'Stream filters preview' : 'Import rules preview'
        }
        size="min(1100px, 94vw)"
        closeButtonProps={{ 'aria-label': 'Close preview', disabled: busy }}
        closeOnEscape={!busy && !confirmApply && !discardPreview}
        closeOnClickOutside={!busy && !confirmApply && !discardPreview}
        trapFocus={!confirmApply && !discardPreview}
        classNames={{
          content: editorClasses.content,
          body: editorClasses.body,
          header: editorClasses.header,
        }}
      >
        <Stack className={editorClasses.previewStack} gap="sm">
          <Group
            gap="sm"
            align="flex-end"
            wrap="nowrap"
            style={{ flexShrink: 0 }}
          >
            <TextInput
              label={
                streamFilters ? 'Regular expression' : 'Category name (regex)'
              }
              aria-label="Preview regular expression"
              ref={previewInput}
              readOnly={!previewEditing}
              disabled={busy || !previewEditing}
              sensitive={streamFilters && previewTarget?.filter_type === 'url'}
              value={previewTarget?.regex_pattern || ''}
              onChange={(event) =>
                updatePreview({ regex_pattern: event.currentTarget.value })
              }
              onKeyDown={(event) => {
                if (event.key === 'Enter') {
                  event.preventDefault();
                  if (!testUnavailableHint && !previewBusy) {
                    setPage(1);
                    loadPreview(previewDraft, previewTarget, 1, pageSize);
                  }
                }
              }}
              style={{ flex: 1, minWidth: 0 }}
            />
            <Tooltip
              label={
                canEditPreview
                  ? 'Edit regular expression'
                  : `Save or discard the current ${noun} before editing another.`
              }
            >
              <ActionIcon
                aria-label="Edit preview expression"
                size="input-sm"
                variant="subtle"
                disabled={busy || previewEditing || !canEditPreview}
                onClick={() => setPreviewEditing(true)}
                data-autofocus
              >
                <SquarePen size={18} />
              </ActionIcon>
            </Tooltip>
            <Checkbox
              label="Case"
              aria-label="Preview case sensitive"
              disabled={busy || !previewEditing}
              checked={
                streamFilters
                  ? previewTarget?.custom_properties?.case_sensitive !== false
                  : !!previewTarget?.case_sensitive
              }
              mb={8}
              onChange={(event) =>
                updatePreview(
                  streamFilters
                    ? {
                        custom_properties: {
                          ...previewTarget.custom_properties,
                          case_sensitive: event.currentTarget.checked,
                        },
                      }
                    : { case_sensitive: event.currentTarget.checked }
                )
              }
            />
            <Tooltip
              label={testUnavailableHint}
              disabled={!testUnavailableHint}
              events={{ hover: true, focus: true, touch: true }}
            >
              <span
                tabIndex={testUnavailableHint ? 0 : undefined}
                aria-label={testUnavailableHint || undefined}
              >
                <Button
                  loading={previewBusy}
                  variant="default"
                  disabled={busy || !!testUnavailableHint}
                  onClick={() => {
                    setPage(1);
                    loadPreview(previewDraft, previewTarget, 1, pageSize);
                  }}
                >
                  Try
                </Button>
              </span>
            </Tooltip>
            <Button
              onClick={savePreview}
              loading={busy}
              disabled={
                !canEditPreview ||
                previewBusy ||
                (!previewHasChanges &&
                  !previewTarget?.isNew &&
                  !dirtyIds.has(previewTarget?.id))
              }
            >
              Save
            </Button>
          </Group>
          {preview && !previewError && (
            <Tooltip
              label={
                previewGroupIds
                  ? 'Cached data for the selected categories. Nothing has been imported.'
                  : preview.last_completed_refresh
                    ? `Last completed ${streamFilters || scope === 'live' ? streamLabel : 'VOD'} refresh: ${refreshedAt}`
                    : 'Available imported data; no completed refresh recorded.'
              }
            >
              <Text
                size="xs"
                c="dimmed"
                tabIndex={0}
                style={{ alignSelf: 'flex-start' }}
              >
                {previewGroupIds
                  ? 'Category preview'
                  : preview.last_completed_refresh
                    ? `Data: ${refreshedAt}`
                    : 'Imported data'}
              </Text>
            </Tooltip>
          )}
          {preview &&
            !previewError &&
            ((streamFilters && !previewGroupIds && !preview.catalog_complete) ||
              (!previewGroupIds && preview.refresh_in_progress)) && (
              <Alert
                color="yellow"
                icon={<Info size={16} />}
                p="xs"
                style={{ flexShrink: 0 }}
              >
                {streamFilters &&
                  !previewGroupIds &&
                  !preview.catalog_complete &&
                  'Only imported streams are available; excluded streams are not included.'}
                {!previewGroupIds &&
                  preview.refresh_in_progress &&
                  ' A refresh is running; this preview uses the previous completed snapshot.'}
              </Alert>
            )}
          {previewWarning && (
            <Alert
              color="yellow"
              icon={<TriangleAlert size={16} />}
              p="xs"
              style={{ flexShrink: 0 }}
            >
              {previewWarning}
            </Alert>
          )}
          <Text
            fw={600}
            c={previewError ? 'red' : undefined}
            role={previewError ? 'alert' : 'status'}
            aria-live="polite"
            style={{ flexShrink: 0 }}
          >
            {previewBusy
              ? 'Evaluating…'
              : previewError
                ? previewError
                : !previewChecked
                  ? 'Not tested'
                  : `${preview.count || 0} matching ${streamFilters ? 'streams' : 'categories'} from ${preview.inventory_count ?? 0} ${streamFilters ? 'streams' : 'categories'}`}
          </Text>
          {preview && !previewError && (
            <>
              {vodRules &&
                Object.keys(previewTarget?.metadata_defaults || {}).length >
                  0 && (
                  <Group
                    gap="sm"
                    align="flex-start"
                    role="group"
                    aria-label="Rule metadata defaults"
                    style={{ flexShrink: 0 }}
                  >
                    {VOD_METADATA_FIELDS.filter((field) =>
                      Object.hasOwn(previewTarget.metadata_defaults, field)
                    ).map((field) => (
                      <Stack
                        key={field}
                        gap={4}
                        style={{ minWidth: 80, maxWidth: 240 }}
                      >
                        <Text size="xs" fw={600}>
                          {VOD_METADATA_LABELS[field]}
                        </Text>
                        <VODMetadataCell
                          values={previewTarget.metadata_defaults}
                          field={field}
                          emptyLabel="None"
                        />
                      </Stack>
                    ))}
                  </Group>
                )}
              <div className={editorClasses.categoryTableFrame}>
                <ScrollArea h="100%" type="auto">
                  <Table
                    striped
                    stickyHeader
                    stickyHeaderOffset={0}
                    className={editorClasses.categoryTable}
                  >
                    <TableThead>
                      <TableTr>
                        <TableTh w={streamFilters ? '55%' : '50%'}>
                          Name
                        </TableTh>
                        {streamFilters ? (
                          <TableTh>Group</TableTh>
                        ) : (
                          <TableTh>Current</TableTh>
                        )}
                        <TableTh>Result</TableTh>
                        {!streamFilters && <TableTh>Items</TableTh>}
                      </TableTr>
                    </TableThead>
                    <TableTbody>
                      {previewRows.map((row, index) => (
                        <TableTr key={row.relation_id || index}>
                          <TableTd>{row.name}</TableTd>
                          <TableTd>
                            {streamFilters
                              ? row.group
                              : row.currently_ignored
                                ? 'Ignored'
                                : row.currently_enabled
                                  ? 'Enabled'
                                  : 'Disabled'}
                          </TableTd>
                          <TableTd>
                            {streamFilters
                              ? row.result
                              : row.would_ignore
                                ? 'Ignored'
                                : row.would_enable == null
                                  ? 'Unchanged'
                                  : row.would_enable
                                    ? 'Enabled'
                                    : 'Disabled'}
                          </TableTd>
                          {!streamFilters && (
                            <TableTd>{row.item_count}</TableTd>
                          )}
                        </TableTr>
                      ))}
                    </TableTbody>
                  </Table>
                </ScrollArea>
              </div>
            </>
          )}
          {(!preview || previewError) && <div style={{ flex: 1 }} />}
          <div className={editorClasses.categoryFooter}>
            {preview && !previewError && (
              <div className={editorClasses.paginationSlot}>
                <ListPagination
                  page={page}
                  pageSize={pageSize}
                  total={preview?.count || 0}
                  onPageChange={(value) => {
                    setPage(value);
                    loadPreview(previewDraft, previewTarget, value, pageSize);
                  }}
                  onPageSizeChange={(value) => {
                    setPageSize(value);
                    setPage(1);
                    loadPreview(previewDraft, previewTarget, 1, value);
                  }}
                />
              </div>
            )}
            <div
              className={editorClasses.categoryFooterActions}
              style={{ gridColumn: 3 }}
            >
              {!streamFilters &&
                !hasActiveEdit &&
                !hasUnsavedChanges &&
                !previewHasChanges && (
                  <Button
                    onClick={() => setConfirmApply(true)}
                    loading={previewBusy}
                    disabled={
                      busy ||
                      !previewChecked ||
                      !preview?.count ||
                      !isRuleEnabled(previewTarget || {}, streamFilters)
                    }
                  >
                    Apply to existing
                  </Button>
                )}
            </div>
          </div>
        </Stack>
      </StackedModal>
      <ConfirmationDialog
        opened={discardPreview}
        onClose={() => setDiscardPreview(false)}
        onConfirm={closePreview}
        title="Unsaved changes"
        message="Discard unsaved expression changes?"
        confirmLabel="Discard"
        cancelLabel="Keep editing"
      />
      <ConfirmationDialog
        opened={confirmApply}
        onClose={() => !previewBusy && setConfirmApply(false)}
        onConfirm={apply}
        loading={previewBusy}
        title="Apply import rule"
        message={`Apply this rule to all ${preview?.count || 0} matching categories?`}
        confirmLabel="Apply"
        cancelLabel="Cancel"
        confirmColor={
          !streamFilters && previewTarget?.action !== 'enable' ? 'red' : 'blue'
        }
      />
      <ConfirmationDialog
        opened={!!deleteTarget}
        onClose={() => setDeleteTarget(null)}
        onConfirm={remove}
        loading={busy}
        title={`Delete ${streamFilters ? 'stream filter' : 'import rule'}`}
        message="Delete this rule? Existing groups and streams will not be deleted."
        confirmLabel="Delete"
        zIndex={300}
      />
    </Stack>
  );
};

export default M3URulesEditor;
