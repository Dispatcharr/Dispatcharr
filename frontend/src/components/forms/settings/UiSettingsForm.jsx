import useSettingsStore from '../../../store/settings.jsx';
import useLocalStorage from '../../../hooks/useLocalStorage.jsx';
import {
  buildTimeZoneOptions,
  getDefaultTimeZone,
} from '../../../utils/dateTimeUtils.js';
import React, { useCallback, useEffect, useMemo, useRef } from 'react';
import { showNotification } from '../../../utils/notificationUtils.js';
import { Select } from '@mantine/core';
import { saveTimeZoneSetting } from '../../../utils/forms/settings/UiSettingsFormUtils.js';

const UiSettingsForm = React.memo(() => {
  const settings = useSettingsStore((s) => s.settings);

  const [tableSize, setTableSize] = useLocalStorage('table-size', 'default');
  const [timeFormat, setTimeFormat] = useLocalStorage('time-format', '12h');
  const [dateFormat, setDateFormat] = useLocalStorage('date-format', 'mdy');
  const [timeZone, setTimeZone] = useLocalStorage(
    'time-zone',
    getDefaultTimeZone()
  );

  const timeZoneOptions = useMemo(
    () => buildTimeZoneOptions(timeZone),
    [timeZone]
  );

  const timeZoneSyncedRef = useRef(false);

  const persistTimeZoneSetting = useCallback(
    async (tzValue) => {
      try {
        await saveTimeZoneSetting(tzValue, settings);
      } catch (error) {
        console.error('Failed to persist time zone setting', error);
        showNotification({
          title: 'Failed to update time zone',
          message: 'Could not save the selected time zone. Please try again.',
          color: 'red',
        });
      }
    },
    [settings]
  );

  useEffect(() => {
    if (settings) {
      const tzSetting = settings['system-time-zone'];
      if (tzSetting?.value) {
        timeZoneSyncedRef.current = true;
        setTimeZone((prev) =>
          prev === tzSetting.value ? prev : tzSetting.value
        );
      } else if (!timeZoneSyncedRef.current && timeZone) {
        timeZoneSyncedRef.current = true;
        persistTimeZoneSetting(timeZone);
      }
    }
  }, [settings, timeZone, setTimeZone, persistTimeZoneSetting]);

  const onUISettingsChange = (name, value) => {
    switch (name) {
      case 'table-size':
        if (value) setTableSize(value);
        break;
      case 'time-format':
        if (value) setTimeFormat(value);
        break;
      case 'date-format':
        if (value) setDateFormat(value);
        break;
      case 'time-zone':
        if (value) {
          setTimeZone(value);
          persistTimeZoneSetting(value);
        }
        break;
    }
  };

  return (
    <>
      <Select
        label="Table Size"
        value={tableSize}
        onChange={(val) => onUISettingsChange('table-size', val)}
        data={[
          {
            value: 'default',
            label: 'Default',
          },
          {
            value: 'compact',
            label: 'Compact',
          },
          {
            value: 'large',
            label: 'Large',
          },
        ]}
      />
      <Select
        label="Time format"
        value={timeFormat}
        onChange={(val) => onUISettingsChange('time-format', val)}
        data={[
          {
            value: '12h',
            label: '12 hour time',
          },
          {
            value: '24h',
            label: '24 hour time',
          },
        ]}
      />
      <Select
        label="Date format"
        value={dateFormat}
        onChange={(val) => onUISettingsChange('date-format', val)}
        data={[
          {
            value: 'mdy',
            label: 'MM/DD/YYYY',
          },
          {
            value: 'dmy',
            label: 'DD/MM/YYYY',
          },
        ]}
      />
      <Select
        label="Time zone"
        searchable
        nothingFoundMessage="No matches"
        value={timeZone}
        onChange={(val) => onUISettingsChange('time-zone', val)}
        data={timeZoneOptions}
      />
    </>
  );
});

export default UiSettingsForm;