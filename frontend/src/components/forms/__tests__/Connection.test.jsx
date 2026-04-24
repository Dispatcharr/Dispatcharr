import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import ConnectionForm from '../Connection';
import { useForm } from '@mantine/form';
import * as ConnectionUtils from '../../../utils/forms/ConnectionUtils.js';

// ── Constants mock ─────────────────────────────────────────────────────────────
vi.mock('../../../constants', () => ({
  SUBSCRIPTION_EVENTS: {
    channel_added: 'Channel Added',
    channel_removed: 'Channel Removed',
    recording_started: 'Recording Started',
  },
}));

// ── ConnectionUtils mock ───────────────────────────────────────────────────────
vi.mock('../../../utils/forms/ConnectionUtils.js', () => ({
  EVENT_OPTIONS: [
    { value: 'channel_added', label: 'Channel Added' },
    { value: 'channel_removed', label: 'Channel Removed' },
    { value: 'recording_started', label: 'Recording Started' },
  ],
  buildConfig: vi.fn(),
  buildSubscriptions: vi.fn(),
  createConnectIntegration: vi.fn(),
  updateConnectIntegration: vi.fn(),
  setConnectSubscriptions: vi.fn(),
  parseApiError: vi.fn(),
}));

// ── Mantine form mock ──────────────────────────────────────────────────────────
vi.mock('@mantine/form', () => ({
  isNotEmpty: vi.fn(() => (value) => (value ? null : 'Required')),
  useForm: vi.fn(),
}));

// ── Mantine core mock ──────────────────────────────────────────────────────────
vi.mock('@mantine/core', () => ({
  Accordion: ({ children }) => <div data-testid="accordion">{children}</div>,
  AccordionControl: ({ children }) => <div>{children}</div>,
  AccordionItem: ({ children }) => <div>{children}</div>,
  AccordionPanel: ({ children }) => <div>{children}</div>,
  Alert: ({ children, color, title }) => (
    <div data-testid="alert" data-color={color}>
      {title && <div data-testid="alert-title">{title}</div>}
      {children}
    </div>
  ),
  Box: ({ children }) => <div>{children}</div>,
  Button: ({ children, onClick, type, disabled, loading, color, variant }) => (
    <button
      data-testid={`button-${typeof children === 'string' ? children.toLowerCase().replace(/\s+/g, '-') : 'btn'}`}
      type={type}
      onClick={onClick}
      disabled={disabled || loading}
      data-color={color}
      data-variant={variant}
      data-loading={loading}
    >
      {children}
    </button>
  ),
  Checkbox: ({ label, checked, onChange }) => (
    <input
      type="checkbox"
      aria-label={label}
      checked={checked ?? false}
      onChange={onChange}
      data-testid={`checkbox-${label}`}
    />
  ),
  Flex: ({ children }) => <div>{children}</div>,
  Group: ({ children }) => <div>{children}</div>,
  Modal: ({ children, opened, onClose, title }) =>
    opened ? (
      <div data-testid="modal">
        <div data-testid="modal-title">{title}</div>
        <button data-testid="modal-close" onClick={onClose}>
          ×
        </button>
        {children}
      </div>
    ) : null,
  Select: ({ label, value, onChange, data, disabled }) => (
    <select
      aria-label={label}
      value={value ?? ''}
      onChange={(e) => onChange?.(e.target.value)}
      disabled={disabled}
      data-testid={`select-${label?.toLowerCase().replace(/\s+/g, '-')}`}
    >
      {(data ?? []).map((opt) => (
        <option key={opt.value ?? opt} value={opt.value ?? opt}>
          {opt.label ?? opt}
        </option>
      ))}
    </select>
  ),
  SimpleGrid: ({ children }) => <div>{children}</div>,
  Stack: ({ children }) => <div>{children}</div>,
  Tabs: ({ children, value }) => (
    <div data-testid="tabs" data-active={value}>
      {typeof children === 'function' ? children() : children}
    </div>
  ),
  TabsList: ({ children }) => <div data-testid="tabs-list">{children}</div>,
  TabsPanel: ({ children, value }) => (
    <div data-testid={`tabs-panel-${value}`}>{children}</div>
  ),
  TabsTab: ({ children, value, onClick }) => (
    <button data-testid={`tab-${value}`} onClick={onClick} role="tab">
      {children}
    </button>
  ),
  Text: ({ children }) => <span>{children}</span>,
  Textarea: ({ label, value, onChange, placeholder }) => (
    <textarea
      aria-label={label}
      value={value ?? ''}
      onChange={onChange}
      placeholder={placeholder}
      data-testid={`textarea-${label?.toLowerCase().replace(/\s+/g, '-')}`}
    />
  ),
  TextInput: ({ label, value, onChange, error, disabled, placeholder }) => (
    <div>
      <input
        aria-label={label}
        value={value ?? ''}
        onChange={onChange}
        disabled={disabled}
        placeholder={placeholder}
        data-testid={`input-${label?.toLowerCase().replace(/\s+/g, '-')}`}
      />
      {error && (
        <span
          data-testid={`error-${label?.toLowerCase().replace(/\s+/g, '-')}`}
        >
          {error}
        </span>
      )}
    </div>
  ),
}));

// ── Helpers ────────────────────────────────────────────────────────────────────

const makeConnection = (overrides = {}) => ({
  id: 1,
  name: 'My Webhook',
  type: 'webhook',
  enabled: true,
  config: {
    url: 'https://example.com/hook',
    headers: { 'X-Token': 'abc123' },
  },
  subscriptions: [
    { event: 'channel_added', enabled: true, payload_template: null },
    {
      event: 'recording_started',
      enabled: true,
      payload_template: '{"id": "{{id}}"}',
    },
  ],
  ...overrides,
});

const makeScriptConnection = (overrides = {}) =>
  makeConnection({
    type: 'script',
    config: { path: '/usr/local/bin/notify.sh' },
    ...overrides,
  });

/**
 * Builds a minimal useForm mock.
 * `onSubmit(handler)` returns an event-handler that calls handler with
 * form values when the <form> submits.
 */
const makeFormMock = (initialValues = {}) => {
  const values = {
    name: '',
    type: 'webhook',
    url: '',
    script_path: '',
    enabled: true,
    ...initialValues,
  };

  return {
    values,
    getValues: vi.fn(() => values),
    setValues: vi.fn((newVals) => Object.assign(values, newVals)),
    reset: vi.fn(),
    key: vi.fn((k) => k),
    getInputProps: vi.fn((field) => ({
      value: values[field] ?? '',
      onChange: vi.fn((e) => {
        values[field] = e?.target?.value ?? e;
      }),
      error: null,
    })),
    onSubmit: vi.fn((handler) => (e) => {
      e?.preventDefault?.();
      handler(values);
    }),
    setErrors: vi.fn(),
  };
};

const renderForm = (props = {}) => {
  const defaults = { isOpen: true, onClose: vi.fn(), connection: null };
  return render(<ConnectionForm {...defaults} {...props} />);
};

// ──────────────────────────────────────────────────────────────────────────────
// Tests
// ──────────────────────────────────────────────────────────────────────────────

describe('ConnectionForm', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(ConnectionUtils.createConnectIntegration).mockResolvedValue({
      id: 99,
    });
    vi.mocked(ConnectionUtils.updateConnectIntegration).mockResolvedValue(
      undefined
    );
    vi.mocked(ConnectionUtils.setConnectSubscriptions).mockResolvedValue(
      undefined
    );
    vi.mocked(ConnectionUtils.buildConfig).mockReturnValue({
      url: 'https://x.com',
    });
    vi.mocked(ConnectionUtils.buildSubscriptions).mockReturnValue([]);
    vi.mocked(ConnectionUtils.parseApiError).mockReturnValue({
      fieldErrors: {},
      apiError: '',
    });
  });

  // ── Visibility ─────────────────────────────────────────────────────────────

  describe('visibility', () => {
    it('renders nothing when isOpen is false', () => {
      vi.mocked(useForm).mockReturnValue(makeFormMock());
      renderForm({ isOpen: false });
      expect(screen.queryByTestId('modal')).not.toBeInTheDocument();
    });

    it('renders the modal when isOpen is true', () => {
      vi.mocked(useForm).mockReturnValue(makeFormMock());
      renderForm({ isOpen: true });
      expect(screen.getByTestId('modal')).toBeInTheDocument();
    });

    it('renders "Connection" as the modal title', () => {
      vi.mocked(useForm).mockReturnValue(makeFormMock());
      renderForm();
      expect(screen.getByTestId('modal-title')).toHaveTextContent('Connection');
    });
  });

  // ── New connection ─────────────────────────────────────────────────────────

  describe('new connection', () => {
    it('resets form when connection is null', () => {
      const form = makeFormMock();
      vi.mocked(useForm).mockReturnValue(form);
      renderForm({ connection: null });
      expect(form.reset).toHaveBeenCalled();
    });

    it('calls createConnectIntegration on submit', async () => {
      const form = makeFormMock({
        name: 'New Hook',
        type: 'webhook',
        url: 'https://x.com',
      });
      vi.mocked(useForm).mockReturnValue(form);

      renderForm({ connection: null });

      fireEvent.submit(screen.getByTestId('modal').querySelector('form'));

      await waitFor(() => {
        expect(ConnectionUtils.createConnectIntegration).toHaveBeenCalledWith(
          expect.objectContaining({ name: 'New Hook', type: 'webhook' }),
          expect.objectContaining({ url: 'https://x.com' })
        );
      });
    });

    it('does not call updateConnectIntegration when creating', async () => {
      const form = makeFormMock({
        name: 'New Hook',
        type: 'webhook',
        url: 'https://x.com',
      });
      vi.mocked(useForm).mockReturnValue(form);

      renderForm({ connection: null });

      fireEvent.submit(screen.getByTestId('modal').querySelector('form'));

      await waitFor(() => {
        expect(ConnectionUtils.createConnectIntegration).toHaveBeenCalled();
      });
      expect(ConnectionUtils.updateConnectIntegration).not.toHaveBeenCalled();
    });

    it('calls setConnectSubscriptions with newly created connection', async () => {
      const created = { id: 99, name: 'New Hook' };
      vi.mocked(ConnectionUtils.createConnectIntegration).mockResolvedValue(
        created
      );

      const form = makeFormMock({
        name: 'New Hook',
        type: 'webhook',
        url: 'https://x.com',
      });
      vi.mocked(useForm).mockReturnValue(form);

      renderForm({ connection: null });
      fireEvent.submit(screen.getByTestId('modal').querySelector('form'));

      await waitFor(() => {
        expect(ConnectionUtils.setConnectSubscriptions).toHaveBeenCalledWith(
          created,
          expect.any(Array)
        );
      });
    });

    it('calls onClose after successful create', async () => {
      const form = makeFormMock({
        name: 'New Hook',
        type: 'webhook',
        url: 'https://x.com',
      });
      vi.mocked(useForm).mockReturnValue(form);

      const onClose = vi.fn();
      renderForm({ connection: null, onClose });
      fireEvent.submit(screen.getByTestId('modal').querySelector('form'));

      await waitFor(() => {
        expect(onClose).toHaveBeenCalled();
      });
    });
  });

  // ── Edit existing connection ───────────────────────────────────────────────

  describe('editing an existing connection', () => {
    it('calls form.setValues with connection data on mount', () => {
      const connection = makeConnection();
      const form = makeFormMock();
      vi.mocked(useForm).mockReturnValue(form);

      renderForm({ connection });

      expect(form.setValues).toHaveBeenCalledWith(
        expect.objectContaining({
          name: 'My Webhook',
          type: 'webhook',
          url: 'https://example.com/hook',
          enabled: true,
        })
      );
    });

    it('calls updateConnectIntegration on submit', async () => {
      const connection = makeConnection();
      const form = makeFormMock({
        name: 'My Webhook',
        type: 'webhook',
        url: 'https://example.com/hook',
      });
      vi.mocked(useForm).mockReturnValue(form);

      renderForm({ connection });
      fireEvent.submit(screen.getByTestId('modal').querySelector('form'));

      await waitFor(() => {
        expect(ConnectionUtils.updateConnectIntegration).toHaveBeenCalledWith(
          connection,
          expect.objectContaining({ name: 'My Webhook' }),
          expect.any(Object)
        );
      });
    });

    it('does not call createConnectIntegration when editing', async () => {
      const connection = makeConnection();
      const form = makeFormMock({
        name: 'My Webhook',
        type: 'webhook',
        url: 'https://example.com/hook',
      });
      vi.mocked(useForm).mockReturnValue(form);

      renderForm({ connection });
      fireEvent.submit(screen.getByTestId('modal').querySelector('form'));

      await waitFor(() => {
        expect(ConnectionUtils.updateConnectIntegration).toHaveBeenCalled();
      });
      expect(ConnectionUtils.createConnectIntegration).not.toHaveBeenCalled();
    });

    it('calls setConnectSubscriptions with existing connection on update', async () => {
      const connection = makeConnection();
      const form = makeFormMock({
        name: 'My Webhook',
        type: 'webhook',
        url: 'https://example.com/hook',
      });
      vi.mocked(useForm).mockReturnValue(form);

      renderForm({ connection });
      fireEvent.submit(screen.getByTestId('modal').querySelector('form'));

      await waitFor(() => {
        expect(ConnectionUtils.setConnectSubscriptions).toHaveBeenCalledWith(
          connection,
          expect.any(Array)
        );
      });
    });

    it('calls onClose after successful update', async () => {
      const connection = makeConnection();
      const form = makeFormMock({
        name: 'My Webhook',
        type: 'webhook',
        url: 'https://example.com/hook',
      });
      vi.mocked(useForm).mockReturnValue(form);

      const onClose = vi.fn();
      renderForm({ connection, onClose });
      fireEvent.submit(screen.getByTestId('modal').querySelector('form'));

      await waitFor(() => {
        expect(onClose).toHaveBeenCalled();
      });
    });

    it('populates subscriptions from connection.subscriptions', () => {
      const connection = makeConnection();
      const form = makeFormMock();
      vi.mocked(useForm).mockReturnValue(form);

      renderForm({ connection });

      // channel_added and recording_started are enabled in makeConnection()
      expect(screen.getByTestId('checkbox-Channel Added')).toBeChecked();
      expect(screen.getByTestId('checkbox-Recording Started')).toBeChecked();
      expect(screen.getByTestId('checkbox-Channel Removed')).not.toBeChecked();
    });

    it('populates headers from connection.config.headers', () => {
      const connection = makeConnection();
      const form = makeFormMock();
      vi.mocked(useForm).mockReturnValue(form);

      renderForm({ connection });

      // The header key 'X-Token' should be rendered in an input
      expect(screen.getByDisplayValue('X-Token')).toBeInTheDocument();
      expect(screen.getByDisplayValue('abc123')).toBeInTheDocument();
    });

    it('initializes payloadTemplates from subscriptions', () => {
      const connection = makeConnection();
      const form = makeFormMock();
      vi.mocked(useForm).mockReturnValue(form);

      renderForm({ connection });

      // The recording_started payload template textarea should contain the template
      expect(screen.getByDisplayValue('{"id": "{{id}}"}')).toBeInTheDocument();
    });
  });

  // ── Script connection ──────────────────────────────────────────────────────

  describe('script connection', () => {
    it('builds config with path for script type', async () => {
      const form = makeFormMock({
        name: 'My Script',
        type: 'script',
        script_path: '/usr/local/bin/notify.sh',
      });
      vi.mocked(useForm).mockReturnValue(form);
      vi.mocked(ConnectionUtils.buildConfig).mockReturnValue({
        path: '/usr/local/bin/notify.sh',
      });

      renderForm({ connection: null });
      fireEvent.submit(screen.getByTestId('modal').querySelector('form'));

      await waitFor(() => {
        expect(ConnectionUtils.createConnectIntegration).toHaveBeenCalledWith(
          expect.any(Object),
          expect.objectContaining({ path: '/usr/local/bin/notify.sh' })
        );
      });
    });

    it('sets script_path from existing script connection', () => {
      const connection = makeScriptConnection();
      const form = makeFormMock();
      vi.mocked(useForm).mockReturnValue(form);

      renderForm({ connection });

      expect(form.setValues).toHaveBeenCalledWith(
        expect.objectContaining({
          type: 'script',
          script_path: '/usr/local/bin/notify.sh',
        })
      );
    });
  });

  // ── Webhook config ─────────────────────────────────────────────────────────

  describe('webhook config', () => {
    it('builds config with url for webhook type', async () => {
      const form = makeFormMock({
        name: 'Hook',
        type: 'webhook',
        url: 'https://example.com/webhook',
      });
      vi.mocked(useForm).mockReturnValue(form);
      vi.mocked(ConnectionUtils.buildConfig).mockReturnValue({
        url: 'https://example.com/webhook',
      });

      renderForm({ connection: null });
      fireEvent.submit(screen.getByTestId('modal').querySelector('form'));

      await waitFor(() => {
        expect(ConnectionUtils.createConnectIntegration).toHaveBeenCalledWith(
          expect.any(Object),
          expect.objectContaining({ url: 'https://example.com/webhook' })
        );
      });
    });

    it('includes headers in webhook config when header rows are filled', async () => {
      const connection = makeConnection();
      const form = makeFormMock({
        name: 'My Webhook',
        type: 'webhook',
        url: 'https://example.com/hook',
      });
      vi.mocked(useForm).mockReturnValue(form);
      vi.mocked(ConnectionUtils.buildConfig).mockReturnValue({
        url: 'https://example.com/hook',
        headers: { 'X-Token': 'abc123' },
      });

      renderForm({ connection });
      fireEvent.submit(screen.getByTestId('modal').querySelector('form'));

      await waitFor(() => {
        expect(ConnectionUtils.updateConnectIntegration).toHaveBeenCalledWith(
          expect.any(Object),
          expect.any(Object),
          expect.objectContaining({ headers: { 'X-Token': 'abc123' } })
        );
      });
    });

    it('omits headers from webhook config when all header rows are empty', async () => {
      const connection = makeConnection({
        config: { url: 'https://example.com/hook', headers: {} },
      });
      const form = makeFormMock({
        name: 'My Webhook',
        type: 'webhook',
        url: 'https://example.com/hook',
      });
      vi.mocked(useForm).mockReturnValue(form);

      renderForm({ connection });
      fireEvent.submit(screen.getByTestId('modal').querySelector('form'));

      await waitFor(() => {
        expect(ConnectionUtils.updateConnectIntegration).toHaveBeenCalledWith(
          expect.any(Object),
          expect.any(Object),
          expect.not.objectContaining({ headers: expect.anything() })
        );
      });
    });
  });

  // ── Subscriptions ──────────────────────────────────────────────────────────

  describe('subscriptions', () => {
    it('passes subscription list with enabled flags to setConnectSubscriptions', async () => {
      const form = makeFormMock({
        name: 'Hook',
        type: 'webhook',
        url: 'https://x.com',
      });
      vi.mocked(useForm).mockReturnValue(form);
      vi.mocked(ConnectionUtils.buildSubscriptions).mockReturnValue([
        { event: 'channel_added', enabled: true, payload_template: null },
        { event: 'channel_removed', enabled: false, payload_template: null },
        {
          event: 'recording_started',
          enabled: true,
          payload_template: '{"id": "{{id}}"}',
        },
      ]);

      renderForm({ connection: null });

      // Toggle channel_added on
      fireEvent.click(screen.getByTestId('checkbox-Channel Added'));
      fireEvent.submit(screen.getByTestId('modal').querySelector('form'));

      await waitFor(() => {
        expect(ConnectionUtils.setConnectSubscriptions).toHaveBeenCalledWith(
          expect.any(Object),
          expect.arrayContaining([
            expect.objectContaining({ event: 'channel_added', enabled: true }),
            expect.objectContaining({
              event: 'channel_removed',
              enabled: false,
            }),
            expect.objectContaining({
              event: 'recording_started',
              enabled: true,
            }),
          ])
        );
      });
    });

    it('toggles event off when checkbox is clicked twice', async () => {
      const connection = makeConnection();
      const form = makeFormMock({
        name: 'Hook',
        type: 'webhook',
        url: 'https://x.com',
      });
      vi.mocked(useForm).mockReturnValue(form);
      vi.mocked(ConnectionUtils.buildSubscriptions).mockReturnValue([
        { event: 'channel_added', enabled: false, payload_template: null },
        { event: 'channel_removed', enabled: false, payload_template: null },
        {
          event: 'recording_started',
          enabled: true,
          payload_template: '{"id": "{{id}}"}',
        },
      ]);

      renderForm({ connection });

      // channel_added starts checked — click to uncheck
      fireEvent.click(screen.getByTestId('checkbox-Channel Added'));
      fireEvent.submit(screen.getByTestId('modal').querySelector('form'));

      await waitFor(() => {
        expect(ConnectionUtils.setConnectSubscriptions).toHaveBeenCalledWith(
          expect.any(Object),
          expect.arrayContaining([
            expect.objectContaining({ event: 'channel_added', enabled: false }),
            expect.objectContaining({
              event: 'channel_removed',
              enabled: false,
            }),
            expect.objectContaining({
              event: 'recording_started',
              enabled: true,
            }),
          ])
        );
      });
    });

    it('includes payload_template in subscription when set', async () => {
      const connection = makeConnection();
      const form = makeFormMock({
        name: 'Hook',
        type: 'webhook',
        url: 'https://x.com',
      });
      vi.mocked(useForm).mockReturnValue(form);
      vi.mocked(ConnectionUtils.buildSubscriptions).mockReturnValue([
        {
          event: 'recording_started',
          enabled: true,
          payload_template: '{"id": "{{id}}"}',
        },
      ]);

      renderForm({ connection });
      fireEvent.submit(screen.getByTestId('modal').querySelector('form'));

      await waitFor(() => {
        const subs = vi.mocked(ConnectionUtils.setConnectSubscriptions).mock
          .calls[0][1];
        const recordingSub = subs.find((s) => s.event === 'recording_started');
        expect(recordingSub).toBeDefined();
        expect(recordingSub.payload_template).toBe('{"id": "{{id}}"}');
      });
    });

    it('sends null payload_template when not set for an event', async () => {
      const form = makeFormMock({
        name: 'Hook',
        type: 'webhook',
        url: 'https://x.com',
      });
      vi.mocked(useForm).mockReturnValue(form);

      renderForm({ connection: null });
      fireEvent.submit(screen.getByTestId('modal').querySelector('form'));

      await waitFor(() => {
        const subs = vi.mocked(ConnectionUtils.setConnectSubscriptions).mock
          .calls[0][1];
        subs.forEach((s) => expect(s.payload_template).toBeNull());
      });
    });
  });

  // ── Error handling ─────────────────────────────────────────────────────────

  describe('error handling', () => {
    it('shows error alert when createConnectIntegration throws', async () => {
      vi.mocked(ConnectionUtils.createConnectIntegration).mockRejectedValue(
        new Error('Server error')
      );
      const form = makeFormMock({
        name: 'Hook',
        type: 'webhook',
        url: 'https://x.com',
      });
      vi.mocked(useForm).mockReturnValue(form);
      vi.mocked(ConnectionUtils.parseApiError).mockReturnValue({
        fieldErrors: {},
        apiError: 'Server error',
      });

      renderForm({ connection: null });
      fireEvent.submit(screen.getByTestId('modal').querySelector('form'));

      await waitFor(() => {
        expect(screen.getByText('Server error')).toBeInTheDocument();
      });
    });

    it('shows error alert when updateConnectIntegration throws', async () => {
      vi.mocked(ConnectionUtils.updateConnectIntegration).mockRejectedValue(
        new Error('Update failed')
      );
      const connection = makeConnection();
      const form = makeFormMock({
        name: 'My Webhook',
        type: 'webhook',
        url: 'https://x.com',
      });
      vi.mocked(useForm).mockReturnValue(form);
      vi.mocked(ConnectionUtils.parseApiError).mockReturnValue({
        fieldErrors: {},
        apiError: 'Update failed',
      });

      renderForm({ connection });
      fireEvent.submit(screen.getByTestId('modal').querySelector('form'));

      await waitFor(() => {
        expect(screen.getByText('Update failed')).toBeInTheDocument();
      });
    });

    it('does not call onClose when submission throws', async () => {
      vi.mocked(ConnectionUtils.createConnectIntegration).mockRejectedValue(
        new Error('fail')
      );
      const form = makeFormMock({
        name: 'Hook',
        type: 'webhook',
        url: 'https://x.com',
      });
      vi.mocked(useForm).mockReturnValue(form);
      vi.mocked(ConnectionUtils.parseApiError).mockReturnValue({
        fieldErrors: {},
        apiError: 'fail',
      });

      const onClose = vi.fn();
      renderForm({ connection: null, onClose });
      fireEvent.submit(screen.getByTestId('modal').querySelector('form'));

      await waitFor(() => {
        expect(screen.getByText('fail')).toBeInTheDocument();
      });
      expect(onClose).not.toHaveBeenCalled();
    });

    it('clears previous API error on new submit attempt', async () => {
      vi.mocked(ConnectionUtils.createConnectIntegration)
        .mockRejectedValueOnce(new Error('First error'))
        .mockResolvedValueOnce({ id: 99 });

      const form = makeFormMock({
        name: 'Hook',
        type: 'webhook',
        url: 'https://x.com',
      });
      vi.mocked(useForm).mockReturnValue(form);
      vi.mocked(ConnectionUtils.parseApiError).mockReturnValue({
        fieldErrors: {},
        apiError: 'First error',
      });

      renderForm({ connection: null });

      // First submit — fails
      fireEvent.submit(screen.getByTestId('modal').querySelector('form'));
      await waitFor(() =>
        expect(screen.queryByText('First error')).toBeInTheDocument()
      );

      // Second submit — succeeds
      fireEvent.submit(screen.getByTestId('modal').querySelector('form'));
      await waitFor(() =>
        expect(screen.queryByText('First error')).not.toBeInTheDocument()
      );
    });
  });

  // ── Modal close ────────────────────────────────────────────────────────────

  describe('modal close', () => {
    it('calls onClose when the modal X button is clicked', () => {
      vi.mocked(useForm).mockReturnValue(makeFormMock());
      const onClose = vi.fn();
      renderForm({ onClose });

      fireEvent.click(screen.getByTestId('modal-close'));

      expect(onClose).toHaveBeenCalled();
    });

    it('clears apiError when handleClose is called', async () => {
      vi.mocked(ConnectionUtils.createConnectIntegration).mockRejectedValue(
        new Error('fail')
      );
      const form = makeFormMock({
        name: 'Hook',
        type: 'webhook',
        url: 'https://x.com',
      });
      vi.mocked(useForm).mockReturnValue(form);
      vi.mocked(ConnectionUtils.parseApiError).mockReturnValue({
        fieldErrors: {},
        apiError: 'fail',
      });

      renderForm({ connection: null });
      fireEvent.submit(screen.getByTestId('modal').querySelector('form'));

      await waitFor(() =>
        expect(screen.queryByText('fail')).toBeInTheDocument()
      );

      fireEvent.click(screen.getByTestId('modal-close'));

      await waitFor(() =>
        expect(screen.queryByText('fail')).not.toBeInTheDocument()
      );
    });
  });

  // ── Header management ──────────────────────────────────────────────────────

  describe('header row management', () => {
    it('renders an empty header row for new connection', () => {
      vi.mocked(useForm).mockReturnValue(makeFormMock());
      renderForm({ connection: null });

      // One empty key input should be present
      const keyInputs = screen.getAllByPlaceholderText(/Header name/i);
      expect(keyInputs).toHaveLength(1);
      expect(keyInputs[0]).toHaveValue('');
    });

    it('adds a new header row when Add Header is clicked', async () => {
      vi.mocked(useForm).mockReturnValue(makeFormMock());
      renderForm({ connection: null });

      await waitFor(() => {
        fireEvent.click(screen.getByText('Add Header'));
      });

      const keyInputs = screen.getAllByPlaceholderText(/Header name/i);
      expect(keyInputs).toHaveLength(2);
    });

    it('removes a header row when the remove button is clicked', async () => {
      const connection = makeConnection();
      vi.mocked(useForm).mockReturnValue(makeFormMock());
      renderForm({ connection });

      await waitFor(() => {
        fireEvent.click(screen.getByText('Add Header'));
      });

      const removeButtons = screen.getAllByTestId('button-remove');
      await waitFor(() => {
        fireEvent.click(removeButtons[1]);
      });

      const keyInputs = screen.getAllByPlaceholderText(/Header name/i);
      expect(keyInputs).toHaveLength(1);
    });

    it('does not remove the last header row', async () => {
      const connection = makeConnection();
      vi.mocked(useForm).mockReturnValue(makeFormMock());
      renderForm({ connection });

      const removeButton = screen.getByTestId('button-remove');
      await waitFor(() => {
        fireEvent.click(removeButton);
      });

      const keyInputs = screen.getAllByPlaceholderText(/Header name/i);
      expect(keyInputs).toHaveLength(1);
    });

    it('updates header key value when typed into', async () => {
      vi.mocked(useForm).mockReturnValue(makeFormMock());
      renderForm({ connection: null });

      const keyInput = screen.getByPlaceholderText(/Header name/i);
      await waitFor(() => {
        fireEvent.change(keyInput, { target: { value: 'Authorization' } });
      });

      expect(screen.getByDisplayValue('Authorization')).toBeInTheDocument();
    });
  });
});
