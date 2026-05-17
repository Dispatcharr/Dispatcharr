// Modal.js
import React, { useState, useEffect, useCallback } from 'react';
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
  Alert,
  Select,
  Loader,
  Badge,
  ScrollArea,
  Table,
} from '@mantine/core';
import { TriangleAlert, Trash2, Plus, Search } from 'lucide-react';
import { isNotEmpty, useForm } from '@mantine/form';
import ScheduleInput from './ScheduleInput';
import { addEPG, updateEPG } from '../../utils/forms/DummyEpgUtils.js';
import { showNotification } from '../../utils/notificationUtils.js';
import API from '../../api.js';

// Countries are fetched dynamically from the SD API on component mount.
// Fallback list used if the API call fails.
const SD_COUNTRIES_FALLBACK = [
  { value: 'USA', label: 'United States' },
  { value: 'CAN', label: 'Canada' },
  { value: 'GBR', label: 'United Kingdom' },
  { value: 'AUS', label: 'Australia' },
  { value: 'AUT', label: 'Austria' },
  { value: 'BEL', label: 'Belgium' },
  { value: 'DNK', label: 'Denmark' },
  { value: 'FIN', label: 'Finland' },
  { value: 'FRA', label: 'France' },
  { value: 'DEU', label: 'Germany' },
  { value: 'IRL', label: 'Ireland' },
  { value: 'ITA', label: 'Italy' },
  { value: 'NLD', label: 'Netherlands' },
  { value: 'NZL', label: 'New Zealand' },
];

const SDLineupManager = ({ sourceId }) => {
  const [countries, setCountries] = useState(SD_COUNTRIES_FALLBACK);
  const [activeLineups, setActiveLineups] = useState([]);
  const [lineupNotice, setLineupNotice] = useState(null);
  const [changesRemaining, setChangesRemaining] = useState(null);
  const [changesResetAt, setChangesResetAt] = useState(null);
  const [searchResults, setSearchResults] = useState([]);
  const [country, setCountry] = useState('USA');
  const [postalCode, setPostalCode] = useState('');
  const [loadingLineups, setLoadingLineups] = useState(false);
  const [searching, setSearching] = useState(false);
  const [addingLineup, setAddingLineup] = useState(null);
  const [removingLineup, setRemovingLineup] = useState(null);
  const maxLineups = 4;
  const SD_DOCS_URL = 'https://github.com/SchedulesDirect/JSON-Service/wiki/API-20141201#tasks-your-client-must-perform';

  const fetchActiveLineups = useCallback(async () => {
    setLoadingLineups(true);
    try {
      const data = await API.getSDLineups(sourceId);
      if (data) {
        setActiveLineups(data.lineups || []);
        setLineupNotice(data.notice || null);
        // Always update changesRemaining from server — includes null (unknown) and 0 (locked)
        if (data.changes_remaining !== undefined) {
          setChangesRemaining(data.changes_remaining);
        }
        if (data.changes_reset_at !== undefined) {
          setChangesResetAt(data.changes_reset_at);
        }
      }
    } finally {
      setLoadingLineups(false);
    }
  }, [sourceId]);

  useEffect(() => {
    if (sourceId && sourceType === 'schedules_direct') {
      fetchActiveLineups();
      // Fetch country list from SD API per their recommendation to not hardcode
      fetch('https://json.schedulesdirect.org/20141201/available/countries')
        .then(r => r.json())
        .then(data => {
          const all = Object.values(data).flat();
          const mapped = all
            .filter(c => c.shortName && c.fullName)
            .map(c => ({ value: c.shortName, label: c.fullName }))
            .sort((a, b) => a.label.localeCompare(b.label));
          if (mapped.length > 0) setCountries(mapped);
        })
        .catch(() => {}); // fallback list remains if fetch fails
    }
  }, [sourceId, fetchActiveLineups]);

  const handleSearch = async () => {
    if (!postalCode.trim()) return;
    setSearching(true);
    setSearchResults([]);
    try {
      const data = await API.searchSDLineups(sourceId, country, postalCode.trim());
      if (data) {
        setSearchResults(data.lineups || []);
      }
    } finally {
      setSearching(false);
    }
  };

  const handleAdd = async (lineup) => {
    setAddingLineup(lineup.lineup);
    try {
      const result = await API.addSDLineup(sourceId, lineup.lineup);
      if (!result) return;

      // Update changesRemaining from response
      if (result.changes_remaining !== undefined && result.changes_remaining !== null) {
        setChangesRemaining(result.changes_remaining);
      }

      if (result.error === 'daily_limit_reached') {
        setChangesRemaining(0);
        await fetchActiveLineups(); // reload to get reset_at from server
        return;
      }

      if (result.error === 'duplicate_lineup') {
        showNotification({ title: 'Already added', message: result.message, color: 'yellow' });
        return;
      }

      if (result.error === 'max_lineups_reached') {
        showNotification({ title: 'Maximum lineups reached', message: result.message, color: 'orange' });
        return;
      }

      if (result.error) {
        showNotification({ title: 'Unable to add lineup', message: result.message, color: 'red' });
        return;
      }

      if (result.code === 0) {
        showNotification({ title: 'Lineup added', message: lineup.name, color: 'green' });
        await fetchActiveLineups();
      }
    } finally {
      setAddingLineup(null);
    }
  };

  const handleRemove = async (lineup) => {
    setRemovingLineup(lineup.lineup);
    try {
      const result = await API.deleteSDLineup(sourceId, lineup.lineup);
      if (result && result.code === 0) {
        showNotification({ title: 'Lineup removed', message: lineup.name, color: 'blue' });
        if (result.changes_remaining !== undefined && result.changes_remaining !== null) {
          setChangesRemaining(result.changes_remaining);
        }
        await fetchActiveLineups();
        setSearchResults([]);
      }
    } finally {
      setRemovingLineup(null);
    }
  };

  const activeLineupIds = new Set(activeLineups.map((l) => l.lineup));
  const atMax = activeLineups.length >= maxLineups;

  return (
    <Box mt="md">
      <Divider my="sm" />
      <Group justify="space-between" mb="xs">
        <Text size="sm" fw={500}>
          Manage Lineups
        </Text>
        <Badge color={atMax ? 'red' : 'blue'} variant="light">
          {loadingLineups ? '...' : `${activeLineups.length} / ${maxLineups}`}
        </Badge>
      </Group>

      {/* Active lineups */}
      {loadingLineups ? (
        <Group justify="center" py="sm">
          <Loader size="sm" />
        </Group>
      ) : activeLineups.length === 0 ? (
        <Text size="xs" c="dimmed" mb="sm">
          {lineupNotice || 'No lineups configured. Search below to add one.'}
        </Text>
      ) : (
        <Box mb="sm">
          {activeLineups.map((lineup) => (
            <Group
              key={lineup.lineup}
              justify="space-between"
              px="sm"
              py="xs"
              mb={4}
              style={{
                background: 'var(--mantine-color-default)',
                border: '1px solid var(--mantine-color-default-border)',
                borderRadius: 'var(--mantine-radius-sm)',
              }}
            >
              <Box>
                <Text size="sm" fw={500}>{lineup.name}</Text>
                <Text size="xs" c="dimmed">
                  {lineup.transport} · {lineup.location} · {lineup.lineup}
                </Text>
              </Box>
              <Button
                size="xs"
                color="red"
                variant="subtle"
                leftSection={<Trash2 size={12} />}
                loading={removingLineup === lineup.lineup}
                onClick={() => handleRemove(lineup)}
              >
                Remove
              </Button>
            </Group>
          ))}
        </Box>
      )}

      {/* Search section */}
      <Text size="xs" fw={500} c="dimmed" mb="xs" tt="uppercase">
        Add a lineup
      </Text>

      {atMax && (
        <Alert color="orange" variant="light" mb="xs" icon={<TriangleAlert size={14} />}>
          Maximum of {maxLineups} lineups reached. Remove one to add another.
        </Alert>
      )}

      {changesRemaining === 0 && (
        <Alert color="red" variant="light" mb="xs" icon={<TriangleAlert size={14} />}>
          You have reached your daily Schedules Direct lineup addition limit. SD allows 6 adds per 24-hour period.{' '}
          {changesResetAt && (
            <span>Limit resets at <strong>{new Date(changesResetAt).toUTCString()}</strong>. </span>
          )}
          {!changesResetAt && <span>Limit resets 24 hours after the first add of the day. </span>}
          <a href={SD_DOCS_URL} target="_blank" rel="noopener noreferrer">Learn more</a>
        </Alert>
      )}

      {changesRemaining === 1 && (
        <Alert color="orange" variant="light" mb="xs" icon={<TriangleAlert size={14} />}>
          You have <strong>1 lineup addition remaining</strong> today. Use it carefully — Schedules Direct limits adds to 6 per 24-hour period.{' '}
          <a href={SD_DOCS_URL} target="_blank" rel="noopener noreferrer">Learn more</a>
        </Alert>
      )}

      {changesRemaining === 2 && (
        <Alert color="yellow" variant="light" mb="xs" icon={<TriangleAlert size={14} />}>
          You have <strong>2 lineup additions remaining</strong> today. Schedules Direct limits adds to 6 per 24-hour period.{' '}
          <a href={SD_DOCS_URL} target="_blank" rel="noopener noreferrer">Learn more</a>
        </Alert>
      )}

      <Group align="flex-end" mb="sm" gap="xs">
        <Select
          label="Country"
          data={countries}
          value={country}
          onChange={(v) => setCountry(v)}
          style={{ flex: 1 }}
          size="sm"
        />
        <TextInput
          label="Postal code"
          placeholder="e.g. 07030"
          value={postalCode}
          onChange={(e) => setPostalCode(e.currentTarget.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
          style={{ flex: 1 }}
          size="sm"
        />
        <Button
          size="sm"
          leftSection={<Search size={14} />}
          loading={searching}
          onClick={handleSearch}
          disabled={!postalCode.trim() || changesRemaining === 0}
        >
          Search
        </Button>
      </Group>

      {searchResults.length > 0 && (
        <ScrollArea h={180} style={{ border: '1px solid var(--mantine-color-default-border)', borderRadius: 'var(--mantine-radius-sm)' }}>
          <Table striped highlightOnHover withRowBorders={false} fz="xs">
            <Table.Tbody>
              {searchResults.map((lineup) => {
                const isActive = activeLineupIds.has(lineup.lineup);
                return (
                  <Table.Tr key={lineup.lineup}>
                    <Table.Td>
                      <Text size="xs" fw={500}>{lineup.name}</Text>
                      <Text size="xs" c="dimmed">{lineup.transport} · {lineup.location}</Text>
                    </Table.Td>
                    <Table.Td style={{ textAlign: 'right', whiteSpace: 'nowrap' }}>
                      {isActive ? (
                        <Badge color="green" variant="light" size="sm">Active</Badge>
                      ) : (
                        <Button
                          size="xs"
                          variant="subtle"
                          leftSection={<Plus size={12} />}
                          loading={addingLineup === lineup.lineup}
                          disabled={atMax || changesRemaining === 0}
                          onClick={() => handleAdd(lineup)}
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
        </ScrollArea>
      )}
    </Box>
  );
};

const EPG = ({ epg = null, isOpen, onClose }) => {
  const [sourceType, setSourceType] = useState('xmltv');
  const [scheduleType, setScheduleType] = useState('interval');
  const [savedEpgId, setSavedEpgId] = useState(null);

  const form = useForm({
    mode: 'uncontrolled',
    initialValues: {
      name: '',
      source_type: 'xmltv',
      url: '',
      username: '',
      api_key: '',
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

    const hasCronExpression =
      values.cron_expression && values.cron_expression.trim() !== '';

    if (hasCronExpression) {
      values.refresh_interval = 0;
    } else {
      values.cron_expression = '';
    }

    if (epg?.id) {
      if (!epg || typeof epg !== 'object' || !epg.id) {
        showNotification({
          title: 'Error',
          message: 'Invalid EPG data. Please close and reopen this form.',
          color: 'red',
        });
        return;
      }

      await updateEPG(values, epg);
      onClose();
    } else {
      const result = await addEPG(values);
      if (result?.id) {
        setSavedEpgId(result.id);
      } else {
        form.reset();
        onClose();
      }
    }
  };

  useEffect(() => {
    if (epg) {
      const values = {
        name: epg.name,
        source_type: epg.source_type,
        url: epg.url,
        username: epg.username || '',
        api_key: epg.api_key,
        is_active: epg.is_active,
        refresh_interval: epg.refresh_interval,
        cron_expression: epg.cron_expression || '',
        priority: epg.priority ?? 0,
      };
      form.setValues(values);
      setSourceType(epg.source_type);
      setSavedEpgId(epg.id);
      setScheduleType(
        epg.cron_expression && epg.cron_expression.trim() !== ''
          ? 'cron'
          : 'interval'
      );
    } else {
      form.reset();
      setSourceType('xmltv');
      setScheduleType('interval');
      setSavedEpgId(null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [epg]);

  const handleSourceTypeChange = (value) => {
    form.setFieldValue('source_type', value);
    setSourceType(value);
  };

  const handleClose = () => {
    form.reset();
    setSavedEpgId(null);
    onClose();
  };

  if (!isOpen) {
    return <></>;
  }

  const isSD = sourceType === 'schedules_direct';

  return (
    <>
      <Modal opened={isOpen} onClose={handleClose} title="EPG Source" size={700}>
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
                  { label: 'XMLTV', value: 'xmltv' },
                  { label: 'Schedules Direct', value: 'schedules_direct' },
                ]}
                onChange={(event) =>
                  handleSourceTypeChange(event.currentTarget.value)
                }
              />

              {isSD && (
                <Alert
                  icon={<TriangleAlert size={16} />}
                  color="yellow"
                  variant="light"
                  title="Schedules Direct API Limits"
                >
                  Schedules Direct enforces a limit of approximately 200 requests per 2 hours.
                  Each refresh uses ~15 requests. Avoid frequent manual refreshes to prevent
                  your account from being temporarily blocked. A 24-hour refresh interval
                  is recommended.
                </Alert>
              )}

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

              {isSD && scheduleType === 'cron' && (
                <Alert
                  icon={<TriangleAlert size={16} />}
                  color="orange"
                  variant="light"
                  title="Schedules Direct Rate Limit Warning"
                >
                  <strong>Exceeding SD's rate limits may result in a permanent account ban.</strong>{' '}
                  Schedules Direct enforces a limit of ~200 API requests per 2-hour window.
                  Your cron schedule must not trigger a refresh more than once every 2 hours.
                  The recommended minimum schedule is{' '}
                  <code>0 */2 * * *</code> (every 2 hours).{' '}
                  <a
                    href="https://github.com/SchedulesDirect/JSON-Service/wiki/API-20141201#tasks-your-client-must-perform"
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    Learn more
                  </a>
                </Alert>
              )}

              {isSD && scheduleType === 'interval' && form.getValues().refresh_interval > 0 && form.getValues().refresh_interval < 2 && (
                <Alert
                  icon={<TriangleAlert size={16} />}
                  color="red"
                  variant="light"
                  title="Interval Too Short"
                >
                  <strong>Schedules Direct requires a minimum refresh interval of 2 hours.</strong>{' '}
                  Setting a shorter interval may result in your account being banned.
                  Please set the interval to 2 or higher, or use 0 to disable auto-refresh.
                </Alert>
              )}
            </Stack>

            <Divider size="sm" orientation="vertical" />

            {/* Right Column */}
            <Stack gap="md" style={{ flex: 1 }}>
              {!isSD && (
                <TextInput
                  id="url"
                  name="url"
                  label="URL"
                  description="Direct URL to the XMLTV file or API endpoint"
                  {...form.getInputProps('url')}
                  key={form.key('url')}
                />
              )}

              {isSD && (
                <>
                  <TextInput
                    id="username"
                    name="username"
                    label="Username"
                    description="Your Schedules Direct account username"
                    {...form.getInputProps('username')}
                    key={form.key('username')}
                  />
                  <TextInput
                    id="api_key"
                    name="api_key"
                    label="Password"
                    description="Your Schedules Direct account password"
                    type="password"
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

          {/* Lineup Manager — only shown for saved SD sources */}
          {isSD && savedEpgId && (
            <SDLineupManager sourceId={savedEpgId} />
          )}

          {/* Full Width Section */}
          <Box mt="md">
            <Divider my="sm" />

            {isSD && !savedEpgId && (
              <Text size="xs" c="dimmed" mb="sm">
                Save this source first to manage Schedules Direct lineups.
              </Text>
            )}

            <Group justify="end" mt="xl">
              <Button variant="outline" onClick={handleClose}>
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
