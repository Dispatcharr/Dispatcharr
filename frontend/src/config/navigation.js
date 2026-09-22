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
  ScrollText,
  History,
  Library,
  SlidersHorizontal,
  Radio,
} from 'lucide-react';

// Shared by the top-level `settings` entry and the nested entry under
// `system.paths`, so the two stay in sync instead of drifting apart.
// `panel: 'settings'` marks this item as one that opens the sidebar's
// settings sub-panel instead of routing directly, so Sidebar.jsx can check
// `item.panel` instead of comparing against the '/settings' path string.
const SETTINGS_NAV_BASE = {
  label: 'Settings',
  icon: LucideSettings,
  path: '/settings',
  panel: 'settings',
};

export const NAV_ITEMS = {
  channels: {
    id: 'channels',
    label: 'Live',
    icon: Radio,
    adminOnly: false,
    paths: [
      {
        label: 'Channels',
        icon: ListOrdered,
        path: '/channels',
        hasBadge: true,
      },
      { label: 'TV Guide', icon: LayoutGrid, path: '/guide' },
      {
        label: 'DVR',
        icon: Database,
        path: '/dvr',
        requiresAccess: 'canViewDvr',
      },
    ],
  },
  vods: {
    id: 'vods',
    label: 'Video on Demand',
    icon: Video,
    adminOnly: true,
    paths: [
      { label: 'Library', icon: Library, path: '/vods' },
      {
        label: 'VOD Profiles',
        icon: SlidersHorizontal,
        path: '/vods/profiles',
        adminOnly: true,
      },
      {
        label: 'Playback History',
        icon: History,
        path: '/vods/playback-history',
        adminOnly: true,
      },
    ],
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
  'vods',
  'sources',
  'stats',
  'plugins',
  'system',
];

export const DEFAULT_USER_ORDER = ['channels', 'settings'];

/** True when a divider should render before navItems[idx] (start or end of a grouped section). */
export const isGroupBoundary = (navItems, idx) =>
  idx > 0 && Boolean(navItems[idx].paths || navItems[idx - 1].paths);

/**
 * Default nav order for a user. For standard users, inserts 'vods' after
 * 'channels' when canViewVod. DVR visibility is handled inside the Live group.
 * Shared by getOrderedNavItems and any caller (e.g. NavOrderForm) that needs
 * the default order on its own, such as to reset to defaults or revert an
 * optimistic update.
 */
export const getDefaultOrder = (isAdmin, { canViewVod = false } = {}) => {
  let order = isAdmin ? [...DEFAULT_ADMIN_ORDER] : [...DEFAULT_USER_ORDER];

  if (!isAdmin && canViewVod && !order.includes('vods')) {
    const channelsIdx = order.indexOf('channels');
    const insertAt = channelsIdx >= 0 ? channelsIdx + 1 : 0;
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
          paths: item.paths
            .filter(
              (entry) =>
                (!entry.adminOnly || isAdmin) &&
                (!entry.requires || access[entry.requires] !== false) &&
                (!entry.requiresAccess ||
                  access[entry.requiresAccess] !== false)
            )
            .map((entry) => ({
              ...entry,
              badge:
                entry.hasBadge && entry.path === '/channels'
                  ? `(${Array.isArray(channelIds) ? channelIds.length : 0})`
                  : entry.badge,
            })),
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
    })
    .filter(Boolean);
};
