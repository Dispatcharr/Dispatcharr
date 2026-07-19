import { renderHook, act } from '@testing-library/react';
import { describe, it, expect, beforeEach } from 'vitest';
import useWarningsStore from '../warnings';

describe('useWarningsStore', () => {
  beforeEach(() => {
    useWarningsStore.setState({
      suppressedWarnings: {},
      actionPreferences: {},
    });
  });

  it('should initialize with default state', () => {
    const { result } = renderHook(() => useWarningsStore());

    expect(result.current.suppressedWarnings).toEqual({});
    expect(result.current.actionPreferences).toEqual({});
  });

  it('should suppress a warning', () => {
    const { result } = renderHook(() => useWarningsStore());

    act(() => {
      result.current.suppressWarning('deleteStream');
    });

    expect(result.current.suppressedWarnings).toEqual({
      deleteStream: true,
    });
  });

  it('should suppress multiple warnings', () => {
    const { result } = renderHook(() => useWarningsStore());

    act(() => {
      result.current.suppressWarning('deleteStream');
      result.current.suppressWarning('deleteProfile');
    });

    expect(result.current.suppressedWarnings).toEqual({
      deleteStream: true,
      deleteProfile: true,
    });
  });

  it('should suppress warning with explicit true value', () => {
    const { result } = renderHook(() => useWarningsStore());

    act(() => {
      result.current.suppressWarning('deleteStream', true);
    });

    expect(result.current.suppressedWarnings.deleteStream).toBe(true);
  });

  it('should unsuppress a warning with explicit false value', () => {
    const { result } = renderHook(() => useWarningsStore());

    act(() => {
      result.current.suppressWarning('deleteStream');
    });

    expect(result.current.suppressedWarnings.deleteStream).toBe(true);

    act(() => {
      result.current.suppressWarning('deleteStream', false);
    });

    expect(result.current.suppressedWarnings.deleteStream).toBe(false);
  });

  it('should check if warning is suppressed', () => {
    const { result } = renderHook(() => useWarningsStore());

    expect(result.current.isWarningSuppressed('deleteStream')).toBe(false);

    act(() => {
      result.current.suppressWarning('deleteStream');
    });

    expect(result.current.isWarningSuppressed('deleteStream')).toBe(true);
  });

  it('should return false for non-existent warning', () => {
    const { result } = renderHook(() => useWarningsStore());

    expect(result.current.isWarningSuppressed('nonExistentAction')).toBe(false);
  });

  it('should reset all suppressions', () => {
    const { result } = renderHook(() => useWarningsStore());

    act(() => {
      result.current.suppressWarning('deleteStream');
      result.current.suppressWarning('deleteProfile');
      result.current.suppressWarning('deleteUser');
    });

    expect(result.current.suppressedWarnings).toEqual({
      deleteStream: true,
      deleteProfile: true,
      deleteUser: true,
    });

    act(() => {
      result.current.resetSuppressions();
    });

    expect(result.current.suppressedWarnings).toEqual({});
  });

  it('should maintain other suppressions when adding new one', () => {
    const { result } = renderHook(() => useWarningsStore());

    act(() => {
      result.current.suppressWarning('deleteStream');
      result.current.suppressWarning('deleteProfile');
    });

    expect(result.current.suppressedWarnings).toEqual({
      deleteStream: true,
      deleteProfile: true,
    });
  });

  it('should handle resetting when already empty', () => {
    const { result } = renderHook(() => useWarningsStore());

    expect(result.current.suppressedWarnings).toEqual({});

    act(() => {
      result.current.resetSuppressions();
    });

    expect(result.current.suppressedWarnings).toEqual({});
  });

  it('should handle checking suppression after unsuppressing', () => {
    const { result } = renderHook(() => useWarningsStore());

    act(() => {
      result.current.suppressWarning('deleteStream', true);
    });

    expect(result.current.isWarningSuppressed('deleteStream')).toBe(true);

    act(() => {
      result.current.suppressWarning('deleteStream', false);
    });

    expect(result.current.isWarningSuppressed('deleteStream')).toBe(false);
  });

  it('should preserve other warnings when unsuppressing one', () => {
    const { result } = renderHook(() => useWarningsStore());

    act(() => {
      result.current.suppressWarning('deleteStream');
      result.current.suppressWarning('deleteProfile');
    });

    act(() => {
      result.current.suppressWarning('deleteStream', false);
    });

    expect(result.current.suppressedWarnings).toEqual({
      deleteStream: false,
      deleteProfile: true,
    });
  });

  it('should handle suppressing same warning multiple times', () => {
    const { result } = renderHook(() => useWarningsStore());

    act(() => {
      result.current.suppressWarning('deleteStream');
      result.current.suppressWarning('deleteStream');
    });

    expect(result.current.suppressedWarnings).toEqual({
      deleteStream: true,
    });
  });

  it('should handle different action keys independently', () => {
    const { result } = renderHook(() => useWarningsStore());

    act(() => {
      result.current.suppressWarning('action1');
      result.current.suppressWarning('action2', false);
    });

    expect(result.current.isWarningSuppressed('action1')).toBe(true);
    expect(result.current.isWarningSuppressed('action2')).toBe(false);
    expect(result.current.isWarningSuppressed('action3')).toBe(false);
  });

  it('should store and read action preferences', () => {
    const { result } = renderHook(() => useWarningsStore());

    expect(result.current.getActionPreference('delete-channel', 'stopStream')).toBe(
      false
    );

    act(() => {
      result.current.setActionPreference('delete-channel', { stopStream: true });
    });

    expect(
      result.current.getActionPreference('delete-channel', 'stopStream')
    ).toBe(true);
    expect(
      result.current.getActionPreference('delete-channels', 'stopStream', false)
    ).toBe(false);
  });

  it('should clear action preferences when resetSuppressions is called', () => {
    const { result } = renderHook(() => useWarningsStore());

    act(() => {
      result.current.suppressWarning('delete-channel');
      result.current.setActionPreference('delete-channel', { stopStream: true });
      result.current.resetSuppressions();
    });

    expect(result.current.suppressedWarnings).toEqual({});
    expect(result.current.actionPreferences).toEqual({});
  });
});
