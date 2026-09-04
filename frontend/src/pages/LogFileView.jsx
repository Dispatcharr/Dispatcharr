import React, {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import { Link, useParams } from 'react-router-dom';
import {
  Anchor,
  Box,
  Button,
  Group,
  Loader,
  Paper,
  Select,
  Text,
  TextInput,
  Title,
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import API from '../api';
import useBrowserStorage from '../hooks/useBrowserStorage';

const COLORS = {
  error: '#ff6b6b',
  warn: '#ffd43b',
  stamp: '#a1a1aa',
  module: '#8bc4eb',
  level: '#e4e4e7',
};

// Captures the separator so it is not re-invented; [\s\S] because '.' drops \r.
const RECORD_TOKENS =
  /^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}(?: [+-]\d{4})?) (\S+) (\S+)( ?)([\s\S]*)$/;

const LEVEL_RANK = {
  TRACE: 10,
  DEBUG: 10,
  INFO: 20,
  WARNING: 30,
  ERROR: 40,
  CRITICAL: 50,
};

const FIRST_PARTY = new Set([
  'core',
  'dispatcharr',
  'live_proxy',
  'vod_proxy',
  'proxy',
]);

// Anything neither first-party nor a plugin is Services.
const parseSource = (source) => {
  if (source.startsWith('apps.')) {
    const module = source.split('.')[1] || source;
    // apps.plugins is the plugin system itself, not a third-party plugin.
    if (module === 'plugins') return { module: 'plugin_sys', tier: 'plugins' };
    return { module, tier: 'app' };
  }
  if (source.startsWith('plugins.'))
    return { module: source.split('.')[1] || source, tier: 'plugins' };
  // Disk-loaded plugins import as _dispatcharr_plugin_<key>.
  if (source.startsWith('_dispatcharr_plugin_')) {
    const head = source.split('.')[0];
    return { module: head.slice(20) || head, tier: 'plugins' };
  }
  // First-party DB pool code logs under a django namespace.
  if (source.startsWith('django.geventpool'))
    return { module: 'geventpool', tier: 'app' };
  const head = source.split('.')[0] || source;
  return { module: head, tier: FIRST_PARTY.has(head) ? 'app' : 'services' };
};

const STAMP_OFFSET = /^(.*) ([+-])(\d{2})(\d{2})$/;

const displayStamp = (stamp) => {
  const m = STAMP_OFFSET.exec(stamp);
  if (!m) return stamp;
  const minutes = m[4] === '00' ? '' : `:${m[4]}`;
  return `${m[1]} [UTC${m[2]}${Number(m[3])}${minutes}]`;
};

const parseRecord = (line) => {
  const m = RECORD_TOKENS.exec(line);
  if (!m) return null;
  const { module, tier } = parseSource(m[3]);
  return {
    stamp: displayStamp(m[1]),
    level: m[2],
    source: m[3],
    module,
    tier,
    sep: m[4],
    message: m[5],
  };
};

const levelLabel = (level) => {
  if (level === 'CRITICAL') return 'ERROR';
  if (level === 'WARNING') return 'WARN';
  if (level === 'TRACE') return 'DEBUG';
  return level;
};

const severityColor = (level) => {
  if (level === 'ERROR' || level === 'CRITICAL') return COLORS.error;
  if (level === 'WARNING') return COLORS.warn;
  return null;
};

const levelColor = (level) => {
  if (level === 'DEBUG' || level === 'TRACE') return COLORS.stamp;
  return severityColor(level) || COLORS.level;
};

// The bar marks what rises above the floor, not everything severe.
const barColor = (level, minRank) => {
  const color = severityColor(level);
  if (!color) return 'transparent';
  // CRITICAL displays as ERROR, so it answers to ERROR's floor.
  const rank = level === 'CRITICAL' ? LEVEL_RANK.ERROR : LEVEL_RANK[level];
  return rank > minRank ? color : 'transparent';
};

const RECORD_START =
  /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}(?: [+-]\d{4})? /;

const SEARCH_DEBOUNCE_MS = 200;

// Bounds the DOM for low-end TV browsers.
const MAX_RENDER_LINES = 5000;

// How close to the live edge still counts as watching it.
const FOLLOW_SLACK_PX = 50;

const LEVEL_COL_MAX = 12;
const MODULE_COL_MAX = 12;

const REFRESH_OPTIONS = [
  { value: '0', label: 'Manual' },
  { value: '5', label: '5s' },
  { value: '10', label: '10s' },
  { value: '30', label: '30s' },
  { value: '60', label: '1m' },
];

const CATEGORY_OPTIONS = [
  { value: 'all', label: 'All categories' },
  { value: 'app', label: 'App' },
  { value: 'plugins', label: 'Plugins' },
  { value: 'services', label: 'Services' },
];

const LEVEL_OPTIONS = [
  { value: '10', label: 'Debug' },
  { value: '20', label: 'Info' },
  { value: '30', label: 'Warning' },
  { value: '40', label: 'Error' },
];

// Mirrors the collector's continuation rules.
const TRACEBACK_HEAD = 'Traceback';

const classifyLines = (lines) => {
  const entries = [];
  let inTraceback = false;
  for (const line of lines) {
    const record = parseRecord(line);
    if (record) {
      // The collector stamps a traceback header but not its tail.
      inTraceback = record.message.startsWith(TRACEBACK_HEAD);
      entries.push({ line, record, kind: 'record' });
    } else if (RECORD_START.test(line)) {
      inTraceback = false;
      entries.push({ line, record: null, kind: 'standalone' });
    } else if (line.startsWith(TRACEBACK_HEAD)) {
      inTraceback = true;
      entries.push({ line, record: null, kind: 'continuation' });
    } else if (inTraceback || /^[ \t]/.test(line) || line === '') {
      entries.push({ line, record: null, kind: 'continuation' });
    } else {
      entries.push({ line, record: null, kind: 'standalone' });
    }
  }
  return entries;
};

const groupEntries = (entries) => {
  const groups = [];
  for (const entry of entries) {
    if (entry.kind !== 'continuation' || !groups.length) {
      groups.push([entry]);
    } else {
      groups[groups.length - 1].push(entry);
    }
  }
  return groups;
};

const filterEntries = (entries, minRank, category, query) => {
  const out = [];
  for (const group of groupEntries(entries)) {
    const record = group[0].record;
    if (record) {
      const rank = LEVEL_RANK[record.level];
      if (rank !== undefined && rank < minRank) continue;
      if (category !== null && record.tier !== category) continue;
    }
    if (query && !group.some((e) => e.line.toLowerCase().includes(query)))
      continue;
    out.push(...group);
  }
  return out;
};

const renderContinuations = (lines) => {
  const out = [];
  let run = [];
  let blank = null;
  const flush = () => {
    if (!run.length) return;
    // React renders no text node for '', so a lone blank line needs its own '\n'.
    const text = run.join('\n') + (blank ? '\n' : '');
    out.push(
      <div key={out.length} style={blank ? { lineHeight: 0.35 } : undefined}>
        {text}
      </div>
    );
    run = [];
  };
  for (const line of lines) {
    const isBlank = line.trim() === '';
    if (blank !== null && isBlank !== blank) flush();
    blank = isBlank;
    run.push(line);
  }
  flush();
  return out;
};

// whiteSpace and textIndent inherit from the hanging block; reset them here.
const columnStyle = (width) => ({
  display: 'inline-block',
  width: `${width}ch`,
  whiteSpace: 'nowrap',
  textIndent: '0px',
  verticalAlign: 'bottom',
});

const emptyState = (message) => (
  <Text size="sm" c="dimmed" ta="center" py="md">
    {message}
  </Text>
);

const buildBlocks = (entries) => {
  const blocks = [];
  for (const entry of entries) {
    const last = blocks[blocks.length - 1];
    if (entry.record) {
      blocks.push({ record: entry.record, continuations: [] });
    } else if (entry.kind === 'continuation' && last) {
      if (last.record) last.continuations.push(entry.line);
      else last.lines.push(entry.line);
    } else {
      blocks.push({ lines: [entry.line] });
    }
  }
  return blocks;
};

const LogFileViewPage = () => {
  const { name } = useParams();
  const [content, setContent] = useState('');
  const [truncated, setTruncated] = useState(false);
  const [loading, setLoading] = useState(true);
  const [refreshSetting, setRefreshSetting] = useBrowserStorage(
    'log-viewer-refresh-interval',
    0
  );
  // A stored value outside the options would render an empty select.
  const refreshSeconds = REFRESH_OPTIONS.some(
    (option) => option.value === String(refreshSetting)
  )
    ? refreshSetting
    : 0;
  const [newestFirst, setNewestFirst] = useBrowserStorage(
    'log-viewer-newest-first',
    false
  );
  const [minLevelSetting, setMinLevelSetting] = useBrowserStorage(
    'log-viewer-min-level',
    20
  );
  const minLevel = LEVEL_OPTIONS.some(
    (option) => option.value === String(minLevelSetting)
  )
    ? Number(minLevelSetting)
    : 20;
  const [categorySetting, setCategorySetting] = useBrowserStorage(
    'log-viewer-category',
    'all'
  );
  const category =
    categorySetting !== 'all' &&
    CATEGORY_OPTIONS.some((option) => option.value === categorySetting)
      ? categorySetting
      : null;
  // Ephemeral by design: searches are moments, not settings.
  const [search, setSearch] = useState('');
  // The box keeps up with typing; the filter waits for a pause.
  const [query, setQuery] = useState('');
  useEffect(() => {
    const id = setTimeout(
      () => setQuery(search.trim().toLowerCase()),
      SEARCH_DEBOUNCE_MS
    );
    return () => clearTimeout(id);
  }, [search]);
  const [loadError, setLoadError] = useState(false);
  // The whole body arrives before the browser saves anything; say so.
  const [downloading, setDownloading] = useState(false);

  const loadingRef = useRef(false);
  const failuresRef = useRef(0);
  const viewportRef = useRef(null);
  // Open at the live edge, and keep following until the reader scrolls away.
  const followingRef = useRef(true);

  const entries = useMemo(
    () => classifyLines(content ? content.split('\n') : []),
    [content]
  );

  // Widths come from every record; the filtered set would shift on each keystroke.
  const cols = useMemo(() => {
    let stamp = 0;
    let level = 0;
    let module = 0;
    for (const entry of entries) {
      if (!entry.record) continue;
      stamp = Math.max(stamp, entry.record.stamp.length);
      level = Math.max(level, levelLabel(entry.record.level).length);
      module = Math.max(module, entry.record.module.length);
    }
    return {
      stamp,
      // Floored at ERROR's width so the column stays put while tailing.
      level: Math.min(Math.max(level, 5), LEVEL_COL_MAX),
      module: Math.min(module, MODULE_COL_MAX),
    };
  }, [entries]);

  const { blocks, hiddenLines } = useMemo(() => {
    let kept = entries;
    if (minLevel || category !== null || query)
      kept = filterEntries(entries, minLevel, category, query);
    const hidden = Math.max(0, kept.length - MAX_RENDER_LINES);
    if (hidden) kept = kept.slice(hidden);
    // Reversed as blocks, not entries, so continuations stay with their record.
    const built = buildBlocks(kept);
    if (newestFirst) built.reverse();
    return { blocks: built, hiddenLines: hidden };
  }, [entries, newestFirst, minLevel, category, query]);

  // Newest sits at whichever end the order puts it.
  const onViewportScroll = useCallback(() => {
    const el = viewportRef.current;
    if (!el) return;
    followingRef.current = newestFirst
      ? el.scrollTop <= FOLLOW_SLACK_PX
      : el.scrollHeight - el.scrollTop - el.clientHeight <= FOLLOW_SLACK_PX;
  }, [newestFirst]);

  // A refresh replaces the content wholesale, so a fixed scrollTop drifts back
  // through history. Re-pin to the live edge for a reader who was watching it.
  useLayoutEffect(() => {
    const el = viewportRef.current;
    if (!el || !followingRef.current) return;
    el.scrollTop = newestFirst ? 0 : el.scrollHeight;
  }, [blocks, newestFirst]);

  // Wrapped lines and continuations hang under the message column.
  const messageIndent = cols.stamp + cols.level + cols.module + 3;

  const notice =
    hiddenLines > 0
      ? `Showing the last ${MAX_RENDER_LINES.toLocaleString()} lines`
      : truncated
        ? 'Large file — showing the last 5 MB'
        : null;

  const load = useCallback(
    async (showLoading = true, { silent = false } = {}) => {
      loadingRef.current = true;
      if (showLoading) setLoading(true);
      try {
        const response = await API.getLogFile(name, { silent });
        if (response) {
          setContent(response.content);
          setTruncated(response.truncated);
          if (!silent) setLoadError(false);
          return true;
        }
        // Silent polls resolve to undefined on failure.
        if (!silent) setLoadError(true);
        return false;
      } catch {
        // getLogFile has already toasted.
        if (!silent) setLoadError(true);
        return false;
      } finally {
        loadingRef.current = false;
        if (showLoading) setLoading(false);
      }
    },
    [name]
  );

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (!refreshSeconds) return undefined;
    failuresRef.current = 0;
    const id = setInterval(async () => {
      if (document.hidden || loadingRef.current) return;
      const ok = await load(false, { silent: true });
      if (ok) {
        failuresRef.current = 0;
      } else {
        failuresRef.current += 1;
        if (failuresRef.current >= 3) {
          setRefreshSetting(0);
          notifications.show({
            title: 'Auto-refresh paused',
            message:
              'Stopped auto-refresh after repeated errors loading the log.',
            color: 'yellow',
            autoClose: 6000,
          });
        }
      }
    }, refreshSeconds * 1000);
    return () => clearInterval(id);
  }, [refreshSeconds, setRefreshSetting, load]);

  return (
    <Box p="md">
      <Paper
        withBorder
        radius="md"
        p={0}
        style={{
          display: 'flex',
          flexDirection: 'column',
          height: 'calc(100vh - var(--mantine-spacing-md) * 2)',
        }}
      >
        <Box
          style={{
            flex: '0 0 auto',
            borderBottom: '1px solid var(--mantine-color-default-border)',
            padding: 'var(--mantine-spacing-sm)',
          }}
        >
          <Group justify="space-between">
            <Group gap="sm">
              <Anchor component={Link} to="/logs" size="sm">
                ← Logs
              </Anchor>
              <Title order={4}>{name}</Title>
            </Group>
            <Group gap="sm">
              {notice && (
                <Text size="sm" c="yellow">
                  {notice}
                </Text>
              )}
              <TextInput
                size="xs"
                label="Search"
                placeholder="Filter text"
                value={search}
                onChange={(event) => setSearch(event.currentTarget.value)}
                style={{ width: 240 }}
              />
              <Select
                size="xs"
                label="Level"
                value={String(minLevel)}
                onChange={(value) => setMinLevelSetting(parseInt(value))}
                allowDeselect={false}
                data={LEVEL_OPTIONS}
                style={{ width: 110 }}
              />
              <Select
                size="xs"
                label="Category"
                value={category === null ? 'all' : category}
                onChange={(value) => setCategorySetting(value)}
                allowDeselect={false}
                data={CATEGORY_OPTIONS}
                style={{ width: 130 }}
              />
              <Select
                size="xs"
                label="Order"
                value={newestFirst ? 'newest' : 'oldest'}
                onChange={(value) => setNewestFirst(value === 'newest')}
                allowDeselect={false}
                data={[
                  { value: 'newest', label: 'Newest first' },
                  { value: 'oldest', label: 'Newest last' },
                ]}
                style={{ width: 130 }}
              />
              <Select
                size="xs"
                label="Auto Refresh"
                value={refreshSeconds.toString()}
                onChange={(value) => setRefreshSetting(parseInt(value))}
                allowDeselect={false}
                data={REFRESH_OPTIONS}
                style={{ width: 120 }}
              />
              <Button
                size="xs"
                variant="subtle"
                onClick={() => load()}
                loading={loading}
                style={{ marginTop: 'auto' }}
              >
                Refresh
              </Button>
              <Button
                size="xs"
                variant="subtle"
                loading={downloading}
                onClick={async () => {
                  setDownloading(true);
                  try {
                    await API.downloadLogFile(name);
                  } finally {
                    setDownloading(false);
                  }
                }}
                style={{ marginTop: 'auto' }}
              >
                Download
              </Button>
            </Group>
          </Group>
        </Box>

        <Box
          p="sm"
          ref={viewportRef}
          onScroll={onViewportScroll}
          // Without minHeight:0 a flex item will not shrink below its content.
          style={{ flex: '1 1 auto', overflow: 'auto', minHeight: '0px' }}
        >
          {loading && !content ? (
            <Loader />
          ) : !content && loadError ? (
            <Group gap="sm">
              <Text size="sm" c="red">
                Failed to load {name}
              </Text>
              <Button size="xs" variant="subtle" onClick={() => load()}>
                Retry
              </Button>
            </Group>
          ) : (
            <div
              style={{
                margin: 0,
                fontFamily:
                  'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace',
                fontSize: 12,
                lineHeight: 1.45,
                // anywhere breaks unbroken tokens like URLs and SQL dumps.
                whiteSpace: 'pre-wrap',
                overflowWrap: 'anywhere',
              }}
            >
              {!content
                ? emptyState('(empty)')
                : blocks.length
                  ? blocks.map((block, i) => {
                      if (!block.record) {
                        return (
                          <div
                            key={i}
                            // Dimming marks these lines as unowned.
                            style={{
                              borderLeft: '2px solid transparent',
                              paddingLeft: 8,
                              color: COLORS.stamp,
                            }}
                          >
                            {block.lines.join('\n')}
                          </div>
                        );
                      }
                      const mc = severityColor(block.record.level);
                      const bc = barColor(block.record.level, minLevel);
                      return (
                        <div
                          key={i}
                          style={{
                            borderLeft: `2px solid ${bc}`,
                            paddingLeft: `calc(8px + ${messageIndent}ch)`,
                            textIndent: `-${messageIndent}ch`,
                          }}
                        >
                          <span
                            style={{
                              ...columnStyle(cols.stamp),
                              color: COLORS.stamp,
                            }}
                          >
                            {block.record.stamp}
                          </span>{' '}
                          <span
                            style={{
                              ...columnStyle(cols.level),
                              color: levelColor(block.record.level),
                              fontWeight: 500,
                              overflow: 'hidden',
                              textOverflow: 'ellipsis',
                            }}
                            title={block.record.level}
                          >
                            {levelLabel(block.record.level)}
                          </span>{' '}
                          <span
                            style={{
                              ...columnStyle(cols.module),
                              color: COLORS.module,
                              overflow: 'hidden',
                              textOverflow: 'ellipsis',
                            }}
                            title={block.record.source}
                          >
                            {block.record.module}
                          </span>
                          {block.record.sep}
                          <span style={mc ? { color: mc } : undefined}>
                            {block.record.message}
                          </span>
                          {block.continuations.length > 0 && (
                            <div
                              style={{
                                textIndent: '0px',
                                color: mc || undefined,
                              }}
                            >
                              {renderContinuations(block.continuations)}
                            </div>
                          )}
                        </div>
                      );
                    })
                  : emptyState('(no records match the filters)')}
            </div>
          )}
        </Box>
      </Paper>
    </Box>
  );
};

export default LogFileViewPage;
