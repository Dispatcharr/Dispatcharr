import React, { useState, useEffect } from 'react';
import { useFormik } from 'formik';
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

const BannerForm = ({ banner = null, isOpen, onClose, onSuccess }) => {
  const [bannerPreview, setBannerPreview] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [selectedFile, setSelectedFile] = useState(null); // Store selected file

  const formik = useFormik({
    initialValues: {
      name: '',
      url: '',
    },
    validationSchema: Yup.object({
      name: Yup.string().required('Name is required'),
      url: Yup.string()
        .required('URL is required')
        .test(
          'valid-url-or-path',
          'Must be a valid URL or local file path',
          (value) => {
            if (!value) return false;
            // Allow local file paths starting with /data/banners/
            if (value.startsWith('/data/banners/')) return true;
            // Allow valid URLs
            try {
              new URL(value);
              return true;
            } catch {
              return false;
            }
          }
        ),
    }),
    onSubmit: async (values, { setSubmitting }) => {
      try {
        setUploading(true);
        let uploadResponse = null; // Store upload response for later use

        // If we have a selected file, upload it first
        if (selectedFile) {
          try {
            uploadResponse = await API.uploadBanner(selectedFile, values.name);
            // Use the uploaded file data instead of form values
            values.name = uploadResponse.name;
            values.url = uploadResponse.url;
          } catch (uploadError) {
            let errorMessage = 'Failed to upload banner file';

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

        // Now create or update the banner with the final values
        // Only proceed if we don't already have a banner from file upload
        if (banner) {
          const updatedBanner = await API.updateBanner(banner.id, values);
          notifications.show({
            title: 'Success',
            message: 'Banner updated successfully',
            color: 'green',
          });
          onSuccess?.({ type: 'update', banner: updatedBanner }); // Call onSuccess for updates
        } else if (!selectedFile) {
          // Only create a new banner entry if we're not uploading a file
          // (file upload already created the banner entry)
          const newBanner = await API.createBanner(values);
          notifications.show({
            title: 'Success',
            message: 'Banner created successfully',
            color: 'green',
          });
          onSuccess?.({ type: 'create', banner: newBanner }); // Call onSuccess for creates
        } else {
          // File was uploaded and banner was already created
          notifications.show({
            title: 'Success',
            message: 'Banner uploaded successfully',
            color: 'green',
          });
          onSuccess?.({ type: 'create', banner: uploadResponse });
        }
        onClose();
      } catch (error) {
        let errorMessage = banner
          ? 'Failed to update banner'
          : 'Failed to create banner';

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
        setSubmitting(false);
        setUploading(false);
      }
    },
  });

  useEffect(() => {
    if (banner) {
      formik.setValues({
        name: banner.name || '',
        url: banner.url || '',
      });
      setBannerPreview(banner.cache_url);
    } else {
      formik.resetForm();
      setBannerPreview(null);
    }
    // Clear any selected file when banner changes
    setSelectedFile(null);
  }, [banner, isOpen]);

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
    setBannerPreview(previewUrl);

    // Auto-fill the name field if empty
    if (!formik.values.name) {
      const nameWithoutExtension = file.name.replace(/\.[^/.]+$/, '');
      formik.setFieldValue('name', nameWithoutExtension);
    }

    // Set a placeholder URL (will be replaced after upload)
    formik.setFieldValue('url', 'file://pending-upload');
  };

  const handleUrlChange = (event) => {
    const url = event.target.value;
    formik.setFieldValue('url', url);

    // Clear any selected file when manually entering URL
    if (selectedFile) {
      setSelectedFile(null);
      // Revoke the object URL to free memory
      if (bannerPreview && bannerPreview.startsWith('blob:')) {
        URL.revokeObjectURL(bannerPreview);
      }
    }

    // Update preview for remote URLs
    if (url && url.startsWith('http')) {
      setBannerPreview(url);
    } else if (!url) {
      setBannerPreview(null);
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
          formik.setFieldValue('name', nameWithoutExtension);
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
      if (bannerPreview && bannerPreview.startsWith('blob:')) {
        URL.revokeObjectURL(bannerPreview);
      }
    };
  }, [bannerPreview]);

  return (
    <Modal
      opened={isOpen}
      onClose={onClose}
      title={banner ? 'Edit Banner' : 'Add Banner'}
      size="md"
    >
      <form onSubmit={formik.handleSubmit}>
        <Stack spacing="md">
          {/* Banner Preview */}
          {bannerPreview && (
            <Center>
              <Box>
                <Text size="sm" color="dimmed" mb="xs" ta="center">
                  Preview
                </Text>
                <Image
                  src={bannerPreview}
                  alt="Banner preview"
                  width={200}
                  height={112}
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
              Upload Banner File
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
            label="Banner URL"
            placeholder="https://example.com/banner.png"
            {...formik.getFieldProps('url')}
            onChange={handleUrlChange}
            onBlur={handleUrlBlur}
            error={formik.touched.url && formik.errors.url}
            disabled={!!selectedFile} // Disable when file is selected
          />

          <TextInput
            label="Name"
            placeholder="Enter banner name"
            {...formik.getFieldProps('name')}
            error={formik.touched.name && formik.errors.name}
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
            <Button type="submit" loading={formik.isSubmitting || uploading}>
              {banner ? 'Update' : 'Create'}
            </Button>
          </Group>
        </Stack>
      </form>
    </Modal>
  );
};

export default BannerForm;