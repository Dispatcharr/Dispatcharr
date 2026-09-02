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
  MonitorCog,
} from 'lucide-react';

// Shared by the top-level `settings` entry and the nested entry under
// `system.paths`, so the two stay in sync instead of drifting apart.
// `panel: 'settings'` marks this item as one that opens the sidebar's
// settings sub-panel instead of routing directly, so Sidebar.jsx can check
// `item.panel` instead of comparing against the '/settings' path string.
const SETTINGS_NAV_BASE = { label: 'Settings', icon: LucideSettings, path: '/settings', panel: 'settings' };

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
  system: {
    id: 'system',
    label: 'System',
    icon: MonitorCog,
    adminOnly: true,
    canHide: false,
    paths: [
      { label: 'Users', icon: User, path: '/users' },
      { label: 'Logo Manager', icon: FileImage, path: '/logos' },
      { label: 'Connect', icon: Webhook, path: '/connect' },
      { ...SETTINGS_NAV_BASE },
    ],
  },
  settings: {
    id: 'settings',
    ...SETTINGS_NAV_BASE,
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
  'system',
];

export const DEFAULT_USER_ORDER = [
  'channels',
  'guide',
  'settings',
];

/** True when a divider should render before navItems[idx] (start or end of a grouped section). */
export const isGroupBoundary = (navItems, idx) =>
  idx > 0 && Boolean(navItems[idx].paths || navItems[idx - 1].paths);

/**
 * Default nav order for a user. For standard users, inserts 'vods' after
 * 'channels' when canViewVod, and 'dvr' after 'guide' when canViewDvr.
 * Shared by getOrderedNavItems and any caller (e.g. NavOrderForm) that needs
 * the default order on its own, such as to reset to defaults or revert an
 * optimistic update.
 */
export const getDefaultOrder = (
  isAdmin,
  { canViewDvr = false, canViewVod = false } = {}
) => {
  let order = isAdmin ? [...DEFAULT_ADMIN_ORDER] : [...DEFAULT_USER_ORDER];

  if (!isAdmin && canViewVod && !order.includes('vods')) {
    const channelsIdx = order.indexOf('channels');
    const insertAt = channelsIdx >= 0 ? channelsIdx + 1 : 0;
    order = [...order.slice(0, insertAt), 'vods', ...order.slice(insertAt)];
  }

  if (!isAdmin && canViewDvr && !order.includes('dvr')) {
    const guideIdx = order.indexOf('guide');
    const insertAt = guideIdx >= 0 ? guideIdx + 1 : order.length - 1;
    order = [...order.slice(0, insertAt), 'dvr', ...order.slice(insertAt)];
  }

  return order;
};

export const getOrderedNavItems = (
  userOrder,
  isAdmin,
  channelIds = [],
  { canViewDvr = false, canViewVod = false } = {}
) => {
  const defaultOrder = getDefaultOrder(isAdmin, { canViewDvr, canViewVod });

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
      panel: item.panel,
    };

    // Add badge for channels
    if (id === 'channels') {
      navItem.badge = `(${Array.isArray(channelIds) ? channelIds.length : 0})`;
    }

    return navItem;
  }).filter(Boolean);
};
