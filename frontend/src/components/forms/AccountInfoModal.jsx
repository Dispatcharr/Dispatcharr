import React, { useMemo, useState } from 'react';
import {
  ActionIcon,
  Alert,
  Badge,
  Box,
  Center,
  Divider,
  Group,
  Modal,
  Stack,
  Table,
  TableTbody,
  TableTd,
  TableTr,
  Text,
  Tooltip,
} from '@mantine/core';
import {
  AlertTriangle,
  CheckCircle,
  Clock,
  Info,
  RefreshCw,
  Users,
  XCircle,
} from 'lucide-react';
import usePlaylistsStore from '../../store/playlists';
import { showNotification } from '../../utils/notificationUtils.js';
import {
  formatTimestamp,
  getTimeRemaining,
  refreshAccountInfo,
} from '../../utils/forms/AccountInfoModalUtils.js';

const AccountInfoModal = ({ isOpen, onClose, profile, onRefresh }) => {
  const [isRefreshing, setIsRefreshing] = useState(false);

  // Get fresh profile data from store to ensure we have the latest custom_properties
  const profiles = usePlaylistsStore((state) => state.profiles);
  const currentProfile = useMemo(() => {
    if (!profile?.id || !profile?.account?.id) return profile;

    // Find the current profile in the store by ID
    const accountProfiles = profiles[profile.account.id] || [];
    const freshProfile = accountProfiles.find((p) => p.id === profile.id);

    // Return fresh profile if found, otherwise fall back to the passed profile
    return freshProfile || profile;
  }, [profile, profiles]);

  const handleRefresh = async () => {
    if (!currentProfile?.id) {
      showNotification({
        title: 'Error',
        message: 'Unable to refresh: Profile information not available',
        color: 'red',
        icon: <XCircle size={16} />,
      });
      return;
    }

    setIsRefreshing(true);

    try {
      const data = await refreshAccountInfo(currentProfile);

      if (data.success) {
        showNotification({
          title: 'Success',
          message:
            'Account info refresh initiated. The information will be updated shortly.',
          color: 'green',
          icon: <CheckCircle size={16} />,
        });

        // Call the parent's refresh function if provided
        if (onRefresh) {
          // Wait a moment for the backend to process, then refresh
          setTimeout(onRefresh, 2000);
        }
      } else {
        showNotification({
          title: 'Error',
          message: data.error || 'Failed to refresh account information',
          color: 'red',
          icon: <XCircle size={16} />,
        });
      }
    } catch {
      // Error notification is already handled by the API function
      // Just need to handle the UI state
    } finally {
      setIsRefreshing(false);
    }
  };

  if (!currentProfile || !currentProfile.custom_properties) {
    return (
      <Modal opened={isOpen} onClose={onClose} title="Account Information">
        <Center p="lg">
          <Stack align="center" spacing="md">
            <Info size={48} color="gray" />
            <Text c="dimmed">No account information available</Text>
            <Text size="sm" c="dimmed" ta="center">
              Account information will be available after the next refresh for
              XtreamCodes accounts.
            </Text>
          </Stack>
        </Center>
      </Modal>
    );
  }

  const { user_info, server_info, last_refresh } =
    currentProfile.custom_properties || {};

  // Helper function to get status badge
  const getStatusBadge = (status) => {
    const statusConfig = {
      Active: { color: 'green', icon: CheckCircle },
      Expired: { color: 'red', icon: XCircle },
      Disabled: { color: 'red', icon: XCircle },
      Banned: { color: 'red', icon: XCircle },
    };

    const config = statusConfig[status] || {
      color: 'gray',
      icon: AlertTriangle,
    };
    const Icon = config.icon;

    return (
      <Badge
        color={config.color}
        variant="light"
        leftSection={<Icon size={12} />}
      >
        {status || 'Unknown'}
      </Badge>
    );
  };

  const timeRemaining = user_info?.exp_date
    ? getTimeRemaining(user_info.exp_date)
    : null;
  const isExpired = timeRemaining === 'Expired';

  return (
    <Modal
      opened={isOpen}
      onClose={onClose}
      title={
        <Group spacing="sm">
          <Info size={20} color="var(--mantine-color-blue-6)" />
          <Text fw={600} size="lg">
            Account Information - {currentProfile.name}
          </Text>
        </Group>
      }
      size="lg"
    >
      <Stack spacing="md">
        {/* Account Status Overview */}
        <Box>
          <Group justify="space-between" mb="sm">
            <Text fw={600} size="lg">
              Account Status
            </Text>
            {getStatusBadge(user_info?.status)}
          </Group>

          {isExpired && (
            <Alert
              icon={<AlertTriangle size={16} />}
              color="red"
              variant="light"
              mb="md"
            >
              This account has expired!
            </Alert>
          )}
        </Box>

        <Divider />

        {/* Key Information Cards */}
        <Group grow>
          <Box
            p="md"
            style={{
              backgroundColor: isExpired
                ? 'rgba(255, 107, 107, 0.08)'
                : 'rgba(64, 192, 87, 0.08)',
              border: `1px solid ${isExpired ? 'rgba(255, 107, 107, 0.2)' : 'rgba(64, 192, 87, 0.2)'}`,
              borderRadius: 8,
            }}
          >
            <Group spacing="xs" mb="xs">
              <Clock
                size={16}
                color={
                  isExpired
                    ? 'var(--mantine-color-red-6)'
                    : 'var(--mantine-color-green-6)'
                }
              />
              <Text fw={500}>Expires</Text>
            </Group>
            <Text size="lg" fw={600} c={isExpired ? 'red' : 'green'}>
              {user_info?.exp_date
                ? formatTimestamp(user_info.exp_date)
                : 'Unknown'}
            </Text>
            {timeRemaining && (
              <Text size="sm" c={isExpired ? 'red' : 'green'}>
                {timeRemaining === 'Expired'
                  ? 'Expired'
                  : `${timeRemaining} remaining`}
              </Text>
            )}
          </Box>

          <Box
            p="md"
            style={{
              backgroundColor: 'rgba(34, 139, 230, 0.08)',
              border: '1px solid rgba(34, 139, 230, 0.2)',
              borderRadius: 8,
            }}
          >
            <Group spacing="xs" mb="xs">
              <Users size={16} color="var(--mantine-color-blue-6)" />
              <Text fw={500}>Connections</Text>
            </Group>
            <Text size="lg" fw={600} c="blue">
              {user_info?.active_cons || '0'} /{' '}
              {user_info?.max_connections || 'Unknown'}
            </Text>
            <Text size="sm" c="dimmed">
              Active / Max
            </Text>
          </Box>
        </Group>

        {/* Profile Notes */}
        {currentProfile?.custom_properties?.notes && (
          <>
            <Divider />
            <Box>
              <Text fw={600} mb="sm">
                Profile Notes
              </Text>
              <Box
                p="sm"
                style={{
                  backgroundColor: 'rgba(134, 142, 150, 0.08)',
                  border: '1px solid rgba(134, 142, 150, 0.2)',
                  borderRadius: 6,
                }}
              >
                <Text size="sm" style={{ whiteSpace: 'pre-wrap' }}>
                  {currentProfile.custom_properties.notes}
                </Text>
              </Box>
            </Box>
          </>
        )}

        <Divider />

        {/* Detailed Information Table */}
        <Box>
          <Text fw={600} mb="sm">
            Account Details
          </Text>
          <Table striped highlightOnHover>
            <TableTbody>
              <TableTr>
                <TableTd fw={500} w="40%">
                  Username
                </TableTd>
                <TableTd>{user_info?.username || 'Unknown'}</TableTd>
              </TableTr>
              <TableTr>
                <TableTd fw={500}>Account Created</TableTd>
                <TableTd>
                  {user_info?.created_at
                    ? formatTimestamp(user_info.created_at)
                    : 'Unknown'}
                </TableTd>
              </TableTr>
              <TableTr>
                <TableTd fw={500}>Trial Account</TableTd>
                <TableTd>
                  <Badge
                    color={user_info?.is_trial === '1' ? 'orange' : 'blue'}
                    variant="light"
                    size="sm"
                  >
                    {user_info?.is_trial === '1' ? 'Yes' : 'No'}
                  </Badge>
                </TableTd>
              </TableTr>
              {user_info?.allowed_output_formats &&
                user_info.allowed_output_formats.length > 0 && (
                  <TableTr>
                    <TableTd fw={500}>Allowed Formats</TableTd>
                    <TableTd>
                      <Group spacing="xs">
                        {user_info.allowed_output_formats.map(
                          (format, index) => (
                            <Badge key={index} variant="outline" size="sm">
                              {format.toUpperCase()}
                            </Badge>
                          )
                        )}
                      </Group>
                    </TableTd>
                  </TableTr>
                )}
            </TableTbody>
          </Table>
        </Box>

        {/* Server Information */}
        {server_info && Object.keys(server_info).length > 0 && (
          <>
            <Divider />
            <Box>
              <Text fw={600} mb="sm">
                Server Information
              </Text>
              <Table striped highlightOnHover>
                <TableTbody>
                  {server_info.url && (
                    <TableTr>
                      <TableTd fw={500} w="40%">
                        Server URL
                      </TableTd>
                      <TableTd>
                        <Text size="sm" family="monospace">
                          {server_info.url}
                        </Text>
                      </TableTd>
                    </TableTr>
                  )}
                  {server_info.port && (
                    <TableTr>
                      <TableTd fw={500}>Port</TableTd>
                      <TableTd>
                        <Badge variant="outline" size="sm">
                          {server_info.port}
                        </Badge>
                      </TableTd>
                    </TableTr>
                  )}
                  {server_info.https_port && (
                    <TableTr>
                      <TableTd fw={500}>HTTPS Port</TableTd>
                      <TableTd>
                        <Badge variant="outline" size="sm" color="green">
                          {server_info.https_port}
                        </Badge>
                      </TableTd>
                    </TableTr>
                  )}
                  {server_info.timezone && (
                    <TableTr>
                      <TableTd fw={500}>Timezone</TableTd>
                      <TableTd>{server_info.timezone}</TableTd>
                    </TableTr>
                  )}
                </TableTbody>
              </Table>
            </Box>
          </>
        )}

        {/* Last Refresh Info */}
        <Divider />
        <Box
          p="sm"
          style={{
            backgroundColor: 'rgba(134, 142, 150, 0.08)',
            border: '1px solid rgba(134, 142, 150, 0.2)',
            borderRadius: 6,
          }}
        >
          <Group spacing="xs" align="center" position="apart">
            {/* Show refresh button for XtreamCodes accounts */}
            {currentProfile?.account?.is_xtream_codes && (
              <Tooltip label="Refresh Account Info Now" position="top">
                <ActionIcon
                  size="sm"
                  variant="light"
                  color="blue"
                  onClick={handleRefresh}
                  loading={isRefreshing}
                  disabled={isRefreshing}
                >
                  <RefreshCw size={14} />
                </ActionIcon>
              </Tooltip>
            )}
            <Group spacing="xs" align="center">
              <Text fw={500} size="sm">
                Last Account Info Refresh:
              </Text>
              <Badge variant="light" color="gray" size="sm">
                {last_refresh ? formatTimestamp(last_refresh) : 'Never'}
              </Badge>
            </Group>
          </Group>
        </Box>
      </Stack>
    </Modal>
  );
};

export default AccountInfoModal;
