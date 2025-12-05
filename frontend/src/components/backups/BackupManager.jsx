import { useEffect, useMemo, useState } from 'react';
import {
  ActionIcon,
  Box,
  Button,
  FileInput,
  Flex,
  Group,
  Loader,
  Modal,
  NumberInput,
  Paper,
  Select,
  Stack,
  Switch,
  Text,
  TextInput,
  Tooltip,
} from '@mantine/core';
import {
  Download,
  RefreshCcw,
  RotateCcw,
  SquareMinus,
  SquarePlus,
  UploadCloud,
} from 'lucide-react';
import { notifications } from '@mantine/notifications';

import API from '../../api';
import ConfirmationDialog from '../ConfirmationDialog';
import useLocalStorage from '../../hooks/useLocalStorage';
import { CustomTable, useTable } from '../tables/CustomTable';

const RowActions = ({ row, handleDownload, handleRestoreClick, handleDeleteClick, downloading }) => {
  return (
    <Flex gap={4} wrap="nowrap">
      <Tooltip label="Download">
        <ActionIcon
          variant="transparent"
          size="sm"
          color="blue.5"
          onClick={() => handleDownload(row.original.name)}
          loading={downloading === row.original.name}
          disabled={downloading !== null}
        >
          <Download size={18} />
        </ActionIcon>
      </Tooltip>
      <Tooltip label="Restore">
        <ActionIcon
          variant="transparent"
          size="sm"
          color="yellow.5"
          onClick={() => handleRestoreClick(row.original)}
        >
          <RotateCcw size={18} />
        </ActionIcon>
      </Tooltip>
      <Tooltip label="Delete">
        <ActionIcon
          variant="transparent"
          size="sm"
          color="red.9"
          onClick={() => handleDeleteClick(row.original)}
        >
          <SquareMinus size={18} />
        </ActionIcon>
      </Tooltip>
    </Flex>
  );
};

// Convert 24h time string to 12h format with period
function to12Hour(time24) {
  if (!time24) return { time: '12:00', period: 'AM' };
  const [hours, minutes] = time24.split(':').map(Number);
  const period = hours >= 12 ? 'PM' : 'AM';
  const hours12 = hours % 12 || 12;
  return {
    time: `${hours12}:${String(minutes).padStart(2, '0')}`,
    period,
  };
}

// Convert 12h time + period to 24h format
function to24Hour(time12, period) {
  if (!time12) return '00:00';
  const [hours, minutes] = time12.split(':').map(Number);
  let hours24 = hours;
  if (period === 'PM' && hours !== 12) {
    hours24 = hours + 12;
  } else if (period === 'AM' && hours === 12) {
    hours24 = 0;
  }
  return `${String(hours24).padStart(2, '0')}:${String(minutes).padStart(2, '0')}`;
}

const DAYS_OF_WEEK = [
  { value: '0', label: 'Sunday' },
  { value: '1', label: 'Monday' },
  { value: '2', label: 'Tuesday' },
  { value: '3', label: 'Wednesday' },
  { value: '4', label: 'Thursday' },
  { value: '5', label: 'Friday' },
  { value: '6', label: 'Saturday' },
];

function formatBytes(bytes) {
  if (bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${(bytes / Math.pow(k, i)).toFixed(2)} ${sizes[i]}`;
}

function formatDate(dateString) {
  const date = new Date(dateString);
  return date.toLocaleString();
}

export default function BackupManager() {
  const [backups, setBackups] = useState([]);
  const [loading, setLoading] = useState(false);
  const [creating, setCreating] = useState(false);
  const [downloading, setDownloading] = useState(null);
  const [uploadFile, setUploadFile] = useState(null);
  const [uploadModalOpen, setUploadModalOpen] = useState(false);
  const [restoreConfirmOpen, setRestoreConfirmOpen] = useState(false);
  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false);
  const [selectedBackup, setSelectedBackup] = useState(null);

  // Read user's time format preference from settings
  const [timeFormat] = useLocalStorage('time-format', '12h');
  const [tableSize] = useLocalStorage('table-size', 'default');
  const is12Hour = timeFormat === '12h';

  // Schedule state
  const [schedule, setSchedule] = useState({
    enabled: false,
    frequency: 'daily',
    time: '03:00',
    day_of_week: 0,
    retention_count: 0,
  });
  const [scheduleLoading, setScheduleLoading] = useState(false);
  const [scheduleSaving, setScheduleSaving] = useState(false);
  const [scheduleChanged, setScheduleChanged] = useState(false);

  // For 12-hour display mode
  const [displayTime, setDisplayTime] = useState('3:00');
  const [timePeriod, setTimePeriod] = useState('AM');

  const columns = useMemo(
    () => [
      {
        header: 'Filename',
        accessorKey: 'name',
        grow: true,
        cell: ({ cell }) => (
          <div
            style={{
              whiteSpace: 'nowrap',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
            }}
          >
            {cell.getValue()}
          </div>
        ),
      },
      {
        header: 'Size',
        accessorKey: 'size',
        size: 80,
        cell: ({ cell }) => (
          <Text size="sm">{formatBytes(cell.getValue())}</Text>
        ),
      },
      {
        header: 'Created',
        accessorKey: 'created',
        size: 160,
        cell: ({ cell }) => (
          <Text size="sm">{formatDate(cell.getValue())}</Text>
        ),
      },
      {
        id: 'actions',
        header: 'Actions',
        size: tableSize === 'compact' ? 75 : 100,
      },
    ],
    [tableSize]
  );

  const renderHeaderCell = (header) => {
    return (
      <Text size="sm" name={header.id}>
        {header.column.columnDef.header}
      </Text>
    );
  };

  const renderBodyCell = ({ cell, row }) => {
    switch (cell.column.id) {
      case 'actions':
        return (
          <RowActions
            row={row}
            handleDownload={handleDownload}
            handleRestoreClick={handleRestoreClick}
            handleDeleteClick={handleDeleteClick}
            downloading={downloading}
          />
        );
    }
  };

  const table = useTable({
    columns,
    data: backups,
    allRowIds: backups.map((b) => b.name),
    bodyCellRenderFns: {
      actions: renderBodyCell,
    },
    headerCellRenderFns: {
      name: renderHeaderCell,
      size: renderHeaderCell,
      created: renderHeaderCell,
      actions: renderHeaderCell,
    },
  });

  const loadBackups = async () => {
    setLoading(true);
    try {
      const backupList = await API.listBackups();
      setBackups(backupList);
    } catch (error) {
      notifications.show({
        title: 'Error',
        message: error?.message || 'Failed to load backups',
        color: 'red',
      });
    } finally {
      setLoading(false);
    }
  };

  const loadSchedule = async () => {
    setScheduleLoading(true);
    try {
      const settings = await API.getBackupSchedule();
      setSchedule(settings);
      setScheduleChanged(false);
      // Initialize 12-hour display values from the loaded time
      const { time, period } = to12Hour(settings.time);
      setDisplayTime(time);
      setTimePeriod(period);
    } catch (error) {
      // Ignore errors on initial load - settings may not exist yet
    } finally {
      setScheduleLoading(false);
    }
  };

  useEffect(() => {
    loadBackups();
    loadSchedule();
  }, []);

  const handleScheduleChange = (field, value) => {
    setSchedule((prev) => ({ ...prev, [field]: value }));
    setScheduleChanged(true);
  };

  // Handle time changes in 12-hour mode
  const handleTimeChange12h = (newTime, newPeriod) => {
    const time = newTime ?? displayTime;
    const period = newPeriod ?? timePeriod;
    setDisplayTime(time);
    setTimePeriod(period);
    // Convert to 24h and update schedule
    const time24 = to24Hour(time, period);
    handleScheduleChange('time', time24);
  };

  // Handle time changes in 24-hour mode
  const handleTimeChange24h = (value) => {
    handleScheduleChange('time', value);
    // Also update 12h display state in case user switches formats
    const { time, period } = to12Hour(value);
    setDisplayTime(time);
    setTimePeriod(period);
  };

  const handleSaveSchedule = async () => {
    setScheduleSaving(true);
    try {
      const updated = await API.updateBackupSchedule(schedule);
      setSchedule(updated);
      setScheduleChanged(false);
      notifications.show({
        title: 'Success',
        message: 'Backup schedule saved',
        color: 'green',
      });
    } catch (error) {
      notifications.show({
        title: 'Error',
        message: error?.message || 'Failed to save schedule',
        color: 'red',
      });
    } finally {
      setScheduleSaving(false);
    }
  };

  const handleCreateBackup = async () => {
    setCreating(true);
    try {
      await API.createBackup();
      notifications.show({
        title: 'Success',
        message: 'Backup created successfully',
        color: 'green',
      });
      await loadBackups();
    } catch (error) {
      notifications.show({
        title: 'Error',
        message: error?.message || 'Failed to create backup',
        color: 'red',
      });
    } finally {
      setCreating(false);
    }
  };

  const handleDownload = async (filename) => {
    setDownloading(filename);
    try {
      await API.downloadBackup(filename);
      notifications.show({
        title: 'Download Started',
        message: `Downloading ${filename}...`,
        color: 'blue',
      });
    } catch (error) {
      notifications.show({
        title: 'Error',
        message: error?.message || 'Failed to download backup',
        color: 'red',
      });
    } finally {
      setDownloading(null);
    }
  };

  const handleDeleteClick = (backup) => {
    setSelectedBackup(backup);
    setDeleteConfirmOpen(true);
  };

  const handleDeleteConfirm = async () => {
    try {
      await API.deleteBackup(selectedBackup.name);
      notifications.show({
        title: 'Success',
        message: 'Backup deleted successfully',
        color: 'green',
      });
      await loadBackups();
    } catch (error) {
      notifications.show({
        title: 'Error',
        message: error?.message || 'Failed to delete backup',
        color: 'red',
      });
    } finally {
      setDeleteConfirmOpen(false);
      setSelectedBackup(null);
    }
  };

  const handleRestoreClick = (backup) => {
    setSelectedBackup(backup);
    setRestoreConfirmOpen(true);
  };

  const handleRestoreConfirm = async () => {
    try {
      await API.restoreBackup(selectedBackup.name);
      notifications.show({
        title: 'Success',
        message: 'Backup restored successfully. You may need to refresh the page.',
        color: 'green',
      });
      setTimeout(() => window.location.reload(), 2000);
    } catch (error) {
      notifications.show({
        title: 'Error',
        message: error?.message || 'Failed to restore backup',
        color: 'red',
      });
    } finally {
      setRestoreConfirmOpen(false);
      setSelectedBackup(null);
    }
  };

  const handleUploadSubmit = async () => {
    if (!uploadFile) return;

    try {
      await API.uploadBackup(uploadFile);
      notifications.show({
        title: 'Success',
        message: 'Backup uploaded successfully',
        color: 'green',
      });
      setUploadModalOpen(false);
      setUploadFile(null);
      await loadBackups();
    } catch (error) {
      notifications.show({
        title: 'Error',
        message: error?.message || 'Failed to upload backup',
        color: 'red',
      });
    }
  };

  return (
    <Stack gap="md">
      {/* Schedule Settings */}
      <Stack gap="sm">
        <Group justify="space-between">
          <Text size="sm" fw={500}>Scheduled Backups</Text>
          <Switch
            checked={schedule.enabled}
            onChange={(e) => handleScheduleChange('enabled', e.currentTarget.checked)}
            label={schedule.enabled ? 'Enabled' : 'Disabled'}
          />
        </Group>

        {scheduleLoading ? (
          <Loader size="sm" />
        ) : (
          <>
            <Group grow align="flex-end">
              <Select
                label="Frequency"
                value={schedule.frequency}
                onChange={(value) => handleScheduleChange('frequency', value)}
                data={[
                  { value: 'daily', label: 'Daily' },
                  { value: 'weekly', label: 'Weekly' },
                ]}
                disabled={!schedule.enabled}
              />
              {schedule.frequency === 'weekly' && (
                <Select
                  label="Day"
                  value={String(schedule.day_of_week)}
                  onChange={(value) => handleScheduleChange('day_of_week', parseInt(value, 10))}
                  data={DAYS_OF_WEEK}
                  disabled={!schedule.enabled}
                />
              )}
              {is12Hour ? (
                <Group grow align="flex-end" gap="xs">
                  <TextInput
                    label="Time"
                    value={displayTime}
                    onChange={(e) => handleTimeChange12h(e.currentTarget.value, null)}
                    placeholder="3:00"
                    disabled={!schedule.enabled}
                  />
                  <Select
                    value={timePeriod}
                    onChange={(value) => handleTimeChange12h(null, value)}
                    data={[
                      { value: 'AM', label: 'AM' },
                      { value: 'PM', label: 'PM' },
                    ]}
                    disabled={!schedule.enabled}
                  />
                </Group>
              ) : (
                <TextInput
                  label="Time"
                  value={schedule.time}
                  onChange={(e) => handleTimeChange24h(e.currentTarget.value)}
                  placeholder="03:00"
                  disabled={!schedule.enabled}
                />
              )}
              <NumberInput
                label="Retention"
                description="0 = keep all"
                value={schedule.retention_count}
                onChange={(value) => handleScheduleChange('retention_count', value || 0)}
                min={0}
                disabled={!schedule.enabled}
              />
              <Button
                onClick={handleSaveSchedule}
                loading={scheduleSaving}
                disabled={!scheduleChanged}
                variant="default"
              >
                Save
              </Button>
            </Group>
          </>
        )}
      </Stack>

      {/* Backups List */}
      <Stack gap={0}>
        <Paper>
          <Box
            style={{
              display: 'flex',
              justifyContent: 'flex-end',
              padding: 10,
            }}
          >
            <Flex gap={6}>
              <Tooltip label="Upload existing backup">
                <Button
                  leftSection={<UploadCloud size={18} />}
                  variant="light"
                  size="xs"
                  onClick={() => setUploadModalOpen(true)}
                  p={5}
                >
                  Upload
                </Button>
              </Tooltip>
              <Tooltip label="Refresh list">
                <Button
                  leftSection={<RefreshCcw size={18} />}
                  variant="light"
                  size="xs"
                  onClick={loadBackups}
                  loading={loading}
                  p={5}
                >
                  Refresh
                </Button>
              </Tooltip>
              <Tooltip label="Create new backup">
                <Button
                  leftSection={<SquarePlus size={18} />}
                  variant="light"
                  size="xs"
                  onClick={handleCreateBackup}
                  loading={creating}
                  p={5}
                  color="green"
                  style={{
                    borderWidth: '1px',
                    borderColor: 'green',
                    color: 'white',
                  }}
                >
                  Create Backup
                </Button>
              </Tooltip>
            </Flex>
          </Box>
        </Paper>

        <Box
          style={{
            display: 'flex',
            flexDirection: 'column',
            maxHeight: 300,
            width: '100%',
            overflow: 'hidden',
          }}
        >
          <Box
            style={{
              flex: 1,
              overflowY: 'auto',
              overflowX: 'auto',
              border: 'solid 1px rgb(68,68,68)',
              borderRadius: 'var(--mantine-radius-default)',
            }}
          >
            {loading ? (
              <Box p="xl" style={{ display: 'flex', justifyContent: 'center' }}>
                <Loader />
              </Box>
            ) : backups.length === 0 ? (
              <Text size="sm" c="dimmed" p="md" ta="center">
                No backups found. Create one to get started.
              </Text>
            ) : (
              <div style={{ minWidth: 500 }}>
                <CustomTable table={table} />
              </div>
            )}
          </Box>
        </Box>
      </Stack>

      <Modal
        opened={uploadModalOpen}
        onClose={() => {
          setUploadModalOpen(false);
          setUploadFile(null);
        }}
        title="Upload Backup"
      >
        <Stack>
          <FileInput
            label="Select backup file"
            placeholder="Choose a .zip file"
            accept=".zip,application/zip,application/x-zip-compressed"
            value={uploadFile}
            onChange={setUploadFile}
          />
          <Group justify="flex-end">
            <Button
              variant="outline"
              onClick={() => {
                setUploadModalOpen(false);
                setUploadFile(null);
              }}
            >
              Cancel
            </Button>
            <Button onClick={handleUploadSubmit} disabled={!uploadFile} variant="default">
              Upload
            </Button>
          </Group>
        </Stack>
      </Modal>

      <ConfirmationDialog
        opened={restoreConfirmOpen}
        onClose={() => {
          setRestoreConfirmOpen(false);
          setSelectedBackup(null);
        }}
        onConfirm={handleRestoreConfirm}
        title="Restore Backup"
        message={`Are you sure you want to restore from "${selectedBackup?.name}"? This will replace all current data with the backup data. This action cannot be undone.`}
        confirmLabel="Restore"
        cancelLabel="Cancel"
      />

      <ConfirmationDialog
        opened={deleteConfirmOpen}
        onClose={() => {
          setDeleteConfirmOpen(false);
          setSelectedBackup(null);
        }}
        onConfirm={handleDeleteConfirm}
        title="Delete Backup"
        message={`Are you sure you want to delete "${selectedBackup?.name}"? This action cannot be undone.`}
        confirmLabel="Delete"
        cancelLabel="Cancel"
      />
    </Stack>
  );
}
