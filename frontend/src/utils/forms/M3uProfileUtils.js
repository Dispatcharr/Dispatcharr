import API from '../../api.js';
import * as Yup from 'yup';

export const updateM3UProfile = async (m3u, submitValues) => {
  await API.updateM3UProfile(m3u.id, submitValues);
};

export const addM3UProfile = async (m3u, submitValues) => {
  await API.addM3UProfile(m3u.id, submitValues);
};

export const deleteM3UProfile = async (playlist, id) => {
  await API.deleteM3UProfile(playlist.id, id);
};

const queryStreams = async (params) => {
  return await API.queryStreams(params);
};

export const getDetectedMode = (storedMode, profile, m3u) => {
  if (storedMode) {
    return storedMode;
  } else if (
    profile?.search_pattern &&
    profile.search_pattern === `${m3u?.username}/${m3u?.password}`
  ) {
    return 'simple';
  } else if (profile?.search_pattern) {
    return 'advanced';
  }
  return 'simple';
};

export const applyRegex = (input, pattern, replacer) => {
  if (!pattern || !input) return input;
  try {
    const regex = new RegExp(pattern, 'g');
    return input.replace(regex, replacer);
  } catch {
    return input;
  }
};

export const buildProfileSchema = (isDefaultProfile, isXC) => {
  return Yup.object({
    name: Yup.string().required('Name is required'),
    search_pattern: Yup.string().when([], {
      is: () => !isDefaultProfile && !isXC,
      then: (schema) => schema.required('Search pattern is required'),
      otherwise: (schema) => schema.notRequired(),
    }),
    replace_pattern: Yup.string().when([], {
      is: () => !isDefaultProfile && !isXC,
      then: (schema) => schema.required('Replace pattern is required'),
      otherwise: (schema) => schema.notRequired(),
    }),
    notes: Yup.string(),
  });
};

export const fetchFirstStreamUrl = async (m3uId) => {
  const params = new URLSearchParams();
  params.append('page', 1);
  params.append('page_size', 1);
  params.append('m3u_account', m3uId);
  const response = await queryStreams(params);
  return response?.results?.[0]?.url ?? null;
};

export const validateXcSimple = (newUsername, newPassword) => {
  const errs = {};
  if (!newUsername.trim()) errs.newUsername = 'New username is required';
  if (!newPassword.trim()) errs.newPassword = 'New password is required';
  return errs;
};

export const prepareExpDate = (expDateValue, isXC) => {
  if (isXC) return undefined;
  if (expDateValue instanceof Date) return expDateValue.toISOString();
  return expDateValue || null;
};

export const applyXcSimplePatterns = (
  values,
  m3u,
  newUsername,
  newPassword
) => {
  return {
    ...values,
    search_pattern: `${m3u?.username || ''}/${m3u?.password || ''}`,
    replace_pattern: `${newUsername.trim()}/${newPassword.trim()}`,
  };
};

export const buildSubmitValues = (
  values,
  profile,
  isDefaultProfile,
  isXC,
  xcMode
) => {
  if (isDefaultProfile) {
    return {
      name: values.name,
      custom_properties: {
        ...(profile?.custom_properties || {}),
        notes: values.notes || '',
      },
    };
  }
  return {
    name: values.name,
    max_streams: values.max_streams,
    search_pattern: values.search_pattern,
    replace_pattern: values.replace_pattern,
    custom_properties: {
      ...(profile?.custom_properties || {}),
      notes: values.notes || '',
      ...(isXC ? { xcMode } : {}),
    },
  };
};
