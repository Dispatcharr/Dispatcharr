import React from 'react';
import {
  Badge,
  Card,
  Group,
  Stack,
  Text,
  ActionIcon,
  Tooltip,
  Button,
} from '@mantine/core';
import {
  CircleDashed,
  Clock,
  Pencil,
  PlayCircle,
  RefreshCw,
  Trash2,
} from 'lucide-react';
import dayjs from 'dayjs';
import relativeTime from 'dayjs/plugin/relativeTime';

dayjs.extend(relativeTime);

const formatDate = (value) => {
  if (!value) return 'Never';
  return dayjs(value).fromNow();
};

const LibraryCard = ({
  library,
  selected,
  onSelect,
  onEdit,
  onDelete,
  onScan,
  loadingScan = false,
}) => {
  return (
    <Card
      shadow={selected ? 'lg' : 'sm'}
      padding="lg"
      radius="md"
      withBorder
      onClick={() => onSelect(library.id)}
      style={{
        cursor: 'pointer',
        borderColor: selected ? '#6366f1' : undefined,
        transition: 'transform 150ms ease, border-color 150ms ease',
      }}
    >
      <Stack spacing="xs">
        <Group align="center" justify="space-between">
          <Text fw={600} size="lg">
            {library.name}
          </Text>
          <Group gap="xs">
            <Badge color="violet" variant="light">
              {library.library_type?.replace('-', ' ') || 'Unknown'}
            </Badge>
            {library.auto_scan_enabled ? (
              <Badge color="green" variant="outline">
                Auto-scan
              </Badge>
            ) : (
              <Badge color="gray" variant="outline">
                Manual only
              </Badge>
            )}
          </Group>
        </Group>

        {library.description && (
          <Text size="sm" c="dimmed">
            {library.description}
          </Text>
        )}

        <Group gap="sm">
          <Tooltip label="Last scan">
            <Group gap={4} align="center">
              <Clock size={16} />
              <Text size="xs">{formatDate(library.last_scan_at)}</Text>
            </Group>
          </Tooltip>
          <Tooltip label="Last success">
            <Group gap={4} align="center">
              <CircleDashed size={16} />
              <Text size="xs">{formatDate(library.last_successful_scan_at)}</Text>
            </Group>
          </Tooltip>
        </Group>

        <Group justify="space-between" mt="sm">
          <Button
            size="xs"
            variant={selected ? 'filled' : 'light'}
            leftSection={<PlayCircle size={16} />}
            onClick={(event) => {
              event.stopPropagation();
              onSelect(library.id);
            }}
          >
            Browse
          </Button>
          <Group gap="xs">
            <Tooltip label="Trigger scan">
              <ActionIcon
                size="sm"
                variant="light"
                loading={loadingScan}
                onClick={(event) => {
                  event.stopPropagation();
                  onScan(library.id);
                }}
              >
                <RefreshCw size={16} />
              </ActionIcon>
            </Tooltip>
            <Tooltip label="Edit library">
              <ActionIcon
                size="sm"
                variant="light"
                onClick={(event) => {
                  event.stopPropagation();
                  onEdit(library);
                }}
              >
                <Pencil size={16} />
              </ActionIcon>
            </Tooltip>
            <Tooltip label="Delete library">
              <ActionIcon
                size="sm"
                variant="light"
                color="red"
                onClick={(event) => {
                  event.stopPropagation();
                  onDelete(library);
                }}
              >
                <Trash2 size={16} />
              </ActionIcon>
            </Tooltip>
          </Group>
        </Group>
      </Stack>
    </Card>
  );
};

export default LibraryCard;
