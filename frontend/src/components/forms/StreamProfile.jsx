// StreamProfile form
import React, { useEffect, useMemo, useState } from 'react';
import { useForm } from 'react-hook-form';
import { yupResolver } from '@hookform/resolvers/yup';
import * as Yup from 'yup';
import API from '../../api';
import useUserAgentsStore from '../../store/userAgents';
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

// Built-in commands supported by Dispatcharr out of the box.
const BUILT_IN_COMMANDS = [
  { value: 'ffmpeg', label: 'FFmpeg' },
  { value: 'streamlink', label: 'Streamlink' },
  { value: 'cvlc', label: 'VLC' },
  { value: 'yt-dlp', label: 'yt-dlp' },
  { value: '__custom__', label: 'Custom…' },
];

// Default parameter examples for each built-in command.
const COMMAND_EXAMPLES = {
  ffmpeg: '-user_agent {userAgent} -i {streamUrl} -c copy -f mpegts pipe:1',
  streamlink: '{streamUrl} --http-header User-Agent={userAgent} best --stdout',
  cvlc: '-vv -I dummy --no-video-title-show --http-user-agent {userAgent} {streamUrl} --sout #standard{access=file,mux=ts,dst=-}',
  'yt-dlp': '--hls-use-mpegts -f best -o - {streamUrl}',
};

// Returns '__custom__' when the command isn't one of the built-ins,
// otherwise returns the command value itself.
const toCommandSelection = (command) =>
  BUILT_IN_COMMANDS.find((o) => o.value === command && o.value !== '__custom__')
    ? command
    : '__custom__';

const schema = Yup.object({
  name: Yup.string().required('Name is required'),
  command: Yup.string().required('Command is required'),
  parameters: Yup.string(),
});

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
    resolver: yupResolver(schema),
  });

  // Sync form + dropdown selection whenever the target profile or modal state changes
  useEffect(() => {
    reset(defaultValues);
    setCommandSelection(toCommandSelection(profile?.command || ''));
  }, [defaultValues, reset, profile]);

  const onSubmit = async (values) => {
    if (profile?.id) {
      await API.updateStreamProfile({ id: profile.id, ...values });
    } else {
      await API.addStreamProfile(values);
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
            onChange={(val) => {
              setCommandSelection(val);
              // For built-in selections, write the real command value immediately
              if (val !== '__custom__') {
                setValue('command', val, { shouldValidate: true });
              } else {
                // Clear so the user enters their own value
                setValue('command', '', { shouldValidate: false });
              }
            }}
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
