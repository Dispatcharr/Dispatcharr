import React, { useRef, useState, useMemo } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { copyToClipboard } from '../utils';
import {
  Copy,
  LogOut,
} from 'lucide-react';
import { getOrderedNavItems } from '../config/navigation';
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
import useAuthStore from '../store/auth';
import { USER_LEVELS } from '../constants';
import UserForm from './forms/User';

const NavLink = ({ item, isActive, collapsed }) => {
  const IconComponent = item.icon;
  return (
    <UnstyledButton
      key={item.path}
      component={Link}
      to={item.path}
      className={`navlink ${isActive ? 'navlink-active' : ''} ${collapsed ? 'navlink-collapsed' : ''}`}
    >
      {IconComponent && <IconComponent size={20} />}
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
  const appVersion = useSettingsStore((s) => s.version);
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const authUser = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);
  const getNavOrder = useAuthStore((s) => s.getNavOrder);
  const getHiddenNav = useAuthStore((s) => s.getHiddenNav);

  const publicIPRef = useRef(null);

  const [userFormOpen, setUserFormOpen] = useState(false);

  const closeUserForm = () => setUserFormOpen(false);

  // Get user's saved navigation order and hidden items using store getters
  const navOrder = getNavOrder();
  const hiddenNav = getHiddenNav();
  const isAdmin = authUser && authUser.user_level >= USER_LEVELS.ADMIN;

  // Navigation Items - computed from user's saved order, filtered by visibility
  const navItems = useMemo(() => {
    const orderedItems = getOrderedNavItems(navOrder, isAdmin, channels);
    return orderedItems.filter((item) => !hiddenNav.includes(item.id));
  }, [navOrder, hiddenNav, isAdmin, channels]);

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
                  <LogOut onClick={onLogout} />
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
