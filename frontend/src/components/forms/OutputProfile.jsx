import React, { useEffect, useMemo, useState } from 'react';
import { useForm } from 'react-hook-form';
import {
  Modal,
  TextInput,
  Textarea,
  Select,
  Button,
  Flex,
  Stack,
  Checkbox,
} from '@mantine/core';
import {
  addOutputProfile,
  BUILT_IN_COMMANDS,
  COMMAND_EXAMPLES,
  getResolver,
  toCommandSelection,
  updateOutputProfile,
} from '../../utils/forms/OutputProfileUtils';

const OutputProfile = ({ profile = null, isOpen, onClose }) => {
  const [commandSelection, setCommandSelection] = useState('ffmpeg');

  const defaultValues = useMemo(
    () => ({
      name: profile?.name || '',
      command: profile?.command || 'ffmpeg',
      parameters: profile?.parameters || '',
      is_active: profile?.is_active ?? true,
    }),
    [profile]
  );

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
    reset,
    setValue,
    watch,
  } = useForm({
    defaultValues,
    resolver: getResolver(),
  });

  useEffect(() => {
    reset(defaultValues);
    setCommandSelection(toCommandSelection(profile?.command || 'ffmpeg'));
  }, [defaultValues, reset, profile]);

  const onSubmit = async (values) => {
    if (profile?.id) {
      await updateOutputProfile({ id: profile.id, ...values });
    } else {
      await addOutputProfile(values);
    }
    reset();
    onClose();
  };

  if (!isOpen) return <></>;

  const isLocked = profile ? profile.locked : false;
  const isCustom = commandSelection === '__custom__';
  const isActiveValue = watch('is_active');

  return (
    <Modal opened={isOpen} onClose={onClose} title="Output Profile">
      <form onSubmit={handleSubmit(onSubmit)}>
        <Stack gap="sm">
          <TextInput
            label="Name"
            description="A unique, descriptive label for this output profile"
            disabled={isLocked}
            {...register('name')}
            error={errors.name?.message}
          />

          <Select
            label="Command"
            description="The executable used to transcode the stream. Must accept stdin (pipe:0) and write to stdout (pipe:1)."
            data={BUILT_IN_COMMANDS}
            disabled={isLocked}
            value={commandSelection}
            onChange={(val) => {
              setCommandSelection(val);
              if (val !== '__custom__') {
                setValue('command', val, { shouldValidate: true });
              } else {
                setValue('command', '', { shouldValidate: false });
              }
            }}
            error={isCustom ? undefined : errors.command?.message}
          />

          {isCustom && (
            <TextInput
              label="Custom Command"
              description="Enter the executable name or full path"
              disabled={isLocked}
              {...register('command')}
              error={errors.command?.message}
            />
          )}

          <Textarea
            label="Parameters"
            description={
              <>
                Command-line arguments. Input is piped via{' '}
                <strong>pipe:0</strong> (stdin); output must be written to{' '}
                <strong>pipe:1</strong> (stdout). Output must be in{' '}
                <strong>MPEG-TS</strong> format (<code>-f mpegts</code>).
                {COMMAND_EXAMPLES[commandSelection] && (
                  <>
                    <br />
                    Example: <em>{COMMAND_EXAMPLES[commandSelection]}</em>
                  </>
                )}
              </>
            }
            autosize
            minRows={2}
            placeholder={
              COMMAND_EXAMPLES[commandSelection] ||
              'Enter command-line arguments…'
            }
            disabled={isLocked}
            {...register('parameters')}
            error={errors.parameters?.message}
          />

          <Checkbox
            label="Is Active"
            description="Enable or disable this output profile"
            checked={isActiveValue}
            onChange={(e) => setValue('is_active', e.currentTarget.checked)}
          />
        </Stack>

        <Flex mih={50} gap="xs" justify="flex-end" align="flex-end">
          <Button
            type="submit"
            variant="filled"
            disabled={isSubmitting}
            size="sm"
          >
            Save
          </Button>
        </Flex>
      </form>
    </Modal>
  );
};

export default OutputProfile;
