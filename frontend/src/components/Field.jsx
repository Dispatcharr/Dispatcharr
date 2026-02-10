import {
  NumberInput,
  Select,
  Switch,
  Text,
  Textarea,
  TextInput,
} from '@mantine/core';
import React from 'react';

export const Field = ({ field, value, onChange }) => {
  const description = field.help_text ?? field.description ?? field.value;
  const common = { label: field.label, description };
  const effective = value ?? field.default;
  switch (field.type) {
    case 'info':
      return (
        <div>
          {field.label && (
            <Text fw={600} size="sm">
              {field.label}
            </Text>
          )}
          {description && (
            <Text size="sm" c="dimmed">
              {description}
            </Text>
          )}
        </div>
      );
    case 'boolean':
      return (
        <Switch
          checked={!!effective}
          onChange={(e) => onChange(field.id, e.currentTarget.checked)}
          label={field.label}
          description={description}
        />
      );
    case 'number':
      return (
        <NumberInput
          value={value ?? field.default ?? 0}
          onChange={(v) => onChange(field.id, v)}
          placeholder={field.placeholder}
          {...common}
        />
      );
    case 'select':
      return (
        <Select
          value={(value ?? field.default ?? '') + ''}
          data={(field.options || []).map((o) => ({
            value: o.value + '',
            label: o.label,
          }))}
          onChange={(v) => onChange(field.id, v)}
          placeholder={field.placeholder}
          {...common}
        />
      );
    case 'text':
      return (
        <Textarea
          value={value ?? field.default ?? ''}
          onChange={(e) => onChange(field.id, e.currentTarget.value)}
          placeholder={field.placeholder}
          {...common}
        />
      );
    case 'string':
    default:
      return (
        <TextInput
          value={value ?? field.default ?? ''}
          onChange={(e) => onChange(field.id, e.currentTarget.value)}
          type={field.input_type === 'password' ? 'password' : 'text'}
          placeholder={field.placeholder}
          {...common}
        />
      );
  }
};
