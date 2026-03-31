// Modal.js
import React, { useState, useEffect } from 'react';
import API from '../../api';
import {
  TextInput,
  Button,
  Checkbox,
  Modal,
  NativeSelect,
  NumberInput,
  Stack,
  Group,
  Divider,
  Box,
  Text,
  Badge,
  Loader,
  Table,
  ActionIcon,
} from '@mantine/core';
import { isNotEmpty, useForm } from '@mantine/form';
import { notifications } from '@mantine/notifications';
import ScheduleInput from './ScheduleInput';

const EPG = ({ epg = null, isOpen, onClose }) => {
  const [sourceType, setSourceType] = useState('xmltv');
  const [scheduleType, setScheduleType] = useState('interval');
  const [lineups, setLineups] = useState([]);
  const [searchResults, setSearchResults] = useState([]);
  const [postalCode, setPostalCode] = useState('');
  const [country, setCountry] = useState('USA');
  const [lineupsLoading, setLineupsLoading] = useState(false);
  const [searchLoading, setSearchLoading] = useState(false);

  const form = useForm({
    mode: 'uncontrolled',
    initialValues: {
      name: '',
      source_type: 'xmltv',
      url: '',
      api_key: '',
      username: '',
      is_active: true,
      refresh_interval: 24,
      cron_expression: '',
      priority: 0,
    },

    validate: {
      name: isNotEmpty('Please select a name'),
      source_type: isNotEmpty('Source type cannot be empty'),
    },
  });

  const onSubmit = async () => {
    const values = form.getValues();

    // Determine which schedule type is active based on field values
    const hasCronExpression =
      values.cron_expression && values.cron_expression.trim() !== '';

    // Clear the field that isn't active based on actual field values
    if (hasCronExpression) {
      values.refresh_interval = 0;
    } else {
      values.cron_expression = '';
    }

    if (epg?.id) {
      // Validate that we have a valid EPG object before updating
      if (!epg || typeof epg !== 'object' || !epg.id) {
        notifications.show({
          title: 'Error',
          message: 'Invalid EPG data. Please close and reopen this form.',
          color: 'red',
        });
        return;
      }

      await API.updateEPG({ id: epg.id, ...values });
      form.reset();
      onClose();
    } else {
      const response = await API.addEPG(values);

      // For SD sources, reopen in edit mode so user can manage lineups
      if (values.source_type === 'schedules_direct' && response?.id) {
        form.reset();
        onClose(response);  // Pass created source to parent for re-open
        return;
      }

      form.reset();
      onClose();
    }
  };

  useEffect(() => {
    if (epg) {
      const values = {
        name: epg.name,
        source_type: epg.source_type,
        url: epg.url,
        api_key: epg.api_key,
        username: epg.username || '',
        is_active: epg.is_active,
        refresh_interval: epg.refresh_interval,
        cron_expression: epg.cron_expression || '',
        priority: epg.priority ?? 0,
      };
      form.setValues(values);
      setSourceType(epg.source_type);
      // Determine schedule type from existing data - check both fields
      setScheduleType(
        epg.cron_expression && epg.cron_expression.trim() !== ''
          ? 'cron'
          : 'interval'
      );

      // Load SD lineups for existing SD sources
      if (epg.source_type === 'schedules_direct' && epg.id) {
        loadLineups();
      }
    } else {
      form.reset();
      setSourceType('xmltv');
      setScheduleType('interval');
      setLineups([]);
      setSearchResults([]);
      setPostalCode('');
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [epg]);

  // Function to handle source type changes
  const handleSourceTypeChange = (value) => {
    form.setFieldValue('source_type', value);
    setSourceType(value);
  };

  const loadLineups = async () => {
    if (!epg?.id) return;
    setLineupsLoading(true);
    try {
      const result = await API.getSDLineups(epg.id);
      setLineups(Array.isArray(result) ? result : []);
    } finally {
      setLineupsLoading(false);
    }
  };

  const searchLineups = async () => {
    if (!epg?.id || !postalCode) return;
    setSearchLoading(true);
    try {
      const result = await API.searchSDLineups(epg.id, country, postalCode);
      setSearchResults(Array.isArray(result) ? result : []);
    } finally {
      setSearchLoading(false);
    }
  };

  const addLineup = async (lineupId) => {
    if (!epg?.id) return;
    const result = await API.addSDLineup(epg.id, lineupId);
    if (result) {
      notifications.show({ title: 'Lineup added', color: 'green' });
      await loadLineups();
    }
  };

  const removeLineup = async (lineupId) => {
    if (!epg?.id) return;
    const result = await API.removeSDLineup(epg.id, lineupId);
    if (result) {
      notifications.show({ title: 'Lineup removed', color: 'yellow' });
      await loadLineups();
    }
  };

  if (!isOpen) {
    return <></>;
  }

  return (
    <>
      <Modal opened={isOpen} onClose={onClose} title="EPG Source" size={700} scrollAreaComponent={Modal.NativeScrollArea}>
        <form onSubmit={form.onSubmit(onSubmit)}>
          <Group justify="space-between" align="top">
            {/* Left Column */}
            <Stack gap="md" style={{ flex: 1 }}>
              <TextInput
                id="name"
                name="name"
                label="Name"
                description="Unique identifier for this EPG source"
                {...form.getInputProps('name')}
                key={form.key('name')}
              />

              <NativeSelect
                id="source_type"
                name="source_type"
                label="Source Type"
                description="Format of the EPG data source"
                {...form.getInputProps('source_type')}
                key={form.key('source_type')}
                data={[
                  {
                    label: 'XMLTV',
                    value: 'xmltv',
                  },
                  {
                    label: 'Schedules Direct',
                    value: 'schedules_direct',
                  },
                ]}
                onChange={(event) =>
                  handleSourceTypeChange(event.currentTarget.value)
                }
              />

              <ScheduleInput
                scheduleType={scheduleType}
                onScheduleTypeChange={setScheduleType}
                intervalValue={form.getValues().refresh_interval}
                onIntervalChange={(v) =>
                  form.setFieldValue('refresh_interval', v)
                }
                cronValue={form.getValues().cron_expression}
                onCronChange={(expr) =>
                  form.setFieldValue('cron_expression', expr)
                }
                intervalLabel="Refresh Interval (hours)"
                intervalDescription="How often to refresh EPG data (0 to disable)"
              />
            </Stack>

            <Divider size="sm" orientation="vertical" />

            {/* Right Column */}
            <Stack gap="md" style={{ flex: 1 }}>
              {sourceType !== 'schedules_direct' && (
                <TextInput
                  id="url"
                  name="url"
                  label="URL"
                  description="Direct URL to the XMLTV file or API endpoint"
                  {...form.getInputProps('url')}
                  key={form.key('url')}
                />
              )}

              {sourceType === 'schedules_direct' && (
                <>
                  <TextInput
                    id="username"
                    name="username"
                    label="Username"
                    description="Schedules Direct account username"
                    {...form.getInputProps('username')}
                    key={form.key('username')}
                  />
                  <TextInput
                    id="api_key"
                    name="api_key"
                    label="Password"
                    type="password"
                    description="Schedules Direct account password"
                    {...form.getInputProps('api_key')}
                    key={form.key('api_key')}
                  />
                </>
              )}

              <NumberInput
                min={0}
                max={999}
                label="Priority"
                description="Priority for EPG matching (higher numbers = higher priority). Used when multiple EPG sources have matching entries for a channel."
                {...form.getInputProps('priority')}
                key={form.key('priority')}
              />

              {/* Put checkbox at the same level as Refresh Interval */}
              <Box style={{ marginTop: 0 }}>
                <Text size="sm" fw={500} mb={3}>
                  Status
                </Text>
                <Text size="xs" c="dimmed" mb={12}>
                  When enabled, this EPG source will auto update.
                </Text>
                <Box
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    height: '30px',
                    marginTop: '-4px',
                  }}
                >
                  <Checkbox
                    id="is_active"
                    name="is_active"
                    label="Enable this EPG source"
                    {...form.getInputProps('is_active', { type: 'checkbox' })}
                    key={form.key('is_active')}
                  />
                </Box>
              </Box>
            </Stack>
          </Group>

          {/* Full Width Section */}
          <Box mt="md">
            <Divider my="sm" />

            {sourceType === 'schedules_direct' && epg?.id && (
              <Box mb="md">
                <Text size="sm" fw={600} mb="xs">
                  Manage Lineups
                </Text>

                {/* Current lineups */}
                {lineupsLoading ? (
                  <Loader size="sm" />
                ) : lineups.length > 0 ? (
                  <Box mb="sm">
                    <Text size="xs" c="dimmed" mb={4}>
                      Active lineups on your SD account:
                    </Text>
                    <Table striped highlightOnHover withTableBorder>
                      <Table.Thead>
                        <Table.Tr>
                          <Table.Th>Lineup</Table.Th>
                          <Table.Th style={{ width: 80 }}></Table.Th>
                        </Table.Tr>
                      </Table.Thead>
                      <Table.Tbody>
                        {lineups.map((l) => (
                          <Table.Tr key={l.lineup}>
                            <Table.Td>
                              <Text size="sm">{l.lineup}</Text>
                            </Table.Td>
                            <Table.Td>
                              <Button
                                size="xs"
                                variant="subtle"
                                color="red"
                                onClick={() => removeLineup(l.lineup)}
                              >
                                Remove
                              </Button>
                            </Table.Td>
                          </Table.Tr>
                        ))}
                      </Table.Tbody>
                    </Table>
                  </Box>
                ) : (
                  <Text size="xs" c="red" mb="sm">
                    No lineups configured. Search and add one below to receive
                    EPG data.
                  </Text>
                )}

                {/* Search for lineups */}
                <Group align="end" gap="xs">
                  <NativeSelect
                    label="Country"
                    value={country}
                    onChange={(e) => setCountry(e.currentTarget.value)}
                    data={[
                      { label: 'United States', value: 'USA' },
                      { label: 'Canada', value: 'CAN' },
                      { label: 'United Kingdom', value: 'GBR' },
                      { label: 'Germany', value: 'DEU' },
                      { label: 'France', value: 'FRA' },
                      { label: 'Italy', value: 'ITA' },
                      { label: 'Spain', value: 'ESP' },
                      { label: 'Switzerland', value: 'CHE' },
                      { label: 'Austria', value: 'AUT' },
                      { label: 'Belgium', value: 'BEL' },
                      { label: 'Netherlands', value: 'NLD' },
                      { label: 'Mexico', value: 'MEX' },
                      { label: 'Australia', value: 'AUS' },
                      { label: 'New Zealand', value: 'NZL' },
                    ]}
                    style={{ width: 160 }}
                    size="xs"
                  />
                  <TextInput
                    label="Postal Code"
                    value={postalCode}
                    onChange={(e) => setPostalCode(e.currentTarget.value)}
                    placeholder="e.g. 33442"
                    style={{ width: 120 }}
                    size="xs"
                  />
                  <Button
                    size="xs"
                    variant="light"
                    onClick={searchLineups}
                    loading={searchLoading}
                    disabled={!postalCode}
                  >
                    Search
                  </Button>
                </Group>

                {/* Search results */}
                {searchResults.length > 0 && (
                  <Box mt="xs">
                    <Text size="xs" c="dimmed" mb={4}>
                      Available lineups:
                    </Text>
                    <Box
                      style={{
                        maxHeight: 200,
                        overflowY: 'auto',
                        border: '1px solid var(--mantine-color-dark-4)',
                        borderRadius: 'var(--mantine-radius-sm)',
                      }}
                    >
                      <Table striped highlightOnHover>
                        <Table.Thead>
                          <Table.Tr>
                            <Table.Th>Name</Table.Th>
                            <Table.Th>Location</Table.Th>
                            <Table.Th>Type</Table.Th>
                            <Table.Th style={{ width: 70 }}></Table.Th>
                          </Table.Tr>
                        </Table.Thead>
                        <Table.Tbody>
                          {searchResults.map((r) => {
                            const alreadyAdded = lineups.some(
                              (l) => l.lineup === r.lineup
                            );
                            return (
                              <Table.Tr key={r.lineup}>
                                <Table.Td>
                                  <Text size="xs">{r.name}</Text>
                                </Table.Td>
                                <Table.Td>
                                  <Text size="xs">{r.location}</Text>
                                </Table.Td>
                                <Table.Td>
                                  <Text size="xs">{r.transport}</Text>
                                </Table.Td>
                                <Table.Td>
                                  {alreadyAdded ? (
                                    <Badge size="xs" color="green">
                                      Added
                                    </Badge>
                                  ) : (
                                    <Button
                                      size="compact-xs"
                                      variant="light"
                                      color="green"
                                      onClick={() => addLineup(r.lineup)}
                                    >
                                      Add
                                    </Button>
                                  )}
                                </Table.Td>
                              </Table.Tr>
                            );
                          })}
                        </Table.Tbody>
                      </Table>
                    </Box>
                  </Box>
                )}
              </Box>
            )}

            <Group justify="end" mt="xl">
              <Button variant="outline" onClick={onClose}>
                Cancel
              </Button>
              <Button type="submit" variant="filled" disabled={form.submitting}>
                {epg?.id ? 'Update' : 'Create'} EPG Source
              </Button>
            </Group>
          </Box>
        </form>
      </Modal>
    </>
  );
};

export default EPG;
