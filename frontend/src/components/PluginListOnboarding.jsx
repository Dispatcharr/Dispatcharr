import { Box, Button, SimpleGrid, Text } from '@mantine/core';
import { Compass, RotateCw, Upload } from 'lucide-react';
import { Link } from 'react-router-dom';

const OnboardingCard = ({ title, children, action }) => (
  <Box
    p="md"
    style={{
      display: 'flex',
      flexDirection: 'column',
      height: '100%',
      minHeight: 190,
      background: 'rgba(39, 39, 42, 0.9)',
      border: '1px solid rgba(63, 63, 70, 0.9)',
      borderRadius: 'var(--mantine-radius-sm)',
    }}
  >
    <Text fw={600}>{title}</Text>
    <Text size="sm" c="dimmed" mt={4} mb="md">
      {children}
    </Text>
    <Box style={{ marginTop: 'auto' }}>{action}</Box>
  </Box>
);

export default function PluginListOnboarding({ onInstallPlugin, onReloadAllPlugins }) {
  return (
    <Box
      ta="center"
      py="xl"
      style={{
        minHeight: 'calc(100vh - 220px)',
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'center',
      }}
    >
      <Text size="lg" c="dimmed">
        No plugins installed yet
      </Text>
      <SimpleGrid
        cols={{ base: 1, sm: 3 }}
        spacing="md"
        mt="lg"
        ta="left"
        style={{ alignItems: 'stretch' }}
      >
        <OnboardingCard
          title="Find Plugins"
          action={
            <Button
              component={Link}
              to="/plugins/browse"
              size="xs"
              variant="light"
              color="blue"
              leftSection={<Compass size={14} />}
            >
              Browse Plugins
            </Button>
          }
        >
          Browse configured repositories and install a managed plugin.
        </OnboardingCard>
        <OnboardingCard
          title="Install a ZIP"
          action={
            <Button
              size="xs"
              variant="default"
              leftSection={<Upload size={14} />}
              onClick={onInstallPlugin}
            >
              Install Plugin
            </Button>
          }
        >
          Upload a plugin ZIP from your computer.
        </OnboardingCard>
        <OnboardingCard
          title="Use a Plugin Folder"
          action={
            <Button
              size="xs"
              variant="default"
              leftSection={<RotateCw size={14} />}
              onClick={onReloadAllPlugins}
            >
              Reload Plugins
            </Button>
          }
        >
          Add a plugin folder to <code>/data/plugins</code>, then reload it.
        </OnboardingCard>
      </SimpleGrid>
    </Box>
  );
}
