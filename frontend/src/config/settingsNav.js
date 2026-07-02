import {
  ArrowLeftRight,
  CalendarDays,
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

export const SETTINGS_GROUPS = [
  {
    id: 'interface',
    label: 'Interface',
    adminOnly: false,
    sections: [
      { id: 'ui-settings', label: 'UI Settings', icon: Palette },
      { id: 'nav-order', label: 'Navigation', icon: Menu },
    ],
  },
  {
    id: 'streaming',
    label: 'Streaming',
    adminOnly: true,
    sections: [
      { id: 'stream-settings', label: 'Stream Settings', icon: Video },
      { id: 'proxy-settings', label: 'Proxy Settings', icon: ArrowLeftRight },
      { id: 'stream-profiles', label: 'Stream Profiles', icon: SlidersHorizontal },
      { id: 'output-profiles', label: 'Output Profiles', icon: FileOutput },
    ],
  },
  {
    id: 'dvr',
    label: 'DVR',
    adminOnly: true,
    sections: [
      { id: 'dvr-settings', label: 'DVR Settings', icon: Tv },
    ],
  },
  {
    id: 'epg',
    label: 'EPG',
    adminOnly: true,
    sections: [
      { id: 'epg-settings', label: 'EPG', icon: CalendarDays },
    ],
  },
  {
    id: 'network',
    label: 'Network',
    adminOnly: true,
    sections: [
      { id: 'user-agents', label: 'User-Agents', icon: Monitor },
      { id: 'network-access', label: 'Network Access', icon: Network },
    ],
  },
  {
    id: 'system',
    label: 'System',
    adminOnly: true,
    sections: [
      { id: 'system-settings', label: 'System Settings', icon: Settings2 },
      { id: 'user-limits', label: 'User Limits', icon: Users },
    ],
  },
  {
    id: 'backup',
    label: 'Backup',
    adminOnly: true,
    sections: [
      { id: 'backups', label: 'Backup & Restore', icon: DatabaseBackup },
    ],
  },
];
