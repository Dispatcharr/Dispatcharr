import { useEffect, useMemo, useRef, useState } from 'react';
import {
  ActionIcon,
  Badge,
  Button,
  Group,
  Paper,
  Pill,
  PillsInput,
  Select,
  Stack,
  Table,
  Text,
  TextInput,
  Tooltip,
} from '@mantine/core';
import { CircleHelp, Plus, Save, SquarePen, Trash2, X } from 'lucide-react';
import ConfirmationDialog from '../../ConfirmationDialog.jsx';
import CleanupPreview from './CleanupPreview.jsx';
import classes from '../../LibraryWorkspace.module.css';

const TABLES = [
  {
    field: 'year_rules',
    title: 'Release-year formats',
    noun: 'year format',
    inputLabel: 'Year format',
    addLabel: 'Add format',
    emptyLabel: 'No year formats configured',
    description:
      'YYYY marks the year. Formats are tested in order; the provider title is kept unchanged.',
  },
];
const LITERAL_FIELDS = [
  {
    field: 'title_rules',
    title: 'Title prefixes',
    noun: 'prefix',
    input: 'New title prefix',
    placeholder: 'Enter a prefix and press Enter',
    description:
      'Literal prefixes are removed first, before other text, year and category cleanup.',
  },
  {
    field: 'removal_rules',
    title: 'Text anywhere',
    noun: 'text removal',
    input: 'New text to remove',
    placeholder: 'e.g. (ES) — press Enter',
    description:
      'Remove this exact text wherever it occurs, before year and category cleanup. These entries are not regular expressions.',
  },
];

const normalizedValue = (field, value) =>
  field === 'year_rules' ? value.replaceAll('{year}', 'YYYY').trim() : value;

function validationError(edit) {
  const row = edit.rows[edit.index];
  const value = normalizedValue(edit.field, row.value);
  if (!value.trim()) return 'Enter a value.';
  if (value.length > (edit.field === 'year_rules' ? 80 : 255))
    return 'This value is too long.';
  if (edit.field === 'year_rules' && value.split('YYYY').length !== 2)
    return 'Include YYYY exactly once.';
  if (
    edit.rows.some(
      (other, index) =>
        index !== edit.index &&
        normalizedValue(edit.field, other.value) === value
    )
  )
    return edit.field === 'year_rules'
      ? 'This year format already exists.'
      : 'This prefix already exists.';
  return null;
}

export default function CleanupRulesEditor({
  settings,
  busy,
  onSave,
  onDirtyChange,
  onResetFeedback,
  showPreview = true,
  onPreviewChange,
}) {
  const [edit, setEdit] = useState(null);
  const [validate, setValidate] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [literalInputs, setLiteralInputs] = useState({
    title_rules: '',
    removal_rules: '',
  });
  const [literalErrors, setLiteralErrors] = useState({});
  const input = useRef(null);
  const savingLiteral = useRef(false);
  const literalDirty = Object.values(literalInputs).some((value) =>
    value.trim()
  );
  const dirty =
    literalDirty ||
    (!!edit &&
      (edit.isNew ||
        JSON.stringify(edit.rows) !== JSON.stringify(edit.original)));
  const locked = busy || !!edit || !!deleteTarget || literalDirty;
  const literalLocked = (field) =>
    busy ||
    !!deleteTarget ||
    !!edit ||
    Object.entries(literalInputs).some(
      ([key, value]) => key !== field && value.trim()
    );
  const previewSettings = useMemo(
    () => ({
      ...settings,
      ...(edit && !validationError(edit) ? { [edit.field]: edit.rows } : {}),
    }),
    [settings, edit]
  );
  useEffect(() => {
    onPreviewChange?.(previewSettings);
  }, [previewSettings, onPreviewChange]);

  useEffect(() => {
    onDirtyChange(dirty);
  }, [dirty, onDirtyChange]);
  useEffect(() => () => onDirtyChange(false), [onDirtyChange]);
  useEffect(() => {
    input.current?.focus();
  }, [edit?.field, edit?.index]);

  const start = (field, index = null) => {
    if (locked || (index === null && settings[field].length >= 20)) return;
    const rows = settings[field].map((row) => ({ ...row }));
    const original = rows.map((row) => ({ ...row }));
    const isNew = index === null;
    if (isNew) {
      index = rows.length;
      rows.push({
        value: '',
        ...(field === 'year_rules' ? { position: 'end' } : {}),
        enabled: true,
      });
    }
    onResetFeedback();
    setValidate(false);
    setEdit({ field, index, rows, original, isNew });
  };
  const update = (patch) => {
    if (busy || !edit) return;
    setEdit((current) => ({
      ...current,
      rows: current.rows.map((row, index) =>
        index === current.index ? { ...row, ...patch } : row
      ),
    }));
  };
  const discard = () => {
    if (busy) return;
    setEdit(null);
    setValidate(false);
    setLiteralInputs({ title_rules: '', removal_rules: '' });
    setLiteralErrors({});
    onResetFeedback();
  };
  const save = async () => {
    if (busy || !edit || !dirty) return;
    setValidate(true);
    if (validationError(edit)) return;
    const rows = edit.rows.map((row, index) =>
      index === edit.index
        ? { ...row, value: normalizedValue(edit.field, row.value) }
        : row
    );
    if (await onSave({ [edit.field]: rows })) {
      setEdit(null);
      setValidate(false);
    }
  };
  const appendLiteral = async ({ field, noun }) => {
    const value = literalInputs[field];
    const rows = settings[field] || [];
    const error = (message) =>
      setLiteralErrors((current) => ({ ...current, [field]: message }));
    if (literalLocked(field) || savingLiteral.current || !value.trim()) return;
    if (rows.some((row) => row.value === value)) {
      error(`This ${noun} already exists.`);
      return;
    }
    if (rows.length >= 20) {
      error('Use no more than 20 entries.');
      return;
    }
    savingLiteral.current = true;
    onResetFeedback();
    error('');
    try {
      if (
        await onSave({
          [field]: [...rows, { value, enabled: true }],
        })
      )
        setLiteralInputs((current) => ({ ...current, [field]: '' }));
    } finally {
      savingLiteral.current = false;
    }
  };
  const removeLiteral = async (field, index) => {
    if (literalLocked(field) || savingLiteral.current) return;
    savingLiteral.current = true;
    onResetFeedback();
    setLiteralErrors({});
    try {
      await onSave({
        [field]: (settings[field] || []).filter(
          (_, position) => position !== index
        ),
      });
    } finally {
      savingLiteral.current = false;
    }
  };
  const remove = async () => {
    if (busy || edit || !deleteTarget) return;
    const { field, index } = deleteTarget;
    await onSave({
      [field]: settings[field].filter((_, rowIndex) => rowIndex !== index),
    });
    setDeleteTarget(null);
  };
  const icon = (
    label,
    Icon,
    action,
    disabled,
    color = 'gray',
    loading = false
  ) => (
    <Tooltip label={label}>
      <ActionIcon
        type="button"
        aria-label={label}
        variant="subtle"
        color={color}
        onClick={action}
        disabled={disabled}
        loading={loading}
      >
        <Icon size={16} />
      </ActionIcon>
    </Tooltip>
  );

  return (
    <Stack gap="md">
      {LITERAL_FIELDS.map((config) => (
        <Paper withBorder p="md" key={config.field}>
          <Stack gap="sm">
            <Group justify="space-between">
              <Group gap={0}>
                <Text fw={600}>{config.title}</Text>
                <Tooltip label={config.description} multiline maw={320}>
                  <ActionIcon
                    variant="subtle"
                    color="gray"
                    aria-label={`About ${config.title.toLowerCase()}`}
                  >
                    <CircleHelp size={16} />
                  </ActionIcon>
                </Tooltip>
              </Group>
            </Group>
            <PillsInput
              error={literalErrors[config.field] || null}
              disabled={literalLocked(config.field)}
            >
              <Pill.Group aria-label={config.title}>
                {(settings[config.field] || []).map((row, index) => (
                  <Tooltip
                    key={`${index}-${row.value}`}
                    label={row.enabled === false ? 'Disabled entry' : row.value}
                  >
                    <Pill
                      withRemoveButton
                      disabled={literalLocked(config.field)}
                      removeButtonProps={{
                        'aria-label': `Remove ${config.noun} ${index + 1}`,
                        'aria-hidden': false,
                        tabIndex: 0,
                        disabled: literalLocked(config.field),
                      }}
                      onRemove={() => removeLiteral(config.field, index)}
                      style={{
                        whiteSpace: 'pre',
                        opacity: row.enabled === false ? 0.5 : 1,
                      }}
                    >
                      {row.value}
                    </Pill>
                  </Tooltip>
                ))}
                <PillsInput.Field
                  aria-label={config.input}
                  placeholder={config.placeholder}
                  maxLength={255}
                  value={literalInputs[config.field]}
                  disabled={
                    literalLocked(config.field) ||
                    (settings[config.field] || []).length >= 20
                  }
                  onChange={(event) => {
                    const value = event.currentTarget.value;
                    setLiteralInputs((current) => ({
                      ...current,
                      [config.field]: value,
                    }));
                    setLiteralErrors({});
                    onResetFeedback();
                  }}
                  onKeyDown={(event) => {
                    if (
                      event.key === 'Enter' &&
                      !event.nativeEvent.isComposing
                    ) {
                      event.preventDefault();
                      appendLiteral(config);
                    }
                  }}
                />
              </Pill.Group>
            </PillsInput>
          </Stack>
        </Paper>
      ))}
      {TABLES.map((table) => {
        const rows =
          edit?.field === table.field ? edit.rows : settings[table.field];
        return (
          <Paper withBorder p="md" key={table.field}>
            <Stack gap="sm">
              <Group justify="space-between">
                <Group gap={0}>
                  <Text fw={600}>{table.title}</Text>
                  <Tooltip label={table.description}>
                    <ActionIcon
                      variant="subtle"
                      color="gray"
                      aria-label="About release-year formats"
                    >
                      <CircleHelp size={16} />
                    </ActionIcon>
                  </Tooltip>
                </Group>
                <Button
                  type="button"
                  size="compact-sm"
                  leftSection={<Plus size={14} />}
                  disabled={locked || rows.length >= 20}
                  onClick={() => start(table.field)}
                >
                  {table.addLabel}
                </Button>
              </Group>
              <div className={classes.tableFrame}>
                <Table.ScrollContainer minWidth={400}>
                  <Table
                    aria-label={table.title}
                    striped
                    className={classes.cleanupTable}
                  >
                    <colgroup>
                      <col />
                      <col style={{ width: 148 }} />
                      <col style={{ width: 80 }} />
                    </colgroup>
                    <Table.Thead>
                      <Table.Tr>
                        <Table.Th scope="col">Format</Table.Th>
                        <Table.Th scope="col">Position</Table.Th>
                        <Table.Th scope="col" className={classes.centeredCell}>
                          Actions
                        </Table.Th>
                      </Table.Tr>
                    </Table.Thead>
                    <Table.Tbody>
                      {!rows.length && (
                        <Table.Tr>
                          <Table.Td colSpan={3}>
                            <Text size="sm" c="dimmed" ta="center">
                              {table.emptyLabel}
                            </Text>
                          </Table.Td>
                        </Table.Tr>
                      )}
                      {rows.map((row, index) => {
                        const editing =
                          edit?.field === table.field && edit.index === index;
                        const rowLocked = busy || !editing;
                        const name = `${table.noun} ${index + 1}`;
                        return (
                          <Table.Tr
                            key={index}
                            data-editing={editing || undefined}
                            data-inactive={edit && !editing ? true : undefined}
                          >
                            <Table.Td>
                              <Group gap="xs" wrap="nowrap">
                                <TextInput
                                  ref={editing ? input : undefined}
                                  size="xs"
                                  aria-label={`${table.inputLabel} ${index + 1}`}
                                  value={row.value}
                                  maxLength={80}
                                  style={{ flex: 1, minWidth: 0 }}
                                  disabled={rowLocked}
                                  error={
                                    editing && validate
                                      ? validationError(edit)
                                      : null
                                  }
                                  onChange={(event) =>
                                    update({ value: event.currentTarget.value })
                                  }
                                  onKeyDown={(event) => {
                                    if (
                                      event.key === 'Enter' &&
                                      !event.nativeEvent.isComposing
                                    ) {
                                      event.preventDefault();
                                      save();
                                    }
                                  }}
                                />
                                {normalizedValue(table.field, row.value) ===
                                  'YYYY' && (
                                  <Tooltip
                                    label="Plain YYYY is removed only when the release year is known from provider data or title metadata. Unmarked numbers in titles are not used to guess the release year."
                                    multiline
                                    w={300}
                                    events={{
                                      hover: true,
                                      focus: true,
                                      touch: true,
                                    }}
                                  >
                                    <ActionIcon
                                      type="button"
                                      size="sm"
                                      variant="subtle"
                                      color="gray"
                                      aria-label="About plain YYYY year format"
                                    >
                                      <CircleHelp size={16} />
                                    </ActionIcon>
                                  </Tooltip>
                                )}
                                {row.enabled === false && (
                                  <Tooltip label="Previously disabled format. Delete and add it again to enable it.">
                                    <Badge color="gray">Disabled</Badge>
                                  </Tooltip>
                                )}
                              </Group>
                            </Table.Td>
                            <Table.Td>
                              <Select
                                size="xs"
                                aria-label={`Year position ${index + 1}`}
                                value={row.position}
                                data={[
                                  { value: 'end', label: 'At end' },
                                  { value: 'anywhere', label: 'Anywhere' },
                                ]}
                                allowDeselect={false}
                                disabled={rowLocked}
                                onChange={(value) =>
                                  update({ position: value })
                                }
                              />
                            </Table.Td>
                            <Table.Td>
                              <div className={classes.actions}>
                                {editing
                                  ? icon(
                                      `Save ${name}`,
                                      Save,
                                      save,
                                      busy || !dirty,
                                      'blue',
                                      busy
                                    )
                                  : icon(
                                      `Edit ${name}`,
                                      SquarePen,
                                      () => start(table.field, index),
                                      locked,
                                      'yellow'
                                    )}
                                {editing
                                  ? icon(
                                      `Discard ${name} changes`,
                                      X,
                                      discard,
                                      busy
                                    )
                                  : icon(
                                      `Delete ${name}`,
                                      Trash2,
                                      () =>
                                        setDeleteTarget({
                                          field: table.field,
                                          index,
                                          noun: table.noun,
                                        }),
                                      locked,
                                      'red'
                                    )}
                              </div>
                            </Table.Td>
                          </Table.Tr>
                        );
                      })}
                    </Table.Tbody>
                  </Table>
                </Table.ScrollContainer>
              </div>
            </Stack>
          </Paper>
        );
      })}
      {showPreview && <CleanupPreview settings={previewSettings} />}
      <ConfirmationDialog
        opened={!!deleteTarget}
        onClose={() => !busy && setDeleteTarget(null)}
        onConfirm={remove}
        loading={busy}
        title={`Delete ${deleteTarget?.noun || 'cleanup rule'}`}
        message="Delete this cleanup rule? Existing Library titles will not be changed."
        confirmLabel="Delete"
      />
    </Stack>
  );
}
