import API from '../../api.js';
import { yupResolver } from '@hookform/resolvers/yup';
import * as Yup from 'yup';

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

export const uploadLogo = async (selectedFile, values) => {
  return await API.uploadLogo(selectedFile, values.name);
};

export const createLogo = async (values) => {
  return await API.createLogo(values);
};

export const updateLogo = async (logo, values) => {
  return await API.updateLogo(logo.id, values);
};

export const getResolver = () => {
  return yupResolver(schema);
};

export const getUploadErrorMessage = (uploadError) => {
  if (
    uploadError.code === 'NETWORK_ERROR' ||
    uploadError.message?.includes('timeout')
  ) {
    return 'Upload timed out. Please try again.';
  } else if (uploadError.status === 413) {
    return 'File too large. Please choose a smaller file.';
  } else if (uploadError.body?.error) {
    return uploadError.body.error;
  }
  return 'Failed to upload logo file';
};

export const getUpdateLogoErrorMessage = (logo, error) => {
  if (error.code === 'NETWORK_ERROR' || error.message?.includes('timeout')) {
    return 'Request timed out. Please try again.';
  } else if (error.response?.data?.error) {
    return error.response.data.error;
  }
  return logo ? 'Failed to update logo' : 'Failed to create logo';
};

export const validateFileSize = (file) => {
  return file.size <= 5 * 1024 * 1024;
};

export const releaseUrl = (url) => {
  if (url && url.startsWith('blob:')) {
    URL.revokeObjectURL(url);
  }
};

export const getFilenameWithoutExtension = (filename) => {
  return filename.replace(/\.[^/.]+$/, '');
};
