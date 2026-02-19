import React, { useEffect, useState } from 'react';
import {
  Box,
  Button,
  Group,
  Stack,
  Switch,
  Card,
  Flex,
  useMantineTheme,
  Text,
  Badge,
  Tooltip,
} from '@mantine/core';
import API from '../api';
import useConnectStore from '../store/connect';
import { SquarePlus, Webhook, FileCode, Logs } from 'lucide-react';
import ConnectionForm from '../components/forms/Connection';
import { SUBSCRIPTION_EVENTS } from '../constants';

export default function ConnectPage() {
  const { integrations, isLoading, fetchIntegrations } = useConnectStore();
  const theme = useMantineTheme();
  const [connection, setConnection] = useState(null);
  const [isConnectionModalOpen, setIsConnectionModalOpen] = useState(false);

  useEffect(() => {
    fetchIntegrations();
  }, [fetchIntegrations]);

  const newConnection = () => {
    setConnection(null);
    setIsConnectionModalOpen(true);
  };

  const editConnection = (connection) => {
    setConnection(connection);
    setIsConnectionModalOpen(true);
  };

  const deleteConnection = async (id) => {
    console.log('Deleting connection', id);
    await API.deleteConnectIntegration(id);
  };

  return (
    <Box p="md">
      <Button
        leftSection={<SquarePlus size={18} />}
        variant="light"
        size="sm"
        onClick={() => newConnection()}
        p={10}
        color={theme.tailwind.green[5]}
        style={{
          borderWidth: '1px',
          borderColor: theme.tailwind.green[5],
          color: 'white',
        }}
      >
        New Connection
      </Button>
      {isLoading && <div>Loading...</div>}
      {!isLoading && (
        <Box
          style={{
            gap: '1rem',
            gridTemplateColumns: 'repeat(auto-fill, minmax(400px, 1fr))',
            alignContent: 'start',
          }}
          display="grid"
          py={10}
        >
          {integrations.map((i) => (
            <IntegrationRow
              key={i.id}
              integration={i}
              editConnection={editConnection}
              deleteConnection={deleteConnection}
            />
          ))}
        </Box>
      )}

      <ConnectionForm
        connection={connection}
        isOpen={isConnectionModalOpen}
        onClose={() => setIsConnectionModalOpen(false)}
      />
    </Box>
  );
}

function IntegrationRow({ integration, editConnection, deleteConnection }) {
  const type = integration.type || 'webhook';
  const [enabled, setEnabled] = useState(!!integration.enabled);
  const webhookUrl = integration?.config?.url || '';
  const scriptPath = integration?.config?.path || '';

  const toggleIntegration = async () => {
    try {
      await API.updateConnectIntegration(integration.id, {
        ...integration,
        enabled: !enabled,
      });
      setEnabled(!enabled);
    } catch (error) {
      console.error('Failed to update integration', error);
    } finally {
    }
  };

  return (
    <Card
      key={integration.id}
      shadow="sm"
      padding="md"
      radius="md"
      withBorder
      style={{
        backgroundColor: '#27272A',
      }}
      color="#fff"
      w={'100%'}
    >
      <Stack gap="xs">
        <Group justify="space-between">
          <Group align="flex-start">
            {integration.type == 'webhook' ? <Webhook /> : <FileCode />}
            <Text fw={800}>{integration.name}</Text>
          </Group>
          <Switch
            label="Enabled"
            checked={enabled}
            onChange={toggleIntegration}
          />
        </Group>

        {type === 'webhook' ? (
          <Group gap={5} align="center">
            <Text fw={500}>Target:</Text>
            <Box style={{ flex: 1, minWidth: 0 }}>
              <Tooltip label={webhookUrl} withArrow multiline>
                <Text
                  style={{
                    whiteSpace: 'nowrap',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                  }}
                >
                  {webhookUrl}
                </Text>
              </Tooltip>
            </Box>
          </Group>
        ) : (
          <Group gap={5} align="center">
            <Text fw={500}>Target:</Text>
            <Box style={{ flex: 1, minWidth: 0 }}>
              <Tooltip label={scriptPath} withArrow multiline>
                <Text
                  style={{
                    whiteSpace: 'nowrap',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                  }}
                >
                  {scriptPath}
                </Text>
              </Tooltip>
            </Box>
          </Group>
        )}

        <Text>Triggers</Text>
        <Group>
          {integration.subscriptions.map(
            (sub) =>
              sub.enabled && (
                <Badge size="sm" variant="light" color="green">
                  {SUBSCRIPTION_EVENTS[sub.event] || sub.event}
                </Badge>
              )
          )}
        </Group>
      </Stack>

      <Flex mih={50} gap="xs" justify="flex-end" align="flex-end">
        <Button size="xs" onClick={() => editConnection(integration)}>
          Edit
        </Button>
        <Button
          variant="outline"
          size="xs"
          color="red"
          onClick={() => deleteConnection(integration.id)}
        >
          Delete
        </Button>
      </Flex>
    </Card>
  );
}
