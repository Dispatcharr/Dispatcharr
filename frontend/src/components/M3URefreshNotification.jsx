// frontend/src/components/FloatingVideo.js
import React, { useState } from 'react';
import usePlaylistsStore from '../store/playlists';
import { notifications } from '@mantine/notifications';
import { IconCheck } from '@tabler/icons-react';

export default function M3URefreshNotification() {
  const { playlists, refreshProgress, removeRefreshProgress } =
    usePlaylistsStore();
  const [progress, setProgress] = useState({});

  const clearAccountNotification = (id) => {
    removeRefreshProgress(id);
    setProgress({
      ...progress,
      [id]: null,
    });
  };

  for (const id in refreshProgress) {
    const playlist = playlists.find((pl) => pl.id == id);
    if (!progress[id]) {
      if (refreshProgress[id] == 100) {
        // This situation is if it refreshes so fast we only get the 100% complete notification
        const notificationId = notifications.show({
          loading: false,
          title: `M3U Refresh: ${playlist.name}`,
          message: `Refresh complete!`,
          icon: <IconCheck />,
        });
        setProgress({
          ...progress,
          [id]: notificationId,
        });
        setTimeout(() => clearAccountNotification(id), 2000);

        return;
      }

      console.log('starting progress bar');
      const notificationId = notifications.show({
        loading: true,
        title: `M3U Refresh: ${playlist.name}`,
        message: `Starting...`,
        autoClose: false,
        withCloseButton: false,
      });

      setProgress({
        ...progress,
        [id]: notificationId,
      });
    } else {
      if (refreshProgress[id] == 0) {
        notifications.update({
          id: progress[id],
          message: `Starting...`,
        });
      } else if (refreshProgress[id] == 100) {
        notifications.update({
          id: progress[id],
          message: `Refresh complete!`,
          loading: false,
          autoClose: 2000,
          icon: <IconCheck />,
        });

        setTimeout(() => clearAccountNotification(id), 2000);
      } else {
        notifications.update({
          id: progress[id],
          message: `Updating M3U: ${refreshProgress[id]}%`,
        });
      }
    }
  }

  return <></>;
}
