import React, { useRef, useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { copyToClipboard } from '../utils';
import {
  ListOrdered,
  Play,
  Database,
  SlidersHorizontal,
  LayoutGrid,
  Settings as LucideSettings,
  Copy,
  ChartLine,
  Video,
  PlugZap,
  LogOut,
  User,
  FileImage,
  Webhook,
  Logs,
  ChevronDown,
  ChevronRight,
  MonitorCog,
} from 'lucide-react';
import {
  Avatar,
  AppShell,
  Group,
  Stack,
  Box,
  Text,
  UnstyledButton,
  TextInput,
  ActionIcon,
  Menu,
  ScrollArea,
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import logo from '../images/logo.png';
import useChannelsStore from '../store/channels';
import './sidebar.css';
import useSettingsStore from '../store/settings';
import useAuthStore from '../store/auth';
import { USER_LEVELS } from '../constants';
import UserForm from './forms/User';
import NotificationCenter from './NotificationCenter';

const NavLink = ({ item, isActive, collapsed }) => {
  return (
    <UnstyledButton
      key={item.path}
      component={Link}
      to={item.path}
      className={`navlink ${isActive ? 'navlink-active' : ''} ${collapsed ? 'navlink-collapsed' : ''}`}
    >
      {item.icon}
      {!collapsed && (
        <Text
          sx={{
            opacity: collapsed ? 0 : 1,
            transition: 'opacity 0.2s ease-in-out',
            whiteSpace: 'nowrap',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            minWidth: collapsed ? 0 : 150,
          }}
        >
          {item.label}
        </Text>
      )}
      {!collapsed && item.badge && (
        <Text size="sm" style={{ color: '#D4D4D8', whiteSpace: 'nowrap' }}>
          {item.badge}
        </Text>
      )}
    </UnstyledButton>
  );
};

function NavGroup({ label, icon, paths, location, collapsed }) {
  const [open, setOpen] = useState(() =>
    location.pathname.startsWith('/connect')
  );

  const parentActive = paths
    .map((path) => path.path)
    .includes(location.pathname);

  return (
    <Box
      style={{ width: '100%', paddingRight: 2 }}
      className={open ? 'navgroup-open' : ''}
    >
      <UnstyledButton
        onClick={() => setOpen((o) => !o)}
        className={`navlink ${parentActive ? 'navlink-parent-active' : ''} ${open ? 'navlink-collapsed' : ''}`}
        style={{ width: '100%' }}
      >
        {icon}
        {!collapsed && (
          <Group justify="space-between" style={{ width: '100%' }}>
            <Text
              sx={{
                opacity: open ? 0 : 1,
                transition: 'opacity 0.2s ease-in-out',
                whiteSpace: 'nowrap',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                minWidth: open ? 0 : 150,
              }}
            >
              {label}
            </Text>

            <Box alignItems="center" style={{ display: 'flex' }}>
              {open ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
            </Box>
          </Group>
        )}
      </UnstyledButton>

      {open && (
        <Box style={{ paddingTop: 10 }}>
          <Stack gap="xs" pl={open ? 0 : 'lg'}>
            {paths.map((child) => {
              const active = location.pathname === child.path;
              return (
                <Box
                  style={{ paddingLeft: collapsed ? 0 : 35 }}
                  key={child.path}
                >
                  <NavLink
                    key={child.path}
                    item={child}
                    isActive={active}
                    collapsed={collapsed}
                  />
                </Box>
              );
            })}
          </Stack>
        </Box>
      )}
    </Box>
  );
}

const Sidebar = ({ collapsed, toggleDrawer, drawerWidth, miniDrawerWidth }) => {
  const location = useLocation();

  const channels = useChannelsStore((s) => s.channels);
  const environment = useSettingsStore((s) => s.environment);
  const appVersion = useSettingsStore((s) => s.version);
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const authUser = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);

  const publicIPRef = useRef(null);

  const [userFormOpen, setUserFormOpen] = useState(false);

  const closeUserForm = () => setUserFormOpen(false);

  // Navigation Items
  const navItems =
    authUser && authUser.user_level == USER_LEVELS.ADMIN
      ? [
          {
            label: 'Channels',
            icon: <ListOrdered size={20} />,
            path: '/channels',
            badge: `(${Object.keys(channels).length})`,
          },
          {
            label: 'VODs',
            path: '/vods',
            icon: <Video size={20} />,
          },
          {
            label: 'M3U & EPG Manager',
            icon: <Play size={20} />,
            path: '/sources',
          },
          { label: 'TV Guide', icon: <LayoutGrid size={20} />, path: '/guide' },
          { label: 'DVR', icon: <Database size={20} />, path: '/dvr' },
          { label: 'Stats', icon: <ChartLine size={20} />, path: '/stats' },
          { label: 'Plugins', icon: <PlugZap size={20} />, path: '/plugins' },
          {
            label: 'Connect',
            icon: <Webhook size={20} />,
            paths: [
              {
                label: 'Connections',
                icon: <Webhook size={20} />,
                path: '/connect',
              },
              {
                label: 'Logs',
                icon: <Logs size={20} />,
                path: '/connect/logs',
              },
            ],
          },
          {
            label: 'Settings',
            icon: <LucideSettings size={20} />,
            paths: [
              {
                label: 'Users',
                icon: <User size={20} />,
                path: '/users',
              },
              {
                label: 'Logo Manager',
                icon: <FileImage size={20} />,
                path: '/logos',
              },
              {
                label: 'System',
                icon: <MonitorCog size={20} />,
                path: '/settings',
              },
            ],
          },
        ]
      : [
          {
            label: 'Channels',
            icon: <ListOrdered size={20} />,
            path: '/channels',
            badge: `(${Object.keys(channels).length})`,
          },
          { label: 'TV Guide', icon: <LayoutGrid size={20} />, path: '/guide' },
          {
            label: 'Settings',
            icon: <LucideSettings size={20} />,
            path: '/settings',
          },
        ];

  // Environment settings and version are loaded by the settings store during initData()
  // No need to fetch them again here - just use the store values

  const copyPublicIP = async () => {
    await copyToClipboard(environment.public_ip, {
      successTitle: 'Success',
      successMessage: 'Public IP copied to clipboard',
    });
  };

  const onLogout = async () => {
    await logout();
    window.location.reload();
  };

  return (
    <AppShell.Navbar
      width={{ base: collapsed ? miniDrawerWidth : drawerWidth }}
      p="xs"
      style={{
        backgroundColor: '#1A1A1E',
        // transition: 'width 0.3s ease',
        borderRight: '1px solid #2A2A2E',
        minHeight: '100vh',
        display: 'flex',
        flexDirection: 'column',
      }}
    >
      {/* Brand - Click to Toggle */}
      <Group
        onClick={toggleDrawer}
        spacing="sm"
        style={{
          cursor: 'pointer',
          display: 'flex',
          alignItems: 'center',
          gap: 12,
          padding: '16px 12px',
          fontSize: 18,
          fontWeight: 600,
          color: '#FFFFFF',
          justifyContent: collapsed ? 'center' : 'flex-start',
          whiteSpace: 'nowrap',
        }}
      >
        {/* <ListOrdered size={24} /> */}
        <img width={30} src={logo} />
        {!collapsed && (
          <Text
            sx={{
              opacity: collapsed ? 0 : 1,
              transition: 'opacity 0.2s ease-in-out',
              whiteSpace: 'nowrap', // Ensures text never wraps
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              minWidth: collapsed ? 0 : 150, // Prevents reflow
            }}
          >
            Dispatcharr
          </Text>
        )}
      </Group>

      {/* Navigation Links */}
      <ScrollArea h="100%" type="scroll" scrollbars="y">
        <Stack
          gap="xs"
          mt="lg"
          style={{
            flex: 1,
            minHeight: 0,
            overflowY: 'auto',
            overflowX: 'hidden',
          }}
        >
          {navItems.map((item) => {
            if (item.paths) {
              return (
                <NavGroup
                  key={item.label}
                  label={item.label}
                  paths={item.paths}
                  location={location}
                  collapsed={collapsed}
                  icon={item.icon}
                />
              );
            }

            const isActive = location.pathname === item.path;

            return (
              <NavLink
                key={item.path}
                item={item}
                collapsed={collapsed}
                isActive={isActive}
              />
            );
          })}
        </Stack>
      </ScrollArea>

      {/* Profile Section */}
      <Box
        style={{
          marginTop: 'auto',
          padding: '16px',
          display: 'flex',
          alignItems: 'center',
          gap: 10,
          borderTop: '1px solid #2A2A2E',
          justifyContent: collapsed ? 'center' : 'flex-start',
        }}
      >
        {isAuthenticated && (
          <Stack gap="sm">
            {!collapsed && (
              <TextInput
                label="Public IP"
                ref={publicIPRef}
                value={environment.public_ip}
                readOnly={true}
                leftSection={
                  environment.country_code && (
                    <img
                      src={`https://flagcdn.com/16x12/${environment.country_code.toLowerCase()}.png`}
                      alt={environment.country_name || environment.country_code}
                      title={
                        environment.country_name || environment.country_code
                      }
                    />
                  )
                }
                rightSection={
                  <ActionIcon
                    variant="transparent"
                    color="gray.9"
                    onClick={copyPublicIP}
                  >
                    <Copy />
                  </ActionIcon>
                }
              />
            )}

            {!collapsed && authUser && (
              <Group
                gap="xs"
                style={{ justifyContent: 'space-between', width: '100%' }}
              >
                <Group gap="xs">
                  <Avatar src="" radius="xl" />
                  <UnstyledButton onClick={() => setUserFormOpen(true)}>
                    {authUser.first_name || authUser.username}
                  </UnstyledButton>
                </Group>
                <ActionIcon variant="transparent" color="white" size="sm">
                  <LogOut onClick={logout} />
                </ActionIcon>
              </Group>
            )}
            {collapsed && (
              <Group gap="xs">
                <Avatar src="" radius="xl" />
              </Group>
            )}
          </Stack>
        )}
      </Box>

      {/* Version and Notification */}
      {!collapsed && (
        <Group
          gap="xs"
          style={{ padding: '0 16px 16px', justifyContent: 'space-between' }}
        >
          <Text size="xs" c="dimmed">
            v{appVersion?.version || '0.0.0'}
            {appVersion?.timestamp ? `-${appVersion.timestamp}` : ''}
          </Text>
          {isAuthenticated && <NotificationCenter />}
        </Group>
      )}
      {collapsed && isAuthenticated && (
        <Box
          style={{
            padding: '0 16px 16px',
            display: 'flex',
            justifyContent: 'center',
          }}
        >
          <NotificationCenter />
        </Box>
      )}

      <UserForm user={authUser} isOpen={userFormOpen} onClose={closeUserForm} />
    </AppShell.Navbar>
  );
};

export default Sidebar;
