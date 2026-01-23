import React, {
  useState,
  useCallback,
  useEffect,
  useRef,
  useMemo,
} from 'react';
import {
  Box,
  TextInput,
  Select,
  NumberInput,
  Tooltip,
  Center,
  Skeleton,
} from '@mantine/core';
import API from '../../../api';
import useChannelsTableStore from '../../../store/channelsTable';

// Editable text cell
export const EditableTextCell = ({ row, column, getValue }) => {
  const isUnlocked = useChannelsTableStore((s) => s.isUnlocked);
  const initialValue = getValue() || '';
  const [value, setValue] = useState(initialValue);
  const [isFocused, setIsFocused] = useState(false);
  const previousValue = useRef(initialValue);
  const isMounted = useRef(false);
  const debounceTimer = useRef(null);

  useEffect(() => {
    const currentValue = getValue() || '';
    if (!isFocused && currentValue !== previousValue.current) {
      setValue(currentValue);
      previousValue.current = currentValue;
    }
  }, [getValue, isFocused]);

  const saveValue = useCallback(
    async (newValue) => {
      // Don't save if not mounted, not unlocked, or value hasn't changed
      if (
        !isMounted.current ||
        !isUnlocked ||
        newValue === previousValue.current
      ) {
        return;
      }

      try {
        const response = await API.updateChannel({
          id: row.original.id,
          [column.id]: newValue || null,
        });
        previousValue.current = newValue;

        // Update the table store to reflect the change
        if (response) {
          useChannelsTableStore.getState().updateChannel(response);
        }
      } catch (error) {
        // Revert on error
        setValue(previousValue.current || '');
      }
    },
    [row.original.id, column.id, isUnlocked]
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
    if (!isUnlocked) return;
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
    setIsFocused(false);
    if (isUnlocked) {
      saveValue(value);
    }
  };

  const handleClick = () => {
    if (isUnlocked) {
      setIsFocused(true);
    }
  };

  if (!isUnlocked || !isFocused) {
    return (
      <Box
        onClick={handleClick}
        style={{
          whiteSpace: 'nowrap',
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          cursor: isUnlocked ? 'text' : 'default',
          padding: '0 4px',
          ...(isUnlocked && {
            '&:hover': {
              backgroundColor: 'rgba(255, 255, 255, 0.05)',
            },
          }),
        }}
      >
        {value}
      </Box>
    );
  }

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
  const initialValue = getValue();
  const [value, setValue] = useState(initialValue);
  const [isFocused, setIsFocused] = useState(false);
  const previousValue = useRef(initialValue);
  const isMounted = useRef(false);

  useEffect(() => {
    const currentValue = getValue();
    if (!isFocused && currentValue !== previousValue.current) {
      setValue(currentValue);
      previousValue.current = currentValue;
    }
  }, [getValue, isFocused]);

  const saveValue = useCallback(
    async (newValue) => {
      // Don't save if not mounted, not unlocked, or value hasn't changed
      if (
        !isMounted.current ||
        !isUnlocked ||
        newValue === previousValue.current
      ) {
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
        const response = await API.updateChannel({
          id: row.original.id,
          [column.id]: newValue,
        });
        previousValue.current = newValue;

        // Update the table store to reflect the change
        if (response) {
          useChannelsTableStore.getState().updateChannel(response);

          // If channel_number was changed, refetch to reorder the table
          if (column.id === 'channel_number') {
            await API.requeryChannels();
            // Exit edit mode after resorting to avoid confusion
            setIsFocused(false);
          }
        }
      } catch (error) {
        // Revert on error
        setValue(previousValue.current);
      }
    },
    [row.original.id, column.id, isUnlocked]
  );

  useEffect(() => {
    isMounted.current = true;
    return () => {
      isMounted.current = false;
    };
  }, []);

  const handleChange = (newValue) => {
    if (!isUnlocked) return;
    setValue(newValue);
  };

  const handleBlur = () => {
    setIsFocused(false);
    if (isUnlocked) {
      saveValue(value);
    }
  };

  const handleClick = () => {
    if (isUnlocked) {
      setIsFocused(true);
    }
  };

  const formattedValue =
    value !== null && value !== undefined
      ? value === Math.floor(value)
        ? Math.floor(value)
        : value
      : '';

  if (!isUnlocked || !isFocused) {
    return (
      <Box
        onClick={handleClick}
        style={{
          textAlign: 'right',
          width: '100%',
          cursor: isUnlocked ? 'text' : 'default',
          padding: '0 4px',
          ...(isUnlocked && {
            '&:hover': {
              backgroundColor: 'rgba(255, 255, 255, 0.05)',
            },
          }),
        }}
      >
        {formattedValue}
      </Box>
    );
  }

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
export const EditableGroupCell = ({ row, getValue, channelGroups }) => {
  const isUnlocked = useChannelsTableStore((s) => s.isUnlocked);
  const groupId = row.original.channel_group_id;
  const groupName = channelGroups[groupId]?.name || '';
  const previousGroupId = useRef(groupId);
  const [isFocused, setIsFocused] = useState(false);
  const [searchValue, setSearchValue] = useState('');

  const saveValue = useCallback(
    async (newGroupId) => {
      // Don't save if not unlocked or value hasn't changed
      if (
        !isUnlocked ||
        String(newGroupId) === String(previousGroupId.current)
      ) {
        return;
      }

      try {
        const response = await API.updateChannel({
          id: row.original.id,
          channel_group_id: parseInt(newGroupId, 10),
        });
        previousGroupId.current = newGroupId;

        // Update the table store to reflect the change
        if (response) {
          useChannelsTableStore.getState().updateChannel(response);
        }
      } catch (error) {
        console.error('Failed to update channel group:', error);
      }
    },
    [row.original.id, isUnlocked]
  );

  const handleClick = () => {
    if (isUnlocked) {
      setIsFocused(true);
    }
  };

  const handleChange = (newGroupId) => {
    saveValue(newGroupId);
    setIsFocused(false);
    setSearchValue('');
  };

  const groupOptions = Object.values(channelGroups).map((group) => ({
    value: String(group.id),
    label: group.name,
  }));

  if (!isUnlocked || !isFocused) {
    return (
      <Box
        onClick={handleClick}
        style={{
          whiteSpace: 'nowrap',
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          cursor: isUnlocked ? 'pointer' : 'default',
          padding: '0 4px',
          ...(isUnlocked && {
            '&:hover': {
              backgroundColor: 'rgba(255, 255, 255, 0.05)',
            },
          }),
        }}
      >
        {groupName}
      </Box>
    );
  }

  return (
    <Select
      value={null}
      onChange={handleChange}
      onBlur={() => setIsFocused(false)}
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
  const epgDataId = getValue();
  const previousEpgDataId = useRef(epgDataId);
  const [isFocused, setIsFocused] = useState(false);
  const [searchValue, setSearchValue] = useState('');

  // Format display text
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

  const saveValue = useCallback(
    async (newEpgDataId) => {
      // Don't save if not unlocked or value hasn't changed
      if (
        !isUnlocked ||
        String(newEpgDataId) === String(previousEpgDataId.current)
      ) {
        return;
      }

      try {
        const response = await API.updateChannel({
          id: row.original.id,
          epg_data_id:
            newEpgDataId === 'null' ? null : parseInt(newEpgDataId, 10),
        });
        previousEpgDataId.current = newEpgDataId;

        // Update the table store to reflect the change
        if (response) {
          useChannelsTableStore.getState().updateChannel(response);
        }
      } catch (error) {
        console.error('Failed to update EPG:', error);
      }
    },
    [row.original.id, isUnlocked]
  );

  const handleClick = () => {
    if (isUnlocked) {
      setSearchValue(''); // Start with empty search
      setIsFocused(true);
    }
  };

  const handleChange = (newEpgDataId) => {
    saveValue(newEpgDataId);
    setSearchValue('');
    setIsFocused(false);
  };

  // Build EPG options
  const epgOptions = useMemo(() => {
    const options = [{ value: 'null', label: 'Not Assigned' }];

    // Convert tvgsById to an array and sort by EPG source name, then by tvg_id
    const tvgsArray = Object.values(tvgsById);
    tvgsArray.sort((a, b) => {
      const aEpgName =
        a.epg_source && epgs[a.epg_source]
          ? epgs[a.epg_source].name
          : a.epg_source || '';
      const bEpgName =
        b.epg_source && epgs[b.epg_source]
          ? epgs[b.epg_source].name
          : b.epg_source || '';
      const epgCompare = aEpgName.localeCompare(bEpgName);
      if (epgCompare !== 0) return epgCompare;
      // Secondary sort by tvg_id
      return (a.tvg_id || '').localeCompare(b.tvg_id || '');
    });

    tvgsArray.forEach((tvg) => {
      const epgSourceName =
        tvg.epg_source && epgs[tvg.epg_source]
          ? epgs[tvg.epg_source].name
          : tvg.epg_source;
      const tvgName = tvg.name;
      // Create a comprehensive label: "EPG Name | TVG-ID | TVG Name"
      let label;
      if (epgSourceName && tvg.tvg_id) {
        label = `${epgSourceName} | ${tvg.tvg_id}`;
        if (tvgName && tvgName !== tvg.tvg_id) {
          label += ` | ${tvgName}`;
        }
      } else if (tvgName) {
        label = tvgName;
      } else {
        label = `ID: ${tvg.id}`;
      }

      options.push({
        value: String(tvg.id),
        label: label,
      });
    });

    return options;
  }, [tvgsById, epgs]);

  // Build tooltip content
  const tooltip = epgObj
    ? `${epgName ? `EPG Name: ${epgName}\n` : ''}${epgObj.name ? `TVG Name: ${epgObj.name}\n` : ''}${tvgId ? `TVG-ID: ${tvgId}` : ''}`.trim()
    : '';

  if (!isUnlocked || !isFocused) {
    // If loading EPG data, show skeleton
    if (isEpgDataPending) {
      return (
        <Box
          style={{
            width: '100%',
            height: '100%',
            display: 'flex',
            alignItems: 'center',
            padding: '0 4px',
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
    // Otherwise, show the normal EPG assignment cell
    return (
      <Tooltip
        label={<span style={{ whiteSpace: 'pre-line' }}>{tooltip}</span>}
        withArrow
        position="top"
        disabled={!epgObj}
        openDelay={500}
      >
        <Box
          onClick={handleClick}
          style={{
            whiteSpace: 'nowrap',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            cursor: isUnlocked ? 'pointer' : 'default',
            padding: '0 4px',
            ...(isUnlocked && {
              '&:hover': {
                backgroundColor: 'rgba(255, 255, 255, 0.05)',
              },
            }),
          }}
        >
          {displayText}
        </Box>
      </Tooltip>
    );
  }

  return (
    <Select
      value={null}
      onChange={handleChange}
      onBlur={() => setIsFocused(false)}
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
export const EditableLogoCell = ({ row, getValue, channelLogos, LazyLogo }) => {
  const isUnlocked = useChannelsTableStore((s) => s.isUnlocked);
  const logoId = getValue();
  const previousLogoId = useRef(logoId);
  const [isFocused, setIsFocused] = useState(false);
  const [searchValue, setSearchValue] = useState('');

  const saveValue = useCallback(
    async (newLogoId) => {
      // Don't save if not unlocked or value hasn't changed
      if (!isUnlocked || String(newLogoId) === String(previousLogoId.current)) {
        return;
      }

      try {
        const response = await API.updateChannel({
          id: row.original.id,
          logo_id: newLogoId === 'null' ? null : parseInt(newLogoId, 10),
        });
        previousLogoId.current = newLogoId;

        // Update the table store to reflect the change
        if (response) {
          useChannelsTableStore.getState().updateChannel(response);
        }
      } catch (error) {
        console.error('Failed to update logo:', error);
      }
    },
    [row.original.id, isUnlocked]
  );

  const handleClick = () => {
    if (isUnlocked) {
      setSearchValue('');
      setIsFocused(true);
    }
  };

  const handleChange = (newLogoId) => {
    saveValue(newLogoId);
    setSearchValue('');
    setIsFocused(false);
  };

  // Build logo options with logo data
  const logoOptions = useMemo(() => {
    const options = [
      {
        value: 'null',
        label: 'Default',
        logo: null,
      },
    ];

    // Convert channelLogos object to array and sort by name
    const logosArray = Object.values(channelLogos);
    logosArray.sort((a, b) => (a.name || '').localeCompare(b.name || ''));

    logosArray.forEach((logo) => {
      options.push({
        value: String(logo.id),
        label: logo.name || `Logo ${logo.id}`,
        logo: logo,
      });
    });

    return options;
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

  if (!isUnlocked || !isFocused) {
    // When not editing, show the logo image
    return (
      <Box
        onClick={handleClick}
        style={{
          cursor: isUnlocked ? 'pointer' : 'default',
          width: '100%',
          height: '100%',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          ...(isUnlocked && {
            '&:hover': {
              backgroundColor: 'rgba(255, 255, 255, 0.05)',
            },
          }),
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
        onBlur={() => setIsFocused(false)}
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
