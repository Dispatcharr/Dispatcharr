import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

// ── Utility mocks ──────────────────────────────────────────────────────────────
vi.mock('../../../utils/forms/UserAgentUtils.js', () => ({
  addUserAgent: vi.fn(),
  updateUserAgent: vi.fn(),
  getResolver: vi.fn(() => undefined),
}));

// ── Mantine core ───────────────────────────────────────────────────────────────
vi.mock('@mantine/core', () => ({
  Button: ({ children, disabled, type }) => (
    <button type={type} disabled={disabled}>
      {children}
    </button>
  ),
  Checkbox: ({ label, checked, onChange }) => (
    <label>
      <input
        type="checkbox"
        data-testid="checkbox-is-active"
        checked={checked}
        onChange={onChange}
      />
      {label}
    </label>
  ),
  Flex: ({ children }) => <div>{children}</div>,
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
  Space: () => <div />,
  TextInput: ({ label, error, ...rest }) => (
    <div>
      <label>{label}</label>
      <input data-testid={`input-${label}`} aria-label={label} {...rest} />
      {error && <span data-testid={`error-${label}`}>{error}</span>}
    </div>
  ),
}));

// ── Imports after mocks ────────────────────────────────────────────────────────
import * as UserAgentUtils from '../../../utils/forms/UserAgentUtils.js';
import UserAgent from '../UserAgent';

// ── Helpers ────────────────────────────────────────────────────────────────────
const makeUserAgent = (overrides = {}) => ({
  id: 1,
  name: 'Chrome',
  user_agent: 'Mozilla/5.0',
  description: 'Chrome browser',
  is_active: true,
  ...overrides,
});

describe('UserAgent', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(UserAgentUtils.addUserAgent).mockResolvedValue({});
    vi.mocked(UserAgentUtils.updateUserAgent).mockResolvedValue({});
    vi.mocked(UserAgentUtils.getResolver).mockReturnValue(undefined);
  });

  // ── Visibility ───────────────────────────────────────────────────────────────

  describe('visibility', () => {
    it('renders nothing when isOpen is false', () => {
      render(<UserAgent isOpen={false} onClose={vi.fn()} />);
      expect(screen.queryByTestId('modal')).not.toBeInTheDocument();
    });

    it('renders the modal when isOpen is true', () => {
      render(<UserAgent isOpen={true} onClose={vi.fn()} />);
      expect(screen.getByTestId('modal')).toBeInTheDocument();
    });

    it('renders modal title "User-Agent"', () => {
      render(<UserAgent isOpen={true} onClose={vi.fn()} />);
      expect(screen.getByTestId('modal-title')).toHaveTextContent('User-Agent');
    });

    it('calls onClose when modal close button is clicked', () => {
      const onClose = vi.fn();
      render(<UserAgent isOpen={true} onClose={onClose} />);
      fireEvent.click(screen.getByTestId('modal-close'));
      expect(onClose).toHaveBeenCalled();
    });
  });

  // ── Default values ───────────────────────────────────────────────────────────

  describe('default values', () => {
    it('renders empty fields when no userAgent prop is given', () => {
      render(<UserAgent isOpen={true} onClose={vi.fn()} />);
      expect(screen.getByTestId('input-Name')).toHaveValue('');
      expect(screen.getByTestId('input-User-Agent')).toHaveValue('');
      expect(screen.getByTestId('input-Description')).toHaveValue('');
    });

    it('pre-fills fields from userAgent prop', () => {
      render(
        <UserAgent
          isOpen={true}
          onClose={vi.fn()}
          userAgent={makeUserAgent()}
        />
      );
      expect(screen.getByTestId('input-Name')).toHaveValue('Chrome');
      expect(screen.getByTestId('input-User-Agent')).toHaveValue('Mozilla/5.0');
      expect(screen.getByTestId('input-Description')).toHaveValue(
        'Chrome browser'
      );
    });

    it('checks Is Active checkbox when userAgent.is_active is true', () => {
      render(
        <UserAgent
          isOpen={true}
          onClose={vi.fn()}
          userAgent={makeUserAgent({ is_active: true })}
        />
      );
      expect(screen.getByTestId('checkbox-is-active')).toBeChecked();
    });

    it('unchecks Is Active checkbox when userAgent.is_active is false', () => {
      render(
        <UserAgent
          isOpen={true}
          onClose={vi.fn()}
          userAgent={makeUserAgent({ is_active: false })}
        />
      );
      expect(screen.getByTestId('checkbox-is-active')).not.toBeChecked();
    });

    it('defaults Is Active to checked when no userAgent prop given', () => {
      render(<UserAgent isOpen={true} onClose={vi.fn()} />);
      expect(screen.getByTestId('checkbox-is-active')).toBeChecked();
    });
  });

  // ── Field interactions ───────────────────────────────────────────────────────

  describe('field interactions', () => {
    it('toggles Is Active checkbox', () => {
      render(
        <UserAgent
          isOpen={true}
          onClose={vi.fn()}
          userAgent={makeUserAgent({ is_active: true })}
        />
      );
      const checkbox = screen.getByTestId('checkbox-is-active');
      fireEvent.click(checkbox);
      expect(checkbox).not.toBeChecked();
    });
  });

  // ── Form submission ──────────────────────────────────────────────────────────

  describe('form submission', () => {
    it('calls addUserAgent when no userAgent id is given', async () => {
      render(<UserAgent isOpen={true} onClose={vi.fn()} />);
      fireEvent.click(screen.getByText('Submit'));
      await waitFor(() => {
        expect(UserAgentUtils.addUserAgent).toHaveBeenCalled();
      });
    });

    it('calls updateUserAgent with the id when editing an existing userAgent', async () => {
      render(
        <UserAgent
          isOpen={true}
          onClose={vi.fn()}
          userAgent={makeUserAgent()}
        />
      );
      fireEvent.click(screen.getByText('Submit'));
      await waitFor(() => {
        expect(UserAgentUtils.updateUserAgent).toHaveBeenCalledWith(
          1,
          expect.objectContaining({ name: 'Chrome' })
        );
      });
    });

    it('does not call addUserAgent when updating', async () => {
      render(
        <UserAgent
          isOpen={true}
          onClose={vi.fn()}
          userAgent={makeUserAgent()}
        />
      );
      fireEvent.click(screen.getByText('Submit'));
      await waitFor(() => {
        expect(UserAgentUtils.addUserAgent).not.toHaveBeenCalled();
      });
    });

    it('does not call updateUserAgent when creating', async () => {
      render(<UserAgent isOpen={true} onClose={vi.fn()} />);
      fireEvent.click(screen.getByText('Submit'));
      await waitFor(() => {
        expect(UserAgentUtils.updateUserAgent).not.toHaveBeenCalled();
      });
    });

    it('calls onClose after successful submission', async () => {
      const onClose = vi.fn();
      render(<UserAgent isOpen={true} onClose={onClose} />);
      fireEvent.click(screen.getByText('Submit'));
      await waitFor(() => {
        expect(onClose).toHaveBeenCalled();
      });
    });

    it('passes is_active value in the submitted payload', async () => {
      render(<UserAgent isOpen={true} onClose={vi.fn()} />);
      const checkbox = screen.getByTestId('checkbox-is-active');
      fireEvent.click(checkbox); // uncheck it
      fireEvent.click(screen.getByText('Submit'));
      await waitFor(() => {
        expect(UserAgentUtils.addUserAgent).toHaveBeenCalledWith(
          expect.objectContaining({ is_active: false })
        );
      });
    });
  });

  // ── useEffect reset ──────────────────────────────────────────────────────────

  describe('form reset on userAgent change', () => {
    it('resets form values when userAgent prop changes', () => {
      const { rerender } = render(
        <UserAgent
          isOpen={true}
          onClose={vi.fn()}
          userAgent={makeUserAgent()}
        />
      );
      expect(screen.getByTestId('input-Name')).toHaveValue('Chrome');

      rerender(
        <UserAgent
          isOpen={true}
          onClose={vi.fn()}
          userAgent={makeUserAgent({
            id: 2,
            name: 'Firefox',
            user_agent: 'Gecko/20100101',
          })}
        />
      );
      expect(screen.getByTestId('input-Name')).toHaveValue('Firefox');
    });

    it('resets to empty when userAgent prop is removed', () => {
      const { rerender } = render(
        <UserAgent
          isOpen={true}
          onClose={vi.fn()}
          userAgent={makeUserAgent()}
        />
      );
      rerender(<UserAgent isOpen={true} onClose={vi.fn()} userAgent={null} />);
      expect(screen.getByTestId('input-Name')).toHaveValue('');
    });
  });
});
