import React, {
  useCallback,
  useEffect,
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
  Title,
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import API from '../api';
import useBrowserStorage from '../hooks/useBrowserStorage';

const COLORS = {
  error: '#ff6b6b', // red
  warn: '#ffd43b', // yellow
  auth: '#51cf66', // green — real login/auth events
  plugin: '#74c0fc', // blue — third-party plugin code
  stamp: '#a1a1aa', // mid grey — readable against the dark ground, still recessive
  module: '#8bc4eb', // soft blue — the module token
  level: '#e4e4e7', // bright neutral — INFO and unknown levels stand apart from the stamp
};

// The collector guarantees the canonical grammar "stamp [offset] LEVEL source rest"; every rule keys off those tokens.
// The separator is captured so an absent one is not invented on re-emit, and the body uses [\s\S] because JS '.' excludes \r, which real messages can carry.
const RECORD_TOKENS =
  /^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}(?: [+-]\d{4})?) (\S+) (\S+)( ?)([\s\S]*)$/;

const LEVEL_RANK = {
  // The viewer bundles TRACE into DEBUG: same rank, same display name.
  TRACE: 10,
  DEBUG: 10,
  INFO: 20,
  WARNING: 30,
  ERROR: 40,
  CRITICAL: 50,
};

// First-party logger names that live outside apps.*: core, the dispatcharr package, and the proxy subsystem's explicit logger names.
const FIRST_PARTY = new Set([
  'core',
  'dispatcharr',
  'live_proxy',
  'vod_proxy',
  'proxy',
]);

// One definition of "module" and the closed category it lives in: the segment
// that names the component. Everything that is not Dispatcharr's own code or a
// plugin — native daemons and third-party Python alike — is Services, which
// also keeps the category vocabulary closed.
const parseSource = (source) => {
  if (source.startsWith('apps.')) {
    const module = source.split('.')[1] || source;
    // apps.plugins is the plugin system's own infrastructure: it files under the
    // Plugins category, renamed so a plugins token always means third-party code.
    if (module === 'plugins') return { module: 'plugin_sys', tier: 'plugins' };
    return { module, tier: 'app' };
  }
  if (source.startsWith('plugins.'))
    return { module: source.slice(8) || source, tier: 'plugins' };
  const head = source.split('.')[0] || source;
  return { module: head, tier: FIRST_PARTY.has(head) ? 'app' : 'services' };
};

const parseRecord = (line) => {
  const m = RECORD_TOKENS.exec(line);
  if (!m) return null;
  const { module, tier } = parseSource(m[3]);
  return {
    stamp: m[1],
    level: m[2],
    source: m[3],
    module,
    tier,
    sep: m[4],
    message: m[5],
  };
};

// Display names compress the level column: CRITICAL joins ERROR, WARNING shortens to WARN, and TRACE joins DEBUG. The raw token stays on hover.
const levelLabel = (level) => {
  if (level === 'CRITICAL') return 'ERROR';
  if (level === 'WARNING') return 'WARN';
  if (level === 'TRACE') return 'DEBUG';
  return level;
};

// Severity lives on the level token and the record bar; the message keeps category colour only.
const levelColor = (level) => {
  if (level === 'ERROR' || level === 'CRITICAL') return COLORS.error;
  if (level === 'WARNING') return COLORS.warn;
  // DEBUG/TRACE share the stamp grey; their medium weight keeps them legible as levels.
  if (level === 'DEBUG' || level === 'TRACE') return COLORS.stamp;
  return COLORS.level;
};

// The bar spans a record block so a traceback reads as one owned unit; quiet levels stay bare.
const barColor = (level) => {
  if (level === 'ERROR' || level === 'CRITICAL') return COLORS.error;
  if (level === 'WARNING') return COLORS.warn;
  return 'transparent';
};

// Message colouring by category; first match wins.
const MESSAGE_RULES = [
  {
    label: 'login/auth',
    color: COLORS.auth,
    // Real auth events only: apps.accounts / jwt_ws_auth sources or django.request 401/403 — but not the routine token-refresh/notification 401 polling, which is benign warn noise.
    test: (r) =>
      r.source.startsWith('apps.accounts.') ||
      r.source === 'dispatcharr.jwt_ws_auth' ||
      (r.source === 'django.request' &&
        /^(Unauthorized|Forbidden)\b(?!:\s*\/api\/(?:accounts\/token\/refresh|core\/notifications))/.test(
          r.message
        )),
  },
  {
    label: 'plugin',
    color: COLORS.plugin,
    // The plugins.<key> source only — apps.plugins.* infrastructure stays default.
    test: (r) => r.source.startsWith('plugins.'),
  },
];

const messageColor = (record) => {
  const rule = MESSAGE_RULES.find((r) => r.test(record));
  return rule ? rule.color : null;
};

// Legend display order (default text first), independent of rule precedence.
const LEGEND = [
  { label: 'text', color: null },
  { label: 'error', color: COLORS.error },
  { label: 'warn', color: COLORS.warn },
  { label: 'login/auth', color: COLORS.auth },
  { label: 'plugin', color: COLORS.plugin },
];

// A record starts with a canonical stamp; anything else is a continuation
// (multi-line messages, traceback frames) and inherits the record's colour.
const RECORD_START =
  /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}(?: [+-]\d{4})? /;

// Cap on rendered lines: every record block emits a handful of nodes, so bound the DOM for low-end TV browsers.
const MAX_RENDER_LINES = 5000;

// Column caps keep one outsized token from pushing every message off-screen; the full value stays on hover.
const LEVEL_COL_MAX = 12;
const MODULE_COL_MAX = 20;

const REFRESH_OPTIONS = [
  { value: '0', label: 'Manual' },
  { value: '5', label: '5s' },
  { value: '10', label: '10s' },
  { value: '30', label: '30s' },
  { value: '60', label: '1m' },
];

// The category vocabulary is closed by construction — unknown loggers land in Services — so this list is static.
const CATEGORY_OPTIONS = [
  { value: 'all', label: 'All categories' },
  { value: 'app', label: 'App' },
  { value: 'plugins', label: 'Plugins' },
  { value: 'services', label: 'Services' },
];

// Selecting a level shows it and everything above; Debug is the floor and includes the app's TRACE records.
const LEVEL_OPTIONS = [
  { value: '10', label: 'Debug' },
  { value: '20', label: 'Info' },
  { value: '30', label: 'Warning' },
  { value: '40', label: 'Error' },
];

// One tokenize-and-classify pass per content change; filters and ordering reuse it.
// Mirrors the collector's continuation rules: an open traceback claims its tail,
// indented and blank lines join the record above, and any other column-0 line
// stands alone (the collector's unstamped pass-through records) so a filter can
// never swallow it under an unrelated record.
const classifyLines = (lines) => {
  const entries = [];
  let inTraceback = false;
  for (const line of lines) {
    const record = parseRecord(line);
    if (record) {
      inTraceback = false;
      entries.push({ line, record, kind: 'record' });
    } else if (RECORD_START.test(line)) {
      inTraceback = false;
      entries.push({ line, record: null, kind: 'standalone' });
    } else if (line.startsWith('Traceback')) {
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

// Records below the level floor or outside the chosen category/module (null = no filter) hide with their continuations; standalone lines and unknown levels always show.
const filterEntries = (entries, minRank, category, module) => {
  const out = [];
  let suppress = false;
  for (const entry of entries) {
    if (entry.record) {
      const rank = LEVEL_RANK[entry.record.level];
      suppress =
        (rank !== undefined && rank < minRank) ||
        (category !== null && entry.record.tier !== category) ||
        (module !== null && entry.record.module !== module);
    } else if (entry.kind === 'standalone') {
      suppress = false;
    }
    if (!suppress) out.push(entry);
  }
  return out;
};

// Newest first flips whole records, so a multi-line record keeps its own line order.
const reverseEntries = (entries) => {
  const groups = [];
  for (const entry of entries) {
    if (entry.kind !== 'continuation' || !groups.length) {
      groups.push([entry]);
    } else {
      groups[groups.length - 1].push(entry);
    }
  }
  return groups.reverse().flat();
};

// Group entries into record blocks (header + its continuations) so each record renders as one bordered unit; continuations stay one joined text node.
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

// Raw log display, radarr-style: monospace, no wrapping, page scroll.
const LogFileViewPage = () => {
  const { name } = useParams();
  const [content, setContent] = useState('');
  const [truncated, setTruncated] = useState(false);
  const [loading, setLoading] = useState(true);
  const [refreshSetting, setRefreshSetting] = useBrowserStorage(
    'log-viewer-refresh-interval',
    0
  );
  // A stored value outside the options falls back to Manual rather than an empty select.
  const refreshSeconds = REFRESH_OPTIONS.some(
    (option) => option.value === String(refreshSetting)
  )
    ? refreshSetting
    : 0;
  const [newestFirst, setNewestFirst] = useBrowserStorage(
    'log-viewer-newest-first',
    true
  );
  const [minLevelSetting, setMinLevelSetting] = useBrowserStorage(
    'log-viewer-min-level',
    20
  );
  // A stored value outside the options falls back to the Info default rather than an empty select.
  const minLevel = LEVEL_OPTIONS.some(
    (option) => option.value === String(minLevelSetting)
  )
    ? Number(minLevelSetting)
    : 20;
  const [categorySetting, setCategorySetting] = useBrowserStorage(
    'log-viewer-category',
    'all'
  );
  // The category vocabulary is closed, so an unknown stored value simply means no filter.
  const category =
    categorySetting !== 'all' &&
    CATEGORY_OPTIONS.some((option) => option.value === categorySetting)
      ? categorySetting
      : null;
  const [moduleSetting, setModuleSetting] = useBrowserStorage(
    'log-viewer-module',
    'all'
  );
  // Stored selections carry an 'm:' prefix so a module literally named "all" can never collide with the sentinel; anything else means no filter.
  const moduleFilter =
    typeof moduleSetting === 'string' && moduleSetting.startsWith('m:')
      ? moduleSetting.slice(2)
      : null;
  const [loadError, setLoadError] = useState(false);

  // Guards the auto-refresh loop: skip a tick mid-flight, and count failures so a persistently-failing tail switches itself off.
  const loadingRef = useRef(false);
  const failuresRef = useRef(0);

  const entries = useMemo(
    () => classifyLines(content ? content.split('\n') : []),
    [content]
  );

  // The module list comes from the loaded tail itself; the vocabulary is open-ended. Tiers drive the category cross-filtering of the module options.
  const { modules, moduleTiers } = useMemo(() => {
    const tiers = new Map();
    for (const entry of entries) {
      if (entry.record && !tiers.has(entry.record.module))
        tiers.set(entry.record.module, entry.record.tier);
    }
    return { modules: [...tiers.keys()].sort(), moduleTiers: tiers };
  }, [entries]);

  // The module control only exists in debug mode, and its filter only applies while the control is visible — no hidden active state.
  const debugMode = minLevel < 20;
  const effectiveModule = debugMode ? moduleFilter : null;

  // Render only the last MAX_RENDER_LINES; hiddenLines drives the "showing the last N lines" notice.
  const { blocks, cols, hiddenLines } = useMemo(() => {
    let kept = entries;
    if (minLevel || category !== null || effectiveModule !== null)
      kept = filterEntries(entries, minLevel, category, effectiveModule);
    const hidden = Math.max(0, kept.length - MAX_RENDER_LINES);
    if (hidden) kept = kept.slice(hidden);
    const built = buildBlocks(newestFirst ? reverseEntries(kept) : kept);
    // Column widths come from the visible records themselves so every row aligns.
    let stamp = 0;
    let level = 0;
    let module = 0;
    for (const block of built) {
      if (!block.record) continue;
      stamp = Math.max(stamp, block.record.stamp.length);
      level = Math.max(level, levelLabel(block.record.level).length);
      module = Math.max(module, block.record.module.length);
    }
    return {
      blocks: built,
      cols: {
        stamp,
        // Floored at ERROR's display width so the column stays put while tailing.
        level: Math.min(Math.max(level, 5), LEVEL_COL_MAX),
        module: Math.min(module, MODULE_COL_MAX),
      },
      hiddenLines: hidden,
    };
  }, [entries, newestFirst, minLevel, category, effectiveModule]);

  // One notice: line-cap wins over the byte-truncation banner since it states what's actually on screen.
  const notice =
    hiddenLines > 0
      ? `Showing the last ${MAX_RENDER_LINES.toLocaleString()} lines`
      : truncated
        ? 'Large file — showing the last 5 MB'
        : null;

  // showLoading=false skips the spinner flash on silent polls (which also suppress getLogFile's toast); returns success/failure.
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
        // Silent polls resolve to undefined on failure (no toast, no throw).
        if (!silent) setLoadError(true);
        return false;
      } catch {
        // Non-silent failures land here: getLogFile has already toasted.
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

  // Optional tail: silent polling interval, skipped while hidden/mid-load, gives up after repeated failures.
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
      <Group justify="space-between" mb="sm">
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
            onChange={(value) => {
              setCategorySetting(value);
              // A category that excludes the selected module visibly resets it rather than silently emptying the view.
              if (
                value !== 'all' &&
                moduleFilter !== null &&
                moduleTiers.get(moduleFilter) !== value
              )
                setModuleSetting('all');
            }}
            allowDeselect={false}
            data={CATEGORY_OPTIONS}
            style={{ width: 130 }}
          />
          {debugMode && (
            <Select
              size="xs"
              label="Module"
              value={moduleFilter === null ? 'all' : `m:${moduleFilter}`}
              onChange={(value) => setModuleSetting(value)}
              allowDeselect={false}
              searchable
              maxDropdownHeight={300}
              data={[
                { value: 'all', label: 'All modules' },
                // The active selection stays listed even when the current tail lacks it, so the filter never silently disengages or re-engages; options outside the active category are disabled.
                ...(moduleFilter !== null && !modules.includes(moduleFilter)
                  ? [moduleFilter]
                  : []
                )
                  .concat(modules)
                  .sort()
                  .map((m) => ({
                    value: `m:${m}`,
                    label: m,
                    disabled:
                      category !== null && moduleTiers.get(m) !== category,
                  })),
              ]}
              style={{ width: 150 }}
            />
          )}
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
            onClick={() => API.downloadLogFile(name)}
            style={{ marginTop: 'auto' }}
          >
            Download
          </Button>
        </Group>
      </Group>

      <Paper withBorder radius="md" p="sm" style={{ overflowX: 'auto' }}>
        <Group gap="md" mb="xs" wrap="wrap">
          {LEGEND.map((item) => (
            <Text
              key={item.label}
              size="xs"
              span
              ff="monospace"
              style={item.color ? { color: item.color } : undefined}
            >
              {item.label}
            </Text>
          ))}
        </Group>
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
              whiteSpace: 'pre',
            }}
          >
            {!content
              ? '(empty)'
              : blocks.length
                ? blocks.map((block, i) => {
                    if (!block.record) {
                      return (
                        <div
                          key={i}
                          style={{
                            borderLeft: '3px solid transparent',
                            paddingLeft: 8,
                          }}
                        >
                          {block.lines.join('\n')}
                        </div>
                      );
                    }
                    const mc = messageColor(block.record);
                    const bc = barColor(block.record.level);
                    return (
                      <div
                        key={i}
                        style={{
                          borderLeft: `3px solid ${bc}`,
                          paddingLeft: 8,
                        }}
                      >
                        <span
                          style={{
                            color: COLORS.stamp,
                            display: 'inline-block',
                            width: `${cols.stamp}ch`,
                            verticalAlign: 'bottom',
                          }}
                        >
                          {block.record.stamp}
                        </span>{' '}
                        <span
                          style={{
                            color: levelColor(block.record.level),
                            fontWeight: 500,
                            display: 'inline-block',
                            width: `${cols.level}ch`,
                            overflow: 'hidden',
                            textOverflow: 'ellipsis',
                            verticalAlign: 'bottom',
                          }}
                          title={block.record.level}
                        >
                          {levelLabel(block.record.level)}
                        </span>{' '}
                        <span
                          style={{
                            color: COLORS.module,
                            display: 'inline-block',
                            width: `${cols.module}ch`,
                            overflow: 'hidden',
                            textOverflow: 'ellipsis',
                            verticalAlign: 'bottom',
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
                              paddingLeft: `${
                                cols.stamp + cols.level + cols.module + 3
                              }ch`,
                              color: mc || undefined,
                            }}
                          >
                            {block.continuations.join('\n')}
                          </div>
                        )}
                      </div>
                    );
                  })
                : '(no records match the filters)'}
          </div>
        )}
      </Paper>
    </Box>
  );
};

export default LogFileViewPage;
