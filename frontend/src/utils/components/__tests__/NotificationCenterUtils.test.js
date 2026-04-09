import { describe, it, expect, vi, beforeEach } from 'vitest';
import * as NotificationUtils from '../NotificationCenterUtils';
import API from '../../../api';

vi.mock('../../../api');

describe('NotificationCenterUtils', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('getNotifications', () => {
    it('should call API.getNotifications with showDismissed parameter', async () => {
      const mockNotifications = [
        { id: 1, message: 'Test notification' }
      ];
      API.getNotifications.mockResolvedValue(mockNotifications);

      const result = await NotificationUtils.getNotifications(false);

      expect(API.getNotifications).toHaveBeenCalledWith(false);
      expect(result).toEqual(mockNotifications);
    });

    it('should call API.getNotifications with showDismissed=true', async () => {
      const mockNotifications = [
        { id: 2, message: 'Dismissed notification', is_dismissed: true }
      ];
      API.getNotifications.mockResolvedValue(mockNotifications);

      const result = await NotificationUtils.getNotifications(true);

      expect(API.getNotifications).toHaveBeenCalledWith(true);
      expect(result).toEqual(mockNotifications);
    });

    it('should handle API errors', async () => {
      const error = new Error('API error');
      API.getNotifications.mockRejectedValue(error);

      await expect(NotificationUtils.getNotifications(false)).rejects.toThrow('API error');
      expect(API.getNotifications).toHaveBeenCalledWith(false);
    });
  });

  describe('dismissNotification', () => {
    it('should call API.dismissNotification with notificationId and actionTaken', async () => {
      API.dismissNotification.mockResolvedValue({ success: true });

      const result = await NotificationUtils.dismissNotification(1, 'dismissed');

      expect(API.dismissNotification).toHaveBeenCalledWith(1, 'dismissed');
      expect(result).toEqual({ success: true });
    });

    it('should handle API errors when dismissing', async () => {
      const error = new Error('Dismiss failed');
      API.dismissNotification.mockRejectedValue(error);

      await expect(NotificationUtils.dismissNotification(1, 'dismissed')).rejects.toThrow('Dismiss failed');
      expect(API.dismissNotification).toHaveBeenCalledWith(1, 'dismissed');
    });
  });

  describe('dismissAllNotifications', () => {
    it('should call API.dismissAllNotifications', async () => {
      API.dismissAllNotifications.mockResolvedValue({ success: true, count: 5 });

      const result = await NotificationUtils.dismissAllNotifications();

      expect(API.dismissAllNotifications).toHaveBeenCalled();
      expect(result).toEqual({ success: true, count: 5 });
    });

    it('should handle API errors when dismissing all', async () => {
      const error = new Error('Dismiss all failed');
      API.dismissAllNotifications.mockRejectedValue(error);

      await expect(NotificationUtils.dismissAllNotifications()).rejects.toThrow('Dismiss all failed');
      expect(API.dismissAllNotifications).toHaveBeenCalled();
    });
  });
});
