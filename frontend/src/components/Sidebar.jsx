import React, { useRef, useEffect, useState } from 'react';
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
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import logo from '../images/logo.png';
import useChannelsStore from '../store/channels';
import './sidebar.css';
import useSettingsStore from '../store/settings';
import useAuthStore from '../store/auth'; // Add this import
import API from '../api';
import { USER_LEVELS } from '../constants';
import UserForm from './forms/User';

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

const Sidebar = ({ collapsed, toggleDrawer, drawerWidth, miniDrawerWidth }) => {
  const location = useLocation();

  const channels = useChannelsStore((s) => s.channels);
  const environment = useSettingsStore((s) => s.environment);
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const authUser = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);

  const publicIPRef = useRef(null);

  const [appVersion, setAppVersion] = useState({
    version: '',
    timestamp: null,
  });
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
            label: 'Settings',
            icon: <LucideSettings size={20} />,
            path: '/settings',
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

  // Fetch environment settings including version on component mount
  useEffect(() => {
    if (!isAuthenticated) {
      return;
    }

    const fetchEnvironment = async () => {
      API.getEnvironmentSettings();
    };

    fetchEnvironment();
  }, [isAuthenticated]);

  // Fetch version information on component mount (regardless of authentication)
  useEffect(() => {
    const fetchVersion = async () => {
      try {
        const versionData = await API.getVersion();
        setAppVersion({
          version: versionData.version || '',
          timestamp: versionData.timestamp || null,
        });
      } catch (error) {
        console.error('Failed to fetch version information:', error);
        // Keep using default values from useState initialization
      }
    };

    fetchVersion();
  }, []);

  const copyPublicIP = async () => {
    const success = await copyToClipboard(environment.public_ip);
    if (success) {
      notifications.show({
        title: 'Success',
        message: 'Public IP copied to clipboard',
        color: 'green',
      });
    } else {
      console.error('Failed to copy public IP to clipboard');
    }
  };

  const onLogout = () => {
    logout();
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
      <Stack gap="xs" mt="lg">
        {navItems.map((item) => {
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
          <Group>
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

            <Avatar src="" radius="xl" />
            {!collapsed && authUser && (
              <Group
                style={{
                  flex: 1,
                  justifyContent: 'space-between',
                  whiteSpace: 'nowrap',
                }}
              >
                <UnstyledButton onClick={() => setUserFormOpen(true)}>
                  {authUser.first_name || authUser.username}
                </UnstyledButton>

                <ActionIcon variant="transparent" color="white" size="sm">
                  <LogOut onClick={logout} />
                </ActionIcon>
              </Group>
            )}
          </Group>
        )}
      </Box>

      {/* Version is always shown when sidebar is expanded, regardless of auth status */}
      {!collapsed && (
        <Text size="xs" style={{ padding: '0 16px 16px' }} c="dimmed">
          v{appVersion?.version || '0.0.0'}
          {appVersion?.timestamp ? `-${appVersion.timestamp}` : ''}
        </Text>
      )}

      <UserForm user={authUser} isOpen={userFormOpen} onClose={closeUserForm} />
    </AppShell.Navbar>
  );
};

export default Sidebar;
