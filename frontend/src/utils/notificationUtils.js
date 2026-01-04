import { notifications } from '@mantine/notifications';

export function showNotification(notificationObject) {
  return notifications.show(notificationObject);
}

export function updateNotification(notificationId, notificationObject) {
  return notifications.update(notificationId, notificationObject);
}