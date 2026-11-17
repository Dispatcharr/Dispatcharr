import { Button, Group } from '@mantine/core';
import { GitFork, Package, RefreshCw } from 'lucide-react';

export default function PluginPageActions({
  onManageRepos,
  onCheckForUpdates,
  checkingForUpdates = false,
}) {
  return (
    <Group gap="xs">
      <Button
        size="xs"
        variant="light"
        color="blue"
        component="a"
        href="https://github.com/Dispatcharr/Plugins?tab=contributing-ov-file"
        target="_blank"
        rel="noopener noreferrer"
        leftSection={<Package size={14} />}
      >
        Publish Your Plugin
      </Button>
      <Button
        size="xs"
        variant="light"
        leftSection={<GitFork size={14} />}
        onClick={onManageRepos}
      >
        Manage Repos
      </Button>
      <Button
        size="xs"
        variant="light"
        color="blue"
        leftSection={<RefreshCw size={14} />}
        onClick={onCheckForUpdates}
        loading={checkingForUpdates}
        disabled={checkingForUpdates}
      >
        Check for Updates
      </Button>
    </Group>
  );
}
