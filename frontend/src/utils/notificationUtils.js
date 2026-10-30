import { notifications } from '@mantine/notifications';
import { Children, createElement, isValidElement } from 'react';
import { ScreenshotText } from '../components/SensitiveFields.jsx';
import { redactUrls } from './screenshotMode.js';

const containsUrl = (children) =>
  Children.toArray(children).some((child) =>
    typeof child === 'string'
      ? redactUrls(child) !== child
      : isValidElement(child) && containsUrl(child.props.children)
  );

const screenshotSafe = (notification) => {
  const result = { ...notification };
  for (const key of ['title', 'message']) {
    if (containsUrl(result[key])) {
      result[key] = createElement(ScreenshotText, null, result[key]);
    }
  }
  return result;
};

export function showNotification(notificationObject) {
  return notifications.show(screenshotSafe(notificationObject));
}

export function updateNotification(notificationId, notificationObject) {
  return notifications.update({
    ...screenshotSafe(notificationObject),
    id: notificationId,
  });
}

export function hideNotification(notificationId) {
  return notifications.hide(notificationId);
}
