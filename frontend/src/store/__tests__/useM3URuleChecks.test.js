import { beforeEach, describe, expect, it } from 'vitest';
import useM3URuleChecks from '../useM3URuleChecks.js';

describe('last explicit account rule checks', () => {
  beforeEach(() => useM3URuleChecks.setState({ checks: {} }));
  it('remembers checks independently by account and content scope', () => {
    const store = useM3URuleChecks.getState();
    store.remember('1-group-rules-live', 'first', {
      causes: { 1: {} },
      coveredBy: {},
    });
    store.remember('1-group-rules-movie', 'second', {
      causes: {},
      coveredBy: {},
    });
    expect(
      useM3URuleChecks.getState().checks['1-group-rules-live'].signature
    ).toBe('first');
    expect(
      useM3URuleChecks.getState().checks['1-group-rules-movie'].signature
    ).toBe('second');
    expect(
      useM3URuleChecks.getState().checks['2-group-rules-live']
    ).toBeUndefined();
    store.forget('1-group-rules-live');
    expect(
      useM3URuleChecks.getState().checks['1-group-rules-live']
    ).toBeUndefined();
    expect(
      useM3URuleChecks.getState().checks['1-group-rules-movie']
    ).toBeDefined();
  });
});
