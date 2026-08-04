import React, { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Anchor, Box, Button, Group, Table, Text, Title } from '@mantine/core';
import { RefreshCcw } from 'lucide-react';
import API from '../api';
import { useDateTimeFormat, format } from '../utils/dateTimeUtils.js';

const humanSize = (bytes) => {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
};

const LogFilesPage = () => {
  const [files, setFiles] = useState([]);
  const [loading, setLoading] = useState(false);
  const { fullDateTimeFormat } = useDateTimeFormat();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const response = await API.getLogFiles();
      if (response) {
        setFiles(response.files || []);
      }
    } catch {
      // errorNotification already surfaced the failure
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <Box p="md" maw={1100} mx="auto">
      <Group justify="space-between" mb="md">
        <Title order={3}>Logs</Title>
        <Button
          size="xs"
          variant="default"
          leftSection={<RefreshCcw size={14} />}
          onClick={load}
          loading={loading}
        >
          Refresh
        </Button>
      </Group>

      <Table highlightOnHover>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>Filename</Table.Th>
            <Table.Th>Last Write Time</Table.Th>
            <Table.Th>Size</Table.Th>
            <Table.Th />
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {files.map((file) => (
            <Table.Tr key={file.name}>
              <Table.Td>
                <Anchor
                  component={Link}
                  to={`/logs/${encodeURIComponent(file.name)}`}
                  size="sm"
                >
                  {file.name}
                </Anchor>
              </Table.Td>
              <Table.Td>
                <Text size="sm">
                  {format(file.modified, fullDateTimeFormat)}
                </Text>
              </Table.Td>
              <Table.Td>
                <Text size="sm">{humanSize(file.size)}</Text>
              </Table.Td>
              <Table.Td align="right">
                <Button
                  variant="subtle"
                  size="xs"
                  onClick={() => API.downloadLogFile(file.name)}
                >
                  Download
                </Button>
              </Table.Td>
            </Table.Tr>
          ))}
          {files.length === 0 && !loading && (
            <Table.Tr>
              <Table.Td colSpan={4}>
                <Text size="sm" c="dimmed" ta="center" py="md">
                  No log files yet
                </Text>
              </Table.Td>
            </Table.Tr>
          )}
        </Table.Tbody>
      </Table>
    </Box>
  );
};

export default LogFilesPage;
