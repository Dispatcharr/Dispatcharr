import {
  render,
  screen,
  waitFor,
} from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import SettingsPage from '../Settings';
import useAuthStore from '../../store/auth';
import { USER_LEVELS } from '../../constants';
import userEvent from '@testing-library/user-event';

// Mock all dependencies
vi.mock('../../store/auth');
vi.mock('../../components/tables/UserAgentsTable', () => ({
  default: ({ active }) => <div data-testid="user-agents-table">UserAgentsTable {active ? 'active' : 'inactive'}</div>,
}));
vi.mock('../../components/tables/StreamProfilesTable', () => ({
  default: ({ active }) => <div data-testid="stream-profiles-table">StreamProfilesTable {active ? 'active' : 'inactive'}</div>,
}));
vi.mock('../../components/backups/BackupManager', () => ({
  default: ({ active }) => <div data-testid="backup-manager">BackupManager {active ? 'active' : 'inactive'}</div>,
}));
vi.mock('../../components/forms/settings/UiSettingsForm', () => ({
  default: ({ active }) => <div data-testid="ui-settings-form">UiSettingsForm {active ? 'active' : 'inactive'}</div>,
}));
vi.mock('../../components/forms/settings/NetworkAccessForm', () => ({
  default: ({ active }) => <div data-testid="network-access-form">NetworkAccessForm {active ? 'active' : 'inactive'}</div>,
}));
vi.mock('../../components/forms/settings/ProxySettingsForm', () => ({
  default: ({ active }) => <div data-testid="proxy-settings-form">ProxySettingsForm {active ? 'active' : 'inactive'}</div>,
}));
vi.mock('../../components/forms/settings/StreamSettingsForm', () => ({
  default: ({ active }) => <div data-testid="stream-settings-form">StreamSettingsForm {active ? 'active' : 'inactive'}</div>,
}));
vi.mock('../../components/forms/settings/DvrSettingsForm', () => ({
  default: ({ active }) => <div data-testid="dvr-settings-form">DvrSettingsForm {active ? 'active' : 'inactive'}</div>,
}));
vi.mock('../../components/forms/settings/SystemSettingsForm', () => ({
  default: ({ active }) => <div data-testid="system-settings-form">SystemSettingsForm {active ? 'active' : 'inactive'}</div>,
}));
vi.mock('../../components/forms/settings/NavOrderForm', () => ({
  default: ({ active }) => <div data-testid="nav-order-form">NavOrderForm {active ? 'active' : 'inactive'}</div>,
}));
vi.mock('../../components/ErrorBoundary', () => ({
  default: ({ children }) => <div data-testid="error-boundary">{children}</div>,
}));

vi.mock('@mantine/core', async () => {
  const accordionComponent = ({ children, onChange, defaultValue }) => <div data-testid="accordion">{children}</div>;
  accordionComponent.Item = ({ children, value }) => (
    <div data-testid={`accordion-item-${value}`}>{children}</div>
  );
  accordionComponent.Control = ({ children }) => (
    <button data-testid="accordion-control">{children}</button>
  );
  accordionComponent.Panel = ({ children }) => (
    <div data-testid="accordion-panel">{children}</div>
  );

  return {
    Accordion: accordionComponent,
    AccordionItem: accordionComponent.Item,
    AccordionControl: accordionComponent.Control,
    AccordionPanel: accordionComponent.Panel,
    Box: ({ children }) => <div>{children}</div>,
    Center: ({ children }) => <div>{children}</div>,
    Loader: () => <div data-testid="loader">Loading...</div>,
    Text: ({ children }) => <span>{children}</span>,
  };
});


describe('SettingsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('Rendering for Regular User', () => {
    beforeEach(() => {
      useAuthStore.mockReturnValue({
        user_level: USER_LEVELS.USER,
        username: 'testuser',
      });
    });

    it('renders the settings page', () => {
      render(<SettingsPage />);

      expect(screen.getByTestId('accordion')).toBeInTheDocument();
    });

    it('renders UI Settings accordion item', () => {
      render(<SettingsPage />);

      expect(screen.getByTestId('accordion-item-ui-settings')).toBeInTheDocument();
      expect(screen.getByText('UI Settings')).toBeInTheDocument();
    });

    it('opens UI Settings panel by default', () => {
      render(<SettingsPage />);

      expect(screen.getByTestId('ui-settings-form')).toBeInTheDocument();
    });

    it('does not render admin-only sections for regular users', () => {
      render(<SettingsPage />);

      expect(screen.queryByText('DVR')).not.toBeInTheDocument();
      expect(screen.queryByText('Stream Settings')).not.toBeInTheDocument();
      expect(screen.queryByText('System Settings')).not.toBeInTheDocument();
      expect(screen.queryByText('User-Agents')).not.toBeInTheDocument();
      expect(screen.queryByText('Stream Profiles')).not.toBeInTheDocument();
      expect(screen.queryByText('Network Access')).not.toBeInTheDocument();
      expect(screen.queryByText('Proxy Settings')).not.toBeInTheDocument();
      expect(screen.queryByText('Backup & Restore')).not.toBeInTheDocument();
    });

    it('renders Navigation accordion item for regular users', () => {
      render(<SettingsPage />);

      expect(screen.getByTestId('accordion-item-nav-order')).toBeInTheDocument();
      expect(screen.getByText('Navigation')).toBeInTheDocument();
    });
  });

  describe('Rendering for Admin User', () => {
    beforeEach(() => {
      useAuthStore.mockReturnValue({
        user_level: USER_LEVELS.ADMIN,
        username: 'admin',
      });
    });

    it('renders all accordion items for admin', async () => {
      render(<SettingsPage />);

      expect(screen.getByText('UI Settings')).toBeInTheDocument();

      await waitFor(() => {
        expect(screen.getByText('DVR')).toBeInTheDocument();
        expect(screen.getByText('Stream Settings')).toBeInTheDocument();
        expect(screen.getByText('System Settings')).toBeInTheDocument();
        expect(screen.getByText('User-Agents')).toBeInTheDocument();
        expect(screen.getByText('Stream Profiles')).toBeInTheDocument();
        expect(screen.getByText('Network Access')).toBeInTheDocument();
        expect(screen.getByText('Proxy Settings')).toBeInTheDocument();
        expect(screen.getByText('Backup & Restore')).toBeInTheDocument();
        expect(screen.getByText('Navigation')).toBeInTheDocument();
      });
    });

    it('renders DVR settings accordion item', () => {
      render(<SettingsPage />);

      expect(screen.getByTestId('accordion-item-dvr-settings')).toBeInTheDocument();
    });

    it('renders Stream Settings accordion item', () => {
      render(<SettingsPage />);

      expect(screen.getByTestId('accordion-item-stream-settings')).toBeInTheDocument();
    });

    it('renders System Settings accordion item', () => {
      render(<SettingsPage />);

      expect(screen.getByTestId('accordion-item-system-settings')).toBeInTheDocument();
    });

    it('renders User-Agents accordion item', () => {
      render(<SettingsPage />);

      expect(screen.getByTestId('accordion-item-user-agents')).toBeInTheDocument();
    });

    it('renders Stream Profiles accordion item', () => {
      render(<SettingsPage />);

      expect(screen.getByTestId('accordion-item-stream-profiles')).toBeInTheDocument();
    });

    it('renders Network Access accordion item', () => {
      render(<SettingsPage />);

      expect(screen.getByTestId('accordion-item-network-access')).toBeInTheDocument();
    });

    it('renders Proxy Settings accordion item', () => {
      render(<SettingsPage />);

      expect(screen.getByTestId('accordion-item-proxy-settings')).toBeInTheDocument();
    });

    it('renders Backup & Restore accordion item', () => {
      render(<SettingsPage />);

      expect(screen.getByTestId('accordion-item-backups')).toBeInTheDocument();
    });

    it('renders Navigation accordion item', () => {
      render(<SettingsPage />);

      expect(screen.getByTestId('accordion-item-nav-order')).toBeInTheDocument();
    });
  });

  describe('Accordion Interactions', () => {
    beforeEach(() => {
      useAuthStore.mockReturnValue({
        user_level: USER_LEVELS.ADMIN,
        username: 'admin',
      });
    });

    it('opens DVR settings when clicked', async () => {
      const user = userEvent.setup();
      render(<SettingsPage />);

      const streamSettingsButton = screen.getByText('DVR');
      await user.click(streamSettingsButton);

      await screen.findByTestId('dvr-settings-form');
    });
  });
});