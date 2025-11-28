import React, { useState, useEffect } from 'react';
import {
  Accordion,
  Alert,
  Button,
  Flex,
  Group,
  NumberInput,
  Select,
  Stack,
  Switch,
  Text,
  TextInput,
  JsonInput,
} from '@mantine/core';
import { useForm } from '@mantine/form';
import { notifications } from '@mantine/notifications';
import { Check, AlertCircle } from 'lucide-react';
import API from '../api';

const HLSOutputSettings = () => {
  const [loading, setLoading] = useState(false);
  const [saved, setSaved] = useState(false);
  const [profiles, setProfiles] = useState([]);
  const [selectedProfile, setSelectedProfile] = useState(null);

  const form = useForm({
    initialValues: {
      name: '',
      description: '',
      segment_duration: 4,
      max_playlist_segments: 10,
      segment_format: 'mpegts',
      playlist_type: 'event',
      dvr_window_seconds: 7200,
      enable_abr: true,
      qualities: JSON.stringify([
        {
          name: '2160p',
          resolution: '3840x2160',
          video_bitrate: '16000k',
          audio_bitrate: '192k',
          description: '4K UHD'
        },
        {
          name: '1440p',
          resolution: '2560x1440',
          video_bitrate: '10000k',
          audio_bitrate: '192k',
          description: '2K QHD'
        },
        {
          name: '1080p',
          resolution: '1920x1080',
          video_bitrate: '5000k',
          audio_bitrate: '128k',
          description: 'Full HD'
        },
        {
          name: '720p',
          resolution: '1280x720',
          video_bitrate: '2800k',
          audio_bitrate: '128k',
          description: 'HD'
        },
        {
          name: '480p',
          resolution: '854x480',
          video_bitrate: '1400k',
          audio_bitrate: '96k',
          description: 'SD'
        },
        {
          name: '360p',
          resolution: '640x360',
          video_bitrate: '800k',
          audio_bitrate: '96k',
          description: 'Low'
        }
      ], null, 2),
      enable_ll_hls: false,
      partial_segment_duration: 0.33,
      storage_path: '/var/www/hls',
      use_memory_storage: false,
      auto_cleanup: true,
      cleanup_interval_seconds: 60,
      enable_auto_restart: true,
      playlist_cache_ttl: 2,
      segment_cache_ttl: 86400,
      enable_cdn: false,
      cdn_base_url: '',
    },
  });

  useEffect(() => {
    loadProfiles();
  }, []);

  const loadProfiles = async () => {
    try {
      const response = await API.get('/hls/profiles/');
      setProfiles(response.data || []);
    } catch (error) {
      console.error('Failed to load HLS profiles:', error);
    }
  };

  const handleProfileSelect = async (profileId) => {
    if (!profileId) {
      form.reset();
      setSelectedProfile(null);
      return;
    }

    try {
      const response = await API.get(`/hls/profiles/${profileId}/`);
      const profile = response.data;
      
      form.setValues({
        ...profile,
        qualities: JSON.stringify(profile.qualities || [], null, 2),
      });
      
      setSelectedProfile(profileId);
    } catch (error) {
      notifications.show({
        title: 'Error',
        message: 'Failed to load profile',
        color: 'red',
        icon: <AlertCircle size={16} />,
      });
    }
  };

  const handleSubmit = async (values) => {
    setLoading(true);
    setSaved(false);

    try {
      // Parse qualities JSON
      let qualitiesData;
      try {
        qualitiesData = JSON.parse(values.qualities);
      } catch (e) {
        notifications.show({
          title: 'Invalid JSON',
          message: 'Qualities field must be valid JSON',
          color: 'red',
          icon: <AlertCircle size={16} />,
        });
        setLoading(false);
        return;
      }

      const payload = {
        ...values,
        qualities: qualitiesData,
      };

      if (selectedProfile) {
        // Update existing profile
        await API.put(`/hls/profiles/${selectedProfile}/`, payload);
      } else {
        // Create new profile
        await API.post('/hls/profiles/', payload);
      }

      setSaved(true);
      await loadProfiles();

      notifications.show({
        title: 'Success',
        message: 'HLS Output profile saved successfully',
        color: 'green',
        icon: <Check size={16} />,
      });

      setTimeout(() => setSaved(false), 3000);
    } catch (error) {
      notifications.show({
        title: 'Error',
        message: error.response?.data?.detail || 'Failed to save profile',
        color: 'red',
        icon: <AlertCircle size={16} />,
      });
    } finally {
      setLoading(false);
    }
  };

  const handleDelete = async () => {
    if (!selectedProfile) return;

    if (!confirm('Are you sure you want to delete this profile?')) return;

    try {
      await API.delete(`/hls/profiles/${selectedProfile}/`);
      
      notifications.show({
        title: 'Success',
        message: 'Profile deleted successfully',
        color: 'green',
        icon: <Check size={16} />,
      });

      form.reset();
      setSelectedProfile(null);
      await loadProfiles();
    } catch (error) {
      notifications.show({
        title: 'Error',
        message: 'Failed to delete profile',
        color: 'red',
        icon: <AlertCircle size={16} />,
      });
    }
  };

  return (
    <Stack gap="md">
      {saved && (
        <Alert variant="light" color="green" title="Saved Successfully">
          HLS Output profile has been saved.
        </Alert>
      )}

      <Select
        label="Select Profile"
        placeholder="Create new profile or select existing"
        data={[
          { value: '', label: '-- Create New Profile --' },
          ...profiles.map(p => ({ value: p.id.toString(), label: p.name }))
        ]}
        value={selectedProfile?.toString() || ''}
        onChange={handleProfileSelect}
      />

      <form onSubmit={form.onSubmit(handleSubmit)}>
        <Accordion variant="separated" defaultValue="basic">
          {/* Basic Settings */}
          <Accordion.Item value="basic">
            <Accordion.Control>Basic Settings</Accordion.Control>
            <Accordion.Panel>
              <Stack gap="sm">
                <TextInput
                  label="Profile Name"
                  placeholder="My HLS Profile"
                  required
                  {...form.getInputProps('name')}
                />
                <TextInput
                  label="Description"
                  placeholder="Profile description"
                  {...form.getInputProps('description')}
                />
              </Stack>
            </Accordion.Panel>
          </Accordion.Item>

          {/* Segment Settings */}
          <Accordion.Item value="segment">
            <Accordion.Control>Segment Settings</Accordion.Control>
            <Accordion.Panel>
              <Stack gap="sm">
                <NumberInput
                  label="Segment Duration (seconds)"
                  description="Duration of each HLS segment (2-10 seconds)"
                  min={2}
                  max={10}
                  {...form.getInputProps('segment_duration')}
                />
                <NumberInput
                  label="Max Playlist Segments"
                  description="Maximum number of segments in playlist"
                  min={3}
                  max={20}
                  {...form.getInputProps('max_playlist_segments')}
                />
                <Select
                  label="Segment Format"
                  description="Container format for segments"
                  data={[
                    { value: 'mpegts', label: 'MPEG-TS (Legacy, Best Compatibility)' },
                    { value: 'fmp4', label: 'Fragmented MP4 (Modern, LL-HLS)' }
                  ]}
                  {...form.getInputProps('segment_format')}
                />
                <Select
                  label="Playlist Type"
                  description="HLS playlist type"
                  data={[
                    { value: 'live', label: 'Live (No DVR)' },
                    { value: 'event', label: 'Event (DVR Enabled)' },
                    { value: 'vod', label: 'VOD (Video on Demand)' }
                  ]}
                  {...form.getInputProps('playlist_type')}
                />
              </Stack>
            </Accordion.Panel>
          </Accordion.Item>

          {/* DVR Settings */}
          <Accordion.Item value="dvr">
            <Accordion.Control>DVR Settings</Accordion.Control>
            <Accordion.Panel>
              <Stack gap="sm">
                <NumberInput
                  label="DVR Window (seconds)"
                  description="How long to keep segments for DVR (0 = disabled, max 86400 = 24 hours)"
                  min={0}
                  max={86400}
                  {...form.getInputProps('dvr_window_seconds')}
                />
                <Text size="sm" c="dimmed">
                  DVR window allows viewers to pause, rewind, and time-shift live streams.
                  Recommended: 7200 seconds (2 hours) for live TV.
                </Text>
              </Stack>
            </Accordion.Panel>
          </Accordion.Item>

          {/* Quality & Bitrate */}
          <Accordion.Item value="quality">
            <Accordion.Control>Quality & Bitrate</Accordion.Control>
            <Accordion.Panel>
              <Stack gap="sm">
                <Switch
                  label="Enable Adaptive Bitrate (ABR)"
                  description="Generate multiple quality levels for adaptive streaming"
                  {...form.getInputProps('enable_abr', { type: 'checkbox' })}
                />
                {form.values.enable_abr && (
                  <JsonInput
                    label="Quality Ladder"
                    description="JSON array of quality profiles (includes 4K UHD support)"
                    placeholder="Enter quality profiles as JSON"
                    minRows={10}
                    maxRows={20}
                    formatOnBlur
                    autosize
                    {...form.getInputProps('qualities')}
                  />
                )}
                <Text size="sm" c="dimmed">
                  Default quality ladder includes: 4K UHD (2160p), 2K QHD (1440p), Full HD (1080p), HD (720p), SD (480p), Low (360p)
                </Text>
              </Stack>
            </Accordion.Panel>
          </Accordion.Item>

          {/* Low-Latency HLS */}
          <Accordion.Item value="ll-hls">
            <Accordion.Control>Low-Latency HLS</Accordion.Control>
            <Accordion.Panel>
              <Stack gap="sm">
                <Switch
                  label="Enable Low-Latency HLS (LL-HLS)"
                  description="Reduce latency to ~3 seconds (requires fMP4 format)"
                  {...form.getInputProps('enable_ll_hls', { type: 'checkbox' })}
                />
                {form.values.enable_ll_hls && (
                  <>
                    <NumberInput
                      label="Partial Segment Duration (seconds)"
                      description="Duration of partial segments for LL-HLS"
                      min={0.1}
                      max={1.0}
                      step={0.01}
                      precision={2}
                      {...form.getInputProps('partial_segment_duration')}
                    />
                    <Alert color="blue" title="LL-HLS Requirements">
                      Low-Latency HLS requires:
                      <ul>
                        <li>Segment Format: Fragmented MP4 (fMP4)</li>
                        <li>HTTP/2 support (enabled by default in Nginx)</li>
                        <li>Compatible HLS player (hls.js v1.0+)</li>
                      </ul>
                    </Alert>
                  </>
                )}
              </Stack>
            </Accordion.Panel>
          </Accordion.Item>

          {/* Storage Settings */}
          <Accordion.Item value="storage">
            <Accordion.Control>Storage Settings</Accordion.Control>
            <Accordion.Panel>
              <Stack gap="sm">
                <TextInput
                  label="Storage Path"
                  description="Base path for storing HLS segments"
                  placeholder="/var/www/hls"
                  {...form.getInputProps('storage_path')}
                />
                <Switch
                  label="Use Memory Storage"
                  description="Store segments in RAM (/dev/shm) for better performance"
                  {...form.getInputProps('use_memory_storage', { type: 'checkbox' })}
                />
                {form.values.use_memory_storage && (
                  <Alert color="yellow" title="Memory Storage Warning">
                    Memory storage provides best performance but segments are lost on restart.
                    Ensure sufficient RAM is available (estimate: bitrate × DVR window).
                  </Alert>
                )}
              </Stack>
            </Accordion.Panel>
          </Accordion.Item>

          {/* Cleanup Settings */}
          <Accordion.Item value="cleanup">
            <Accordion.Control>Cleanup Settings</Accordion.Control>
            <Accordion.Panel>
              <Stack gap="sm">
                <Switch
                  label="Auto Cleanup"
                  description="Automatically delete old segments outside DVR window"
                  {...form.getInputProps('auto_cleanup', { type: 'checkbox' })}
                />
                {form.values.auto_cleanup && (
                  <>
                    <NumberInput
                      label="Cleanup Interval (seconds)"
                      description="How often to run cleanup task"
                      min={10}
                      max={300}
                      {...form.getInputProps('cleanup_interval_seconds')}
                    />
                    <Switch
                      label="Enable Auto-Restart"
                      description="Automatically restart encoding on errors"
                      {...form.getInputProps('enable_auto_restart', { type: 'checkbox' })}
                    />
                  </>
                )}
              </Stack>
            </Accordion.Panel>
          </Accordion.Item>

          {/* Caching Settings */}
          <Accordion.Item value="caching">
            <Accordion.Control>Caching Settings</Accordion.Control>
            <Accordion.Panel>
              <Stack gap="sm">
                <NumberInput
                  label="Playlist Cache TTL (seconds)"
                  description="How long to cache playlists (keep short for DVR)"
                  min={1}
                  max={10}
                  {...form.getInputProps('playlist_cache_ttl')}
                />
                <NumberInput
                  label="Segment Cache TTL (seconds)"
                  description="How long to cache segments (can be long, segments are immutable)"
                  min={3600}
                  max={604800}
                  {...form.getInputProps('segment_cache_ttl')}
                />
                <Alert color="blue" title="Caching & DVR">
                  Short playlist cache (1-5s) is critical for DVR functionality.
                  Long segment cache (24h+) is safe because segments are immutable.
                </Alert>
              </Stack>
            </Accordion.Panel>
          </Accordion.Item>

          {/* CDN Settings */}
          <Accordion.Item value="cdn">
            <Accordion.Control>CDN Settings (Optional)</Accordion.Control>
            <Accordion.Panel>
              <Stack gap="sm">
                <Switch
                  label="Enable CDN"
                  description="Use CDN for segment delivery (optional enhancement)"
                  {...form.getInputProps('enable_cdn', { type: 'checkbox' })}
                />
                {form.values.enable_cdn && (
                  <>
                    <TextInput
                      label="CDN Base URL"
                      description="Base URL for CDN (e.g., https://cdn.example.com)"
                      placeholder="https://cdn.example.com"
                      {...form.getInputProps('cdn_base_url')}
                    />
                    <Alert color="blue" title="CDN is Optional">
                      HLS Output works perfectly without CDN using Nginx local cache.
                      CDN is only needed for global distribution or high viewer counts.
                    </Alert>
                  </>
                )}
              </Stack>
            </Accordion.Panel>
          </Accordion.Item>
        </Accordion>

        <Flex mt="md" justify="space-between">
          {selectedProfile && (
            <Button color="red" variant="outline" onClick={handleDelete}>
              Delete Profile
            </Button>
          )}
          <Group ml="auto">
            <Button variant="default" onClick={() => form.reset()}>
              Reset
            </Button>
            <Button type="submit" loading={loading}>
              {selectedProfile ? 'Update Profile' : 'Create Profile'}
            </Button>
          </Group>
        </Flex>
      </form>
    </Stack>
  );
};

export default HLSOutputSettings;

