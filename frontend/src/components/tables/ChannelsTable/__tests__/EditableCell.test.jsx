// @vitest-environment jsdom
import { describe, it, expect, beforeEach, vi } from 'vitest';

// Mock the notification utility before importing the module under test
// so the helper picks up the mock.
vi.mock('../../../../utils/notificationUtils.js', () => ({
  showNotification: vi.fn(),
}));

// Mock other heavy dependencies so the import doesn't pull in stores.
vi.mock('../../../../store/channelsTable', () => ({ default: { getState: vi.fn() } }));
vi.mock('../../../../store/logos', () => ({ default: vi.fn() }));
vi.mock('../../../../utils/forms/ChannelUtils.js', () => ({
  requeryChannels: vi.fn(),
  updateChannel: vi.fn(),
}));
vi.mock('../../../../utils/tables/ChannelsTableUtils.js', () => ({
  buildInlinePatch: vi.fn(),
  getEpgOptions: vi.fn(),
  getLogoOptions: vi.fn(),
}));

import { notifyInlineSaveError } from '../EditableCell.jsx';
import { showNotification } from '../../../../utils/notificationUtils.js';

describe('EditableCell.notifyInlineSaveError (F-12 regression guard)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('surfaces a red notification when an inline save fails (the fix)', () => {
    // Regression guard: the previous implementation silently reverted
    // the field on save error with no user feedback. The user could
    // see their input vanish without knowing why. This helper must
    // produce a visible error notification.
    const error = new Error('Bad request');
    notifyInlineSaveError('name', error);

    expect(showNotification).toHaveBeenCalledTimes(1);
    const arg = showNotification.mock.calls[0][0];
    expect(arg.color).toBe('red');
    expect(arg.title).toMatch(/not saved|error/i);
    expect(arg.message).toBeTruthy();
  });

  it('extracts a per-field validator message from a structured DRF response', () => {
    // DRF serializer errors come back as { field: ["error string"] }.
    // The helper must dig into the field-keyed array and surface the
    // first message rather than rendering "[object Object]" or
    // generic fallback.
    const apiError = {
      message: 'Request failed',
      body: {
        channel_number: ['Channel number 0 is below the allowed minimum.'],
      },
    };
    notifyInlineSaveError('channel_number', apiError);

    const arg = showNotification.mock.calls[0][0];
    expect(arg.message).toContain('below the allowed minimum');
  });

  it('extracts a top-level "detail" key when DRF emits a non-field error', () => {
    const apiError = {
      message: 'Request failed',
      body: { detail: 'Channel name exceeds max_length=512' },
    };
    notifyInlineSaveError('name', apiError);

    const arg = showNotification.mock.calls[0][0];
    expect(arg.message).toContain('max_length');
  });

  it('falls back to the error.message when no body shape is available', () => {
    notifyInlineSaveError('name', new Error('Network error'));
    const arg = showNotification.mock.calls[0][0];
    expect(arg.message).toContain('Network error');
  });

  it('uses a generic fallback when nothing useful is on the error', () => {
    notifyInlineSaveError('name', {});
    const arg = showNotification.mock.calls[0][0];
    expect(arg.message).toBeTruthy();
    expect(typeof arg.message).toBe('string');
  });
});
