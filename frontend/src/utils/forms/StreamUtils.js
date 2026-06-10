import * as Yup from 'yup';
import { yupResolver } from '@hookform/resolvers/yup';
import API from '../../api.js';

const schema = Yup.object({
  name: Yup.string().required('Name is required'),
  url: Yup.string().required('URL is required').min(0),
});

export const getResolver = () => {
  return yupResolver(schema);
};

export const updateStream = (streamId, payload) => {
  return API.updateStream({ id: streamId, ...payload });
};
export const addStream = (payload) => {
  return API.addStream(payload);
};
