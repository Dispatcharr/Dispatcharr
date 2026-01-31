import React, { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  Container,
  Title,
  Text,
  Loader,
  Center,
  Stack,
  Alert,
  Button,
  Group,
} from '@mantine/core';
import { AlertCircle, ArrowLeft } from 'lucide-react';
import API from '../api';
import PluginRenderer from '../components/plugins/PluginRenderer';

/**
 * PluginPage - Renders a custom plugin page using the UI schema
 *
 * This component:
 * 1. Fetches the plugin's page schema from the API
 * 2. Passes the schema to PluginRenderer for rendering
 * 3. Handles loading and error states
 */
const PluginPage = () => {
  const { pluginKey, pageId = 'main' } = useParams();
  const navigate = useNavigate();

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [pageData, setPageData] = useState(null);
  const [plugin, setPlugin] = useState(null);

  useEffect(() => {
    const fetchPage = async () => {
      setLoading(true);
      setError(null);

      try {
        const response = await API.getPluginPage(pluginKey, pageId);
        setPlugin(response.plugin);
        setPageData(response.page);
      } catch (err) {
        const message = err?.body?.error || err?.message || 'Failed to load plugin page';
        setError(message);
      } finally {
        setLoading(false);
      }
    };

    fetchPage();
  }, [pluginKey, pageId]);

  if (loading) {
    return (
      <Center h="50vh">
        <Stack align="center" gap="md">
          <Loader size="lg" />
          <Text c="dimmed">Loading plugin...</Text>
        </Stack>
      </Center>
    );
  }

  if (error) {
    return (
      <Container size="sm" mt="xl">
        <Alert
          icon={<AlertCircle size={16} />}
          title="Error loading plugin page"
          color="red"
          variant="filled"
        >
          {error}
        </Alert>
        <Group mt="md">
          <Button
            leftSection={<ArrowLeft size={16} />}
            variant="subtle"
            onClick={() => navigate('/plugins')}
          >
            Back to Plugins
          </Button>
        </Group>
      </Container>
    );
  }

  if (!pageData) {
    return (
      <Container size="sm" mt="xl">
        <Alert
          icon={<AlertCircle size={16} />}
          title="Page not found"
          color="yellow"
        >
          This plugin does not have a custom page defined.
        </Alert>
        <Group mt="md">
          <Button
            leftSection={<ArrowLeft size={16} />}
            variant="subtle"
            onClick={() => navigate('/plugins')}
          >
            Back to Plugins
          </Button>
        </Group>
      </Container>
    );
  }

  return (
    <Container fluid p="md">
      {/* Page header */}
      {pageData.title && (
        <Stack gap="xs" mb="lg">
          <Title order={2}>{pageData.title}</Title>
          {pageData.description && (
            <Text c="dimmed">{pageData.description}</Text>
          )}
        </Stack>
      )}

      {/* Render the page components */}
      <PluginRenderer
        pluginKey={pluginKey}
        components={pageData.components || []}
        modals={pageData.modals || []}
      />
    </Container>
  );
};

export default PluginPage;
