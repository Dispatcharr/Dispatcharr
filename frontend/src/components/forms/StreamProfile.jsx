// StreamProfile form
import React, { useEffect, useMemo, useState } from 'react';
import { useForm } from 'react-hook-form';
import useUserAgentsStore from '../../store/userAgents';
import {
  Button,
  Checkbox,
  Flex,
  Modal,
  Select,
  Stack,
  Textarea,
  TextInput,
} from '@mantine/core';
import {
  addStreamProfile,
  BUILT_IN_COMMANDS,
  COMMAND_EXAMPLES,
  getResolver,
  toCommandSelection,
  updateStreamProfile,
} from '../../utils/forms/StreamProfileUtils.js';

const StreamProfile = ({ profile = null, isOpen, onClose }) => {
  const userAgents = useUserAgentsStore((state) => state.userAgents);

  // Separate state for the dropdown selection so 'Custom…' can be chosen
  // independently of the actual command string stored in the form.
  const [commandSelection, setCommandSelection] = useState('ffmpeg');

  const defaultValues = useMemo(
    () => ({
      name: profile?.name || '',
      command: profile?.command || '',
      parameters: profile?.parameters || '',
      is_active: profile?.is_active ?? true,
      user_agent: profile?.user_agent ? `${profile.user_agent}` : '',
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

  // Sync form + dropdown selection whenever the target profile or modal state changes
  useEffect(() => {
    reset(defaultValues);
    setCommandSelection(toCommandSelection(profile?.command || ''));
  }, [defaultValues, reset, profile]);

  const onSubmit = async (values) => {
    if (profile?.id) {
      await updateStreamProfile(profile.id, values);
    } else {
      await addStreamProfile(values);
    }

    reset();
    onClose();
  };

  if (!isOpen) {
    return <></>;
  }

  const isLocked = profile ? profile.locked : false;
  const isCustom = commandSelection === '__custom__';
  const userAgentValue = watch('user_agent');
  const isActiveValue = watch('is_active');

  const handleOnChangeCommand = (val) => {
    setCommandSelection(val);
    // For built-in selections, write the real command value immediately
    if (val !== '__custom__') {
      setValue('command', val, { shouldValidate: true });
    } else {
      // Clear so the user enters their own value
      setValue('command', '', { shouldValidate: false });
    }
  };

  return (
    <Modal opened={isOpen} onClose={onClose} title="Stream Profile">
      <form onSubmit={handleSubmit(onSubmit)}>
        <Stack gap="sm">
          <TextInput
            label="Name"
            description="A unique, descriptive label for this stream profile"
            disabled={isLocked}
            {...register('name')}
            error={errors.name?.message}
          />

          <Select
            label="Command"
            description={
              <>
                The executable used to process the stream.
                <br />
                Choose a built-in tool or select <em>Custom…</em> to enter any
                executable name or path.
              </>
            }
            data={BUILT_IN_COMMANDS}
            disabled={isLocked}
            value={commandSelection}
            onChange={handleOnChangeCommand}
            error={isCustom ? undefined : errors.command?.message}
          />

          {isCustom && (
            <TextInput
              label="Custom Command"
              description="Enter the executable name (e.g. ffmpeg) or full path (e.g. /usr/local/bin/mycmd)"
              disabled={isLocked}
              {...register('command')}
              error={errors.command?.message}
            />
          )}

          <Textarea
            label="Parameters"
            description={
              <>
                Command-line arguments passed to the command.
                <br />
                Use <strong>{'{streamUrl}'}</strong> and{' '}
                <strong>{'{userAgent}'}</strong> as placeholders — they are
                substituted at stream time.
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

          <Select
            label="User-Agent"
            description="Optional user-agent override. Falls back to the system default if not set."
            clearable
            data={userAgents.map((ua) => ({
              label: ua.name,
              value: `${ua.id}`,
            }))}
            value={userAgentValue}
            onChange={(val) => setValue('user_agent', val ?? '')}
            error={errors.user_agent?.message}
          />

          <Checkbox
            label="Is Active"
            description="Enable or disable this stream profile"
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

export default StreamProfile;
