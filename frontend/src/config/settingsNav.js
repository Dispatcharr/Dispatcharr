import { lazy } from 'react';
import {
  ArrowLeftRight,
  DatabaseBackup,
  FileOutput,
  Menu,
  Monitor,
  Network,
  Palette,
  Settings2,
  SlidersHorizontal,
  Tv,
  Users,
  Video,
} from 'lucide-react';

const UiSettingsForm = lazy(() => import('../components/forms/settings/UiSettingsForm.jsx'));
const NavOrderForm = lazy(() => import('../components/forms/settings/NavOrderForm.jsx'));
const StreamSettingsForm = lazy(() => import('../components/forms/settings/StreamSettingsForm.jsx'));
const ProxySettingsForm = lazy(() => import('../components/forms/settings/ProxySettingsForm.jsx'));
const StreamProfilesTable = lazy(() => import('../components/tables/StreamProfilesTable.jsx'));
const OutputProfilesTable = lazy(() => import('../components/tables/OutputProfilesTable.jsx'));
const DvrSettingsForm = lazy(() => import('../components/forms/settings/DvrSettingsForm.jsx'));
const UserAgentsTable = lazy(() => import('../components/tables/UserAgentsTable.jsx'));
const NetworkAccessForm = lazy(() => import('../components/forms/settings/NetworkAccessForm.jsx'));
const SystemSettingsForm = lazy(() => import('../components/forms/settings/SystemSettingsForm.jsx'));
const UserLimitsForm = lazy(() => import('../components/forms/settings/UserLimitsForm.jsx'));
const BackupManager = lazy(() => import('../components/backups/BackupManager.jsx'));

// Component lives on each section so it can never drift out of sync with the
// id used for routing/lookup (previously a separate COMPONENT_MAP keyed by
// the same ids, kept in sync only by convention).
export const SETTINGS_GROUPS = [
  {
    id: 'interface',
    label: 'Interface',
    adminOnly: false,
    sections: [
      { id: 'ui-settings', label: 'UI Settings', icon: Palette, Component: UiSettingsForm },
      { id: 'nav-order', label: 'Navigation', icon: Menu, Component: NavOrderForm },
    ],
  },
  {
    id: 'streaming',
    label: 'Streaming',
    adminOnly: true,
    sections: [
      { id: 'stream-settings', label: 'Stream Settings', icon: Video, Component: StreamSettingsForm },
      { id: 'proxy-settings', label: 'Proxy Settings', icon: ArrowLeftRight, Component: ProxySettingsForm },
      { id: 'stream-profiles', label: 'Stream Profiles', icon: SlidersHorizontal, Component: StreamProfilesTable },
      { id: 'output-profiles', label: 'Output Profiles', icon: FileOutput, Component: OutputProfilesTable },
    ],
  },
  {
    id: 'dvr',
    label: 'DVR',
    adminOnly: true,
    sections: [
      { id: 'dvr-settings', label: 'DVR Settings', icon: Tv, Component: DvrSettingsForm },
    ],
  },
  {
    id: 'network',
    label: 'Network',
    adminOnly: true,
    sections: [
      { id: 'user-agents', label: 'User-Agents', icon: Monitor, Component: UserAgentsTable },
      { id: 'network-access', label: 'Network Access', icon: Network, Component: NetworkAccessForm },
    ],
  },
  {
    id: 'system',
    label: 'System',
    adminOnly: true,
    sections: [
      { id: 'system-settings', label: 'System Settings', icon: Settings2, Component: SystemSettingsForm },
      { id: 'user-limits', label: 'User Limits', icon: Users, Component: UserLimitsForm },
    ],
  },
  {
    id: 'backup',
    label: 'Backup',
    adminOnly: true,
    sections: [
      { id: 'backups', label: 'Backup & Restore', icon: DatabaseBackup, Component: BackupManager },
    ],
  },
];

/** Settings groups visible to the current user (non-admin-only, or all if isAdmin). */
export const getVisibleSettingsGroups = (isAdmin) =>
  SETTINGS_GROUPS.filter((g) => !g.adminOnly || isAdmin);
