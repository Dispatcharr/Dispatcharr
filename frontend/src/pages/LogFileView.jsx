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
  TextInput,
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
  // Plugins loaded from disk import as _dispatcharr_plugin_<key>, so getLogger(__name__) inside a plugin wears that head.
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

// The file keeps the machine-parseable "+1200" for external tooling; the viewer spells it out.
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
    // Third-party plugin code only — plugins.<key> by convention or the loader's _dispatcharr_plugin_<key> import name; apps.plugins.* infrastructure stays default.
    test: (r) =>
      r.source.startsWith('plugins.') ||
      r.source.startsWith('_dispatcharr_plugin_'),
  },
];

const messageColor = (record) => {
  const rule = MESSAGE_RULES.find((r) => r.test(record));
  return rule ? rule.color : null;
};

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

// Group a record with its continuations (standalones stand alone) so filters and ordering treat a multi-line record as one unit.
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

// Records below the level floor or outside the chosen category/module (null = no filter) hide with their continuations; standalone lines and unknown levels always show. The text query narrows every group, matching any line of a record block.
const filterEntries = (entries, minRank, category, module, query) => {
  const out = [];
  for (const group of groupEntries(entries)) {
    const record = group[0].record;
    if (record) {
      const rank = LEVEL_RANK[record.level];
      if (rank !== undefined && rank < minRank) continue;
      if (category !== null && record.tier !== category) continue;
      if (module !== null && record.module !== module) continue;
    }
    if (query && !group.some((e) => e.line.toLowerCase().includes(query)))
      continue;
    out.push(...group);
  }
  return out;
};

// Newest first flips whole records, so a multi-line record keeps its own line order.
const reverseEntries = (entries) => groupEntries(entries).reverse().flat();

// Blank continuation runs render at reduced height: the bytes stay in the DOM (and copy), only the vertical gap tightens.
const renderContinuations = (lines) => {
  const out = [];
  let run = [];
  let blank = null;
  const flush = () => {
    if (!run.length) return;
    out.push(
      <div key={out.length} style={blank ? { lineHeight: 0.35 } : undefined}>
        {run.join('\n')}
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

// Group entries into record blocks (header + its continuations) so each record renders as one bordered unit.
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
    false
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
  // The text filter is deliberately ephemeral — searches are moments, not settings.
  const [search, setSearch] = useState('');
  const query = search.trim().toLowerCase();
  const [loadError, setLoadError] = useState(false);

  // Guards the auto-refresh loop: skip a tick mid-flight, and count failures so a persistently-failing tail switches itself off.
  const loadingRef = useRef(false);
  const failuresRef = useRef(0);

  const entries = useMemo(
    () => classifyLines(content ? content.split('\n') : []),
    [content]
  );

  // The module list comes from the loaded tail itself; the vocabulary is open-ended. A module name can span tiers (a plugin keyed like a daemon), so the map holds every tier seen.
  const { modules, moduleTiers } = useMemo(() => {
    const tiers = new Map();
    for (const entry of entries) {
      if (!entry.record) continue;
      const seen = tiers.get(entry.record.module);
      if (seen) seen.add(entry.record.tier);
      else tiers.set(entry.record.module, new Set([entry.record.tier]));
    }
    return { modules: [...tiers.keys()].sort(), moduleTiers: tiers };
  }, [entries]);

  // The module control only exists in debug mode, and its filter only applies while the control is visible — no hidden active state.
  const debugMode = minLevel < 20;
  const effectiveModule = debugMode ? moduleFilter : null;

  // Render only the last MAX_RENDER_LINES; hiddenLines drives the "showing the last N lines" notice.
  const { blocks, cols, hiddenLines } = useMemo(() => {
    let kept = entries;
    if (minLevel || category !== null || effectiveModule !== null || query)
      kept = filterEntries(entries, minLevel, category, effectiveModule, query);
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
  }, [entries, newestFirst, minLevel, category, effectiveModule, query]);

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
          <TextInput
            size="xs"
            label="Search"
            placeholder="Filter text"
            value={search}
            onChange={(event) => setSearch(event.currentTarget.value)}
            style={{ width: 180 }}
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
            onChange={(value) => {
              setCategorySetting(value);
              // Reset only a provably incompatible selection, and only while the Module control is visible: a module of unknown tier stays engaged — the per-record filter already keeps wrong rows out.
              const tiers =
                moduleFilter === null ? null : moduleTiers.get(moduleFilter);
              if (value !== 'all' && debugMode && tiers && !tiers.has(value))
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
                    // Grey out only when every one of the module's known tiers is excluded; ghosts stay selectable.
                    disabled:
                      category !== null &&
                      moduleTiers.has(m) &&
                      !moduleTiers.get(m).has(category),
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
                            {renderContinuations(block.continuations)}
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
