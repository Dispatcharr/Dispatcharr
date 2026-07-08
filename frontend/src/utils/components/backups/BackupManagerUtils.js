// Convert 24h time string to 12h format with period
import API from '../../../api.js';

export function to12Hour(time24) {
  if (!time24) return { time: '12:00', period: 'AM' };
  const [hours, minutes] = time24.split(':').map(Number);
  const period = hours >= 12 ? 'PM' : 'AM';
  const hours12 = hours % 12 || 12;
  return {
    time: `${hours12}:${String(minutes).padStart(2, '0')}`,
    period,
  };
}

// Convert 12h time + period to 24h format
export function to24Hour(time12, period) {
  if (!time12) return '00:00';
  const [hours, minutes] = time12.split(':').map(Number);
  let hours24 = hours;
  if (period === 'PM' && hours !== 12) {
    hours24 = hours + 12;
  } else if (period === 'AM' && hours === 12) {
    hours24 = 0;
  }
  return `${String(hours24).padStart(2, '0')}:${String(minutes).padStart(2, '0')}`;
}

export const DAYS_OF_WEEK = [
  { value: '0', label: 'Sunday' },
  { value: '1', label: 'Monday' },
  { value: '2', label: 'Tuesday' },
  { value: '3', label: 'Wednesday' },
  { value: '4', label: 'Thursday' },
  { value: '5', label: 'Friday' },
  { value: '6', label: 'Saturday' },
];

export const listBackups = () => {
  return API.listBackups();
};
export const getBackupSchedule = () => {
  return API.getBackupSchedule();
};
export const updateBackupSchedule = (settings) => {
  return API.updateBackupSchedule(settings);
};
export const createBackup = () => {
  return API.createBackup();
};
export const uploadBackup = (file) => {
  return API.uploadBackup(file);
};
export const downloadBackup = (filename) => {
  return API.downloadBackup(filename);
};
export const restoreBackup = (filename, onProgress) => {
  return API.restoreBackup(filename, onProgress);
};
export const deleteBackup = (filename) => {
  return API.deleteBackup(filename);
};
