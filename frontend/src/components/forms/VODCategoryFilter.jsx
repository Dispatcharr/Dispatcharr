// Modal.js
import React, { useState, useEffect } from 'react';
import {
  TextInput,
  Button,
  Flex,
  Stack,
  Group,
  SimpleGrid,
  Text,
  Divider,
  Box,
  Checkbox,
} from '@mantine/core';
import { CircleCheck, CircleX } from 'lucide-react';
import useVODStore from '../../store/useVODStore';

const VODCategoryFilter = ({
  playlist = null,
  categoryStates,
  setCategoryStates,
  type,
  autoEnableNewGroups,
  setAutoEnableNewGroups,
}) => {
  const categories = useVODStore((s) => s.categories);
  const [filter, setFilter] = useState('');

  useEffect(() => {
    if (Object.keys(categories).length === 0) {
      return;
    }

    console.log(categories);

    setCategoryStates(
      Object.values(categories)
        .filter(
          (cat) =>
            cat.m3u_accounts.find((acc) => acc.m3u_account == playlist.id) &&
            cat.category_type == type
        )
        .map((cat) => {
          const match = cat.m3u_accounts.find(
            (acc) => acc.m3u_account == playlist.id
          );
          if (match) {
            return {
              ...cat,
              enabled: match.enabled || false, // Keep user's previous choice, default to false for new categories
              original_enabled: match.enabled,
            };
          }
        })
    );
  }, [categories, playlist.id, setCategoryStates, type]);

  const toggleEnabled = (id) => {
    setCategoryStates(
      categoryStates.map((state) => ({
        ...state,
        enabled: state.id == id ? !state.enabled : state.enabled,
      }))
    );
  };

  const selectAll = () => {
    setCategoryStates(
      categoryStates.map((state) => ({
        ...state,
        enabled: state.name.toLowerCase().includes(filter.toLowerCase())
          ? true
          : state.enabled,
      }))
    );
  };

  const deselectAll = () => {
    setCategoryStates(
      categoryStates.map((state) => ({
        ...state,
        enabled: state.name.toLowerCase().includes(filter.toLowerCase())
          ? false
          : state.enabled,
      }))
    );
  };

  return (
    <Stack style={{ paddingTop: 10 }}>
      <Checkbox
        label={`Automatically enable new ${type === 'movie' ? 'movie' : 'series'} categories discovered on future scans`}
        checked={autoEnableNewGroups}
        onChange={(event) =>
          setAutoEnableNewGroups(event.currentTarget.checked)
        }
        size="sm"
        description="When disabled, new categories from the provider will be created but disabled by default. You can enable them manually later."
      />

      <Flex gap="sm">
        <TextInput
          placeholder="Filter categories..."
          value={filter}
          onChange={(event) => setFilter(event.currentTarget.value)}
          style={{ flex: 1 }}
          size="xs"
        />
        <Button variant="default" size="xs" onClick={selectAll}>
          Select Visible
        </Button>
        <Button variant="default" size="xs" onClick={deselectAll}>
          Deselect Visible
        </Button>
      </Flex>

      <Box style={{ maxHeight: '50vh', overflowY: 'auto' }}>
        <SimpleGrid
          cols={{ base: 1, sm: 2, md: 3 }}
          spacing="xs"
          verticalSpacing="xs"
        >
          {categoryStates
            .filter((category) => {
              return category.name.toLowerCase().includes(filter.toLowerCase());
            })
            .sort((a, b) => a.name.localeCompare(b.name))
            .map((category) => (
              <Group
                key={category.id}
                spacing="xs"
                style={{
                  padding: '8px',
                  border: '1px solid #444',
                  borderRadius: '8px',
                  backgroundColor: category.enabled ? '#2A2A2E' : '#1E1E22',
                  flexDirection: 'column',
                  alignItems: 'stretch',
                }}
              >
                {/* Group Enable/Disable Button */}
                <Button
                  color={category.enabled ? 'green' : 'gray'}
                  variant="filled"
                  onClick={() => toggleEnabled(category.id)}
                  radius="md"
                  size="xs"
                  leftSection={
                    category.enabled ? (
                      <CircleCheck size={14} />
                    ) : (
                      <CircleX size={14} />
                    )
                  }
                  fullWidth
                >
                  <Text size="xs" truncate>
                    {category.name}
                  </Text>
                </Button>
              </Group>
            ))}
        </SimpleGrid>
      </Box>
    </Stack>
  );
};

export default VODCategoryFilter;
