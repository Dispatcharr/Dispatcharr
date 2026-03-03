import React, { useEffect, useState } from 'react';
import API from '../../api';
import {
  Button,
  Modal,
  Select,
  Stack,
  Flex,
  TextInput,
  Box,
  Checkbox,
  Text,
  SimpleGrid,
  Textarea,
  Group,
  Tabs,
  Accordion,
  Alert,
} from '@mantine/core';
import { isNotEmpty, useForm } from '@mantine/form';
import { SUBSCRIPTION_EVENTS } from '../../constants';

const EVENT_OPTIONS = Object.entries(SUBSCRIPTION_EVENTS).map(
  ([value, label]) => ({
    value,
    label,
  })
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
    console.log(values);
    try {
      setSubmitting(true);
      setApiError('');
      // Build config including optional headers
      let config;
      if (values.type === 'webhook') {
        const hdrs = {};
        headers.forEach((h) => {
          if (h.key && h.key.trim()) hdrs[h.key] = h.value;
        });
        config = { url: values.url };
        if (Object.keys(hdrs).length) config.headers = hdrs;
      } else {
        config = { path: values.script_path };
      }

      if (connection) {
        await API.updateConnectIntegration(connection.id, {
          name: values.name,
          type: values.type,
          config,
          enabled: values.enabled,
        });
      } else {
        connection = await API.createConnectIntegration({
          name: values.name,
          type: values.type,
          config,
          enabled: values.enabled,
        });
      }

      // Build subscription list including optional payload templates
      const subs = Object.keys(SUBSCRIPTION_EVENTS).map((event) => ({
        event,
        enabled: selectedEvents.includes(event),
        payload_template: payloadTemplates[event] || null,
      }));

      await API.setConnectSubscriptions(connection.id, subs);
      handleClose();
    } catch (error) {
      console.error('Failed to create/update connection', error);
      // Try to map server-side validation errors to form fields
      const body = error?.body;

      if (body && typeof body === 'object') {
        const fieldErrors = {};
        if (body.name) {
          fieldErrors.name = body.name;
        }
        if (body.type) {
          fieldErrors.type = body.type;
        }
        if (body.config) {
          if (values.type === 'webhook') {
            fieldErrors.url = msg;
          } else {
            fieldErrors.script_path = msg;
          }
        }

        const nonField = body.non_field_errors || body.detail;
        if (Object.keys(fieldErrors).length > 0) {
          form.setErrors(fieldErrors);
        }
        if (nonField) setApiError(nonField);
        if (!nonField && Object.keys(fieldErrors).length === 0) {
          setApiError(body);
        }
      } else {
        setApiError(error?.message || 'Unknown error');
      }
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

  return (
    <Modal opened={isOpen} size="lg" onClose={handleClose} title="Connection">
      <form onSubmit={form.onSubmit(onSubmit)}>
        <Tabs defaultValue="settings">
          <Tabs.List>
            <Tabs.Tab value="settings">Settings</Tabs.Tab>
            <Tabs.Tab value="triggers">Event Triggers</Tabs.Tab>
            {form.getValues().type === 'webhook' && (
              <Tabs.Tab value="templates">Payload Templates</Tabs.Tab>
            )}
          </Tabs.List>

          <Tabs.Panel value="settings" style={{ paddingTop: 10 }}>
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
                      <Group key={idx} align="flex-start">
                        <TextInput
                          placeholder="Header name"
                          value={h.key}
                          onChange={(e) => {
                            const next = [...headers];
                            next[idx] = { ...next[idx], key: e.target.value };
                            setHeaders(next);
                          }}
                          style={{ flex: 1 }}
                        />
                        <TextInput
                          placeholder="Header value"
                          value={h.value}
                          onChange={(e) => {
                            const next = [...headers];
                            next[idx] = {
                              ...next[idx],
                              value: e.target.value,
                            };
                            setHeaders(next);
                          }}
                          style={{ flex: 1 }}
                        />
                        <Button
                          size="xs"
                          color="red"
                          onClick={() => {
                            const next = headers.filter((_, i) => i !== idx);
                            setHeaders(
                              next.length ? next : [{ key: '', value: '' }]
                            );
                          }}
                        >
                          Remove
                        </Button>
                      </Group>
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
          </Tabs.Panel>

          <Tabs.Panel value="triggers" style={{ paddingTop: 10 }}>
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
          </Tabs.Panel>

          {form.getValues().type === 'webhook' && (
            <Tabs.Panel value="templates" style={{ paddingTop: 10 }}>
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
                      {EVENT_OPTIONS.map(
                        (opt) =>
                          selectedEvents.includes(opt.value) && (
                            <Accordion.Item key={opt.value} value={opt.value}>
                              <Accordion.Control
                                disabled={!selectedEvents.includes(opt.value)}
                                style={{ paddingTop: 4, paddingBottom: 4 }}
                              >
                                {opt.label}
                              </Accordion.Control>
                              <Accordion.Panel>
                                <Textarea
                                  placeholder={
                                    'Optional Jinja2 template (ex: {"content": "Channel {{ channel_name }} just started streaming!"} )'
                                  }
                                  minRows={3}
                                  value={payloadTemplates[opt.value] || ''}
                                  autosize
                                  onChange={(e) =>
                                    setPayloadTemplates({
                                      ...payloadTemplates,
                                      [opt.value]: e.target.value,
                                    })
                                  }
                                />
                              </Accordion.Panel>
                            </Accordion.Item>
                          )
                      )}
                    </Accordion>
                  </div>
                </div>
              </Stack>
            </Tabs.Panel>
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
