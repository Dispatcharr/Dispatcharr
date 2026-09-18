import React, { useEffect, useMemo, useState } from 'react';
import {
  ActionIcon,
  Alert,
  Badge,
  Box,
  Button,
  Group,
  Modal,
  Paper,
  Pagination,
  Popover,
  PopoverDropdown,
  PopoverTarget,
  Progress,
  ScrollArea,
  SegmentedControl,
  Select,
  SimpleGrid,
  Stack,
  Switch,
  Table,
  TableTbody,
  TableTd,
  TableTh,
  TableThead,
  TableTr,
  Tabs,
  TabsList,
  TabsPanel,
  TabsTab,
  Text,
  TextInput,
  Title,
  Tooltip,
} from '@mantine/core';
import { Eye, Filter, Plus, RefreshCw, Save, Trash2 } from 'lucide-react';
import API from '../api';
import useVODStore from '../store/useVODStore';
import { showNotification } from '../utils/notificationUtils';
import { normalizeLanguageCodes } from '../utils/languageCodes.js';
import {
  CONTAINER_EXTENSION_OPTIONS,
  RESOLUTION_VALUES,
} from '../utils/vodMetadataOptions.js';
import { LanguageSelect } from './LanguagePicker.jsx';
import VideoFeaturePicker from './VideoFeaturePicker.jsx';
import VODCategoryFilter from './forms/VODCategoryFilter.jsx';
import { resolveProfileCategoryRows } from './forms/VODProfileCategoryRules.utils.js';
import VODFailoverRanking from './VODFailoverRanking.jsx';
import VODSourceRules from './VODSourceRules.jsx';
import VODEditionRules from './VODEditionRules.jsx';
import VODModal from './VODModal.jsx';
import SeriesModal from './SeriesModal.jsx';
import {
  DEFAULT_VOD_FAILOVER_RANKING,
  normalizeVODFailoverRanking,
} from '../utils/vodFailoverRanking.js';

const EMPTY_PROFILE = {
  name: '',
  export_mode: 'compact',
  is_default: false,
  is_active: true,
  hard_constraints: {
    source_rules: [],
    content_default_action: 'exclude',
    category_import_rules: [],
    disabled_ranking: [],
    audio_language_order: [],
    subtitle_language_order: [],
  },
  ranking: DEFAULT_VOD_FAILOVER_RANKING,
  provider_order: [],
  edition_rules: [],
  naming_mode: 'template',
  name_template: '{title} ({year}) {edition}',
  metadata_source: 'canonical',
  canonical_title_source: 'primary',
  category_rules: [],
};

const metadataText = (metadata, field) => {
  const value = metadata?.[field];
  if (Array.isArray(value)) return value.length ? value.join(', ') : '—';
  return value || '—';
};

const hasOwn = (object, key) =>
  Object.prototype.hasOwnProperty.call(object || {}, key);

const outputTitleFields = (template) => {
  const fields = new Set();
  for (const match of String(template || '').matchAll(
    /{([a-z_]+)(?:![^}:]+)?(?::[^}]+)?}/gi
  )) {
    fields.add(match[1].toLowerCase());
  }
  return fields;
};

const defaultOutputTemplate = (mode) =>
  mode === 'variants' ? '{title}' : '{title} ({year}) {edition}';

const normalizedOutputSettings = (profile) => {
  const mode = profile.export_mode || 'compact';
  const originalTemplate = String(profile.name_template || '').trim();
  const providerTemplate = originalTemplate.includes('{source}');
  const canonicalTemplate =
    originalTemplate.includes('{canonical}') ||
    originalTemplate.includes('{title}');
  let titleSource =
    mode === 'variants' && profile.canonical_title_source === 'provider'
      ? 'provider'
      : profile.canonical_title_source === 'secondary'
        ? 'secondary'
        : 'primary';
  let template = originalTemplate;

  if (
    mode === 'variants' &&
    (profile.naming_mode === 'provider' ||
      (profile.naming_mode === 'mode_default' && !template))
  ) {
    titleSource = 'provider';
    template = '{title}';
  } else if (profile.naming_mode === 'canonical') {
    template = defaultOutputTemplate(mode);
  } else if (profile.naming_mode !== 'template' || !template) {
    template = defaultOutputTemplate(mode);
  } else {
    if (mode === 'variants' && providerTemplate && !canonicalTemplate) {
      titleSource = 'provider';
      template = template.replaceAll('{source}', '{title}');
    }
    template = template
      .replaceAll(
        '{canonical}',
        template.includes('{year}') ? '{title}' : '{title} ({year})'
      )
      .replaceAll('{edition_name}', '{edition}');
  }

  if (mode === 'compact' && titleSource === 'provider') titleSource = 'primary';
  return { template, titleSource };
};

const formatDuration = (seconds) => {
  const rounded = Math.max(Math.round(seconds || 0), 0);
  if (rounded < 60) return `${rounded}s`;
  if (rounded >= 3600) {
    const hours = Math.floor(rounded / 3600);
    const minutes = Math.floor((rounded % 3600) / 60);
    return `${hours}h ${minutes}m`;
  }
  const minutes = Math.floor(rounded / 60);
  const remainder = rounded % 60;
  return `${minutes}m ${remainder}s`;
};

const outputModeLabel = (mode) =>
  mode === 'compact'
    ? 'Compact'
    : mode === 'variants'
      ? 'Variants'
      : 'Unknown mode';

const catalogModeLabel = (mode) =>
  mode === 'compact' ? 'Compact' : mode === 'variants' ? 'All' : 'Unknown';

const SOURCES_TAB_HELP =
  'Only categories enabled in the M3U account are available here. Manual Allow/Block choices override ordered import rules. Rule edits take effect after Save and apply; Save profile stores the complete profile and starts one rebuild. New provider categories are evaluated after their VOD refresh completes.';
const CONTENT_RULES_TAB_HELP =
  'Order matters and the first matching filter decides. Filters can combine effective source metadata (including manual corrections) with reusable canonical metadata. Unmatched content follows the selected default; external IDs are intentionally not filter fields.';
const EDITIONS_TAB_HELP =
  "First match wins. Compact creates one client entry per canonical title and suffix. Every split stays in the title's output category, and failover stays inside the matching suffix. Unmatched sources use the canonical title without a suffix.";
const PREVIEW_PAGE_SIZES = [25, 50, 100, 200];
const PREVIEW_PAGE_SIZE_STORAGE_KEY = 'vodOutputProfilePreviewPageSize';

const initialPreviewPageSize = () => {
  const stored = Number(
    window.localStorage.getItem(PREVIEW_PAGE_SIZE_STORAGE_KEY)
  );
  return PREVIEW_PAGE_SIZES.includes(stored) ? stored : 50;
};

const buildPhaseDescription = (progress) => {
  const descriptions = {
    1: 'Movies: applying profile rules and ranking eligible sources',
    2: 'Movies: writing the selected output catalog in database batches',
    3: 'Series: applying profile rules and ranking eligible sources',
    4: 'Series: writing the selected output catalog in database batches',
    5: 'Activating the completed catalog for clients',
  };
  return descriptions[Number(progress?.stage_index)] || progress?.phase || '';
};

const profilePayload = (profile) => ({
  name: profile.name.trim(),
  export_mode: profile.export_mode,
  is_default: profile.is_default,
  is_active: profile.is_active,
  hard_constraints: {
    content_default_action:
      profile.hard_constraints?.content_default_action === 'exclude'
        ? 'exclude'
        : 'include',
    source_rules: (profile.hard_constraints?.source_rules || []).map((rule) => {
      const normalizedRule = { ...rule };
      for (const field of [
        'min_year',
        'max_year',
        'min_rating',
        'max_rating',
      ]) {
        delete normalizedRule[field];
      }
      return {
        ...normalizedRule,
        required_audio_languages: normalizeLanguageCodes(
          rule.required_audio_languages || []
        ),
        required_subtitle_languages: normalizeLanguageCodes(
          rule.required_subtitle_languages || []
        ),
        required_video_features: rule.required_video_features || [],
      };
    }),
    ...(hasOwn(profile.hard_constraints, 'category_import_rules')
      ? {
          category_import_rules: (
            profile.hard_constraints.category_import_rules || []
          ).map((rule, index) => ({
            id: rule.id,
            scope: rule.scope,
            m3u_account_id: rule.m3u_account_id
              ? Number(rule.m3u_account_id)
              : null,
            match_field: 'group_name',
            regex_pattern: rule.regex_pattern || '',
            action: rule.action === 'enable' ? 'enable' : 'disable',
            case_sensitive: Boolean(rule.case_sensitive),
            enabled: rule.enabled !== false,
            order: index,
          })),
        }
      : {}),
    disabled_ranking: profile.hard_constraints?.disabled_ranking || [],
    audio_language_order: normalizeLanguageCodes(
      profile.hard_constraints?.audio_language_order || []
    ),
    subtitle_language_order: normalizeLanguageCodes(
      profile.hard_constraints?.subtitle_language_order || []
    ),
  },
  ranking: normalizeVODFailoverRanking(
    profile.ranking || DEFAULT_VOD_FAILOVER_RANKING
  ),
  provider_order: [...new Set(profile.provider_order || [])]
    .map(Number)
    .filter((providerId) => Number.isInteger(providerId) && providerId > 0),
  edition_rules: (profile.edition_rules || []).map((rule) => ({
    id: rule.id,
    name: rule.title_suffix.trim(),
    title_suffix: rule.title_suffix.trim(),
    enabled: rule.enabled !== false,
    min_resolution: Number(rule.min_resolution || 0),
    max_resolution: Number(rule.max_resolution || 0),
    required_audio_languages: normalizeLanguageCodes(
      rule.required_audio_languages || []
    ),
    required_subtitle_languages: normalizeLanguageCodes(
      rule.required_subtitle_languages || []
    ),
    required_video_features: rule.required_video_features || [],
  })),
  naming_mode: 'template',
  name_template:
    String(profile.name_template || '').trim() ||
    defaultOutputTemplate(profile.export_mode),
  metadata_source: profile.metadata_source || 'provider',
  canonical_title_source:
    profile.export_mode === 'variants' &&
    profile.canonical_title_source === 'provider'
      ? 'provider'
      : profile.canonical_title_source === 'secondary'
        ? 'secondary'
        : 'primary',
  category_rules: (profile.category_rules || [])
    .map((rule) => ({
      category_relation: Number(rule.category_relation),
      enabled: rule.enabled !== false,
      priority: Number(rule.priority || 0),
    }))
    .filter((rule) => Number.isInteger(rule.category_relation))
    .sort((left, right) => left.category_relation - right.category_relation),
});

const canonicalizeObject = (value) => {
  if (Array.isArray(value)) return value.map(canonicalizeObject);
  if (!value || typeof value !== 'object') return value;
  return Object.fromEntries(
    Object.entries(value)
      .filter(([, item]) => item !== undefined)
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([key, item]) => [key, canonicalizeObject(item)])
  );
};

const profileDraftSignature = (profile) =>
  JSON.stringify(canonicalizeObject(profilePayload(profile)));

const VODOutputProfilesModal = ({ opened, onClose, embedded = false }) => {
  const categories = useVODStore((state) => state.categories);
  const profiles = useVODStore((state) => state.accessPolicies);
  const fetchCategories = useVODStore((state) => state.fetchCategories);
  const fetchProfiles = useVODStore((state) => state.fetchAccessPolicies);
  const upsertAccessPolicy = useVODStore((state) => state.upsertAccessPolicy);
  const removeAccessPolicy = useVODStore((state) => state.removeAccessPolicy);
  const [profileId, setProfileId] = useState('');
  const [creating, setCreating] = useState(false);
  const [draft, setDraft] = useState(EMPTY_PROFILE);
  const [savedDraftSignature, setSavedDraftSignature] = useState('');
  const [candidateTarget, setCandidateTarget] = useState(null);
  const [candidateData, setCandidateData] = useState(null);
  const [candidateLoading, setCandidateLoading] = useState(false);
  const [candidateError, setCandidateError] = useState('');
  const [saving, setSaving] = useState(false);
  const [rebuilding, setRebuilding] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [activeTab, setActiveTab] = useState('settings');
  const [preview, setPreview] = useState({ count: 0, results: [] });
  const [previewLoading, setPreviewLoading] = useState(false);
  const [page, setPage] = useState(1);
  const [previewPageSize, setPreviewPageSize] = useState(
    initialPreviewPageSize
  );
  const [filters, setFilters] = useState({
    type: 'movie',
    search: '',
    m3u_account: '',
    category: '',
    audio_language: '',
    subtitle_language: '',
    resolution: '',
    container_extension: '',
    video_feature: '',
    metadata_status: '',
    genre: '',
    anime_mode: '',
    adult_mode: '',
  });

  const selectedProfile = profiles.find(
    (profile) => String(profile.id) === String(profileId)
  );
  const selectedProfileId = selectedProfile?.id;
  const selectedSelectionStatus = selectedProfile?.selection_status;
  const defaultReplacementAvailable = profiles.some(
    (profile) =>
      String(profile.id) !== String(selectedProfileId) && profile.is_active
  );
  const canDeleteProfile = Boolean(
    selectedProfile &&
    (!selectedProfile.is_default || defaultReplacementAvailable)
  );
  const deleteProfileHint = selectedProfile?.is_default
    ? defaultReplacementAvailable
      ? 'The next active profile becomes the default automatically.'
      : 'Create or activate another profile before deleting the active default.'
    : 'Delete this VOD output profile.';
  const selectionAvailable =
    selectedProfile?.selection_available ??
    selectedProfile?.selection_current ??
    false;

  const resetDraft = (profile = null) => {
    const source = profile || EMPTY_PROFILE;
    const sourceRules = source.hard_constraints?.source_rules || [];
    const sourceConstraints = source.hard_constraints || {};
    const outputSettings = normalizedOutputSettings(source);
    const nextDraft = {
      ...EMPTY_PROFILE,
      ...source,
      hard_constraints: {
        content_default_action: hasOwn(
          source.hard_constraints,
          'content_default_action'
        )
          ? source.hard_constraints.content_default_action === 'exclude'
            ? 'exclude'
            : 'include'
          : profile
            ? 'include'
            : 'exclude',
        source_rules: sourceRules,
        disabled_ranking: sourceConstraints.disabled_ranking || [],
        audio_language_order: normalizeLanguageCodes(
          sourceConstraints.audio_language_order || []
        ),
        subtitle_language_order: normalizeLanguageCodes(
          sourceConstraints.subtitle_language_order || []
        ),
        ...(hasOwn(sourceConstraints, 'category_import_rules')
          ? {
              category_import_rules:
                sourceConstraints.category_import_rules || [],
            }
          : {}),
      },
      ranking: normalizeVODFailoverRanking(
        source.ranking || EMPTY_PROFILE.ranking
      ),
      provider_order: source.provider_order || [],
      edition_rules: source.edition_rules || [],
      naming_mode: 'template',
      name_template: outputSettings.template,
      metadata_source: source.metadata_source || 'provider',
      canonical_title_source: outputSettings.titleSource,
      category_rules: source.category_rules || [],
    };
    setDraft(nextDraft);
    setSavedDraftSignature(profileDraftSignature(nextDraft));
  };

  useEffect(() => {
    if (!opened) return;
    Promise.all([fetchCategories(), fetchProfiles()]);
  }, [fetchCategories, fetchProfiles, opened]);

  useEffect(() => {
    if (opened) return;
    setCreating(false);
    setProfileId('');
    setActiveTab('settings');
    setCandidateTarget(null);
  }, [opened]);

  useEffect(() => {
    if (!opened || creating || profileId || !profiles.length) return;
    const first = profiles.find((profile) => profile.is_default) || profiles[0];
    setProfileId(String(first.id));
  }, [creating, opened, profileId, profiles]);

  useEffect(() => {
    if (creating || !selectedProfile) return;
    resetDraft(selectedProfile);
    // Polling replaces profile objects in the store. Only switching profiles
    // may reset a local, possibly unsaved draft.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [creating, selectedProfile?.id]);

  useEffect(() => {
    if (!opened || !selectedProfileId) return;
    if (!['pending', 'building'].includes(selectedSelectionStatus)) {
      return;
    }
    let cancelled = false;
    let timer;
    const poll = async () => {
      await fetchProfiles();
      if (!cancelled) timer = window.setTimeout(poll, 2000);
    };
    timer = window.setTimeout(poll, 2000);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [fetchProfiles, opened, selectedProfileId, selectedSelectionStatus]);

  useEffect(() => {
    if (
      !candidateTarget ||
      !selectedProfile?.id ||
      candidateTarget.profile_context === false
    ) {
      setCandidateData(null);
      setCandidateLoading(false);
      setCandidateError('');
      return;
    }
    let cancelled = false;
    setCandidateData(null);
    setCandidateLoading(true);
    setCandidateError('');
    const previewMode =
      selectedProfile.selection_active_mode ||
      selectedProfile.selection_counts?.export_mode ||
      selectedProfile.export_mode;
    API.getVODAccessPolicyCandidates(selectedProfile.id, {
      type: candidateTarget.content_type || filters.type,
      canonical_id: candidateTarget.canonical_id,
      ...(candidateTarget.relation_id
        ? { current_relation_id: candidateTarget.relation_id }
        : {}),
      ...(previewMode === 'compact' && candidateTarget.edition_key
        ? { edition_key: candidateTarget.edition_key }
        : {}),
    })
      .then((response) => {
        if (!cancelled) setCandidateData(response);
      })
      .catch((error) => {
        if (!cancelled) {
          setCandidateError(
            error?.body?.detail ||
              error?.message ||
              'Could not load profile source information.'
          );
        }
      })
      .finally(() => {
        if (!cancelled) setCandidateLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [
    candidateTarget,
    filters.type,
    selectedProfile?.export_mode,
    selectedProfile?.id,
    selectedProfile?.selection_active_mode,
    selectedProfile?.selection_counts?.export_mode,
  ]);

  useEffect(() => {
    if (
      draft.export_mode === 'variants' &&
      ['editions', 'failover'].includes(activeTab)
    ) {
      setActiveTab('settings');
    }
  }, [activeTab, draft.export_mode]);

  const accountOptions = useMemo(
    () =>
      [
        ...new Map(
          Object.values(categories || {}).flatMap((category) =>
            (category.m3u_accounts || [])
              .filter((relation) => relation.enabled !== false)
              .map((relation) => [
                String(relation.m3u_account),
                relation.account_name,
              ])
          )
        ),
      ]
        .map(([value, label]) => ({ value, label }))
        .sort((left, right) => left.label.localeCompare(right.label)),
    [categories]
  );
  const movieCategoryStates = useMemo(
    () => resolveProfileCategoryRows(categories, draft, 'movie'),
    [categories, draft]
  );
  const seriesCategoryStates = useMemo(
    () => resolveProfileCategoryRows(categories, draft, 'series'),
    [categories, draft]
  );
  const allowedCategoryStates = useMemo(
    () =>
      [...movieCategoryStates, ...seriesCategoryStates].filter(
        (category) => category.enabled
      ),
    [movieCategoryStates, seriesCategoryStates]
  );
  const selectedCategoryIds = allowedCategoryStates.map((category) =>
    String(category.relation_id)
  );

  const updateProfileCategoryStates = (currentRows) => (updater) => {
    const nextRows =
      typeof updater === 'function' ? updater(currentRows) : updater;
    const previousById = new Map(
      currentRows.map((row) => [String(row.relation_id), row])
    );
    const changedById = new Map(
      (nextRows || [])
        .filter((row) => {
          const previous = previousById.get(String(row.relation_id));
          return previous && previous.enabled !== row.enabled;
        })
        .map((row) => [String(row.relation_id), row.enabled])
    );
    if (!changedById.size) return;
    setDraft((current) => {
      const existing = new Map(
        (current.category_rules || []).map((rule) => [
          String(rule.category_relation),
          rule,
        ])
      );
      changedById.forEach((enabled, relationId) => {
        existing.set(relationId, {
          category_relation: Number(relationId),
          enabled,
          priority: 0,
        });
      });
      return { ...current, category_rules: [...existing.values()] };
    });
  };

  const updateProfileCategoryRules = (scope, scopeRules) => {
    setDraft((current) => {
      const constraints = current.hard_constraints || {};
      const otherRules = (constraints.category_import_rules || []).filter(
        (rule) => rule.scope !== scope
      );
      return {
        ...current,
        hard_constraints: {
          ...constraints,
          category_import_rules: [...otherRules, ...scopeRules],
        },
      };
    });
  };

  const failoverAccountOptions = useMemo(() => {
    const allowedAccountIds = new Set(
      allowedCategoryStates.map((category) => String(category.accountId))
    );
    if (!allowedAccountIds.size) return accountOptions;
    return accountOptions.filter((option) =>
      allowedAccountIds.has(String(option.value))
    );
  }, [accountOptions, allowedCategoryStates]);
  const categoryOptions = useMemo(
    () =>
      Object.values(categories || {})
        .filter(
          (category) =>
            category.category_type === filters.type &&
            (category.m3u_accounts || []).some(
              (relation) =>
                relation.enabled !== false &&
                (!filters.m3u_account ||
                  String(relation.m3u_account) === filters.m3u_account)
            )
        )
        .map((category) => ({
          value: String(category.id),
          label: category.name,
        }))
        .sort((left, right) => left.label.localeCompare(right.label)),
    [categories, filters.m3u_account, filters.type]
  );

  const loadPreview = async () => {
    if (!selectionAvailable) {
      setPreview({ count: 0, results: [] });
      return;
    }
    setPreviewLoading(true);
    try {
      const previewMode =
        selectedProfile?.selection_active_mode ||
        selectedProfile?.selection_counts?.export_mode ||
        selectedProfile?.export_mode;
      const applicableFilters =
        previewMode === 'compact'
          ? {
              type: filters.type,
              search: filters.search,
              category: filters.category,
              metadata_status: filters.metadata_status,
              genre: filters.genre,
              anime_mode: filters.anime_mode,
              adult_mode: filters.adult_mode,
            }
          : filters;
      const params = Object.fromEntries(
        Object.entries({
          ...applicableFilters,
          page,
          page_size: previewPageSize,
        }).filter(([, value]) => value !== '')
      );
      setPreview(
        await API.getVODAccessPolicySelections(selectedProfile.id, params)
      );
    } catch {
      setPreview({ count: 0, results: [] });
    } finally {
      setPreviewLoading(false);
    }
  };

  useEffect(() => {
    if (!opened || activeTab !== 'preview') return;
    const timer = window.setTimeout(loadPreview, 250);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    activeTab,
    filters,
    opened,
    page,
    previewPageSize,
    selectionAvailable,
    selectedProfile?.id,
    selectedProfile?.selection_active_mode,
    selectedProfile?.selection_completed_at,
  ]);

  const updateConstraint = (field, value) =>
    setDraft((current) => ({
      ...current,
      hard_constraints: {
        ...current.hard_constraints,
        [field]: value,
      },
    }));

  const save = async () => {
    if (!draft.name.trim()) return;
    setSaving(true);
    try {
      const payload = profilePayload(draft);
      const previousProfile = selectedProfile;
      const creatingProfile = !profileId;
      if (profileId && previousProfile?.is_active) {
        upsertAccessPolicy({
          ...previousProfile,
          ...payload,
          selection_status: 'pending',
          selection_current: false,
          selection_started_at: new Date().toISOString(),
          selection_progress: {
            phase: 'Saving profile and publishing catalog update',
            percent: 0,
            target_export_mode: payload.export_mode,
            queued_at: new Date().toISOString(),
            task_name: 'apps.vod.tasks.rebuild_vod_profile_selection',
            batch: false,
            trigger_reason: 'VOD output profile settings were saved',
          },
        });
      }
      const saved = profileId
        ? await API.updateVODAccessPolicy(profileId, payload)
        : await API.createVODAccessPolicy(payload);
      if (profileId) {
        upsertAccessPolicy(saved);
      } else {
        upsertAccessPolicy(saved, { preserveIfMissing: true });
        // Confirm the committed server list before leaving creation mode. The
        // optimistic entry remains visible if this request fails or a stale
        // response does not contain it yet.
        await fetchProfiles();
      }
      resetDraft(saved);
      setCreating(false);
      setProfileId(String(saved.id));
      if (
        ['pending', 'building'].includes(saved.selection_status) &&
        !saved.selection_progress?.task_id &&
        !creatingProfile
      ) {
        // A caller-owned outer transaction can make the mutation response
        // arrive with the pre-publication placeholder. The follow-up request
        // runs after the HTTP transaction committed and attaches the real
        // Celery task immediately instead of waiting for the first poll tick.
        await fetchProfiles();
      }
      showNotification({
        title: 'VOD output profile saved',
        message: creatingProfile
          ? 'The initial catalog preparation started automatically. The profile is available immediately and becomes client-ready when preparation finishes.'
          : 'The catalog update started automatically. No manual rebuild is required; the previous preview remains visible until the update finishes.',
        color: 'green',
      });
    } catch (error) {
      if (profileId && selectedProfile) {
        upsertAccessPolicy(selectedProfile, { force: true });
      }
      showNotification({
        title: 'VOD output profile was not saved',
        message: error?.message || 'Please check the values and retry.',
        color: 'red',
      });
    } finally {
      setSaving(false);
    }
  };

  const remove = async () => {
    if (!canDeleteProfile) return;
    const deletedProfile = selectedProfile;
    setDeleting(true);
    try {
      await API.deleteVODAccessPolicy(deletedProfile.id);
      removeAccessPolicy(deletedProfile.id);
      const refreshedProfiles = await fetchProfiles();
      const remainingProfiles = Array.isArray(refreshedProfiles)
        ? refreshedProfiles
        : profiles.filter(
            (profile) => String(profile.id) !== String(deletedProfile.id)
          );
      const nextProfile =
        remainingProfiles.find((profile) => profile.is_default) ||
        remainingProfiles[0] ||
        null;
      setCreating(false);
      setProfileId(nextProfile ? String(nextProfile.id) : '');
      resetDraft(nextProfile);
      showNotification({
        title: 'VOD output profile deleted',
        message: `${deletedProfile.name} was removed.`,
        color: 'green',
      });
    } catch (error) {
      await fetchProfiles();
      showNotification({
        title: 'VOD output profile was not deleted',
        message: error?.message || 'Please retry.',
        color: 'red',
      });
    } finally {
      setDeleting(false);
    }
  };

  const rebuild = async () => {
    if (!selectedProfile || draftChanged) return;
    setRebuilding(true);
    try {
      const updated = await API.rebuildVODAccessPolicy(selectedProfile.id);
      upsertAccessPolicy(updated, { force: true });
      if (
        ['pending', 'building'].includes(updated.selection_status) &&
        !updated.selection_progress?.task_id
      ) {
        await fetchProfiles();
      }
      showNotification({
        title: 'VOD output catalog queued',
        message: 'The saved profile catalog is being rebuilt.',
        color: 'green',
      });
    } catch (error) {
      showNotification({
        title: 'VOD output catalog was not queued',
        message: error?.message || 'Please retry.',
        color: 'red',
      });
    } finally {
      setRebuilding(false);
    }
  };

  const startNew = () => {
    setCreating(true);
    setProfileId('');
    resetDraft();
    setActiveTab('settings');
  };

  const draftChanged = profileDraftSignature(draft) !== savedDraftSignature;
  const titleFields = outputTitleFields(draft.name_template);
  const allowedTitleFields = new Set(
    draft.export_mode === 'compact'
      ? ['title', 'year', 'edition']
      : [
          'title',
          'year',
          'provider',
          'dub',
          'sub',
          'resolution',
          'format',
          'features',
        ]
  );
  const unsupportedTitleFields = [...titleFields].filter(
    (field) => !allowedTitleFields.has(field)
  );
  const outputFormatError = !titleFields.has('title')
    ? 'Include {title}; the Title selection controls its value.'
    : unsupportedTitleFields.length
      ? `Not available for ${outputModeLabel(draft.export_mode)}: ${unsupportedTitleFields.map((field) => `{${field}}`).join(', ')}`
      : '';
  const canSave = Boolean(
    draft.name.trim() &&
    !outputFormatError &&
    (creating || (selectedProfile && draftChanged))
  );
  const counts = selectedProfile?.selection_counts || {};
  const buildProgress = selectedProfile?.selection_progress || {};
  const selectionUpdating = ['pending', 'building'].includes(
    selectedProfile?.selection_status
  );
  const buildPhase = buildPhaseDescription(buildProgress);
  const buildPercent = (() => {
    const value = Number(buildProgress.percent);
    if (!Number.isFinite(value)) return null;
    return Math.min(Math.max(value, 0), 100);
  })();
  const activeMode =
    selectedProfile?.selection_active_mode ||
    counts.export_mode ||
    (selectedProfile?.selection_current ? selectedProfile.export_mode : '');
  const advancedPreviewFilterCount = [
    ...(activeMode !== 'compact'
      ? [
          filters.audio_language,
          filters.subtitle_language,
          filters.resolution,
          filters.container_extension,
          filters.video_feature,
        ]
      : []),
    filters.metadata_status,
    filters.genre,
    filters.anime_mode,
    filters.adult_mode,
  ].filter(Boolean).length;
  const clearAdvancedPreviewFilters = () => {
    setFilters((current) => ({
      ...current,
      audio_language: '',
      subtitle_language: '',
      resolution: '',
      container_extension: '',
      video_feature: '',
      metadata_status: '',
      genre: '',
      anime_mode: '',
      adult_mode: '',
    }));
    setPage(1);
  };
  const buildStartedAt =
    selectedProfile?.selection_status === 'pending'
      ? buildProgress.queued_at ||
        selectedProfile.selection_started_at ||
        buildProgress.updated_at
      : selectedProfile?.selection_started_at || buildProgress.updated_at;
  const buildElapsedSeconds = buildStartedAt
    ? Math.max((Date.now() - new Date(buildStartedAt).getTime()) / 1000, 0)
    : 0;
  const lastUpdatedAt =
    counts.completed_at || selectedProfile?.selection_completed_at || '';
  const lastBuildSeconds = Number(counts.prepared_seconds);
  const hasLastBuildDuration =
    counts.prepared_seconds !== null &&
    counts.prepared_seconds !== '' &&
    Number.isFinite(lastBuildSeconds) &&
    lastBuildSeconds >= 0;
  const profileOptions = profiles.map((profile) => ({
    value: String(profile.id),
    label: `${profile.name}${profile.is_default ? ' (default)' : ''}`,
  }));
  const selectionState = (() => {
    if (!selectedProfile?.is_active) {
      return {
        label: 'Inactive',
        color: 'gray',
        description: 'This profile is saved but is not used for XC output.',
      };
    }
    if (selectedProfile.selection_status === 'failed') {
      return {
        label: 'Failed',
        color: 'red',
        description:
          'The latest XC catalog preparation failed. Correct and save the profile, or rebuild its saved catalog manually.',
      };
    }
    if (['pending', 'building'].includes(selectedProfile.selection_status)) {
      const waiting = selectedProfile.selection_status === 'pending';
      const taskState = selectedProfile.selection_task_state || 'UNKNOWN';
      const initialPreparation = !selectedProfile.active_selection_generation;
      return {
        label: initialPreparation ? 'Preparing' : 'Updating',
        color: 'blue',
        description: initialPreparation
          ? waiting
            ? `The initial catalog is waiting in the Celery queue (task state: ${taskState}).`
            : 'The initial source selection is being prepared for clients.'
          : waiting
            ? `The update is waiting in the Celery queue (task state: ${taskState}). The current catalog remains active.`
            : 'The updated source selection is being prepared. The current catalog remains active until this finishes.',
      };
    }
    if (selectedProfile.selection_current) {
      return {
        label: 'Ready',
        color: 'green',
        description:
          'The prepared XC catalog is current and ready for clients.',
      };
    }
    return {
      label: 'Outdated',
      color: 'yellow',
      description:
        'The saved profile may be affected by changed metadata. Its last completed catalog remains active until you rebuild it.',
    };
  })();
  const batchWaitingForTurn = Boolean(
    selectedProfile?.selection_status === 'pending' &&
    buildProgress.batch &&
    selectedProfile.selection_task_state === 'STARTED' &&
    !String(buildProgress.phase || '').includes('M3U/VOD refresh')
  );
  const candidateContent = useMemo(
    () =>
      candidateTarget
        ? {
            id: candidateTarget.canonical_id,
            name:
              candidateTarget.name ||
              candidateTarget.canonical_title ||
              candidateTarget.provider_title,
            year: candidateTarget.year,
          }
        : null,
    [candidateTarget]
  );
  const Surface = embedded ? Box : Modal;
  const surfaceProps = embedded
    ? {
        p: 'md',
        h: '100%',
        style: {
          display: 'flex',
          flexDirection: 'column',
          minHeight: 0,
          minWidth: 0,
          overflow: 'hidden',
        },
      }
    : {
        opened,
        onClose,
        title: 'VOD output profiles',
        size: '70vw',
        yOffset: '5vh',
        lockScroll: false,
        styles: {
          content: {
            display: 'flex',
            flexDirection: 'column',
            height: '90vh',
            maxHeight: '90vh',
            minWidth: 0,
            overflow: 'hidden',
          },
          body: {
            flex: 1,
            minHeight: 0,
            minWidth: 0,
            overflow: 'hidden',
          },
        },
      };
  return (
    <>
      <Surface {...surfaceProps}>
        <Stack h="100%" gap="sm" style={{ minWidth: 0 }}>
          {embedded && <Title order={2}>VOD Profiles</Title>}
          <Group align="flex-end" wrap="wrap">
            <Select
              label="Profile"
              placeholder="New profile"
              searchable
              data={profileOptions}
              value={profileId || null}
              onChange={(value) => {
                setCreating(false);
                setProfileId(value || '');
              }}
              style={{ flex: '0 1 460px', minWidth: 260 }}
            />
            {selectedProfile && (
              <Tooltip label={selectionState.description} multiline maw={360}>
                <Box h={36} style={{ display: 'flex', alignItems: 'center' }}>
                  <Badge color={selectionState.color} size="lg">
                    {selectionState.label}
                  </Badge>
                </Box>
              </Tooltip>
            )}
            <Group gap="sm" wrap="nowrap" style={{ marginLeft: 'auto' }}>
              <Button
                variant="default"
                leftSection={<Plus size={15} />}
                onClick={startNew}
              >
                New
              </Button>
              {selectedProfile &&
                ['outdated', 'failed'].includes(
                  selectedProfile.selection_status
                ) && (
                  <Tooltip
                    label={
                      draftChanged
                        ? 'Save or discard the profile changes before rebuilding.'
                        : 'Build a new catalog from the saved profile and current metadata.'
                    }
                  >
                    <Box>
                      <Button
                        variant="default"
                        leftSection={<RefreshCw size={15} />}
                        loading={rebuilding}
                        disabled={draftChanged}
                        onClick={rebuild}
                      >
                        Rebuild
                      </Button>
                    </Box>
                  </Tooltip>
                )}
              <Button
                leftSection={<Save size={15} />}
                loading={saving}
                disabled={!canSave}
                onClick={save}
              >
                Save profile
              </Button>
              <Tooltip label={deleteProfileHint}>
                <Box>
                  <Button
                    color="red"
                    variant="light"
                    leftSection={<Trash2 size={15} />}
                    disabled={!canDeleteProfile}
                    loading={deleting}
                    onClick={remove}
                  >
                    Delete
                  </Button>
                </Box>
              </Tooltip>
            </Group>
          </Group>

          {selectedProfile && (
            <Group gap="xs" wrap="wrap">
              {selectionAvailable ? (
                <Badge variant="light" color="gray">
                  {catalogModeLabel(activeMode)}
                </Badge>
              ) : (
                <Text size="sm" c="dimmed">
                  No catalog prepared yet
                </Text>
              )}
              {lastUpdatedAt && (
                <Text size="sm" c="dimmed">
                  Last updated: {new Date(lastUpdatedAt).toLocaleString()}
                </Text>
              )}
              {hasLastBuildDuration && (
                <Text size="sm" c="dimmed">
                  Last build: {formatDuration(lastBuildSeconds)}
                </Text>
              )}
            </Group>
          )}

          {!selectionUpdating && (
            <Group gap="lg" wrap="wrap">
              <Text size="sm">
                Movies: {counts.movies?.output_entries || 0} output entries ·{' '}
                {counts.movies?.canonical_titles || 0} titles
              </Text>
              <Text size="sm">
                Series: {counts.series?.output_entries || 0} output entries ·{' '}
                {counts.series?.canonical_titles || 0} titles
              </Text>
              <Text size="sm">
                Eligible sources: {counts.eligible_sources || 0} · Unknown
                metadata: {counts.unknown_metadata || 0}
              </Text>
            </Group>
          )}

          {selectionUpdating && (
            <Stack gap={3}>
              <Text size="sm" fw={500}>
                {batchWaitingForTurn
                  ? 'VOD profile catalog batch is running; this profile is waiting for its turn'
                  : buildPhase ||
                    (selectedProfile.selection_status === 'pending'
                      ? 'Waiting for worker'
                      : 'Preparing catalog')}
                {buildProgress.batch_position && buildProgress.batch_total
                  ? ` · Profile ${buildProgress.batch_position} of ${buildProgress.batch_total}`
                  : ''}
                {buildPercent !== null
                  ? ` · ${Math.round(buildPercent)}% complete`
                  : ''}
                {` · ${formatDuration(buildElapsedSeconds)} elapsed`}
              </Text>
              {buildPercent !== null && (
                <Progress
                  value={buildPercent}
                  animated={selectedProfile.selection_status === 'building'}
                  aria-label="Catalog preparation progress"
                  size="sm"
                />
              )}
            </Stack>
          )}

          {selectedProfile?.selection_status === 'ready' &&
            selectionAvailable &&
            activeMode &&
            activeMode !== selectedProfile.export_mode && (
              <Alert color="yellow" title="Saved settings are not active">
                The active catalog was built as {outputModeLabel(activeMode)},
                but this profile is saved as{' '}
                {outputModeLabel(selectedProfile.export_mode)}. Save the profile
                once to publish a corrected catalog build.
              </Alert>
            )}

          {selectedProfile?.selection_error && (
            <Alert color="red">{selectedProfile.selection_error}</Alert>
          )}

          <Tabs
            value={activeTab}
            onChange={setActiveTab}
            style={{
              display: 'flex',
              flex: 1,
              flexDirection: 'column',
              minHeight: 0,
              minWidth: 0,
              overflow: 'hidden',
            }}
            styles={{
              list: { flexShrink: 0 },
              panel: {
                flex: 1,
                minHeight: 0,
                minWidth: 0,
                overflow: 'hidden',
              },
            }}
          >
            <TabsList>
              <TabsTab value="settings">Settings</TabsTab>
              <Tooltip
                label={SOURCES_TAB_HELP}
                multiline
                maw={420}
                openDelay={350}
                withArrow
              >
                <TabsTab value="sources">Sources</TabsTab>
              </Tooltip>
              <Tooltip
                label={CONTENT_RULES_TAB_HELP}
                multiline
                maw={420}
                openDelay={350}
                withArrow
              >
                <TabsTab value="content-rules">Content rules</TabsTab>
              </Tooltip>
              {draft.export_mode === 'compact' && (
                <Tooltip
                  label={EDITIONS_TAB_HELP}
                  multiline
                  maw={420}
                  openDelay={350}
                  withArrow
                >
                  <TabsTab value="editions">Editions</TabsTab>
                </Tooltip>
              )}
              {draft.export_mode === 'compact' && (
                <TabsTab value="failover">Failover</TabsTab>
              )}
              <TabsTab value="preview">Content preview</TabsTab>
            </TabsList>

            <TabsPanel value="settings" pt="md">
              <ScrollArea h="100%">
                <Box pb="xs">
                  <Paper withBorder p="lg" radius="md" maw={900} mx="auto">
                    <Stack>
                      <TextInput
                        label="Profile name"
                        required
                        value={draft.name}
                        onChange={(event) =>
                          setDraft({
                            ...draft,
                            name: event.currentTarget.value,
                          })
                        }
                      />
                      <Select
                        label="Output"
                        data={[
                          {
                            value: 'compact',
                            label:
                              'Compact — one entry per canonical title and suffix',
                          },
                          {
                            value: 'variants',
                            label:
                              'Variants — every allowed provider source as a separate entry',
                          },
                        ]}
                        value={draft.export_mode}
                        onChange={(value) =>
                          setDraft({
                            ...draft,
                            export_mode: value,
                            naming_mode: 'template',
                            name_template: defaultOutputTemplate(value),
                            canonical_title_source:
                              value === 'compact' &&
                              draft.canonical_title_source === 'provider'
                                ? 'primary'
                                : draft.canonical_title_source,
                          })
                        }
                      />
                      <Select
                        label="Metadata"
                        description="Choose the descriptive data independently from the output title."
                        data={[
                          {
                            value: 'canonical',
                            label: 'Enriched — use canonical / TMDB metadata',
                          },
                          {
                            value: 'provider',
                            label:
                              'Provider — use metadata from the selected source',
                          },
                        ]}
                        value={draft.metadata_source}
                        onChange={(value) =>
                          setDraft({
                            ...draft,
                            metadata_source: value || 'canonical',
                          })
                        }
                      />
                      <Select
                        label="Title"
                        description="This value is inserted wherever {title} appears below."
                        data={[
                          {
                            value: 'primary',
                            label: 'Canonical — primary language',
                          },
                          {
                            value: 'secondary',
                            label: 'Canonical — secondary language',
                          },
                          ...(draft.export_mode === 'variants'
                            ? [
                                {
                                  value: 'provider',
                                  label: 'Provider — original source title',
                                },
                              ]
                            : []),
                        ]}
                        value={draft.canonical_title_source}
                        onChange={(value) =>
                          setDraft({
                            ...draft,
                            canonical_title_source: value || 'primary',
                          })
                        }
                      />
                      <TextInput
                        label="Output format"
                        description={
                          draft.export_mode === 'compact'
                            ? 'Available: {title}, {year}, {edition}'
                            : 'Available: {title}, {year}, {provider}, {dub}, {sub}, {resolution}, {format}, {features}'
                        }
                        placeholder={defaultOutputTemplate(draft.export_mode)}
                        value={draft.name_template}
                        error={outputFormatError || null}
                        onChange={(event) =>
                          setDraft({
                            ...draft,
                            naming_mode: 'template',
                            name_template: event.currentTarget.value,
                          })
                        }
                      />
                      <Group grow>
                        <Switch
                          label="Active"
                          checked={draft.is_active}
                          onChange={(event) =>
                            setDraft({
                              ...draft,
                              is_active: event.currentTarget.checked,
                            })
                          }
                        />
                        <Switch
                          label="Default profile"
                          checked={draft.is_default}
                          onChange={(event) =>
                            setDraft({
                              ...draft,
                              is_default: event.currentTarget.checked,
                            })
                          }
                        />
                      </Group>
                    </Stack>
                  </Paper>
                </Box>
              </ScrollArea>
            </TabsPanel>

            <TabsPanel value="sources" pt="md">
              <ScrollArea h="100%">
                <Box pb="xs">
                  <Paper withBorder p="lg" radius="md">
                    <Stack>
                      <Tabs defaultValue="movie">
                        <TabsList>
                          <TabsTab value="movie">VOD - Movies</TabsTab>
                          <TabsTab value="series">VOD - Series</TabsTab>
                        </TabsList>
                        <TabsPanel value="movie">
                          <VODCategoryFilter
                            mode="profile"
                            categoryStates={movieCategoryStates}
                            setCategoryStates={updateProfileCategoryStates(
                              movieCategoryStates
                            )}
                            type="movie"
                            rules={(
                              draft.hard_constraints.category_import_rules || []
                            ).filter((rule) => rule.scope === 'movie')}
                            onRulesChange={(rules) =>
                              updateProfileCategoryRules('movie', rules)
                            }
                            accountOptions={accountOptions}
                          />
                        </TabsPanel>
                        <TabsPanel value="series">
                          <VODCategoryFilter
                            mode="profile"
                            categoryStates={seriesCategoryStates}
                            setCategoryStates={updateProfileCategoryStates(
                              seriesCategoryStates
                            )}
                            type="series"
                            rules={(
                              draft.hard_constraints.category_import_rules || []
                            ).filter((rule) => rule.scope === 'series')}
                            onRulesChange={(rules) =>
                              updateProfileCategoryRules('series', rules)
                            }
                            accountOptions={accountOptions}
                          />
                        </TabsPanel>
                      </Tabs>
                    </Stack>
                  </Paper>
                </Box>
              </ScrollArea>
            </TabsPanel>

            <TabsPanel value="content-rules" pt="md">
              <ScrollArea h="100%">
                <Box pb="xs">
                  <Paper withBorder p="lg" radius="md">
                    <VODSourceRules
                      value={draft.hard_constraints.source_rules || []}
                      onChange={(value) =>
                        updateConstraint('source_rules', value)
                      }
                      defaultAction={
                        draft.hard_constraints.content_default_action ||
                        'include'
                      }
                      onDefaultActionChange={(value) =>
                        updateConstraint('content_default_action', value)
                      }
                      categoryRelationIds={selectedCategoryIds}
                      onOpenDetails={(row) =>
                        setCandidateTarget({ ...row, profile_context: false })
                      }
                    />
                  </Paper>
                </Box>
              </ScrollArea>
            </TabsPanel>

            {draft.export_mode === 'compact' && (
              <TabsPanel value="failover" pt="md">
                <ScrollArea h="100%">
                  <Box pb="xs">
                    <Paper withBorder p="lg" radius="md" maw={900} mx="auto">
                      <VODFailoverRanking
                        value={draft.ranking}
                        disabled={draft.hard_constraints.disabled_ranking || []}
                        audioLanguageOrder={
                          draft.hard_constraints.audio_language_order || []
                        }
                        subtitleLanguageOrder={
                          draft.hard_constraints.subtitle_language_order || []
                        }
                        providerOrder={draft.provider_order}
                        providerOptions={failoverAccountOptions}
                        onChange={(ranking) =>
                          setDraft((current) => ({ ...current, ranking }))
                        }
                        onDisabledChange={(disabledRanking) =>
                          updateConstraint('disabled_ranking', disabledRanking)
                        }
                        onAudioLanguageOrderChange={(languages) =>
                          updateConstraint('audio_language_order', languages)
                        }
                        onSubtitleLanguageOrderChange={(languages) =>
                          updateConstraint('subtitle_language_order', languages)
                        }
                        onProviderOrderChange={(providerOrder) =>
                          setDraft((current) => ({
                            ...current,
                            provider_order: providerOrder,
                          }))
                        }
                      />
                    </Paper>
                  </Box>
                </ScrollArea>
              </TabsPanel>
            )}

            <TabsPanel value="editions" pt="md">
              <ScrollArea h="100%">
                <Box pb="xs">
                  {draft.export_mode === 'compact' && (
                    <Paper withBorder p="lg" radius="md">
                      <VODEditionRules
                        value={draft.edition_rules}
                        onChange={(edition_rules) =>
                          setDraft((current) => ({
                            ...current,
                            edition_rules,
                          }))
                        }
                      />
                    </Paper>
                  )}
                </Box>
              </ScrollArea>
            </TabsPanel>

            <TabsPanel value="preview" pt="md">
              <Stack h="100%" style={{ minHeight: 0, overflow: 'hidden' }}>
                {!selectionAvailable && (
                  <Alert color="yellow">
                    This profile has no completed catalog yet. Its content can
                    be previewed as soon as the first preparation finishes.
                  </Alert>
                )}
                <Group align="flex-end" wrap="wrap">
                  <SegmentedControl
                    value={filters.type}
                    onChange={(value) => {
                      setFilters({ ...filters, type: value, category: '' });
                      setPage(1);
                    }}
                    data={[
                      { value: 'movie', label: 'Movies' },
                      { value: 'series', label: 'Series' },
                    ]}
                  />
                  <TextInput
                    label="Search"
                    value={filters.search}
                    onChange={(event) => {
                      setFilters({
                        ...filters,
                        search: event.currentTarget.value,
                      });
                      setPage(1);
                    }}
                    miw={220}
                  />
                  {activeMode !== 'compact' && (
                    <Select
                      label="M3U account"
                      clearable
                      searchable
                      data={accountOptions}
                      value={filters.m3u_account || null}
                      onChange={(value) => {
                        setFilters({
                          ...filters,
                          m3u_account: value || '',
                          category: '',
                        });
                        setPage(1);
                      }}
                      miw={180}
                    />
                  )}
                  <Select
                    label="Category"
                    clearable
                    searchable
                    data={categoryOptions}
                    value={filters.category || null}
                    onChange={(value) => {
                      setFilters({ ...filters, category: value || '' });
                      setPage(1);
                    }}
                    miw={180}
                  />
                  <Popover
                    width={470}
                    position="bottom-end"
                    shadow="md"
                    withArrow
                    withinPortal
                  >
                    <PopoverTarget>
                      <Button
                        variant={
                          advancedPreviewFilterCount ? 'light' : 'default'
                        }
                        leftSection={<Filter size={17} />}
                        aria-label="Additional output preview filters"
                      >
                        Filters
                        {advancedPreviewFilterCount
                          ? ` (${advancedPreviewFilterCount})`
                          : ''}
                      </Button>
                    </PopoverTarget>
                    <PopoverDropdown>
                      <Stack gap="sm">
                        <SimpleGrid cols={2}>
                          {activeMode !== 'compact' && (
                            <>
                              <LanguageSelect
                                label="DUB"
                                value={filters.audio_language}
                                onChange={(value) => {
                                  setFilters({
                                    ...filters,
                                    audio_language: value,
                                  });
                                  setPage(1);
                                }}
                              />
                              <LanguageSelect
                                label="SUB"
                                value={filters.subtitle_language}
                                onChange={(value) => {
                                  setFilters({
                                    ...filters,
                                    subtitle_language: value,
                                  });
                                  setPage(1);
                                }}
                              />
                              <Select
                                label="Resolution"
                                placeholder="Any"
                                clearable
                                data={RESOLUTION_VALUES}
                                value={filters.resolution || null}
                                onChange={(value) => {
                                  setFilters({
                                    ...filters,
                                    resolution: value || '',
                                  });
                                  setPage(1);
                                }}
                              />
                              <Select
                                label="Format"
                                placeholder="Any"
                                clearable
                                data={CONTAINER_EXTENSION_OPTIONS}
                                value={filters.container_extension || null}
                                onChange={(value) => {
                                  setFilters({
                                    ...filters,
                                    container_extension: value || '',
                                  });
                                  setPage(1);
                                }}
                              />
                              <Box>
                                <VideoFeaturePicker
                                  label="Features"
                                  emptyLabel="Any"
                                  value={
                                    filters.video_feature
                                      ? [filters.video_feature]
                                      : []
                                  }
                                  onChange={(value) => {
                                    setFilters({
                                      ...filters,
                                      video_feature:
                                        value[value.length - 1] || '',
                                    });
                                    setPage(1);
                                  }}
                                />
                              </Box>
                            </>
                          )}
                          <Select
                            label="Metadata"
                            placeholder="Any"
                            clearable
                            data={[
                              { value: 'missing_tmdb', label: 'No TMDB ID' },
                              {
                                value: 'missing_external_ids',
                                label: 'No external ID',
                              },
                              {
                                value: 'missing_metadata',
                                label: 'TMDB details not enriched',
                              },
                            ]}
                            value={filters.metadata_status || null}
                            onChange={(value) => {
                              setFilters({
                                ...filters,
                                metadata_status: value || '',
                              });
                              setPage(1);
                            }}
                          />
                          <TextInput
                            label="Genre contains"
                            placeholder="e.g. Horror"
                            value={filters.genre || ''}
                            onChange={(event) => {
                              setFilters({
                                ...filters,
                                genre: event.currentTarget.value,
                              });
                              setPage(1);
                            }}
                          />
                          <Select
                            label="Anime"
                            placeholder="Any"
                            clearable
                            data={[
                              { value: 'yes', label: 'Yes' },
                              { value: 'no', label: 'No' },
                            ]}
                            value={filters.anime_mode || null}
                            onChange={(value) => {
                              setFilters({
                                ...filters,
                                anime_mode: value || '',
                              });
                              setPage(1);
                            }}
                          />
                          <Select
                            label="Adult content"
                            placeholder="Any"
                            clearable
                            data={[
                              { value: 'yes', label: 'Yes' },
                              { value: 'no', label: 'No' },
                            ]}
                            value={filters.adult_mode || null}
                            onChange={(value) => {
                              setFilters({
                                ...filters,
                                adult_mode: value || '',
                              });
                              setPage(1);
                            }}
                          />
                        </SimpleGrid>
                        <Group justify="flex-end">
                          <Button
                            size="xs"
                            variant="subtle"
                            disabled={!advancedPreviewFilterCount}
                            onClick={clearAdvancedPreviewFilters}
                          >
                            Clear filters
                          </Button>
                        </Group>
                      </Stack>
                    </PopoverDropdown>
                  </Popover>
                </Group>
                <Group justify="space-between">
                  <Text fw={500}>
                    {preview.count || 0} matching output entries
                  </Text>
                  <Text size="sm" c="dimmed">
                    {filters.type === 'movie'
                      ? counts.movies?.canonical_titles || 0
                      : counts.series?.canonical_titles || 0}{' '}
                    canonical titles in this profile
                  </Text>
                </Group>
                <ScrollArea style={{ flex: 1, minHeight: 0 }}>
                  <Box pb="xs">
                    <Table
                      striped
                      highlightOnHover
                      withTableBorder
                      stickyHeader
                    >
                      <TableThead>
                        <TableTr>
                          <TableTh>Title</TableTh>
                          <TableTh>
                            {activeMode === 'compact' ? 'Sources' : 'Source'}
                          </TableTh>
                          <TableTh>Category</TableTh>
                          {activeMode !== 'compact' && (
                            <>
                              <TableTh>DUB</TableTh>
                              <TableTh>SUB</TableTh>
                              <TableTh>Resolution</TableTh>
                              <TableTh>Format</TableTh>
                              <TableTh>Features</TableTh>
                            </>
                          )}
                          <TableTh>Details</TableTh>
                        </TableTr>
                      </TableThead>
                      <TableTbody>
                        {!previewLoading && preview.results?.length === 0 && (
                          <TableTr>
                            <TableTd colSpan={activeMode === 'compact' ? 4 : 9}>
                              <Text ta="center" c="dimmed" py="lg">
                                No prepared output matches the current filters.
                              </Text>
                            </TableTd>
                          </TableTr>
                        )}
                        {(preview.results || []).map((row) => (
                          <TableTr key={row.id}>
                            <TableTd>{row.name}</TableTd>
                            <TableTd>
                              {activeMode === 'compact'
                                ? row.source_count
                                : row.m3u_account_name}
                            </TableTd>
                            <TableTd>{row.category_name || '—'}</TableTd>
                            {activeMode !== 'compact' && (
                              <>
                                <TableTd>
                                  {metadataText(
                                    row.metadata,
                                    'audio_languages'
                                  )}
                                </TableTd>
                                <TableTd>
                                  {metadataText(
                                    row.metadata,
                                    'subtitle_languages'
                                  )}
                                </TableTd>
                                <TableTd>
                                  {row.resolution ? `${row.resolution}p` : '—'}
                                </TableTd>
                                <TableTd>
                                  {row.container_extension || '—'}
                                </TableTd>
                                <TableTd>
                                  {metadataText(row.metadata, 'video_features')}
                                </TableTd>
                              </>
                            )}
                            <TableTd>
                              <Tooltip label="Open title and profile sources">
                                <ActionIcon
                                  variant="subtle"
                                  aria-label={`Open details for ${row.name}`}
                                  onClick={() => setCandidateTarget(row)}
                                >
                                  <Eye size={17} />
                                </ActionIcon>
                              </Tooltip>
                            </TableTd>
                          </TableTr>
                        ))}
                      </TableTbody>
                    </Table>
                  </Box>
                </ScrollArea>
                <Group
                  gap={5}
                  justify="center"
                  wrap="nowrap"
                  style={{ flexShrink: 0, paddingBottom: 2 }}
                >
                  <Text size="xs">Rows</Text>
                  <Select
                    aria-label="Rows"
                    size="xs"
                    value={String(previewPageSize)}
                    data={PREVIEW_PAGE_SIZES.map((value) => ({
                      value: String(value),
                      label: String(value),
                    }))}
                    onChange={(value) => {
                      const nextPageSize = Number(value) || 50;
                      setPreviewPageSize(nextPageSize);
                      setPage(1);
                      window.localStorage.setItem(
                        PREVIEW_PAGE_SIZE_STORAGE_KEY,
                        String(nextPageSize)
                      );
                    }}
                    allowDeselect={false}
                    w={70}
                  />
                  <Pagination
                    value={page}
                    onChange={setPage}
                    total={Math.max(
                      1,
                      Math.ceil((preview.count || 0) / previewPageSize)
                    )}
                    size="xs"
                    withEdges
                  />
                  <Text size="xs" c="dimmed">
                    {preview.count
                      ? `${(page - 1) * previewPageSize + 1}–${Math.min(
                          page * previewPageSize,
                          preview.count
                        )} of ${preview.count}`
                      : '0 of 0'}
                  </Text>
                </Group>
              </Stack>
            </TabsPanel>
          </Tabs>
        </Stack>
      </Surface>

      {candidateTarget?.content_type === 'series' ? (
        <SeriesModal
          series={candidateContent}
          opened
          onClose={() => setCandidateTarget(null)}
          profileCandidates={candidateData}
          profileCandidatesLoading={candidateLoading}
          profileCandidatesError={candidateError}
          onMetadataChanged={loadPreview}
        />
      ) : candidateTarget ? (
        <VODModal
          vod={candidateContent}
          opened
          onClose={() => setCandidateTarget(null)}
          profileCandidates={candidateData}
          profileCandidatesLoading={candidateLoading}
          profileCandidatesError={candidateError}
          onMetadataChanged={loadPreview}
        />
      ) : null}
    </>
  );
};

export default VODOutputProfilesModal;
