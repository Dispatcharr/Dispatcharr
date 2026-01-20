import React, { cloneElement, isValidElement } from 'react';
import { Box, Flex, Pill, Tooltip, MultiSelect } from '@mantine/core';

/**
 * Automatically wraps MultiSelect components with pill display and tooltips
 * Recursively searches through React children to find and enhance MultiSelect
 */
const MultiSelectHeaderWrapper = ({ children }) => {
  const enhanceMultiSelect = (element) => {
    if (!isValidElement(element)) {
      return element;
    }

    // Check if this element is a MultiSelect
    if (element.type === MultiSelect) {
      const { value = [], data = [], ...otherProps } = element.props;
      const selectedValues = Array.isArray(value) ? value : [];

      if (selectedValues.length === 0) {
        // No selections - just render the MultiSelect with hidden pills
        return cloneElement(element, {
          ...otherProps,
          value,
          data,
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

      return (
        <Box style={{ width: '100%', position: 'relative' }}>
          <Tooltip label={tooltipContent} position="top" withArrow>
            <Flex
              gap={4}
              style={{
                position: 'absolute',
                top: 4,
                left: 4,
                right: 30,
                zIndex: 1,
                pointerEvents: 'none',
                overflow: 'hidden',
              }}
            >
              <Pill
                size="xs"
                style={{
                  flex: '1 1 auto',
                  minWidth: 0,
                  maxWidth:
                    selectedValues.length > 1
                      ? 'calc(100% - 50px)'
                      : 'calc(100% - 30px)',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                  display: 'block',
                  pointerEvents: 'auto',
                }}
              >
                {firstLabel}
              </Pill>
              {selectedValues.length > 1 && (
                <Pill
                  size="xs"
                  style={{ flexShrink: 0, pointerEvents: 'auto' }}
                >
                  +{selectedValues.length - 1}
                </Pill>
              )}
            </Flex>
          </Tooltip>
          {cloneElement(element, {
            ...otherProps,
            value,
            data,
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
