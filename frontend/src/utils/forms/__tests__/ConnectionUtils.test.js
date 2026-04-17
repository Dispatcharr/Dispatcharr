import { describe, it, expect, vi, beforeEach } from 'vitest';
import {
  EVENT_OPTIONS,
  updateConnectIntegration,
  createConnectIntegration,
  setConnectSubscriptions,
  buildConfig,
  buildSubscriptions,
  parseApiError,
} from '../ConnectionUtils.js';

// ── Module mocks ───────────────────────────────────────────────────────────────

vi.mock('../../../api.js', () => ({
  default: {
    updateConnectIntegration: vi.fn(),
    createConnectIntegration: vi.fn(),
    setConnectSubscriptions: vi.fn(),
  },
}));

vi.mock('../../../constants.js', () => ({
  SUBSCRIPTION_EVENTS: {
    channel_added: 'Channel Added',
    channel_removed: 'Channel Removed',
    recording_started: 'Recording Started',
  },
}));

// ── Imports after mocks ────────────────────────────────────────────────────────

import API from '../../../api.js';

// ── Helpers ────────────────────────────────────────────────────────────────────

const makeConnection = (overrides = {}) => ({ id: 'conn-1', ...overrides });

const makeValues = (overrides = {}) => ({
  name: 'Test Integration',
  type: 'webhook',
  enabled: true,
  url: 'https://example.com/hook',
  script_path: '',
  ...overrides,
});

// ──────────────────────────────────────────────────────────────────────────────

describe('ConnectionUtils', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // ── EVENT_OPTIONS ────────────────────────────────────────────────────────────

  describe('EVENT_OPTIONS', () => {
    it('maps SUBSCRIPTION_EVENTS entries to { value, label } objects', () => {
      expect(EVENT_OPTIONS).toEqual([
        { value: 'channel_added', label: 'Channel Added' },
        { value: 'channel_removed', label: 'Channel Removed' },
        { value: 'recording_started', label: 'Recording Started' },
      ]);
    });

    it('has the same length as SUBSCRIPTION_EVENTS', () => {
      expect(EVENT_OPTIONS).toHaveLength(3);
    });
  });

  // ── createConnectIntegration ─────────────────────────────────────────────────

  describe('createConnectIntegration', () => {
    it('calls API.createConnectIntegration with the correct payload', async () => {
      const values = makeValues();
      const config = { url: 'https://example.com/hook' };
      vi.mocked(API.createConnectIntegration).mockResolvedValue({
        id: 'new-1',
      });

      await createConnectIntegration(values, config);

      expect(API.createConnectIntegration).toHaveBeenCalledWith({
        name: 'Test Integration',
        type: 'webhook',
        config,
        enabled: true,
      });
    });

    it('returns the API response', async () => {
      vi.mocked(API.createConnectIntegration).mockResolvedValue({
        id: 'new-1',
      });
      const result = await createConnectIntegration(makeValues(), {});
      expect(result).toEqual({ id: 'new-1' });
    });

    it('propagates API errors', async () => {
      vi.mocked(API.createConnectIntegration).mockRejectedValue(
        new Error('Network error')
      );
      await expect(createConnectIntegration(makeValues(), {})).rejects.toThrow(
        'Network error'
      );
    });
  });

  // ── updateConnectIntegration ─────────────────────────────────────────────────

  describe('updateConnectIntegration', () => {
    it('calls API.updateConnectIntegration with connection.id and correct payload', async () => {
      const connection = makeConnection();
      const values = makeValues();
      const config = { url: 'https://example.com/hook' };
      vi.mocked(API.updateConnectIntegration).mockResolvedValue({
        id: 'conn-1',
      });

      await updateConnectIntegration(connection, values, config);

      expect(API.updateConnectIntegration).toHaveBeenCalledWith('conn-1', {
        name: 'Test Integration',
        type: 'webhook',
        config,
        enabled: true,
      });
    });

    it('returns the API response', async () => {
      vi.mocked(API.updateConnectIntegration).mockResolvedValue({
        id: 'conn-1',
        name: 'Updated',
      });
      const result = await updateConnectIntegration(
        makeConnection(),
        makeValues(),
        {}
      );
      expect(result).toEqual({ id: 'conn-1', name: 'Updated' });
    });

    it('propagates API errors', async () => {
      vi.mocked(API.updateConnectIntegration).mockRejectedValue(
        new Error('Server error')
      );
      await expect(
        updateConnectIntegration(makeConnection(), makeValues(), {})
      ).rejects.toThrow('Server error');
    });
  });

  // ── setConnectSubscriptions ──────────────────────────────────────────────────

  describe('setConnectSubscriptions', () => {
    it('calls API.setConnectSubscriptions with connection.id and subs', async () => {
      const connection = makeConnection();
      const subs = [
        { event: 'channel_added', enabled: true, payload_template: null },
      ];
      vi.mocked(API.setConnectSubscriptions).mockResolvedValue(undefined);

      await setConnectSubscriptions(connection, subs);

      expect(API.setConnectSubscriptions).toHaveBeenCalledWith('conn-1', subs);
    });

    it('propagates API errors', async () => {
      vi.mocked(API.setConnectSubscriptions).mockRejectedValue(
        new Error('Failed')
      );
      await expect(
        setConnectSubscriptions(makeConnection(), [])
      ).rejects.toThrow('Failed');
    });
  });

  // ── buildConfig ──────────────────────────────────────────────────────────────

  describe('buildConfig', () => {
    describe('webhook type', () => {
      it('returns config with url only when no headers are provided', () => {
        const values = makeValues({
          type: 'webhook',
          url: 'https://example.com/hook',
        });
        expect(buildConfig(values, [])).toEqual({
          url: 'https://example.com/hook',
        });
      });

      it('includes headers when non-empty key/value pairs are present', () => {
        const values = makeValues({
          type: 'webhook',
          url: 'https://example.com/hook',
        });
        const headers = [{ key: 'Authorization', value: 'Bearer token' }];
        expect(buildConfig(values, headers)).toEqual({
          url: 'https://example.com/hook',
          headers: { Authorization: 'Bearer token' },
        });
      });

      it('omits headers with blank keys', () => {
        const values = makeValues({
          type: 'webhook',
          url: 'https://example.com/hook',
        });
        const headers = [
          { key: '', value: 'should-be-ignored' },
          { key: '   ', value: 'also-ignored' },
          { key: 'X-Custom', value: 'kept' },
        ];
        expect(buildConfig(values, headers)).toEqual({
          url: 'https://example.com/hook',
          headers: { 'X-Custom': 'kept' },
        });
      });

      it('omits headers property entirely when all keys are blank', () => {
        const values = makeValues({
          type: 'webhook',
          url: 'https://example.com/hook',
        });
        const headers = [{ key: '', value: 'ignored' }];
        const config = buildConfig(values, headers);
        expect(config).not.toHaveProperty('headers');
      });

      it('supports multiple headers', () => {
        const values = makeValues({
          type: 'webhook',
          url: 'https://example.com/hook',
        });
        const headers = [
          { key: 'X-One', value: '1' },
          { key: 'X-Two', value: '2' },
        ];
        expect(buildConfig(values, headers)).toEqual({
          url: 'https://example.com/hook',
          headers: { 'X-One': '1', 'X-Two': '2' },
        });
      });
    });

    describe('script type', () => {
      it('returns config with path from script_path', () => {
        const values = makeValues({
          type: 'script',
          script_path: '/usr/local/bin/notify.sh',
        });
        expect(buildConfig(values, [])).toEqual({
          path: '/usr/local/bin/notify.sh',
        });
      });

      it('ignores headers for script type', () => {
        const values = makeValues({
          type: 'script',
          script_path: '/usr/bin/run.sh',
        });
        const headers = [{ key: 'Authorization', value: 'Bearer token' }];
        const config = buildConfig(values, headers);
        expect(config).not.toHaveProperty('headers');
        expect(config).toEqual({ path: '/usr/bin/run.sh' });
      });
    });
  });

  // ── buildSubscriptions ───────────────────────────────────────────────────────

  describe('buildSubscriptions', () => {
    it('returns an entry for every event in SUBSCRIPTION_EVENTS', () => {
      const result = buildSubscriptions([], {});
      expect(result).toHaveLength(3);
      expect(result.map((s) => s.event)).toEqual([
        'channel_added',
        'channel_removed',
        'recording_started',
      ]);
    });

    it('marks events as enabled when they are in selectedEvents', () => {
      const result = buildSubscriptions(['channel_added'], {});
      const added = result.find((s) => s.event === 'channel_added');
      const removed = result.find((s) => s.event === 'channel_removed');
      expect(added.enabled).toBe(true);
      expect(removed.enabled).toBe(false);
    });

    it('sets payload_template from payloadTemplates when present', () => {
      const templates = { channel_added: '{"key":"{{value}}"}' };
      const result = buildSubscriptions(['channel_added'], templates);
      const added = result.find((s) => s.event === 'channel_added');
      expect(added.payload_template).toBe('{"key":"{{value}}"}');
    });

    it('sets payload_template to null when not in payloadTemplates', () => {
      const result = buildSubscriptions([], {});
      result.forEach((s) => expect(s.payload_template).toBeNull());
    });

    it('sets payload_template to null when value is undefined in payloadTemplates', () => {
      const templates = { channel_added: undefined };
      const result = buildSubscriptions([], templates);
      const added = result.find((s) => s.event === 'channel_added');
      expect(added.payload_template).toBeNull();
    });
  });

  // ── parseApiError ────────────────────────────────────────────────────────────

  describe('parseApiError', () => {
    it('returns message when error has no body', () => {
      const error = { message: 'Network failure' };
      expect(parseApiError(error)).toEqual({
        fieldErrors: {},
        apiError: 'Network failure',
      });
    });

    it('returns "Unknown error" when error has no body and no message', () => {
      expect(parseApiError({})).toEqual({
        fieldErrors: {},
        apiError: 'Unknown error',
      });
    });

    it('returns message when body is a string (not an object)', () => {
      const error = { body: 'Bad Request', message: 'HTTP 400' };
      expect(parseApiError(error)).toEqual({
        fieldErrors: {},
        apiError: 'HTTP 400',
      });
    });

    it('extracts known field errors from body', () => {
      const error = {
        body: { name: 'This field is required.', type: 'Invalid choice.' },
      };
      const { fieldErrors } = parseApiError(error);
      expect(fieldErrors).toEqual({
        name: 'This field is required.',
        type: 'Invalid choice.',
      });
    });

    it('ignores unknown fields in body', () => {
      const error = { body: { unknown_field: 'some error' } };
      const { fieldErrors } = parseApiError(error);
      expect(fieldErrors).toEqual({});
    });

    it('uses non_field_errors as apiError when present', () => {
      const error = { body: { non_field_errors: 'Invalid credentials.' } };
      const { apiError } = parseApiError(error);
      expect(apiError).toBe('Invalid credentials.');
    });

    it('falls back to detail as apiError when non_field_errors is absent', () => {
      const error = { body: { detail: 'Authentication required.' } };
      const { apiError } = parseApiError(error);
      expect(apiError).toBe('Authentication required.');
    });

    it('prefers non_field_errors over detail', () => {
      const error = {
        body: { non_field_errors: 'NF error', detail: 'Detail error' },
      };
      const { apiError } = parseApiError(error);
      expect(apiError).toBe('NF error');
    });

    it('sets apiError to empty string when field errors are present but no non_field_errors', () => {
      const error = { body: { name: 'Required.' } };
      const { apiError } = parseApiError(error);
      expect(apiError).toBe('');
    });

    it('JSON.stringifies body as fallback when no field errors and no non_field_errors', () => {
      const error = { body: { unexpected: 'data' } };
      const { apiError } = parseApiError(error);
      expect(apiError).toBe(JSON.stringify({ unexpected: 'data' }));
    });

    it('handles null error gracefully', () => {
      expect(parseApiError(null)).toEqual({
        fieldErrors: {},
        apiError: 'Unknown error',
      });
    });

    it('handles undefined error gracefully', () => {
      expect(parseApiError(undefined)).toEqual({
        fieldErrors: {},
        apiError: 'Unknown error',
      });
    });
  });
});
