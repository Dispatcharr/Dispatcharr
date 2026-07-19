import { render, screen } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import {
  PluginSecurityWarning,
  PluginSupportDisclaimer,
  PluginDowngradeWarning,
  PluginInfoNote,
  PluginRestartWarning,
} from '../PluginWarnings';

// ── Image mock ─────────────────────────────────────────────────────────────────
vi.mock('../../images/logo.png', () => ({ default: 'mocked-logo.png' }));

// ── lucide-react mock ──────────────────────────────────────────────────────────
vi.mock('lucide-react', () => ({
  AlertTriangle: ({ size }) => (
    <svg data-testid="icon-alert-triangle" data-size={size} />
  ),
  Info: ({ size }) => <svg data-testid="icon-info" data-size={size} />,
  OctagonAlert: ({ size }) => (
    <svg data-testid="icon-octagon-alert" data-size={size} />
  ),
}));

// ── Mantine core mock ──────────────────────────────────────────────────────────
vi.mock('@mantine/core', () => ({
  Box: ({ children, style }) => <div style={style}>{children}</div>,
  Text: ({ children, size, style }) => (
    <p data-size={size} style={style}>
      {children}
    </p>
  ),
}));

// ──────────────────────────────────────────────────────────────────────────────

describe('PluginWarnings', () => {
  // ── PluginSecurityWarning ────────────────────────────────────────────────────

  describe('PluginSecurityWarning', () => {
    it('renders children text', () => {
      render(
        <PluginSecurityWarning>This plugin is dangerous</PluginSecurityWarning>
      );
      expect(screen.getByText('This plugin is dangerous')).toBeInTheDocument();
    });

    it('renders the OctagonAlert icon', () => {
      render(<PluginSecurityWarning>Warning</PluginSecurityWarning>);
      expect(screen.getByTestId('icon-octagon-alert')).toBeInTheDocument();
    });

    it('does not render AlertTriangle or Info icons', () => {
      render(<PluginSecurityWarning>Warning</PluginSecurityWarning>);
      expect(
        screen.queryByTestId('icon-alert-triangle')
      ).not.toBeInTheDocument();
      expect(screen.queryByTestId('icon-info')).not.toBeInTheDocument();
    });

    it('renders different children correctly', () => {
      render(
        <PluginSecurityWarning>
          <strong>Critical</strong> security issue
        </PluginSecurityWarning>
      );
      expect(screen.getByText('Critical')).toBeInTheDocument();
    });
  });

  // ── PluginSupportDisclaimer ──────────────────────────────────────────────────

  describe('PluginSupportDisclaimer', () => {
    it('renders the disclaimer text', () => {
      render(<PluginSupportDisclaimer />);
      expect(
        screen.getByText(
          /Dispatcharr community support cannot assist with third-party plugin issues/i
        )
      ).toBeInTheDocument();
    });

    it('mentions plugin Discord thread', () => {
      render(<PluginSupportDisclaimer />);
      expect(
        screen.getByText(/use the plugin.*Discord thread/i)
      ).toBeInTheDocument();
    });

    it('mentions submitting an issue on the plugin repository', () => {
      render(<PluginSupportDisclaimer />);
      expect(
        screen.getByText(/submit an issue.*on the plugin.*repository/i)
      ).toBeInTheDocument();
    });

    it('renders the Dispatcharr logo image', () => {
      render(<PluginSupportDisclaimer />);
      const logo = screen.getByAltText('Dispatcharr');
      expect(logo).toBeInTheDocument();
      expect(logo).toHaveAttribute('src', 'mocked-logo.png');
    });

    it('renders logo as non-draggable', () => {
      render(<PluginSupportDisclaimer />);
      const logo = screen.getByAltText('Dispatcharr');
      expect(logo).toHaveAttribute('draggable', 'false');
    });

    it('does not render any lucide icons', () => {
      render(<PluginSupportDisclaimer />);
      expect(
        screen.queryByTestId('icon-octagon-alert')
      ).not.toBeInTheDocument();
      expect(
        screen.queryByTestId('icon-alert-triangle')
      ).not.toBeInTheDocument();
      expect(screen.queryByTestId('icon-info')).not.toBeInTheDocument();
    });
  });

  // ── PluginDowngradeWarning ───────────────────────────────────────────────────

  describe('PluginDowngradeWarning', () => {
    it('renders children text', () => {
      render(
        <PluginDowngradeWarning>
          Downgrading may break things
        </PluginDowngradeWarning>
      );
      expect(
        screen.getByText('Downgrading may break things')
      ).toBeInTheDocument();
    });

    it('renders the AlertTriangle icon', () => {
      render(<PluginDowngradeWarning>Caution</PluginDowngradeWarning>);
      expect(screen.getByTestId('icon-alert-triangle')).toBeInTheDocument();
    });

    it('does not render OctagonAlert or Info icons', () => {
      render(<PluginDowngradeWarning>Caution</PluginDowngradeWarning>);
      expect(
        screen.queryByTestId('icon-octagon-alert')
      ).not.toBeInTheDocument();
      expect(screen.queryByTestId('icon-info')).not.toBeInTheDocument();
    });

    it('renders JSX children correctly', () => {
      render(
        <PluginDowngradeWarning>
          <span data-testid="inner">Inner content</span>
        </PluginDowngradeWarning>
      );
      expect(screen.getByTestId('inner')).toBeInTheDocument();
    });
  });

  // ── PluginInfoNote ───────────────────────────────────────────────────────────

  describe('PluginInfoNote', () => {
    it('renders children text', () => {
      render(<PluginInfoNote>This is an informational note.</PluginInfoNote>);
      expect(
        screen.getByText('This is an informational note.')
      ).toBeInTheDocument();
    });

    it('renders the Info icon', () => {
      render(<PluginInfoNote>Note</PluginInfoNote>);
      expect(screen.getByTestId('icon-info')).toBeInTheDocument();
    });

    it('does not render OctagonAlert or AlertTriangle icons', () => {
      render(<PluginInfoNote>Note</PluginInfoNote>);
      expect(
        screen.queryByTestId('icon-octagon-alert')
      ).not.toBeInTheDocument();
      expect(
        screen.queryByTestId('icon-alert-triangle')
      ).not.toBeInTheDocument();
    });

    it('renders JSX children correctly', () => {
      render(
        <PluginInfoNote>
          <span data-testid="info-child">details</span>
        </PluginInfoNote>
      );
      expect(screen.getByTestId('info-child')).toBeInTheDocument();
    });
  });

  // ── PluginRestartWarning ─────────────────────────────────────────────────────

  describe('PluginRestartWarning', () => {
    it('renders the restart warning text', () => {
      render(<PluginRestartWarning />);
      expect(
        screen.getByText(/Importing a plugin may briefly restart the backend/i)
      ).toBeInTheDocument();
    });

    it('mentions temporary disconnect', () => {
      render(<PluginRestartWarning />);
      expect(
        screen.getByText(/you might see a.*temporary disconnect/i)
      ).toBeInTheDocument();
    });

    it('mentions automatic reconnect', () => {
      render(<PluginRestartWarning />);
      expect(
        screen.getByText(/the app will.*reconnect automatically/i)
      ).toBeInTheDocument();
    });

    it('renders the AlertTriangle icon', () => {
      render(<PluginRestartWarning />);
      expect(screen.getByTestId('icon-alert-triangle')).toBeInTheDocument();
    });

    it('does not render OctagonAlert or Info icons', () => {
      render(<PluginRestartWarning />);
      expect(
        screen.queryByTestId('icon-octagon-alert')
      ).not.toBeInTheDocument();
      expect(screen.queryByTestId('icon-info')).not.toBeInTheDocument();
    });
  });

  // ── Shared layout structure ──────────────────────────────────────────────────

  describe('shared layout structure', () => {
    it('PluginSecurityWarning renders xs Text', () => {
      render(<PluginSecurityWarning>msg</PluginSecurityWarning>);
      expect(screen.getByText('msg')).toHaveAttribute('data-size', 'xs');
    });

    it('PluginSupportDisclaimer renders xs Text', () => {
      render(<PluginSupportDisclaimer />);
      const text = screen.getByText(
        /Dispatcharr community support cannot assist/i
      );
      expect(text).toHaveAttribute('data-size', 'xs');
    });

    it('PluginDowngradeWarning renders xs Text', () => {
      render(<PluginDowngradeWarning>msg</PluginDowngradeWarning>);
      expect(screen.getByText('msg')).toHaveAttribute('data-size', 'xs');
    });

    it('PluginInfoNote renders xs Text', () => {
      render(<PluginInfoNote>msg</PluginInfoNote>);
      expect(screen.getByText('msg')).toHaveAttribute('data-size', 'xs');
    });

    it('PluginRestartWarning renders xs Text', () => {
      render(<PluginRestartWarning />);
      expect(screen.getByText(/Importing a plugin/i)).toHaveAttribute(
        'data-size',
        'xs'
      );
    });
  });
});
