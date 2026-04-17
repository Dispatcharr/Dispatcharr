import React, { useEffect, useState } from 'react';
import {
  Accordion,
  AccordionControl,
  AccordionItem,
  AccordionPanel,
  Alert,
  Box,
  Button,
  Checkbox,
  Flex,
  Group,
  Modal,
  Select,
  SimpleGrid,
  Stack,
  Tabs,
  TabsList,
  TabsPanel,
  TabsTab,
  Text,
  Textarea,
  TextInput,
} from '@mantine/core';
import { isNotEmpty, useForm } from '@mantine/form';
import {
  buildConfig,
  buildSubscriptions,
  createConnectIntegration,
  EVENT_OPTIONS,
  parseApiError,
  setConnectSubscriptions,
  updateConnectIntegration,
} from '../../utils/forms/ConnectionUtils.js';

const PayloadTemplateItem = ({ opt, payloadTemplates, onTemplateChange }) => (
  <AccordionItem value={opt.value} key={opt.value}>
    <AccordionControl>{opt.label}</AccordionControl>
    <AccordionPanel>
      <Textarea
        label={opt.label}
        placeholder='{"key": "{{value}}"}'
        value={payloadTemplates[opt.value] ?? ''}
        onChange={onTemplateChange}
      />
    </AccordionPanel>
  </AccordionItem>
);

const HeaderRow = ({ h, onKeyChange, onValueChange, onRemove }) => (
  <Group align="flex-start">
    <TextInput
      placeholder="Header name"
      value={h.key}
      onChange={onKeyChange}
      style={{ flex: 1 }}
    />
    <TextInput
      placeholder="Header value"
      value={h.value}
      onChange={onValueChange}
      style={{ flex: 1 }}
    />
    <Button size="xs" color="red" onClick={onRemove}>
      Remove
    </Button>
  </Group>
);

const ConnectionForm = ({ connection = null, isOpen, onClose }) => {
  const [submitting, setSubmitting] = useState(false);
  const [selectedEvents, setSelectedEvents] = useState([]);
  const [headers, setHeaders] = useState([]);
  const [payloadTemplates, setPayloadTemplates] = useState({});
  const [apiError, setApiError] = useState('');

  // One-time form
  const form = useForm({
    mode: 'controlled',
    initialValues: {
      name: connection?.name || '',
      type: connection?.type || 'webhook',
      url: connection?.config?.url || '',
      script_path: connection?.config?.path || '',
      enabled: connection?.enabled ?? true,
    },
    validate: {
      name: isNotEmpty('Provide a name'),
      type: isNotEmpty('Select a type'),
      url: (value, values) => {
        if (values.type === 'webhook' && !value.trim()) {
          return 'Provide a webhook URL';
        }
        return null;
      },
      script_path: (value, values) => {
        if (values.type === 'script' && !value.trim()) {
          return 'Provide a script path';
        }
        return null;
      },
    },
  });

  useEffect(() => {
    if (connection) {
      const values = {
        name: connection.name,
        type: connection.type,
        url: connection.config?.url,
        script_path: connection.config?.path,
        enabled: connection.enabled,
      };
      form.setValues(values);
      setSelectedEvents(
        connection.subscriptions.reduce((acc, sub) => {
          if (sub.enabled) acc.push(sub.event);
          return acc;
        }, [])
      );
      // Initialize headers array from config.headers object
      const cfgHeaders = connection.config?.headers || {};
      const hdrs = Object.keys(cfgHeaders).length
        ? Object.entries(cfgHeaders).map(([k, v]) => ({ key: k, value: v }))
        : [{ key: '', value: '' }];
      setHeaders(hdrs);

      // Initialize payload templates per subscription
      const templates = {};
      connection.subscriptions.forEach((sub) => {
        if (sub.payload_template) templates[sub.event] = sub.payload_template;
      });
      setPayloadTemplates(templates);
    } else {
      form.reset();
      setSelectedEvents([]);
      setHeaders([{ key: '', value: '' }]);
      setPayloadTemplates({});
    }
  }, [connection]);

  const handleClose = () => {
    setApiError('');
    onClose?.();
  };

  const onSubmit = async (values) => {
    setSubmitting(true);
    setApiError('');
    try {
      const config = buildConfig(values, headers);
      const subs = buildSubscriptions(selectedEvents, payloadTemplates);

      if (connection) {
        await updateConnectIntegration(connection, values, config);
      } else {
        connection = await createConnectIntegration(values, config);
      }

      await setConnectSubscriptions(connection, subs);
      handleClose();
    } catch (error) {
      console.error('Failed to create/update connection', error);

      const { fieldErrors, apiError } = parseApiError(error);
      if (Object.keys(fieldErrors).length > 0) form.setErrors(fieldErrors);
      setApiError(apiError);
    } finally {
      setSubmitting(false);
    }
  };

  const toggleEvent = (event) => {
    setSelectedEvents((prev) =>
      prev.includes(event) ? prev.filter((e) => e !== event) : [...prev, event]
    );
  };

  if (!isOpen) return null;

  const onHeaderKeyChange = (idx, newValue) => {
    const next = [...headers];
    next[idx] = { ...next[idx], key: newValue };
    setHeaders(next);
  };

  const onHeaderValueChange = (idx, newValue) => {
    const next = [...headers];
    next[idx] = {
      ...next[idx],
      value: newValue,
    };
    setHeaders(next);
  };

  const onHeaderRemove = (idx) => {
    const next = headers.filter((_, i) => i !== idx);
    setHeaders(next.length ? next : [{ key: '', value: '' }]);
  };

  return (
    <Modal opened={isOpen} size="lg" onClose={handleClose} title="Connection">
      <form onSubmit={form.onSubmit(onSubmit)}>
        <Tabs defaultValue="settings">
          <TabsList>
            <TabsTab value="settings">Settings</TabsTab>
            <TabsTab value="triggers">Event Triggers</TabsTab>
            {form.getValues().type === 'webhook' && (
              <TabsTab value="templates">Payload Templates</TabsTab>
            )}
          </TabsList>

          <TabsPanel value="settings" style={{ paddingTop: 10 }}>
            <Stack gap="md">
              {apiError ? (
                <Text c="red" size="sm">
                  {apiError}
                </Text>
              ) : null}
              <TextInput
                label="Name"
                {...form.getInputProps('name')}
                key={form.key('name')}
              />
              <Select
                {...form.getInputProps('type')}
                key={form.key('type')}
                label="Connection Type"
                data={[
                  { value: 'webhook', label: 'Webhook' },
                  { value: 'script', label: 'Custom Script' },
                ]}
              />
              {form.getValues().type === 'webhook' ? (
                <TextInput
                  label="Webhook URL"
                  {...form.getInputProps('url')}
                  key={form.key('url')}
                />
              ) : (
                <TextInput
                  label="Script Path"
                  {...form.getInputProps('script_path')}
                  key={form.key('script_path')}
                />
              )}

              {form.getValues().type === 'webhook' ? (
                <Box>
                  <Text size="sm" weight={500} mb={5}>
                    Custom Headers (optional)
                  </Text>
                  <Stack spacing="xs">
                    {headers.map((h, idx) => (
                      <HeaderRow
                        key={idx}
                        h={h}
                        onKeyChange={(e) =>
                          onHeaderKeyChange(idx, e.target.value)
                        }
                        onValueChange={(e) =>
                          onHeaderValueChange(idx, e.target.value)
                        }
                        onRemove={() => onHeaderRemove(idx)}
                      />
                    ))}
                    <Button
                      size="xs"
                      onClick={() =>
                        setHeaders([...headers, { key: '', value: '' }])
                      }
                    >
                      Add Header
                    </Button>
                  </Stack>
                </Box>
              ) : null}
            </Stack>
          </TabsPanel>

          <TabsPanel value="triggers" style={{ paddingTop: 10 }}>
            <SimpleGrid cols={3}>
              {EVENT_OPTIONS.map((opt) => (
                <Checkbox
                  key={opt.value}
                  label={opt.label}
                  checked={selectedEvents.includes(opt.value)}
                  onChange={() => toggleEvent(opt.value)}
                />
              ))}
            </SimpleGrid>
          </TabsPanel>

          {form.getValues().type === 'webhook' && (
            <TabsPanel value="templates" style={{ paddingTop: 10 }}>
              <Stack gap="xs">
                <Alert variant="default">
                  <Text size="sm">
                    Enable event triggers to set individual templates.
                  </Text>
                </Alert>
                <div
                  style={{
                    maxHeight: '60vh',
                    display: 'flex',
                    flexDirection: 'column',
                  }}
                >
                  <div style={{ overflow: 'auto', flex: 1, minHeight: 0 }}>
                    <Accordion
                      multiple={true}
                      styles={{
                        label: { padding: 2 },
                      }}
                    >
                      {EVENT_OPTIONS.filter((opt) =>
                        selectedEvents.includes(opt.value)
                      ).map((opt) => (
                        <PayloadTemplateItem
                          key={opt.value}
                          opt={opt}
                          payloadTemplates={payloadTemplates}
                          onTemplateChange={(e) =>
                            setPayloadTemplates({
                              ...payloadTemplates,
                              [opt.value]: e.target.value,
                            })
                          }
                        />
                      ))}
                    </Accordion>
                  </div>
                </div>
              </Stack>
            </TabsPanel>
          )}
        </Tabs>
        <Flex mih={50} gap="xs" justify="flex-end" align="flex-end">
          <Button type="submit" loading={submitting}>
            Save
          </Button>
        </Flex>
      </form>
    </Modal>
  );
};

export default ConnectionForm;
