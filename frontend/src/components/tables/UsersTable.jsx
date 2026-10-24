import React, { useMemo, useCallback, useState } from 'react';
import API from '../../api';
import UserForm from '../forms/User';
import useUsersStore from '../../store/users';
import useChannelsStore from '../../store/channels';
import useAuthStore from '../../store/auth';
import useSettingsStore from '../../store/settings';
import useScreenshotMode from '../../store/useScreenshotMode.js';
import { SensitiveValue } from '../SensitiveFields.jsx';
import { USER_LEVELS, USER_LEVEL_LABELS } from '../../constants';
import useWarningsStore from '../../store/warnings';
import {
  SquarePlus,
  SquareMinus,
  SquarePen,
  Copy,
  Eye,
  EyeOff,
  Link as LinkIcon,
  Search,
  X,
} from 'lucide-react';
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
  Menu,
  MenuDropdown,
  MenuItem,
  MenuLabel,
  MenuTarget,
  Stack,
  Badge,
  TextInput,
  Tooltip,
} from '@mantine/core';
import { CustomTable, useTable } from './CustomTable';
import ConfirmationDialog from '../ConfirmationDialog';
import useBrowserStorage from '../../hooks/useBrowserStorage';
import { useDateTimeFormat, format } from '../../utils/dateTimeUtils.js';
import { copyToClipboard, useDebounce } from '../../utils';
import {
  makeHeaderCellRenderer,
  makeSortingChangeHandler,
} from './tableSortingUtils';
import {
  buildUserXcUrls,
  getFilteredUsers,
  getSortedUsers,
  getUserFullName,
} from '../../utils/tables/UsersTableUtils.js';

const resizableColumns = [
  { id: 'user_level', size: 120, minRatio: 0.07 },
  { id: 'username', size: 120, minRatio: 0.08 },
  { id: 'name', size: 125, minRatio: 0.07 },
  { id: 'email', size: 150, minRatio: 0.09 },
  { id: 'date_joined', size: 120, minRatio: 0.08 },
  { id: 'last_login', size: 175, minRatio: 0.1 },
  { id: 'custom_properties', size: 125, minRatio: 0.08 },
  { id: 'channel_profiles', size: 180, minRatio: 0.1 },
];

const deleteUser = (id) => {
  return API.deleteUser(id);
};
const XCPasswordCell = ({ getValue }) => {
  const [isVisible, setIsVisible] = useState(false);
  const screenshotMode = useScreenshotMode((state) => state.enabled);
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
        {password === 'N/A'
          ? 'N/A'
          : isVisible && !screenshotMode
            ? password
            : '••••••••'}
      </Text>
      {password !== 'N/A' && (
        <ActionIcon
          size="xs"
          variant="transparent"
          color="gray"
          aria-label={
            isVisible && !screenshotMode
              ? 'Hide XC password'
              : 'Show XC password'
          }
          disabled={screenshotMode}
          onClick={() => setIsVisible((v) => !v)}
        >
          {isVisible && !screenshotMode ? (
            <EyeOff size={12} />
          ) : (
            <Eye size={12} />
          )}
        </ActionIcon>
      )}
    </Group>
  );
};

const UserLinksMenu = ({ user, iconSize }) => {
  const [menuOpened, setMenuOpened] = useState(false);
  const env_mode = useSettingsStore((s) => s.environment.env_mode);

  const urls = buildUserXcUrls(user, env_mode);
  if (!urls) {
    return (
      <ActionIcon
        aria-label="Copy XC URLs"
        size={iconSize}
        variant="transparent"
        color="gray"
        disabled
      >
        <LinkIcon size="18" />
      </ActionIcon>
    );
  }

  const items = [
    {
      label: 'M3U',
      value: urls.m3u,
      successTitle: 'M3U URL Copied!',
      successMessage: 'The M3U URL has been copied to your clipboard.',
    },
    {
      label: 'EPG',
      value: urls.epg,
      successTitle: 'EPG URL Copied!',
      successMessage: 'The EPG URL has been copied to your clipboard.',
    },
    {
      label: 'XC Details',
      value: urls.details,
      successTitle: 'XC Details Copied!',
      successMessage:
        'Server, username, and XC password have been copied to your clipboard.',
    },
  ];

  const copyItem = async ({ value, successTitle, successMessage }) => {
    await copyToClipboard(value, { successTitle, successMessage });
  };

  return menuOpened ? (
    <Menu opened onChange={setMenuOpened} position="bottom-end">
      <MenuTarget>
        <ActionIcon size={iconSize} variant="transparent" color="gray">
          <LinkIcon size="18" />
        </ActionIcon>
      </MenuTarget>

      <MenuDropdown>
        <MenuLabel>Xtream URLs</MenuLabel>
        {items.map((item) => (
          <MenuItem
            key={item.label}
            leftSection={<Copy size="14" />}
            onClick={() => copyItem(item)}
          >
            <Text size="xs">{item.label}</Text>
          </MenuItem>
        ))}
      </MenuDropdown>
    </Menu>
  ) : (
    <ActionIcon
      aria-label="Copy XC URLs"
      size={iconSize}
      variant="transparent"
      color="gray"
      onClick={() => setMenuOpened(true)}
    >
      <LinkIcon size="18" />
    </ActionIcon>
  );
};

const UserRowActions = ({ theme, row, editUser, handleDeleteUser }) => {
  const [tableSize, _] = useBrowserStorage('table-size', 'default');
  const authUser = useAuthStore((s) => s.user);

  const onEdit = useCallback(() => {
    editUser(row.original);
  }, [row.original, editUser]);

  const onDelete = useCallback(() => {
    handleDeleteUser(row.original.id);
  }, [row.original.id, handleDeleteUser]);

  const iconSize =
    tableSize == 'default' ? 'sm' : tableSize == 'compact' ? 'xs' : 'md';

  return (
    <Group gap={2} justify="center" wrap="nowrap">
      <ActionIcon
        size={iconSize}
        variant="transparent"
        color={theme.tailwind.yellow[3]}
        aria-label={`Edit user ${row.original.username}`}
        onClick={onEdit}
        disabled={authUser.user_level !== USER_LEVELS.ADMIN}
      >
        <SquarePen size="18" />
      </ActionIcon>

      <ActionIcon
        size={iconSize}
        variant="transparent"
        color={theme.tailwind.red[6]}
        aria-label={`Delete user ${row.original.username}`}
        onClick={onDelete}
        disabled={
          authUser.user_level !== USER_LEVELS.ADMIN ||
          authUser.id === row.original.id
        }
      >
        <SquareMinus size="18" />
      </ActionIcon>

      <UserLinksMenu user={row.original} iconSize={iconSize} />
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
  const [search, setSearch] = useState('');
  // Empty query uses delay 0 so the clear button restores the list immediately.
  const debouncedSearch = useDebounce(search, search.trim() === '' ? 0 : 300);
  const [sorting, setSorting] = useState([]);
  const [columnSizing, setColumnSizing] = useBrowserStorage(
    'users-table-column-sizing',
    {}
  );
  const responsiveColumnSizing = useMemo(
    () =>
      Object.fromEntries(
        resizableColumns
          .filter(({ id }) => columnSizing[id] != null)
          .map(({ id }) => [id, columnSizing[id]])
      ),
    [columnSizing]
  );

  const executeDeleteUser = useCallback(async (id) => {
    setIsLoading(true);
    setDeleting(true);
    try {
      await deleteUser(id);
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

  const handleDeleteUser = useCallback(
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
        sortable: true,
        cell: ({ getValue }) => (
          <Text size="sm">{USER_LEVEL_LABELS[getValue()]}</Text>
        ),
      },
      {
        header: 'Username',
        accessorKey: 'username',
        size: 120,
        minSize: 75,
        sortable: true,
        cell: ({ getValue }) => (
          <Box
            style={{
              whiteSpace: 'nowrap',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
            }}
          >
            <SensitiveValue component="span" inherit>
              {getValue()}
            </SensitiveValue>
          </Box>
        ),
      },
      {
        id: 'name',
        header: 'Name',
        size: 125,
        minSize: 50,
        sortable: true,
        accessorFn: getUserFullName,
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
        sortable: true,
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
        size: 120,
        minSize: 110,
        sortable: true,
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
        sortable: true,
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
        size: 90,
        header: 'Actions',
        enableSorting: false,
        enableResizing: false,
        cell: ({ row }) => (
          <UserRowActions
            theme={theme}
            row={row}
            editUser={editUser}
            handleDeleteUser={handleDeleteUser}
          />
        ),
      },
    ],
    [
      theme,
      editUser,
      handleDeleteUser,
      fullDateFormat,
      fullDateTimeFormat,
      profileIdToName,
    ]
  );

  const responsiveColumns = useMemo(
    () =>
      columns.map((column) => {
        const sizing = resizableColumns.find(
          ({ id }) => id === (column.id || column.accessorKey)
        );
        return sizing
          ? {
              ...column,
              grow: true,
              flexRatio: true,
              size: sizing.size,
              minSize: 0,
              enableResizing: sizing.id !== 'channel_profiles',
            }
          : column;
      }),
    [columns]
  );

  const closeUserForm = () => {
    setSelectedUser(null);
    setUserModalOpen(false);
  };

  const data = useMemo(() => {
    const filtered = getFilteredUsers(users, debouncedSearch);
    const sortColumn = sorting[0];

    return sortColumn
      ? getSortedUsers(filtered, sortColumn.id, sortColumn.desc)
      : [...filtered].sort((a, b) => a.id - b.id);
  }, [users, debouncedSearch, sorting]);

  const onSortingChange = makeSortingChangeHandler(sorting, setSorting);

  const renderHeaderCell = makeHeaderCellRenderer(sorting, onSortingChange);

  const table = useTable({
    columns: responsiveColumns,
    data,
    allRowIds: data.map((user) => user.id),
    enablePagination: false,
    enableRowSelection: false,
    enableRowVirtualization: false,
    renderTopToolbar: false,
    sorting,
    columnSizing: responsiveColumnSizing,
    setColumnSizing,
    pairedColumnSizing: resizableColumns,
    tableId: 'users',
    onResetColumnSizing: () => setColumnSizing({}),
    manualSorting: true,
    manualFiltering: true,
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
        <Stack gap="md" style={{ minWidth: 0, width: '100%' }}>
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
                justifyContent: 'space-between',
                alignItems: 'center',
                gap: '16px',
                padding: '16px',
                borderBottom: '1px solid #3f3f46',
              }}
            >
              <TextInput
                placeholder="Search users..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                w={250}
                size="xs"
                leftSection={<Search size={16} />}
                rightSection={
                  search ? (
                    <ActionIcon
                      onClick={() => setSearch('')}
                      variant="subtle"
                      color="gray"
                      size="sm"
                      aria-label="Clear search"
                    >
                      <X size={14} />
                    </ActionIcon>
                  ) : null
                }
              />

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
                {data.length === 0 && users.length > 0 ? (
                  <Text size="xl" c="dimmed" ta="center" py="xl">
                    No users match this search.
                  </Text>
                ) : (
                  <CustomTable table={table} />
                )}
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

Username: `}
              <SensitiveValue component="span" inherit>
                {userToDelete.username}
              </SensitiveValue>
              {`
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
