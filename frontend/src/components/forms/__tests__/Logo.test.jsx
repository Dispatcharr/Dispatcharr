import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import LogoForm from '../Logo';

// ── Utility mocks ──────────────────────────────────────────────────────────────
vi.mock('../../../utils/forms/LogoUtils.js', () => ({
  createLogo: vi.fn(),
  updateLogo: vi.fn(),
  uploadLogo: vi.fn(),
  getFilenameWithoutExtension: vi.fn((name) => name.replace(/\.[^.]+$/, '')),
  getResolver: vi.fn(() => undefined),
  getUpdateLogoErrorMessage: vi.fn((logo, err) => err.message),
  getUploadErrorMessage: vi.fn((err) => err.message),
  releaseUrl: vi.fn(),
  validateFileSize: vi.fn(() => true),
}));

vi.mock('../../../utils/notificationUtils.js', () => ({
  showNotification: vi.fn(),
}));

// ── Mantine dropzone ───────────────────────────────────────────────────────────
vi.mock('@mantine/dropzone', () => ({
  Dropzone: vi.fn(({ children, onDrop }) => (
    <div data-testid="dropzone" onClick={() => onDrop([])}>
      {children}
    </div>
  )),
  DropzoneAccept: ({ children }) => (
    <div data-testid="dz-accept">{children}</div>
  ),
  DropzoneReject: ({ children }) => (
    <div data-testid="dz-reject">{children}</div>
  ),
  DropzoneIdle: ({ children }) => <div data-testid="dz-idle">{children}</div>,
}));

// ── Mantine core ───────────────────────────────────────────────────────────────
vi.mock('@mantine/core', () => ({
  Box: ({ children }) => <div>{children}</div>,
  Button: ({ children, onClick, type, loading, variant }) => (
    <button
      type={type || 'button'}
      onClick={onClick}
      disabled={loading}
      data-variant={variant}
      data-loading={loading}
    >
      {children}
    </button>
  ),
  Center: ({ children }) => <div>{children}</div>,
  Divider: ({ label }) => <hr aria-label={label} />,
  Group: ({ children }) => <div>{children}</div>,
  Image: ({ src, alt, fallbackSrc }) => (
    <img src={src} alt={alt} data-fallback={fallbackSrc} />
  ),
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
  Stack: ({ children }) => <div>{children}</div>,
  Text: ({ children, size, color }) => (
    <span data-size={size} data-color={color}>
      {children}
    </span>
  ),
  TextInput: ({
    label,
    placeholder,
    onChange,
    onBlur,
    error,
    disabled,
    ...rest
  }) => (
    <div>
      <label>
        {label}
        <input
          aria-label={label}
          placeholder={placeholder}
          onChange={onChange}
          onBlur={onBlur}
          disabled={disabled}
          {...rest}
        />
      </label>
      {error && <span data-testid={`error-${label}`}>{error}</span>}
    </div>
  ),
}));

// ── lucide-react ───────────────────────────────────────────────────────────────
vi.mock('lucide-react', () => ({
  FileImage: () => <svg data-testid="icon-file-image" />,
  Upload: () => <svg data-testid="icon-upload" />,
  X: () => <svg data-testid="icon-x" />,
}));

// ──────────────────────────────────────────────────────────────────────────────
// Imports after mocks
// ──────────────────────────────────────────────────────────────────────────────
import * as LogoUtils from '../../../utils/forms/LogoUtils.js';
import { showNotification } from '../../../utils/notificationUtils.js';

// ── Helpers ────────────────────────────────────────────────────────────────────
const makeLogo = (overrides = {}) => ({
  id: 1,
  name: 'My Logo',
  url: 'https://example.com/logo.png',
  cache_url: 'https://cdn.example.com/logo.png',
  ...overrides,
});

const defaultProps = (overrides = {}) => ({
  logo: null,
  isOpen: true,
  onClose: vi.fn(),
  onSuccess: vi.fn(),
  ...overrides,
});

const makeFile = (name = 'test-logo.png', size = 1024) =>
  new File(['content'], name, { type: 'image/png', size });

// ──────────────────────────────────────────────────────────────────────────────

describe('LogoForm', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(LogoUtils.validateFileSize).mockReturnValue(true);
    vi.mocked(LogoUtils.createLogo).mockResolvedValue({
      id: 2,
      name: 'New Logo',
      url: 'https://example.com/new.png',
    });
    vi.mocked(LogoUtils.updateLogo).mockResolvedValue({
      id: 1,
      name: 'Updated Logo',
      url: 'https://example.com/updated.png',
    });
    vi.mocked(LogoUtils.uploadLogo).mockResolvedValue({
      id: 3,
      name: 'uploaded-logo',
      url: 'https://cdn.example.com/uploaded.png',
    });
    vi.mocked(LogoUtils.getResolver).mockReturnValue(undefined);

    URL.createObjectURL = vi.fn();
  });

  afterEach(() => {
    delete URL.createObjectURL;
  });

  // ── Rendering ──────────────────────────────────────────────────────────────

  describe('rendering', () => {
    it('renders the modal when isOpen is true', () => {
      render(<LogoForm {...defaultProps()} />);
      expect(screen.getByTestId('modal')).toBeInTheDocument();
    });

    it('does not render the modal when isOpen is false', () => {
      render(<LogoForm {...defaultProps({ isOpen: false })} />);
      expect(screen.queryByTestId('modal')).not.toBeInTheDocument();
    });

    it('shows "Add Logo" title for new logo', () => {
      render(<LogoForm {...defaultProps()} />);
      expect(screen.getByTestId('modal-title')).toHaveTextContent('Add Logo');
    });

    it('shows "Edit Logo" title when editing existing logo', () => {
      render(<LogoForm {...defaultProps({ logo: makeLogo() })} />);
      expect(screen.getByTestId('modal-title')).toHaveTextContent('Edit Logo');
    });

    it('shows "Create" button for new logo', () => {
      render(<LogoForm {...defaultProps()} />);
      expect(screen.getByText('Create')).toBeInTheDocument();
    });

    it('shows "Update" button when editing existing logo', () => {
      render(<LogoForm {...defaultProps({ logo: makeLogo() })} />);
      expect(screen.getByText('Update')).toBeInTheDocument();
    });

    it('pre-fills name input when editing existing logo', () => {
      render(<LogoForm {...defaultProps({ logo: makeLogo() })} />);
      expect(screen.getByDisplayValue('My Logo')).toBeInTheDocument();
    });

    it('pre-fills URL input when editing existing logo', () => {
      render(<LogoForm {...defaultProps({ logo: makeLogo() })} />);
      expect(
        screen.getByDisplayValue('https://example.com/logo.png')
      ).toBeInTheDocument();
    });

    it('shows logo preview when logo has cache_url', () => {
      render(<LogoForm {...defaultProps({ logo: makeLogo() })} />);
      const img = screen.getByAltText('Logo preview');
      expect(img).toHaveAttribute('src', 'https://cdn.example.com/logo.png');
    });

    it('does not show preview when no logo provided', () => {
      render(<LogoForm {...defaultProps()} />);
      expect(screen.queryByAltText('Logo preview')).not.toBeInTheDocument();
    });

    it('renders the dropzone', () => {
      render(<LogoForm {...defaultProps()} />);
      expect(screen.getByTestId('dropzone')).toBeInTheDocument();
    });

    it('calls onClose when Cancel is clicked', () => {
      const onClose = vi.fn();
      render(<LogoForm {...defaultProps({ onClose })} />);
      fireEvent.click(screen.getByText('Cancel'));
      expect(onClose).toHaveBeenCalled();
    });

    it('calls onClose when modal close button is clicked', () => {
      const onClose = vi.fn();
      render(<LogoForm {...defaultProps({ onClose })} />);
      fireEvent.click(screen.getByTestId('modal-close'));
      expect(onClose).toHaveBeenCalled();
    });
  });

  // ── Create logo ────────────────────────────────────────────────────────────

  describe('creating a logo via URL', () => {
    it('calls createLogo with entered values on submit', async () => {
      render(<LogoForm {...defaultProps()} />);

      fireEvent.change(
        screen.getByPlaceholderText('https://example.com/logo.png'),
        {
          target: { value: 'https://example.com/new.png' },
        }
      );
      fireEvent.change(screen.getByPlaceholderText('Enter logo name'), {
        target: { value: 'New Logo' },
      });
      fireEvent.click(screen.getByText('Create'));

      await waitFor(() => {
        expect(LogoUtils.createLogo).toHaveBeenCalled();
      });
    });

    it('shows success notification after creating logo', async () => {
      render(<LogoForm {...defaultProps()} />);

      fireEvent.change(
        screen.getByPlaceholderText('https://example.com/logo.png'),
        {
          target: { value: 'https://example.com/new.png' },
        }
      );
      fireEvent.click(screen.getByText('Create'));

      await waitFor(() => {
        expect(showNotification).toHaveBeenCalledWith(
          expect.objectContaining({ title: 'Success', color: 'green' })
        );
      });
    });

    it('calls onSuccess with type "create" after creating logo', async () => {
      const onSuccess = vi.fn();
      render(<LogoForm {...defaultProps({ onSuccess })} />);

      fireEvent.change(
        screen.getByPlaceholderText('https://example.com/logo.png'),
        {
          target: { value: 'https://example.com/new.png' },
        }
      );
      fireEvent.click(screen.getByText('Create'));

      await waitFor(() => {
        expect(onSuccess).toHaveBeenCalledWith(
          expect.objectContaining({ type: 'create' })
        );
      });
    });

    it('calls onClose after creating logo', async () => {
      const onClose = vi.fn();
      render(<LogoForm {...defaultProps({ onClose })} />);

      fireEvent.change(
        screen.getByPlaceholderText('https://example.com/logo.png'),
        {
          target: { value: 'https://example.com/new.png' },
        }
      );
      fireEvent.click(screen.getByText('Create'));

      await waitFor(() => {
        expect(onClose).toHaveBeenCalled();
      });
    });

    it('shows error notification when createLogo throws', async () => {
      vi.mocked(LogoUtils.createLogo).mockRejectedValue(new Error('API error'));
      render(<LogoForm {...defaultProps()} />);

      fireEvent.change(
        screen.getByPlaceholderText('https://example.com/logo.png'),
        {
          target: { value: 'https://example.com/new.png' },
        }
      );
      fireEvent.click(screen.getByText('Create'));

      await waitFor(() => {
        expect(showNotification).toHaveBeenCalledWith(
          expect.objectContaining({ title: 'Error', color: 'red' })
        );
      });
    });
  });

  // ── Update logo ────────────────────────────────────────────────────────────

  describe('updating an existing logo', () => {
    it('calls updateLogo on submit', async () => {
      render(<LogoForm {...defaultProps({ logo: makeLogo() })} />);
      fireEvent.click(screen.getByText('Update'));

      await waitFor(() => {
        expect(LogoUtils.updateLogo).toHaveBeenCalledWith(
          makeLogo(),
          expect.objectContaining({ name: 'My Logo' })
        );
      });
    });

    it('calls onSuccess with type "update" after updating logo', async () => {
      const onSuccess = vi.fn();
      render(<LogoForm {...defaultProps({ logo: makeLogo(), onSuccess })} />);
      fireEvent.click(screen.getByText('Update'));

      await waitFor(() => {
        expect(onSuccess).toHaveBeenCalledWith(
          expect.objectContaining({ type: 'update' })
        );
      });
    });

    it('shows success notification after updating logo', async () => {
      render(<LogoForm {...defaultProps({ logo: makeLogo() })} />);
      fireEvent.click(screen.getByText('Update'));

      await waitFor(() => {
        expect(showNotification).toHaveBeenCalledWith(
          expect.objectContaining({ title: 'Success', color: 'green' })
        );
      });
    });

    it('shows error notification when updateLogo throws', async () => {
      vi.mocked(LogoUtils.updateLogo).mockRejectedValue(
        new Error('Server error')
      );
      render(<LogoForm {...defaultProps({ logo: makeLogo() })} />);
      fireEvent.click(screen.getByText('Update'));

      await waitFor(() => {
        expect(showNotification).toHaveBeenCalledWith(
          expect.objectContaining({ title: 'Error', color: 'red' })
        );
      });
    });
  });

  // ── File upload ────────────────────────────────────────────────────────────

  describe('file upload via dropzone', () => {
    it('calls uploadLogo with the selected file on submit', async () => {
      const file = makeFile('my-logo.png');

      // Override dropzone to pass our test file
      const { Dropzone } = await import('@mantine/dropzone');
      vi.mocked(Dropzone).mockImplementation(({ children, onDrop }) => (
        <div data-testid="dropzone" onClick={() => onDrop([file])}>
          {children}
        </div>
      ));

      render(<LogoForm {...defaultProps()} />);

      fireEvent.click(screen.getByTestId('dropzone'));
      fireEvent.click(screen.getByText('Create'));

      await waitFor(() => {
        expect(LogoUtils.uploadLogo).toHaveBeenCalledWith(
          file,
          expect.any(Object)
        );
      });
    });

    it('shows error notification when file is too large', async () => {
      vi.mocked(LogoUtils.validateFileSize).mockReturnValue(false);

      // Override dropzone to pass a file
      const file = makeFile('big.png', 10 * 1024 * 1024);
      const { Dropzone } = await import('@mantine/dropzone');
      vi.mocked(Dropzone).mockImplementationOnce(({ children, onDrop }) => (
        <div data-testid="dropzone" onClick={() => onDrop([file])}>
          {children}
        </div>
      ));

      render(<LogoForm {...defaultProps()} />);
      fireEvent.click(screen.getByTestId('dropzone'));

      await waitFor(() => {
        expect(showNotification).toHaveBeenCalledWith(
          expect.objectContaining({ title: 'Error', color: 'red' })
        );
      });
    });

    it('shows upload error notification when uploadLogo throws', async () => {
      vi.mocked(LogoUtils.uploadLogo).mockRejectedValue(
        new Error('Upload failed')
      );
      const file = makeFile('logo.png');
      const { Dropzone } = await import('@mantine/dropzone');
      vi.mocked(Dropzone).mockImplementationOnce(({ children, onDrop }) => (
        <div data-testid="dropzone" onClick={() => onDrop([file])}>
          {children}
        </div>
      ));

      render(<LogoForm {...defaultProps()} />);
      fireEvent.click(screen.getByTestId('dropzone'));
      fireEvent.click(screen.getByText('Create'));

      await waitFor(() => {
        expect(showNotification).toHaveBeenCalledWith(
          expect.objectContaining({ title: 'Upload Error', color: 'red' })
        );
      });
    });
  });

  // ── URL input behaviour ────────────────────────────────────────────────────

  describe('URL input behaviour', () => {
    it('updates preview when a valid http URL is entered', () => {
      render(<LogoForm {...defaultProps()} />);
      fireEvent.change(
        screen.getByPlaceholderText('https://example.com/logo.png'),
        {
          target: { value: 'https://example.com/img.png' },
        }
      );
      expect(screen.getByAltText('Logo preview')).toHaveAttribute(
        'src',
        'https://example.com/img.png'
      );
    });

    it('removes preview when URL is cleared', () => {
      render(<LogoForm {...defaultProps({ logo: makeLogo() })} />);
      fireEvent.change(
        screen.getByPlaceholderText('https://example.com/logo.png'),
        {
          target: { value: '' },
        }
      );
      expect(screen.queryByAltText('Logo preview')).not.toBeInTheDocument();
    });

    it('auto-fills name from URL on blur', () => {
      render(<LogoForm {...defaultProps()} />);
      fireEvent.change(
        screen.getByPlaceholderText('https://example.com/logo.png'),
        {
          target: { value: 'https://example.com/my-channel-logo.png' },
        }
      );
      fireEvent.blur(
        screen.getByPlaceholderText('https://example.com/logo.png'),
        {
          target: { value: 'https://example.com/my-channel-logo.png' },
        }
      );
      expect(LogoUtils.getFilenameWithoutExtension).toHaveBeenCalled();
    });

    it('does not throw on blur with invalid URL', () => {
      render(<LogoForm {...defaultProps()} />);
      expect(() => {
        fireEvent.blur(
          screen.getByPlaceholderText('https://example.com/logo.png'),
          {
            target: { value: 'not-a-url' },
          }
        );
      }).not.toThrow();
    });
  });
});
