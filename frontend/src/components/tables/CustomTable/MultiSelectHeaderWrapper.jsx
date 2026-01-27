import React, { cloneElement, isValidElement, useRef } from 'react';
import { Box, Flex, Pill, Tooltip, MultiSelect } from '@mantine/core';

/**
 * Automatically wraps MultiSelect components with pill display and tooltips
 * Recursively searches through React children to find and enhance MultiSelect
 */
const MultiSelectHeaderWrapper = ({ children }) => {
  const inputRef = useRef(null);

  const enhanceMultiSelect = (element) => {
    if (!isValidElement(element)) {
      return element;
    }

    // Check if this element is a MultiSelect
    if (element.type === MultiSelect) {
      const { value = [], data = [], onChange, ...otherProps } = element.props;
      const selectedValues = Array.isArray(value) ? value : [];

      if (selectedValues.length === 0) {
        // No selections - just render the MultiSelect with hidden pills
        return cloneElement(element, {
          ...otherProps,
          value,
          data,
          onChange,
          styles: { pill: { display: 'none' } },
        });
      }

      // Get first label
      const firstLabel =
        data.find((opt) => opt.value === selectedValues[0])?.label ||
        selectedValues[0];

      // Build tooltip content
      const tooltipContent = (
        <div>
          {selectedValues.slice(0, 10).map((val, idx) => {
            const label = data.find((opt) => opt.value === val)?.label || val;
            return <div key={idx}>{label}</div>;
          })}
          {selectedValues.length > 10 && (
            <div style={{ marginTop: '4px', fontStyle: 'italic' }}>
              +{selectedValues.length - 10} more
            </div>
          )}
        </div>
      );

      // Handle opening the dropdown when pill is clicked
      const handlePillClick = (e) => {
        // Check if the click is on the remove button (it has a data-attribute)
        if (e.target.closest('[data-disabled]') || e.target.closest('button')) {
          return; // Let the remove button handle it
        }
        e.stopPropagation();
        // Focus and click the input to open the dropdown
        if (inputRef.current) {
          const input = inputRef.current.querySelector('input');
          if (input) {
            input.focus();
            input.click();
          }
        }
      };

      // Handle removing a single filter value
      const handleRemoveFirst = (e) => {
        e?.stopPropagation?.();
        if (onChange && selectedValues.length > 0) {
          const newValues = selectedValues.slice(1);
          onChange(newValues);
        }
      };

      // Handle clearing all filters
      const handleClearAll = (e) => {
        e?.stopPropagation?.();
        if (onChange) {
          onChange([]);
        }
      };

      return (
        <Box ref={inputRef} style={{ width: '100%', position: 'relative' }}>
          <Tooltip label={tooltipContent} position="top" withArrow>
            <Flex
              gap={4}
              style={{
                position: 'absolute',
                top: 4,
                left: 4,
                right: 20,
                zIndex: 1,
                pointerEvents: 'none',
                overflow: 'hidden',
              }}
            >
              <Pill
                size="xs"
                withRemoveButton
                onRemove={handleRemoveFirst}
                onClick={handlePillClick}
                removeButtonProps={{
                  onClick: handleRemoveFirst,
                  style: { cursor: 'pointer' },
                }}
                style={{
                  flex: selectedValues.length > 1 ? '1 1 auto' : '0 1 auto',
                  minWidth: 0,
                  maxWidth:
                    selectedValues.length > 1 ? 'calc(100% - 40px)' : '100%',
                  pointerEvents: 'auto',
                }}
              >
                <span
                  style={{
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                  }}
                >
                  {firstLabel}
                </span>
              </Pill>
              {selectedValues.length > 1 && (
                <Pill
                  size="xs"
                  withRemoveButton
                  onRemove={handleClearAll}
                  onClick={handlePillClick}
                  removeButtonProps={{
                    onClick: handleClearAll,
                    style: { cursor: 'pointer' },
                  }}
                  style={{
                    flexShrink: 0,
                    pointerEvents: 'auto',
                  }}
                >
                  <span
                    style={{
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap',
                    }}
                  >
                    +{selectedValues.length - 1}
                  </span>
                </Pill>
              )}
            </Flex>
          </Tooltip>
          {cloneElement(element, {
            ...otherProps,
            value,
            data,
            onChange,
            styles: { pill: { display: 'none' } },
            style: { width: '100%', ...otherProps.style },
          })}
        </Box>
      );
    }

    // Check if element has children - recursively enhance them
    if (element.props && element.props.children) {
      const enhancedChildren = React.Children.map(
        element.props.children,
        (child) => enhanceMultiSelect(child)
      );

      // Clone element with enhanced children
      return cloneElement(element, {}, enhancedChildren);
    }

    return element;
  };

  return <>{enhanceMultiSelect(children)}</>;
};

export default MultiSelectHeaderWrapper;
