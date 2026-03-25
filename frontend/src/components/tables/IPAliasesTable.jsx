import { useMemo, useState } from 'react';
import useIPAliasesStore from '../../store/ipAliases';
import IPAliasForm from '../forms/IPAliasForm';
import {
  ActionIcon,
  Tooltip,
  Text,
  Paper,
  Box,
  Button,
  Stack,
  Flex,
} from '@mantine/core';
import { SquareMinus, SquarePen, SquarePlus } from 'lucide-react';
import { CustomTable, useTable } from './CustomTable';

const RowActions = ({ row, editAlias, deleteAlias }) => {
  return (
    <>
      <ActionIcon
        variant="transparent"
        size="sm"
        color="yellow.5"
        onClick={() => editAlias(row.original)}
      >
        <SquarePen size="18" />
      </ActionIcon>
      <ActionIcon
        variant="transparent"
        size="sm"
        color="red.9"
        onClick={() => deleteAlias(row.original.id)}
      >
        <SquareMinus size="18" />
      </ActionIcon>
    </>
  );
};

const IPAliasesTable = () => {
  const [editingAlias, setEditingAlias] = useState(null);
  const [formOpen, setFormOpen] = useState(false);

  const aliases = useIPAliasesStore((s) => s.aliases);
  const deleteAlias = useIPAliasesStore((s) => s.deleteAlias);

  const columns = useMemo(
    () => [
      {
        header: 'Alias',
        accessorKey: 'alias',
        size: 200,
      },
      {
        header: 'IP Address',
        accessorKey: 'ip_address',
        size: 200,
        cell: ({ cell }) => (
          <Text size="sm" ff="monospace">
            {cell.getValue()}
          </Text>
        ),
      },
      {
        id: 'actions',
        header: 'Actions',
        size: 75,
      },
    ],
    []
  );

  const editAlias = (alias = null) => {
    setEditingAlias(alias);
    setFormOpen(true);
  };

  const handleDelete = async (id) => {
    await deleteAlias(id);
  };

  const closeForm = () => {
    setEditingAlias(null);
    setFormOpen(false);
  };

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
            editAlias={editAlias}
            deleteAlias={handleDelete}
          />
        );
    }
  };

  const table = useTable({
    columns,
    data: aliases,
    allRowIds: aliases.map((a) => a.id),
    bodyCellRenderFns: {
      actions: renderBodyCell,
    },
    headerCellRenderFns: {
      alias: renderHeaderCell,
      ip_address: renderHeaderCell,
      actions: renderHeaderCell,
    },
  });

  return (
    <Stack gap={0} style={{ padding: 0 }}>
      <Paper>
        <Box
          style={{
            display: 'flex',
            justifyContent: 'flex-end',
            padding: 10,
          }}
        >
          <Flex gap={6}>
            <Tooltip label="Add IP Alias">
              <Button
                leftSection={<SquarePlus size={18} />}
                variant="light"
                size="xs"
                onClick={() => editAlias()}
                p={5}
                color="green"
                style={{
                  borderWidth: '1px',
                  borderColor: 'green',
                  color: 'white',
                }}
              >
                Add IP Alias
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
          <div style={{ minWidth: 400 }}>
            <CustomTable table={table} />
          </div>
        </Box>
      </Box>

      {aliases.length === 0 && (
        <Text size="sm" c="dimmed" ta="center" py="md">
          No IP aliases configured. Add one to see friendly names on the Stats
          page.
        </Text>
      )}

      <IPAliasForm
        ipAlias={editingAlias}
        isOpen={formOpen}
        onClose={closeForm}
      />
    </Stack>
  );
};

export default IPAliasesTable;
