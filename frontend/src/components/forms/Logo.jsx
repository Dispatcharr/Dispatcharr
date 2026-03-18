import React, { useState, useEffect, useMemo } from 'react';
import { useForm } from 'react-hook-form';
import { yupResolver } from '@hookform/resolvers/yup';
import * as Yup from 'yup';
import {
  Modal,
  TextInput,
  Button,
  Group,
  Stack,
  Image,
  Text,
  Center,
  Box,
  Divider,
} from '@mantine/core';
import { Dropzone } from '@mantine/dropzone';
import { Upload, FileImage, X } from 'lucide-react';
import { notifications } from '@mantine/notifications';
import API from '../../api';

const schema = Yup.object({
  name: Yup.string().required('Name is required'),
  url: Yup.string()
    .required('URL is required')
    .test(
      'valid-url-or-path',
      'Must be a valid URL or local file path',
      (value) => {
        if (!value) return false;
        // Allow local file paths starting with /data/logos/
        if (value.startsWith('/data/logos/')) return true;
        // Allow valid URLs
        try {
          new URL(value);
          return true;
        } catch {
          return false;
        }
      }
    ),
});

const LogoForm = ({ logo = null, isOpen, onClose, onSuccess }) => {
  const [logoPreview, setLogoPreview] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [selectedFile, setSelectedFile] = useState(null); // Store selected file

  const defaultValues = useMemo(
    () => ({
      name: logo?.name || '',
      url: logo?.url || '',
    }),
    [logo]
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
    try {
      setUploading(true);
      let uploadResponse = null; // Store upload response for later use

      // If we have a selected file, upload it first
      if (selectedFile) {
        try {
          uploadResponse = await API.uploadLogo(selectedFile, values.name);
          // Use the uploaded file data instead of form values
          values.name = uploadResponse.name;
          values.url = uploadResponse.url;
        } catch (uploadError) {
          let errorMessage = 'Failed to upload logo file';

          if (
            uploadError.code === 'NETWORK_ERROR' ||
            uploadError.message?.includes('timeout')
          ) {
            errorMessage = 'Upload timed out. Please try again.';
          } else if (uploadError.status === 413) {
            errorMessage = 'File too large. Please choose a smaller file.';
          } else if (uploadError.body?.error) {
            errorMessage = uploadError.body.error;
          }

          notifications.show({
            title: 'Upload Error',
            message: errorMessage,
            color: 'red',
          });
          return; // Don't proceed with creation if upload fails
        }
      }

      // Now create or update the logo with the final values
      // Only proceed if we don't already have a logo from file upload
      if (logo) {
        const updatedLogo = await API.updateLogo(logo.id, values);
        notifications.show({
          title: 'Success',
          message: 'Logo updated successfully',
          color: 'green',
        });
        onSuccess?.({ type: 'update', logo: updatedLogo }); // Call onSuccess for updates
      } else if (!selectedFile) {
        // Only create a new logo entry if we're not uploading a file
        // (file upload already created the logo entry)
        const newLogo = await API.createLogo(values);
        notifications.show({
          title: 'Success',
          message: 'Logo created successfully',
          color: 'green',
        });
        onSuccess?.({ type: 'create', logo: newLogo }); // Call onSuccess for creates
      } else {
        // File was uploaded and logo was already created
        notifications.show({
          title: 'Success',
          message: 'Logo uploaded successfully',
          color: 'green',
        });
        onSuccess?.({ type: 'create', logo: uploadResponse });
      }
      onClose();
    } catch (error) {
      let errorMessage = logo
        ? 'Failed to update logo'
        : 'Failed to create logo';

      // Handle specific timeout errors
      if (
        error.code === 'NETWORK_ERROR' ||
        error.message?.includes('timeout')
      ) {
        errorMessage = 'Request timed out. Please try again.';
      } else if (error.response?.data?.error) {
        errorMessage = error.response.data.error;
      }

      notifications.show({
        title: 'Error',
        message: errorMessage,
        color: 'red',
      });
    } finally {
      setUploading(false);
    }
  };

  useEffect(() => {
    reset(defaultValues);
    setLogoPreview(logo?.cache_url || null);
    setSelectedFile(null);
  }, [defaultValues, logo, reset]);

  const handleFileSelect = (files) => {
    if (files.length === 0) return;

    const file = files[0];

    // Validate file size on frontend first
    if (file.size > 5 * 1024 * 1024) {
      // 5MB
      notifications.show({
        title: 'Error',
        message: 'File too large. Maximum size is 5MB.',
        color: 'red',
      });
      return;
    }

    // Store the file for later upload and create preview
    setSelectedFile(file);

    // Generate a local preview URL
    const previewUrl = URL.createObjectURL(file);
    setLogoPreview(previewUrl);

    // Auto-fill the name field if empty
    const currentName = watch('name');
    if (!currentName) {
      const nameWithoutExtension = file.name.replace(/\.[^/.]+$/, '');
      setValue('name', nameWithoutExtension);
    }

    // Set a placeholder URL (will be replaced after upload)
    setValue('url', 'file://pending-upload');
  };

  const handleUrlChange = (event) => {
    const url = event.target.value;
    setValue('url', url);

    // Clear any selected file when manually entering URL
    if (selectedFile) {
      setSelectedFile(null);
      // Revoke the object URL to free memory
      if (logoPreview && logoPreview.startsWith('blob:')) {
        URL.revokeObjectURL(logoPreview);
      }
    }

    // Update preview for remote URLs
    if (url && url.startsWith('http')) {
      setLogoPreview(url);
    } else if (!url) {
      setLogoPreview(null);
    }
  };

  const handleUrlBlur = (event) => {
    const urlValue = event.target.value;
    if (urlValue) {
      try {
        const url = new URL(urlValue);
        const pathname = url.pathname;
        const filename = pathname.substring(pathname.lastIndexOf('/') + 1);
        const nameWithoutExtension = filename.replace(/\.[^/.]+$/, '');
        if (nameWithoutExtension) {
          setValue('name', nameWithoutExtension);
        }
      } catch (error) {
        // If the URL is invalid, do nothing.
        // The validation schema will catch this.
      }
    }
  };

  // Clean up object URLs when component unmounts or preview changes
  useEffect(() => {
    return () => {
      if (logoPreview && logoPreview.startsWith('blob:')) {
        URL.revokeObjectURL(logoPreview);
      }
    };
  }, [logoPreview]);

  return (
    <Modal
      opened={isOpen}
      onClose={onClose}
      title={logo ? 'Edit Logo' : 'Add Logo'}
      size="md"
    >
      <form onSubmit={handleSubmit(onSubmit)}>
        <Stack spacing="md">
          {/* Logo Preview */}
          {logoPreview && (
            <Center>
              <Box>
                <Text size="sm" color="dimmed" mb="xs" ta="center">
                  Preview
                </Text>
                <Image
                  src={logoPreview}
                  alt="Logo preview"
                  width={100}
                  height={75}
                  fit="contain"
                  fallbackSrc="/logo.png"
                  style={{
                    transition: 'transform 0.3s ease',
                    cursor: 'pointer',
                    ':hover': {
                      transform: 'scale(1.5)',
                    },
                  }}
                  onMouseEnter={(e) => {
                    e.target.style.transform = 'scale(1.5)';
                  }}
                  onMouseLeave={(e) => {
                    e.target.style.transform = 'scale(1)';
                  }}
                />
              </Box>
            </Center>
          )}

          {/* File Upload */}
          <Box>
            <Text size="sm" fw={500} mb="xs">
              Upload Logo File
            </Text>
            <Dropzone
              onDrop={handleFileSelect}
              loading={uploading}
              accept={{
                'image/*': [
                  '.png',
                  '.jpg',
                  '.jpeg',
                  '.gif',
                  '.webp',
                  '.bmp',
                  '.svg',
                ],
              }}
              multiple={false}
              maxSize={5 * 1024 * 1024} // 5MB limit
            >
              <Group
                justify="center"
                gap="xl"
                mih={120}
                style={{ pointerEvents: 'none' }}
              >
                <Dropzone.Accept>
                  <Upload size={50} color="green" />
                </Dropzone.Accept>
                <Dropzone.Reject>
                  <X size={50} color="red" />
                </Dropzone.Reject>
                <Dropzone.Idle>
                  <FileImage size={50} />
                </Dropzone.Idle>

                <div>
                  <Text size="xl" inline>
                    {selectedFile
                      ? `Selected: ${selectedFile.name}`
                      : 'Drag image here or click to select'}
                  </Text>
                  <Text size="sm" color="dimmed" inline mt={7}>
                    {selectedFile
                      ? 'File will be uploaded when you click Create/Update'
                      : 'Supports PNG, JPEG, GIF, WebP, SVG files'}
                  </Text>
                </div>
              </Group>
            </Dropzone>
          </Box>

          <Divider label="OR" labelPosition="center" />

          {/* Manual URL Input */}
          <TextInput
            label="Logo URL"
            placeholder="https://example.com/logo.png"
            {...register('url')}
            onChange={handleUrlChange}
            onBlur={handleUrlBlur}
            error={errors.url?.message}
            disabled={!!selectedFile} // Disable when file is selected
          />

          <TextInput
            label="Name"
            placeholder="Enter logo name"
            {...register('name')}
            error={errors.name?.message}
          />

          {selectedFile && (
            <Text size="sm" color="blue">
              Selected file: {selectedFile.name} - will be uploaded when you
              submit
            </Text>
          )}

          <Group justify="flex-end" mt="md">
            <Button variant="light" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" loading={isSubmitting || uploading}>
              {logo ? 'Update' : 'Create'}
            </Button>
          </Group>
        </Stack>
      </form>
    </Modal>
  );
};

export default LogoForm;
