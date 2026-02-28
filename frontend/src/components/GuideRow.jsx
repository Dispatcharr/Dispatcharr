import React, { useState } from 'react';
import {
  CHANNEL_WIDTH,
  EXPANDED_PROGRAM_HEIGHT,
  HOUR_WIDTH,
  MINUTE_BLOCK_WIDTH,
  MINUTE_INCREMENT,
  PROGRAM_HEIGHT,
} from '../pages/guideUtils.js';
import { Box, Flex, Text } from '@mantine/core';
import { Play } from 'lucide-react';
import logo from '../images/logo.png';

// Buffer in pixels beyond the viewport edges to render programs.
// This prevents pop-in when scrolling horizontally.
const H_BUFFER = 600;

const GuideRow = React.memo(({ index, style, data }) => {
  const {
    filteredChannels,
    programsByChannelId,
    expandedProgramId,
    rowHeights,
    logos,
    renderProgram,
    handleLogoClick,
    contentWidth,
    guideScrollLeftRef,
    viewportWidth,
    timelineStartMs,
  } = data;

  const [hovered, setHovered] = useState(false);

  const channel = filteredChannels[index];
  if (!channel) {
    return null;
  }

  const channelPrograms = programsByChannelId.get(channel.id) || [];
  const rowHeight =
    rowHeights[index] ??
    (channelPrograms.some((program) => program.id === expandedProgramId)
      ? EXPANDED_PROGRAM_HEIGHT
      : PROGRAM_HEIGHT);

  // Horizontal viewport culling — only render programs whose pixel range
  // overlaps the visible scroll window (plus a buffer to avoid pop-in).
  const scrollLeft = guideScrollLeftRef.current;
  const vpLeft = scrollLeft - H_BUFFER;
  const vpRight = scrollLeft + viewportWidth + H_BUFFER;

  const visiblePrograms = channelPrograms.filter((program) => {
    const leftPx =
      ((program.startMs - timelineStartMs) / 60000 / MINUTE_INCREMENT) *
      MINUTE_BLOCK_WIDTH;
    const durationMin = (program.endMs - program.startMs) / 60000;
    const widthPx = (durationMin / MINUTE_INCREMENT) * MINUTE_BLOCK_WIDTH;
    // Program is visible if its right edge is past vpLeft AND left edge is before vpRight
    return leftPx + widthPx > vpLeft && leftPx < vpRight;
  });

  const PlaceholderProgram = () => {
    // Only render placeholder blocks that overlap the viewport
    const totalPlaceholders = Math.ceil(24 / 2);
    const blockWidth = HOUR_WIDTH * 2;
    return (
      <>
        {Array.from({ length: totalPlaceholders }).map(
          (_, placeholderIndex) => {
            const left = placeholderIndex * blockWidth;
            if (left + blockWidth < vpLeft || left > vpRight) return null;
            return (
              <Box
                key={`placeholder-${channel.id}-${placeholderIndex}`}
                style={{
                  alignItems: 'center',
                  justifyContent: 'center',
                }}
                pos="absolute"
                left={left}
                top={0}
                w={blockWidth}
                h={rowHeight - 4}
                bd={'1px dashed #2D3748'}
                bdrs={4}
                display={'flex'}
                c="#4A5568"
              >
                <Text size="sm">No program data</Text>
              </Box>
            );
          }
        )}
      </>
    );
  };

  return (
    <div
      data-testid="guide-row"
      style={{ ...style, width: contentWidth, height: rowHeight }}
    >
      <Box
        style={{
          borderBottom: '0px solid #27272A',
          transition: 'height 0.2s ease',
          overflow: 'visible',
        }}
        display={'flex'}
        h={'100%'}
        pos="relative"
      >
        <Box
          className="channel-logo"
          style={{
            flexShrink: 0,
            alignItems: 'center',
            justifyContent: 'center',
            backgroundColor: '#18181B',
            borderRight: '1px solid #27272A',
            borderBottom: '1px solid #27272A',
            boxShadow: '2px 0 5px rgba(0,0,0,0.2)',
            zIndex: 30,
            transition: 'height 0.2s ease',
            cursor: 'pointer',
          }}
          w={CHANNEL_WIDTH}
          miw={CHANNEL_WIDTH}
          display={'flex'}
          left={0}
          h={'100%'}
          pos="relative"
          onClick={(event) => handleLogoClick(channel, event)}
          onMouseEnter={() => setHovered(true)}
          onMouseLeave={() => setHovered(false)}
        >
          {hovered && (
            <Flex
              align="center"
              justify="center"
              style={{
                backgroundColor: 'rgba(0, 0, 0, 0.7)',
                zIndex: 10,
                animation: 'fadeIn 0.2s',
              }}
              pos="absolute"
              top={0}
              left={0}
              right={0}
              bottom={0}
              w={'100%'}
              h={'100%'}
            >
              <Play size={32} color="#fff" fill="#fff" />
            </Flex>
          )}

          <Flex
            direction="column"
            align="center"
            justify="space-between"
            style={{
              boxSizing: 'border-box',
              zIndex: 5,
            }}
            w={'100%'}
            h={'100%'}
            p={'4px'}
            pos="relative"
          >
            <Box
              style={{
                alignItems: 'center',
                justifyContent: 'center',
                overflow: 'hidden',
              }}
              w={'100%'}
              h={`${rowHeight - 32}px`}
              display={'flex'}
              p={'4px'}
              mb={'4px'}
            >
              <img
                src={logos[channel.logo_id]?.cache_url || logo}
                alt={channel.name}
                style={{
                  maxWidth: '100%',
                  maxHeight: '100%',
                  objectFit: 'contain',
                }}
              />
            </Box>

            <Text
              size="sm"
              weight={600}
              style={{
                transform: 'translateX(-50%)',
                backgroundColor: '#18181B',
                alignItems: 'center',
                justifyContent: 'center',
              }}
              pos="absolute"
              bottom={4}
              left={'50%'}
              p={'2px 8px'}
              bdrs={4}
              fz={'0.85em'}
              bd={'1px solid #27272A'}
              h={'24px'}
              display={'flex'}
              miw={'36px'}
            >
              {channel.channel_number || '-'}
            </Text>
          </Flex>
        </Box>

        <Box
          style={{
            transition: 'height 0.2s ease',
          }}
          flex={1}
          pos="relative"
          h={'100%'}
          pl={0}
        >
          {visiblePrograms.length > 0 ? (
            visiblePrograms.map((program) =>
              renderProgram(program, undefined, channel)
            )
          ) : channelPrograms.length > 0 ? null : (
            <PlaceholderProgram />
          )}
        </Box>
      </Box>
    </div>
  );
});

export default GuideRow;
