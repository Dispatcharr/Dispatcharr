import React, { useEffect, useMemo } from 'react';
import { useForm } from 'react-hook-form';
import { yupResolver } from '@hookform/resolvers/yup';
import * as Yup from 'yup';
import useIPAliasesStore from '../../store/ipAliases';
import { TextInput, Button, Modal, Flex, Space } from '@mantine/core';

const schema = Yup.object({
  ip_address: Yup.string()
    .required('IP address is required')
    .matches(
      /^(\d{1,3}\.){3}\d{1,3}$|^([0-9a-fA-F]{0,4}:){2,7}[0-9a-fA-F]{0,4}$/,
      'Must be a valid IPv4 or IPv6 address'
    ),
  alias: Yup.string()
    .required('Alias is required')
    .max(100, 'Alias must be 100 characters or less'),
});

const IPAliasForm = ({ ipAlias = null, isOpen, onClose, defaultIp = '' }) => {
  const createAlias = useIPAliasesStore((s) => s.createAlias);
  const updateAlias = useIPAliasesStore((s) => s.updateAlias);

  const defaultValues = useMemo(
    () => ({
      ip_address: ipAlias?.ip_address || defaultIp || '',
      alias: ipAlias?.alias || '',
    }),
    [ipAlias, defaultIp]
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
    try {
      if (ipAlias?.id) {
        await updateAlias(ipAlias.id, values);
      } else {
        await createAlias(values);
      }
      reset();
      onClose();
    } catch {
      // Error notification handled by API layer
    }
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
      title={ipAlias?.id ? 'Edit IP Alias' : 'Add IP Alias'}
    >
      <form onSubmit={handleSubmit(onSubmit)}>
        <TextInput
          label="IP Address"
          placeholder="e.g. 192.168.1.100"
          {...register('ip_address')}
          error={errors.ip_address?.message}
          disabled={!!ipAlias?.id}
        />

        <Space h="sm" />

        <TextInput
          label="Alias"
          placeholder="e.g. Dad's House"
          {...register('alias')}
          error={errors.alias?.message}
        />

        <Flex mih={50} gap="xs" justify="flex-end" align="flex-end">
          <Button
            size="small"
            type="submit"
            variant="contained"
            disabled={isSubmitting}
          >
            {ipAlias?.id ? 'Update' : 'Add'}
          </Button>
        </Flex>
      </form>
    </Modal>
  );
};

export default IPAliasForm;
