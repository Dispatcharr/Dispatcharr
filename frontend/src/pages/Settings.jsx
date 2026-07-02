import React, { Suspense, useState, useEffect } from 'react';
import { useLocation } from 'react-router-dom';
import {
  Box,
  Divider,
  Loader,
  Paper,
  Text,
} from '@mantine/core';
import { SETTINGS_GROUPS } from '../config/settingsNav';
import useAuthStore from '../store/auth';
import { USER_LEVELS } from '../constants';
import UiSettingsForm from '../components/forms/settings/UiSettingsForm.jsx';
import ErrorBoundary from '../components/ErrorBoundary.jsx';

const UserAgentsTable = React.lazy(
  () => import('../components/tables/UserAgentsTable.jsx')
);
const StreamProfilesTable = React.lazy(
  () => import('../components/tables/StreamProfilesTable.jsx')
);
const OutputProfilesTable = React.lazy(
  () => import('../components/tables/OutputProfilesTable.jsx')
);
const BackupManager = React.lazy(
  () => import('../components/backups/BackupManager.jsx')
);
const UserLimitsForm = React.lazy(
  () => import('../components/forms/settings/UserLimitsForm.jsx')
);
const NetworkAccessForm = React.lazy(
  () => import('../components/forms/settings/NetworkAccessForm.jsx')
);
const ProxySettingsForm = React.lazy(
  () => import('../components/forms/settings/ProxySettingsForm.jsx')
);
const StreamSettingsForm = React.lazy(
  () => import('../components/forms/settings/StreamSettingsForm.jsx')
);
const DvrSettingsForm = React.lazy(
  () => import('../components/forms/settings/DvrSettingsForm.jsx')
);
const SystemSettingsForm = React.lazy(
  () => import('../components/forms/settings/SystemSettingsForm.jsx')
);
const EpgSettingsForm = React.lazy(
  () => import('../components/forms/settings/EpgSettingsForm.jsx')
);
const NavOrderForm = React.lazy(
  () => import('../components/forms/settings/NavOrderForm.jsx')
);

const COMPONENT_MAP = {
  'ui-settings': UiSettingsForm,
  'nav-order': NavOrderForm,
  'stream-settings': StreamSettingsForm,
  'stream-profiles': StreamProfilesTable,
  'output-profiles': OutputProfilesTable,
  'dvr-settings': DvrSettingsForm,
  'epg-settings': EpgSettingsForm,
  'user-agents': UserAgentsTable,
  'network-access': NetworkAccessForm,
  'proxy-settings': ProxySettingsForm,
  'system-settings': SystemSettingsForm,
  'user-limits': UserLimitsForm,
  backups: BackupManager,
};

const SettingsPage = () => {
  const authUser = useAuthStore((s) => s.user);
  const location = useLocation();
  const isAdmin = authUser.user_level >= USER_LEVELS.ADMIN;

  const [activeSection, setActiveSection] = useState(
    () => location.hash.replace('#', '') || null
  );

  useEffect(() => {
    const hash = location.hash.replace('#', '');
    if (hash) setActiveSection(hash);
  }, [location.hash]);

  const visibleGroups = SETTINGS_GROUPS.filter((g) => !g.adminOnly || isAdmin);
  const allSections = visibleGroups.flatMap((g) => g.sections);
  const activeSectionConfig = activeSection
    ? (allSections.find((s) => s.id === activeSection) ?? null)
    : null;
  const ActiveComponent = activeSectionConfig ? COMPONENT_MAP[activeSectionConfig.id] : null;

  return (
    <Box p={10} maw={900} mx="auto">
      {ActiveComponent ? (
        <Paper withBorder p="md" radius="md">
          <Text size="lg" fw={600} mb={6}>
            {activeSectionConfig.label}
          </Text>
          <Divider mb="md" />
          <ErrorBoundary>
            <Suspense fallback={<Loader />}>
              <ActiveComponent active={true} />
            </Suspense>
          </ErrorBoundary>
        </Paper>
      ) : (
        <Box
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            height: '100%',
            minHeight: 200,
          }}
        >
          <Text c="dimmed" size="sm">
            Select a setting from the sidebar
          </Text>
        </Box>
      )}
    </Box>
  );
};

export default SettingsPage;
