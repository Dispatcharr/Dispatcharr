import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  ActionIcon,
  AppShellMain,
  Badge,
  Box,
  Button,
  Group,
  Loader,
  Modal,
  NumberInput,
  Pagination,
  Select,
  SimpleGrid,
  Stack,
  Text,
  Textarea,
  TextInput,
} from '@mantine/core';
import API from '../api.js';
import {
  RefreshCcw,
  Trash2,
  Plus,
  Search,
  KeyRound,
  ShieldCheck,
  ShieldAlert,
  Package,
} from 'lucide-react';
import { usePluginStore } from '../store/plugins.jsx';
import useSettingsStore from '../store/settings.jsx';
import AvailablePluginCard from '../components/cards/AvailablePluginCard.jsx';
import { showNotification } from '../utils/notificationUtils.js';
import { reloadPlugins } from '../utils/pages/PluginsUtils.js';
import { compareVersions } from '../components/pluginUtils.js';

export default function PluginBrowsePage() {
  const repos = usePluginStore((s) => s.repos);
  const reposLoading = usePluginStore((s) => s.reposLoading);
  const availablePlugins = usePluginStore((s) => s.availablePlugins);
  const availableLoading = usePluginStore((s) => s.availableLoading);
  const fetchRepos = usePluginStore((s) => s.fetchRepos);
  const fetchAvailablePlugins = usePluginStore((s) => s.fetchAvailablePlugins);
  const refreshRepo = usePluginStore((s) => s.refreshRepo);
  const addRepo = usePluginStore((s) => s.addRepo);
  const removeRepo = usePluginStore((s) => s.removeRepo);
  const updateRepo = usePluginStore((s) => s.updateRepo);

  const appVersion = useSettingsStore((s) => s.version?.version || '');

  const [repoModalOpen, setRepoModalOpen] = useState(false);
  const [newRepoUrl, setNewRepoUrl] = useState('');
  const [newRepoPublicKey, setNewRepoPublicKey] = useState('');
  const [addingRepo, setAddingRepo] = useState(false);
  const [refreshingAll, setRefreshingAll] = useState(false);
  const [editingKeyRepoId, setEditingKeyRepoId] = useState(null);
  const [editKeyValue, setEditKeyValue] = useState('');
  const [savingKey, setSavingKey] = useState(false);
  const [showAddRepo, setShowAddRepo] = useState(false);
  const [deleteConfirmId, setDeleteConfirmId] = useState(null);
  const [gpgKeyFocused, setGpgKeyFocused] = useState(false);
  const [repoPreview, setRepoPreview] = useState(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const previewTimer = useRef(null);
  const [refreshInterval, setRefreshInterval] = useState(6);
  const [savingInterval, setSavingInterval] = useState(false);
  const saveIntervalTimer = useRef(null);

  const recentlyInstalledSlugs = useRef(new Set());
  const recentlyUninstalledSlugs = useRef(new Set());

  const [searchQuery, setSearchQuery] = useState('');
  const [sortBy, setSortBy] = useState('updated');
  const [filterRepo, setFilterRepo] = useState('all');
  const [filterStatus, setFilterStatus] = useState('all');
  const [page, setPage] = useState(1);
  const perPage = 9;

  const hasFetched = useRef(false);

  useEffect(() => {
    if (!hasFetched.current) {
      hasFetched.current = true;
      fetchRepos();
      fetchAvailablePlugins();
    }
  }, [fetchRepos, fetchAvailablePlugins]);

  const handleRefreshAll = useCallback(async () => {
    setRefreshingAll(true);
    try {
      for (const repo of usePluginStore.getState().repos) {
        await refreshRepo(repo.id);
      }
      await fetchAvailablePlugins();
      await reloadPlugins();
      usePluginStore.getState().invalidatePlugins();
      showNotification({
        title: 'Refreshed',
        message: 'All plugin repos refreshed',
        color: 'green',
      });
    } catch {
      showNotification({
        title: 'Error',
        message: 'Some repos failed to refresh',
        color: 'red',
      });
    } finally {
      setRefreshingAll(false);
    }
  }, [refreshRepo, fetchAvailablePlugins]);

  const handleAddRepo = useCallback(async () => {
    if (!newRepoUrl.trim()) return;
    setAddingRepo(true);
    try {
      await addRepo({
        url: newRepoUrl.trim(),
        public_key: newRepoPublicKey.trim(),
      });
      setNewRepoUrl('');
      setNewRepoPublicKey('');
      setRepoPreview(null);
      setShowAddRepo(false);
      await fetchAvailablePlugins();
      showNotification({
        title: 'Added',
        message: 'Plugin repo added',
        color: 'green',
      });
    } catch {
      // Error notification handled by API layer
    } finally {
      setAddingRepo(false);
    }
  }, [newRepoUrl, newRepoPublicKey, addRepo, fetchAvailablePlugins]);

  const handleDeleteRepo = useCallback(
    async (id) => {
      await removeRepo(id);
      setDeleteConfirmId(null);
      await fetchAvailablePlugins();
      showNotification({
        title: 'Removed',
        message: 'Plugin repo removed',
        color: 'green',
      });
    },
    [removeRepo, fetchAvailablePlugins]
  );

  const handleEditKey = useCallback((repo) => {
    setEditingKeyRepoId(repo.id);
    setEditKeyValue(repo.public_key || '');
  }, []);

  const handleSaveKey = useCallback(async () => {
    if (editingKeyRepoId == null) return;
    setSavingKey(true);
    try {
      await updateRepo(editingKeyRepoId, { public_key: editKeyValue });
      await refreshRepo(editingKeyRepoId);
      await fetchAvailablePlugins();
      showNotification({
        title: 'Updated',
        message: 'Public key updated',
        color: 'green',
      });
      setEditingKeyRepoId(null);
      setEditKeyValue('');
    } catch {
      showNotification({
        title: 'Error',
        message: 'Failed to update key',
        color: 'red',
      });
    } finally {
      setSavingKey(false);
    }
  }, [
    editingKeyRepoId,
    editKeyValue,
    updateRepo,
    refreshRepo,
    fetchAvailablePlugins,
  ]);

  const loadRepoSettings = useCallback(async () => {
    const data = await API.getPluginRepoSettings();
    if (data) setRefreshInterval(data.refresh_interval_hours ?? 6);
  }, []);

  const handleSaveInterval = useCallback((val) => {
    const hours = val ?? 0;
    setRefreshInterval(hours);
    if (saveIntervalTimer.current) clearTimeout(saveIntervalTimer.current);
    saveIntervalTimer.current = setTimeout(async () => {
      setSavingInterval(true);
      try {
        await API.updatePluginRepoSettings({ refresh_interval_hours: hours });
      } catch {
        // Error notification handled by API layer
      } finally {
        setSavingInterval(false);
      }
    }, 800);
  }, []);

  // Debounced manifest preview
  const fetchPreview = useCallback((url, publicKey) => {
    if (previewTimer.current) clearTimeout(previewTimer.current);
    if (!url.trim() || !url.match(/^https?:\/\/.+/i)) {
      setRepoPreview(null);
      setPreviewLoading(false);
      return;
    }
    setPreviewLoading(true);
    previewTimer.current = setTimeout(async () => {
      const result = await API.previewPluginRepo(url.trim(), publicKey?.trim());
      setRepoPreview(result);
      setPreviewLoading(false);
    }, 600);
  }, []);

  // Cleanup any pending timers on unmount
  useEffect(() => {
    return () => {
      if (previewTimer.current) clearTimeout(previewTimer.current);
      if (saveIntervalTimer.current) clearTimeout(saveIntervalTimer.current);
    };
  }, []);
  // Load settings when modal opens
  useEffect(() => {
    if (repoModalOpen) loadRepoSettings();
  }, [repoModalOpen, loadRepoSettings]);

  const loading = availableLoading && availablePlugins.length === 0;

  // Build repo filter options from available plugins
  const repoOptions = React.useMemo(() => {
    const seen = new Map();
    availablePlugins.forEach((p) => {
      if (!seen.has(p.repo_id)) {
        seen.set(p.repo_id, p.repo_name || `Repo ${p.repo_id}`);
      }
    });
    return [
      { value: 'all', label: 'All Repos' },
      ...Array.from(seen, ([id, name]) => ({ value: String(id), label: name })),
    ];
  }, [availablePlugins]);

  // Filter and sort plugins
  const filteredPlugins = React.useMemo(() => {
    let list = [...availablePlugins];

    // Text search
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase().trim();
      list = list.filter(
        (p) =>
          p.name?.toLowerCase().includes(q) ||
          p.description?.toLowerCase().includes(q) ||
          p.author?.toLowerCase().includes(q)
      );
    }

    // Repo filter
    if (filterRepo !== 'all') {
      list = list.filter((p) => String(p.repo_id) === filterRepo);
    }

    // Status filter
    if (filterStatus === 'installed') {
      list = list.filter((p) => p.installed);
    } else if (filterStatus === 'not-installed') {
      list = list.filter((p) => !p.installed);
    } else if (filterStatus === 'compatible') {
      list = list.filter((p) => {
        const meetsMin =
          !p.min_dispatcharr_version ||
          compareVersions(appVersion, p.min_dispatcharr_version) >= 0;
        const meetsMax =
          !p.max_dispatcharr_version ||
          compareVersions(appVersion, p.max_dispatcharr_version) <= 0;
        return meetsMin && meetsMax;
      });
    }

    // Sort
    list.sort((a, b) => {
      // Pre-sort weights: deprecated → installed → incompatible sink to bottom (in that order)
      // Recently installed plugins are exempt so they don't jump away after install
      const weight = (p) => {
        if (recentlyInstalledSlugs.current.has(p.slug)) return 0;
        if (recentlyUninstalledSlugs.current.has(p.slug)) return 2;
        const meetsMin =
          !p.min_dispatcharr_version ||
          compareVersions(appVersion, p.min_dispatcharr_version) >= 0;
        const meetsMax =
          !p.max_dispatcharr_version ||
          compareVersions(appVersion, p.max_dispatcharr_version) <= 0;
        if (p.deprecated) return 1;
        if (p.installed) return 2;
        if (!meetsMin || !meetsMax) return 3;
        return 0;
      };
      const wa = weight(a);
      const wb = weight(b);
      if (wa !== wb) return wa - wb;

      switch (sortBy) {
        case 'name-asc':
          return (a.name || '').localeCompare(b.name || '');
        case 'name-desc':
          return (b.name || '').localeCompare(a.name || '');
        case 'author':
          return (a.author || '').localeCompare(b.author || '');
        case 'updated':
          return (b.last_updated || '').localeCompare(a.last_updated || '');
        default:
          return 0;
      }
    });

    return list;
  }, [
    availablePlugins,
    searchQuery,
    filterRepo,
    filterStatus,
    sortBy,
    appVersion,
  ]);

  // Reset to page 1 when filters/search change
  React.useEffect(() => {
    setPage(1);
  }, [searchQuery, filterRepo, filterStatus, sortBy]);

  const totalPages = Math.ceil(filteredPlugins.length / perPage);
  const paginatedPlugins = filteredPlugins.slice(
    (page - 1) * perPage,
    page * perPage
  );

  return (
    <AppShellMain p={16}>
      <Group justify="space-between" mb="md">
        <Group gap="xs" align="center">
          <Text fw={700} size="lg">
            Find Plugins
          </Text>
          {availablePlugins.length > 0 && (
            <Badge variant="light" color="gray" size="sm">
              {availablePlugins.length} Plugins Available
            </Badge>
          )}
          {repos.length > 1 && (
            <Badge variant="light" color="gray" size="sm">
              {repos.length} Repos
            </Badge>
          )}
        </Group>
        <Group>
          <Button
            size="xs"
            variant="light"
            color="teal"
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
            onClick={() => setRepoModalOpen(true)}
          >
            Manage Repos
          </Button>
          <ActionIcon
            variant="light"
            onClick={handleRefreshAll}
            title="Refresh all repos"
            loading={refreshingAll}
          >
            <RefreshCcw size={18} />
          </ActionIcon>
        </Group>
      </Group>

      {loading && <Loader />}

      {!loading && (
        <Group gap="sm" mb="md" wrap="wrap">
          <TextInput
            placeholder="Search plugins..."
            leftSection={<Search size={14} />}
            size="xs"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.currentTarget.value)}
            style={{ flex: 1, minWidth: 180, maxWidth: 300 }}
          />
          <Select
            size="xs"
            allowDeselect={false}
            value={sortBy}
            onChange={setSortBy}
            data={[
              { value: 'name-asc', label: 'Name A-Z' },
              { value: 'name-desc', label: 'Name Z-A' },
              { value: 'author', label: 'Author' },
              { value: 'updated', label: 'Recently Updated' },
            ]}
            style={{ width: 170 }}
          />
          {repoOptions.length > 2 && (
            <Select
              size="xs"
              allowDeselect={false}
              value={filterRepo}
              onChange={setFilterRepo}
              data={repoOptions}
              style={{ width: 160 }}
            />
          )}
          <Select
            size="xs"
            allowDeselect={false}
            value={filterStatus}
            onChange={setFilterStatus}
            data={[
              { value: 'all', label: 'All Plugins' },
              { value: 'installed', label: 'Installed' },
              { value: 'not-installed', label: 'Not Installed' },
              { value: 'compatible', label: 'Compatible' },
            ]}
            style={{ width: 150 }}
          />
        </Group>
      )}

      {!loading &&
        filteredPlugins.length === 0 &&
        availablePlugins.length > 0 && (
          <Box>
            <Text c="dimmed">
              No plugins match your filters. Try adjusting your search or filter
              criteria.
            </Text>
          </Box>
        )}

      {!loading && availablePlugins.length === 0 && (
        <Box>
          <Text c="dimmed">
            No plugins available. Try refreshing repos or adding a new plugin
            repository.
          </Text>
        </Box>
      )}

      {!loading && filteredPlugins.length > 0 && (
        <>
          <SimpleGrid cols={{ base: 1, md: 2, xl: 3 }} spacing="md">
            {paginatedPlugins.map((p) => (
              <AvailablePluginCard
                key={`${p.repo_id}-${p.slug}`}
                plugin={p}
                appVersion={appVersion}
                multiRepo={repos.length > 1}
                onBeforeInstall={(slug) => {
                  if (slug) recentlyInstalledSlugs.current.add(slug);
                }}
                onInstalled={(slug) => {
                  if (slug) recentlyInstalledSlugs.current.add(slug);
                  fetchAvailablePlugins();
                }}
                onUninstalled={(slug) => {
                  if (slug) recentlyUninstalledSlugs.current.add(slug);
                }}
              />
            ))}
          </SimpleGrid>
          {totalPages > 1 && (
            <Group justify="center" mt="lg">
              <Pagination
                value={page}
                onChange={setPage}
                total={totalPages}
                size="sm"
              />
            </Group>
          )}
        </>
      )}

      {/* Manage Repos Modal */}
      <Modal
        opened={repoModalOpen}
        onClose={() => setRepoModalOpen(false)}
        title={
          <Group justify="space-between" align="flex-start" w="100%">
            <div style={{ flex: 1 }}>
              <Text fw={600}>Plugin Repositories</Text>
              <Text size="sm" c="dimmed" mt={4}>
                Add third-party plugin repositories or manage existing ones.
                Manifests are fetched automatically at the configured interval.
              </Text>
            </div>
            <div style={{ textAlign: 'left', flexShrink: 0 }}>
              <Text size="sm" fw={500} mb={2}>
                Refresh Interval
              </Text>
              <NumberInput
                value={refreshInterval}
                onChange={handleSaveInterval}
                min={0}
                max={168}
                size="xs"
                disabled={savingInterval}
                w={115}
              />
              <Text size="xs" c="dimmed" mt={2}>
                Hours, 0 to disable
              </Text>
            </div>
          </Group>
        }
        centered
        size="lg"
        styles={{
          title: { width: '100%' },
          header: { alignItems: 'flex-start' },
        }}
      >
        <Stack gap="md">
          {reposLoading && repos.length === 0 && <Loader size="sm" />}

          {repos.map((repo) => (
            <React.Fragment key={repo.id}>
              <Group
                justify="space-between"
                align="center"
                wrap="nowrap"
                style={{
                  padding: '8px 12px',
                  borderRadius: 8,
                  backgroundColor: 'var(--mantine-color-dark-6)',
                }}
              >
                <Box style={{ minWidth: 0, flex: 1 }}>
                  <Group gap="xs" align="center">
                    <Text fw={500} size="sm" lineClamp={1}>
                      {repo.name}
                    </Text>
                    {repo.is_official && (
                      <Badge
                        size="xs"
                        variant="filled"
                        style={{ backgroundColor: '#14917E' }}
                      >
                        Official Repo
                      </Badge>
                    )}
                    {repo.signature_verified === true && (
                      <Badge
                        size="xs"
                        variant="light"
                        color="green"
                        leftSection={<ShieldCheck size={10} />}
                      >
                        Verified Signature
                      </Badge>
                    )}
                    {repo.signature_verified === false && (
                      <Badge
                        size="xs"
                        variant="light"
                        color="red"
                        leftSection={<ShieldAlert size={10} />}
                      >
                        Invalid Signature
                      </Badge>
                    )}
                  </Group>
                  {repo.registry_url ? (
                    <Text size="xs" c="dimmed" lineClamp={1}>
                      <a
                        href={repo.registry_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        style={{
                          color: 'var(--mantine-color-blue-4)',
                          textDecoration: 'none',
                        }}
                      >
                        {repo.registry_url}
                      </a>
                    </Text>
                  ) : null}
                  <Text size="xs" c="dimmed" lineClamp={1}>
                    {repo.url}
                  </Text>
                  {repo.last_fetched && (
                    <Text
                      size="xs"
                      c={
                        repo.last_fetch_status &&
                        repo.last_fetch_status !== '200'
                          ? 'red'
                          : 'dimmed'
                      }
                    >
                      Last fetched:{' '}
                      {new Date(repo.last_fetched).toLocaleString()}
                      {repo.last_fetch_status &&
                      repo.last_fetch_status !== '200'
                        ? ` · ${repo.last_fetch_status}`
                        : repo.plugin_count != null
                          ? ` · ${repo.plugin_count} plugin${repo.plugin_count !== 1 ? 's' : ''} available`
                          : ''}
                    </Text>
                  )}
                </Box>
                {!repo.is_official && (
                  <Stack gap={4} align="center">
                    <ActionIcon
                      variant="subtle"
                      color="gray"
                      title="Edit public key"
                      onClick={() => handleEditKey(repo)}
                    >
                      <KeyRound size={16} />
                    </ActionIcon>
                    <ActionIcon
                      variant="subtle"
                      color="red"
                      title="Remove repo"
                      onClick={() => setDeleteConfirmId(repo.id)}
                    >
                      <Trash2 size={16} />
                    </ActionIcon>
                  </Stack>
                )}
              </Group>
              {editingKeyRepoId === repo.id && (
                <Stack gap="xs" mt="xs">
                  <Textarea
                    placeholder={
                      '-----BEGIN PGP PUBLIC KEY BLOCK-----\n\nOptional: Paste public GPG key here\n\n-----END PGP PUBLIC KEY BLOCK-----'
                    }
                    value={editKeyValue}
                    onChange={(e) => setEditKeyValue(e.currentTarget.value)}
                    size="xs"
                    minRows={3}
                    autosize
                  />
                  <Group gap="xs">
                    <Button
                      size="xs"
                      onClick={handleSaveKey}
                      loading={savingKey}
                    >
                      Save Key
                    </Button>
                    <Button
                      size="xs"
                      variant="subtle"
                      color="gray"
                      onClick={() => setEditingKeyRepoId(null)}
                    >
                      Cancel
                    </Button>
                  </Group>
                </Stack>
              )}
            </React.Fragment>
          ))}

          {!showAddRepo ? (
            <Button
              variant="light"
              leftSection={<Plus size={16} />}
              size="sm"
              onClick={() => setShowAddRepo(true)}
            >
              Add Repository
            </Button>
          ) : (
            <>
              <Text fw={500} size="sm" mt="sm">
                Add Repository
              </Text>
              <Box
                style={{
                  padding: '8px 12px',
                  borderRadius: 8,
                  minHeight: 90,
                  display: 'flex',
                  alignItems: 'center',
                  backgroundColor: 'var(--mantine-color-dark-6)',
                  border:
                    repoPreview && !previewLoading && !repoPreview.valid
                      ? '1px solid var(--mantine-color-red-7)'
                      : 'none',
                }}
              >
                {previewLoading ? (
                  <Group gap="xs" align="center">
                    <Loader size={14} />
                    <Text size="xs" c="dimmed">
                      Checking manifest...
                    </Text>
                  </Group>
                ) : repoPreview ? (
                  repoPreview.valid ? (
                    <Box>
                      <Group gap="xs" align="center">
                        <Text fw={500} size="sm">
                          {repoPreview.registry_name}
                        </Text>
                        {repoPreview.signature_verified === true && (
                          <Badge
                            size="xs"
                            variant="light"
                            color="green"
                            leftSection={<ShieldCheck size={10} />}
                          >
                            Verified Signature
                          </Badge>
                        )}
                        {repoPreview.signature_verified === false && (
                          <>
                            <Badge
                              size="xs"
                              variant="light"
                              color="gray"
                              leftSection={<ShieldCheck size={10} />}
                            >
                              Signed Manifest
                            </Badge>
                            <Text
                              size="xs"
                              c="var(--mantine-color-yellow-6)"
                              fs="italic"
                            >
                              Public key required for verification
                            </Text>
                          </>
                        )}
                        {repoPreview.signature_verified == null && (
                          <Badge size="xs" variant="light" color="gray">
                            No Signature
                          </Badge>
                        )}
                      </Group>
                      {repoPreview.registry_url ? (
                        <Text size="xs" c="dimmed">
                          <a
                            href={repoPreview.registry_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            style={{
                              color: 'var(--mantine-color-blue-4)',
                              textDecoration: 'none',
                            }}
                          >
                            {repoPreview.registry_url}
                          </a>
                        </Text>
                      ) : null}
                      <Text size="xs" c="dimmed" lineClamp={1}>
                        {newRepoUrl.trim()}
                      </Text>
                      <Text size="xs" c="dimmed">
                        {repoPreview.plugin_count} plugin
                        {repoPreview.plugin_count !== 1 ? 's' : ''} available
                      </Text>
                    </Box>
                  ) : (
                    <Text size="xs" c="red">
                      {repoPreview.errors?.join(' ') || 'Invalid manifest'}
                    </Text>
                  )
                ) : (
                  <Text size="xs" c="yellow">
                    Third-party repositories are not reviewed by the Dispatcharr
                    team.
                    <br />
                    Adding sources and installing plugins is done at your own
                    risk.
                  </Text>
                )}
              </Box>
              <TextInput
                placeholder="Repository Manifest URL (ending in .json)"
                value={newRepoUrl}
                onChange={(e) => {
                  setNewRepoUrl(e.currentTarget.value);
                  fetchPreview(e.currentTarget.value, newRepoPublicKey);
                }}
                size="sm"
              />
              <Textarea
                placeholder={
                  gpgKeyFocused
                    ? '-----BEGIN PGP PUBLIC KEY BLOCK-----\n\nPaste public GPG key here\n\n-----END PGP PUBLIC KEY BLOCK-----'
                    : 'Optional: Paste public GPG key here'
                }
                value={newRepoPublicKey}
                onChange={(e) => {
                  const value = e.currentTarget.value;
                  setNewRepoPublicKey(value);
                  fetchPreview(newRepoUrl, value);
                }}
                size="sm"
                minRows={gpgKeyFocused || newRepoPublicKey ? 4 : 1}
                maxRows={8}
                autosize
                onFocus={() => setGpgKeyFocused(true)}
                onBlur={() => {
                  if (!newRepoPublicKey) setGpgKeyFocused(false);
                }}
                styles={
                  repoPreview?.valid &&
                  repoPreview?.signature_verified === false &&
                  !newRepoPublicKey.trim()
                    ? {
                        input: { borderColor: 'var(--mantine-color-yellow-6)' },
                      }
                    : undefined
                }
              />
              <Group gap="xs" justify="flex-end">
                <Button
                  variant="subtle"
                  color="gray"
                  size="sm"
                  onClick={() => {
                    setShowAddRepo(false);
                    setNewRepoUrl('');
                    setNewRepoPublicKey('');
                    setRepoPreview(null);
                  }}
                >
                  Cancel
                </Button>
                <Button
                  onClick={handleAddRepo}
                  loading={addingRepo}
                  disabled={!newRepoUrl.trim()}
                  leftSection={<Plus size={16} />}
                  size="sm"
                >
                  Add Repo
                </Button>
              </Group>
            </>
          )}
        </Stack>
      </Modal>

      {/* Delete Confirmation Modal */}
      <Modal
        opened={deleteConfirmId != null}
        onClose={() => setDeleteConfirmId(null)}
        title="Remove Repository"
        size="sm"
        centered
      >
        <Text size="sm">Are you sure you want to remove this repository?</Text>
        <Text size="xs" c="dimmed" mt="xs">
          Plugins installed from this repo will remain installed but become
          unmanaged.
        </Text>
        <Group mt="md" justify="flex-end" gap="xs">
          <Button
            variant="subtle"
            color="gray"
            onClick={() => setDeleteConfirmId(null)}
          >
            Cancel
          </Button>
          <Button color="red" onClick={() => handleDeleteRepo(deleteConfirmId)}>
            Remove
          </Button>
        </Group>
      </Modal>
    </AppShellMain>
  );
}
