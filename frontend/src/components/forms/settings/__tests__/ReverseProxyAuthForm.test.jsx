import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

// ── Store mocks ────────────────────────────────────────────────────────────────
vi.mock('../../../../store/settings.jsx', () => ({ default: vi.fn() }));

// ── Utility mocks ──────────────────────────────────────────────────────────────
vi.mock('../../../../utils/pages/SettingsUtils.js', () => ({
  createSetting: vi.fn(),
  updateSetting: vi.fn(),
}));

// ── Mantine form ───────────────────────────────────────────────────────────────
vi.mock('@mantine/form', () => ({
  useForm: vi.fn(),
}));

// ── Mantine core ───────────────────────────────────────────────────────────────
vi.mock('@mantine/core', () => ({
  Alert: ({ title, children }) => (
    <div data-testid="alert">
      <strong>{title}</strong>
      {children ? <div>{children}</div> : null}
    </div>
  ),
  Button: ({ children, onClick, disabled }) => (
    <button onClick={onClick} disabled={disabled}>
      {children}
    </button>
  ),
  Flex: ({ children }) => <div>{children}</div>,
  Stack: ({ children }) => <div>{children}</div>,
  Switch: ({ label, description, id }) => (
    <div>
      <label htmlFor={id}>{label}</label>
      <p>{description}</p>
      <input data-testid={id} id={id} type="checkbox" onChange={() => {}} />
    </div>
  ),
  TextInput: ({ label, description, id, placeholder }) => (
    <div>
      <label htmlFor={id}>{label}</label>
      <p>{description}</p>
      <input data-testid={id} id={id} placeholder={placeholder} />
    </div>
  ),
}));

// ──────────────────────────────────────────────────────────────────────────────
// Imports after mocks
// ──────────────────────────────────────────────────────────────────────────────
import ReverseProxyAuthForm from '../ReverseProxyAuthForm';
import useSettingsStore from '../../../../store/settings.jsx';
import {
  createSetting,
  updateSetting,
} from '../../../../utils/pages/SettingsUtils.js';
import { useForm } from '@mantine/form';

// ──────────────────────────────────────────────────────────────────────────────
// Helpers
// ──────────────────────────────────────────────────────────────────────────────
const setupMocks = ({ settings = {}, formValues = {} } = {}) => {
  const values = { enabled: false, header: '', ...formValues };

  const formMock = {
    values,
    getValues: vi.fn().mockReturnValue(values),
    setValues: vi.fn(),
    getInputProps: vi.fn((field, opts) =>
      opts?.type === 'checkbox'
        ? { checked: values[field] ?? false, onChange: vi.fn() }
        : { value: values[field] ?? '', onChange: vi.fn() }
    ),
    onSubmit: vi.fn((handler) => handler),
  };

  const fetchSettings = vi.fn().mockResolvedValue(undefined);

  vi.mocked(useForm).mockReturnValue(formMock);
  vi.mocked(useSettingsStore).mockImplementation((sel) =>
    sel({ settings, fetchSettings })
  );

  return { formMock, fetchSettings };
};

const EXISTING_SETTING = {
  reverse_proxy_auth: {
    id: 7,
    key: 'reverse_proxy_auth',
    name: 'Reverse Proxy Auth',
    value: { enabled: true, header: 'X-Forwarded-User' },
  },
};

describe('ReverseProxyAuthForm', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('rendering', () => {
    it('renders the enable switch and header input', () => {
      setupMocks();
      render(<ReverseProxyAuthForm active={true} />);

      expect(
        screen.getByTestId('reverse_proxy_auth_enabled')
      ).toBeInTheDocument();
      expect(
        screen.getByTestId('reverse_proxy_auth_header')
      ).toBeInTheDocument();
      expect(screen.getByText('Save')).toBeInTheDocument();
    });

    it('warns that the header is only trusted from a trusted proxy', () => {
      setupMocks();
      render(<ReverseProxyAuthForm active={true} />);

      expect(screen.getByText('Trust your proxy first')).toBeInTheDocument();
    });

    it('seeds the form from the stored setting', () => {
      const { formMock } = setupMocks({ settings: EXISTING_SETTING });
      render(<ReverseProxyAuthForm active={true} />);

      expect(formMock.setValues).toHaveBeenCalledWith({
        enabled: true,
        header: 'X-Forwarded-User',
      });
    });

    it('falls back to disabled with no header when the setting is missing', () => {
      const { formMock } = setupMocks();
      render(<ReverseProxyAuthForm active={true} />);

      expect(formMock.setValues).toHaveBeenCalledWith({
        enabled: false,
        header: '',
      });
    });
  });

  describe('validation', () => {
    const getValidator = () => {
      setupMocks();
      render(<ReverseProxyAuthForm active={true} />);
      return vi.mocked(useForm).mock.calls[0][0].validate.header;
    };

    it('requires a header name when enabling', () => {
      expect(getValidator()('', { enabled: true })).toMatch(/required/i);
    });

    it('allows an empty header while disabled', () => {
      expect(getValidator()('', { enabled: false })).toBeNull();
    });

    it('accepts a conventional header name', () => {
      expect(getValidator()('X-Forwarded-User', { enabled: true })).toBeNull();
    });

    it('rejects a header name containing an underscore', () => {
      expect(getValidator()('Remote_User', { enabled: true })).toMatch(
        /letters, digits and dashes/i
      );
    });
  });

  describe('saving', () => {
    it('updates the existing setting with a trimmed header', async () => {
      setupMocks({
        settings: EXISTING_SETTING,
        formValues: { enabled: true, header: '  X-Auth-Request-User  ' },
      });
      vi.mocked(updateSetting).mockResolvedValue({});

      render(<ReverseProxyAuthForm active={true} />);
      fireEvent.click(screen.getByText('Save'));

      await waitFor(() => {
        expect(updateSetting).toHaveBeenCalledWith({
          ...EXISTING_SETTING.reverse_proxy_auth,
          value: { enabled: true, header: 'X-Auth-Request-User' },
        });
      });
      expect(createSetting).not.toHaveBeenCalled();
    });

    it('creates the setting when no row exists yet', async () => {
      setupMocks({ formValues: { enabled: true, header: 'X-Forwarded-User' } });
      vi.mocked(createSetting).mockResolvedValue({});

      render(<ReverseProxyAuthForm active={true} />);
      fireEvent.click(screen.getByText('Save'));

      await waitFor(() => {
        expect(createSetting).toHaveBeenCalledWith({
          key: 'reverse_proxy_auth',
          name: 'Reverse Proxy Auth',
          value: { enabled: true, header: 'X-Forwarded-User' },
        });
      });
      expect(updateSetting).not.toHaveBeenCalled();
    });

    it('refreshes settings after a successful save', async () => {
      const { fetchSettings } = setupMocks({
        settings: EXISTING_SETTING,
        formValues: { enabled: true, header: 'X-Forwarded-User' },
      });
      vi.mocked(updateSetting).mockResolvedValue({});

      render(<ReverseProxyAuthForm active={true} />);
      fireEvent.click(screen.getByText('Save'));

      await waitFor(() => expect(fetchSettings).toHaveBeenCalled());
      expect(screen.getByText('Saved Successfully')).toBeInTheDocument();
    });

    it('surfaces the error message returned by the backend', async () => {
      setupMocks({
        settings: EXISTING_SETTING,
        formValues: { enabled: true, header: 'X-Forwarded-User' },
      });
      const failure = new Error('rejected');
      failure.body = { message: 'Invalid header name.' };
      vi.mocked(updateSetting).mockRejectedValue(failure);

      render(<ReverseProxyAuthForm active={true} />);
      fireEvent.click(screen.getByText('Save'));

      await waitFor(() =>
        expect(screen.getByText('Invalid header name.')).toBeInTheDocument()
      );
    });
  });
});
