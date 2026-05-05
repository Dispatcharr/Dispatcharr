import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  Modal,
  Stack,
  Text,
  TextInput,
  Textarea,
  SegmentedControl,
  Group,
  Button,
  Select,
  Badge,
  Divider,
  ScrollArea,
  Alert,
} from '@mantine/core';
import API from '../../api.js';
import useChannelsStore from '../../store/channels.jsx';
import useEPGsStore from '../../store/epgs.jsx';
import { useDebounce } from '../../utils.js';
import { showNotification } from '../../utils/notificationUtils.js';

const TITLE_MODES = [
  { label: 'Exact', value: 'exact' },
  { label: 'Contains', value: 'contains' },
  { label: 'Whole word', value: 'search' },
  { label: 'Regex', value: 'regex' },
];

const DESCRIPTION_MODES = [
  { label: 'Contains', value: 'contains' },
  { label: 'Whole word', value: 'search' },
  { label: 'Regex', value: 'regex' },
];

const EPISODE_MODES = [
  { label: 'All episodes', value: 'all' },
  { label: 'New only', value: 'new' },
];

function formatRange(start, end) {
  try {
    const s = new Date(start);
    const e = new Date(end);
    const sameDay = s.toDateString() === e.toDateString();
    const dateStr = s.toLocaleDateString();
    const startStr = s.toLocaleTimeString([], {
      hour: '2-digit',
      minute: '2-digit',
    });
    const endStr = e.toLocaleTimeString([], {
      hour: '2-digit',
      minute: '2-digit',
    });
    return sameDay
      ? `${dateStr} ${startStr} - ${endStr}`
      : `${dateStr} ${startStr} -> ${e.toLocaleString()}`;
  } catch {
    return `${start} - ${end}`;
  }
}

export default function SeriesRuleEditorModal({
  opened,
  onClose,
  initialRule,
  onSaved,
}) {
  const tvgs = useEPGsStore((s) => s.tvgs);
  const tvgsById = useEPGsStore((s) => s.tvgsById);

  const [tvgId, setTvgId] = useState('');
  const [mode, setMode] = useState('all');
  const [title, setTitle] = useState('');
  const [titleMode, setTitleMode] = useState('exact');
  const [description, setDescription] = useState('');
  const [descriptionMode, setDescriptionMode] = useState('contains');
  const [channelId, setChannelId] = useState('');
  const [allChannels, setAllChannels] = useState([]);

  const [preview, setPreview] = useState({
    matches: [],
    total: 0,
    epg_found: true,
  });
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState(null);
  const [saving, setSaving] = useState(false);
  const abortRef = useRef(null);

  // Hydrate state when opened or initial rule changes
  useEffect(() => {
    if (!opened) return;
    setTvgId(String(initialRule?.tvg_id || ''));
    setMode(initialRule?.mode || 'all');
    setTitle(initialRule?.title || '');
    setTitleMode(initialRule?.title_mode || 'exact');
    setDescription(initialRule?.description || '');
    setDescriptionMode(initialRule?.description_mode || 'contains');
    setChannelId(initialRule?.channel_id ? String(initialRule.channel_id) : '');
    setPreview({ matches: [], total: 0, epg_found: true });
    setPreviewError(null);
  }, [opened, initialRule]);

  // Load channels from the summary API on modal open (same as Recording.jsx).
  useEffect(() => {
    if (!opened) return;
    let cancelled = false;
    API.getChannelsSummary()
      .then((chans) => {
        if (!cancelled) setAllChannels(Array.isArray(chans) ? chans : []);
      })
      .catch(() => {
        if (!cancelled) setAllChannels([]);
      });
    return () => {
      cancelled = true;
    };
  }, [opened]);

  // Build the payload for both preview and save
  const payload = useMemo(
    () => ({
      tvg_id: tvgId.trim(),
      mode,
      title: title.trim(),
      title_mode: titleMode,
      description: description.trim(),
      description_mode: descriptionMode,
      ...(channelId ? { channel_id: Number(channelId) } : {}),
    }),
    [tvgId, mode, title, titleMode, description, descriptionMode, channelId]
  );

  // Debounce the part of the payload that affects preview
  const debouncedPreviewKey = useDebounce(payload, 500);

  useEffect(() => {
    if (!opened) return;
    if (
      !debouncedPreviewKey.tvg_id &&
      !debouncedPreviewKey.title &&
      !debouncedPreviewKey.description
    ) {
      setPreview({ matches: [], total: 0, epg_found: true });
      return;
    }
    // Abort any in-flight request
    if (abortRef.current) abortRef.current.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    setPreviewLoading(true);
    setPreviewError(null);
    API.previewSeriesRule(debouncedPreviewKey, { signal: controller.signal })
      .then((resp) => {
        if (controller.signal.aborted) return;
        setPreview(resp || { matches: [], total: 0 });
      })
      .catch((err) => {
        if (err?.name === 'AbortError' || controller.signal.aborted) return;
        const msg = err?.body?.error || err?.message || 'Preview failed';
        setPreviewError(msg);
        setPreview({ matches: [], total: 0, epg_found: true });
      })
      .finally(() => {
        if (!controller.signal.aborted) setPreviewLoading(false);
      });

    return () => controller.abort();
  }, [opened, debouncedPreviewKey]);

  // EPG channel options for the tvg_id selector. Deduplicate by tvg_id value
  // since the same channel can appear across multiple EPG sources.
  const tvgOptions = useMemo(() => {
    const seen = new Set();
    const options = [];
    for (const t of tvgs || []) {
      if (!t.tvg_id || seen.has(t.tvg_id)) continue;
      seen.add(t.tvg_id);
      options.push({
        value: t.tvg_id,
        label: t.name ? `${t.name} (${t.tvg_id})` : t.tvg_id,
      });
    }
    return options.sort((a, b) => a.label.localeCompare(b.label));
  }, [tvgs]);

  // Channel select options: prefer channels matching the selected tvg_id.
  const channelOptions = useMemo(() => {
    const sorted = [...allChannels].sort((a, b) => {
      const aNum = Number(a.channel_number) || 0;
      const bNum = Number(b.channel_number) || 0;
      if (aNum !== bNum) return aNum - bNum;
      return (a.name || '').localeCompare(b.name || '');
    });
    const matching = [];
    const others = [];
    for (const c of sorted) {
      const item = {
        value: String(c.id),
        label: c.channel_number
          ? `${c.channel_number} - ${c.name || `Channel ${c.id}`}`
          : c.name || `Channel ${c.id}`,
      };
      const cTvg = c.epg_data_id ? tvgsById?.[c.epg_data_id]?.tvg_id : null;
      if (tvgId && cTvg && String(cTvg) === String(tvgId)) {
        matching.push(item);
      } else {
        others.push(item);
      }
    }
    return [...matching, ...others];
  }, [allChannels, tvgsById, tvgId]);

  const canSave = !!(payload.title || payload.description);

  const handleSave = async () => {
    setSaving(true);
    try {
      await API.createSeriesRule(payload);
      // Trigger evaluation so matching upcoming programs get scheduled.
      try {
        await API.evaluateSeriesRules(payload.tvg_id);
        await useChannelsStore.getState().fetchRecordings();
      } catch (e) {
        console.warn('Failed to evaluate after save', e);
      }
      showNotification({ title: 'Series rule saved' });
      if (onSaved) await onSaved();
      onClose();
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title={initialRule?.tvg_id ? 'Edit Series Rule' : 'New Series Rule'}
      centered
      size="lg"
      radius="md"
      zIndex={9999}
      overlayProps={{ color: '#000', backgroundOpacity: 0.55, blur: 0 }}
      styles={{
        content: { backgroundColor: '#18181B', color: 'white' },
        header: { backgroundColor: '#18181B', color: 'white' },
        title: { color: 'white' },
      }}
    >
      <Stack gap="sm">
        <Select
          label="EPG channel (optional)"
          description="Limit matching to a specific EPG channel. Leave blank to search all channels."
          placeholder="Search by name or tvg_id..."
          searchable
          clearable
          data={tvgOptions}
          value={tvgId || null}
          onChange={(v) => setTvgId(v || '')}
          nothingFoundMessage="No EPG channels found"
          comboboxProps={{ zIndex: 10000 }}
          filter={({ options, search }) => {
            const q = search.toLowerCase().trim();
            if (!q) return options;
            return options.filter(
              ({ label, value }) =>
                label.toLowerCase().includes(q) ||
                value.toLowerCase().includes(q)
            );
          }}
        />

        <Stack gap={4}>
          <TextInput
            label="Title (optional)"
            description="At least a title or description is required."
            placeholder='e.g. The Daily Show, or "Law and Order" AND crime'
            value={title}
            onChange={(e) => setTitle(e.currentTarget.value)}
          />
          <SegmentedControl
            data={TITLE_MODES}
            value={titleMode}
            onChange={setTitleMode}
            size="xs"
          />
        </Stack>

        <Stack gap={4}>
          <Textarea
            label="Description (optional)"
            description="Match against the program description. Supports AND / OR and quoted phrases."
            placeholder="e.g. (Newcastle OR NEW) AND (Villa OR AST)"
            value={description}
            onChange={(e) => setDescription(e.currentTarget.value)}
            autosize
            minRows={1}
            maxRows={3}
          />
          <SegmentedControl
            data={DESCRIPTION_MODES}
            value={descriptionMode}
            onChange={setDescriptionMode}
            size="xs"
          />
        </Stack>

        <Group grow align="end">
          <Stack gap={4}>
            <Text size="sm" fw={500}>
              Episodes
            </Text>
            <SegmentedControl
              data={EPISODE_MODES}
              value={mode}
              onChange={setMode}
              size="xs"
            />
          </Stack>
          <Select
            label="Pinned channel (optional)"
            description="Recordings will be created on this channel. Defaults to lowest channel number for the EPG."
            placeholder="Default"
            data={channelOptions}
            value={channelId || null}
            onChange={(v) => setChannelId(v || '')}
            clearable
            searchable
            comboboxProps={{ zIndex: 10000 }}
          />
        </Group>

        <Divider />

        <Group justify="space-between" align="center">
          <Group gap="xs" align="center">
            <Text size="sm" fw={500}>
              Preview
            </Text>
            <Badge
              size="sm"
              variant="light"
              color={previewLoading ? 'yellow' : 'blue'}
            >
              {previewLoading
                ? 'loading'
                : `${preview.matches?.length || 0} of ${preview.total || 0}`}
            </Badge>
          </Group>
          {!preview.epg_found && tvgId && !previewLoading && (
            <Text size="xs" c="orange">
              No EPG channel matches this tvg_id.
            </Text>
          )}
        </Group>

        {previewError && (
          <Alert color="red" variant="light">
            {previewError}
          </Alert>
        )}

        {preview.warn && !previewLoading && (
          <Alert color="orange" variant="light">
            This rule matches many programs. Consider selecting a specific EPG
            channel or adding more search criteria.
          </Alert>
        )}

        <ScrollArea.Autosize mah={240}>
          <Stack gap={4}>
            {(preview.matches || []).map((p) => (
              <Group key={p.id} gap="xs" wrap="nowrap" align="flex-start">
                <Stack gap={0} style={{ minWidth: 160 }}>
                  <Text size="xs" c="dimmed">
                    {formatRange(p.start_time, p.end_time)}
                  </Text>
                  {p.tvg_id && !tvgId && (
                    <Text size="xs" c="dimmed" fs="italic">
                      {p.tvg_id}
                    </Text>
                  )}
                </Stack>
                <Stack gap={0} style={{ flex: 1 }}>
                  <Text size="sm" lineClamp={1}>
                    {p.title}
                    {p.sub_title ? ` - ${p.sub_title}` : ''}
                    {p.is_new ? ' (NEW)' : ''}
                  </Text>
                  {p.description && (
                    <Text size="xs" c="dimmed" lineClamp={2}>
                      {p.description}
                    </Text>
                  )}
                </Stack>
              </Group>
            ))}
            {!previewLoading &&
              (preview.matches?.length || 0) === 0 &&
              (tvgId || title || description) &&
              preview.epg_found !== false && (
                <Text size="xs" c="dimmed">
                  No matching upcoming programs in the next 7 days.
                </Text>
              )}
          </Stack>
        </ScrollArea.Autosize>

        <Group justify="flex-end" gap="xs">
          <Button variant="subtle" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={handleSave} loading={saving} disabled={!canSave}>
            Save rule
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}
