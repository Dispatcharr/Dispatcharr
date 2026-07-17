import { yupResolver } from '@hookform/resolvers/yup';
import * as Yup from 'yup';
import API from '../../api';

const schema = Yup.object({
  name: Yup.string().required('Name is required'),
});
export const getResolver = () => {
  return yupResolver(schema);
};
export const updateServerGroup = (values) => {
  return API.updateServerGroup(values);
};
export const addServerGroup = (values) => {
  return API.addServerGroup(values);
};
