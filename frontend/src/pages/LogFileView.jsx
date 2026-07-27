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
  Switch,
  Text,
  Title,
} from '@mantine/core';
import { Download, RefreshCcw } from 'lucide-react';
import { notifications } from '@mantine/notifications';
import API from '../api';

const COLORS = {
  error: '#ff6b6b', // red
  warn: '#ffd43b', // yellow
  auth: '#51cf66', // green — real login/auth events
  plugin: '#74c0fc', // blue — third-party plugin code
};

// Line colouring by log category; first match wins, and auth outranks warn since 401/403 lines log at WARNING.
const LINE_RULES = [
  {
    label: 'error',
    color: COLORS.error,
    // Anchor the level keywords to the level field so a message body mentioning "ERROR" (e.g. "state to ERROR in Redis") doesn't redden an INFO line; Traceback/Exception stay content-matched for stack dumps.
    test: (line) =>
      /^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}[.,]\d+\s+(ERROR|CRITICAL|FATAL)\b|Traceback|Exception/.test(
        line
      ),
  },
  {
    label: 'login/auth',
    color: COLORS.auth,
    // Real auth events only: apps.accounts / jwt_ws_auth loggers or django.request 401/403 — but not the routine token-refresh/notification 401 polling, which is benign warn noise.
    test: (line) =>
      /^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}[.,]\d+\s+\w+\s+(apps\.accounts\.|dispatcharr\.jwt_ws_auth\b|django\.request\s+(Unauthorized|Forbidden)\b(?!:\s*\/api\/(?:accounts\/token\/refresh|core\/notifications)))/.test(
        line
      ),
  },
  {
    label: 'warn',
    color: COLORS.warn,
    test: (line) => /\bWARN(ING)?\b/.test(line),
  },
  {
    label: 'plugin',
    color: COLORS.plugin,
    // Match the plugins.<key> logger-name field, not the word "plugin" — apps.plugins.* infrastructure stays default.
    test: (line) =>
      /^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}[.,]\d+\s+\w+\s+plugins\./.test(
        line
      ),
  },
];

// Legend display order (default text first), independent of rule precedence.
const LEGEND = [
  { label: 'text', color: null },
  { label: 'error', color: COLORS.error },
  { label: 'warn', color: COLORS.warn },
  { label: 'login/auth', color: COLORS.auth },
  { label: 'plugin', color: COLORS.plugin },
];

// A record starts with a timestamp; anything else is a continuation line
// (multi-line messages, traceback frames) and inherits the record's colour.
const RECORD_START = /^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}/;

// Cap on rendered lines: a mixed-severity tail can defeat the run-length grouping (one span per line), so bound the DOM for low-end TV browsers.
const MAX_RENDER_LINES = 5000;

// Group consecutive same-colour lines into one span each, so a 5 MB file renders a few hundred nodes, not one per line.
const colorizeLines = (lines) => {
  const chunks = [];
  let current = null;
  let recordColor = null;
  let seenRecord = false;
  for (const line of lines) {
    let color;
    if (RECORD_START.test(line)) {
      const rule = LINE_RULES.find((r) => r.test(line));
      color = rule ? rule.color : null;
      recordColor = color;
      seenRecord = true;
    } else if (seenRecord) {
      color = recordColor;
    } else {
      const rule = LINE_RULES.find((r) => r.test(line));
      color = rule ? rule.color : null;
    }
    if (current && current.color === color) {
      current.text += `\n${line}`;
    } else {
      current = { color, text: line };
      chunks.push(current);
    }
  }
  return chunks;
};

// Raw log display, radarr-style: monospace, no wrapping, page scroll.
const LogFileViewPage = () => {
  const { name } = useParams();
  const [content, setContent] = useState('');
  const [truncated, setTruncated] = useState(false);
  const [loading, setLoading] = useState(true);
  const [autoRefresh, setAutoRefresh] = useState(false);
  const [loadError, setLoadError] = useState(false);

  // Guards the auto-refresh loop: skip a tick mid-flight, and count failures so a persistently-failing tail switches itself off.
  const loadingRef = useRef(false);
  const failuresRef = useRef(0);

  // Render only the last MAX_RENDER_LINES; hiddenLines drives the "showing the last N lines" notice.
  const { chunks, hiddenLines } = useMemo(() => {
    const all = content ? content.split('\n') : [];
    const hidden = Math.max(0, all.length - MAX_RENDER_LINES);
    return { chunks: colorizeLines(hidden ? all.slice(hidden) : all), hiddenLines: hidden };
  }, [content]);

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
    if (!autoRefresh) return undefined;
    failuresRef.current = 0;
    const id = setInterval(async () => {
      if (document.hidden || loadingRef.current) return;
      const ok = await load(false, { silent: true });
      if (ok) {
        failuresRef.current = 0;
      } else {
        failuresRef.current += 1;
        if (failuresRef.current >= 3) {
          setAutoRefresh(false);
          notifications.show({
            title: 'Auto-refresh paused',
            message: 'Stopped auto-refresh after repeated errors loading the log.',
            color: 'yellow',
            autoClose: 6000,
          });
        }
      }
    }, 5000);
    return () => clearInterval(id);
  }, [autoRefresh, load]);

  return (
    <Box p="md">
      <Group justify="space-between" mb="sm">
        <Group gap="sm">
          <Anchor component={Link} to="/logs" size="sm">
            ← Log Files
          </Anchor>
          <Title order={4}>{name}</Title>
        </Group>
        <Group gap="sm">
          {notice && (
            <Text size="sm" c="yellow">
              {notice}
            </Text>
          )}
          <Switch
            size="xs"
            label="Auto-refresh"
            checked={autoRefresh}
            onChange={(e) => setAutoRefresh(e.currentTarget.checked)}
          />
          <Button
            size="xs"
            variant="default"
            leftSection={<RefreshCcw size={14} />}
            onClick={() => load()}
            loading={loading}
          >
            Refresh
          </Button>
          <Button
            size="xs"
            variant="default"
            leftSection={<Download size={14} />}
            onClick={() => API.downloadLogFile(name)}
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
            <Button size="xs" variant="default" onClick={() => load()}>
              Retry
            </Button>
          </Group>
        ) : (
          <pre
            style={{
              margin: 0,
              fontFamily:
                'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace',
              fontSize: 12,
              lineHeight: 1.45,
              whiteSpace: 'pre',
            }}
          >
            {content
              ? chunks.map((chunk, i) => (
                  <span
                    key={i}
                    style={chunk.color ? { color: chunk.color } : undefined}
                  >
                    {i < chunks.length - 1 ? `${chunk.text}\n` : chunk.text}
                  </span>
                ))
              : '(empty)'}
          </pre>
        )}
      </Paper>
    </Box>
  );
};

export default LogFileViewPage;
