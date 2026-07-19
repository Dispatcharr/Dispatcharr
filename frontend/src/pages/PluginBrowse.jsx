import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  ActionIcon,
  AppShellMain,
  Badge,
  Box,
  Button,
  Group,
  Loader,
  NativeSelect,
  Pagination,
  Select,
  SimpleGrid,
  Text,
  TextInput,
} from '@mantine/core';
import { Package, RefreshCcw, Search } from 'lucide-react';
import { usePluginStore } from '../store/plugins.jsx';
import useSettingsStore from '../store/settings.jsx';
import AvailablePluginCard from '../components/cards/AvailablePluginCard.jsx';
import ManageReposModal from '../components/modals/ManageReposModal.jsx';
import { showNotification } from '../utils/notificationUtils.js';
import { reloadPlugins } from '../utils/pages/PluginsUtils.js';
import { compareVersions } from '../utils/components/pluginUtils.js';

export default function PluginBrowsePage() {
  const repos = usePluginStore((s) => s.repos);
  const availablePlugins = usePluginStore((s) => s.availablePlugins);
  const availableLoading = usePluginStore((s) => s.availableLoading);
  const fetchRepos = usePluginStore((s) => s.fetchRepos);
  const fetchAvailablePlugins = usePluginStore((s) => s.fetchAvailablePlugins);
  const refreshRepo = usePluginStore((s) => s.refreshRepo);

  const appVersion = useSettingsStore((s) => s.version?.version || '');

  const [repoModalOpen, setRepoModalOpen] = useState(false);
  const [refreshingAll, setRefreshingAll] = useState(false);

  const recentlyInstalledSlugs = useRef(new Set());
  const recentlyUpdatedSlugs = useRef(new Set());
  const recentlyUninstalledSlugs = useRef(new Set());

  const [searchQuery, setSearchQuery] = useState('');
  const [sortBy, setSortBy] = useState('updated');
  const [filterRepo, setFilterRepo] = useState('all');
  const [filterStatus, setFilterStatus] = useState('all');
  const [page, setPage] = useState(1);
  const [perPage, setPerPage] = useState(() => {
    const stored = localStorage.getItem('pluginBrowsePerPage');
    return stored && !isNaN(Number(stored)) ? Number(stored) : 9;
  });
  const handlePerPageChange = (value) => {
    setPerPage(Number(value));
    localStorage.setItem('pluginBrowsePerPage', value);
  };

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
        if (p.install_status === 'update_available') return -1;
        if (recentlyUpdatedSlugs.current.has(p.slug)) return -1;
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

  // Reset to page 1 when filters/search/page-size change
  React.useEffect(() => {
    setPage(1);
  }, [searchQuery, filterRepo, filterStatus, sortBy, perPage]);

  const totalPages = Math.ceil(filteredPlugins.length / perPage);
  const paginatedPlugins = filteredPlugins.slice(
    (page - 1) * perPage,
    page * perPage
  );

  return (
    <AppShellMain
      style={{
        padding: 0,
        display: 'flex',
        flexDirection: 'column',
        minHeight: '100%',
      }}
    >
      <Box p={16} pb={60} style={{ flex: 1 }}>
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
                No plugins match your filters. Try adjusting your search or
                filter criteria.
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
          <SimpleGrid cols={{ base: 1, md: 2, xl: 3 }} spacing="md">
            {paginatedPlugins.map((p) => (
              <AvailablePluginCard
                key={`${p.repo_id}-${p.slug}`}
                plugin={p}
                appVersion={appVersion}
                multiRepo={repos.length > 1}
                onBeforeInstall={(slug) => {
                  if (slug) {
                    if (p.install_status === 'update_available') {
                      recentlyUpdatedSlugs.current.add(slug);
                    } else {
                      recentlyInstalledSlugs.current.add(slug);
                    }
                  }
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
        )}
      </Box>

      {!loading && filteredPlugins.length > 0 && (
        <Box
          style={{
            position: 'fixed',
            bottom: 0,
            left: 'var(--app-shell-navbar-offset, 0rem)',
            right: 0,
            zIndex: 100,
            background: '#1A1A1E',
            borderTop: '1px solid #2A2A2E',
          }}
        >
          <Group gap={5} justify="center" style={{ padding: 8 }}>
            <Text size="xs">Page Size</Text>
            <NativeSelect
              size="xxs"
              value={String(perPage)}
              data={['9', '18', '27', '36']}
              onChange={(e) => handlePerPageChange(e.target.value)}
              styles={{ input: { textAlignLast: 'center' } }}
            />
            <Pagination
              total={totalPages}
              value={page}
              onChange={setPage}
              size="xs"
              withEdges
            />
            <Text size="xs">
              {`${(page - 1) * perPage + 1} to ${Math.min(page * perPage, filteredPlugins.length)} of ${filteredPlugins.length}`}
            </Text>
          </Group>
        </Box>
      )}

      <ManageReposModal
        opened={repoModalOpen}
        onClose={() => setRepoModalOpen(false)}
      />
    </AppShellMain>
  );
}
