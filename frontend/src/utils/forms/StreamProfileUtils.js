// Built-in commands supported by Dispatcharr out of the box.
import { yupResolver } from '@hookform/resolvers/yup';
import API from '../../api.js';
import * as Yup from 'yup';

export const BUILT_IN_COMMANDS = [
  { value: 'ffmpeg', label: 'FFmpeg' },
  { value: 'streamlink', label: 'Streamlink' },
  { value: 'cvlc', label: 'VLC' },
  { value: 'yt-dlp', label: 'yt-dlp' },
  { value: '__custom__', label: 'Custom…' },
];

// Default parameter examples for each built-in command.
export const COMMAND_EXAMPLES = {
  ffmpeg: '-user_agent {userAgent} -i {streamUrl} -c copy -f mpegts pipe:1',
  streamlink: '{streamUrl} --http-header User-Agent={userAgent} best --stdout',
  cvlc: '-vv -I dummy --no-video-title-show --http-user-agent {userAgent} {streamUrl} --sout #standard{access=file,mux=ts,dst=-}',
  'yt-dlp': '--hls-use-mpegts -f best -o - {streamUrl}',
};

// Returns '__custom__' when the command isn't one of the built-ins,
// otherwise returns the command value itself.
export const toCommandSelection = (command) =>
  BUILT_IN_COMMANDS.find((o) => o.value === command && o.value !== '__custom__')
    ? command
    : '__custom__';

const schema = Yup.object({
  name: Yup.string().required('Name is required'),
  command: Yup.string().required('Command is required'),
  parameters: Yup.string(),
});

export const getResolver = () => {
  return yupResolver(schema);
};

export const updateStreamProfile = (profileId, values) => {
  return API.updateStreamProfile({ id: profileId, ...values });
};
export const addStreamProfile = (values) => {
  return API.addStreamProfile(values);
};
