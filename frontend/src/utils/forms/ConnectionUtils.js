import API from '../../api.js';
import { SUBSCRIPTION_EVENTS } from '../../constants.js';

export const EVENT_OPTIONS = Object.entries(SUBSCRIPTION_EVENTS).map(
  ([value, label]) => ({
    value,
    label,
  })
);

export const updateConnectIntegration = (connection, values, config) => {
  return API.updateConnectIntegration(connection.id, {
    name: values.name,
    type: values.type,
    config,
    enabled: values.enabled,
  });
};

export const createConnectIntegration = (values, config) => {
  return API.createConnectIntegration({
    name: values.name,
    type: values.type,
    config,
    enabled: values.enabled,
  });
};

export const setConnectSubscriptions = (connection, subs) => {
  return API.setConnectSubscriptions(connection.id, subs);
};

const buildWebhookConfig = (url, headers) => {
  const hdrs = {};
  headers.forEach((h) => {
    if (h.key && h.key.trim()) hdrs[h.key] = h.value;
  });
  const config = { url };
  if (Object.keys(hdrs).length) config.headers = hdrs;
  return config;
};

const buildScriptConfig = (scriptPath) => ({ path: scriptPath });

export const buildConfig = (values, headers) =>
  values.type === 'webhook'
    ? buildWebhookConfig(values.url, headers)
    : buildScriptConfig(values.script_path);

export const buildSubscriptions = (selectedEvents, payloadTemplates) =>
  Object.keys(SUBSCRIPTION_EVENTS).map((event) => ({
    event,
    enabled: selectedEvents.includes(event),
    payload_template: payloadTemplates[event] ?? null,
  }));

export const parseApiError = (error) => {
  const body = error?.body;

  if (!body || typeof body !== 'object') {
    return { fieldErrors: {}, apiError: error?.message ?? 'Unknown error' };
  }

  const knownFields = ['name', 'type'];
  const fieldErrors = Object.fromEntries(
    knownFields.filter((f) => body[f]).map((f) => [f, body[f]])
  );

  const nonField = body.non_field_errors ?? body.detail ?? null;
  const apiError =
    nonField ??
    (Object.keys(fieldErrors).length === 0 ? JSON.stringify(body) : '');

  return { fieldErrors, apiError };
};
