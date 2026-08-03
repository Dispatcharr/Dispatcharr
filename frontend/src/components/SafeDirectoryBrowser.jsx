import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Badge,
  Box,
  Button,
  Group,
  Loader,
  Modal,
  Paper,
  ScrollArea,
  Stack,
  Text,
  TextInput,
  UnstyledButton,
} from '@mantine/core';
import {
  ArrowUp,
  ChevronRight,
  Folder,
  FolderOpen,
  HardDrive,
  Home,
  Search,
} from 'lucide-react';

import API from '../api';

const apiErrorText = (error) =>
  error?.body?.detail || error?.message || 'The directory could not be opened.';

const pathLabel = (path) => {
  const normalized = String(path || '').replace(/\\/g, '/');
  if (normalized === '/') return '/';
  const parts = normalized.split('/').filter(Boolean);
  return parts.at(-1) || normalized;
};

function buildScopedBreadcrumbs(currentPath, root) {
  if (!currentPath) return [];
  const normalizedCurrent = currentPath.replace(/\\/g, '/');
  const normalizedRoot = String(root?.path || currentPath).replace(/\\/g, '/');
  const crumbs = [
    {
      label: root?.name || pathLabel(normalizedRoot),
      path: normalizedRoot,
    },
  ];
  if (normalizedCurrent === normalizedRoot) return crumbs;

  const relative = normalizedCurrent
    .slice(normalizedRoot === '/' ? 1 : normalizedRoot.length + 1)
    .split('/')
    .filter(Boolean);
  let accumulated = normalizedRoot;
  relative.forEach((part) => {
    accumulated =
      accumulated === '/' ? `/${part}` : `${accumulated}/${part}`;
    crumbs.push({ label: part, path: accumulated });
  });
  return crumbs;
}

/**
 * Reusable, server-scoped directory browser.
 *
 * `scope` must be registered in SAFE_DIRECTORY_BROWSER_SCOPES on the server.
 * The browser never accepts an allowed root from the client.
 */
export default function SafeDirectoryBrowser({
  opened,
  onClose,
  onSelect,
  scope,
  initialPath = '',
  title = 'Select directory',
}) {
  const [listing, setListing] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [search, setSearch] = useState('');

  const load = useCallback(
    async (path = '', enterSingleRoot = false) => {
      setLoading(true);
      setError('');
      setSearch('');
      try {
        let result = await API.browseSafeDirectories(scope, path);
        if (enterSingleRoot && !path) {
          const availableRoots = (result.roots || []).filter(
            (root) => root.available && root.readable
          );
          if (availableRoots.length === 1) {
            result = await API.browseSafeDirectories(
              scope,
              availableRoots[0].path
            );
          }
        }
        setListing(result);
      } catch (requestError) {
        setError(apiErrorText(requestError));
      } finally {
        setLoading(false);
      }
    },
    [scope]
  );

  useEffect(() => {
    if (!opened) return;
    setListing(null);
    load(initialPath, !initialPath);
  }, [initialPath, load, opened]);

  const breadcrumbs = useMemo(
    () => buildScopedBreadcrumbs(listing?.path, listing?.root),
    [listing?.path, listing?.root]
  );

  const filteredEntries = useMemo(() => {
    const entries = listing?.entries || [];
    const query = search.trim().toLocaleLowerCase();
    if (!query) return entries;
    return entries.filter(
      (entry) =>
        entry.name?.toLocaleLowerCase().includes(query) ||
        entry.path?.toLocaleLowerCase().includes(query)
    );
  }, [listing?.entries, search]);

  const showRoots = () => load('');

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title={title}
      size="xl"
      overlayProps={{ backgroundOpacity: 0.6, blur: 4 }}
      zIndex={410}
    >
      <Stack gap="md">
        {listing?.path && (
          <Paper withBorder radius="md" p="sm">
            <Group justify="space-between" align="center" wrap="nowrap">
              <ScrollArea type="auto" offsetScrollbars style={{ flex: 1 }}>
                <Group gap={6} wrap="nowrap">
                  <FolderOpen size={16} />
                  {breadcrumbs.map((crumb, index) => (
                    <Group
                      key={`${crumb.path}-${index}`}
                      gap={6}
                      wrap="nowrap"
                    >
                      <Button
                        variant="subtle"
                        size="compact-xs"
                        leftSection={index === 0 ? <Home size={12} /> : undefined}
                        onClick={() => load(crumb.path)}
                      >
                        {crumb.label}
                      </Button>
                      {index < breadcrumbs.length - 1 && (
                        <ChevronRight
                          size={12}
                          color="var(--mantine-color-dimmed)"
                        />
                      )}
                    </Group>
                  ))}
                </Group>
              </ScrollArea>
              <Badge variant="light" color="gray">
                {listing.entries?.length || 0} folders
              </Badge>
            </Group>
          </Paper>
        )}

        {listing?.path && (
          <Group gap="sm" align="flex-end">
            <TextInput
              label="Filter folders"
              placeholder="Search current directory"
              value={search}
              onChange={(event) => setSearch(event.currentTarget.value)}
              leftSection={<Search size={14} />}
              style={{ flex: 1 }}
            />
            <Button
              size="xs"
              variant="light"
              leftSection={<ArrowUp size={14} />}
              onClick={() => load(listing.parent)}
              disabled={!listing.parent || loading}
            >
              Up one level
            </Button>
          </Group>
        )}

        {error && (
          <Alert color="red" title="Unable to open directory">
            <Stack gap="xs">
              <Text size="sm">{error}</Text>
              <Button variant="light" color="red" size="xs" onClick={showRoots}>
                Show allowed roots
              </Button>
            </Stack>
          </Alert>
        )}

        {listing && !listing.configured && (
          <Alert color="yellow" title="No allowed directories are configured">
            <Text size="sm">
              {listing.configuration_hint ||
                'Configure an allowed directory scope on the server first.'}
            </Text>
          </Alert>
        )}

        {listing?.roots && listing.configured && (
          <Paper withBorder radius="md" p={4}>
            <Stack gap={4}>
              {listing.roots.map((root) => (
                <UnstyledButton
                  key={root.path}
                  disabled={!root.available || !root.readable}
                  onClick={() => load(root.path)}
                  style={{
                    width: '100%',
                    padding: '10px 12px',
                    borderRadius: 8,
                    border: '1px solid rgba(148, 163, 184, 0.18)',
                    background: 'rgba(15, 23, 42, 0.35)',
                    opacity: root.available && root.readable ? 1 : 0.55,
                  }}
                >
                  <Group justify="space-between" align="center" wrap="nowrap">
                    <Group
                      gap="sm"
                      align="center"
                      wrap="nowrap"
                      style={{ minWidth: 0 }}
                    >
                      <HardDrive size={16} />
                      <Box style={{ minWidth: 0 }}>
                        <Text size="sm" fw={600} lineClamp={1}>
                          {root.name || root.path}
                        </Text>
                        <Text size="xs" c="dimmed" lineClamp={1}>
                          {root.path}
                        </Text>
                      </Box>
                    </Group>
                    {root.available && root.readable ? (
                      <ChevronRight
                        size={14}
                        color="var(--mantine-color-dimmed)"
                      />
                    ) : (
                      <Badge color="red" variant="light" size="sm">
                        {!root.available ? 'Not mounted' : 'Not readable'}
                      </Badge>
                    )}
                  </Group>
                </UnstyledButton>
              ))}
            </Stack>
          </Paper>
        )}

        {listing?.path && (
          <Paper withBorder radius="md" p={4}>
            <ScrollArea h={320} offsetScrollbars>
              {loading ? (
                <Group justify="center" py="xl">
                  <Loader size="sm" />
                </Group>
              ) : filteredEntries.length === 0 ? (
                <Stack align="center" py="xl" gap={4}>
                  <Text c="dimmed" size="sm">
                    {listing.entries?.length === 0
                      ? 'No subdirectories found.'
                      : 'No folders match your search.'}
                  </Text>
                </Stack>
              ) : (
                <Stack gap={4}>
                  {filteredEntries.map((entry) => (
                    <UnstyledButton
                      key={entry.path}
                      onClick={() => load(entry.path)}
                      style={{
                        width: '100%',
                        padding: '10px 12px',
                        borderRadius: 8,
                        border: '1px solid rgba(148, 163, 184, 0.18)',
                        background: 'rgba(15, 23, 42, 0.35)',
                      }}
                    >
                      <Group
                        justify="space-between"
                        align="center"
                        wrap="nowrap"
                      >
                        <Group
                          gap="sm"
                          align="center"
                          wrap="nowrap"
                          style={{ minWidth: 0 }}
                        >
                          <Folder size={16} />
                          <Box style={{ minWidth: 0 }}>
                            <Text size="sm" fw={600} lineClamp={1}>
                              {entry.name || entry.path}
                            </Text>
                            <Text size="xs" c="dimmed" lineClamp={1}>
                              {entry.path}
                            </Text>
                          </Box>
                        </Group>
                        <ChevronRight
                          size={14}
                          color="var(--mantine-color-dimmed)"
                        />
                      </Group>
                    </UnstyledButton>
                  ))}
                </Stack>
              )}
            </ScrollArea>
          </Paper>
        )}

        {!listing?.path && loading && (
          <Group justify="center" py="xl">
            <Loader size="sm" />
          </Group>
        )}

        <Group justify="space-between">
          <Button
            variant="light"
            size="xs"
            onClick={() => load(listing?.path || '')}
            loading={loading}
            disabled={!listing?.configured}
          >
            Refresh
          </Button>
          <Group gap="sm">
            <Button variant="subtle" onClick={onClose}>
              Cancel
            </Button>
            <Button
              onClick={() => onSelect(listing.path)}
              disabled={!listing?.path || loading}
            >
              Use this folder
            </Button>
          </Group>
        </Group>
      </Stack>
    </Modal>
  );
}
