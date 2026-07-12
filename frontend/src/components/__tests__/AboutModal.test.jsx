import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import AboutModal from '../AboutModal';

// ── Store mock ─────────────────────────────────────────────────────────────────
vi.mock('../../store/settings', () => ({ default: vi.fn() }));

// ── Image mock ─────────────────────────────────────────────────────────────────
vi.mock('../../images/logo.png', () => ({ default: 'mocked-logo.png' }));

// ── Custom icons mock ──────────────────────────────────────────────────────────
vi.mock('../icons.jsx', () => ({
  DiscordIcon: ({ size }) => (
    <svg data-testid="discord-icon" data-size={size} />
  ),
  GitHubIcon: ({ size }) => <svg data-testid="github-icon" data-size={size} />,
}));

// ── lucide-react mock ──────────────────────────────────────────────────────────
vi.mock('lucide-react', () => ({
  BookOpen: ({ size }) => <svg data-testid="icon-book-open" data-size={size} />,
  Heart: ({ size }) => <svg data-testid="icon-heart" data-size={size} />,
  Users: ({ size }) => <svg data-testid="icon-users" data-size={size} />,
}));

// ── Mantine core mock ──────────────────────────────────────────────────────────
vi.mock('@mantine/core', async () => ({
  Box: ({ children, style }) => <div style={style}>{children}</div>,
  Button: ({ children, href, target, rel, variant, color, leftSection }) => (
    <a
      data-testid="button"
      href={href}
      target={target}
      rel={rel}
      data-variant={variant}
      data-color={color}
    >
      {leftSection}
      {children}
    </a>
  ),
  Divider: () => <hr data-testid="divider" />,
  Group: ({ children, justify }) => (
    <div data-justify={justify}>{children}</div>
  ),
  Modal: ({ children, opened, onClose, title, size }) =>
    opened ? (
      <div data-testid="modal" data-size={size}>
        <div data-testid="modal-title">{title}</div>
        <button data-testid="modal-close" onClick={onClose}>
          ×
        </button>
        {children}
      </div>
    ) : null,
  SimpleGrid: ({ children, cols }) => <div data-cols={cols}>{children}</div>,
  Stack: ({ children }) => <div>{children}</div>,
  Text: ({ children, fw, size, c, span }) =>
    span ? (
      <span data-fw={fw} data-size={size} data-color={c}>
        {children}
      </span>
    ) : (
      <p data-fw={fw} data-size={size} data-color={c}>
        {children}
      </p>
    ),
  Tooltip: ({ children, label, position }) => (
    <div data-tooltip={label} data-position={position}>
      {children}
    </div>
  ),
}));

// ──────────────────────────────────────────────────────────────────────────────
// Imports after mocks
// ──────────────────────────────────────────────────────────────────────────────
import useSettingsStore from '../../store/settings';

// ── Helpers ────────────────────────────────────────────────────────────────────
const setupStore = (version = { version: '1.2.3', timestamp: '20240601' }) => {
  vi.mocked(useSettingsStore).mockImplementation((sel) => sel({ version }));
};

describe('AboutModal', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // ── Visibility ───────────────────────────────────────────────────────────────

  describe('visibility', () => {
    it('renders modal content when isOpen is true', () => {
      setupStore();
      render(<AboutModal isOpen={true} onClose={vi.fn()} />);
      expect(screen.getByTestId('modal')).toBeInTheDocument();
    });

    it('does not render modal content when isOpen is false', () => {
      setupStore();
      render(<AboutModal isOpen={false} onClose={vi.fn()} />);
      expect(screen.queryByTestId('modal')).not.toBeInTheDocument();
    });

    it('calls onClose when close button is clicked', () => {
      setupStore();
      const onClose = vi.fn();
      render(<AboutModal isOpen={true} onClose={onClose} />);
      fireEvent.click(screen.getByTestId('modal-close'));
      expect(onClose).toHaveBeenCalledTimes(1);
    });

    it('renders with the correct modal title', () => {
      setupStore();
      render(<AboutModal isOpen={true} onClose={vi.fn()} />);
      expect(screen.getByTestId('modal-title')).toHaveTextContent(
        'About Dispatcharr'
      );
    });
  });

  // ── Version string ───────────────────────────────────────────────────────────

  describe('version string', () => {
    it('displays version with timestamp when both are present', () => {
      setupStore({ version: '2.0.0', timestamp: '20240601' });
      render(<AboutModal isOpen={true} onClose={vi.fn()} />);
      expect(screen.getByText('v2.0.0-20240601')).toBeInTheDocument();
    });

    it('displays version without timestamp when timestamp is null', () => {
      setupStore({ version: '1.5.0', timestamp: null });
      render(<AboutModal isOpen={true} onClose={vi.fn()} />);
      expect(screen.getByText('v1.5.0')).toBeInTheDocument();
    });

    it('displays version without timestamp when timestamp is undefined', () => {
      setupStore({ version: '1.5.0' });
      render(<AboutModal isOpen={true} onClose={vi.fn()} />);
      expect(screen.getByText('v1.5.0')).toBeInTheDocument();
    });

    it('falls back to v0.0.0 when version is undefined', () => {
      vi.mocked(useSettingsStore).mockImplementation((sel) =>
        sel({ version: undefined })
      );
      render(<AboutModal isOpen={true} onClose={vi.fn()} />);
      expect(screen.getByText('v0.0.0')).toBeInTheDocument();
    });

    it('falls back to v0.0.0 when version object has no version field', () => {
      setupStore({ version: '', timestamp: null });
      render(<AboutModal isOpen={true} onClose={vi.fn()} />);
      expect(screen.getByText('v0.0.0')).toBeInTheDocument();
    });
  });

  // ── Logo & branding ──────────────────────────────────────────────────────────

  describe('logo and branding', () => {
    it('renders the Dispatcharr logo', () => {
      setupStore();
      render(<AboutModal isOpen={true} onClose={vi.fn()} />);
      const logo = screen.getByAltText('Dispatcharr');
      expect(logo).toBeInTheDocument();
      expect(logo).toHaveAttribute('src', 'mocked-logo.png');
    });

    it('renders the app name "Dispatcharr"', () => {
      setupStore();
      render(<AboutModal isOpen={true} onClose={vi.fn()} />);
      expect(screen.getByText('Dispatcharr')).toBeInTheDocument();
    });
  });

  // ── Action buttons ───────────────────────────────────────────────────────────

  describe('action buttons', () => {
    it('renders the Documentation button with correct href', () => {
      setupStore();
      render(<AboutModal isOpen={true} onClose={vi.fn()} />);
      expect(screen.getByText('Documentation').closest('a')).toHaveAttribute(
        'href',
        'https://dispatcharr.github.io/Dispatcharr-Docs/'
      );
    });

    it('renders the Discord button with correct href', () => {
      setupStore();
      render(<AboutModal isOpen={true} onClose={vi.fn()} />);
      expect(screen.getByText('Discord').closest('a')).toHaveAttribute(
        'href',
        'https://discord.gg/Sp45V5BcxU'
      );
    });

    it('renders the GitHub button with correct href', () => {
      setupStore();
      render(<AboutModal isOpen={true} onClose={vi.fn()} />);
      expect(screen.getByText('GitHub').closest('a')).toHaveAttribute(
        'href',
        'https://github.com/Dispatcharr/Dispatcharr'
      );
    });

    it('renders the Donate button with correct href', () => {
      setupStore();
      render(<AboutModal isOpen={true} onClose={vi.fn()} />);
      expect(screen.getByText('Donate').closest('a')).toHaveAttribute(
        'href',
        'https://opencollective.com/dispatcharr/contribute'
      );
    });

    it('all external buttons open in a new tab', () => {
      setupStore();
      render(<AboutModal isOpen={true} onClose={vi.fn()} />);
      const buttons = screen.getAllByTestId('button');
      buttons.forEach((btn) => {
        expect(btn).toHaveAttribute('target', '_blank');
      });
    });

    it('all external buttons have noopener noreferrer rel', () => {
      setupStore();
      render(<AboutModal isOpen={true} onClose={vi.fn()} />);
      const buttons = screen.getAllByTestId('button');
      buttons.forEach((btn) => {
        expect(btn).toHaveAttribute('rel', 'noopener noreferrer');
      });
    });

    it('renders 4 action buttons', () => {
      setupStore();
      render(<AboutModal isOpen={true} onClose={vi.fn()} />);
      expect(screen.getAllByTestId('button')).toHaveLength(4);
    });
  });

  // ── Icons ────────────────────────────────────────────────────────────────────

  describe('icons', () => {
    it('renders BookOpen icon for Documentation button', () => {
      setupStore();
      render(<AboutModal isOpen={true} onClose={vi.fn()} />);
      expect(screen.getByTestId('icon-book-open')).toBeInTheDocument();
    });

    it('renders DiscordIcon for Discord button', () => {
      setupStore();
      render(<AboutModal isOpen={true} onClose={vi.fn()} />);
      expect(screen.getByTestId('discord-icon')).toBeInTheDocument();
    });

    it('renders GitHubIcon for GitHub button', () => {
      setupStore();
      render(<AboutModal isOpen={true} onClose={vi.fn()} />);
      expect(screen.getByTestId('github-icon')).toBeInTheDocument();
    });

    it('renders Heart icon for Donate button', () => {
      setupStore();
      render(<AboutModal isOpen={true} onClose={vi.fn()} />);
      expect(screen.getByTestId('icon-heart')).toBeInTheDocument();
    });

    it('renders Users icon in Contributors section', () => {
      setupStore();
      render(<AboutModal isOpen={true} onClose={vi.fn()} />);
      expect(screen.getByTestId('icon-users')).toBeInTheDocument();
    });
  });

  // ── Contributors section ─────────────────────────────────────────────────────

  describe('contributors section', () => {
    it('renders the Contributors heading', () => {
      setupStore();
      render(<AboutModal isOpen={true} onClose={vi.fn()} />);
      expect(screen.getByText('Contributors')).toBeInTheDocument();
    });

    it('renders the contributors description text', () => {
      setupStore();
      render(<AboutModal isOpen={true} onClose={vi.fn()} />);
      expect(
        screen.getByText(
          /Dispatcharr is built by the community, for the community/i
        )
      ).toBeInTheDocument();
    });
  });

  // ── Memorial section ─────────────────────────────────────────────────────────

  describe('memorial section', () => {
    it('renders the memorial text for Jesse Mann', () => {
      setupStore();
      render(<AboutModal isOpen={true} onClose={vi.fn()} />);
      expect(screen.getByText(/In memory of/i)).toBeInTheDocument();
    });

    it('renders Jesse Mann name in the memorial', () => {
      setupStore();
      render(<AboutModal isOpen={true} onClose={vi.fn()} />);
      expect(screen.getByText('Jesse Mann')).toBeInTheDocument();
    });

    it('renders the memorial tooltip with correct label', () => {
      setupStore();
      render(<AboutModal isOpen={true} onClose={vi.fn()} />);
      const tooltip = screen
        .getByText('Jesse Mann')
        .closest('[data-tooltip="Remembering Jesse Mann"]');
      expect(tooltip).toBeInTheDocument();
    });
  });
});
