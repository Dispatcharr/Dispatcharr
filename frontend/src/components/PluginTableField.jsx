import React from 'react';
import {
  ActionIcon,
  Button,
  Checkbox,
  NumberInput,
  Select,
  Stack,
  Table,
  Text,
  TextInput,
} from '@mantine/core';
import { SquarePlus, Trash2 } from 'lucide-react';

const emptyRow = (columns) =>
  Object.fromEntries((columns || []).map((c) => [c.id, undefined]));

const CellInput = ({ column, value, onChange }) => {
  switch (column.type) {
    case 'boolean':
      return (
        <Checkbox
          checked={!!value}
          onChange={(e) => onChange(e.currentTarget.checked)}
        />
      );
    case 'number':
      return (
        <NumberInput value={value ?? ''} onChange={onChange} size="xs" />
      );
    case 'select':
      return (
        <Select
          value={value != null ? value + '' : null}
          data={(column.options || []).map((o) => ({
            value: o.value + '',
            label: o.label,
          }))}
          onChange={onChange}
          size="xs"
        />
      );
    case 'string':
    default:
      return (
        <TextInput
          value={value ?? ''}
          onChange={(e) => onChange(e.currentTarget.value)}
          size="xs"
        />
      );
  }
};

export const PluginTableField = ({ field, value, onChange }) => {
  const columns = field.columns || [];
  const rows = Array.isArray(value) ? value : field.default || [];

  const updateCell = (rowIndex, colId, newVal) => {
    const next = rows.map((row, i) =>
      i === rowIndex ? { ...row, [colId]: newVal } : row
    );
    onChange(field.id, next);
  };

  const addRow = () => {
    onChange(field.id, [...rows, emptyRow(columns)]);
  };

  const deleteRow = (rowIndex) => {
    onChange(
      field.id,
      rows.filter((_, i) => i !== rowIndex)
    );
  };

  return (
    <Stack gap="xs">
      {field.label && (
        <Text fw={600} size="sm">
          {field.label}
        </Text>
      )}
      <Table withTableBorder withColumnBorders>
        <Table.Thead>
          <Table.Tr>
            {columns.map((c) => (
              <Table.Th key={c.id}>{c.label || c.id}</Table.Th>
            ))}
            <Table.Th w={40} />
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {rows.map((row, rowIndex) => (
            <Table.Tr key={rowIndex}>
              {columns.map((col) => (
                <Table.Td key={col.id}>
                  <CellInput
                    column={col}
                    value={row?.[col.id]}
                    onChange={(v) => updateCell(rowIndex, col.id, v)}
                  />
                </Table.Td>
              ))}
              <Table.Td>
                <ActionIcon
                  variant="subtle"
                  color="red"
                  onClick={() => deleteRow(rowIndex)}
                >
                  <Trash2 size={16} />
                </ActionIcon>
              </Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
      <Button
        variant="subtle"
        size="xs"
        leftSection={<SquarePlus size={16} />}
        onClick={addRow}
        style={{ alignSelf: 'flex-start' }}
      >
        Add row
      </Button>
    </Stack>
  );
};
