import React, { useEffect, useState } from 'react';
import {
  Alert,
  Button,
  Checkbox,
  Group,
  Modal,
  Stack,
  Text,
} from '@mantine/core';
import { RefreshCw } from 'lucide-react';
import { VOD_PROFILE_REBUILD_EVENT } from '../utils/vodProfileUpdates.js';

const SUPPRESSION_KEY = 'vod-profile-rebuild-notice-suppressed';

const VODProfileRebuildNotice = ({ onOpenProfiles }) => {
  const [profilesAffected, setProfilesAffected] = useState(0);
  const [dontAskAgain, setDontAskAgain] = useState(false);

  useEffect(() => {
    const showNotice = (event) => {
      if (window.localStorage.getItem(SUPPRESSION_KEY) === 'true') return;
      setProfilesAffected(Number(event?.detail?.profilesAffected || 0));
    };
    window.addEventListener(VOD_PROFILE_REBUILD_EVENT, showNotice);
    return () =>
      window.removeEventListener(VOD_PROFILE_REBUILD_EVENT, showNotice);
  }, []);

  const close = () => {
    if (dontAskAgain) {
      window.localStorage.setItem(SUPPRESSION_KEY, 'true');
    }
    setProfilesAffected(0);
    setDontAskAgain(false);
  };
  const openProfiles = () => {
    close();
    onOpenProfiles?.();
  };

  return (
    <Modal
      opened={profilesAffected > 0}
      onClose={close}
      title="Output profile rebuild required"
      centered
    >
      <Stack>
        <Alert color="yellow" icon={<RefreshCw size={17} />}>
          {profilesAffected === 1
            ? 'One prepared output profile is now outdated.'
            : `${profilesAffected} prepared output profiles are now outdated.`}
        </Alert>
        <Text size="sm">
          The saved VOD data is available in management immediately. Clients
          continue receiving each last completed profile catalog until its
          rebuild finishes. The change will be included in the next rebuild.
          Start it from Output profiles when you want the change published.
        </Text>
        <Checkbox
          label="Don't ask again"
          checked={dontAskAgain}
          onChange={(event) => setDontAskAgain(event.currentTarget.checked)}
        />
        <Group justify="flex-end">
          <Button variant="default" onClick={close}>
            Later
          </Button>
          <Button leftSection={<RefreshCw size={15} />} onClick={openProfiles}>
            Open output profiles
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
};

export default VODProfileRebuildNotice;
