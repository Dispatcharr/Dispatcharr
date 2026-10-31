import {
  ActionIcon,
  Group,
  ScrollArea,
  Table,
  Text,
  Tooltip,
} from '@mantine/core';
import { Eye, LockKeyhole, LockKeyholeOpen } from 'lucide-react';
import { libraryMetadataStatus } from '../utils/libraryMetadataStatus.js';
import classes from './LibraryWorkspace.module.css';

const Title = ({ value, color }) => (
  <Tooltip
    label={value || '—'}
    multiline
    maw={500}
    styles={{ tooltip: { overflowWrap: 'anywhere' } }}
  >
    <Text size="sm" c={color} truncate className={classes.cleanupTitle}>
      {value || '—'}
    </Text>
  </Tooltip>
);

export default function CleanupPreviewTable({ rows, items = [], onPreview }) {
  const selection = !!onPreview;
  const Frame = selection ? ScrollArea.Autosize : 'div';
  return (
    <Frame
      {...(selection ? { mah: '45dvh', offsetScrollbars: true } : {})}
      className={classes.tableFrame}
    >
      <Table.ScrollContainer minWidth={selection ? 720 : 440}>
        <Table
          striped
          layout="fixed"
          className={classes.cleanupTable}
          aria-label="Cleanup preview"
        >
          <colgroup>
            <col />
            <col />
            <col style={{ width: 90 }} />
            {selection && (
              <>
                <col style={{ width: 160 }} />
                <col style={{ width: 72 }} />
              </>
            )}
          </colgroup>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Provider title</Table.Th>
              <Table.Th>Clean title</Table.Th>
              <Table.Th>Year</Table.Th>
              {selection && (
                <>
                  <Table.Th>TMDB result</Table.Th>
                  <Table.Th ta="center">Details</Table.Th>
                </>
              )}
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {!rows.length && (
              <Table.Tr>
                <Table.Td colSpan={selection ? 5 : 3}>
                  <Text size="sm" c="dimmed" ta="center">
                    No matching titles
                  </Text>
                </Table.Td>
              </Table.Tr>
            )}
            {rows.map((row) => {
              const item =
                items.find(
                  (value) =>
                    value.content_type === row.content_type &&
                    value.content_id === row.id
                ) || row.item;
              const before = selection
                ? item?.provider_name || row.before
                : row.before;
              const status = libraryMetadataStatus(item || {});
              const LockIcon = row.locked ? LockKeyhole : LockKeyholeOpen;
              return (
                <Table.Tr
                  key={`${row.content_type}:${row.source_id || row.id}`}
                >
                  <Table.Td>
                    <Title value={before} />
                  </Table.Td>
                  <Table.Td>
                    <Group gap="xs" wrap="nowrap">
                      <Title
                        value={row.after}
                        color={before !== row.after ? 'teal' : 'dimmed'}
                      />
                    </Group>
                  </Table.Td>
                  <Table.Td>{row.year ?? '—'}</Table.Td>
                  {selection && (
                    <>
                      <Table.Td>
                        <Text size="xs" c={status.color}>
                          {status.label}
                        </Text>
                      </Table.Td>
                      <Table.Td>
                        <Group gap={4} wrap="nowrap" justify="center">
                          <Tooltip
                            label={
                              row.locked
                                ? 'Automatic metadata matching is locked'
                                : 'Automatic metadata matching is unlocked'
                            }
                            withArrow
                          >
                            <LockIcon
                              size={15}
                              aria-label={
                                row.locked
                                  ? 'Metadata locked'
                                  : 'Metadata unlocked'
                              }
                            />
                          </Tooltip>
                          <Tooltip label="Open title preview" withArrow>
                            <ActionIcon
                              size="sm"
                              variant="subtle"
                              aria-label={`Preview ${row.after || row.before}`}
                              onClick={() =>
                                onPreview(
                                  item || {
                                    content_type: row.content_type,
                                    content_id: row.id,
                                    name: row.after || row.before,
                                    year: row.year,
                                  }
                                )
                              }
                            >
                              <Eye size={16} />
                            </ActionIcon>
                          </Tooltip>
                        </Group>
                      </Table.Td>
                    </>
                  )}
                </Table.Tr>
              );
            })}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>
    </Frame>
  );
}
