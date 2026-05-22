import React, { useMemo, useCallback, useState } from 'react';
import API from '../../api';
import UserForm from '../forms/User';
import useUsersStore from '../../store/users';
import useChannelsStore from '../../store/channels';
import useAuthStore from '../../store/auth';
import { USER_LEVELS, USER_LEVEL_LABELS } from '../../constants';
import useWarningsStore from '../../store/warnings';
import { SquarePlus, SquareMinus, SquarePen, Eye, EyeOff } from 'lucide-react';
import {
  ActionIcon,
  Box,
  Text,
  Paper,
  Button,
  Flex,
  Group,
  useMantineTheme,
  LoadingOverlay,
  Stack,
  Badge,
  Tooltip,
} from '@mantine/core';
import { CustomTable, useTable } from './CustomTable';
import ConfirmationDialog from '../ConfirmationDialog';
import useLocalStorage from '../../hooks/useLocalStorage';
import { useDateTimeFormat, format } from '../../utils/dateTimeUtils.js';

const XCPasswordCell = ({ getValue }) => {
  const [isVisible, setIsVisible] = useState(false);
  const customProps = getValue() || {};
  const password = customProps.xc_password || 'N/A';

  return (
    <Group
      gap={4}
      style={{
        alignItems: 'center',
        overflow: 'hidden',
        flexWrap: 'nowrap',
      }}
    >
      <Text
        size="sm"
        style={{
          fontFamily: 'monospace',
          flex: '1 1 0',
          minWidth: 0,
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
        }}
      >
        {password === 'N/A' ? 'N/A' : isVisible ? password : '••••••••'}
      </Text>
      {password !== 'N/A' && (
        <ActionIcon
          size="xs"
          variant="transparent"
          color="gray"
          onClick={() => setIsVisible((v) => !v)}
        >
          {isVisible ? <EyeOff size={12} /> : <Eye size={12} />}
        </ActionIcon>
      )}
    </Group>
  );
};

const UserRowActions = ({ theme, row, editUser, deleteUser }) => {
  const [tableSize, _] = useLocalStorage('table-size', 'default');
  const authUser = useAuthStore((s) => s.user);

  const onEdit = useCallback(() => {
    editUser(row.original);
  }, [row.original, editUser]);

  const onDelete = useCallback(() => {
    deleteUser(row.original.id);
  }, [row.original.id, deleteUser]);

  const iconSize =
    tableSize == 'default' ? 'sm' : tableSize == 'compact' ? 'xs' : 'md';

  return (
    <Group gap={2} justify="center" wrap="nowrap">
      <ActionIcon
        size={iconSize}
        variant="transparent"
        color={theme.tailwind.yellow[3]}
        onClick={onEdit}
        disabled={authUser.user_level !== USER_LEVELS.ADMIN}
      >
        <SquarePen size="18" />
      </ActionIcon>

      <ActionIcon
        size={iconSize}
        variant="transparent"
        color={theme.tailwind.red[6]}
        onClick={onDelete}
        disabled={
          authUser.user_level !== USER_LEVELS.ADMIN ||
          authUser.id === row.original.id
        }
      >
        <SquareMinus size="18" />
      </ActionIcon>
    </Group>
  );
};

const UsersTable = () => {
  const theme = useMantineTheme();
  const { fullDateFormat, fullDateTimeFormat } = useDateTimeFormat();

  /**
   * STORES
   */
  const users = useUsersStore((s) => s.users);
  const profiles = useChannelsStore((s) => s.profiles);
  const authUser = useAuthStore((s) => s.user);
  const isWarningSuppressed = useWarningsStore((s) => s.isWarningSuppressed);
  const suppressWarning = useWarningsStore((s) => s.suppressWarning);

  /**
   * useState
   */
  const [selectedUser, setSelectedUser] = useState(null);
  const [userModalOpen, setUserModalOpen] = useState(false);
  const [confirmDeleteOpen, setConfirmDeleteOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [userToDelete, setUserToDelete] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const executeDeleteUser = useCallback(async (id) => {
    setIsLoading(true);
    setDeleting(true);
    try {
      await API.deleteUser(id);
    } finally {
      setDeleting(false);
      setIsLoading(false);
      setConfirmDeleteOpen(false);
    }
  }, []);

  const editUser = useCallback(async (user = null) => {
    setSelectedUser(user);
    setUserModalOpen(true);
  }, []);

  const deleteUser = useCallback(
    async (id) => {
      const user = users.find((u) => u.id === id);
      setUserToDelete(user);
      setDeleteTarget(id);

      if (isWarningSuppressed('delete-user')) {
        return executeDeleteUser(id);
      }

      setConfirmDeleteOpen(true);
    },
    [users, isWarningSuppressed, executeDeleteUser]
  );

  /**
   * useMemo
   */
  // Create a profile ID to name lookup map for efficient rendering
  const profileIdToName = useMemo(() => {
    const map = {};
    Object.values(profiles).forEach((profile) => {
      map[profile.id] = profile.name;
    });
    return map;
  }, [profiles]);

  const columns = useMemo(
    () => [
      {
        header: 'User Level',
        accessorKey: 'user_level',
        size: 120,
        minSize: 80,
        cell: ({ getValue }) => (
          <Text size="sm">{USER_LEVEL_LABELS[getValue()]}</Text>
        ),
      },
      {
        header: 'Username',
        accessorKey: 'username',
        size: 120,
        minSize: 75,
        cell: ({ getValue }) => (
          <Box
            style={{
              whiteSpace: 'nowrap',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
            }}
          >
            {getValue()}
          </Box>
        ),
      },
      {
        id: 'name',
        header: 'Name',
        size: 125,
        minSize: 50,
        accessorFn: (row) =>
          `${row.first_name || ''} ${row.last_name || ''}`.trim(),
        cell: ({ getValue }) => (
          <Box
            style={{
              whiteSpace: 'nowrap',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
            }}
          >
            {getValue() || '-'}
          </Box>
        ),
      },
      {
        header: 'Email',
        accessorKey: 'email',
        size: 125,
        minSize: 50,
        cell: ({ getValue }) => (
          <Box
            style={{
              whiteSpace: 'nowrap',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
            }}
          >
            {getValue()}
          </Box>
        ),
      },
      {
        header: 'Date Joined',
        accessorKey: 'date_joined',
        size: 90,
        minSize: 90,
        cell: ({ getValue }) => {
          const date = getValue();
          return (
            <Text size="sm">{date ? format(date, fullDateFormat) : '-'}</Text>
          );
        },
      },
      {
        header: 'Last Login',
        accessorKey: 'last_login',
        size: 175,
        minSize: 85,
        cell: ({ getValue }) => {
          const date = getValue();
          return (
            <Text size="sm">
              {date ? format(date, fullDateTimeFormat) : 'Never'}
            </Text>
          );
        },
      },
      {
        header: 'XC Password',
        accessorKey: 'custom_properties',
        size: 125,
        minSize: 95,
        enableSorting: false,
        cell: XCPasswordCell,
      },
      {
        header: 'Channel Profiles',
        accessorKey: 'channel_profiles',
        size: 120,
        minSize: 116,
        grow: true,
        cell: ({ getValue }) => {
          const userProfiles = getValue() || [];
          const profileNames = userProfiles
            .map((id) => profileIdToName[id])
            .filter(Boolean); // Filter out any undefined values
          return (
            <Group gap={4} wrap="wrap" py={4}>
              {profileNames.length > 0 ? (
                profileNames.map((name, index) => (
                  <Tooltip key={index} label={name} withArrow>
                    <Badge size="sm" variant="light" color="gray">
                      {name}
                    </Badge>
                  </Tooltip>
                ))
              ) : (
                <Badge size="sm" variant="light" color="gray">
                  All
                </Badge>
              )}
            </Group>
          );
        },
      },
      {
        id: 'actions',
        size: 65,
        header: 'Actions',
        enableSorting: false,
        enableResizing: false,
        cell: ({ row }) => (
          <UserRowActions
            theme={theme}
            row={row}
            editUser={editUser}
            deleteUser={deleteUser}
          />
        ),
      },
    ],
    [theme, editUser, deleteUser, fullDateFormat, fullDateTimeFormat]
  );

  const closeUserForm = () => {
    setSelectedUser(null);
    setUserModalOpen(false);
  };

  const data = useMemo(() => {
    return users.sort((a, b) => a.id - b.id);
  }, [users]);

  const renderHeaderCell = (header) => {
    return (
      <Text size="sm" name={header.id}>
        {header.column.columnDef.header}
      </Text>
    );
  };

  const table = useTable({
    columns,
    data,
    allRowIds: data.map((user) => user.id),
    enablePagination: false,
    enableRowSelection: false,
    enableRowVirtualization: false,
    renderTopToolbar: false,
    manualSorting: false,
    manualFiltering: false,
    manualPagination: false,
    headerCellRenderFns: {
      actions: renderHeaderCell,
      username: renderHeaderCell,
      name: renderHeaderCell,
      email: renderHeaderCell,
      user_level: renderHeaderCell,
      last_login: renderHeaderCell,
      date_joined: renderHeaderCell,
      channel_profiles: renderHeaderCell,
      custom_properties: renderHeaderCell,
    },
  });

  return (
    <>
      <Box
        style={{
          display: 'flex',
          justifyContent: 'center',
          padding: '0px',
          minHeight: '100vh',
        }}
      >
        <Stack gap="md" style={{ maxWidth: '1200px', width: '100%' }}>
          <Flex style={{ alignItems: 'center', paddingBottom: 10 }} gap={15}>
            <Text
              style={{
                fontFamily: 'Inter, sans-serif',
                fontWeight: 500,
                fontSize: '20px',
                lineHeight: 1,
                letterSpacing: '-0.3px',
                color: 'gray.6',
                marginBottom: 0,
              }}
            >
              Users
            </Text>
          </Flex>

          <Paper
            style={{
              backgroundColor: '#27272A',
              border: '1px solid #3f3f46',
              borderRadius: 'var(--mantine-radius-md)',
            }}
          >
            {/* Top toolbar */}
            <Box
              style={{
                display: 'flex',
                justifyContent: 'flex-end',
                padding: '16px',
                borderBottom: '1px solid #3f3f46',
              }}
            >
              <Button
                leftSection={<SquarePlus size={18} />}
                variant="light"
                size="xs"
                onClick={() => editUser()}
                p={5}
                color={theme.tailwind.green[5]}
                style={{
                  borderWidth: '1px',
                  borderColor: theme.tailwind.green[5],
                  color: 'white',
                }}
                disabled={authUser.user_level !== USER_LEVELS.ADMIN}
              >
                Add User
              </Button>
            </Box>

            {/* Table container */}
            <Box
              style={{
                position: 'relative',
                overflow: 'auto',
                borderRadius:
                  '0 0 var(--mantine-radius-md) var(--mantine-radius-md)',
              }}
            >
              <div style={{ minWidth: '900px' }}>
                <LoadingOverlay visible={isLoading} />
                <CustomTable table={table} />
              </div>
            </Box>
          </Paper>
        </Stack>
      </Box>

      <UserForm
        user={selectedUser}
        isOpen={userModalOpen}
        onClose={closeUserForm}
      />

      <ConfirmationDialog
        opened={confirmDeleteOpen}
        onClose={() => setConfirmDeleteOpen(false)}
        onConfirm={() => executeDeleteUser(deleteTarget)}
        loading={deleting}
        title="Confirm User Deletion"
        message={
          userToDelete ? (
            <div style={{ whiteSpace: 'pre-line' }}>
              {`Are you sure you want to delete the following user?

Username: ${userToDelete.username}
Email: ${userToDelete.email}
User Level: ${USER_LEVEL_LABELS[userToDelete.user_level]}

This action cannot be undone.`}
            </div>
          ) : (
            'Are you sure you want to delete this user? This action cannot be undone.'
          )
        }
        confirmLabel="Delete"
        cancelLabel="Cancel"
        actionKey="delete-user"
        onSuppressChange={suppressWarning}
        size="md"
      />
    </>
  );
};

export default UsersTable;
