import {NETWORK_ACCESS_OPTIONS, USER_LEVELS} from "../../constants.js";
import { IPV4_CIDR_REGEX, IPV6_CIDR_REGEX } from '../networkUtils.js';
import API from "../../api.js";

const isValidNetworkEntry = (entry) =>
  entry.match(IPV4_CIDR_REGEX) ||
  entry.match(IPV6_CIDR_REGEX) ||
  (entry + '/32').match(IPV4_CIDR_REGEX) ||
  (entry + '/128').match(IPV6_CIDR_REGEX);
const NETWORK_KEYS = Object.keys(NETWORK_ACCESS_OPTIONS);

export const createUser = (values) => {
  return API.createUser(values);
};

export const updateUser = (userId, values, isAdmin, authUser) => {
  return API.updateUser(
    userId,
    values,
    isAdmin ? false : authUser.id === userId
  );
};

export const generateApiKey = (payload) => {
  return API.generateApiKey(payload);
};

export const revokeApiKey = (payload) => {
  return API.revokeApiKey(payload);
};

export const userToFormValues = (user) => {
  const customProps = user.custom_properties || {};
  const networks = customProps.allowed_networks || {};

  return {
    username: user.username,
    first_name: user.first_name || '',
    last_name: user.last_name || '',
    email: user.email,
    user_level: `${user.user_level}`,
    stream_limit: user.stream_limit || 0,
    channel_profiles:
      user.channel_profiles.length > 0
        ? user.channel_profiles.map((id) => `${id}`)
        : ['0'],
    xc_password: customProps.xc_password || '',
    output_format: customProps.output_format || '',
    output_profile: customProps.output_profile
      ? `${customProps.output_profile}`
      : '',
    hide_adult_content: customProps.hide_adult_content || false,
    epg_days: customProps.epg_days || 0,
    epg_prev_days: customProps.epg_prev_days || 0,
    allowed_ips: [
      ...new Set(
        NETWORK_KEYS.flatMap((key) =>
          networks[key] ? networks[key].split(',').filter(Boolean) : []
        )
      ),
    ],
  };
};

export const formValuesToPayload = (values, existingUser) => {
  const customProps = { ...(existingUser?.custom_properties || {}) };
  const payload = { ...values };

  customProps.xc_password = payload.xc_password || '';
  delete payload.xc_password;

  customProps.output_format = payload.output_format || null;
  delete payload.output_format;

  customProps.output_profile = payload.output_profile
    ? parseInt(payload.output_profile, 10)
    : null;
  delete payload.output_profile;

  customProps.hide_adult_content = payload.hide_adult_content || false;
  delete payload.hide_adult_content;

  customProps.epg_days = payload.epg_days || 0;
  delete payload.epg_days;

  customProps.epg_prev_days = payload.epg_prev_days || 0;
  delete payload.epg_prev_days;

  const joined = (payload.allowed_ips || []).join(',');
  delete payload.allowed_ips;
  const allowed_networks = {};
  if (joined) {
    NETWORK_KEYS.forEach((key) => {
      allowed_networks[key] = joined;
    });
  }
  customProps.allowed_networks = allowed_networks;

  payload.custom_properties = customProps;

  if (payload.channel_profiles?.includes('0')) {
    payload.channel_profiles = [];
  }

  return payload;
};

export const getFormInitialValues = () => {
  return {
    username: '',
    first_name: '',
    last_name: '',
    email: '',
    user_level: '0',
    stream_limit: 0,
    password: '',
    xc_password: '',
    output_format: '',
    output_profile: '',
    channel_profiles: [],
    hide_adult_content: false,
    epg_days: 0,
    epg_prev_days: 0,
    allowed_ips: [],
  };
}

export const getFormValidators = (user) => {
  return (values) => ({
    username: !values.username
      ? 'Username is required'
      : values.user_level == USER_LEVELS.STREAMER &&
      !values.username.match(/^[a-z0-9]+$/i)
        ? 'Streamer username must be alphanumeric'
        : null,
    password:
      !user && !values.password && values.user_level != USER_LEVELS.STREAMER
        ? 'Password is required'
        : null,
    xc_password:
      values.xc_password && !values.xc_password.match(/^[a-z0-9]+$/i)
        ? 'XC password must be alphanumeric'
        : null,
    allowed_ips: (values.allowed_ips || []).some(
      (t) => !isValidNetworkEntry(t)
    )
      ? 'Invalid IP address or CIDR range'
      : null,
  });
}