// src/api.js (updated)
import useAuthStore from './store/auth';
import useChannelsStore from './store/channels';
import useLogosStore from './store/logos';
import useUserAgentsStore from './store/userAgents';
import usePlaylistsStore from './store/playlists';
import useEPGsStore from './store/epgs';
import useStreamsStore from './store/streams';
import useStreamProfilesStore from './store/streamProfiles';
import useSettingsStore from './store/settings';
import { notifications } from '@mantine/notifications';
import useChannelsTableStore from './store/channelsTable';
import useUsersStore from './store/users';

// If needed, you can set a base host or keep it empty if relative requests
const host = import.meta.env.DEV
  ? `http://${window.location.hostname}:5656`
  : '';

const errorNotification = (message, error) => {
  let errorMessage = '';

  if (error.status) {
    try {
      // Try to format the error body if it's an object
      if (typeof error.body === 'object') {
        errorMessage = JSON.stringify(error.body, null, 2);
      } else {
        errorMessage = `${error.status} - ${error.body}`;
      }
    } catch (e) {
      errorMessage = `${error.status} - ${String(error.body)}`;
    }
  } else {
    errorMessage = error.message || 'Unknown error';
  }

  notifications.show({
    title: 'Error',
    message: `${message}: ${errorMessage}`,
    autoClose: 10000,
    color: 'red',
  });

  throw error;
};

const request = async (url, options = {}) => {
  if (
    options.body &&
    !(options.body instanceof FormData) &&
    typeof options.body === 'object'
  ) {
    options.body = JSON.stringify(options.body);
    options.headers = {
      ...options.headers,
      'Content-Type': 'application/json',
    };
  }

  if (options.auth !== false) {
    options.headers = {
      ...options.headers,
      Authorization: `Bearer ${await API.getAuthToken()}`,
    };
  }

  const response = await fetch(url, options);

  if (!response.ok) {
    const error = new Error(`HTTP error! Status: ${response.status}`);

    let errorBody = await response.text();

    try {
      errorBody = JSON.parse(errorBody);
    } catch (e) {
      // If parsing fails, leave errorBody as the raw text
    }

    error.status = response.status;
    error.response = response;
    error.body = errorBody;

    throw error;
  }

  try {
    const retval = await response.json();
    return retval;
  } catch (e) {
    return '';
  }
};

export default class API {
  static lastQueryParams = new URLSearchParams();

  /**
   * A static method so we can do:  await API.getAuthToken()
   */
  static async getAuthToken() {
    return await useAuthStore.getState().getToken();
  }

  static async fetchSuperUser() {
    try {
      return await request(`${host}/api/accounts/initialize-superuser/`, {
        auth: false,
        method: 'GET',
      });
    } catch (error) {
      console.error('Error checking superuser status:', error);
      throw error;
    }
  }

  static async createSuperUser({ username, email, password }) {
    try {
      const response = await request(
        `${host}/api/accounts/initialize-superuser/`,
        {
          auth: false,
          method: 'POST',
          body: {
            username,
            password,
            email,
          },
        }
      );

      return response;
    } catch (e) {
      errorNotification('Failed to create superuser', e);
    }
  }

  static async login(username, password) {
    try {
      const response = await request(`${host}/api/accounts/token/`, {
        auth: false,
        method: 'POST',
        body: { username, password },
      });

      return response;
    } catch (e) {
      errorNotification('Login failed', e);
    }
  }

  static async refreshToken(refresh) {
    try {
      return await request(`${host}/api/accounts/token/refresh/`, {
        auth: false,
        method: 'POST',
        body: { refresh },
      });
    } catch (error) {
      // If user does not exist or token is invalid, clear tokens
      if (error.status === 401 || error.message?.includes('does not exist')) {
        localStorage.removeItem('token');
        localStorage.removeItem('refreshToken');
        window.location.href = '/login'; // Redirect to login
      }
      throw error;
    }
  }

  static async logout() {
    return await request(`${host}/api/accounts/auth/logout/`, {
      auth: true,  // Send JWT token so backend can identify the user
      method: 'POST',
    });
  }

  static async getChannels() {
    try {
      const response = await request(`${host}/api/channels/channels/`);

      return response;
    } catch (e) {
      errorNotification('Failed to retrieve channels', e);
    }
  }

  static async queryChannels(params) {
    try {
      API.lastQueryParams = params;

      const response = await request(
        `${host}/api/channels/channels/?${params.toString()}`
      );

      useChannelsTableStore.getState().queryChannels(response, params);

      return response;
    } catch (e) {
      errorNotification('Failed to fetch channels', e);
    }
  }

  static async requeryChannels() {
    try {
      const [response, ids] = await Promise.all([
        request(
          `${host}/api/channels/channels/?${API.lastQueryParams.toString()}`
        ),
        API.getAllChannelIds(API.lastQueryParams),
      ]);

      useChannelsTableStore
        .getState()
        .queryChannels(response, API.lastQueryParams);
      useChannelsTableStore.getState().setAllQueryIds(ids);

      return response;
    } catch (e) {
      errorNotification('Failed to fetch channels', e);
    }
  }

  static async getAllChannelIds(params) {
    try {
      const response = await request(
        `${host}/api/channels/channels/ids/?${params.toString()}`
      );

      return response;
    } catch (e) {
      errorNotification('Failed to fetch channel IDs', e);
    }
  }

  static async getChannelGroups() {
    try {
      const response = await request(`${host}/api/channels/groups/`);

      return response;
    } catch (e) {
      errorNotification('Failed to retrieve channel groups', e);
    }
  }

  static async addChannelGroup(values) {
    try {
      const response = await request(`${host}/api/channels/groups/`, {
        method: 'POST',
        body: values,
      });

      if (response.id) {
        // Add association flags for new groups
        const processedGroup = {
          ...response,
          hasChannels: false,
          hasM3UAccounts: false,
          canEdit: true,
          canDelete: true,
        };
        useChannelsStore.getState().addChannelGroup(processedGroup);
        // Refresh channel groups to update the UI
        useChannelsStore.getState().fetchChannelGroups();
      }

      return response;
    } catch (e) {
      errorNotification('Failed to create channel group', e);
    }
  }

  static async updateChannelGroup(values) {
    try {
      const { id, ...payload } = values;
      const response = await request(`${host}/api/channels/groups/${id}/`, {
        method: 'PUT',
        body: payload,
      });

      if (response.id) {
        useChannelsStore.getState().updateChannelGroup(response);
      }

      return response;
    } catch (e) {
      errorNotification('Failed to update channel group', e);
    }
  }

  static async deleteChannelGroup(id) {
    try {
      await request(`${host}/api/channels/groups/${id}/`, {
        method: 'DELETE',
      });

      // Remove from store after successful deletion
      useChannelsStore.getState().removeChannelGroup(id);

      return true;
    } catch (e) {
      errorNotification('Failed to delete channel group', e);
      throw e;
    }
  }

  static async cleanupUnusedChannelGroups() {
    try {
      const response = await request(`${host}/api/channels/groups/cleanup/`, {
        method: 'POST',
      });

      // Refresh channel groups to update the UI
      useChannelsStore.getState().fetchChannelGroups();

      return response;
    } catch (e) {
      errorNotification('Failed to cleanup unused channel groups', e);
      throw e;
    }
  }

  static async addChannel(channel) {
    try {
      let body = null;
      // Prepare a copy to safely mutate
      const channelData = { ...channel };

      // Remove channel_number if empty, null, or not a valid number
      if (
        channelData.channel_number === '' ||
        channelData.channel_number === null ||
        channelData.channel_number === undefined ||
        (typeof channelData.channel_number === 'string' && channelData.channel_number.trim() === '')
      ) {
        delete channelData.channel_number;
      }

      if (channel.logo_file) {
        // Must send FormData for file upload
        body = new FormData();
        for (const prop in channelData) {
          body.append(prop, channelData[prop]);
        }
      } else {
        body = { ...channelData };
        delete body.logo_file;
      }

      const response = await request(`${host}/api/channels/channels/`, {
        method: 'POST',
        body: body,
      });

      API.getLogos();

      if (response.id) {
        useChannelsStore.getState().addChannel(response);
      }

      return response;
    } catch (e) {
      errorNotification('Failed to create channel', e);
    }
  }

  static async deleteChannel(id) {
    try {
      await request(`${host}/api/channels/channels/${id}/`, {
        method: 'DELETE',
      });

      useChannelsStore.getState().removeChannels([id]);
    } catch (e) {
      errorNotification('Failed to delete channel', e);
    }
  }

  // @TODO: the bulk delete endpoint is currently broken
  static async deleteChannels(channel_ids) {
    try {
      await request(`${host}/api/channels/channels/bulk-delete/`, {
        method: 'DELETE',
        body: { channel_ids },
      });

      useChannelsStore.getState().removeChannels(channel_ids);
    } catch (e) {
      errorNotification('Failed to delete channels', e);
    }
  }

  static async updateChannel(values) {
    try {
      // Clean up values before sending to API
      const payload = { ...values };

      // Handle special values
      if (
        payload.stream_profile_id === '0' ||
        payload.stream_profile_id === 0
      ) {
        payload.stream_profile_id = null;
      }

      // Handle logo_id properly (0 means "no logo")
      if (payload.logo_id === '0' || payload.logo_id === 0) {
        payload.logo_id = null;
      }

      // Ensure tvg_id is included properly (not as empty string)
      if (payload.tvg_id === '') {
        payload.tvg_id = null;
      }

      // Ensure tvc_guide_stationid is included properly (not as empty string)
      if (payload.tvc_guide_stationid === '') {
        payload.tvc_guide_stationid = null;
      }

      // Handle channel_number properly
      if (payload.channel_number === '') {
        payload.channel_number = null;
      } else if (
        payload.channel_number !== null &&
        payload.channel_number !== undefined
      ) {
        // Ensure channel_number is explicitly treated as a float
        payload.channel_number = parseFloat(payload.channel_number);
      }

      const response = await request(
        `${host}/api/channels/channels/${payload.id}/`,
        {
          method: 'PATCH',
          body: payload,
        }
      );

      useChannelsStore.getState().updateChannel(response);
      return response;
    } catch (e) {
      errorNotification('Failed to update channel', e);
    }
  }

  static async updateChannels(ids, values) {
    const body = [];
    for (const id of ids) {
      body.push({
        id: id,
        ...values,
      });
    }

    try {
      const response = await request(
        `${host}/api/channels/channels/edit/bulk/`,
        {
          method: 'PATCH',
          body,
        }
      );

      // Show success notification
      if (response.message) {
        notifications.show({
          title: 'Channels Updated',
          message: response.message,
          color: 'green',
          autoClose: 4000,
        });
      }

      return response;
    } catch (e) {
      errorNotification('Failed to update channels', e);
    }
  }

  // Bulk update with per-channel payloads (e.g., regex renames)
  static async bulkUpdateChannels(updates) {
    try {
      const response = await request(
        `${host}/api/channels/channels/edit/bulk/`,
        {
          method: 'PATCH',
          body: updates,
        }
      );

      return response;
    } catch (e) {
      errorNotification('Failed to update channels', e);
    }
  }

  static async setChannelEPG(channelId, epgDataId) {
    try {
      const response = await request(
        `${host}/api/channels/channels/${channelId}/set-epg/`,
        {
          method: 'POST',
          body: { epg_data_id: epgDataId },
        }
      );

      // Update the channel in the store with the refreshed data
      if (response.channel) {
        useChannelsStore.getState().updateChannel(response.channel);
      }

      // Show notification about task status
      if (response.task_status) {
        notifications.show({
          title: 'EPG Status',
          message: response.task_status,
          color: 'blue',
        });
      }

      return response;
    } catch (e) {
      errorNotification('Failed to update channel EPG', e);
    }
  }

  static async setChannelNamesFromEpg(channelIds) {
    try {
      const response = await request(
        `${host}/api/channels/channels/set-names-from-epg/`,
        {
          method: 'POST',
          body: { channel_ids: channelIds },
        }
      );

      notifications.show({
        title: 'Task Started',
        message: response.message,
        color: 'blue',
      });

      return response;
    } catch (e) {
      errorNotification('Failed to start EPG name setting task', e);
      throw e;
    }
  }

  static async setChannelLogosFromEpg(channelIds) {
    try {
      const response = await request(
        `${host}/api/channels/channels/set-logos-from-epg/`,
        {
          method: 'POST',
          body: { channel_ids: channelIds },
        }
      );

      notifications.show({
        title: 'Task Started',
        message: response.message,
        color: 'blue',
      });

      return response;
    } catch (e) {
      errorNotification('Failed to start EPG logo setting task', e);
      throw e;
    }
  }

  static async setChannelTvgIdsFromEpg(channelIds) {
    try {
      const response = await request(
        `${host}/api/channels/channels/set-tvg-ids-from-epg/`,
        {
          method: 'POST',
          body: { channel_ids: channelIds },
        }
      );

      notifications.show({
        title: 'Task Started',
        message: response.message,
        color: 'blue',
      });

      return response;
    } catch (e) {
      errorNotification('Failed to start EPG TVG-ID setting task', e);
      throw e;
    }
  }

  static async assignChannelNumbers(channelIds, startingNum = 1) {
    try {
      const response = await request(`${host}/api/channels/channels/assign/`, {
        method: 'POST',
        body: { channel_ids: channelIds, starting_number: startingNum },
      });

      return response;
    } catch (e) {
      errorNotification('Failed to assign channel #s', e);
    }
  }

  static async createChannelFromStream(values) {
    try {
      const response = await request(
        `${host}/api/channels/channels/from-stream/`,
        {
          method: 'POST',
          body: values,
        }
      );

      if (response.id) {
        useChannelsStore.getState().addChannel(response);
      }

      return response;
    } catch (e) {
      errorNotification('Failed to create channel', e);
    }
  }

  static async createChannelsFromStreamsAsync(streamIds, channelProfileIds = null, startingChannelNumber = null) {
    try {
      const requestBody = {
        stream_ids: streamIds,
      };

      if (channelProfileIds !== null) {
        requestBody.channel_profile_ids = channelProfileIds;
      }

      if (startingChannelNumber !== null) {
        requestBody.starting_channel_number = startingChannelNumber;
      }

      const response = await request(
        `${host}/api/channels/channels/from-stream/bulk/`,
        {
          method: 'POST',
          body: requestBody,
        }
      );

      return response;
    } catch (e) {
      errorNotification('Failed to start bulk channel creation task', e);
      throw e;
    }
  }

  static async getStreams(ids = null) {
    try {
      const params = new URLSearchParams();
      if (ids) {
        params.append('ids', ids.join(','));
      }
      const response = await request(
        `${host}/api/channels/streams/?${params.toString()}`
      );

      return response;
    } catch (e) {
      errorNotification('Failed to retrieve streams', e);
    }
  }

  static async getChannelStreams(id) {
    try {
      const response = await request(
        `${host}/api/channels/channels/${id}/streams/`
      );

      return response;
    } catch (e) {
      errorNotification('Failed to retrieve channel streams', e);
    }
  }

  static async queryStreams(params) {
    try {
      const response = await request(
        `${host}/api/channels/streams/?${params.toString()}`
      );

      return response;
    } catch (e) {
      errorNotification('Failed to fetch streams', e);
    }
  }

  static async getAllStreamIds(params) {
    try {
      const response = await request(
        `${host}/api/channels/streams/ids/?${params.toString()}`
      );

      return response;
    } catch (e) {
      errorNotification('Failed to fetch stream IDs', e);
    }
  }

  static async getStreamGroups() {
    try {
      const response = await request(`${host}/api/channels/streams/groups/`);

      return response;
    } catch (e) {
      errorNotification('Failed to retrieve stream groups', e);
    }
  }

  static async addStream(values) {
    try {
      const response = await request(`${host}/api/channels/streams/`, {
        method: 'POST',
        body: values,
      });

      if (response.id) {
        useStreamsStore.getState().addStream(response);
      }

      return response;
    } catch (e) {
      errorNotification('Failed to add stream', e);
    }
  }

  static async updateStream(values) {
    try {
      const { id, ...payload } = values;
      const response = await request(`${host}/api/channels/streams/${id}/`, {
        method: 'PUT',
        body: payload,
      });

      if (response.id) {
        useStreamsStore.getState().updateStream(response);
      }

      return response;
    } catch (e) {
      errorNotification('Failed to update stream', e);
    }
  }

  static async deleteStream(id) {
    try {
      await request(`${host}/api/channels/streams/${id}/`, {
        method: 'DELETE',
      });

      useStreamsStore.getState().removeStreams([id]);
    } catch (e) {
      errorNotification('Failed to delete stream', e);
    }
  }

  static async deleteStreams(ids) {
    try {
      await request(`${host}/api/channels/streams/bulk-delete/`, {
        method: 'DELETE',
        body: { stream_ids: ids },
      });

      useStreamsStore.getState().removeStreams(ids);
    } catch (e) {
      errorNotification('Failed to delete streams', e);
    }
  }

  static async getUserAgents() {
    try {
      const response = await request(`${host}/api/core/useragents/`);

      return response;
    } catch (e) {
      errorNotification('Failed to retrieve user-agents', e);
    }
  }

  static async addUserAgent(values) {
    try {
      const response = await request(`${host}/api/core/useragents/`, {
        method: 'POST',
        body: values,
      });

      useUserAgentsStore.getState().addUserAgent(response);

      return response;
    } catch (e) {
      errorNotification('Failed to create user-agent', e);
    }
  }

  static async updateUserAgent(values) {
    try {
      const { id, ...payload } = values;
      const response = await request(`${host}/api/core/useragents/${id}/`, {
        method: 'PUT',
        body: payload,
      });

      useUserAgentsStore.getState().updateUserAgent(response);

      return response;
    } catch (e) {
      errorNotification('Failed to update user-agent', e);
    }
  }

  static async deleteUserAgent(id) {
    try {
      await request(`${host}/api/core/useragents/${id}/`, {
        method: 'DELETE',
      });

      useUserAgentsStore.getState().removeUserAgents([id]);
    } catch (e) {
      errorNotification('Failed to delete user-agent', e);
    }
  }

  static async getPlaylist(id) {
    try {
      const response = await request(`${host}/api/m3u/accounts/${id}/`);

      return response;
    } catch (e) {
      errorNotification(`Failed to retrieve M3U account ${id}`, e);
    }
  }

  static async getPlaylists() {
    try {
      const response = await request(`${host}/api/m3u/accounts/`);

      return response;
    } catch (e) {
      errorNotification('Failed to retrieve M3U accounts', e);
    }
  }

  static async updateM3UGroupSettings(
    playlistId,
    groupSettings = [],
    categorySettings = []
  ) {
    try {
      const response = await request(
        `${host}/api/m3u/accounts/${playlistId}/group-settings/`,
        {
          method: 'PATCH',
          body: {
            group_settings: groupSettings,
            category_settings: categorySettings,
          },
        }
      );
      // Fetch the updated playlist and update the store
      const updatedPlaylist = await API.getPlaylist(playlistId);
      usePlaylistsStore.getState().updatePlaylist(updatedPlaylist);
      return response;
    } catch (e) {
      errorNotification('Failed to update M3U group settings', e);
    }
  }

  static async addPlaylist(values) {
    try {
      let body = null;
      if (values.file) {
        body = new FormData();
        for (const prop in values) {
          body.append(prop, values[prop]);
        }
      } else {
        body = { ...values };
        delete body.file;
      }

      const response = await request(`${host}/api/m3u/accounts/`, {
        method: 'POST',
        body,
      });

      usePlaylistsStore.getState().addPlaylist(response);

      return response;
    } catch (e) {
      errorNotification('Failed to create M3U account', e);
    }
  }

  static async refreshPlaylist(id) {
    try {
      const response = await request(`${host}/api/m3u/refresh/${id}/`, {
        method: 'POST',
      });
      return response;
    } catch (e) {
      errorNotification('Failed to refresh M3U account', e);
    }
  }
  static async refreshAllPlaylist() {
    try {
      const response = await request(`${host}/api/m3u/refresh/`, {
        method: 'POST',
      });

      return response;
    } catch (e) {
      errorNotification('Failed to refresh all M3U accounts', e);
    }
  }
  static async refreshVODContent(accountId) {
    try {
      const response = await request(
        `${host}/api/m3u/accounts/${accountId}/refresh-vod/`,
        {
          method: 'POST',
        }
      );
      return response;
    } catch (e) {
      errorNotification('Failed to refresh VOD content', e);
    }
  }

  static async deletePlaylist(id) {
    try {
      await request(`${host}/api/m3u/accounts/${id}/`, {
        method: 'DELETE',
      });

      usePlaylistsStore.getState().removePlaylists([id]);
      // @TODO: MIGHT need to optimize this later if someone has thousands of channels
      // but I'm feeling laze right now
      // useChannelsStore.getState().fetchChannels();
    } catch (e) {
      errorNotification(`Failed to delete playlist ${id}`, e);
    }
  }

  static async updatePlaylist(values, isToggle = false) {
    const { id, ...payload } = values;

    try {
      // If this is just toggling the active state, make a simpler request
      if (
        isToggle &&
        'is_active' in payload &&
        Object.keys(payload).length === 1
      ) {
        const response = await request(`${host}/api/m3u/accounts/${id}/`, {
          method: 'PATCH',
          body: { is_active: payload.is_active },
        });

        usePlaylistsStore.getState().updatePlaylist(response);
        return response;
      }

      // Original implementation for full updates
      let body = null;
      if (payload.file) {
        delete payload.server_url;

        body = new FormData();
        for (const prop in values) {
          body.append(prop, values[prop]);
        }
      } else {
        delete payload.file;
        if (!payload.server_url) {
          delete payload.sever_url;
        }

        body = { ...payload };
        delete body.file;
      }

      const response = await request(`${host}/api/m3u/accounts/${id}/`, {
        method: 'PATCH',
        body,
      });

      usePlaylistsStore.getState().updatePlaylist(response);

      return response;
    } catch (e) {
      errorNotification(`Failed to update M3U account ${id}`, e);
    }
  }

  static async getEPGs() {
    try {
      const response = await request(`${host}/api/epg/sources/`);

      return response;
    } catch (e) {
      errorNotification('Failed to retrieve EPGs', e);
    }
  }

  static async getEPGData() {
    try {
      const response = await request(`${host}/api/epg/epgdata/`);

      return response;
    } catch (e) {
      errorNotification('Failed to retrieve EPG data', e);
    }
  }

  // Notice there's a duplicated "refreshPlaylist" method above;
  // you might want to rename or remove one if it's not needed.

  static async addEPG(values) {
    try {
      let body = null;
      if (values.files) {
        body = new FormData();
        for (const prop in values) {
          body.append(prop, values[prop]);
        }
      } else {
        body = { ...values };
        delete body.file;
      }

      const response = await request(`${host}/api/epg/sources/`, {
        method: 'POST',
        body,
      });

      useEPGsStore.getState().addEPG(response);

      return response;
    } catch (e) {
      errorNotification('Failed to create EPG', e);
    }
  }

  static async updateEPG(values, isToggle = false) {
    // Validate that values is an object
    if (!values || typeof values !== 'object') {
      console.error('updateEPG called with invalid values:', values);
      return;
    }

    const { id, ...payload } = values;

    // Validate that we have an ID and payload is an object
    if (!id || typeof payload !== 'object') {
      console.error('updateEPG: invalid id or payload', { id, payload });
      return;
    }

    try {
      // If this is just toggling the active state, make a simpler request
      if (
        isToggle &&
        'is_active' in payload &&
        Object.keys(payload).length === 1
      ) {
        const response = await request(`${host}/api/epg/sources/${id}/`, {
          method: 'PATCH',
          body: { is_active: payload.is_active },
        });

        useEPGsStore.getState().updateEPG(response);
        return response;
      }

      // Original implementation for full updates
      let body = null;
      if (payload.files) {
        body = new FormData();
        for (const prop in payload) {
          if (prop == 'url') {
            continue;
          }
          body.append(prop, payload[prop]);
        }
      } else {
        delete payload.file;
        if (!payload.url) {
          delete payload.url;
        }
        body = payload;
      }

      const response = await request(`${host}/api/epg/sources/${id}/`, {
        method: 'PATCH',
        body,
      });

      useEPGsStore.getState().updateEPG(response);

      return response;
    } catch (e) {
      errorNotification(`Failed to update EPG ${id}`, e);
    }
  }

  static async deleteEPG(id) {
    try {
      await request(`${host}/api/epg/sources/${id}/`, {
        method: 'DELETE',
      });

      useEPGsStore.getState().removeEPGs([id]);
    } catch (e) {
      errorNotification(`Failed to delete EPG ${id}`, e);
    }
  }

  static async refreshEPG(id) {
    try {
      const response = await request(`${host}/api/epg/import/`, {
        method: 'POST',
        body: { id },
      });

      return response;
    } catch (e) {
      errorNotification(`Failed to refresh EPG ${id}`, e);
    }
  }

  static async getTimezones() {
    try {
      const response = await request(`${host}/api/core/timezones/`);
      return response;
    } catch (e) {
      errorNotification('Failed to retrieve timezones', e);
      // Return fallback data instead of throwing
      return {
        timezones: ['UTC', 'US/Eastern', 'US/Central', 'US/Mountain', 'US/Pacific'],
        grouped: {},
        count: 5
      };
    }
  }

  static async getStreamProfiles() {
    try {
      const response = await request(`${host}/api/core/streamprofiles/`);

      return response;
    } catch (e) {
      errorNotification('Failed to retrieve sream profiles', e);
    }
  }

  static async addStreamProfile(values) {
    try {
      const response = await request(`${host}/api/core/streamprofiles/`, {
        method: 'POST',
        body: values,
      });

      useStreamProfilesStore.getState().addStreamProfile(response);

      return response;
    } catch (e) {
      errorNotification('Failed to create stream profile', e);
    }
  }

  static async updateStreamProfile(values) {
    const { id, ...payload } = values;

    try {
      const response = await request(`${host}/api/core/streamprofiles/${id}/`, {
        method: 'PUT',
        body: payload,
      });

      useStreamProfilesStore.getState().updateStreamProfile(response);

      return response;
    } catch (e) {
      errorNotification(`Failed to update stream profile ${id}`, e);
    }
  }

  static async deleteStreamProfile(id) {
    try {
      await request(`${host}/api/core/streamprofiles/${id}/`, {
        method: 'DELETE',
      });

      useStreamProfilesStore.getState().removeStreamProfiles([id]);
    } catch (e) {
      errorNotification(`Failed to delete stream propfile ${id}`, e);
    }
  }

  static async getGrid() {
    try {
      const response = await request(`${host}/api/epg/grid/`);

      return response.data;
    } catch (e) {
      errorNotification('Failed to retrieve program grid', e);
    }
  }

  static async addM3UProfile(accountId, values) {
    try {
      const response = await request(
        `${host}/api/m3u/accounts/${accountId}/profiles/`,
        {
          method: 'POST',
          body: values,
        }
      );

      // Refresh the playlist
      const playlist = await API.getPlaylist(accountId);
      usePlaylistsStore
        .getState()
        .updateProfiles(playlist.id, playlist.profiles);

      return response;
    } catch (e) {
      errorNotification(`Failed to add profile to account ${accountId}`, e);
    }
  }

  static async deleteM3UProfile(accountId, id) {
    try {
      await request(`${host}/api/m3u/accounts/${accountId}/profiles/${id}/`, {
        method: 'DELETE',
      });

      const playlist = await API.getPlaylist(accountId);
      usePlaylistsStore.getState().updatePlaylist(playlist);
    } catch (e) {
      errorNotification(`Failed to delete profile for account ${accountId}`, e);
    }
  }

  static async updateM3UProfile(accountId, values) {
    const { id, ...payload } = values;

    try {
      await request(`${host}/api/m3u/accounts/${accountId}/profiles/${id}/`, {
        method: 'PUT',
        body: payload,
      });

      const playlist = await API.getPlaylist(accountId);
      usePlaylistsStore
        .getState()
        .updateProfiles(playlist.id, playlist.profiles);
    } catch (e) {
      errorNotification(`Failed to update profile for account ${accountId}`, e);
    }
  }

  static async refreshAccountInfo(profileId) {
    try {
      const response = await request(`${host}/api/m3u/refresh-account-info/${profileId}/`, {
        method: 'POST',
      });
      return response;
    } catch (e) {
      // If it's a structured error response, return it instead of throwing
      if (e.body && typeof e.body === 'object') {
        return e.body;
      }
      errorNotification(`Failed to refresh account info for profile ${profileId}`, e);
      throw e;
    }
  }

  static async addM3UFilter(accountId, values) {
    try {
      const response = await request(
        `${host}/api/m3u/accounts/${accountId}/filters/`,
        {
          method: 'POST',
          body: values,
        }
      );

      return response;
    } catch (e) {
      errorNotification(`Failed to add profile to account ${accountId}`, e);
    }
  }

  static async deleteM3UFilter(accountId, id) {
    try {
      await request(`${host}/api/m3u/accounts/${accountId}/filters/${id}/`, {
        method: 'DELETE',
      });
    } catch (e) {
      errorNotification(`Failed to delete profile for account ${accountId}`, e);
    }
  }

  static async updateM3UFilter(accountId, filterId, values) {
    const { id, ...payload } = values;

    try {
      await request(
        `${host}/api/m3u/accounts/${accountId}/filters/${filterId}/`,
        {
          method: 'PUT',
          body: payload,
        }
      );
    } catch (e) {
      errorNotification(`Failed to update profile for account ${accountId}`, e);
    }
  }

  static async getSettings() {
    try {
      const response = await request(`${host}/api/core/settings/`);

      return response;
    } catch (e) {
      errorNotification('Failed to retrieve settings', e);
    }
  }

  static async getEnvironmentSettings() {
    try {
      const response = await request(`${host}/api/core/settings/env/`);

      return response;
    } catch (e) {
      errorNotification('Failed to retrieve environment settings', e);
    }
  }

  // Backup API (async with Celery task polling)
  static async listBackups() {
    try {
      const response = await request(`${host}/api/backups/`);
      return response || [];
    } catch (e) {
      errorNotification('Failed to load backups', e);
      throw e;
    }
  }

  static async getBackupStatus(taskId, token = null) {
    try {
      let url = `${host}/api/backups/status/${taskId}/`;
      if (token) {
        url += `?token=${encodeURIComponent(token)}`;
      }
      const response = await request(url, { auth: !token });
      return response;
    } catch (e) {
      throw e;
    }
  }

  static async waitForBackupTask(taskId, onProgress, token = null) {
    const pollInterval = 2000; // Poll every 2 seconds
    const maxAttempts = 300; // Max 10 minutes (300 * 2s)

    for (let attempt = 0; attempt < maxAttempts; attempt++) {
      try {
        const status = await API.getBackupStatus(taskId, token);

        if (onProgress) {
          onProgress(status);
        }

        if (status.state === 'completed') {
          return status.result;
        } else if (status.state === 'failed') {
          throw new Error(status.error || 'Task failed');
        }
      } catch (e) {
        throw e;
      }

      // Wait before next poll
      await new Promise((resolve) => setTimeout(resolve, pollInterval));
    }

    throw new Error('Task timed out');
  }

  static async createBackup(onProgress) {
    try {
      // Start the backup task
      const response = await request(`${host}/api/backups/create/`, {
        method: 'POST',
      });

      // Wait for the task to complete using token for auth
      const result = await API.waitForBackupTask(response.task_id, onProgress, response.task_token);
      return result;
    } catch (e) {
      errorNotification('Failed to create backup', e);
      throw e;
    }
  }

  static async uploadBackup(file) {
    try {
      const formData = new FormData();
      formData.append('file', file);

      const response = await request(
        `${host}/api/backups/upload/`,
        {
          method: 'POST',
          body: formData,
        }
      );
      return response;
    } catch (e) {
      errorNotification('Failed to upload backup', e);
      throw e;
    }
  }

  static async deleteBackup(filename) {
    try {
      const encodedFilename = encodeURIComponent(filename);
      await request(`${host}/api/backups/${encodedFilename}/delete/`, {
        method: 'DELETE',
      });
    } catch (e) {
      errorNotification('Failed to delete backup', e);
      throw e;
    }
  }

  static async getDownloadToken(filename) {
    // Get a download token from the server
    try {
      const response = await request(`${host}/api/backups/${encodeURIComponent(filename)}/download-token/`);
      return response.token;
    } catch (e) {
      throw e;
    }
  }

  static async downloadBackup(filename) {
    try {
      // Get a download token first (requires auth)
      const token = await API.getDownloadToken(filename);
      const encodedFilename = encodeURIComponent(filename);

      // Build the download URL with token
      const downloadUrl = `${host}/api/backups/${encodedFilename}/download/?token=${encodeURIComponent(token)}`;

      // Use direct browser navigation instead of fetch to avoid CORS issues
      const link = document.createElement('a');
      link.href = downloadUrl;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);

      return { filename };
    } catch (e) {
      errorNotification('Failed to download backup', e);
      throw e;
    }
  }

  static async restoreBackup(filename, onProgress) {
    try {
      // Start the restore task
      const encodedFilename = encodeURIComponent(filename);
      const response = await request(
        `${host}/api/backups/${encodedFilename}/restore/`,
        {
          method: 'POST',
        }
      );

      // Wait for the task to complete using token for auth
      // Token-based auth allows status polling even after DB restore invalidates user sessions
      const result = await API.waitForBackupTask(response.task_id, onProgress, response.task_token);
      return result;
    } catch (e) {
      errorNotification('Failed to restore backup', e);
      throw e;
    }
  }

  static async getBackupSchedule() {
    try {
      const response = await request(`${host}/api/backups/schedule/`);
      return response;
    } catch (e) {
      errorNotification('Failed to get backup schedule', e);
      throw e;
    }
  }

  static async updateBackupSchedule(settings) {
    try {
      const response = await request(`${host}/api/backups/schedule/update/`, {
        method: 'PUT',
        body: settings,
      });
      return response;
    } catch (e) {
      errorNotification('Failed to update backup schedule', e);
      throw e;
    }
  }

  static async getVersion() {
    try {
      const response = await request(`${host}/api/core/version/`, {
        auth: false,
      });

      return response;
    } catch (e) {
      errorNotification('Failed to retrieve version', e);
    }
  }

  // Plugins API
  static async getPlugins() {
    try {
      const response = await request(`${host}/api/plugins/plugins/`);
      return response.plugins || [];
    } catch (e) {
      errorNotification('Failed to retrieve plugins', e);
    }
  }

  static async reloadPlugins() {
    try {
      const response = await request(`${host}/api/plugins/plugins/reload/`, {
        method: 'POST',
      });
      return response;
    } catch (e) {
      errorNotification('Failed to reload plugins', e);
    }
  }

  static async importPlugin(file) {
    try {
      const form = new FormData();
      form.append('file', file);
      const response = await request(`${host}/api/plugins/plugins/import/`, {
        method: 'POST',
        body: form,
      });
      return response;
    } catch (e) {
      // Show only the concise error message for plugin import
      const msg = (e?.body && (e.body.error || e.body.detail)) || e?.message || 'Failed to import plugin';
      notifications.show({ title: 'Import failed', message: msg, color: 'red' });
      throw e;
    }
  }

  static async deletePlugin(key) {
    try {
      const response = await request(`${host}/api/plugins/plugins/${key}/delete/`, {
        method: 'DELETE',
      });
      return response;
    } catch (e) {
      errorNotification('Failed to delete plugin', e);
    }
  }

  static async updatePluginSettings(key, settings) {
    try {
      const response = await request(
        `${host}/api/plugins/plugins/${key}/settings/`,
        {
          method: 'POST',
          body: { settings },
        }
      );
      return response?.settings || {};
    } catch (e) {
      errorNotification('Failed to update plugin settings', e);
    }
  }

  static async runPluginAction(key, action, params = {}) {
    try {
      const response = await request(`${host}/api/plugins/plugins/${key}/run/`, {
        method: 'POST',
        body: { action, params },
      });
      return response;
    } catch (e) {
      errorNotification('Failed to run plugin action', e);
    }
  }

  static async setPluginEnabled(key, enabled) {
    try {
      const response = await request(`${host}/api/plugins/plugins/${key}/enabled/`, {
        method: 'POST',
        body: { enabled },
      });
      return response;
    } catch (e) {
      errorNotification('Failed to update plugin enabled state', e);
    }
  }

  static async checkSetting(values) {
    const { id, ...payload } = values;

    try {
      const response = await request(`${host}/api/core/settings/check/`, {
        method: 'POST',
        body: payload,
      });

      return response;
    } catch (e) {
      errorNotification('Failed to update settings', e);
    }
  }

  static async updateSetting(values) {
    const { id, ...payload } = values;

    try {
      const response = await request(`${host}/api/core/settings/${id}/`, {
        method: 'PUT',
        body: payload,
      });

      useSettingsStore.getState().updateSetting(response);

      return response;
    } catch (e) {
      errorNotification('Failed to update settings', e);
    }
  }

  static async createSetting(values) {
    try {
      const response = await request(`${host}/api/core/settings/`, {
        method: 'POST',
        body: values,
      });
      useSettingsStore.getState().updateSetting(response);
      return response;
    } catch (e) {
      errorNotification('Failed to create setting', e);
    }
  }

  static async getChannelStats(uuid = null) {
    try {
      const response = await request(`${host}/proxy/ts/status`);

      return response;
    } catch (e) {
      errorNotification('Failed to retrieve channel stats', e);
    }
  }

  static async getVODStats() {
    try {
      const response = await request(`${host}/proxy/vod/stats/`);

      return response;
    } catch (e) {
      errorNotification('Failed to retrieve VOD stats', e);
    }
  }

  static async stopChannel(id) {
    try {
      const response = await request(`${host}/proxy/ts/stop/${id}`, {
        method: 'POST',
      });

      return response;
    } catch (e) {
      errorNotification('Failed to stop channel', e);
    }
  }

  static async stopClient(channelId, clientId) {
    try {
      const response = await request(
        `${host}/proxy/ts/stop_client/${channelId}`,
        {
          method: 'POST',
          body: { client_id: clientId },
        }
      );

      return response;
    } catch (e) {
      errorNotification('Failed to stop client', e);
    }
  }

  static async matchEpg(channelIds = null) {
    try {
      const requestBody = channelIds ? { channel_ids: channelIds } : {};

      const response = await request(
        `${host}/api/channels/channels/match-epg/`,
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify(requestBody),
        }
      );

      return response;
    } catch (e) {
      errorNotification('Failed to run EPG auto-match', e);
    }
  }

  static async matchChannelEpg(channelId) {
    try {
      const response = await request(
        `${host}/api/channels/channels/${channelId}/match-epg/`,
        {
          method: 'POST',
        }
      );

      // Update the channel in the store with the refreshed data if provided
      if (response.channel) {
        useChannelsStore.getState().updateChannel(response.channel);
      }

      return response;
    } catch (e) {
      errorNotification('Failed to run EPG auto-match for channel', e);
    }
  }

  static async fetchActiveChannelStats() {
    try {
      const response = await request(`${host}/proxy/ts/status`);
      return response;
    } catch (e) {
      errorNotification('Failed to fetch active channel stats', e);
      throw e;
    }
  }

  static async getLogos(params = {}) {
    try {
      const queryParams = new URLSearchParams(params);
      const response = await request(
        `${host}/api/channels/logos/?${queryParams.toString()}`
      );

      return response;
    } catch (e) {
      errorNotification('Failed to retrieve logos', e);
    }
  }

  static async getLogosByIds(logoIds) {
    try {
      if (!logoIds || logoIds.length === 0) return [];

      const params = new URLSearchParams();
      logoIds.forEach(id => params.append('ids', id));
      // Disable pagination for ID-based queries to get all matching logos
      params.append('no_pagination', 'true');

      const response = await request(
        `${host}/api/channels/logos/?${params.toString()}`
      );

      return response;
    } catch (e) {
      errorNotification('Failed to retrieve logos by IDs', e);
      return [];
    }
  }

  static async fetchLogos() {
    try {
      const response = await this.getLogos();
      useLogosStore.getState().setLogos(response);
      return response;
    } catch (e) {
      errorNotification('Failed to fetch logos', e);
    }
  }

  static async fetchUsedLogos() {
    try {
      const response = await useLogosStore.getState().fetchUsedLogos();
      return response;
    } catch (e) {
      errorNotification('Failed to fetch used logos', e);
    }
  }

  static async fetchLogosByIds(logoIds) {
    try {
      const response = await useLogosStore.getState().fetchLogosByIds(logoIds);
      return response;
    } catch (e) {
      errorNotification('Failed to fetch logos by IDs', e);
    }
  }

  static async uploadLogo(file, name = null) {
    try {
      const formData = new FormData();
      formData.append('file', file);

      // Add custom name if provided
      if (name && name.trim()) {
        formData.append('name', name.trim());
      }

      // Add timeout handling for file uploads
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 30000); // 30 second timeout

      const response = await fetch(`${host}/api/channels/logos/upload/`, {
        method: 'POST',
        body: formData,
        headers: {
          Authorization: `Bearer ${await API.getAuthToken()}`,
        },
        signal: controller.signal,
      });

      clearTimeout(timeoutId);

      if (!response.ok) {
        const error = new Error(`HTTP error! Status: ${response.status}`);
        let errorBody = await response.text();

        try {
          errorBody = JSON.parse(errorBody);
        } catch (e) {
          // If parsing fails, leave errorBody as the raw text
        }

        error.status = response.status;
        error.response = response;
        error.body = errorBody;
        throw error;
      }

      const result = await response.json();
      useLogosStore.getState().addLogo(result);
      return result;
    } catch (e) {
      if (e.name === 'AbortError') {
        const timeoutError = new Error('Upload timed out. Please try again.');
        timeoutError.code = 'NETWORK_ERROR';
        throw timeoutError;
      }
      errorNotification('Failed to upload logo', e);
      throw e;
    }
  }

  static async createLogo(values) {
    try {
      // Use FormData for logo creation to match backend expectations
      const formData = new FormData();
      for (const [key, value] of Object.entries(values)) {
        if (value !== null && value !== undefined) {
          formData.append(key, value);
        }
      }

      const response = await request(`${host}/api/channels/logos/`, {
        method: 'POST',
        body: formData,
      });

      useLogosStore.getState().addLogo(response);

      return response;
    } catch (e) {
      errorNotification('Failed to create logo', e);
    }
  }

  static async updateLogo(id, values) {
    try {
      const response = await request(`${host}/api/channels/logos/${id}/`, {
        method: 'PUT',
        body: values, // This will be converted to JSON in the request function
      });

      useLogosStore.getState().updateLogo(response);

      return response;
    } catch (e) {
      errorNotification('Failed to update logo', e);
    }
  }

  static async deleteLogo(id, deleteFile = false) {
    try {
      const params = new URLSearchParams();
      if (deleteFile) {
        params.append('delete_file', 'true');
      }

      const url = `${host}/api/channels/logos/${id}/?${params.toString()}`;
      await request(url, {
        method: 'DELETE',
      });

      useLogosStore.getState().removeLogo(id);

      return true;
    } catch (e) {
      errorNotification('Failed to delete logo', e);
    }
  }

  static async deleteLogos(ids, deleteFiles = false) {
    try {
      const body = { logo_ids: ids };
      if (deleteFiles) {
        body.delete_files = true;
      }

      await request(`${host}/api/channels/logos/bulk-delete/`, {
        method: 'DELETE',
        body: body,
      });

      // Remove multiple logos from store
      ids.forEach((id) => {
        useLogosStore.getState().removeLogo(id);
      });

      return true;
    } catch (e) {
      errorNotification('Failed to delete logos', e);
    }
  }

  static async cleanupUnusedLogos(deleteFiles = false) {
    try {
      const body = {};
      if (deleteFiles) {
        body.delete_files = true;
      }

      const response = await request(`${host}/api/channels/logos/cleanup/`, {
        method: 'POST',
        body: body,
      });

      return response;
    } catch (e) {
      errorNotification('Failed to cleanup unused logos', e);
      throw e;
    }
  }

  // VOD Logo Methods
  static async getVODLogos(params = {}) {
    try {
      // Transform usage filter to match backend expectations
      const apiParams = { ...params };
      if (apiParams.usage === 'used') {
        apiParams.used = 'true';
        delete apiParams.usage;
      } else if (apiParams.usage === 'unused') {
        apiParams.used = 'false';
        delete apiParams.usage;
      } else if (apiParams.usage === 'movies') {
        apiParams.used = 'movies';
        delete apiParams.usage;
      } else if (apiParams.usage === 'series') {
        apiParams.used = 'series';
        delete apiParams.usage;
      }

      const queryParams = new URLSearchParams(apiParams);
      const response = await request(
        `${host}/api/vod/vodlogos/?${queryParams.toString()}`
      );

      return response;
    } catch (e) {
      errorNotification('Failed to retrieve VOD logos', e);
      throw e;
    }
  }

  static async deleteVODLogo(id) {
    try {
      await request(`${host}/api/vod/vodlogos/${id}/`, {
        method: 'DELETE',
      });

      return true;
    } catch (e) {
      errorNotification('Failed to delete VOD logo', e);
      throw e;
    }
  }

  static async deleteVODLogos(ids) {
    try {
      await request(`${host}/api/vod/vodlogos/bulk-delete/`, {
        method: 'DELETE',
        body: { logo_ids: ids },
      });

      return true;
    } catch (e) {
      errorNotification('Failed to delete VOD logos', e);
      throw e;
    }
  }

  static async cleanupUnusedVODLogos() {
    try {
      const response = await request(`${host}/api/vod/vodlogos/cleanup/`, {
        method: 'POST',
      });

      return response;
    } catch (e) {
      errorNotification('Failed to cleanup unused VOD logos', e);
      throw e;
    }
  }

  static async getChannelProfiles() {
    try {
      const response = await request(`${host}/api/channels/profiles/`);

      return response;
    } catch (e) {
      errorNotification('Failed to get channel profiles', e);
    }
  }

  static async addChannelProfile(values) {
    try {
      const response = await request(`${host}/api/channels/profiles/`, {
        method: 'POST',
        body: values,
      });

      useChannelsStore.getState().addProfile(response);

      return response;
    } catch (e) {
      errorNotification('Failed to create channel profile', e);
    }
  }

  static async updateChannelProfile(values) {
    const { id, ...payload } = values;

    try {
      const response = await request(`${host}/api/channels/profiles/${id}/`, {
        method: 'PUT',
        body: payload,
      });

      useChannelsStore.getState().updateProfile(response);

      return response;
    } catch (e) {
      errorNotification('Failed to update channel profile', e);
    }
  }

  static async deleteChannelProfile(id) {
    try {
      await request(`${host}/api/channels/profiles/${id}/`, {
        method: 'DELETE',
      });

      useChannelsStore.getState().removeProfiles([id]);
    } catch (e) {
      errorNotification(`Failed to delete channel profile ${id}`, e);
    }
  }

  static async updateProfileChannel(channelId, profileId, enabled) {
    try {
      await request(
        `${host}/api/channels/profiles/${profileId}/channels/${channelId}/`,
        {
          method: 'PATCH',
          body: { enabled },
        }
      );

      useChannelsStore
        .getState()
        .updateProfileChannels([channelId], profileId, enabled);
    } catch (e) {
      errorNotification(`Failed to update channel for profile ${profileId}`, e);
    }
  }

  static async updateProfileChannels(channelIds, profileId, enabled) {
    try {
      await request(
        `${host}/api/channels/profiles/${profileId}/channels/bulk-update/`,
        {
          method: 'PATCH',
          body: {
            channels: channelIds.map((id) => ({
              channel_id: id,
              enabled,
            })),
          },
        }
      );

      useChannelsStore
        .getState()
        .updateProfileChannels(channelIds, profileId, enabled);
    } catch (e) {
      errorNotification(
        `Failed to bulk update channels for profile ${profileId}`,
        e
      );
    }
  }

  static async getRecordings() {
    try {
      const response = await request(`${host}/api/channels/recordings/`);

      return response;
    } catch (e) {
      errorNotification('Failed to retrieve recordings', e);
    }
  }

  static async createRecording(values) {
    try {
      const response = await request(`${host}/api/channels/recordings/`, {
        method: 'POST',
        body: values,
      });

      useChannelsStore.getState().fetchRecordings();

      return response;
    } catch (e) {
      errorNotification('Failed to create recording', e);
    }
  }

  static async updateRecording(id, values) {
    try {
      const response = await request(`${host}/api/channels/recordings/${id}/`, {
        method: 'PATCH',
        body: values,
      });
      useChannelsStore.getState().fetchRecordings();
      return response;
    } catch (e) {
      errorNotification(`Failed to update recording ${id}`, e);
    }
  }

  static async getComskipConfig() {
    try {
      return await request(`${host}/api/channels/dvr/comskip-config/`);
    } catch (e) {
      errorNotification('Failed to retrieve comskip configuration', e);
    }
  }

  static async uploadComskipIni(file) {
    try {
      const formData = new FormData();
      formData.append('file', file);
      return await request(`${host}/api/channels/dvr/comskip-config/`, {
        method: 'POST',
        body: formData,
      });
    } catch (e) {
      errorNotification('Failed to upload comskip.ini', e);
    }
  }

  static async listRecurringRules() {
    try {
      const response = await request(`${host}/api/channels/recurring-rules/`);
      return response;
    } catch (e) {
      errorNotification('Failed to retrieve recurring DVR rules', e);
    }
  }

  static async createRecurringRule(payload) {
    try {
      const response = await request(`${host}/api/channels/recurring-rules/`, {
        method: 'POST',
        body: payload,
      });
      return response;
    } catch (e) {
      errorNotification('Failed to create recurring DVR rule', e);
    }
  }

  static async updateRecurringRule(ruleId, payload) {
    try {
      const response = await request(`${host}/api/channels/recurring-rules/${ruleId}/`, {
        method: 'PATCH',
        body: payload,
      });
      return response;
    } catch (e) {
      errorNotification(`Failed to update recurring rule ${ruleId}`, e);
    }
  }

  static async deleteRecurringRule(ruleId) {
    try {
      await request(`${host}/api/channels/recurring-rules/${ruleId}/`, {
        method: 'DELETE',
      });
    } catch (e) {
      errorNotification(`Failed to delete recurring rule ${ruleId}`, e);
    }
  }

  static async deleteRecording(id) {
    try {
      await request(`${host}/api/channels/recordings/${id}/`, { method: 'DELETE' });
      // Optimistically remove locally for instant UI update
      try { useChannelsStore.getState().removeRecording(id); } catch {}
    } catch (e) {
      errorNotification(`Failed to delete recording ${id}`, e);
    }
  }

  static async runComskip(recordingId) {
    try {
      const resp = await request(`${host}/api/channels/recordings/${recordingId}/comskip/`, {
        method: 'POST',
      });
      // Refresh recordings list to reflect comskip status when done later
      // This endpoint just queues the task; the websocket/refresh will update eventually
      return resp;
    } catch (e) {
      errorNotification('Failed to run comskip', e);
      throw e;
    }
  }

  // DVR Series Rules
  static async listSeriesRules() {
    try {
      const resp = await request(`${host}/api/channels/series-rules/`);
      return resp?.rules || [];
    } catch (e) {
      errorNotification('Failed to load series rules', e);
      return [];
    }
  }

  static async createSeriesRule(values) {
    try {
      const resp = await request(`${host}/api/channels/series-rules/`, {
        method: 'POST',
        body: values,
      });
      notifications.show({ title: 'Series rule saved' });
      return resp;
    } catch (e) {
      errorNotification('Failed to save series rule', e);
      throw e;
    }
  }

  static async deleteSeriesRule(tvgId) {
    try {
      await request(`${host}/api/channels/series-rules/${tvgId}/`, { method: 'DELETE' });
      notifications.show({ title: 'Series rule removed' });
    } catch (e) {
      errorNotification('Failed to remove series rule', e);
      throw e;
    }
  }

  static async deleteAllUpcomingRecordings() {
    try {
      const resp = await request(`${host}/api/channels/recordings/bulk-delete-upcoming/`, {
        method: 'POST',
      });
      notifications.show({ title: `Removed ${resp.removed || 0} upcoming` });
      useChannelsStore.getState().fetchRecordings();
      return resp;
    } catch (e) {
      errorNotification('Failed to delete upcoming recordings', e);
      throw e;
    }
  }

  static async evaluateSeriesRules(tvgId = null) {
    try {
      await request(`${host}/api/channels/series-rules/evaluate/`, {
        method: 'POST',
        body: tvgId ? { tvg_id: tvgId } : {},
      });
    } catch (e) {
      errorNotification('Failed to evaluate series rules', e);
    }
  }

  static async bulkRemoveSeriesRecordings({ tvg_id, title = null, scope = 'title' }) {
    try {
      const resp = await request(`${host}/api/channels/series-rules/bulk-remove/`, {
        method: 'POST',
        body: { tvg_id, title, scope },
      });
      notifications.show({ title: `Removed ${resp.removed || 0} scheduled` });
      return resp;
    } catch (e) {
      errorNotification('Failed to bulk-remove scheduled recordings', e);
      throw e;
    }
  }

  static async switchStream(channelId, streamId) {
    try {
      const response = await request(
        `${host}/proxy/ts/change_stream/${channelId}`,
        {
          method: 'POST',
          body: { stream_id: streamId },
        }
      );

      return response;
    } catch (e) {
      errorNotification('Failed to switch stream', e);
      throw e;
    }
  }

  static async nextStream(channelId, streamId) {
    try {
      const response = await request(
        `${host}/proxy/ts/next_stream/${channelId}`,
        {
          method: 'POST',
          body: { stream_id: streamId },
        }
      );

      return response;
    } catch (e) {
      errorNotification('Failed to switch stream', e);
      throw e;
    }
  }

  static async batchSetEPG(associations) {
    try {
      const response = await request(
        `${host}/api/channels/channels/batch-set-epg/`,
        {
          method: 'POST',
          body: { associations },
        }
      );

      // If successful, requery channels to update UI
      if (response.success) {
        // Build message based on whether EPG sources need refreshing
        let message = `Updated ${response.channels_updated} channel${response.channels_updated !== 1 ? 's' : ''}`;
        if (response.programs_refreshed > 0) {
          message += `, refreshing ${response.programs_refreshed} EPG source${response.programs_refreshed !== 1 ? 's' : ''}`;
        }

        notifications.show({
          title: 'EPG Association',
          message: message,
          color: 'blue',
        });

        // First fetch the complete channel data
        await useChannelsStore.getState().fetchChannels();
        // Then refresh the current table view
        this.requeryChannels();
      }

      return response;
    } catch (e) {
      errorNotification('Failed to update channel EPGs', e);
    }
  }

  static async getChannel(id) {
    try {
      const response = await request(
        `${host}/api/channels/channels/${id}/?include_streams=true`
      );
      return response;
    } catch (e) {
      errorNotification('Failed to fetch channel details', e);
      return null;
    }
  }

  static async me() {
    return await request(`${host}/api/accounts/users/me/`);
  }

  static async getUsers() {
    try {
      const response = await request(`${host}/api/accounts/users/`);
      return response;
    } catch (e) {
      errorNotification('Failed to fetch users', e);
    }
  }

  static async createUser(body) {
    try {
      const response = await request(`${host}/api/accounts/users/`, {
        method: 'POST',
        body,
      });

      useUsersStore.getState().addUser(response);

      return response;
    } catch (e) {
      errorNotification('Failed to fetch users', e);
    }
  }

  static async updateUser(id, body) {
    try {
      const response = await request(`${host}/api/accounts/users/${id}/`, {
        method: 'PATCH',
        body,
      });

      useUsersStore.getState().updateUser(response);

      return response;
    } catch (e) {
      errorNotification('Failed to fetch users', e);
    }
  }

  static async deleteUser(id) {
    try {
      await request(`${host}/api/accounts/users/${id}/`, {
        method: 'DELETE',
      });

      useUsersStore.getState().removeUser(id);
    } catch (e) {
      errorNotification('Failed to delete user', e);
    }
  }

  static async rehashStreams() {
    try {
      const response = await request(`${host}/api/core/rehash-streams/`, {
        method: 'POST',
      });

      return response;
    } catch (e) {
      errorNotification('Failed to trigger stream rehash', e);
    }
  }

  static async getStreamsByIds(ids) {
    try {
      // Use POST for large ID lists to avoid URL length limitations
      if (ids.length > 50) {
        const response = await request(
          `${host}/api/channels/streams/by-ids/`,
          {
            method: 'POST',
            body: { ids },
          }
        );
        return response;
      } else {
        // Use GET for small ID lists for backward compatibility
        const params = new URLSearchParams();
        params.append('ids', ids.join(','));
        const response = await request(
          `${host}/api/channels/streams/?${params.toString()}`
        );
        return response.results || response;
      }
    } catch (e) {
      errorNotification('Failed to retrieve streams by IDs', e);
      throw e; // Re-throw to allow proper error handling in calling code
    }
  }

  // VOD Methods
  static async getMovies(params = new URLSearchParams()) {
    try {
      const response = await request(
        `${host}/api/vod/movies/?${params.toString()}`
      );
      return response;
    } catch (e) {
      // Don't show error notification for "Invalid page" errors as they're handled gracefully
      const isInvalidPage = e.body?.detail?.includes('Invalid page') ||
                           e.message?.includes('Invalid page');

      if (!isInvalidPage) {
        errorNotification('Failed to retrieve movies', e);
      }
      throw e;
    }
  }

  static async getSeries(params = new URLSearchParams()) {
    try {
      const response = await request(
        `${host}/api/vod/series/?${params.toString()}`
      );
      return response;
    } catch (e) {
      // Don't show error notification for "Invalid page" errors as they're handled gracefully
      const isInvalidPage = e.body?.detail?.includes('Invalid page') ||
                           e.message?.includes('Invalid page');

      if (!isInvalidPage) {
        errorNotification('Failed to retrieve series', e);
      }
      throw e;
    }
  }

  static async getAllContent(params = new URLSearchParams()) {
    try {
      console.log('Calling getAllContent with URL:', `${host}/api/vod/all/?${params.toString()}`);
      const response = await request(
        `${host}/api/vod/all/?${params.toString()}`
      );
      console.log('getAllContent raw response:', response);
      return response;
    } catch (e) {
      console.error('getAllContent error:', e);
      console.error('Error status:', e.status);
      console.error('Error body:', e.body);
      console.error('Error message:', e.message);

      // Don't show error notification for "Invalid page" errors as they're handled gracefully
      const isInvalidPage = e.body?.detail?.includes('Invalid page') ||
                           e.message?.includes('Invalid page');

      if (!isInvalidPage) {
        errorNotification('Failed to retrieve content', e);
      }
      throw e;
    }
  }

  static async getMovieDetails(movieId) {
    try {
      const response = await request(`${host}/api/vod/movies/${movieId}/`);
      return response;
    } catch (e) {
      errorNotification('Failed to retrieve movie details', e);
    }
  }

  static async getMovieProviderInfo(movieId) {
    try {
      const response = await request(
        `${host}/api/vod/movies/${movieId}/provider-info/`
      );
      return response;
    } catch (e) {
      errorNotification('Failed to retrieve movie provider info', e);
    }
  }

  static async getMovieProviders(movieId) {
    try {
      const response = await request(
        `${host}/api/vod/movies/${movieId}/providers/`
      );
      return response;
    } catch (e) {
      errorNotification('Failed to retrieve movie providers', e);
    }
  }

  static async getSeriesProviders(seriesId) {
    try {
      const response = await request(
        `${host}/api/vod/series/${seriesId}/providers/`
      );
      return response;
    } catch (e) {
      errorNotification('Failed to retrieve series providers', e);
    }
  }

  static async getVODCategories() {
    try {
      const response = await request(`${host}/api/vod/categories/`);
      return response;
    } catch (e) {
      errorNotification('Failed to retrieve VOD categories', e);
    }
  }

  static async getSeriesInfo(seriesId) {
    try {
      // Call the provider-info endpoint that includes episodes
      const response = await request(
        `${host}/api/vod/series/${seriesId}/provider-info/?include_episodes=true`
      );
      return response;
    } catch (e) {
      errorNotification('Failed to retrieve series info', e);
    }
  }

  static async updateVODPosition(vodUuid, clientId, position) {
    try {
      const response = await request(
        `${host}/proxy/vod/stream/${vodUuid}/position/`,
        {
          method: 'POST',
          body: { client_id: clientId, position },
        }
      );
      return response;
    } catch (e) {
      errorNotification('Failed to update playback position', e);
    }
  }

  static async getSystemEvents(limit = 100, offset = 0, eventType = null) {
    try {
      const params = new URLSearchParams();
      params.append('limit', limit);
      params.append('offset', offset);
      if (eventType) {
        params.append('event_type', eventType);
      }
      const response = await request(
        `${host}/api/core/system-events/?${params.toString()}`
      );
      return response;
    } catch (e) {
      errorNotification('Failed to retrieve system events', e);
    }
  }
}
