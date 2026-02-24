import React, { useEffect, useState, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  ActionIcon,
  Badge,
  Box,
  Button,
  Card,
  Divider,
  Group,
  Indicator,
  Popover,
  ScrollArea,
  Stack,
  Text,
  ThemeIcon,
  Tooltip,
  useMantineTheme,
} from '@mantine/core';
import {
  Bell,
  Check,
  CheckCheck,
  Download,
  ExternalLink,
  Info,
  Settings,
  AlertTriangle,
  Megaphone,
  X,
  Eye,
  EyeOff,
  ArrowRight,
} from 'lucide-react';
import useNotificationsStore from '../store/notifications';
import API from '../api';

// Get icon for notification type
const getNotificationIcon = (type) => {
  switch (type) {
    case 'version_update':
      return <Download size={16} />;
    case 'setting_recommendation':
      return <Settings size={16} />;
    case 'announcement':
      return <Megaphone size={16} />;
    case 'warning':
      return <AlertTriangle size={16} />;
    case 'info':
    default:
      return <Info size={16} />;
  }
};

// Get color for notification priority
const getPriorityColor = (priority) => {
  switch (priority) {
    case 'critical':
      return 'red';
    case 'high':
      return 'orange';
    case 'normal':
      return 'blue';
    case 'low':
    default:
      return 'gray';
  }
};

// Get color for notification type
const getTypeColor = (type) => {
  switch (type) {
    case 'version_update':
      return 'green';
    case 'setting_recommendation':
      return 'blue';
    case 'announcement':
      return 'violet';
    case 'warning':
      return 'orange';
    case 'info':
    default:
      return 'gray';
  }
};

// Individual notification item component
const NotificationItem = ({ notification, onDismiss, onAction, onClose }) => {
  const theme = useMantineTheme();
  const navigate = useNavigate();
  const typeColor = getTypeColor(notification.notification_type);
  const priorityColor = getPriorityColor(notification.priority);
  const isDismissed = notification.is_dismissed;

  const handleDismiss = (e) => {
    e.stopPropagation();
    onDismiss(notification.id, 'dismissed');
  };

  const handleAction = () => {
    // Handle action_url from action_data
    const actionUrl = notification.action_data?.action_url;
    const releaseUrl = notification.action_data?.release_url;

    if (actionUrl) {
      // Internal navigation
      onClose(); // Close the popover
      navigate(actionUrl);
    } else if (releaseUrl) {
      // External link
      window.open(releaseUrl, '_blank');
    }

    if (onAction) {
      onAction(notification);
    }
  };

  return (
    <Card
      padding="sm"
      radius="md"
      withBorder
      style={{
        borderLeft: `3px solid ${theme.colors[priorityColor][5]}`,
        backgroundColor:
          notification.priority === 'critical'
            ? theme.colors.red[9] + '10'
            : undefined,
        opacity: isDismissed ? 0.6 : 1,
        position: 'relative',
      }}
    >
      {/* Dismiss button for non-setting notifications (only if not already dismissed) */}
      {notification.notification_type !== 'setting_recommendation' &&
        !isDismissed && (
          <ActionIcon
            variant="subtle"
            color="gray"
            size="sm"
            onClick={handleDismiss}
            style={{ position: 'absolute', top: 8, right: 8 }}
          >
            <X size={14} />
          </ActionIcon>
        )}

      <Group wrap="nowrap" align="flex-start" gap="sm">
        <ThemeIcon color={typeColor} variant="light" size="md" radius="xl">
          {getNotificationIcon(notification.notification_type)}
        </ThemeIcon>
        <Box style={{ flex: 1 }}>
          <Group gap="xs" mb={4}>
            <Text size="sm" fw={600} lineClamp={1}>
              {notification.title}
            </Text>
            {isDismissed && (
              <Badge size="xs" color="gray" variant="light">
                Dismissed
              </Badge>
            )}
            {notification.priority === 'high' ||
            notification.priority === 'critical' ? (
              <Badge size="xs" color={priorityColor} variant="filled">
                {notification.priority}
              </Badge>
            ) : null}
          </Group>
          <Text size="xs" c="dimmed" lineClamp={5}>
            {notification.message}
          </Text>

          {/* Action buttons for specific notification types */}
          {notification.notification_type === 'version_update' &&
            notification.action_data?.release_url && (
              <Button
                size="xs"
                variant="light"
                color="green"
                mt="xs"
                leftSection={<ExternalLink size={12} />}
                onClick={handleAction}
              >
                View Release
              </Button>
            )}

          {/* Generic action button for notifications with action_url/action_text */}
          {notification.action_data?.action_url &&
            notification.action_data?.action_text && (
              <Button
                size="xs"
                variant="light"
                color={typeColor}
                mt="xs"
                rightSection={<ArrowRight size={12} />}
                onClick={handleAction}
              >
                {notification.action_data.action_text}
              </Button>
            )}

          {notification.notification_type === 'setting_recommendation' &&
            !notification.action_data?.action_url && (
              <Group gap="xs" mt="xs">
                <Button
                  size="xs"
                  variant="light"
                  color="blue"
                  onClick={() => {
                    onDismiss(notification.id, 'applied');
                    // Navigate to settings or apply the setting
                    if (onAction) onAction(notification);
                  }}
                >
                  Apply
                </Button>
                <Button
                  size="xs"
                  variant="subtle"
                  color="gray"
                  onClick={handleDismiss}
                >
                  Ignore
                </Button>
              </Group>
            )}
        </Box>
      </Group>

      <Text size="xs" c="dimmed" mt="xs" ta="right">
        {new Date(notification.created_at).toLocaleDateString()}
      </Text>
    </Card>
  );
};

// Main notification center component with bell icon and popover
const NotificationCenter = ({ onSettingAction }) => {
  const [opened, setOpened] = useState(false);
  const [showDismissed, setShowDismissed] = useState(false);

  const notifications = useNotificationsStore((s) => s.notifications);
  const unreadCount = useNotificationsStore((s) => s.unreadCount);
  const getUnreadNotifications = useNotificationsStore(
    (s) => s.getUnreadNotifications
  );

  // Fetch notifications on mount and periodically
  const fetchNotifications = useCallback(async () => {
    try {
      await API.getNotifications(showDismissed);
    } catch (error) {
      console.error('Failed to fetch notifications:', error);
    }
  }, [showDismissed]);

  useEffect(() => {
    fetchNotifications();

    // Refresh notifications every 5 minutes
    const interval = setInterval(fetchNotifications, 5 * 60 * 1000);
    return () => clearInterval(interval);
  }, [fetchNotifications]);

  const handleDismiss = async (notificationId, actionTaken = null) => {
    try {
      await API.dismissNotification(notificationId, actionTaken);
    } catch (error) {
      console.error('Failed to dismiss notification:', error);
    }
  };

  const handleDismissAll = async () => {
    try {
      await API.dismissAllNotifications();
    } catch (error) {
      console.error('Failed to dismiss all notifications:', error);
    }
  };

  const handleAction = (notification) => {
    if (
      notification.notification_type === 'setting_recommendation' &&
      onSettingAction
    ) {
      onSettingAction(notification);
    }
  };

  const unreadNotifications = getUnreadNotifications();
  const displayedNotifications = showDismissed
    ? notifications
    : unreadNotifications;

  return (
    <Popover
      opened={opened}
      onChange={setOpened}
      width={380}
      position="bottom-end"
      shadow="lg"
      withArrow
    >
      <Popover.Target>
        <Indicator
          color="red"
          size={16}
          label={unreadCount > 9 ? '9+' : unreadCount}
          disabled={unreadCount === 0}
          offset={4}
          processing={unreadCount > 0}
        >
          <ActionIcon
            variant="subtle"
            color="gray"
            size="lg"
            onClick={() => setOpened((o) => !o)}
            aria-label="Notifications"
          >
            <Bell size={20} />
          </ActionIcon>
        </Indicator>
      </Popover.Target>

      <Popover.Dropdown p={0}>
        {/* Header */}
        <Group justify="space-between" p="sm" pb="xs">
          <Group gap="xs">
            <Text fw={600} size="sm">
              Notifications
            </Text>
            {unreadCount > 0 && (
              <Badge size="sm" color="blue" variant="light">
                {unreadCount} new
              </Badge>
            )}
          </Group>
          <Group gap="xs">
            <Tooltip
              label={showDismissed ? 'Hide dismissed' : 'Show dismissed'}
            >
              <ActionIcon
                variant="subtle"
                color="gray"
                size="sm"
                onClick={() => setShowDismissed((prev) => !prev)}
              >
                {showDismissed ? <EyeOff size={16} /> : <Eye size={16} />}
              </ActionIcon>
            </Tooltip>
            {unreadCount > 0 && (
              <Tooltip label="Mark all as read">
                <ActionIcon
                  variant="subtle"
                  color="gray"
                  size="sm"
                  onClick={handleDismissAll}
                >
                  <CheckCheck size={16} />
                </ActionIcon>
              </Tooltip>
            )}
          </Group>
        </Group>

        <Divider />

        {/* Notification list */}
        <ScrollArea.Autosize mah={400} type="auto" offsetScrollbars>
          {displayedNotifications.length === 0 ? (
            <Box p="lg" ta="center">
              <ThemeIcon
                color="gray"
                variant="light"
                size="xl"
                radius="xl"
                mb="sm"
              >
                <Check size={20} />
              </ThemeIcon>
              <Text size="sm" c="dimmed">
                {showDismissed
                  ? 'No dismissed notifications'
                  : 'All caught up!'}
              </Text>
              <Text size="xs" c="dimmed">
                {showDismissed
                  ? 'Dismissed notifications appear here'
                  : 'No new notifications'}
              </Text>
            </Box>
          ) : (
            <Stack gap="xs" p="xs">
              {displayedNotifications.map((notification) => (
                <NotificationItem
                  key={notification.id}
                  notification={notification}
                  onDismiss={handleDismiss}
                  onAction={handleAction}
                  onClose={() => setOpened(false)}
                />
              ))}
            </Stack>
          )}
        </ScrollArea.Autosize>

        {/* Footer with info text */}
        {!showDismissed &&
          notifications.length > unreadNotifications.length && (
            <>
              <Divider />
              <Box p="xs" ta="center">
                <Text size="xs" c="dimmed">
                  {notifications.length - unreadNotifications.length} dismissed
                  notification
                  {notifications.length - unreadNotifications.length !== 1
                    ? 's'
                    : ''}
                </Text>
              </Box>
            </>
          )}
      </Popover.Dropdown>
    </Popover>
  );
};

export default NotificationCenter;
