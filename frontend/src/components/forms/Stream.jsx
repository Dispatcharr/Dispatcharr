// Modal.js
import React, { useEffect, useMemo } from 'react';
import { useForm } from 'react-hook-form';
import { yupResolver } from '@hookform/resolvers/yup';
import * as Yup from 'yup';
import API from '../../api';
import useStreamProfilesStore from '../../store/streamProfiles';
import { Modal, TextInput, Select, Button, Flex } from '@mantine/core';
import useChannelsStore from '../../store/channels';

const schema = Yup.object({
  name: Yup.string().required('Name is required'),
  url: Yup.string().required('URL is required').min(0),
});

const Stream = ({ stream = null, isOpen, onClose }) => {
  const streamProfiles = useStreamProfilesStore((state) => state.profiles);
  const channelGroups = useChannelsStore((s) => s.channelGroups);

  const defaultValues = useMemo(
    () => ({
      name: stream?.name || '',
      url: stream?.url || '',
      channel_group: stream?.channel_group
        ? String(stream.channel_group)
        : null,
      stream_profile_id: stream?.stream_profile_id
        ? String(stream.stream_profile_id)
        : '',
    }),
    [stream]
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

  const onSubmit = async (values) => {
    console.log(values);

    // Convert string IDs back to integers for the API
    const payload = {
      ...values,
      channel_group: values.channel_group
        ? parseInt(values.channel_group, 10)
        : null,
      stream_profile_id: values.stream_profile_id
        ? parseInt(values.stream_profile_id, 10)
        : null,
    };

    if (stream?.id) {
      await API.updateStream({ id: stream.id, ...payload });
    } else {
      await API.addStream(payload);
    }

    reset();
    onClose();
  };

  useEffect(() => {
    reset(defaultValues);
  }, [defaultValues, reset]);

  if (!isOpen) {
    return <></>;
  }

  const channelGroupValue = watch('channel_group');
  const streamProfileValue = watch('stream_profile_id');

  return (
    <Modal opened={isOpen} onClose={onClose} title="Stream" zIndex={10}>
      <form onSubmit={handleSubmit(onSubmit)}>
        <TextInput
          label="Stream Name"
          {...register('name')}
          error={errors.name?.message}
        />

        <TextInput
          label="Stream URL"
          {...register('url')}
          error={errors.url?.message}
        />

        <Select
          label="Group"
          searchable
          value={channelGroupValue}
          onChange={(value) => setValue('channel_group', value)}
          error={errors.channel_group?.message}
          data={Object.values(channelGroups).map((group) => ({
            label: group.name,
            value: `${group.id}`,
          }))}
        />

        <Select
          label="Stream Profile"
          placeholder="Optional"
          searchable
          value={streamProfileValue}
          onChange={(value) => setValue('stream_profile_id', value)}
          error={errors.stream_profile_id?.message}
          data={streamProfiles.map((profile) => ({
            label: profile.name,
            value: `${profile.id}`,
          }))}
          comboboxProps={{ withinPortal: false, zIndex: 1000 }}
        />

        <Flex mih={50} gap="xs" justify="flex-end" align="flex-end">
          <Button
            type="submit"
            variant="contained"
            color="primary"
            disabled={isSubmitting}
          >
            Submit
          </Button>
        </Flex>
      </form>
    </Modal>
  );
};

export default Stream;
