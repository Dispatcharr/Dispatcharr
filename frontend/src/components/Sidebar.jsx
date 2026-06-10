import React, { useState, useMemo, useEffect } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { copyToClipboard } from '../utils';
import {
  ArrowLeft,
  ChevronRight,
  Copy,
  Heart,
  HelpCircle,
  LogOut,
} from 'lucide-react';
import { SETTINGS_GROUPS } from '../config/settingsNav';
import { SlidingPanels, usePanelNav } from './SlidingPanels';
import AboutModal from './AboutModal';
import { getOrderedNavItems } from '../config/navigation';
import {
  Avatar,
  Box,
  Group,
  Stack,
  Text,
  UnstyledButton,
  ActionIcon,
  AppShellNavbar,
  ScrollArea,
  Skeleton,
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

// ─── Small shared components ─────────────────────────────────────────────────

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

/** A single leaf nav item that navigates to item.path. */
const NavItem = ({ item, isActive, collapsed }) => {
  const Icon = item.icon;
  return (
    <Tooltip label={item.label} position="right" withArrow disabled={!collapsed}>
      <UnstyledButton
        component={Link}
        to={item.path}
        className={`navlink${isActive ? ' navlink-active' : ''}${collapsed ? ' navlink-collapsed' : ''}`}
      >
        {Icon && <Icon size={20} />}
        {!collapsed && (
          <Text size="sm" style={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', flex: 1, minWidth: 0 }}>
            {item.label}
          </Text>
        )}
        {!collapsed && item.badge && (
          <Text size="sm" style={{ color: '#D4D4D8', whiteSpace: 'nowrap' }}>
            {item.badge}
          </Text>
        )}
      </UnstyledButton>
    </Tooltip>
  );
};

/** Flat group with a decorative heading, matches the settings sub-panel design language. */
function NavGroup({ label, paths, location, collapsed, onSettingsClick, settingsPanelOpen }) {
  return (
    <Box style={{ width: '100%' }}>
      {!collapsed && (
        <Text
          size="xs"
          fw={700}
          tt="uppercase"
          c="dimmed"
          style={{ padding: '2px 10px 4px', letterSpacing: '0.05em', whiteSpace: 'nowrap' }}
        >
          {label}
        </Text>
      )}
      <Stack gap={4}>
        {paths.map((child) => {
          if (child.path === '/settings' && onSettingsClick) {
            const Icon = child.icon;
            const isActive = settingsPanelOpen || location.pathname.startsWith('/settings');
            return (
              <Tooltip key={child.path} label={child.label} position="right" withArrow disabled={!collapsed}>
                <UnstyledButton
                  onClick={onSettingsClick}
                  className={`navlink${isActive ? ' navlink-active' : ''}${collapsed ? ' navlink-collapsed' : ''}`}
                  style={{ width: '100%' }}
                >
                  {Icon && <Icon size={20} />}
                  {!collapsed && (
                    <>
                      <Text size="sm" style={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', flex: 1, minWidth: 0 }}>
                        {child.label}
                      </Text>
                      <ChevronRight size={14} style={{ flexShrink: 0, opacity: 0.5 }} />
                    </>
                  )}
                </UnstyledButton>
              </Tooltip>
            );
          }
          return (
            <NavItem key={child.path} item={child} isActive={location.pathname === child.path} collapsed={collapsed} />
          );
        })}
      </Stack>
    </Box>
  );
}

/** Back button shown at the top of every sub-panel. */
const BackButton = ({ label, collapsed, onClick }) => (
  <Tooltip label="Back" position="right" withArrow disabled={!collapsed}>
    <UnstyledButton
      onClick={onClick}
      className={`navlink${collapsed ? ' navlink-collapsed' : ''}`}
      style={{ width: '100%' }}
    >
      <ArrowLeft size={20} />
      {!collapsed && (
        <Text size="sm" fw={500} style={{ whiteSpace: 'nowrap' }}>
          {label}
        </Text>
      )}
    </UnstyledButton>
  </Tooltip>
);

// ─── Sidebar ─────────────────────────────────────────────────────────────────

const Sidebar = ({ collapsed, toggleDrawer, drawerWidth, miniDrawerWidth }) => {
  const location = useLocation();
  const navigate = useNavigate();

  const channelIds = useChannelsStore((s) => s.channelIds);
  const environment = useSettingsStore((s) => s.environment);
  const appVersion = useSettingsStore((s) => s.version);
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const authUser = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);
  const getNavOrder = useAuthStore((s) => s.getNavOrder);
  const getHiddenNav = useAuthStore((s) => s.getHiddenNav);

  const [userFormOpen, setUserFormOpen] = useState(false);
  const [aboutOpen, setAboutOpen] = useState(false);
  const [ipRevealed, setIpRevealed] = useState(false);

  const isAdmin = authUser && authUser.user_level >= USER_LEVELS.ADMIN;

  const navOrder = getNavOrder();
  const hiddenNav = getHiddenNav();
  const navItems = useMemo(() => {
    const ordered = getOrderedNavItems(navOrder, isAdmin, channelIds);
    return ordered.filter((item) => !hiddenNav.includes(item.id));
  }, [navOrder, hiddenNav, isAdmin, channelIds]);

  const isSettingsPage = location.pathname.startsWith('/settings');
  const activeSettingsId = location.hash.replace('#', '');
  const visibleSettingsGroups = SETTINGS_GROUPS.filter((g) => !g.adminOnly || isAdmin);

  // Panel navigation state, drives the SlidingPanels component
  const nav = usePanelNav();
  // Destructure push so the stable setPanel reference appears in the dep array,
  // not the recreated nav object.
  const { push: pushPanel } = nav;

  // Sync settings route → panel state without causing loops.
  useEffect(() => {
    pushPanel((curr) => {
      if (isSettingsPage && curr?.type !== 'settings') return { type: 'settings' };
      if (!isSettingsPage && curr?.type === 'settings') return null;
      return curr;
    });
  }, [isSettingsPage, pushPanel]);

  const copyPublicIP = async () => {
    await copyToClipboard(environment.public_ip, {
      successTitle: 'Success',
      successMessage: 'Public IP copied to clipboard',
    });
  };

  const handleBack = () => {
    nav.close(); // close panel only, content stays on whatever is currently rendered
  };

  // ── Panel content ────────────────────────────────────────────────────────

  const primaryPanel = (
    <ScrollArea h="100%" type="scroll" scrollbars="y">
      <Stack gap={4} mt="lg" style={{ minHeight: 0, overflowX: 'hidden', paddingRight: 2 }}>
        {navItems.flatMap((item, idx) => {
          const els = [];

          if (item.paths) {
            if (idx > 0) {
              els.push(
                <Box key={`div-${item.id}`} style={{ borderTop: '1px solid #2A2A2E', margin: '4px 4px 6px' }} />
              );
            }
            els.push(
              <NavGroup
                key={item.id}
                label={item.label}
                paths={item.paths}
                location={location}
                collapsed={collapsed}
                onSettingsClick={() => nav.push({ type: 'settings' })}
                settingsPanelOpen={nav.isOpen}
              />
            );
            return els;
          }

          // Settings leaf item: open sidebar sub-panel instead of navigating
          if (item.path === '/settings') {
            const Icon = item.icon;
            const isActive = nav.isOpen || location.pathname.startsWith('/settings');
            els.push(
              <Tooltip key={item.path} label={item.label} position="right" withArrow disabled={!collapsed}>
                <UnstyledButton
                  onClick={() => nav.push({ type: 'settings' })}
                  className={`navlink${isActive ? ' navlink-active' : ''}${collapsed ? ' navlink-collapsed' : ''}`}
                  style={{ width: '100%' }}
                >
                  {Icon && <Icon size={20} />}
                  {!collapsed && (
                    <>
                      <Text style={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', flex: 1, minWidth: 0 }}>
                        {item.label}
                      </Text>
                      <ChevronRight size={14} style={{ flexShrink: 0, opacity: 0.5 }} />
                    </>
                  )}
                </UnstyledButton>
              </Tooltip>
            );
            return els;
          }

          els.push(
            <NavItem
              key={item.path}
              item={item}
              isActive={location.pathname === item.path}
              collapsed={collapsed}
            />
          );
          return els;
        })}
      </Stack>
    </ScrollArea>
  );

  const secondaryPanel = (
    <Box style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <ScrollArea style={{ flex: 1, minHeight: 0 }} type="scroll" scrollbars="y">
        <Stack gap={4} mt="xs" style={{ overflowX: 'hidden', paddingRight: 2 }}>
          {/* Settings sub-panel */}
          {nav.displayed?.type === 'settings' &&
            visibleSettingsGroups.map((group, gi) => (
              <Box key={group.id}>
                {gi > 0 && <Box style={{ borderTop: '1px solid #2A2A2E', margin: '4px 4px 6px' }} />}
                {!collapsed && (
                  <Text
                    size="xs"
                    fw={700}
                    tt="uppercase"
                    c="dimmed"
                    style={{ padding: '2px 10px 2px', letterSpacing: '0.05em', whiteSpace: 'nowrap' }}
                  >
                    {group.label}
                  </Text>
                )}
                {group.sections.map((section) => {
                  const Icon = section.icon;
                  return (
                    <Tooltip
                      key={section.id}
                      label={section.label}
                      position="right"
                      withArrow
                      disabled={!collapsed}
                    >
                      <UnstyledButton
                        onClick={() => navigate(`/settings#${section.id}`, { replace: true })}
                        className={`navlink${activeSettingsId === section.id ? ' navlink-active' : ''}${collapsed ? ' navlink-collapsed' : ''}`}
                        style={{ width: '100%' }}
                      >
                        <Icon size={20} />
                        {!collapsed && (
                          <Text size="sm" style={{ whiteSpace: 'nowrap' }}>{section.label}</Text>
                        )}
                      </UnstyledButton>
                    </Tooltip>
                  );
                })}
              </Box>
            ))}
        </Stack>
      </ScrollArea>

      <Stack gap={4} style={{ padding: '4px 0 8px' }}>
        <BackButton label="Back" collapsed={collapsed} onClick={handleBack} />
      </Stack>
    </Box>
  );

  // ── Render ───────────────────────────────────────────────────────────────

  return (
    <AppShellNavbar
      width={{ base: collapsed ? miniDrawerWidth : drawerWidth }}
      p="xs"
      style={{
        backgroundColor: '#1A1A1E',
        borderRight: '1px solid #2A2A2E',
        minHeight: '100vh',
        display: 'flex',
        flexDirection: 'column',
      }}
    >
      {/* Brand: click to toggle collapse */}
      <Group
        onClick={toggleDrawer}
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
        <img width={30} src={logo} alt="Dispatcharr" />
        {!collapsed && (
          <Text style={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', minWidth: 150 }}>
            Dispatcharr
          </Text>
        )}
      </Group>

      <SlidingPanels
        isOpen={nav.isOpen}
        primary={primaryPanel}
        secondary={secondaryPanel}
      />

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
          <Stack gap="sm" style={{ width: '100%' }}>
            {!collapsed &&
              environment.ip_lookup_enabled !== false &&
              environment.ip_lookup_pending && (
                <Box>
                  <Text size="sm" fw={500} mb={4}>Public IP</Text>
                  <Skeleton height={36} radius="sm" />
                </Box>
              )}

            {!collapsed &&
              environment.ip_lookup_enabled !== false &&
              !environment.ip_lookup_pending &&
              environment.public_ip &&
              !environment.public_ip.startsWith('Error') && (
                <Box onClick={() => setIpRevealed((v) => !v)} style={{ cursor: 'pointer' }}>
                  <Text size="sm" fw={500} mb={4}>Public IP</Text>
                  <Box
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      border: '1px solid var(--mantine-color-default-border)',
                      borderRadius: 'var(--mantine-radius-sm)',
                      backgroundColor: 'var(--mantine-color-dark-6)',
                      height: '36px',
                      paddingLeft: '10px',
                      gap: '8px',
                    }}
                  >
                    {environment.country_code && (
                      <img
                        src={`https://flagcdn.com/16x12/${environment.country_code.toLowerCase()}.png`}
                        alt={environment.country_name || environment.country_code}
                        title={[environment.country_name || environment.country_code, environment.city]
                          .filter(Boolean).join(', ')}
                        style={{ flexShrink: 0 }}
                      />
                    )}
                    <Box style={{ flex: 1, overflow: 'hidden' }}>
                      <span style={{ display: 'block', whiteSpace: 'nowrap', fontSize: 'var(--mantine-font-size-sm)', color: 'var(--mantine-color-text)' }}>
                        {(() => {
                          const ip = environment.public_ip;
                          const isIPv6 = ip.includes(':');
                          const sep = isIPv6 ? ':' : '.';
                          const parts = ip.split(sep);
                          const splitAt = isIPv6 ? 4 : 2;
                          return (
                            <>
                              {parts.slice(0, splitAt).join(sep) + sep}
                              <span style={{ filter: ipRevealed ? 'none' : 'blur(5px)', transition: 'filter 0.15s', userSelect: ipRevealed ? 'text' : 'none' }}>
                                {parts.slice(splitAt).join(sep)}
                              </span>
                            </>
                          );
                        })()}
                      </span>
                    </Box>
                    <ActionIcon variant="transparent" color="gray.9" onClick={(e) => { e.stopPropagation(); copyPublicIP(); }} style={{ flexShrink: 0 }}>
                      <Copy />
                    </ActionIcon>
                  </Box>
                </Box>
              )}

            {!collapsed && authUser && (
              <Group gap="xs" style={{ justifyContent: 'space-between', width: '100%' }}>
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
              <Group justify="center" style={{ width: '100%' }}>
                <Avatar src="" radius="xl" />
              </Group>
            )}
          </Stack>
        )}
      </Box>

      {/* Version and Notifications */}
      {!collapsed && (
        <Group gap="xs" wrap="nowrap" style={{ padding: '0 16px 16px', justifyContent: 'space-between' }}>
          <Tooltip
            label={`v${appVersion?.version || '0.0.0'}${appVersion?.timestamp ? `-${appVersion.timestamp}` : ''}`}
            position="top"
          >
            <Text
              size="xs"
              c="dimmed"
              style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', minWidth: 0, flex: 1, cursor: 'pointer' }}
              onClick={() =>
                copyToClipboard(
                  `v${appVersion?.version || '0.0.0'}${appVersion?.timestamp ? `-${appVersion.timestamp}` : ''}`,
                  { successTitle: 'Copied', successMessage: 'Version copied to clipboard' }
                )
              }
            >
              v{appVersion?.version || '0.0.0'}{appVersion?.timestamp ? `-${appVersion.timestamp}` : ''}
            </Text>
          </Tooltip>
          <Group gap="xs" wrap="nowrap">
            <Tooltip label="About" position="top">
              <ActionIcon variant="transparent" color="gray" onClick={() => setAboutOpen(true)}>
                <HelpCircle size={20} />
              </ActionIcon>
            </Tooltip>
            <DonateButton />
            {isAuthenticated && <NotificationCenter />}
          </Group>
        </Group>
      )}
      {collapsed && (
        <Box style={{ padding: '0 16px 16px', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 8 }}>
          {isAuthenticated && <NotificationCenter />}
          <DonateButton tooltipPosition="right" />
          <Tooltip label="About" position="right">
            <ActionIcon variant="transparent" color="gray" onClick={() => setAboutOpen(true)}>
              <HelpCircle size={20} />
            </ActionIcon>
          </Tooltip>
        </Box>
      )}

      <UserForm user={authUser} isOpen={userFormOpen} onClose={() => setUserFormOpen(false)} />
      <AboutModal isOpen={aboutOpen} onClose={() => setAboutOpen(false)} />
    </AppShellNavbar>
  );
};

export default Sidebar;
