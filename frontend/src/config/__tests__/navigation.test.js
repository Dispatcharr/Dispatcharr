import { describe, it, expect } from 'vitest';
import {
  NAV_ITEMS,
  DEFAULT_ADMIN_ORDER,
  DEFAULT_USER_ORDER,
  getOrderedNavItems,
} from '../navigation';

describe('navigation config', () => {
  describe('NAV_ITEMS', () => {
    it('has all expected nav items', () => {
      expect(NAV_ITEMS.channels).toBeDefined();
      expect(NAV_ITEMS.vods).toBeDefined();
      expect(NAV_ITEMS.sources).toBeDefined();
      expect(NAV_ITEMS.guide).toBeDefined();
      expect(NAV_ITEMS.dvr).toBeDefined();
      expect(NAV_ITEMS.stats).toBeDefined();
      expect(NAV_ITEMS.plugins).toBeDefined();
      expect(NAV_ITEMS.users).toBeDefined();
      expect(NAV_ITEMS.logos).toBeDefined();
      expect(NAV_ITEMS.settings).toBeDefined();
    });

    it('has correct adminOnly flags', () => {
      expect(NAV_ITEMS.channels.adminOnly).toBe(false);
      expect(NAV_ITEMS.guide.adminOnly).toBe(false);
      expect(NAV_ITEMS.settings.adminOnly).toBe(false);

      expect(NAV_ITEMS.vods.adminOnly).toBe(true);
      expect(NAV_ITEMS.sources.adminOnly).toBe(true);
      expect(NAV_ITEMS.dvr.adminOnly).toBe(true);
      expect(NAV_ITEMS.stats.adminOnly).toBe(true);
      expect(NAV_ITEMS.plugins.adminOnly).toBe(true);
      expect(NAV_ITEMS.users.adminOnly).toBe(true);
      expect(NAV_ITEMS.logos.adminOnly).toBe(true);
    });
  });

  describe('DEFAULT_ADMIN_ORDER', () => {
    it('includes all nav items', () => {
      expect(DEFAULT_ADMIN_ORDER).toHaveLength(Object.keys(NAV_ITEMS).length);
      Object.keys(NAV_ITEMS).forEach((id) => {
        expect(DEFAULT_ADMIN_ORDER).toContain(id);
      });
    });
  });

  describe('DEFAULT_USER_ORDER', () => {
    it('only includes non-admin items', () => {
      DEFAULT_USER_ORDER.forEach((id) => {
        expect(NAV_ITEMS[id].adminOnly).toBe(false);
      });
    });

    it('includes channels, guide, and settings', () => {
      expect(DEFAULT_USER_ORDER).toContain('channels');
      expect(DEFAULT_USER_ORDER).toContain('guide');
      expect(DEFAULT_USER_ORDER).toContain('settings');
    });
  });

  describe('getOrderedNavItems', () => {
    it('returns default order when no saved order exists for admin', () => {
      const result = getOrderedNavItems(null, true);

      expect(result.map((item) => item.id)).toEqual(DEFAULT_ADMIN_ORDER);
    });

    it('returns default order when no saved order exists for non-admin', () => {
      const result = getOrderedNavItems(null, false);

      expect(result.map((item) => item.id)).toEqual(DEFAULT_USER_ORDER);
    });

    it('returns default order when saved order is empty array', () => {
      const result = getOrderedNavItems([], true);

      expect(result.map((item) => item.id)).toEqual(DEFAULT_ADMIN_ORDER);
    });

    it('uses custom order when provided', () => {
      const customOrder = ['settings', 'channels', 'vods', 'sources', 'guide', 'dvr', 'stats', 'plugins', 'users', 'logos'];
      const result = getOrderedNavItems(customOrder, true);

      expect(result.map((item) => item.id)).toEqual(customOrder);
    });

    it('appends missing items to end of saved order', () => {
      // Simulate a saved order that is missing some newer items
      const savedOrder = ['channels', 'vods', 'sources'];
      const result = getOrderedNavItems(savedOrder, true);

      // First items should be in saved order
      expect(result[0].id).toBe('channels');
      expect(result[1].id).toBe('vods');
      expect(result[2].id).toBe('sources');

      // All items should be present
      expect(result).toHaveLength(Object.keys(NAV_ITEMS).length);

      // Missing items should be appended at the end
      const resultIds = result.map((item) => item.id);
      expect(resultIds).toContain('guide');
      expect(resultIds).toContain('settings');
    });

    it('filters out admin-only items for non-admin users', () => {
      const customOrder = ['channels', 'vods', 'sources', 'guide', 'dvr', 'settings'];
      const result = getOrderedNavItems(customOrder, false);

      const resultIds = result.map((item) => item.id);

      // Should only include non-admin items
      expect(resultIds).toContain('channels');
      expect(resultIds).toContain('guide');
      expect(resultIds).toContain('settings');

      // Should not include admin-only items
      expect(resultIds).not.toContain('vods');
      expect(resultIds).not.toContain('sources');
      expect(resultIds).not.toContain('dvr');
    });

    it('filters out unknown items from saved order', () => {
      const savedOrder = ['channels', 'unknown_item', 'vods', 'invalid', 'settings'];
      const result = getOrderedNavItems(savedOrder, true);

      const resultIds = result.map((item) => item.id);

      expect(resultIds).not.toContain('unknown_item');
      expect(resultIds).not.toContain('invalid');
      expect(resultIds).toContain('channels');
      expect(resultIds).toContain('vods');
      expect(resultIds).toContain('settings');
    });

    it('adds channel badge with correct count', () => {
      const channels = { 1: {}, 2: {}, 3: {} };
      const result = getOrderedNavItems(null, true, channels);

      const channelItem = result.find((item) => item.id === 'channels');
      expect(channelItem.badge).toBe('(3)');
    });

    it('returns items with correct structure', () => {
      const result = getOrderedNavItems(null, true);

      result.forEach((item) => {
        expect(item).toHaveProperty('id');
        expect(item).toHaveProperty('label');
        expect(item).toHaveProperty('icon');
        expect(item).toHaveProperty('path');
      });
    });

    it('preserves order when user changes role from admin to non-admin', () => {
      // Admin saved a custom order
      const adminSavedOrder = ['settings', 'vods', 'channels', 'sources', 'guide', 'dvr', 'stats', 'plugins', 'users', 'logos'];

      // When user is demoted to non-admin, only allowed items should show
      const result = getOrderedNavItems(adminSavedOrder, false);
      const resultIds = result.map((item) => item.id);

      // Order should be preserved for allowed items
      expect(resultIds[0]).toBe('settings');
      expect(resultIds[1]).toBe('channels');
      expect(resultIds[2]).toBe('guide');

      // Should only have non-admin items
      expect(resultIds).toHaveLength(3);
    });
  });
});
