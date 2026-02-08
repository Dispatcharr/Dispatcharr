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
  Title,
  Checkbox,
  Text,
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
    } else {
      form.reset();
    }
  }, [connection]);

  const handleClose = () => {
    onClose?.();
  };

  const onSubmit = async (values) => {
    console.log(values);
    try {
      setSubmitting(true);
      const config =
        values.type === 'webhook'
          ? { url: values.url }
          : { path: values.script_path };

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

      await API.setConnectSubscriptions(
        connection.id,
        Object.keys(SUBSCRIPTION_EVENTS).map((event) => ({
          event,
          enabled: selectedEvents.includes(event),
        }))
      );
      handleClose();
    } catch (error) {
      console.error('Failed to create connection', error);
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
    <Modal opened={isOpen} onClose={handleClose} title="Connection">
      <Stack>
        <form onSubmit={form.onSubmit(onSubmit)}>
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

          <Box>
            <Text size="sm" weight={500} mb={5}>
              Triggers
            </Text>
            <Stack gap="xs">
              {EVENT_OPTIONS.map((opt) => (
                <Checkbox
                  key={opt.value}
                  label={opt.label}
                  checked={selectedEvents.includes(opt.value)}
                  onChange={() => toggleEvent(opt.value)}
                />
              ))}
            </Stack>
          </Box>

          <Flex mih={50} gap="xs" justify="flex-end" align="flex-end">
            <Button type="submit" loading={submitting}>
              Save
            </Button>
          </Flex>
        </form>
      </Stack>
    </Modal>
  );
};

export default ConnectionForm;
