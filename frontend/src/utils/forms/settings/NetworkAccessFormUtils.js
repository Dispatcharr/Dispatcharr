import { NETWORK_ACCESS_OPTIONS } from '../../../constants.js';
import { IPV4_CIDR_REGEX, IPV6_CIDR_REGEX } from '../../networkUtils.js';

export const getNetworkAccessFormInitialValues = () => {
  return Object.keys(NETWORK_ACCESS_OPTIONS).reduce((acc, key) => {
    acc[key] = '0.0.0.0/0,::/0';
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