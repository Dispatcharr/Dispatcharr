import { NumberInput, Select, Switch, TextInput } from '@mantine/core';
import React from 'react';

export const Field = ({ field, value, onChange }) => {
  const common = { label: field.label, description: field.help_text };
  const effective = value ?? field.default;
  switch (field.type) {
    case 'boolean':
      return (
        <Switch
          checked={!!effective}
          onChange={(e) => onChange(field.id, e.currentTarget.checked)}
          label={field.label}
          description={field.help_text}
        />
      );
    case 'number':
      return (
        <NumberInput
          value={value ?? field.default ?? 0}
          onChange={(v) => onChange(field.id, v)}
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
          {...common}
        />
      );
    case 'string':
    default:
      return (
        <TextInput
          value={value ?? field.default ?? ''}
          onChange={(e) => onChange(field.id, e.currentTarget.value)}
          {...common}
        />
      );
  }
};