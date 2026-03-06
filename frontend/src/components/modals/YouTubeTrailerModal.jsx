import { Box, Modal } from '@mantine/core';
import React from 'react';

export const YouTubeTrailerModal = ({ opened, onClose, trailerUrl }) => {
  return (
    <Modal opened={opened} onClose={onClose} title="Trailer" size="xl" centered>
      <Box pos="relative" pb={'56.25%'} h={0}>
        {trailerUrl && (
          <iframe
            src={trailerUrl}
            title="YouTube Trailer"
            frameBorder="0"
            allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share"
            referrerPolicy="strict-origin-when-cross-origin"
            allowFullScreen
            style={{
              position: 'absolute',
              top: 0,
              left: 0,
              width: '100%',
              height: '100%',
              borderRadius: 8,
            }}
          />
        )}
      </Box>
    </Modal>
  );
};