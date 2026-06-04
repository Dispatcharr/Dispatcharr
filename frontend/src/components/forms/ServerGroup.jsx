import React, { useEffect, useMemo } from 'react';
import { useForm } from 'react-hook-form';
import { yupResolver } from '@hookform/resolvers/yup';
import * as Yup from 'yup';
import API from '../../api';
import { Button, Flex, Modal, NumberInput, TextInput } from '@mantine/core';

const schema = Yup.object({
  name: Yup.string().required('Name is required'),
  max_streams: Yup.number()
    .min(0, 'Must be 0 or greater')
    .required('Max streams is required'),
});

const ServerGroupForm = ({ serverGroup = null, isOpen, onClose }) => {
  const defaultValues = useMemo(
    () => ({
      name: serverGroup?.name || '',
      max_streams: serverGroup?.max_streams ?? 0,
    }),
    [serverGroup]
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
    const payload = {
      ...values,
      max_streams: Number(values.max_streams),
    };

    if (serverGroup?.id) {
      await API.updateServerGroup({ id: serverGroup.id, ...payload });
    } else {
      await API.addServerGroup(payload);
    }

    reset();
    onClose();
  };

  useEffect(() => {
    reset(defaultValues);
  }, [defaultValues, reset]);

  if (!isOpen) {
    return null;
  }

  const maxStreams = watch('max_streams');

  return (
    <Modal opened={isOpen} onClose={onClose} title="Server Group">
      <form onSubmit={handleSubmit(onSubmit)}>
        <TextInput
          label="Name"
          {...register('name')}
          error={errors.name?.message}
        />

        <NumberInput
          label="Max Streams"
          description="Set above 0 to enable shared login pooling. Per-login limits use each account profile's max streams. Unlimited profiles (0) skip cross-account enforcement."
          min={0}
          value={maxStreams}
          onChange={(value) => setValue('max_streams', value ?? 0)}
          error={errors.max_streams?.message}
        />

        <Flex mih={50} gap="xs" justify="flex-end" align="flex-end">
          <Button size="small" type="submit" disabled={isSubmitting}>
            Submit
          </Button>
        </Flex>
      </form>
    </Modal>
  );
};

export default ServerGroupForm;
