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
  Webhook,
  MonitorCog,
  ScrollText,
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
    section: 'Live TV',
  },
  vods: {
    id: 'vods',
    label: 'Library',
    icon: Video,
    path: '/vods',
    adminOnly: true,
    section: 'Video on Demand',
  },
  sources: {
    id: 'sources',
    label: 'Sources',
    icon: Play,
    adminOnly: true,
    paths: [
      { label: 'M3U Accounts', icon: Play, path: '/sources/m3u' },
      { label: 'EPG Sources', icon: Database, path: '/sources/epg' },
    ],
  },
  guide: {
    id: 'guide',
    label: 'TV Guide',
    icon: LayoutGrid,
    path: '/guide',
    adminOnly: false,
    section: 'Live TV',
  },
  dvr: {
    id: 'dvr',
    label: 'DVR',
    icon: Database,
    path: '/dvr',
    adminOnly: true,
    section: 'Live TV',
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
    panel: 'plugins',
    adminOnly: true,
    // Sidebar.jsx renders pinned-plugin rows (from usePluginStore + the
    // user's pinnedPlugins preference) directly beneath this entry in the
    // primary nav, in addition to the full list living in the slide-over.
    dynamicPinned: true,
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
      { label: 'Logs', icon: ScrollText, path: '/logs', requires: 'logPersist' },
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
  'guide',
  'dvr',
  'vods',
  'sources',
  'stats',
  'plugins',
  'system',
];

export const DEFAULT_USER_ORDER = ['channels', 'guide', 'settings'];

/** Whether a nav item renders as its own visually-grouped block (heading + rows). */
const isGroupedItem = (item) => Boolean(item.paths || item.dynamicPinned);

/** True when a divider should render before navItems[idx] (start or end of a grouped section). */
export const isGroupBoundary = (navItems, idx) =>
  idx > 0 &&
  Boolean(
    isGroupedItem(navItems[idx]) ||
    isGroupedItem(navItems[idx - 1]) ||
    navItems[idx].section !== navItems[idx - 1].section
  );

/**
 * Default nav order keeps Live items together, followed by the VOD library.
 * Shared by getOrderedNavItems and any caller (e.g. NavOrderForm) that needs
 * the default order on its own, such as to reset to defaults or revert an
 * optimistic update.
 */
export const getDefaultOrder = (
  isAdmin,
  { canViewDvr = false, canViewVod = false } = {}
) => {
  let order = isAdmin ? [...DEFAULT_ADMIN_ORDER] : [...DEFAULT_USER_ORDER];

  if (!isAdmin && canViewDvr && !order.includes('dvr')) {
    const guideIdx = order.indexOf('guide');
    const insertAt = guideIdx >= 0 ? guideIdx + 1 : order.length - 1;
    order = [...order.slice(0, insertAt), 'dvr', ...order.slice(insertAt)];
  }

  if (!isAdmin && canViewVod && !order.includes('vods')) {
    const lastLiveIdx = Math.max(
      order.indexOf('channels'),
      order.indexOf('guide'),
      order.indexOf('dvr')
    );
    const insertAt = lastLiveIdx + 1;
    order = [...order.slice(0, insertAt), 'vods', ...order.slice(insertAt)];
  }

  return order;
};

export const getOrderedNavItems = (
  userOrder,
  isAdmin,
  channelIds = [],
  access = {}
) => {
  const defaultOrder = getDefaultOrder(isAdmin, access);

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

  return order
    .map((id) => {
      const item = NAV_ITEMS[id];
      if (!item) return null;

      // Group item (has paths array)
      if (item.paths) {
        return {
          id: item.id,
          label: item.label,
          icon: item.icon,
          // A missing flag keeps the entry.
          paths: item.paths.filter(
            (entry) => !entry.requires || access[entry.requires] !== false
          ),
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
        section: item.section,
        dynamicPinned: item.dynamicPinned,
      };

      // Add badge for channels
      if (id === 'channels') {
        navItem.badge = `(${Array.isArray(channelIds) ? channelIds.length : 0})`;
      }

      return navItem;
    })
    .filter(Boolean);
};
