import React, { Suspense } from 'react';
import { useLocation } from 'react-router-dom';
import {
  Box,
  Divider,
  Loader,
  Paper,
  Text,
} from '@mantine/core';
import { getVisibleSettingsGroups } from '../config/settingsNav';
import useAuthStore from '../store/auth';
import { USER_LEVELS } from '../constants';
import ErrorBoundary from '../components/ErrorBoundary.jsx';

const SettingsPage = () => {
  const authUser = useAuthStore((s) => s.user);
  const location = useLocation();
  const isAdmin = authUser.user_level >= USER_LEVELS.ADMIN;

  const activeSection = location.hash.replace('#', '') || null;

  const visibleGroups = getVisibleSettingsGroups(isAdmin);
  const allSections = visibleGroups.flatMap((g) => g.sections);
  const activeSectionConfig = activeSection
    ? (allSections.find((s) => s.id === activeSection) ?? null)
    : null;
  const ActiveComponent = activeSectionConfig?.Component ?? null;

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
