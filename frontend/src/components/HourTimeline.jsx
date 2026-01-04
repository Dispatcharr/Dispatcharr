import React from 'react';
import { Box, Text } from '@mantine/core';
import { format } from '../utils/dateTimeUtils.js';
import { HOUR_WIDTH } from '../pages/guideUtils.js';

const HourBlock = React.memo(({ hourData, timeFormat, formatDayLabel, handleTimeClick }) => {
  const { time, isNewDay } = hourData;

  return (
    <Box
      key={format(time)}
      style={{
        borderRight: '1px solid #8DAFAA',
        cursor: 'pointer',
        borderLeft: isNewDay ? '2px solid #3BA882' : 'none',
        backgroundColor: isNewDay ? '#1E2A27' : '#1B2421',
      }}
      w={HOUR_WIDTH}
      h={'40px'}
      pos='relative'
      c='#a0aec0'
      onClick={(e) => handleTimeClick(time, e)}
    >
      <Text
        size="sm"
        style={{ transform: 'none' }}
        pos='absolute'
        top={8}
        left={4}
        bdrs={2}
        lh={1.2}
        ta='left'
      >
        <Text
          span
          size="xs"
          display={'block'}
          opacity={0.7}
          fw={isNewDay ? 600 : 400}
          c={isNewDay ? '#3BA882' : undefined}
        >
          {formatDayLabel(time)}
        </Text>
        {format(time, timeFormat)}
        <Text span size="xs" ml={1} opacity={0.7} />
      </Text>

      <Box
        style={{
          backgroundColor: '#27272A',
          zIndex: 10,
        }}
        pos='absolute'
        left={0}
        top={0}
        bottom={0}
        w={'1px'}
      />

      <Box
        style={{ justifyContent: 'space-between' }}
        pos='absolute'
        bottom={0}
        w={'100%'}
        display={'flex'}
        p={'0 1px'}
      >
        {[15, 30, 45].map((minute) => (
          <Box
            key={minute}
            style={{ backgroundColor: '#718096' }}
            w={'1px'}
            h={'8px'}
            pos='absolute'
            bottom={0}
            left={`${(minute / 60) * 100}%`}
          />
        ))}
      </Box>
    </Box>
  );
});

const HourTimeline = React.memo(({
   hourTimeline,
   timeFormat,
   formatDayLabel,
   handleTimeClick
 }) => {
  return (
    <>
      {hourTimeline.map((hourData) => (
        <HourBlock
          key={format(hourData.time)}
          hourData={hourData}
          timeFormat={timeFormat}
          formatDayLabel={formatDayLabel}
          handleTimeClick={handleTimeClick}
        />
      ))}
    </>
  );
});

export default HourTimeline;
