import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import DvrSettingsForm from '../DvrSettingsForm';

// ── Store mocks ────────────────────────────────────────────────────────────────
vi.mock('../../../../store/settings.jsx', () => {
  const mock = vi.fn();
  mock.getState = vi.fn();
  return { default: mock };
});

// ── Utility mocks ──────────────────────────────────────────────────────────────
vi.mock('../../../../utils/pages/SettingsUtils.js', () => ({
  getChangedSettings: vi.fn(),
  parseSettings: vi.fn(),
  saveChangedSettings: vi.fn(),
}));

vi.mock('../../../../utils/notificationUtils.js', () => ({
  showNotification: vi.fn(),
}));

vi.mock('../../../../utils/forms/settings/DvrSettingsFormUtils.js', () => ({
  getComskipConfig: vi.fn(),
  getDvrSettingsFormInitialValues: vi.fn(),
  uploadComskipIni: vi.fn(),
}));

// ── Mantine form ───────────────────────────────────────────────────────────────
vi.mock('@mantine/form', () => ({
  useForm: vi.fn(),
}));

// ── Mantine core ───────────────────────────────────────────────────────────────
vi.mock('@mantine/core', () => ({
  Alert: ({ title }) => <div data-testid="alert">{title}</div>,
  Button: ({ children, onClick, disabled, type, variant }) => (
    <button
      type={type || 'button'}
      onClick={onClick}
      disabled={disabled}
      data-variant={variant}
    >
      {children}
    </button>
  ),
  FileInput: ({ placeholder, onChange, disabled }) => (
    <input
      data-testid="file-input"
      type="file"
      placeholder={placeholder}
      disabled={disabled}
      onChange={(e) => {
        const file = e.target.files?.[0] ?? null;
        onChange?.(file);
      }}
    />
  ),
  Flex: ({ children }) => <div>{children}</div>,
  Group: ({ children }) => <div>{children}</div>,
  NumberInput: ({ label, id, name, ...rest }) => (
    <input
      data-testid={id}
      id={id}
      name={name}
      aria-label={label}
      type="number"
      onChange={(e) => rest.onChange?.(Number(e.target.value))}
    />
  ),
  Stack: ({ children }) => <div>{children}</div>,
  Switch: ({ label, id, checked, onChange }) => (
    <input
      data-testid={id}
      id={id}
      type="checkbox"
      aria-label={label}
      checked={checked ?? false}
      onChange={onChange}
    />
  ),
  Text: ({ children }) => <span>{children}</span>,
  TextInput: ({ label, id, name, placeholder, ...rest }) => (
    <input
      data-testid={id}
      id={id}
      name={name}
      aria-label={label}
      placeholder={placeholder}
      onChange={(e) => rest.onChange?.(e)}
    />
  ),
}));

// ──────────────────────────────────────────────────────────────────────────────
// Imports after mocks
// ──────────────────────────────────────────────────────────────────────────────
import useSettingsStore from '../../../../store/settings.jsx';
import { useForm } from '@mantine/form';
import {
  getChangedSettings,
  parseSettings,
  saveChangedSettings,
} from '../../../../utils/pages/SettingsUtils.js';
import { showNotification } from '../../../../utils/notificationUtils.js';
import {
  getComskipConfig,
  getDvrSettingsFormInitialValues,
  uploadComskipIni,
} from '../../../../utils/forms/settings/DvrSettingsFormUtils.js';

// ──────────────────────────────────────────────────────────────────────────────
// Helpers
// ──────────────────────────────────────────────────────────────────────────────
const mockFormValues = {
  comskip_enabled: false,
  comskip_custom_path: '',
  pre_offset_minutes: 0,
  post_offset_minutes: 0,
  tv_template: '',
  tv_fallback_template: '',
  movie_template: '',
  movie_fallback_template: '',
};

const makeFormMock = (overrides = {}) => ({
  getInputProps: vi.fn((field, opts) => {
    if (opts?.type === 'checkbox')
      return { checked: mockFormValues[field] ?? false, onChange: vi.fn() };
    return { value: mockFormValues[field] ?? '', onChange: vi.fn() };
  }),
  setValues: vi.fn(),
  setFieldValue: vi.fn(),
  getValues: vi.fn(() => mockFormValues),
  onSubmit: vi.fn((handler) => (e) => {
    e?.preventDefault?.();
    return handler();
  }),
  ...overrides,
});

const makeSettings = (overrides = {}) => ({
  comskip_enabled: { key: 'comskip_enabled', value: 'false' },
  comskip_custom_path: { key: 'comskip_custom_path', value: '' },
  pre_offset_minutes: { key: 'pre_offset_minutes', value: '0' },
  post_offset_minutes: { key: 'post_offset_minutes', value: '0' },
  ...overrides,
});

const setupMocks = ({ settings = makeSettings(), formOverrides = {} } = {}) => {
  const formMock = makeFormMock(formOverrides);

  vi.mocked(useForm).mockReturnValue(formMock);
  vi.mocked(getDvrSettingsFormInitialValues).mockReturnValue(mockFormValues);
  vi.mocked(parseSettings).mockReturnValue(mockFormValues);
  vi.mocked(getComskipConfig).mockResolvedValue({ path: '', exists: false });
  vi.mocked(getChangedSettings).mockReturnValue({});
  vi.mocked(saveChangedSettings).mockResolvedValue(undefined);

  vi.mocked(useSettingsStore).mockImplementation((sel) => sel({ settings }));
  vi.mocked(useSettingsStore).getState = vi.fn(() => ({
    updateSetting: vi.fn(),
  }));

  return { formMock };
};

// ──────────────────────────────────────────────────────────────────────────────
// Tests
// ──────────────────────────────────────────────────────────────────────────────
describe('DvrSettingsForm', () => {
  let formMock;

  beforeEach(() => {
    vi.clearAllMocks();
    ({ formMock } = setupMocks());
  });

  // ── Rendering ──────────────────────────────────────────────────────────────
  describe('rendering', () => {
    it('renders the form without crashing', async () => {
      render(<DvrSettingsForm active={true} />);
      await waitFor(() => {
        expect(screen.getByTestId('comskip_enabled')).toBeInTheDocument();
      });
    });

    it('renders the comskip enabled switch', async () => {
      render(<DvrSettingsForm active={true} />);
      await waitFor(() => {
        expect(screen.getByTestId('comskip_enabled')).toBeInTheDocument();
      });
    });

    it('renders the comskip custom path text input', async () => {
      render(<DvrSettingsForm active={true} />);
      await waitFor(() => {
        expect(screen.getByTestId('comskip_custom_path')).toBeInTheDocument();
      });
    });

    it('renders the file input for comskip.ini upload', async () => {
      render(<DvrSettingsForm active={true} />);
      await waitFor(() => {
        expect(screen.getByTestId('file-input')).toBeInTheDocument();
      });
    });

    it('renders the Upload comskip.ini button', async () => {
      render(<DvrSettingsForm active={true} />);
      await waitFor(() => {
        expect(screen.getByText('Upload comskip.ini')).toBeInTheDocument();
      });
    });

    it('renders the pre_offset_minutes number input', async () => {
      render(<DvrSettingsForm active={true} />);
      await waitFor(() => {
        expect(screen.getByTestId('pre_offset_minutes')).toBeInTheDocument();
      });
    });

    it('renders the post_offset_minutes number input', async () => {
      render(<DvrSettingsForm active={true} />);
      await waitFor(() => {
        expect(screen.getByTestId('post_offset_minutes')).toBeInTheDocument();
      });
    });

    it('renders all template text inputs', async () => {
      render(<DvrSettingsForm active={true} />);
      await waitFor(() => {
        expect(screen.getByTestId('tv_template')).toBeInTheDocument();
        expect(screen.getByTestId('tv_fallback_template')).toBeInTheDocument();
        expect(screen.getByTestId('movie_template')).toBeInTheDocument();
        expect(
          screen.getByTestId('movie_fallback_template')
        ).toBeInTheDocument();
      });
    });

    it('renders the Save button', async () => {
      render(<DvrSettingsForm active={true} />);
      await waitFor(() => {
        expect(screen.getByText('Save')).toBeInTheDocument();
      });
    });

    it('does not show success alert on initial render', async () => {
      render(<DvrSettingsForm active={true} />);
      await waitFor(() => {
        expect(screen.queryByTestId('alert')).not.toBeInTheDocument();
      });
    });

    it('shows "No custom comskip.ini uploaded." when no config exists', async () => {
      render(<DvrSettingsForm active={true} />);
      await waitFor(() => {
        expect(
          screen.getByText('No custom comskip.ini uploaded.')
        ).toBeInTheDocument();
      });
    });

    it('shows config path when comskipConfig has path and exists', async () => {
      vi.mocked(getComskipConfig).mockResolvedValue({
        path: '/app/docker/comskip.ini',
        exists: true,
      });
      render(<DvrSettingsForm active={true} />);
      await waitFor(() => {
        expect(
          screen.getByText('Using /app/docker/comskip.ini')
        ).toBeInTheDocument();
      });
    });
  });

  // ── Initialization ─────────────────────────────────────────────────────────
  describe('initialization', () => {
    it('calls getDvrSettingsFormInitialValues on mount', async () => {
      render(<DvrSettingsForm active={true} />);
      await waitFor(() => {
        expect(getDvrSettingsFormInitialValues).toHaveBeenCalled();
      });
    });

    it('calls parseSettings with settings on mount', async () => {
      render(<DvrSettingsForm active={true} />);
      await waitFor(() => {
        expect(parseSettings).toHaveBeenCalledWith(makeSettings());
        expect(formMock.setValues).toHaveBeenCalledWith(mockFormValues);
      });
    });

    it('calls getComskipConfig on mount', async () => {
      render(<DvrSettingsForm active={true} />);
      await waitFor(() => {
        expect(getComskipConfig).toHaveBeenCalled();
      });
    });

    it('sets comskip path from getComskipConfig response', async () => {
      vi.mocked(getComskipConfig).mockResolvedValue({
        path: '/custom/path/comskip.ini',
        exists: true,
      });
      render(<DvrSettingsForm active={true} />);
      await waitFor(() => {
        expect(formMock.setFieldValue).toHaveBeenCalledWith(
          'comskip_custom_path',
          '/custom/path/comskip.ini'
        );
      });
    });

    it('handles getComskipConfig error gracefully', async () => {
      vi.mocked(getComskipConfig).mockRejectedValue(new Error('network error'));
      const consoleSpy = vi
        .spyOn(console, 'error')
        .mockImplementation(() => {});
      render(<DvrSettingsForm active={true} />);
      await waitFor(() => {
        expect(consoleSpy).toHaveBeenCalledWith(
          'Failed to load comskip config',
          expect.any(Error)
        );
      });
      consoleSpy.mockRestore();
    });

    it('does not call setFieldValue when getComskipConfig returns no path', async () => {
      render(<DvrSettingsForm active={true} />);
      await waitFor(() => {
        expect(getComskipConfig).toHaveBeenCalled();
      });
      expect(formMock.setFieldValue).not.toHaveBeenCalledWith(
        'comskip_custom_path',
        expect.anything()
      );
    });
  });

  // ── active prop ────────────────────────────────────────────────────────────
  describe('active prop', () => {
    it('resets saved state when active becomes false', async () => {
      vi.mocked(getChangedSettings).mockReturnValue({ comskip_enabled: true });
      const { rerender } = render(<DvrSettingsForm active={true} />);

      fireEvent.submit(screen.getByText('Save').closest('form'));

      await waitFor(() => {
        expect(screen.getByTestId('alert')).toBeInTheDocument();
      });

      rerender(<DvrSettingsForm active={false} />);

      await waitFor(() => {
        expect(screen.queryByTestId('alert')).not.toBeInTheDocument();
      });
    });
  });

  // ── Form submission ────────────────────────────────────────────────────────
  describe('form submission', () => {
    it('calls getChangedSettings and saveChangedSettings on submit', async () => {
      vi.mocked(getChangedSettings).mockReturnValue({ pre_offset_minutes: 5 });
      render(<DvrSettingsForm active={true} />);
      fireEvent.submit(screen.getByText('Save').closest('form'));

      await waitFor(() => {
        expect(getChangedSettings).toHaveBeenCalledWith(
          mockFormValues,
          makeSettings()
        );
        expect(saveChangedSettings).toHaveBeenCalledWith(makeSettings(), {
          pre_offset_minutes: 5,
        });
      });
    });

    it('shows success alert after successful save', async () => {
      render(<DvrSettingsForm active={true} />);
      fireEvent.submit(screen.getByText('Save').closest('form'));

      await waitFor(() => {
        expect(screen.getByTestId('alert')).toBeInTheDocument();
        expect(screen.getByText('Saved Successfully')).toBeInTheDocument();
      });
    });

    it('does not show success alert when saveChangedSettings throws', async () => {
      vi.mocked(saveChangedSettings).mockRejectedValue(
        new Error('save failed')
      );
      const consoleSpy = vi
        .spyOn(console, 'error')
        .mockImplementation(() => {});

      render(<DvrSettingsForm active={true} />);
      fireEvent.submit(screen.getByText('Save').closest('form'));

      await waitFor(() => {
        expect(consoleSpy).toHaveBeenCalledWith(
          'Error saving settings:',
          expect.any(Error)
        );
        expect(screen.queryByTestId('alert')).not.toBeInTheDocument();
      });
      consoleSpy.mockRestore();
    });
  });

  // ── comskip upload ─────────────────────────────────────────────────────────
  describe('comskip upload', () => {
    it('Upload button is disabled when no file is selected', async () => {
      render(<DvrSettingsForm active={true} />);
      await waitFor(() => {
        expect(screen.getByText('Upload comskip.ini')).toBeDisabled();
      });
    });

    it('calls uploadComskipIni with the selected file', async () => {
      const mockFile = new File(['content'], 'comskip.ini', {
        type: 'text/plain',
      });
      vi.mocked(uploadComskipIni).mockResolvedValue({
        path: '/uploaded/comskip.ini',
      });

      render(<DvrSettingsForm active={true} />);
      fireEvent.change(screen.getByTestId('file-input'), {
        target: { files: [mockFile] },
      });

      await waitFor(() => {
        fireEvent.click(screen.getByText('Upload comskip.ini'));
      });

      await waitFor(() => {
        expect(uploadComskipIni).toHaveBeenCalledWith(mockFile);
      });
    });

    it('shows success notification after successful upload', async () => {
      const mockFile = new File(['content'], 'comskip.ini', {
        type: 'text/plain',
      });
      vi.mocked(uploadComskipIni).mockResolvedValue({
        path: '/uploaded/comskip.ini',
      });

      render(<DvrSettingsForm active={true} />);
      fireEvent.change(screen.getByTestId('file-input'), {
        target: { files: [mockFile] },
      });

      await waitFor(() => {
        fireEvent.click(screen.getByText('Upload comskip.ini'));
      });

      await waitFor(() => {
        expect(showNotification).toHaveBeenCalledWith(
          expect.objectContaining({
            title: 'comskip.ini uploaded',
            color: 'green',
          })
        );
      });
    });

    it('sets comskip_custom_path form field after successful upload', async () => {
      const mockFile = new File(['content'], 'comskip.ini', {
        type: 'text/plain',
      });
      vi.mocked(uploadComskipIni).mockResolvedValue({
        path: '/uploaded/comskip.ini',
      });

      render(<DvrSettingsForm active={true} />);
      fireEvent.change(screen.getByTestId('file-input'), {
        target: { files: [mockFile] },
      });

      await waitFor(() => {
        fireEvent.click(screen.getByText('Upload comskip.ini'));
      });

      await waitFor(() => {
        expect(formMock.setFieldValue).toHaveBeenCalledWith(
          'comskip_custom_path',
          '/uploaded/comskip.ini'
        );
      });
    });

    it('handles upload error gracefully', async () => {
      const mockFile = new File(['content'], 'comskip.ini', {
        type: 'text/plain',
      });
      vi.mocked(uploadComskipIni).mockRejectedValue(new Error('upload failed'));
      const consoleSpy = vi
        .spyOn(console, 'error')
        .mockImplementation(() => {});

      render(<DvrSettingsForm active={true} />);
      fireEvent.change(screen.getByTestId('file-input'), {
        target: { files: [mockFile] },
      });

      await waitFor(() => {
        fireEvent.click(screen.getByText('Upload comskip.ini'));
      });

      await waitFor(() => {
        expect(consoleSpy).toHaveBeenCalledWith(
          'Failed to upload comskip.ini',
          expect.any(Error)
        );
        expect(showNotification).not.toHaveBeenCalled();
      });
      consoleSpy.mockRestore();
    });

    it('does not call uploadComskipIni when no file is selected', async () => {
      render(<DvrSettingsForm active={true} />);
      await waitFor(() => screen.getByTestId('file-input'));
      expect(uploadComskipIni).not.toHaveBeenCalled();
    });
  });
});
