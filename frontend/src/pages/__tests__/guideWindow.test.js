import { describe, it, expect } from 'vitest';
import {
  CHUNK_MS,
  INITIAL_FORWARD_MS,
  INITIAL_LOOKBACK_MS,
  KEEP_MS,
  MS_PER_HOUR,
  PREFETCH_MARGIN_MS,
  appendWindowParams,
  cullProgramsToKeepWindow,
  getInitialWindow,
  mergeProgramsById,
  nextChunkBackward,
  nextChunkForward,
  shouldPrefetchBackward,
  shouldPrefetchForward,
  timelineOriginScrollDeltaPx,
  toIsoParam,
  viewportTimeRange,
} from '../../utils/guideWindow';
import { PX_PER_MS } from '../../utils/guideUtils';

describe('guideWindow', () => {
  const nowMs = Date.parse('2024-01-15T12:00:00.000Z');

  describe('getInitialWindow', () => {
    it('returns now−1h through now+24h', () => {
      const win = getInitialWindow(nowMs);
      expect(win.startMs).toBe(nowMs - INITIAL_LOOKBACK_MS);
      expect(win.endMs).toBe(nowMs + INITIAL_FORWARD_MS);
      expect(win.endMs - win.startMs).toBe(
        INITIAL_LOOKBACK_MS + INITIAL_FORWARD_MS
      );
    });
  });

  describe('toIsoParam / appendWindowParams', () => {
    it('writes ISO start and end query params', () => {
      const params = new URLSearchParams();
      appendWindowParams(params, nowMs, nowMs + CHUNK_MS);
      expect(params.get('start')).toBe(toIsoParam(nowMs));
      expect(params.get('end')).toBe(toIsoParam(nowMs + CHUNK_MS));
      expect(params.get('start')).toMatch(/2024-01-15T12:00:00\.000Z/);
    });
  });

  describe('nextChunkForward / nextChunkBackward', () => {
    it('abuts 12h chunks on the loaded edges', () => {
      const end = nowMs + INITIAL_FORWARD_MS;
      const fwd = nextChunkForward(end);
      expect(fwd.startMs).toBe(end);
      expect(fwd.endMs).toBe(end + CHUNK_MS);

      const start = nowMs - INITIAL_LOOKBACK_MS;
      const back = nextChunkBackward(start);
      expect(back.endMs).toBe(start);
      expect(back.startMs).toBe(start - CHUNK_MS);
    });
  });

  describe('shouldPrefetchForward / shouldPrefetchBackward', () => {
    it('triggers when the viewport is within the margin of an edge', () => {
      const loadedEnd = nowMs + INITIAL_FORWARD_MS;
      expect(shouldPrefetchForward(loadedEnd - PREFETCH_MARGIN_MS, loadedEnd)).toBe(
        true
      );
      expect(
        shouldPrefetchForward(loadedEnd - PREFETCH_MARGIN_MS - 1, loadedEnd)
      ).toBe(false);

      const loadedStart = nowMs - INITIAL_LOOKBACK_MS;
      expect(
        shouldPrefetchBackward(loadedStart + PREFETCH_MARGIN_MS, loadedStart, 0)
      ).toBe(true);
      expect(
        shouldPrefetchBackward(
          loadedStart + PREFETCH_MARGIN_MS + 1,
          loadedStart,
          0
        )
      ).toBe(false);
      // Not at the left scroll edge: do not prefetch even if time-margin matches.
      expect(
        shouldPrefetchBackward(loadedStart, loadedStart, 100)
      ).toBe(false);
    });
  });

  describe('viewportTimeRange', () => {
    it('maps scroll pixels to time using PX_PER_MS', () => {
      const timelineStart = nowMs;
      const scrollLeft = PX_PER_MS * MS_PER_HOUR;
      const widthPx = PX_PER_MS * 2 * MS_PER_HOUR;
      const view = viewportTimeRange(timelineStart, scrollLeft, widthPx);
      expect(view.startMs).toBeCloseTo(timelineStart + MS_PER_HOUR);
      expect(view.endMs).toBeCloseTo(timelineStart + 3 * MS_PER_HOUR);
      expect(view.centerMs).toBeCloseTo(timelineStart + 2 * MS_PER_HOUR);
    });
  });

  describe('mergeProgramsById', () => {
    it('merges by id with incoming winning', () => {
      const existing = [
        { id: 'a', title: 'Old A' },
        { id: 'b', title: 'B' },
      ];
      const incoming = [
        { id: 'a', title: 'New A' },
        { id: 'c', title: 'C' },
      ];
      const merged = mergeProgramsById(existing, incoming);
      expect(merged).toHaveLength(3);
      expect(merged.find((p) => p.id === 'a').title).toBe('New A');
      expect(merged.find((p) => p.id === 'c').title).toBe('C');
    });

    it('handles empty sides', () => {
      expect(mergeProgramsById([], [{ id: 1 }])).toEqual([{ id: 1 }]);
      expect(mergeProgramsById([{ id: 1 }], [])).toEqual([{ id: 1 }]);
    });
  });

  describe('timelineOriginScrollDeltaPx', () => {
    it('increases scrollLeft when the timeline grows left', () => {
      const delta = timelineOriginScrollDeltaPx(1000, 0, 2);
      expect(delta).toBe(2000);
    });

    it('decreases scrollLeft when the left bound is culled forward', () => {
      const delta = timelineOriginScrollDeltaPx(0, 1000, 2);
      expect(delta).toBe(-2000);
    });
  });

  describe('cullProgramsToKeepWindow', () => {
    const toMs = (v) =>
      typeof v === 'number' ? v : Date.parse(String(v));

    it('is a no-op when span is within KEEP_MS', () => {
      const programs = [
        { id: 1, startMs: nowMs, endMs: nowMs + 1000 },
      ];
      const result = cullProgramsToKeepWindow(
        programs,
        nowMs,
        KEEP_MS,
        nowMs,
        nowMs + KEEP_MS,
        toMs
      );
      expect(result.culled).toBe(false);
      expect(result.programs).toBe(programs);
    });

    it('drops programs entirely outside the keep window', () => {
      const loadedStart = nowMs;
      const loadedEnd = nowMs + KEEP_MS + CHUNK_MS;
      const programs = [
        {
          id: 'old',
          startMs: loadedStart,
          endMs: loadedStart + 1000,
        },
        {
          id: 'mid',
          startMs: loadedEnd - KEEP_MS / 2,
          endMs: loadedEnd - KEEP_MS / 2 + 1000,
        },
        {
          id: 'new',
          startMs: loadedEnd - 1000,
          endMs: loadedEnd,
        },
      ];
      const center = loadedEnd - 1000;
      const result = cullProgramsToKeepWindow(
        programs,
        center,
        KEEP_MS,
        loadedStart,
        loadedEnd,
        toMs
      );
      expect(result.culled).toBe(true);
      expect(result.programs.map((p) => p.id)).not.toContain('old');
      expect(result.programs.map((p) => p.id)).toContain('mid');
      expect(result.programs.map((p) => p.id)).toContain('new');
      expect(result.rangeEndMs - result.rangeStartMs).toBe(KEEP_MS);
    });
  });
});
