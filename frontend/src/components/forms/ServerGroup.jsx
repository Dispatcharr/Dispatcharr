import React, { useEffect, useMemo } from 'react';
import { useForm } from 'react-hook-form';
import { yupResolver } from '@hookform/resolvers/yup';
import * as Yup from 'yup';
import API from '../../api';
import { Button, Flex, Modal, TextInput } from '@mantine/core';

const schema = Yup.object({
  name: Yup.string().required('Name is required'),
});

const ServerGroupForm = ({
  serverGroup = null,
  isOpen,
  onClose,
  onSaved,
}) => {
  const defaultValues = useMemo(
    () => ({
      name: serverGroup?.name || '',
    }),
    [serverGroup]
  );

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
    reset,
  } = useForm({
    defaultValues,
    resolver: yupResolver(schema),
  });

  const onSubmit = async (values) => {
    let response;
    if (serverGroup?.id) {
      response = await API.updateServerGroup({ id: serverGroup.id, ...values });
    } else {
      response = await API.addServerGroup(values);
    }

    if (response) {
      onSaved?.(response);
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

  return (
    <Modal
      opened={isOpen}
      onClose={onClose}
      title="Server Group"
      centered
      withinPortal
      zIndex={400}
    >
      <form onSubmit={handleSubmit(onSubmit)}>
        <TextInput
          label="Name"
          description="Accounts in this group share connection limits when they use the same provider login. Limits come from each account profile's max streams."
          {...register('name')}
          error={errors.name?.message}
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
