import { create } from 'zustand';

// Store for managing system notifications (version updates, recommended settings, announcements)
const useNotificationsStore = create((set, get) => ({
  notifications: [],
  unreadCount: 0,
  isLoading: false,
  error: null,
  lastFetched: null,

  // Set notifications directly (used by API layer)
  setNotifications: (notifications) => {
    const unreadCount = notifications.filter((n) => !n.is_dismissed).length;
    set({
      notifications,
      unreadCount,
      lastFetched: new Date().toISOString(),
    });
  },

  // Add a new notification (e.g., from WebSocket)
  addNotification: (notification) => {
    set((state) => {
      const exists = state.notifications.some(
        (n) => n.notification_key === notification.notification_key
      );
      if (exists) {
        // Update existing notification
        return {
          notifications: state.notifications.map((n) =>
            n.notification_key === notification.notification_key
              ? { ...n, ...notification }
              : n
          ),
        };
      }
      // Add new notification
      const newNotifications = [notification, ...state.notifications];
      return {
        notifications: newNotifications,
        unreadCount: newNotifications.filter((n) => !n.is_dismissed).length,
      };
    });
  },

  // Mark a notification as dismissed locally
  dismissNotification: (notificationKey) => {
    set((state) => {
      const notifications = state.notifications.map((n) =>
        n.notification_key === notificationKey
          ? { ...n, is_dismissed: true }
          : n
      );
      return {
        notifications,
        unreadCount: notifications.filter((n) => !n.is_dismissed).length,
      };
    });
  },

  // Mark all notifications as dismissed locally
  dismissAllNotifications: () => {
    set((state) => ({
      notifications: state.notifications.map((n) => ({
        ...n,
        is_dismissed: true,
      })),
      unreadCount: 0,
    }));
  },

  // Remove a notification from the store
  removeNotification: (notificationKey) => {
    set((state) => {
      const notifications = state.notifications.filter(
        (n) => n.notification_key !== notificationKey
      );
      return {
        notifications,
        unreadCount: notifications.filter((n) => !n.is_dismissed).length,
      };
    });
  },

  // Update unread count
  setUnreadCount: (count) => {
    set({ unreadCount: count });
  },

  // Set loading state
  setLoading: (isLoading) => {
    set({ isLoading });
  },

  // Set error state
  setError: (error) => {
    set({ error });
  },

  // Get notifications by type
  getNotificationsByType: (type) => {
    return get().notifications.filter((n) => n.notification_type === type);
  },

  // Get unread notifications only
  getUnreadNotifications: () => {
    return get().notifications.filter((n) => !n.is_dismissed);
  },
}));

export default useNotificationsStore;
