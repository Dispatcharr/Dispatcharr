import * as Yup from 'yup';
import API from '../../api';
import { yupResolver } from '@hookform/resolvers/yup';

export const BUILT_IN_COMMANDS = [
  { value: 'ffmpeg', label: 'FFmpeg' },
  { value: '__custom__', label: 'Custom…' },
];

export const COMMAND_EXAMPLES = {
  ffmpeg:
    '-i pipe:0 -c:v libx264 -b:v 2000k -vf scale=-2:720 -c:a copy -f mpegts pipe:1',
};

export const toCommandSelection = (command) =>
  BUILT_IN_COMMANDS.find((o) => o.value === command && o.value !== '__custom__')
    ? command
    : '__custom__';

export const schema = Yup.object({
  name: Yup.string().required('Name is required'),
  command: Yup.string().required('Command is required'),
  parameters: Yup.string(),
});

export const addOutputProfile = (values) => {
  return API.addOutputProfile(values);
};

export const updateOutputProfile = (values) => {
  return API.updateOutputProfile(values);
};

export const getResolver = () => {
  return yupResolver(schema);
};
