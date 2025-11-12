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
} from '@mantine/core';
import { AlertCircle } from 'lucide-react';
import API from '../api';

const PluginPage = () => {
  const { pluginKey } = useParams();
  const [plugin, setPlugin] = useState(null);
  const [loading, setLoading] = useState(true);
  const [pluginSettings, setPluginSettings] = useState({});

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
      </Stack>
    </Box>
  );
};

export default PluginPage;

