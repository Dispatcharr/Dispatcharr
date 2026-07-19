import API from '../../api.js';

// Helper function to format status text
export const formatStatusText = (status) => {
  if (!status) return 'Unknown';
  return status.charAt(0).toUpperCase() + status.slice(1).toLowerCase();
};

export const updateEpg = async (values, epg, isToggle) => {
  return API.updateEPG({ ...values, id: epg.id }, isToggle);
};
export const deleteEpg = (id) => {
  return API.deleteEPG(id);
};
export const refreshEpg = (id, force = false) => {
  return API.refreshEPG(id, force);
};

export const getProgressLabel = (action) => {
  switch (action) {
    case 'downloading':
      return 'Downloading';
    case 'extracting':
      return 'Extracting';
    case 'parsing_channels':
      return 'Parsing Channels';
    case 'parsing_programs':
      return 'Parsing Programs';
    default:
      return null;
  }
};

export const getProgressInfo = (progress) => {
  // Build additional info string from progress data
  if (progress.message) {
    return progress.message;
  } else if (
    progress.processed !== undefined &&
    progress.channels !== undefined
  ) {
    return `${progress.processed.toLocaleString()} programs for ${progress.channels} channels`;
  } else if (progress.processed !== undefined && progress.total !== undefined) {
    return `${progress.processed.toLocaleString()} / ${progress.total.toLocaleString()}`;
  }
  return null;
};

export const getSortedEpgs = (epgs, compareColumn, compareDesc) => {
  return [...epgs].sort((a, b) => {
    if (a[compareColumn] < b[compareColumn]) return compareDesc ? 1 : -1;
    if (a[compareColumn] > b[compareColumn]) return compareDesc ? -1 : 1;
    return 0;
  });
};