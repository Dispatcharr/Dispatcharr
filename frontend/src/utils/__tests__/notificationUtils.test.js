import { describe, it, expect, vi, beforeEach } from 'vitest';
import { notifications } from '@mantine/notifications';
import * as notificationUtils from '../notificationUtils';

vi.mock('@mantine/notifications', () => ({
  notifications: {
    show: vi.fn(),
    update: vi.fn(),
  },
}));

describe('notificationUtils', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('showNotification', () => {
    it('should call notifications.show with notification object', () => {
      const notificationObject = {
        title: 'Test Title',
        message: 'Test message',
        color: 'blue',
      };

      notificationUtils.showNotification(notificationObject);

      expect(notifications.show).toHaveBeenCalledWith(notificationObject);
      expect(notifications.show).toHaveBeenCalledTimes(1);
    });

    it('should return the result from notifications.show', () => {
      const mockReturnValue = 'notification-id-123';
      notifications.show.mockReturnValue(mockReturnValue);

      const result = notificationUtils.showNotification({ message: 'test' });

      expect(result).toBe(mockReturnValue);
    });

    it('should handle notification with all properties', () => {
      const notificationObject = {
        id: 'custom-id',
        title: 'Success',
        message: 'Operation completed',
        color: 'green',
        autoClose: 5000,
        withCloseButton: true,
      };

      notificationUtils.showNotification(notificationObject);

      expect(notifications.show).toHaveBeenCalledWith(notificationObject);
    });

    it('should handle minimal notification object', () => {
      const notificationObject = {
        message: 'Simple message',
      };

      notificationUtils.showNotification(notificationObject);

      expect(notifications.show).toHaveBeenCalledWith(notificationObject);
    });
  });

  describe('updateNotification', () => {
    it('should call notifications.update with id and notification object', () => {
      const notificationId = 'notification-123';
      const notificationObject = {
        title: 'Updated Title',
        message: 'Updated message',
        color: 'green',
      };

      notificationUtils.updateNotification(notificationId, notificationObject);

      expect(notifications.update).toHaveBeenCalledWith(
        notificationId,
        notificationObject
      );
      expect(notifications.update).toHaveBeenCalledTimes(1);
    });

    it('should return the result from notifications.update', () => {
      const mockReturnValue = { success: true };
      notifications.update.mockReturnValue(mockReturnValue);

      const result = notificationUtils.updateNotification('id', {
        message: 'test',
      });

      expect(result).toBe(mockReturnValue);
    });

    it('should handle loading to success transition', () => {
      const notificationId = 'loading-notification';
      const updateObject = {
        title: 'Success',
        message: 'Operation completed successfully',
        color: 'green',
        loading: false,
      };

      notificationUtils.updateNotification(notificationId, updateObject);

      expect(notifications.update).toHaveBeenCalledWith(
        notificationId,
        updateObject
      );
    });

    it('should handle loading to error transition', () => {
      const notificationId = 'loading-notification';
      const updateObject = {
        title: 'Error',
        message: 'Operation failed',
        color: 'red',
        loading: false,
      };

      notificationUtils.updateNotification(notificationId, updateObject);

      expect(notifications.update).toHaveBeenCalledWith(
        notificationId,
        updateObject
      );
    });

    it('should handle partial updates', () => {
      const notificationId = 'notification-123';
      const updateObject = {
        color: 'yellow',
      };

      notificationUtils.updateNotification(notificationId, updateObject);

      expect(notifications.update).toHaveBeenCalledWith(
        notificationId,
        updateObject
      );
    });

    it('should handle empty notification id', () => {
      const notificationObject = { message: 'test' };

      notificationUtils.updateNotification('', notificationObject);

      expect(notifications.update).toHaveBeenCalledWith('', notificationObject);
    });

    it('should handle null notification id', () => {
      const notificationObject = { message: 'test' };

      notificationUtils.updateNotification(null, notificationObject);

      expect(notifications.update).toHaveBeenCalledWith(
        null,
        notificationObject
      );
    });
  });
});
