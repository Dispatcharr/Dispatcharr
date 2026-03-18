import { NETWORK_ACCESS_OPTIONS } from '../../../constants.js';
import { IPV4_CIDR_REGEX, IPV6_CIDR_REGEX } from '../../networkUtils.js';

// Default CIDR ranges for M3U/EPG endpoints (local networks only)
const M3U_EPG_DEFAULTS =
  '127.0.0.0/8,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,::1/128,fc00::/7,fe80::/10';

export const getNetworkAccessFormInitialValues = () => {
  return Object.keys(NETWORK_ACCESS_OPTIONS).reduce((acc, key) => {
    // M3U/EPG endpoints default to local networks only
    acc[key] = key === 'M3U_EPG' ? M3U_EPG_DEFAULTS : '0.0.0.0/0,::/0';
    return acc;
  }, {});
};

export const getNetworkAccessFormValidation = () => {
  return Object.keys(NETWORK_ACCESS_OPTIONS).reduce((acc, key) => {
    acc[key] = (value) => {
      if (
        value
          .split(',')
          .some(
            (cidr) =>
              !(cidr.match(IPV4_CIDR_REGEX) || cidr.match(IPV6_CIDR_REGEX))
          )
      ) {
        return 'Invalid CIDR range';
      }

      return null;
    };
    return acc;
  }, {});
};

export const getNetworkAccessDefaults = () => {
  return {
    M3U_EPG: M3U_EPG_DEFAULTS,
    STREAMS: '0.0.0.0/0,::/0',
    XC_API: '0.0.0.0/0,::/0',
    UI: '0.0.0.0/0,::/0',
  };
};
