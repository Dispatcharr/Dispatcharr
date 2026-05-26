// Modal.js
import React, { useEffect, useMemo } from 'react';
import { useForm } from 'react-hook-form';
import { Button, Checkbox, Flex, Modal, Space, TextInput } from '@mantine/core';
import {
  addUserAgent,
  getResolver,
  updateUserAgent,
} from '../../utils/forms/UserAgentUtils.js';

const UserAgent = ({ userAgent = null, isOpen, onClose }) => {
  const defaultValues = useMemo(
    () => ({
      name: userAgent?.name || '',
      user_agent: userAgent?.user_agent || '',
      description: userAgent?.description || '',
      is_active: userAgent?.is_active ?? true,
    }),
    [userAgent]
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

  const onSubmit = async (values) => {
    if (userAgent?.id) {
      await updateUserAgent(userAgent.id, values);
    } else {
      await addUserAgent(values);
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

  const isActive = watch('is_active');

  return (
    <Modal opened={isOpen} onClose={onClose} title="User-Agent">
      <form onSubmit={handleSubmit(onSubmit)}>
        <TextInput
          label="Name"
          {...register('name')}
          error={errors.name?.message}
        />

        <TextInput
          label="User-Agent"
          {...register('user_agent')}
          error={errors.user_agent?.message}
        />

        <TextInput
          label="Description"
          {...register('description')}
          error={errors.description?.message}
        />

        <Space h="md" />

        <Checkbox
          label="Is Active"
          checked={isActive}
          onChange={(e) => setValue('is_active', e.currentTarget.checked)}
        />

        <Flex mih={50} gap="xs" justify="flex-end" align="flex-end">
          <Button
            size="small"
            type="submit"
            variant="contained"
            disabled={isSubmitting}
          >
            Submit
          </Button>
        </Flex>
      </form>
    </Modal>
  );
};

export default UserAgent;
