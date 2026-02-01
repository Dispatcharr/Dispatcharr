import {
  ListOrdered,
  Play,
  Database,
  LayoutGrid,
  Settings as LucideSettings,
  ChartLine,
  Video,
  PlugZap,
  User,
  FileImage,
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
    path: '/plugins',
    adminOnly: true,
  },
  users: {
    id: 'users',
    label: 'Users',
    icon: User,
    path: '/users',
    adminOnly: true,
  },
  logos: {
    id: 'logos',
    label: 'Logo Manager',
    icon: FileImage,
    path: '/logos',
    adminOnly: true,
  },
  settings: {
    id: 'settings',
    label: 'Settings',
    icon: LucideSettings,
    path: '/settings',
    adminOnly: false,
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
  'users',
  'logos',
  'settings',
];

export const DEFAULT_USER_ORDER = [
  'channels',
  'guide',
  'settings',
];

export const getOrderedNavItems = (userOrder, isAdmin, channels = {}) => {
  const defaultOrder = isAdmin ? DEFAULT_ADMIN_ORDER : DEFAULT_USER_ORDER;
  const allowedItems = isAdmin
    ? Object.keys(NAV_ITEMS)
    : Object.keys(NAV_ITEMS).filter((id) => !NAV_ITEMS[id].adminOnly);

  let order;
  if (userOrder && Array.isArray(userOrder) && userOrder.length > 0) {
    // Filter saved order to only include allowed items
    const filteredOrder = userOrder.filter((id) => allowedItems.includes(id));

    // Find any new items that aren't in the saved order and append them
    const missingItems = allowedItems.filter((id) => !filteredOrder.includes(id));

    order = [...filteredOrder, ...missingItems];
  } else {
    order = defaultOrder;
  }

  return order.map((id) => {
    const item = NAV_ITEMS[id];
    if (!item) return null;

    const navItem = {
      id: item.id,
      label: item.label,
      icon: item.icon,
      path: item.path,
    };

    // Add badge for channels
    if (item.hasBadge && id === 'channels') {
      navItem.badge = `(${Object.keys(channels).length})`;
    }

    return navItem;
  }).filter(Boolean);
};
