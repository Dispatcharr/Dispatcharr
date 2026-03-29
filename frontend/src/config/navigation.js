import {
  ListOrdered,
  Play,
  Database,
  LayoutGrid,
  Settings as LucideSettings,
  ChartLine,
  Video,
  PlugZap,
  Package,
  Download,
  User,
  FileImage,
  Webhook,
  Logs,
  Blocks,
  MonitorCog,
} from 'lucide-react';

export const NAV_ITEMS = {
  channels: {
    id: 'channels',
    label: 'Channels',
    icon: ListOrdered,
    path: '/channels',
    adminOnly: false,
    hasBadge: true,
  },
  vods: {
    id: 'vods',
    label: 'VODs',
    icon: Video,
    path: '/vods',
    adminOnly: true,
  },
  sources: {
    id: 'sources',
    label: 'M3U & EPG Manager',
    icon: Play,
    path: '/sources',
    adminOnly: true,
  },
  guide: {
    id: 'guide',
    label: 'TV Guide',
    icon: LayoutGrid,
    path: '/guide',
    adminOnly: false,
  },
  dvr: {
    id: 'dvr',
    label: 'DVR',
    icon: Database,
    path: '/dvr',
    adminOnly: true,
  },
  stats: {
    id: 'stats',
    label: 'Stats',
    icon: ChartLine,
    path: '/stats',
    adminOnly: true,
  },
  plugins: {
    id: 'plugins',
    label: 'Plugins',
    icon: PlugZap,
    adminOnly: true,
    paths: [
      { label: 'My Plugins', icon: Package, path: '/plugins' },
      { label: 'Find Plugins', icon: Download, path: '/plugins/browse' },
    ],
  },
  integrations: {
    id: 'integrations',
    label: 'Integrations',
    icon: Blocks,
    adminOnly: true,
    paths: [
      { label: 'Connections', icon: Webhook, path: '/connect' },
      { label: 'Logs', icon: Logs, path: '/connect/logs' },
    ],
  },
  system: {
    id: 'system',
    label: 'System',
    icon: MonitorCog,
    adminOnly: true,
    canHide: false,
    paths: [
      { label: 'Users', icon: User, path: '/users' },
      { label: 'Logo Manager', icon: FileImage, path: '/logos' },
      { label: 'Settings', icon: LucideSettings, path: '/settings' },
    ],
  },
  settings: {
    id: 'settings',
    label: 'Settings',
    icon: LucideSettings,
    path: '/settings',
    adminOnly: false,
    canHide: false,
  },
};

export const DEFAULT_ADMIN_ORDER = [
  'channels',
  'vods',
  'sources',
  'guide',
  'dvr',
  'stats',
  'plugins',
  'integrations',
  'system',
];

export const DEFAULT_USER_ORDER = [
  'channels',
  'guide',
  'settings',
];

export const getOrderedNavItems = (userOrder, isAdmin, channelIds = []) => {
  const defaultOrder = isAdmin ? DEFAULT_ADMIN_ORDER : DEFAULT_USER_ORDER;

  let order;
  if (userOrder && Array.isArray(userOrder) && userOrder.length > 0) {
    // Filter saved order to only include allowed items
    const filteredOrder = userOrder.filter((id) => defaultOrder.includes(id));

    // Find any new items that aren't in the saved order and append them
    const missingItems = defaultOrder.filter(
      (id) => !filteredOrder.includes(id)
    );

    order = [...filteredOrder, ...missingItems];
  } else {
    order = defaultOrder;
  }

  return order.map((id) => {
    const item = NAV_ITEMS[id];
    if (!item) return null;

    // Group item (has paths array)
    if (item.paths) {
      return {
        id: item.id,
        label: item.label,
        icon: item.icon,
        paths: item.paths,
        canHide: item.canHide,
      };
    }

    const navItem = {
      id: item.id,
      label: item.label,
      icon: item.icon,
      path: item.path,
      canHide: item.canHide,
    };

    // Add badge for channels
    if (id === 'channels') {
      navItem.badge = `(${Array.isArray(channelIds) ? channelIds.length : 0})`;
    }

    return navItem;
  }).filter(Boolean);
};
