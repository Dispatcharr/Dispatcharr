import React, { useMemo, useState } from 'react';
import {
  Button,
  Checkbox,
  Group,
  Modal,
  ScrollArea,
  Stack,
  Text,
  TextInput,
} from '@mantine/core';
import { Plus } from 'lucide-react';
import {
  LANGUAGE_OPTIONS,
  normalizeLanguageCodes,
} from '../utils/languageCodes.js';

const labelForCode = (code) =>
  LANGUAGE_OPTIONS.find((option) => option.value === code)?.label ||
  String(code || '').toUpperCase();

const LanguagePicker = ({
  label,
  value = [],
  onChange,
  disabled = false,
  size,
  emptyLabel = 'No languages selected',
  single = false,
}) => {
  const normalized = normalizeLanguageCodes(value);
  const [opened, setOpened] = useState(false);
  const [query, setQuery] = useState('');
  const [pending, setPending] = useState([]);
  const options = useMemo(
    () =>
      LANGUAGE_OPTIONS.filter((option) =>
        option.label.toLowerCase().includes(query.trim().toLowerCase())
      ),
    [query]
  );

  const openPicker = () => {
    setPending(normalized);
    setQuery('');
    setOpened(true);
  };

  const toggle = (code) =>
    setPending((current) => {
      if (current.includes(code)) {
        return current.filter((item) => item !== code);
      }
      return single ? [code] : [...current, code];
    });

  const apply = () => {
    const next = normalizeLanguageCodes(pending);
    onChange?.(single ? next[0] || '' : next);
    setOpened(false);
  };

  const remove = (code) => {
    const next = normalized.filter((current) => current !== code);
    onChange?.(single ? next[0] || '' : next);
  };

  return (
    <Stack gap={5}>
      {label && (
        <Text component="label" size={size === 'xs' ? 'xs' : 'sm'} fw={500}>
          {label}
        </Text>
      )}
      <div
        style={{
          minHeight: size === 'xs' ? 30 : 36,
          border: '1px solid var(--mantine-color-default-border)',
          borderRadius: 'var(--mantine-radius-default)',
          background: 'var(--mantine-color-default)',
          display: 'flex',
          alignItems: 'center',
          overflow: 'hidden',
        }}
      >
        <Group gap={5} px="xs" py={3} style={{ flex: 1, minWidth: 0 }}>
          {normalized.length ? (
            normalized.map((code) => (
              <Button
                key={code}
                aria-label={`Remove ${code}`}
                variant="light"
                color="gray"
                size="compact-xs"
                disabled={disabled}
                onClick={() => remove(code)}
              >
                {labelForCode(code)} ×
              </Button>
            ))
          ) : (
            <Text size={size === 'xs' ? 'xs' : 'sm'} c="dimmed">
              {emptyLabel}
            </Text>
          )}
        </Group>
        <Button
          aria-label={label ? `Add ${label} language` : 'Add language'}
          disabled={disabled}
          size="compact-xs"
          px={7}
          m={2}
          variant="subtle"
          onClick={openPicker}
        >
          <Plus size={15} />
        </Button>
      </div>

      <Modal
        opened={opened}
        onClose={() => setOpened(false)}
        title={label || 'Select languages'}
        size="md"
      >
        <Stack>
          <TextInput
            aria-label="Search languages"
            placeholder="Search by code or language name"
            value={query}
            onChange={(event) => setQuery(event.currentTarget.value)}
          />
          <ScrollArea h={360} type="auto">
            <Stack gap={2}>
              {options.map((option) => (
                <Checkbox
                  key={option.value}
                  label={option.label}
                  checked={pending.includes(option.value)}
                  onChange={() => toggle(option.value)}
                  py={5}
                />
              ))}
            </Stack>
          </ScrollArea>
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setOpened(false)}>
              Cancel
            </Button>
            <Button onClick={apply}>Apply</Button>
          </Group>
        </Stack>
      </Modal>
    </Stack>
  );
};

export const LanguageSelect = ({
  value,
  onChange,
  label,
  placeholder = 'Any',
  disabled = false,
  size,
  w,
  miw,
  style,
}) => (
  <div style={{ width: w, minWidth: miw, ...style }}>
    <LanguagePicker
      label={label}
      value={value ? [value] : []}
      onChange={onChange}
      disabled={disabled}
      size={size}
      emptyLabel={placeholder}
      single
    />
  </div>
);

export default LanguagePicker;
