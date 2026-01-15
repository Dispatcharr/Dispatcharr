// Modal.js
import React, { useEffect, useMemo } from 'react';
import { useForm } from 'react-hook-form';
import { yupResolver } from '@hookform/resolvers/yup';
import * as Yup from 'yup';
import API from '../../api';
import useUserAgentsStore from '../../store/userAgents';
import { Modal, TextInput, Select, Button, Flex } from '@mantine/core';

const schema = Yup.object({
  name: Yup.string().required('Name is required'),
  command: Yup.string().required('Command is required'),
  parameters: Yup.string().required('Parameters are is required'),
});

const StreamProfile = ({ profile = null, isOpen, onClose }) => {
  const userAgents = useUserAgentsStore((state) => state.userAgents);

  const defaultValues = useMemo(
    () => ({
      name: profile?.name || '',
      command: profile?.command || '',
      parameters: profile?.parameters || '',
      is_active: profile?.is_active ?? true,
      user_agent: profile?.user_agent || '',
    }),
    [profile]
  );

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
    reset,
    watch,
  } = useForm({
    defaultValues,
    resolver: yupResolver(schema),
  });

  const onSubmit = async (values) => {
    if (profile?.id) {
      await API.updateStreamProfile({ id: profile.id, ...values });
    } else {
      await API.addStreamProfile(values);
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

  const userAgentValue = watch('user_agent');

  return (
    <Modal opened={isOpen} onClose={onClose} title="Stream Profile">
      <form onSubmit={handleSubmit(onSubmit)}>
        <TextInput
          label="Name"
          {...register('name')}
          error={errors.name?.message}
          disabled={profile ? profile.locked : false}
        />
        <TextInput
          label="Command"
          {...register('command')}
          error={errors.command?.message}
          disabled={profile ? profile.locked : false}
        />
        <TextInput
          label="Parameters"
          {...register('parameters')}
          error={errors.parameters?.message}
          disabled={profile ? profile.locked : false}
        />

        <Select
          label="User-Agent"
          {...register('user_agent')}
          value={userAgentValue}
          error={errors.user_agent?.message}
          data={userAgents.map((ua) => ({
            label: ua.name,
            value: `${ua.id}`,
          }))}
        />

        <Flex mih={50} gap="xs" justify="flex-end" align="flex-end">
          <Button
            type="submit"
            variant="contained"
            color="primary"
            disabled={isSubmitting}
            size="small"
          >
            Submit
          </Button>
        </Flex>
      </form>
    </Modal>
  );
};

export default StreamProfile;
