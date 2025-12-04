// Modal.js
import React, { useEffect } from 'react';
import { useFormik } from 'formik';
import * as Yup from 'yup';
import API from '../../api';
import useStreamProfilesStore from '../../store/streamProfiles';
import { Modal, TextInput, Select, Button, Flex } from '@mantine/core';
import useChannelsStore from '../../store/channels';

const Stream = ({ stream = null, isOpen, onClose }) => {
  const streamProfiles = useStreamProfilesStore((state) => state.profiles);
  const channelGroups = useChannelsStore((s) => s.channelGroups);

  const formik = useFormik({
    initialValues: {
      name: '',
      url: '',
      channel_group: null,
      stream_profile_id: '',
    },
    validationSchema: Yup.object({
      name: Yup.string().required('Name is required'),
      url: Yup.string().required('URL is required').min(0),
      // stream_profile_id: Yup.string().required('Stream profile is required'),
    }),
    onSubmit: async (values, { setSubmitting, resetForm }) => {
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

      resetForm();
      setSubmitting(false);
      onClose();
    },
  });

  useEffect(() => {
    if (stream) {
      formik.setValues({
        name: stream.name,
        url: stream.url,
        // Convert IDs to strings to match Select component values
        channel_group: stream.channel_group
          ? String(stream.channel_group)
          : null,
        stream_profile_id: stream.stream_profile_id
          ? String(stream.stream_profile_id)
          : '',
      });
    } else {
      formik.resetForm();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stream]);

  if (!isOpen) {
    return <></>;
  }

  return (
    <Modal opened={isOpen} onClose={onClose} title="Stream" zIndex={10}>
      <form onSubmit={formik.handleSubmit}>
        <TextInput
          id="name"
          name="name"
          label="Stream Name"
          value={formik.values.name}
          onChange={formik.handleChange}
          error={formik.errors.name}
        />

        <TextInput
          id="url"
          name="url"
          label="Stream URL"
          value={formik.values.url}
          onChange={formik.handleChange}
          error={formik.errors.url}
        />

        <Select
          id="channel_group"
          name="channel_group"
          label="Group"
          searchable
          value={formik.values.channel_group}
          onChange={(value) => {
            formik.setFieldValue('channel_group', value); // Update Formik's state with the new value
          }}
          error={formik.errors.channel_group}
          data={Object.values(channelGroups).map((group) => ({
            label: group.name,
            value: `${group.id}`,
          }))}
        />

        <Select
          id="stream_profile_id"
          name="stream_profile_id"
          label="Stream Profile"
          placeholder="Optional"
          searchable
          value={formik.values.stream_profile_id}
          onChange={(value) => {
            formik.setFieldValue('stream_profile_id', value); // Update Formik's state with the new value
          }}
          error={formik.errors.stream_profile_id}
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
            disabled={formik.isSubmitting}
          >
            Submit
          </Button>
        </Flex>
      </form>
    </Modal>
  );
};

export default Stream;
