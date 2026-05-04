import { NETWORK_ACCESS_OPTIONS } from '../../../constants.js';
import { IPV4_CIDR_REGEX, IPV6_CIDR_REGEX } from '../../networkUtils.js';

// Default CIDR ranges for M3U/EPG endpoints (local networks only)
const M3U_EPG_DEFAULTS = ['127.0.0.0/8', '10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16', '::1/128', 'fc00::/7', 'fe80::/10'];
const OPEN_DEFAULTS = ['0.0.0.0/0', '::/0'];

const isValidEntry = (entry) =>
  entry.match(IPV4_CIDR_REGEX) ||
  entry.match(IPV6_CIDR_REGEX) ||
  (entry + '/32').match(IPV4_CIDR_REGEX) ||
  (entry + '/128').match(IPV6_CIDR_REGEX);

export const getNetworkAccessFormInitialValues = () =>
  Object.keys(NETWORK_ACCESS_OPTIONS).reduce((acc, key) => {
    // M3U/EPG endpoints default to local networks only
    acc[key] = key === 'M3U_EPG' ? M3U_EPG_DEFAULTS : OPEN_DEFAULTS;
    return acc;
  }, {});

export const getNetworkAccessFormValidation = () =>
  Object.keys(NETWORK_ACCESS_OPTIONS).reduce((acc, key) => {
    acc[key] = (tags) => {
      if (!tags || tags.length === 0) return null;
      return tags.some((t) => !isValidEntry(t)) ? 'Invalid IP address or CIDR range' : null;
    };
    return acc;
  }, {});

export const getNetworkAccessDefaults = () => ({
  M3U_EPG: M3U_EPG_DEFAULTS,
  STREAMS: OPEN_DEFAULTS,
  XC_API: OPEN_DEFAULTS,
  UI: OPEN_DEFAULTS,
});
