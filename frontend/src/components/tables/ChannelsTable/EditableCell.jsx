import React, { memo, useCallback, useEffect, useMemo, useRef, useState, } from 'react';
import { Box, NumberInput, Select, Skeleton, TextInput, Tooltip, } from '@mantine/core';
import useChannelsTableStore from '../../../store/channelsTable';
import useLogosStore from '../../../store/logos';
import { requeryChannels, updateChannel, } from '../../../utils/forms/ChannelUtils.js';
import { showNotification } from '../../../utils/notificationUtils.js';
import {
  buildInlinePatch,
  getEpgOptions,
  getLogoOptions,
} from '../../../utils/tables/ChannelsTableUtils.js';

// Surfaces server-side validation failures so the user knows the
// inline edit was rejected (otherwise the cell silently reverts).
// Exported so unit tests can verify the message composition without
// mounting the component.
export const notifyInlineSaveError = (columnId, error) => {
  const detail =
    error?.body?.detail ||
    error?.body?.[columnId]?.[0] ||
    error?.body?.error ||
    error?.message ||
    'Server rejected the change';
  showNotification({
    title: 'Edit not saved',
    message: String(detail),
    color: 'red',
    autoClose: 5000,
  });
};

// Lightweight wrapper that only renders full editable cell when unlocked
// This prevents 250+ heavy component instances when table is locked
const EditableCellWrapper = memo(
  ({ children, getValue, isUnlocked, renderLocked }) => {
    if (!isUnlocked) {
      // Render lightweight locked view
      return renderLocked ? (
        renderLocked(getValue())
      ) : (
        <Box
          style={{
            whiteSpace: 'nowrap',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            padding: '0 4px',
          }}
        >
          {getValue() ?? ''}
        </Box>
      );
    }
    // Only render heavy component when unlocked
    return children;
  }
);

// Editable text cell
export const EditableTextCell = ({ row, column, getValue }) => {
  const isUnlocked = useChannelsTableStore((s) => s.isUnlocked);
  const [isFocused, setIsFocused] = useState(false);

  // When locked or not focused, show simple display
  if (!isUnlocked || !isFocused) {
    return (
      <Box
        onClick={() => isUnlocked && setIsFocused(true)}
        style={{
          whiteSpace: 'nowrap',
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          cursor: isUnlocked ? 'text' : 'default',
          padding: '0 4px',
        }}
      >
        {getValue() ?? ''}
      </Box>
    );
  }

  // Only mount heavy component when actually editing
  return (
    <EditableTextCellInner
      row={row}
      column={column}
      getValue={getValue}
      onBlur={() => setIsFocused(false)}
    />
  );
};

// Inner component with all the editing logic - only rendered when focused
const EditableTextCellInner = ({ row, column, getValue, onBlur }) => {
  const initialValue = getValue() || '';
  const [value, setValue] = useState(initialValue);
  const previousValue = useRef(initialValue);
  const isMounted = useRef(false);
  const debounceTimer = useRef(null);

  useEffect(() => {
    const currentValue = getValue() || '';
    if (currentValue !== previousValue.current) {
      setValue(currentValue);
      previousValue.current = currentValue;
    }
  }, [getValue]);

  const saveValue = useCallback(
    async (newValue) => {
      // Don't save if not mounted or value hasn't changed
      if (!isMounted.current || newValue === previousValue.current) {
        return;
      }

      try {
        const response = await updateChannel(
          buildInlinePatch(row.original, column.id, newValue)
        );
        previousValue.current = newValue;

        // Update the table store to reflect the change
        if (response) {
          useChannelsTableStore.getState().updateChannel(response);
        }
      } catch (error) {
        // Surface server-side errors (e.g. max_length=512, validator
        // rejection) so the user knows the change was not saved.
        notifyInlineSaveError(column.id, error);
        setValue(previousValue.current || '');
      }
    },
    [row.original, column.id]
  );

  useEffect(() => {
    isMounted.current = true;
    const timer = debounceTimer.current;
    return () => {
      isMounted.current = false;
      if (timer) {
        clearTimeout(timer);
      }
    };
  }, []);

  const handleChange = (e) => {
    const newValue = e.currentTarget.value;
    setValue(newValue);

    // Clear existing timer
    if (debounceTimer.current) {
      clearTimeout(debounceTimer.current);
    }

    // Set new timer
    debounceTimer.current = setTimeout(() => {
      saveValue(newValue);
    }, 500);
  };

  const handleBlur = () => {
    saveValue(value);
    onBlur();
  };

  return (
    <TextInput
      value={value}
      onChange={handleChange}
      onBlur={handleBlur}
      autoFocus
      size="xs"
      variant="unstyled"
      styles={{
        root: {
          width: '100%',
        },
        input: {
          minHeight: 'unset',
          height: '100%',
          width: '100%',
          padding: '0 4px',
          backgroundColor: 'rgba(255, 255, 255, 0.1)',
        },
      }}
    />
  );
};

// Editable number cell
export const EditableNumberCell = ({ row, column, getValue }) => {
  const isUnlocked = useChannelsTableStore((s) => s.isUnlocked);
  const [isFocused, setIsFocused] = useState(false);

  const value = getValue();
  const formattedValue =
    value !== null && value !== undefined
      ? value === Math.floor(value)
        ? Math.floor(value)
        : value
      : '';

  // When locked or not focused, show simple display
  if (!isUnlocked || !isFocused) {
    return (
      <Box
        onClick={() => isUnlocked && setIsFocused(true)}
        style={{
          textAlign: 'right',
          width: '100%',
          cursor: isUnlocked ? 'text' : 'default',
          padding: '0 4px',
        }}
      >
        {formattedValue}
      </Box>
    );
  }

  return (
    <EditableNumberCellInner
      row={row}
      column={column}
      getValue={getValue}
      onBlur={() => setIsFocused(false)}
    />
  );
};

// Inner component with all the editing logic - only rendered when focused
const EditableNumberCellInner = ({ row, column, getValue, onBlur }) => {
  const initialValue = getValue();
  const [value, setValue] = useState(initialValue);
  const previousValue = useRef(initialValue);
  const isMounted = useRef(false);

  useEffect(() => {
    const currentValue = getValue();
    if (currentValue !== previousValue.current) {
      setValue(currentValue);
      previousValue.current = currentValue;
    }
  }, [getValue]);

  const saveValue = useCallback(
    async (newValue) => {
      // Don't save if not mounted or value hasn't changed
      if (!isMounted.current || newValue === previousValue.current) {
        return;
      }

      // For channel_number, don't save null/undefined values
      if (
        column.id === 'channel_number' &&
        (newValue === null || newValue === undefined || newValue === '')
      ) {
        // Revert to previous value
        setValue(previousValue.current);
        return;
      }

      try {
        const response = await updateChannel(
          buildInlinePatch(row.original, column.id, newValue)
        );
        previousValue.current = newValue;

        // Update the table store to reflect the change
        if (response) {
          useChannelsTableStore.getState().updateChannel(response);

          // If channel_number was changed, refetch to reorder the table
          if (column.id === 'channel_number') {
            await requeryChannels();
            onBlur();
          }
        }
      } catch (error) {
        // Surface server-side errors (channel_number out-of-range,
        // collision, etc.) so the user knows the change was not saved.
        notifyInlineSaveError(column.id, error);
        setValue(previousValue.current);
      }
    },
    [row.original, column.id, onBlur]
  );

  useEffect(() => {
    isMounted.current = true;
    return () => {
      isMounted.current = false;
    };
  }, []);

  const handleChange = (newValue) => {
    setValue(newValue);
  };

  const handleBlur = () => {
    saveValue(value);
    onBlur();
  };

  return (
    <NumberInput
      value={value}
      onChange={handleChange}
      onBlur={handleBlur}
      autoFocus
      size="xs"
      variant="unstyled"
      hideControls
      styles={{
        input: {
          minHeight: 'unset',
          height: '100%',
          padding: '0 4px',
          textAlign: 'right',
          backgroundColor: 'rgba(255, 255, 255, 0.1)',
        },
      }}
    />
  );
};

// Editable select cell for groups
export const EditableGroupCell = ({ row, channelGroups }) => {
  const isUnlocked = useChannelsTableStore((s) => s.isUnlocked);
  const [isFocused, setIsFocused] = useState(false);
  const groupId = row.original.channel_group_id;
  const groupName = channelGroups[groupId]?.name || '';

  // Show simple display when locked OR when unlocked but not focused
  if (!isUnlocked || !isFocused) {
    return (
      <Box
        onClick={() => isUnlocked && setIsFocused(true)}
        style={{
          whiteSpace: 'nowrap',
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          padding: '0 4px',
          cursor: isUnlocked ? 'pointer' : 'default',
        }}
      >
        {groupName}
      </Box>
    );
  }

  return (
    <EditableGroupCellInner
      row={row}
      channelGroups={channelGroups}
      groupName={groupName}
      groupId={groupId}
      onBlur={() => setIsFocused(false)}
    />
  );
};

// Inner component with all the editing logic - only rendered when focused
const EditableGroupCellInner = ({
  row,
  channelGroups,
  groupName,
  groupId,
  onBlur,
}) => {
  const previousGroupId = useRef(groupId);
  const [searchValue, setSearchValue] = useState('');

  const saveValue = useCallback(
    async (newGroupId) => {
      // Don't save if value hasn't changed
      if (String(newGroupId) === String(previousGroupId.current)) {
        return;
      }

      try {
        const response = await updateChannel(
          buildInlinePatch(
            row.original,
            'channel_group_id',
            parseInt(newGroupId, 10)
          )
        );
        previousGroupId.current = newGroupId;

        // Update the table store to reflect the change
        if (response) {
          useChannelsTableStore.getState().updateChannel(response);
        }
      } catch (error) {
        console.error('Failed to update channel group:', error);
        notifyInlineSaveError(column.id, error);
      }
    },
    [row.original]
  );

  const handleChange = (newGroupId) => {
    saveValue(newGroupId);
    onBlur();
    setSearchValue('');
  };

  const groupOptions = Object.values(channelGroups).map((group) => ({
    value: String(group.id),
    label: group.name,
  }));

  return (
    <Select
      value={null}
      onChange={handleChange}
      onBlur={onBlur}
      data={groupOptions}
      size="xs"
      variant="unstyled"
      searchable
      searchValue={searchValue}
      onSearchChange={setSearchValue}
      autoFocus
      placeholder={groupName}
      nothingFoundMessage="No groups found"
      styles={{
        input: {
          minHeight: 'unset',
          height: '100%',
          padding: '0 4px',
          backgroundColor: 'rgba(255, 255, 255, 0.1)',
        },
      }}
    />
  );
};

// Editable select cell for EPG
export const EditableEPGCell = ({
  row,
  getValue,
  tvgsById,
  epgs,
  tvgsLoaded,
}) => {
  const isUnlocked = useChannelsTableStore((s) => s.isUnlocked);
  const [isFocused, setIsFocused] = useState(false);
  const epgDataId = getValue();

  // Format display text - needed for both locked and unlocked states
  const epgObj = epgDataId ? tvgsById[epgDataId] : null;
  const tvgId = epgObj?.tvg_id;
  const epgName =
    epgObj && epgObj.epg_source
      ? epgs[epgObj.epg_source]?.name || epgObj.epg_source
      : null;
  const displayText =
    epgObj && epgName
      ? `${epgObj.epg_source} - ${tvgId}`
      : epgObj
        ? epgObj.name
        : 'Not Assigned';

  // Show skeleton while EPG data is loading (only if channel has an EPG assignment)
  const isEpgDataPending = epgDataId && !epgObj && !tvgsLoaded;

  // Build tooltip content
  const tooltip = epgObj
    ? `${epgName ? `EPG Name: ${epgName}\n` : ''}${epgObj.name ? `TVG Name: ${epgObj.name}\n` : ''}${tvgId ? `TVG-ID: ${tvgId}` : ''}`.trim()
    : '';

  // Show simple display when locked OR when unlocked but not focused
  if (!isUnlocked || !isFocused) {
    // If loading EPG data, show skeleton
    if (isEpgDataPending) {
      return (
        <Box
          onClick={() => isUnlocked && setIsFocused(true)}
          style={{
            width: '100%',
            height: '100%',
            display: 'flex',
            alignItems: 'center',
            padding: '0 4px',
            cursor: isUnlocked ? 'pointer' : 'default',
          }}
        >
          <Skeleton
            height={18}
            width="70%"
            visible={true}
            animate={true}
            style={{ borderRadius: 4 }}
          />
        </Box>
      );
    }
    return (
      <Tooltip
        label={<span style={{ whiteSpace: 'pre-line' }}>{tooltip}</span>}
        withArrow
        position="top"
        disabled={!epgObj}
        openDelay={500}
      >
        <Box
          onClick={() => isUnlocked && setIsFocused(true)}
          style={{
            whiteSpace: 'nowrap',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            padding: '0 4px',
            cursor: isUnlocked ? 'pointer' : 'default',
          }}
        >
          {displayText}
        </Box>
      </Tooltip>
    );
  }

  return (
    <EditableEPGCellInner
      row={row}
      tvgsById={tvgsById}
      epgs={epgs}
      epgDataId={epgDataId}
      epgObj={epgObj}
      displayText={displayText}
      onBlur={() => setIsFocused(false)}
    />
  );
};

// Inner component with all the editing logic - only rendered when focused
const EditableEPGCellInner = ({
  row,
  tvgsById,
  epgs,
  epgDataId,
  displayText,
  onBlur,
}) => {
  const previousEpgDataId = useRef(epgDataId);
  const [searchValue, setSearchValue] = useState('');

  const saveValue = useCallback(
    async (newEpgDataId) => {
      // Don't save if value hasn't changed
      if (String(newEpgDataId) === String(previousEpgDataId.current)) {
        return;
      }

      try {
        const response = await updateChannel(
          buildInlinePatch(
            row.original,
            'epg_data_id',
            newEpgDataId === 'null' ? null : parseInt(newEpgDataId, 10)
          )
        );
        previousEpgDataId.current = newEpgDataId;

        // Update the table store to reflect the change
        if (response) {
          useChannelsTableStore.getState().updateChannel(response);
        }
      } catch (error) {
        console.error('Failed to update EPG:', error);
        notifyInlineSaveError(column.id, error);
      }
    },
    [row.original]
  );

  const handleChange = (newEpgDataId) => {
    saveValue(newEpgDataId);
    setSearchValue('');
    onBlur();
  };

  // Build EPG options
  const epgOptions = useMemo(() => {
    return getEpgOptions(tvgsById, epgs);
  }, [tvgsById, epgs]);

  return (
    <Select
      value={null}
      onChange={handleChange}
      onBlur={onBlur}
      data={epgOptions}
      size="xs"
      variant="unstyled"
      searchable
      searchValue={searchValue}
      onSearchChange={setSearchValue}
      autoFocus
      placeholder={displayText}
      nothingFoundMessage="No EPG found"
      styles={{
        input: {
          minHeight: 'unset',
          height: '100%',
          padding: '0 4px',
          backgroundColor: 'rgba(255, 255, 255, 0.1)',
        },
      }}
    />
  );
};

// Editable cell for Logo selection
export const EditableLogoCell = ({
  row,
  getValue,
  LazyLogo,
  ensureLogosLoaded,
}) => {
  const isUnlocked = useChannelsTableStore((s) => s.isUnlocked);
  const [isFocused, setIsFocused] = useState(false);
  const logoId = getValue();

  const handleClick = () => {
    if (isUnlocked) {
      // Ensure logos are loaded when user tries to edit
      ensureLogosLoaded?.();
      setIsFocused(true);
    }
  };

  // Show simple display when locked OR when unlocked but not focused
  if (!isUnlocked || !isFocused) {
    return (
      <Box
        onClick={handleClick}
        style={{
          width: '100%',
          height: '100%',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          cursor: isUnlocked ? 'pointer' : 'default',
        }}
      >
        {LazyLogo && (
          <LazyLogo
            logoId={logoId}
            alt="logo"
            style={{ maxHeight: 18, maxWidth: 55 }}
          />
        )}
      </Box>
    );
  }

  return (
    <EditableLogoCellInner
      row={row}
      logoId={logoId}
      onBlur={() => setIsFocused(false)}
    />
  );
};

// Inner component with all the editing logic - only rendered when focused
const EditableLogoCellInner = ({ row, logoId, onBlur }) => {
  // Subscribe directly to the logos store so we get updates when logos load
  const channelLogos = useLogosStore((s) => s.channelLogos);
  const previousLogoId = useRef(logoId);
  const [searchValue, setSearchValue] = useState('');

  const saveValue = useCallback(
    async (newLogoId) => {
      // Don't save if value hasn't changed
      if (String(newLogoId) === String(previousLogoId.current)) {
        return;
      }

      try {
        const response = await updateChannel(
          buildInlinePatch(
            row.original,
            'logo_id',
            newLogoId === 'null' ? null : parseInt(newLogoId, 10)
          )
        );
        previousLogoId.current = newLogoId;

        // Update the table store to reflect the change
        if (response) {
          useChannelsTableStore.getState().updateChannel(response);
        }
      } catch (error) {
        console.error('Failed to update logo:', error);
        notifyInlineSaveError(column.id, error);
      }
    },
    [row.original]
  );

  const handleChange = (newLogoId) => {
    saveValue(newLogoId);
    setSearchValue('');
    onBlur();
  };

  // Build logo options with logo data
  const logoOptions = useMemo(() => {
    return getLogoOptions(channelLogos);
  }, [channelLogos]);

  // Get display text for the current logo
  const displayText =
    logoId && channelLogos[logoId] ? channelLogos[logoId].name : 'Default';

  // Custom option renderer to show logo images
  const renderOption = ({ option }) => {
    if (option.value === 'null') {
      return <div style={{ padding: '8px 12px' }}>Default</div>;
    }

    return (
      <Box
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: '12px',
          padding: '8px 12px',
          minHeight: '50px',
        }}
      >
        <img
          src={option.logo?.cache_url}
          alt={option.label}
          style={{
            height: '40px',
            maxWidth: '100px',
            objectFit: 'contain',
          }}
          onError={(e) => {
            e.target.style.display = 'none';
          }}
        />
        <span style={{ fontSize: '13px' }}>{option.label}</span>
      </Box>
    );
  };

  return (
    <Box
      style={{
        width: '100%',
        height: '100%',
        display: 'flex',
        alignItems: 'center',
      }}
    >
      <Select
        value={null}
        onChange={handleChange}
        onBlur={onBlur}
        data={logoOptions}
        size="xs"
        variant="unstyled"
        searchable
        searchValue={searchValue}
        onSearchChange={setSearchValue}
        autoFocus
        placeholder={displayText}
        nothingFoundMessage="No logos found"
        renderOption={renderOption}
        maxDropdownHeight={400}
        comboboxProps={{ width: 250, position: 'bottom-start' }}
        styles={{
          input: {
            minHeight: 'unset',
            height: '100%',
            padding: '0 4px',
            backgroundColor: 'rgba(255, 255, 255, 0.1)',
          },
          option: {
            padding: 0,
          },
          dropdown: {
            minWidth: '250px',
          },
        }}
      />
    </Box>
  );
};
