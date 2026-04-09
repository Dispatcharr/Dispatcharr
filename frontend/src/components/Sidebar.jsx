import React, { useRef, useState, useMemo } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { copyToClipboard } from '../utils';
import { Copy, LogOut, ChevronDown, ChevronRight, Heart } from 'lucide-react';
import { getOrderedNavItems } from '../config/navigation';
import {
  Avatar,
  Group,
  Stack,
  Box,
  Text,
  UnstyledButton,
  TextInput,
  ActionIcon,
  AppShellNavbar,
  ScrollArea,
  Tooltip,
} from '@mantine/core';
import logo from '../images/logo.png';
import useChannelsStore from '../store/channels';
import './sidebar.css';
import useSettingsStore from '../store/settings';
import useAuthStore from '../store/auth';
import { USER_LEVELS } from '../constants';
import UserForm from './forms/User';
import NotificationCenter from './NotificationCenter';

const DonateButton = ({ tooltipPosition = 'top' }) => (
  <Tooltip label="Support Dispatcharr" position={tooltipPosition}>
    <ActionIcon
      component="a"
      href="https://opencollective.com/dispatcharr/contribute"
      target="_blank"
      rel="noopener noreferrer"
      variant="transparent"
      color="pink"
    >
      <Heart size={20} />
    </ActionIcon>
  </Tooltip>
);

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

function NavGroup({ label, icon: IconComponent, paths, location, collapsed }) {
  const [open, setOpen] = useState(() =>
    paths.some((p) => location.pathname.startsWith(p.path))
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
        {IconComponent && <IconComponent size={20} />}
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

  const channelIds = useChannelsStore((s) => s.channelIds);
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

  const isAdmin = authUser && authUser.user_level >= USER_LEVELS.ADMIN;

  // Navigation Items - computed from user's saved order, filtered by visibility
  const navOrder = getNavOrder();
  const hiddenNav = getHiddenNav();
  const navItems = useMemo(() => {
    const orderedItems = getOrderedNavItems(navOrder, isAdmin, channelIds);
    return orderedItems.filter((item) => !hiddenNav.includes(item.id));
  }, [navOrder, hiddenNav, isAdmin, channelIds]);

  // Environment settings and version are loaded by the settings store during initData()
  // No need to fetch them again here - just use the store values

  const copyPublicIP = async () => {
    await copyToClipboard(environment.public_ip, {
      successTitle: 'Success',
      successMessage: 'Public IP copied to clipboard',
    });
  };

  return (
    <AppShellNavbar
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
          wrap="nowrap"
          style={{ padding: '0 16px 16px', justifyContent: 'space-between' }}
        >
          <Tooltip
            label={`v${appVersion?.version || '0.0.0'}${appVersion?.timestamp ? `-${appVersion.timestamp}` : ''}`}
            position="top"
          >
            <Text
              size="xs"
              c="dimmed"
              style={{
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
                minWidth: 0,
                flex: 1,
                cursor: 'pointer',
              }}
              onClick={() =>
                copyToClipboard(
                  `v${appVersion?.version || '0.0.0'}${appVersion?.timestamp ? `-${appVersion.timestamp}` : ''}`,
                  {
                    successTitle: 'Copied',
                    successMessage: 'Version copied to clipboard',
                  }
                )
              }
            >
              v{appVersion?.version || '0.0.0'}
              {appVersion?.timestamp ? `-${appVersion.timestamp}` : ''}
            </Text>
          </Tooltip>
          <Group gap="xs" wrap="nowrap">
            <DonateButton />
            {isAuthenticated && <NotificationCenter />}
          </Group>
        </Group>
      )}
      {collapsed && (
        <Box
          style={{
            padding: '0 16px 16px',
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            gap: 8,
          }}
        >
          {isAuthenticated && <NotificationCenter />}
          <DonateButton tooltipPosition="right" />
        </Box>
      )}

      <UserForm user={authUser} isOpen={userFormOpen} onClose={closeUserForm} />
    </AppShellNavbar>
  );
};

export default Sidebar;
