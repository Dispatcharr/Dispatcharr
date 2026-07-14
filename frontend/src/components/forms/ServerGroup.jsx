import React, { useEffect, useMemo } from 'react';
import { useForm } from 'react-hook-form';
import { Button, Flex, Modal, TextInput } from '@mantine/core';
import {
  getResolver,
  updateServerGroup,
  addServerGroup,
} from '../../utils/forms/ServerGroupUtils';

const ServerGroupForm = ({ serverGroup = null, isOpen, onClose, onSaved }) => {
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
    resolver: getResolver(),
  });

  const onSubmit = async (values) => {
    const response = serverGroup?.id
      ? await updateServerGroup({ id: serverGroup.id, ...values })
      : await addServerGroup(values);

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
