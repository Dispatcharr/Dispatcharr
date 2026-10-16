import { SourceMapConsumer } from 'source-map-js';

// Matches V8 ("at name (url:line:col)") and JSC/Safari ("name@url:line:col")
// stack frames.
const FRAME_RE = /(https?:\/\/[^\s)]+\.js):(\d+):(\d+)/g;

// Module-scoped and shared across calls: a bundle's map never changes for a
// given hashed filename.
const consumerCache = new Map();

async function loadConsumer(scriptUrl) {
  if (consumerCache.has(scriptUrl)) return consumerCache.get(scriptUrl);

  const consumerPromise = fetch(`${scriptUrl}.map`)
    .then((res) => (res.ok ? res.json() : null))
    .then((rawMap) => (rawMap ? new SourceMapConsumer(rawMap) : null))
    .catch(() => null);

  consumerCache.set(scriptUrl, consumerPromise);
  return consumerPromise;
}

// Resolves each minified stack frame in `text` to its original file:line:col.
// Leaves a frame unresolved (rather than throwing) if its map is unavailable.
export async function symbolicateText(text) {
  if (!text) return text;

  const lines = text.split('\n');
  const resolvedLines = [];

  for (const line of lines) {
    resolvedLines.push(line);
    const frames = [...line.matchAll(FRAME_RE)];

    for (const [, scriptUrl, lineNum, colNum] of frames) {
      const consumer = await loadConsumer(scriptUrl);
      if (!consumer) continue;

      const original = consumer.originalPositionFor({
        line: Number(lineNum),
        column: Number(colNum),
      });

      if (original?.source) {
        const source = original.source.replace(/^(\.\.\/)+/, '');
        const location = `${source}:${original.line}:${original.column}`;
        resolvedLines.push(
          original.name
            ? `        at ${original.name} (${location})`
            : `        at ${location}`
        );
      }
    }
  }

  return resolvedLines.join('\n');
}
