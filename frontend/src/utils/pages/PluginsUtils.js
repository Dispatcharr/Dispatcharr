import API from '../../api.js';

export const updatePluginSettings = async (key, settings) => {
  return await API.updatePluginSettings(key, settings);
};
export const runPluginAction = async (key, actionId) => {
  return await API.runPluginAction(key, actionId);
};
export const setPluginEnabled = async (key, next) => {
  return await API.setPluginEnabled(key, next);
};
export const importPlugin = async (importFile) => {
  return await API.importPlugin(importFile);
};
export const reloadPlugins = async () => {
  return await API.reloadPlugins();
};
export const deletePluginByKey = (key) => {
  return API.deletePlugin(key);
};
