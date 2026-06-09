import { yupResolver } from '@hookform/resolvers/yup';
import API from '../../api.js';
import * as Yup from 'yup';

const schema = Yup.object({
  name: Yup.string().required('Name is required'),
  user_agent: Yup.string().required('User-Agent is required'),
});
export const getResolver = () => {
  return yupResolver(schema);
};
export const updateUserAgent = (userAgentId, values) => {
  return API.updateUserAgent({ id: userAgentId, ...values });
};
export const addUserAgent = (values) => {
  return API.addUserAgent(values);
};
