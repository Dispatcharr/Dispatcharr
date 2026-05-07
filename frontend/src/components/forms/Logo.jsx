import React, { useEffect, useMemo, useState } from 'react';
import { useForm } from 'react-hook-form';
import {
  Box,
  Button,
  Center,
  Divider,
  Group,
  Image,
  Modal,
  Stack,
  Text,
  TextInput,
} from '@mantine/core';
import {
  Dropzone,
  DropzoneAccept,
  DropzoneIdle,
  DropzoneReject,
} from '@mantine/dropzone';
import { FileImage, Upload, X } from 'lucide-react';
import { showNotification } from '../../utils/notificationUtils.js';
import {
  createLogo,
  getFilenameWithoutExtension,
  getResolver,
  getUpdateLogoErrorMessage,
  getUploadErrorMessage,
  releaseUrl,
  updateLogo,
  uploadLogo,
  validateFileSize,
} from '../../utils/forms/LogoUtils.js';

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
    resolver: getResolver(),
  });

  const onSubmit = async (values) => {
    try {
      setUploading(true);
      let uploadResponse = null; // Store upload response for later use

      // If we have a selected file, upload it first
      if (selectedFile) {
        try {
          uploadResponse = await uploadLogo(selectedFile, values);
          // Use the uploaded file data instead of form values
          values.name = uploadResponse.name;
          values.url = uploadResponse.url;
        } catch (uploadError) {
          showNotification({
            title: 'Upload Error',
            message: getUploadErrorMessage(uploadError),
            color: 'red',
          });
          return; // Don't proceed with creation if upload fails
        }
      }

      // Now create or update the logo with the final values
      // Only proceed if we don't already have a logo from file upload
      if (logo) {
        const updatedLogo = await updateLogo(logo, values);
        showNotification({
          title: 'Success',
          message: 'Logo updated successfully',
          color: 'green',
        });
        onSuccess?.({ type: 'update', logo: updatedLogo }); // Call onSuccess for updates
      } else if (!selectedFile) {
        // Only create a new logo entry if we're not uploading a file
        // (file upload already created the logo entry)
        const newLogo = await createLogo(values);
        showNotification({
          title: 'Success',
          message: 'Logo created successfully',
          color: 'green',
        });
        onSuccess?.({ type: 'create', logo: newLogo }); // Call onSuccess for creates
      } else {
        // File was uploaded and logo was already created
        showNotification({
          title: 'Success',
          message: 'Logo uploaded successfully',
          color: 'green',
        });
        onSuccess?.({ type: 'create', logo: uploadResponse });
      }
      onClose();
    } catch (error) {
      showNotification({
        title: 'Error',
        message: getUpdateLogoErrorMessage(logo, error),
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
    if (files.length === 0) {
      console.log('No files selected');
      return;
    }

    const file = files[0];

    // Validate file size on frontend first
    if (!validateFileSize(file)) {
      // 5MB
      showNotification({
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
      setValue('name', getFilenameWithoutExtension(file.name));
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
      releaseUrl(logoPreview);
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
        const nameWithoutExtension = getFilenameWithoutExtension(filename);
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
    return () => releaseUrl(logoPreview);
  }, [logoPreview]);

  return (
    <Modal
      opened={isOpen}
      onClose={onClose}
      title={logo ? 'Edit Logo' : 'Add Logo'}
      size="md"
      // Render above any other open modal (e.g. the per-group gear modal
      // in LiveGroupFilter) when this is invoked from one. Default Mantine
      // modal zIndex is 200; bumping to 1000 here keeps it on top.
      zIndex={1000}
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
                <DropzoneAccept>
                  <Upload size={50} color="green" />
                </DropzoneAccept>
                <DropzoneReject>
                  <X size={50} color="red" />
                </DropzoneReject>
                <DropzoneIdle>
                  <FileImage size={50} />
                </DropzoneIdle>

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
