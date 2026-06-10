import { render, screen, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import SettingsPage from '../Settings';
import useAuthStore from '../../store/auth';
import { USER_LEVELS } from '../../constants';

vi.mock('../../store/auth');
vi.mock('../../components/tables/UserAgentsTable', () => ({
  default: ({ active }) => (
    <div data-testid="user-agents-table">UserAgentsTable {active ? 'active' : 'inactive'}</div>
  ),
}));
vi.mock('../../components/tables/StreamProfilesTable', () => ({
  default: ({ active }) => (
    <div data-testid="stream-profiles-table">StreamProfilesTable {active ? 'active' : 'inactive'}</div>
  ),
}));
vi.mock('../../components/backups/BackupManager', () => ({
  default: ({ active }) => (
    <div data-testid="backup-manager">BackupManager {active ? 'active' : 'inactive'}</div>
  ),
}));
vi.mock('../../components/forms/settings/UiSettingsForm', () => ({
  default: ({ active }) => (
    <div data-testid="ui-settings-form">UiSettingsForm {active ? 'active' : 'inactive'}</div>
  ),
}));
vi.mock('../../components/forms/settings/NetworkAccessForm', () => ({
  default: ({ active }) => (
    <div data-testid="network-access-form">NetworkAccessForm {active ? 'active' : 'inactive'}</div>
  ),
}));
vi.mock('../../components/forms/settings/ProxySettingsForm', () => ({
  default: ({ active }) => (
    <div data-testid="proxy-settings-form">ProxySettingsForm {active ? 'active' : 'inactive'}</div>
  ),
}));
vi.mock('../../components/forms/settings/StreamSettingsForm', () => ({
  default: ({ active }) => (
    <div data-testid="stream-settings-form">StreamSettingsForm {active ? 'active' : 'inactive'}</div>
  ),
}));
vi.mock('../../components/forms/settings/DvrSettingsForm', () => ({
  default: ({ active }) => (
    <div data-testid="dvr-settings-form">DvrSettingsForm {active ? 'active' : 'inactive'}</div>
  ),
}));
vi.mock('../../components/forms/settings/SystemSettingsForm', () => ({
  default: ({ active }) => (
    <div data-testid="system-settings-form">SystemSettingsForm {active ? 'active' : 'inactive'}</div>
  ),
}));
vi.mock('../../components/forms/settings/NavOrderForm', () => ({
  default: ({ active }) => (
    <div data-testid="nav-order-form">NavOrderForm {active ? 'active' : 'inactive'}</div>
  ),
}));
vi.mock('../../components/forms/settings/UserLimitsForm', () => ({
  default: ({ active }) => (
    <div data-testid="user-limits-form">UserLimitsForm {active ? 'active' : 'inactive'}</div>
  ),
}));
vi.mock('../../components/ErrorBoundary', () => ({
  default: ({ children }) => <div data-testid="error-boundary">{children}</div>,
}));

vi.mock('@mantine/core', async () => ({
  Box: ({ children }) => <div>{children}</div>,
  Divider: () => <hr />,
  Loader: () => <div data-testid="loader">Loading...</div>,
  Text: ({ children }) => <span>{children}</span>,
}));

const renderWithRouter = (component, { initialEntries = ['/settings'] } = {}) =>
  render(<MemoryRouter initialEntries={initialEntries}>{component}</MemoryRouter>);

describe('SettingsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('no section selected', () => {
    beforeEach(() => {
      useAuthStore.mockReturnValue({ user_level: USER_LEVELS.USER, username: 'testuser' });
    });

    it('shows placeholder when no hash', () => {
      renderWithRouter(<SettingsPage />);
      expect(screen.getByText('Select a setting from the sidebar')).toBeInTheDocument();
    });
  });

  describe('regular user', () => {
    beforeEach(() => {
      useAuthStore.mockReturnValue({ user_level: USER_LEVELS.USER, username: 'testuser' });
    });

    it('renders ui-settings section via hash', async () => {
      renderWithRouter(<SettingsPage />, { initialEntries: ['/settings#ui-settings'] });
      await waitFor(() => {
        expect(screen.getByTestId('ui-settings-form')).toBeInTheDocument();
      });
      expect(screen.getByText('UI Settings')).toBeInTheDocument();
    });

    it('renders nav-order section via hash', async () => {
      renderWithRouter(<SettingsPage />, { initialEntries: ['/settings#nav-order'] });
      await waitFor(() => {
        expect(screen.getByTestId('nav-order-form')).toBeInTheDocument();
      });
    });

    it('shows placeholder for admin-only section hash', () => {
      renderWithRouter(<SettingsPage />, { initialEntries: ['/settings#dvr-settings'] });
      expect(screen.getByText('Select a setting from the sidebar')).toBeInTheDocument();
    });
  });

  describe('admin user', () => {
    beforeEach(() => {
      useAuthStore.mockReturnValue({ user_level: USER_LEVELS.ADMIN, username: 'admin' });
    });

    it('renders dvr-settings section via hash', async () => {
      renderWithRouter(<SettingsPage />, { initialEntries: ['/settings#dvr-settings'] });
      await waitFor(() => {
        expect(screen.getByTestId('dvr-settings-form')).toBeInTheDocument();
      });
      expect(screen.getByText('DVR Settings')).toBeInTheDocument();
    });

    it('renders stream-settings section via hash', async () => {
      renderWithRouter(<SettingsPage />, { initialEntries: ['/settings#stream-settings'] });
      await waitFor(() => {
        expect(screen.getByTestId('stream-settings-form')).toBeInTheDocument();
      });
    });

    it('renders stream-profiles section via hash', async () => {
      renderWithRouter(<SettingsPage />, { initialEntries: ['/settings#stream-profiles'] });
      await waitFor(() => {
        expect(screen.getByTestId('stream-profiles-table')).toBeInTheDocument();
      });
    });

    it('renders network-access section via hash', async () => {
      renderWithRouter(<SettingsPage />, { initialEntries: ['/settings#network-access'] });
      await waitFor(() => {
        expect(screen.getByTestId('network-access-form')).toBeInTheDocument();
      });
    });

    it('renders proxy-settings section via hash', async () => {
      renderWithRouter(<SettingsPage />, { initialEntries: ['/settings#proxy-settings'] });
      await waitFor(() => {
        expect(screen.getByTestId('proxy-settings-form')).toBeInTheDocument();
      });
    });

    it('renders backups section via hash', async () => {
      renderWithRouter(<SettingsPage />, { initialEntries: ['/settings#backups'] });
      await waitFor(() => {
        expect(screen.getByTestId('backup-manager')).toBeInTheDocument();
      });
    });

    it('renders system-settings section via hash', async () => {
      renderWithRouter(<SettingsPage />, { initialEntries: ['/settings#system-settings'] });
      await waitFor(() => {
        expect(screen.getByTestId('system-settings-form')).toBeInTheDocument();
      });
    });

    it('passes active=true to rendered component', async () => {
      renderWithRouter(<SettingsPage />, { initialEntries: ['/settings#dvr-settings'] });
      await waitFor(() => {
        expect(screen.getByText(/active/)).toBeInTheDocument();
      });
      expect(screen.getByText('DvrSettingsForm active')).toBeInTheDocument();
    });
  });
});
