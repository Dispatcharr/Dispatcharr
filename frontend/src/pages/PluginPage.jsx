import React, { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import {
  Box,
  Title,
  Text,
  Stack,
  Accordion,
  Switch,
  NumberInput,
  Select,
  TextInput,
  Loader,
  Alert,
  Button,
  Group,
  Divider,
  Modal,
} from '@mantine/core';
import { AlertCircle } from 'lucide-react';
import { notifications } from '@mantine/notifications';
import API from '../api';

const PluginPage = () => {
  const { pluginKey } = useParams();
  const [plugin, setPlugin] = useState(null);
  const [loading, setLoading] = useState(true);
  const [pluginSettings, setPluginSettings] = useState({});

  // State for plugin actions
  const [running, setRunning] = useState(false);
  const [lastResult, setLastResult] = useState(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [confirmConfig, setConfirmConfig] = useState({
    title: '',
    message: '',
    onConfirm: null,
  });

  useEffect(() => {
    const loadPlugin = async () => {
      try {
        setLoading(true);
        const response = await API.getPlugins();
        const foundPlugin = response.find(p => p.key === pluginKey);
        
        if (foundPlugin) {
          setPlugin(foundPlugin);
          setPluginSettings(foundPlugin.settings || {});
        }
      } catch (error) {
        console.error('Failed to load plugin:', error);
      } finally {
        setLoading(false);
      }
    };

    loadPlugin();
  }, [pluginKey]);

  const onPluginSettingChange = async (fieldId, value) => {
    setPluginSettings(prev => ({
      ...prev,
      [fieldId]: value
    }));

    try {
      const updatedSettings = {
        ...pluginSettings,
        [fieldId]: value
      };
      await API.updatePluginSettings(pluginKey, updatedSettings);
    } catch (error) {
      console.error('Failed to save plugin setting:', error);
    }
  };

  const onRunAction = async (actionId) => {
    setRunning(true);
    setLastResult(null);
    try {
      const resp = await API.runPluginAction(pluginKey, actionId);
      if (resp?.success) {
        setLastResult(resp.result || {});
        const msg = resp.result?.message || 'Plugin action completed';
        notifications.show({
          title: plugin.name,
          message: msg,
          color: 'green',
        });
      } else {
        const err = resp?.error || 'Unknown error';
        setLastResult({ error: err });
        notifications.show({
          title: `${plugin.name} error`,
          message: String(err),
          color: 'red',
        });
      }
    } finally {
      setRunning(false);
    }
  };

  const renderPluginField = (field) => {
    const value = pluginSettings[field.id] ?? field.default;
    const onChange = (val) => onPluginSettingChange(field.id, val);

    switch (field.type) {
      case 'boolean':
        return (
          <Switch
            key={field.id}
            label={field.label}
            description={field.help_text}
            checked={!!value}
            onChange={(e) => onChange(e.currentTarget.checked)}
          />
        );
      case 'number':
        return (
          <NumberInput
            key={field.id}
            label={field.label}
            description={field.help_text}
            value={value ?? 0}
            onChange={onChange}
          />
        );
      case 'select':
        return (
          <Select
            key={field.id}
            label={field.label}
            description={field.help_text}
            value={value ? String(value) : ''}
            data={(field.options || []).map(o => ({
              value: String(o.value),
              label: o.label
            }))}
            onChange={onChange}
          />
        );
      case 'string':
      default:
        return (
          <TextInput
            key={field.id}
            label={field.label}
            description={field.help_text}
            value={value ?? ''}
            onChange={(e) => onChange(e.currentTarget.value)}
          />
        );
    }
  };

  if (loading) {
    return (
      <Box p="xl" style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: '400px' }}>
        <Loader size="lg" />
      </Box>
    );
  }

  if (!plugin) {
    return (
      <Box p="xl">
        <Alert icon={<AlertCircle size={16} />} title="Plugin Not Found" color="red">
          The plugin "{pluginKey}" could not be found or is not enabled.
        </Alert>
      </Box>
    );
  }

  if (!plugin.enabled) {
    return (
      <Box p="xl">
        <Alert icon={<AlertCircle size={16} />} title="Plugin Disabled" color="yellow">
          The plugin "{plugin.name}" is currently disabled. Enable it from the Plugins page to configure its settings.
        </Alert>
      </Box>
    );
  }

  // Group fields by section
  const unsectionedFields = plugin.fields?.filter(f => !f.section) || [];
  const sectionedFields = plugin.fields?.filter(f => f.section) || [];
  const sections = [...new Set(sectionedFields.map(f => f.section))];

  return (
    <Box p="xl">
      <Stack gap="lg">
        {/* Plugin Header */}
        <div>
          <Title order={2}>{plugin.name}</Title>
          <Text size="sm" c="dimmed" mt="xs">
            {plugin.description}
          </Text>
        </div>

        {/* Plugin Settings */}
        {plugin.fields && plugin.fields.length > 0 ? (
          <Accordion variant="separated" defaultValue={sections[0] || 'main'}>
            {/* Unsectioned fields in a default section */}
            {unsectionedFields.length > 0 && (
              <Accordion.Item value="main">
                <Accordion.Control>General Settings</Accordion.Control>
                <Accordion.Panel>
                  <Stack gap="sm">
                    {unsectionedFields.map(field => renderPluginField(field))}
                  </Stack>
                </Accordion.Panel>
              </Accordion.Item>
            )}

            {/* Sectioned fields */}
            {sections.map(section => (
              <Accordion.Item key={section} value={section}>
                <Accordion.Control>{section}</Accordion.Control>
                <Accordion.Panel>
                  <Stack gap="sm">
                    {sectionedFields
                      .filter(f => f.section === section)
                      .map(field => renderPluginField(field))}
                  </Stack>
                </Accordion.Panel>
              </Accordion.Item>
            ))}
          </Accordion>
        ) : (
          <Text c="dimmed">This plugin has no configurable settings.</Text>
        )}

        {/* Plugin Actions */}
        {plugin.actions && plugin.actions.length > 0 && (
          <Box>
            <Divider my="md" />
            <Title order={4} mb="sm">Actions</Title>
            <Stack gap="xs">
              {plugin.actions.map((action) => (
                <Group key={action.id} justify="space-between">
                  <div>
                    <Text>{action.label}</Text>
                    {action.description && (
                      <Text size="sm" c="dimmed">
                        {action.description}
                      </Text>
                    )}
                  </div>
                  <Button
                    loading={running}
                    onClick={async () => {
                      // Determine if confirmation is required
                      const actionConfirm = action.confirm;
                      let requireConfirm = false;
                      let confirmTitle = `Run ${action.label}?`;
                      let confirmMessage = `You're about to run "${action.label}" from "${plugin.name}".`;

                      if (actionConfirm) {
                        if (typeof actionConfirm === 'boolean') {
                          requireConfirm = actionConfirm;
                        } else if (typeof actionConfirm === 'object') {
                          requireConfirm = actionConfirm.required !== false;
                          if (actionConfirm.title) confirmTitle = actionConfirm.title;
                          if (actionConfirm.message) confirmMessage = actionConfirm.message;
                        }
                      }

                      if (requireConfirm) {
                        await new Promise((resolve) => {
                          setConfirmConfig({
                            title: confirmTitle,
                            message: confirmMessage,
                            onConfirm: resolve,
                          });
                          setConfirmOpen(true);
                        });
                      }

                      await onRunAction(action.id);
                    }}
                    size="xs"
                  >
                    {running ? 'Running…' : 'Run'}
                  </Button>
                </Group>
              ))}
              {running && (
                <Text size="sm" c="dimmed">
                  Running action… please wait
                </Text>
              )}
              {!running && lastResult?.file && (
                <Text size="sm" c="dimmed">
                  Output: {lastResult.file}
                </Text>
              )}
              {!running && lastResult?.error && (
                <Text size="sm" c="red">
                  Error: {String(lastResult.error)}
                </Text>
              )}
            </Stack>
          </Box>
        )}
      </Stack>

      {/* Action Confirmation Modal */}
      <Modal
        opened={confirmOpen}
        onClose={() => {
          setConfirmOpen(false);
          setConfirmConfig({ title: '', message: '', onConfirm: null });
        }}
        title={confirmConfig.title}
        centered
      >
        <Stack>
          <Text size="sm">{confirmConfig.message}</Text>
          <Group justify="flex-end">
            <Button
              variant="default"
              size="xs"
              onClick={() => {
                setConfirmOpen(false);
                setConfirmConfig({ title: '', message: '', onConfirm: null });
              }}
            >
              Cancel
            </Button>
            <Button
              size="xs"
              onClick={() => {
                const cb = confirmConfig.onConfirm;
                setConfirmOpen(false);
                setConfirmConfig({ title: '', message: '', onConfirm: null });
                if (cb) cb();
              }}
            >
              Confirm
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Box>
  );
};

export default PluginPage;

