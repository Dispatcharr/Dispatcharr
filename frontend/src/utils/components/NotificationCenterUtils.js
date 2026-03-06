import API from '../../api.js';

export const getNotifications = (showDismissed) => {
  return API.getNotifications(showDismissed);
};
export const dismissNotification = (notificationId, actionTaken) => {
  return API.dismissNotification(notificationId, actionTaken);
};
export const dismissAllNotifications = () => {
  return API.dismissAllNotifications();
};