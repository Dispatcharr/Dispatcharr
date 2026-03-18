import useSettingsStore from '../../../store/settings.jsx';
import useLocalStorage from '../../../hooks/useLocalStorage.jsx';
import useTablePreferences from '../../../hooks/useTablePreferences.jsx';
import {
  buildTimeZoneOptions,
  getDefaultTimeZone,
} from '../../../utils/dateTimeUtils.js';
import React, { useCallback, useEffect, useMemo, useRef } from 'react';
import { showNotification } from '../../../utils/notificationUtils.js';
import { Select, Switch, Stack } from '@mantine/core';
import { saveTimeZoneSetting } from '../../../utils/forms/settings/UiSettingsFormUtils.js';

const UiSettingsForm = React.memo(() => {
  const settings = useSettingsStore((s) => s.settings);

  const [timeFormat, setTimeFormat] = useLocalStorage('time-format', '12h');
  const [dateFormat, setDateFormat] = useLocalStorage('date-format', 'mdy');
  const [timeZone, setTimeZone] = useLocalStorage(
    'time-zone',
    getDefaultTimeZone()
  );

  // Use shared table preferences hook
  const { headerPinned, setHeaderPinned, tableSize, setTableSize } =
    useTablePreferences();

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
      const systemSettings = settings['system_settings'];
      const tzValue = systemSettings?.value?.time_zone;
      if (tzValue) {
        timeZoneSyncedRef.current = true;
        setTimeZone((prev) => (prev === tzValue ? prev : tzValue));
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
      case 'header-pinned':
        setHeaderPinned(value);
        break;
    }
  };

  return (
    <Stack gap="md">
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
      <Switch
        label="Pin Table Headers"
        description="Keep table headers visible when scrolling"
        checked={headerPinned}
        onChange={(event) =>
          onUISettingsChange('header-pinned', event.currentTarget.checked)
        }
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
    </Stack>
  );
});

export default UiSettingsForm;
