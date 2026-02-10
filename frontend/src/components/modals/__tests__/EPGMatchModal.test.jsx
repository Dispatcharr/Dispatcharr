import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import EPGMatchModal from '../EPGMatchModal';
import * as SettingsUtils from '../../../utils/pages/SettingsUtils';
import API from '../../../api';

// Mock dependencies
vi.mock('../../../api', () => ({
  default: {
    matchEpg: vi.fn(),
  },
}));

vi.mock('../../../utils/pages/SettingsUtils', () => ({
  getChangedSettings: vi.fn(),
  saveChangedSettings: vi.fn(),
}));

vi.mock('@mantine/notifications', () => ({
  notifications: {
    show: vi.fn(),
  },
}));

vi.mock('../../../store/settings', () => ({
  default: vi.fn((selector) => {
    const mockState = {
      settings: {
        epg_settings: {
          value: {
            epg_match_mode: 'default',
            epg_match_ignore_prefixes: [],
            epg_match_ignore_suffixes: [],
            epg_match_ignore_custom: [],
          },
        },
      },
    };
    return selector(mockState);
  }),
}));

vi.mock('@mantine/core', () => {
  const React = require('react');

  const RadioComponent = ({
    label,
    value,
    checked,
    description,
    groupValue,
    groupOnChange,
  }) => {
    const isChecked = checked !== undefined ? checked : groupValue === value;
    const handleChange = groupOnChange || (() => {});

    return (
      <label>
        <input
          type="radio"
          value={value}
          checked={isChecked}
          onChange={() => handleChange(value)}
          aria-label={label}
        />
        {label}
        {description && <span>{description}</span>}
      </label>
    );
  };

  RadioComponent.Group = ({ children, value, onChange, label }) => {
    // Clone children and inject group props
    const enhancedChildren = React.Children.map(children, (child) => {
      if (React.isValidElement(child)) {
        // If it's a Stack or other container, recursively enhance its children
        if (
          child.type?.name === 'Stack' ||
          child.props['data-testid'] === 'stack'
        ) {
          return React.cloneElement(child, {
            children: React.Children.map(
              child.props.children,
              (nestedChild) => {
                if (
                  React.isValidElement(nestedChild) &&
                  nestedChild.type === RadioComponent
                ) {
                  return React.cloneElement(nestedChild, {
                    groupValue: value,
                    groupOnChange: onChange,
                  });
                }
                return nestedChild;
              }
            ),
          });
        }
        // If it's a Radio component, inject props directly
        if (child.type === RadioComponent) {
          return React.cloneElement(child, {
            groupValue: value,
            groupOnChange: onChange,
          });
        }
      }
      return child;
    });

    return (
      <div role="radiogroup" aria-label={label}>
        {label && <span>{label}</span>}
        {enhancedChildren}
      </div>
    );
  };

  return {
    Modal: ({ children, opened, title }) =>
      opened ? (
        <div data-testid="modal">
          <div data-testid="modal-title">{title}</div>
          {children}
        </div>
      ) : null,
    Stack: ({ children }) => <div data-testid="stack">{children}</div>,
    Radio: RadioComponent,
    TagsInput: ({ label, value, onChange, ...props }) => (
      <div>
        <label htmlFor={label}>{label}</label>
        <input
          id={label}
          aria-label={label}
          value={value?.join(',') || ''}
          onChange={(e) => onChange(e.target.value.split(',').filter(Boolean))}
          {...props}
        />
      </div>
    ),
    Button: ({ children, onClick, loading, ...props }) => (
      <button onClick={onClick} disabled={loading} {...props}>
        {loading ? 'Loading...' : children}
      </button>
    ),
    Group: ({ children }) => <div data-testid="group">{children}</div>,
    Loader: () => <div data-testid="loader">Loading...</div>,
    Text: ({ children }) => <span>{children}</span>,
  };
});

describe('EPGMatchModal', () => {
  const defaultProps = {
    opened: true,
    onClose: vi.fn(),
    selectedChannelIds: [],
  };

  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('Rendering', () => {
    it('should render the modal when opened', () => {
      render(<EPGMatchModal {...defaultProps} />);
      expect(screen.getByText('EPG Match Settings')).toBeInTheDocument();
    });

    it('should show default mode selected by default', () => {
      render(<EPGMatchModal {...defaultProps} />);
      const defaultRadio = screen.getByLabelText('Use default settings');
      expect(defaultRadio).toBeChecked();
    });

    it('should not show advanced fields in default mode', () => {
      render(<EPGMatchModal {...defaultProps} />);
      expect(
        screen.queryByLabelText('Ignore Prefixes')
      ).not.toBeInTheDocument();
    });

    it('should show advanced fields when advanced mode is selected', async () => {
      render(<EPGMatchModal {...defaultProps} />);
      const advancedRadio = screen.getByLabelText('Configure advanced options');

      fireEvent.click(advancedRadio);

      await waitFor(() => {
        expect(screen.getByLabelText('Ignore Prefixes')).toBeInTheDocument();
        expect(screen.getByLabelText('Ignore Suffixes')).toBeInTheDocument();
        expect(
          screen.getByLabelText('Ignore Custom Strings')
        ).toBeInTheDocument();
      });
    });
  });

  describe('Mode Switching', () => {
    it('should allow switching between default and advanced modes', async () => {
      render(<EPGMatchModal {...defaultProps} />);

      const defaultRadio = screen.getByLabelText('Use default settings');
      const advancedRadio = screen.getByLabelText('Configure advanced options');

      expect(defaultRadio).toBeChecked();

      fireEvent.click(advancedRadio);
      await waitFor(() => {
        expect(advancedRadio).toBeChecked();
        expect(defaultRadio).not.toBeChecked();
      });

      fireEvent.click(defaultRadio);
      await waitFor(() => {
        expect(defaultRadio).toBeChecked();
        expect(advancedRadio).not.toBeChecked();
      });
    });
  });

  describe('Form Submission', () => {
    it('should save mode and trigger auto-match', async () => {
      SettingsUtils.getChangedSettings.mockReturnValue({
        epg_match_mode: 'default',
      });
      SettingsUtils.saveChangedSettings.mockResolvedValue();
      API.matchEpg.mockResolvedValue();

      render(<EPGMatchModal {...defaultProps} />);

      const submitButton = screen.getByText('Start Auto-Match');
      fireEvent.click(submitButton);

      await waitFor(() => {
        expect(SettingsUtils.saveChangedSettings).toHaveBeenCalled();
        expect(API.matchEpg).toHaveBeenCalled();
        expect(defaultProps.onClose).toHaveBeenCalled();
      });
    });

    it('should pass selectedChannelIds to matchEpg when provided', async () => {
      const selectedIds = [1, 2, 3];
      SettingsUtils.getChangedSettings.mockReturnValue({});
      API.matchEpg.mockResolvedValue();

      render(
        <EPGMatchModal {...defaultProps} selectedChannelIds={selectedIds} />
      );

      const submitButton = screen.getByText('Start Auto-Match');
      fireEvent.click(submitButton);

      await waitFor(() => {
        expect(API.matchEpg).toHaveBeenCalledWith(selectedIds);
      });
    });

    it('should handle save errors gracefully', async () => {
      const error = new Error('Save failed');
      SettingsUtils.getChangedSettings.mockReturnValue({
        epg_match_mode: 'default',
      });
      SettingsUtils.saveChangedSettings.mockRejectedValue(error);

      render(<EPGMatchModal {...defaultProps} />);

      const submitButton = screen.getByText('Start Auto-Match');
      fireEvent.click(submitButton);

      await waitFor(() => {
        expect(defaultProps.onClose).not.toHaveBeenCalled();
      });
    });
  });

  describe('Settings Persistence', () => {
    it('should include epg_match_mode in settings to save', async () => {
      SettingsUtils.getChangedSettings.mockImplementation((values) => values);
      SettingsUtils.saveChangedSettings.mockResolvedValue();
      API.matchEpg.mockResolvedValue();

      render(<EPGMatchModal {...defaultProps} />);

      const submitButton = screen.getByText('Start Auto-Match');
      fireEvent.click(submitButton);

      await waitFor(() => {
        expect(SettingsUtils.getChangedSettings).toHaveBeenCalledWith(
          expect.objectContaining({
            epg_match_mode: 'default',
          }),
          expect.anything()
        );
      });
    });
  });

  describe('UI Text', () => {
    it('should show correct text for selected channels', () => {
      render(
        <EPGMatchModal {...defaultProps} selectedChannelIds={[1, 2, 3]} />
      );
      expect(
        screen.getByText(
          /Match channels to EPG data for 3 selected channel\(s\)/
        )
      ).toBeInTheDocument();
    });

    it('should show correct text for all channels', () => {
      render(<EPGMatchModal {...defaultProps} selectedChannelIds={[]} />);
      expect(
        screen.getByText(
          /Match channels to EPG data for all channels without EPG/
        )
      ).toBeInTheDocument();
    });
  });
});
