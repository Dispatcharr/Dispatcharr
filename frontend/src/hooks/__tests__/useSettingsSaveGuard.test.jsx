import { describe, it, expect } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import useSettingsSaveGuard from '../useSettingsSaveGuard';

describe('useSettingsSaveGuard', () => {
  it('starts with isSavingRef false', () => {
    const { result } = renderHook(() => useSettingsSaveGuard());
    expect(result.current.isSavingRef.current).toBe(false);
  });

  it('runSave sets the ref for the duration of the callback', async () => {
    const { result } = renderHook(() => useSettingsSaveGuard());
    let sawSaving = false;

    await act(async () => {
      await result.current.runSave(async () => {
        sawSaving = result.current.isSavingRef.current;
        return 'ok';
      });
    });

    expect(sawSaving).toBe(true);
    expect(result.current.isSavingRef.current).toBe(false);
  });

  it('runSave clears the ref even when the callback throws', async () => {
    const { result } = renderHook(() => useSettingsSaveGuard());

    await act(async () => {
      await expect(
        result.current.runSave(async () => {
          throw new Error('save failed');
        })
      ).rejects.toThrow('save failed');
    });

    expect(result.current.isSavingRef.current).toBe(false);
  });

  it('runSave returns the callback result', async () => {
    const { result } = renderHook(() => useSettingsSaveGuard());
    let value;

    await act(async () => {
      value = await result.current.runSave(async () => 42);
    });

    expect(value).toBe(42);
  });
});
