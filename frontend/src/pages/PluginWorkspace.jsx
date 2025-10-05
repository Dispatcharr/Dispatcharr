import React, { useMemo } from 'react';
import { useParams, useLocation, useNavigate } from 'react-router-dom';
import { AppShell, Box, Loader, Stack, Text, Tabs } from '@mantine/core';
import usePluginsStore from '../store/plugins';
import { PluginUIProvider, PluginCanvas } from '../plugin-ui';
import { ensureArray } from '../plugin-ui/utils';

const resolvePagePath = (pluginKey, page) => {
  if (!page) return `/plugins/${pluginKey}`;
  return page.route || `/plugins/${pluginKey}/${page.id}`;
};

const PluginWorkspace = ({ pluginKey: propKey, initialPageId }) => {
  const params = useParams();
  const location = useLocation();
  const navigate = useNavigate();

  const pluginKey = propKey || params.pluginKey;
  const routePageId = params.pageId;

  const plugin = usePluginsStore((state) =>
    pluginKey ? state.plugins[pluginKey] : null
  );
  const loading = usePluginsStore((state) => state.loading);

  const ui = plugin?.ui_schema || {};
  const pages = useMemo(() => ensureArray(ui.pages), [ui.pages]);

  const defaultPage = useMemo(() => {
    if (!pages.length) return null;
    const primary = pages.find((page) => (page.placement || 'plugin') === 'plugin');
    return primary || pages[0];
  }, [pages]);

  const effectivePageId = routePageId || initialPageId || defaultPage?.id;
  const targetPage = pages.find((page) => page.id === effectivePageId) || defaultPage;
  const layout = targetPage?.layout || ui.layout;

  const pageTitle = targetPage?.label || plugin?.name || 'Plugin';
  const pageDescription = targetPage?.description || plugin?.description || '';

  const tabPages = useMemo(
    () =>
      pages.filter((page) => {
        if (page.placement === 'sidebar') return false;
        if (page.placement === 'hidden') return false;
        return true;
      }),
    [pages]
  );

  if (!plugin && loading) {
    return (
      <AppShell.Main style={{ padding: 24 }}>
        <Loader />
      </AppShell.Main>
    );
  }

  if (!plugin) {
    return (
      <AppShell.Main style={{ padding: 24 }}>
        <Stack gap="sm">
          <Text fw={700} size="lg">
            Plugin not found
          </Text>
          <Text size="sm" c="dimmed">
            The requested plugin workspace does not exist. It may have been removed or is unavailable.
          </Text>
        </Stack>
      </AppShell.Main>
    );
  }

  if (!layout) {
    return (
      <AppShell.Main style={{ padding: 24 }}>
        <Stack gap="sm">
          <Text fw={700} size="lg">
            {plugin.name}
          </Text>
          <Text size="sm" c="dimmed">
            This plugin does not define an advanced workspace layout yet.
          </Text>
        </Stack>
      </AppShell.Main>
    );
  }

  const handleTabChange = (value) => {
    const nextPage = pages.find((page) => page.id === value);
    if (nextPage) {
      navigate(resolvePagePath(plugin.key, nextPage));
    }
  };

  return (
    <AppShell.Main style={{ padding: 24 }}>
      <Stack gap="md">
        <Box>
          <Text fw={700} size="lg">
            {pageTitle}
          </Text>
          {pageDescription && (
            <Text size="sm" c="dimmed">
              {pageDescription}
            </Text>
          )}
        </Box>

        {tabPages.length > 1 && (
          <Tabs
            value={targetPage?.id}
            onChange={handleTabChange}
            keepMounted={false}
            variant="outline"
          >
            <Tabs.List>
              {tabPages.map((page) => (
                <Tabs.Tab value={page.id} key={page.id}>
                  {page.label || page.id}
                </Tabs.Tab>
              ))}
            </Tabs.List>
          </Tabs>
        )}

        <PluginUIProvider pluginKey={plugin.key} plugin={plugin}>
          <PluginCanvas layout={layout} context={{ plugin, page: targetPage, location }} />
        </PluginUIProvider>
      </Stack>
    </AppShell.Main>
  );
};

export default PluginWorkspace;
