import { useState } from 'react';
import { Box, Button, Group, Modal, Table, Text, Tooltip, UnstyledButton } from '@mantine/core';
import { ChevronRight, TriangleAlert } from 'lucide-react';
import useSettingsStore from '../store/settings';

const NO_EFFECTS = [];

export function SafeModeSidebar({ collapsed }) {
  const safeMode = useSettingsStore((state) => state.environment?.safe_mode);
  const effects = useSettingsStore((state) => state.environment?.safe_mode_effects ?? NO_EFFECTS);
  const [opened, setOpened] = useState(false);
  if (!safeMode) return null;

  const button = (
    <UnstyledButton
      aria-label="Safe mode active, learn more"
      onClick={() => setOpened(true)}
      style={{ width: '100%', padding: collapsed ? 8 : 10, borderRadius: 6,
        color: 'var(--mantine-color-yellow-4)', background: 'var(--mantine-color-yellow-light)' }}
    >
      <Group gap="xs" justify={collapsed ? 'center' : 'flex-start'} wrap="nowrap">
        <TriangleAlert size={19} style={{ flexShrink: 0 }} />
        {!collapsed && <>
          <Box style={{ flex: 1 }}><Text size="sm" fw={700}>Safe mode active</Text>
            <Text size="xs">Some features may be unavailable.</Text></Box>
          <ChevronRight size={16} style={{ flexShrink: 0 }} />
        </>}
      </Group>
    </UnstyledButton>
  );

  return (
    <>
      {collapsed ? <Tooltip label="Safe mode active" position="right">{button}</Tooltip> : button}
      <Modal opened={opened} onClose={() => setOpened(false)} title="Safe mode active" centered>
        <Table mb="md">
          <Table.Tbody>
            {effects.map((effect) => (
              <Table.Tr key={effect.id}>
                <Table.Td>{effect.label}</Table.Td><Table.Td>{effect.status}</Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
        <Text size="sm">To exit safe mode, remove DISPATCHARR_SAFE_MODE and recreate the container. For modular installs, update both web and Celery.</Text>
        <Group justify="flex-end" mt="md"><Button onClick={() => setOpened(false)}>Close</Button></Group>
      </Modal>
    </>
  );
}
