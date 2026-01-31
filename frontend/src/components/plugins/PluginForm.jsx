import React, { useState, useCallback } from 'react';
import {
  Stack,
  TextInput,
  NumberInput,
  Textarea,
  Select,
  Checkbox,
  Switch,
  Button,
  Group,
} from '@mantine/core';
import { usePluginContext } from './PluginRenderer';

/**
 * PluginForm - Renders a form based on schema
 *
 * Supports field types: text, textarea, number, email, url, password,
 * select, checkbox, switch, date, datetime, time
 */
const PluginForm = ({
  id,
  fields = [],
  submit_action,
  submit_label = 'Submit',
  reset_on_submit = true,
  layout = 'vertical',
  initialValues = {},
}) => {
  const context = usePluginContext();

  // Initialize form values from defaults and initialValues
  const getInitialValues = useCallback(() => {
    const values = {};
    fields.forEach((field) => {
      values[field.id] = initialValues[field.id] ?? field.default ?? '';
    });
    return values;
  }, [fields, initialValues]);

  const [values, setValues] = useState(getInitialValues);
  const [errors, setErrors] = useState({});
  const [submitting, setSubmitting] = useState(false);

  // Handle field value change
  const handleChange = (fieldId, value) => {
    setValues((prev) => ({ ...prev, [fieldId]: value }));
    // Clear error when field changes
    if (errors[fieldId]) {
      setErrors((prev) => {
        const next = { ...prev };
        delete next[fieldId];
        return next;
      });
    }
  };

  // Validate form
  const validate = () => {
    const newErrors = {};

    fields.forEach((field) => {
      const value = values[field.id];

      // Required validation
      if (field.required && (value === '' || value === null || value === undefined)) {
        newErrors[field.id] = `${field.label} is required`;
        return;
      }

      // Min/max for numbers
      if (field.type === 'number' && value !== '' && value !== null) {
        if (field.min !== undefined && value < field.min) {
          newErrors[field.id] = `${field.label} must be at least ${field.min}`;
        }
        if (field.max !== undefined && value > field.max) {
          newErrors[field.id] = `${field.label} must be at most ${field.max}`;
        }
      }

      // Min/max length for text
      if ((field.type === 'text' || field.type === 'textarea') && value) {
        if (field.min_length && value.length < field.min_length) {
          newErrors[field.id] = `${field.label} must be at least ${field.min_length} characters`;
        }
        if (field.max_length && value.length > field.max_length) {
          newErrors[field.id] = `${field.label} must be at most ${field.max_length} characters`;
        }
      }

      // URL validation
      if (field.type === 'url' && value) {
        try {
          new URL(value);
        } catch {
          newErrors[field.id] = `${field.label} must be a valid URL`;
        }
      }

      // Email validation
      if (field.type === 'email' && value) {
        const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
        if (!emailRegex.test(value)) {
          newErrors[field.id] = `${field.label} must be a valid email`;
        }
      }
    });

    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  };

  // Handle form submit
  const handleSubmit = async (e) => {
    e.preventDefault();

    if (!validate()) {
      return;
    }

    if (!submit_action) {
      console.warn('Form has no submit_action defined');
      return;
    }

    setSubmitting(true);

    try {
      await context.runAction(submit_action, values);

      if (reset_on_submit) {
        setValues(getInitialValues());
      }
    } finally {
      setSubmitting(false);
    }
  };

  // Render a single field
  const renderField = (field) => {
    const commonProps = {
      key: field.id,
      label: field.label,
      description: field.help_text,
      placeholder: field.placeholder,
      required: field.required,
      disabled: field.disabled,
      error: errors[field.id],
    };

    switch (field.type) {
      case 'text':
      case 'string':
      case 'email':
      case 'url':
      case 'password':
        return (
          <TextInput
            {...commonProps}
            type={field.type === 'string' ? 'text' : field.type}
            value={values[field.id] || ''}
            onChange={(e) => handleChange(field.id, e.target.value)}
            maxLength={field.max_length}
          />
        );

      case 'textarea':
        return (
          <Textarea
            {...commonProps}
            value={values[field.id] || ''}
            onChange={(e) => handleChange(field.id, e.target.value)}
            minRows={field.rows || 3}
            maxLength={field.max_length}
          />
        );

      case 'number':
        return (
          <NumberInput
            {...commonProps}
            value={values[field.id] ?? ''}
            onChange={(value) => handleChange(field.id, value)}
            min={field.min}
            max={field.max}
            step={field.step}
          />
        );

      case 'select':
        return (
          <Select
            {...commonProps}
            data={field.options?.map((opt) =>
              typeof opt === 'string'
                ? { value: opt, label: opt }
                : { value: opt.value, label: opt.label }
            ) || []}
            value={values[field.id] || null}
            onChange={(value) => handleChange(field.id, value)}
            clearable={!field.required}
            searchable={field.searchable}
          />
        );

      case 'multi_select':
        return (
          <Select
            {...commonProps}
            multiple
            data={field.options?.map((opt) =>
              typeof opt === 'string'
                ? { value: opt, label: opt }
                : { value: opt.value, label: opt.label }
            ) || []}
            value={values[field.id] || []}
            onChange={(value) => handleChange(field.id, value)}
            clearable
            searchable={field.searchable}
          />
        );

      case 'checkbox':
        return (
          <Checkbox
            key={field.id}
            label={field.label}
            description={field.help_text}
            disabled={field.disabled}
            checked={!!values[field.id]}
            onChange={(e) => handleChange(field.id, e.target.checked)}
          />
        );

      case 'switch':
      case 'boolean':
        return (
          <Switch
            key={field.id}
            label={field.label}
            description={field.help_text}
            disabled={field.disabled}
            checked={!!values[field.id]}
            onChange={(e) => handleChange(field.id, e.target.checked)}
          />
        );

      case 'hidden':
        return null;

      default:
        // Default to text input
        return (
          <TextInput
            {...commonProps}
            value={values[field.id] || ''}
            onChange={(e) => handleChange(field.id, e.target.value)}
          />
        );
    }
  };

  return (
    <form onSubmit={handleSubmit}>
      <Stack gap="md">
        {fields.map((field) => {
          if (field.visible === false) return null;
          return renderField(field);
        })}

        <Group justify="flex-end" mt="md">
          <Button type="submit" loading={submitting}>
            {submit_label}
          </Button>
        </Group>
      </Stack>
    </form>
  );
};

export default PluginForm;
