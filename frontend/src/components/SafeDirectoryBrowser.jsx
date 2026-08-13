import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Badge,
  Box,
  Button,
  FileInput,
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
  FileText,
  Folder,
  FolderPlus,
  FolderOpen,
  HardDrive,
  Home,
  Search,
  Upload,
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
    accumulated = accumulated === '/' ? `/${part}` : `${accumulated}/${part}`;
    crumbs.push({ label: part, path: accumulated });
  });
  return crumbs;
}

/**
 * Reusable, server-scoped path browser.
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
  onUpload,
  uploadAccept,
  uploadLabel = 'Upload file',
}) {
  const [listing, setListing] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [search, setSearch] = useState('');
  const [createOpened, setCreateOpened] = useState(false);
  const [folderName, setFolderName] = useState('');
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState('');
  const [selectedFilePath, setSelectedFilePath] = useState('');
  const [uploadFile, setUploadFile] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState('');

  const load = useCallback(
    async (path = '', enterSingleRoot = false, fallbackToRoots = false) => {
      setLoading(true);
      setError('');
      setSearch('');
      setSelectedFilePath('');
      try {
        let result;
        try {
          result = await API.browseSafeDirectories(scope, path);
        } catch (requestError) {
          if (!fallbackToRoots || !path) throw requestError;
          result = await API.browseSafeDirectories(scope, '');
        }
        if (enterSingleRoot && !result.path) {
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
        setSelectedFilePath(result.selected_path || '');
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
    setUploadFile(null);
    setUploadError('');
    load(initialPath, true, true);
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
  const selectsFiles = listing?.selection_mode === 'file';

  const openCreateFolder = () => {
    setFolderName('');
    setCreateError('');
    setCreateOpened(true);
  };

  const createFolder = async (event) => {
    event.preventDefault();
    const name = folderName.trim();
    if (!name || !listing?.path) return;
    setCreating(true);
    setCreateError('');
    try {
      const created = await API.createSafeDirectory(scope, listing.path, name);
      setCreateOpened(false);
      setFolderName('');
      await load(created.path);
    } catch (requestError) {
      setCreateError(apiErrorText(requestError));
    } finally {
      setCreating(false);
    }
  };

  const uploadSelectedFile = async () => {
    if (!uploadFile || !onUpload) return;
    setUploading(true);
    setUploadError('');
    try {
      const result = await onUpload(uploadFile);
      const uploadedPath = String(result?.path || '').trim();
      if (!uploadedPath) {
        throw new Error('The upload did not return a selectable file path.');
      }
      onSelect(uploadedPath);
    } catch (uploadFailure) {
      setUploadError(apiErrorText(uploadFailure));
    } finally {
      setUploading(false);
    }
  };

  return (
    <>
      <Modal
        opened={createOpened}
        onClose={() => !creating && setCreateOpened(false)}
        title="Create Folder"
        size="sm"
        centered
        zIndex={430}
      >
        <form onSubmit={createFolder}>
          <Stack gap="md">
            <Text size="sm" c="dimmed">
              The folder will be created in {listing?.path}.
            </Text>
            <TextInput
              label="Folder name"
              placeholder="New folder"
              value={folderName}
              onChange={(event) => setFolderName(event.currentTarget.value)}
              error={createError || undefined}
              autoFocus
              disabled={creating}
            />
            <Group justify="end">
              <Button
                type="button"
                variant="default"
                onClick={() => setCreateOpened(false)}
                disabled={creating}
              >
                Cancel
              </Button>
              <Button
                type="submit"
                loading={creating}
                disabled={!folderName.trim()}
              >
                Create Folder
              </Button>
            </Group>
          </Stack>
        </form>
      </Modal>

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
                          leftSection={
                            index === 0 ? <Home size={12} /> : undefined
                          }
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
                  {listing.entries?.length || 0}{' '}
                  {selectsFiles ? 'items' : 'folders'}
                </Badge>
              </Group>
            </Paper>
          )}

          {listing?.path && (
            <Group gap="sm" align="flex-end">
              <TextInput
                label={
                  selectsFiles ? 'Filter folders and files' : 'Filter folders'
                }
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
                <Button
                  variant="light"
                  color="red"
                  size="xs"
                  onClick={showRoots}
                >
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
                        ? selectsFiles
                          ? 'No folders or matching files found.'
                          : 'No subdirectories found.'
                        : selectsFiles
                          ? 'No folders or files match your search.'
                          : 'No folders match your search.'}
                    </Text>
                  </Stack>
                ) : (
                  <Stack gap={4}>
                    {filteredEntries.map((entry) => (
                      <UnstyledButton
                        key={entry.path}
                        onClick={() =>
                          entry.type === 'file'
                            ? setSelectedFilePath(entry.path)
                            : load(entry.path)
                        }
                        style={{
                          width: '100%',
                          padding: '10px 12px',
                          borderRadius: 8,
                          border: '1px solid rgba(148, 163, 184, 0.18)',
                          background:
                            entry.type === 'file' &&
                            selectedFilePath === entry.path
                              ? 'rgba(34, 139, 230, 0.22)'
                              : 'rgba(15, 23, 42, 0.35)',
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
                            {entry.type === 'file' ? (
                              <FileText size={16} />
                            ) : (
                              <Folder size={16} />
                            )}
                            <Box style={{ minWidth: 0 }}>
                              <Text size="sm" fw={600} lineClamp={1}>
                                {entry.name || entry.path}
                              </Text>
                              <Text size="xs" c="dimmed" lineClamp={1}>
                                {entry.path}
                              </Text>
                            </Box>
                          </Group>
                          {entry.type !== 'file' && (
                            <ChevronRight
                              size={14}
                              color="var(--mantine-color-dimmed)"
                            />
                          )}
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

          {onUpload && (
            <Paper withBorder radius="md" p="sm">
              <Stack gap="xs">
                <Text size="sm" fw={600}>
                  {uploadLabel}
                </Text>
                <Group align="flex-end" gap="sm" wrap="nowrap">
                  <FileInput
                    aria-label={uploadLabel}
                    placeholder="Choose a file"
                    accept={uploadAccept}
                    value={uploadFile}
                    onChange={setUploadFile}
                    clearable
                    disabled={uploading}
                    style={{ flex: 1 }}
                  />
                  <Button
                    variant="light"
                    leftSection={<Upload size={14} />}
                    onClick={uploadSelectedFile}
                    loading={uploading}
                    disabled={!uploadFile || uploading}
                  >
                    Upload
                  </Button>
                </Group>
                {uploadError && (
                  <Text size="xs" c="red">
                    {uploadError}
                  </Text>
                )}
              </Stack>
            </Paper>
          )}

          <Group justify="space-between">
            <Group gap="sm">
              <Button
                variant="light"
                size="xs"
                onClick={() => load(listing?.path || '')}
                loading={loading}
                disabled={!listing?.configured}
              >
                Refresh
              </Button>
              {listing?.path && listing.allows_create && (
                <Button
                  variant="light"
                  size="xs"
                  leftSection={<FolderPlus size={14} />}
                  onClick={openCreateFolder}
                  disabled={!listing.can_create || loading}
                >
                  Create Folder
                </Button>
              )}
            </Group>
            <Group gap="sm">
              <Button variant="subtle" onClick={onClose}>
                Cancel
              </Button>
              <Button
                onClick={() =>
                  onSelect(selectsFiles ? selectedFilePath : listing.path)
                }
                disabled={
                  loading || (selectsFiles ? !selectedFilePath : !listing?.path)
                }
              >
                {selectsFiles ? 'Use this file' : 'Use this folder'}
              </Button>
            </Group>
          </Group>
        </Stack>
      </Modal>
    </>
  );
}
