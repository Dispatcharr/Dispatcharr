import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

// ── @mantine/core ──────────────────────────────────────────────────────────────
vi.mock('@mantine/core', () => {
  const React = require('react');

  // Named declarations so reference equality checks (child.type === Stack) work
  function Stack({ children }) {
    return <div>{children}</div>;
  }

  function RadioItem({ value, label, description, _onChange }) {
    return (
      <label>
        <input
          type="radio"
          data-testid={`radio-${value}`}
          value={value}
          onChange={() => _onChange?.(value)}
          aria-label={label}
        />
        {label}
        {description && (
          <span data-testid={`radio-desc-${value}`}>{description}</span>
        )}
      </label>
    );
  }

  function RadioGroup({ children, onChange, label }) {
    // Inject _onChange into Radio children, handling the Stack wrapper
    const inject = (child) => {
      if (!React.isValidElement(child)) return child;
      if (child.type === RadioItem) {
        return React.cloneElement(child, { _onChange: onChange });
      }
      if (child.type === Stack && child.props.children) {
        return React.cloneElement(child, {
          children: React.Children.map(child.props.children, inject),
        });
      }
      return child;
    };

    return (
      <div>
        {label && <label>{label}</label>}
        {React.Children.map(children, inject)}
      </div>
    );
  }

  return {
    Button: ({ children, onClick, variant }) => (
      <button onClick={onClick} data-variant={variant}>
        {children}
      </button>
    ),
    Checkbox: ({ label, checked, onChange }) => (
      <div>
        <input
          type="checkbox"
          data-testid="remember-checkbox"
          checked={checked ?? false}
          onChange={(e) =>
            onChange({ currentTarget: { checked: e.target.checked } })
          }
        />
        {label && <label>{label}</label>}
      </div>
    ),
    Divider: ({ label }) => <hr aria-label={label} />,
    Group: ({ children }) => <div>{children}</div>,
    Modal: ({ children, opened, onClose, title }) =>
      opened ? (
        <div data-testid="modal">
          <div data-testid="modal-title">{title}</div>
          <button data-testid="modal-close" onClick={onClose}>
            ×
          </button>
          {children}
        </div>
      ) : null,
    MultiSelect: ({ label, data, value, onChange }) => {
      const flat = (data ?? []).flatMap((g) =>
        g.items ? g.items : [{ value: g.value, label: g.label }]
      );
      return (
        <div>
          {label && <label>{label}</label>}
          {flat.map((opt) => (
            <button
              key={opt.value}
              data-testid={`profile-option-${opt.value}`}
              onClick={() => onChange([...(value ?? []), opt.value])}
            >
              {opt.label}
            </button>
          ))}
        </div>
      );
    },
    NumberInput: ({
      label,
      value,
      onChange,
      min,
      placeholder,
      description,
    }) => (
      <div>
        {label && <label>{label}</label>}
        <input
          type="number"
          data-testid="number-input"
          value={value ?? ''}
          min={min}
          placeholder={placeholder}
          onChange={(e) => onChange(Number(e.target.value))}
        />
        {description && <span>{description}</span>}
      </div>
    ),
    Radio: RadioItem,
    RadioGroup,
    Stack,
    Text: ({ children, c }) => <span data-color={c}>{children}</span>,
  };
});

// ── Imports after mocks ────────────────────────────────────────────────────────
import CreateChannelModal from '../CreateChannelModal';

// ── Shared helpers ─────────────────────────────────────────────────────────────
const makeProfiles = () => [
  { id: '0', name: 'All Profiles' }, // should be filtered out
  { id: '1', name: 'Profile One' },
  { id: '2', name: 'Profile Two' },
];

const defaultProps = (overrides = {}) => ({
  opened: true,
  onClose: vi.fn(),
  mode: 'provider',
  onModeChange: vi.fn(),
  numberValue: '',
  onNumberValueChange: vi.fn(),
  rememberChoice: false,
  onRememberChoiceChange: vi.fn(),
  onConfirm: vi.fn(),
  isBulk: false,
  streamCount: 1,
  streamName: 'My Stream',
  selectedProfileIds: [],
  onProfileIdsChange: vi.fn(),
  channelProfiles: makeProfiles(),
  ...overrides,
});

// ──────────────────────────────────────────────────────────────────────────────

describe('CreateChannelModal', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // ── Visibility ─────────────────────────────────────────────────────────────

  describe('visibility', () => {
    it('renders the modal when opened is true', () => {
      render(<CreateChannelModal {...defaultProps()} />);
      expect(screen.getByTestId('modal')).toBeInTheDocument();
    });

    it('does not render the modal when opened is false', () => {
      render(<CreateChannelModal {...defaultProps({ opened: false })} />);
      expect(screen.queryByTestId('modal')).not.toBeInTheDocument();
    });

    it('calls onClose when the close button is clicked', () => {
      const onClose = vi.fn();
      render(<CreateChannelModal {...defaultProps({ onClose })} />);
      fireEvent.click(screen.getByTestId('modal-close'));
      expect(onClose).toHaveBeenCalled();
    });
  });

  // ── Title and labels ───────────────────────────────────────────────────────

  describe('title and labels', () => {
    it('shows "Create Channel" title for single mode', () => {
      render(<CreateChannelModal {...defaultProps()} />);
      expect(screen.getByTestId('modal-title')).toHaveTextContent(
        'Create Channel'
      );
    });

    it('shows "Create Channels Options" title for bulk mode', () => {
      render(<CreateChannelModal {...defaultProps({ isBulk: true })} />);
      expect(screen.getByTestId('modal-title')).toHaveTextContent(
        'Create Channels Options'
      );
    });

    it('shows "Create Channel" confirm button for single mode', () => {
      render(<CreateChannelModal {...defaultProps()} />);
      expect(
        screen.getByRole('button', { name: 'Create Channel' })
      ).toBeInTheDocument();
    });

    it('shows "Create Channels" confirm button for bulk mode', () => {
      render(<CreateChannelModal {...defaultProps({ isBulk: true })} />);
      expect(screen.getByText('Create Channels')).toBeInTheDocument();
    });

    it('shows "Number Assignment" numbering label for single mode', () => {
      render(<CreateChannelModal {...defaultProps()} />);
      expect(screen.getByText('Number Assignment')).toBeInTheDocument();
    });

    it('shows "Numbering Mode" numbering label for bulk mode', () => {
      render(<CreateChannelModal {...defaultProps({ isBulk: true })} />);
      expect(screen.getByText('Numbering Mode')).toBeInTheDocument();
    });
  });

  // ── Description text ───────────────────────────────────────────────────────

  describe('description text', () => {
    it('shows the streamName in the description for single mode', () => {
      render(
        <CreateChannelModal {...defaultProps({ streamName: 'ESPN HD' })} />
      );
      expect(screen.getByText(/ESPN HD/)).toBeInTheDocument();
    });

    it('shows the streamCount in the description for bulk mode', () => {
      render(
        <CreateChannelModal
          {...defaultProps({ isBulk: true, streamCount: 5 })}
        />
      );
      expect(screen.getByText(/5 channels/)).toBeInTheDocument();
    });
  });

  // ── Radio options ──────────────────────────────────────────────────────────

  describe('radio options', () => {
    it('renders all four radio options', () => {
      render(<CreateChannelModal {...defaultProps()} />);
      expect(screen.getByTestId('radio-provider')).toBeInTheDocument();
      expect(screen.getByTestId('radio-auto')).toBeInTheDocument();
      expect(screen.getByTestId('radio-highest')).toBeInTheDocument();
      expect(screen.getByTestId('radio-specific')).toBeInTheDocument();
    });

    it('renders "Use Provider Number" label for single mode', () => {
      render(<CreateChannelModal {...defaultProps()} />);
      expect(screen.getByLabelText('Use Provider Number')).toBeInTheDocument();
    });

    it('renders "Use Provider Numbers" label for bulk mode', () => {
      render(<CreateChannelModal {...defaultProps({ isBulk: true })} />);
      expect(screen.getByLabelText('Use Provider Numbers')).toBeInTheDocument();
    });

    it('renders "Auto-Assign Next Available" label for single mode', () => {
      render(<CreateChannelModal {...defaultProps()} />);
      expect(
        screen.getByLabelText('Auto-Assign Next Available')
      ).toBeInTheDocument();
    });

    it('renders "Auto-Assign Sequential" label for bulk mode', () => {
      render(<CreateChannelModal {...defaultProps({ isBulk: true })} />);
      expect(
        screen.getByLabelText('Auto-Assign Sequential')
      ).toBeInTheDocument();
    });

    it('renders "Use Specific Number" label for single mode', () => {
      render(<CreateChannelModal {...defaultProps()} />);
      expect(screen.getByLabelText('Use Specific Number')).toBeInTheDocument();
    });

    it('renders "Start from Custom Number" label for bulk mode', () => {
      render(<CreateChannelModal {...defaultProps({ isBulk: true })} />);
      expect(
        screen.getByLabelText('Start from Custom Number')
      ).toBeInTheDocument();
    });

    it('calls onModeChange when a radio option is selected', () => {
      const onModeChange = vi.fn();
      render(<CreateChannelModal {...defaultProps({ onModeChange })} />);
      fireEvent.click(screen.getByLabelText('Auto-Assign Next Available'));
      expect(onModeChange).toHaveBeenCalledWith('auto');
    });
  });

  // ── NumberInput visibility ─────────────────────────────────────────────────

  describe('NumberInput visibility', () => {
    it('does not show NumberInput when mode is "provider"', () => {
      render(<CreateChannelModal {...defaultProps({ mode: 'provider' })} />);
      expect(screen.queryByTestId('number-input')).not.toBeInTheDocument();
    });

    it('does not show NumberInput when mode is "auto"', () => {
      render(<CreateChannelModal {...defaultProps({ mode: 'auto' })} />);
      expect(screen.queryByTestId('number-input')).not.toBeInTheDocument();
    });

    it('does not show NumberInput when mode is "highest"', () => {
      render(<CreateChannelModal {...defaultProps({ mode: 'highest' })} />);
      expect(screen.queryByTestId('number-input')).not.toBeInTheDocument();
    });

    it('shows NumberInput when mode is "specific" in single mode', () => {
      render(<CreateChannelModal {...defaultProps({ mode: 'specific' })} />);
      expect(screen.getByTestId('number-input')).toBeInTheDocument();
    });

    it('shows NumberInput when mode is "custom" in bulk mode', () => {
      render(
        <CreateChannelModal
          {...defaultProps({ isBulk: true, mode: 'custom' })}
        />
      );
      expect(screen.getByTestId('number-input')).toBeInTheDocument();
    });

    it('does not show NumberInput when mode is "specific" but isBulk is true', () => {
      render(
        <CreateChannelModal
          {...defaultProps({ isBulk: true, mode: 'specific' })}
        />
      );
      expect(screen.queryByTestId('number-input')).not.toBeInTheDocument();
    });

    it('calls onNumberValueChange when NumberInput value changes', () => {
      const onNumberValueChange = vi.fn();
      render(
        <CreateChannelModal
          {...defaultProps({
            mode: 'specific',
            numberValue: 5,
            onNumberValueChange,
          })}
        />
      );
      fireEvent.change(screen.getByTestId('number-input'), {
        target: { value: '10' },
      });
      expect(onNumberValueChange).toHaveBeenCalledWith(10);
    });

    it('shows "Channel Number" label in single mode', () => {
      render(<CreateChannelModal {...defaultProps({ mode: 'specific' })} />);
      expect(screen.getByText('Channel Number')).toBeInTheDocument();
    });

    it('shows "Starting Channel Number" label in bulk mode', () => {
      render(
        <CreateChannelModal
          {...defaultProps({ isBulk: true, mode: 'custom' })}
        />
      );
      expect(screen.getByText('Starting Channel Number')).toBeInTheDocument();
    });
  });

  // ── Remember choice checkbox ───────────────────────────────────────────────

  describe('remember choice checkbox', () => {
    it('renders unchecked when rememberChoice is false', () => {
      render(
        <CreateChannelModal {...defaultProps({ rememberChoice: false })} />
      );
      expect(screen.getByTestId('remember-checkbox')).not.toBeChecked();
    });

    it('renders checked when rememberChoice is true', () => {
      render(
        <CreateChannelModal {...defaultProps({ rememberChoice: true })} />
      );
      expect(screen.getByTestId('remember-checkbox')).toBeChecked();
    });

    it('calls onRememberChoiceChange with true when checked', () => {
      const onRememberChoiceChange = vi.fn();
      render(
        <CreateChannelModal
          {...defaultProps({ rememberChoice: false, onRememberChoiceChange })}
        />
      );
      fireEvent.click(screen.getByTestId('remember-checkbox'));
      expect(onRememberChoiceChange).toHaveBeenCalledWith(true);
    });

    it('calls onRememberChoiceChange with false when unchecked', () => {
      const onRememberChoiceChange = vi.fn();
      render(
        <CreateChannelModal
          {...defaultProps({ rememberChoice: true, onRememberChoiceChange })}
        />
      );
      fireEvent.click(screen.getByTestId('remember-checkbox'));
      expect(onRememberChoiceChange).toHaveBeenCalledWith(false);
    });
  });

  // ── Action buttons ─────────────────────────────────────────────────────────

  describe('action buttons', () => {
    it('calls onConfirm when the confirm button is clicked', () => {
      const onConfirm = vi.fn();
      render(<CreateChannelModal {...defaultProps({ onConfirm })} />);
      fireEvent.click(screen.getByRole('button', { name: 'Create Channel' }));
      expect(onConfirm).toHaveBeenCalled();
    });

    it('calls onClose when the Cancel button is clicked', () => {
      const onClose = vi.fn();
      render(<CreateChannelModal {...defaultProps({ onClose })} />);
      fireEvent.click(screen.getByText('Cancel'));
      expect(onClose).toHaveBeenCalled();
    });
  });

  // ── Channel profiles ───────────────────────────────────────────────────────

  describe('channel profiles', () => {
    it('renders the "All Profiles" special option', () => {
      render(<CreateChannelModal {...defaultProps()} />);
      expect(screen.getByTestId('profile-option-all')).toBeInTheDocument();
    });

    it('renders the "No Profiles" special option', () => {
      render(<CreateChannelModal {...defaultProps()} />);
      expect(screen.getByTestId('profile-option-none')).toBeInTheDocument();
    });

    it('renders channel profile options (excluding id "0")', () => {
      render(<CreateChannelModal {...defaultProps()} />);
      expect(screen.getByTestId('profile-option-1')).toBeInTheDocument();
      expect(screen.getByTestId('profile-option-2')).toBeInTheDocument();
    });

    it('does not render the profile with id "0"', () => {
      render(<CreateChannelModal {...defaultProps()} />);
      expect(screen.queryByTestId('profile-option-0')).not.toBeInTheDocument();
    });

    it('renders "All Profiles" and "No Profiles" labels', () => {
      render(<CreateChannelModal {...defaultProps()} />);
      expect(screen.getByText('All Profiles')).toBeInTheDocument();
      expect(screen.getByText('No Profiles')).toBeInTheDocument();
    });
  });

  // ── handleProfileChange logic ──────────────────────────────────────────────

  describe('handleProfileChange', () => {
    it('selects only "all" when "All Profiles" is clicked', () => {
      const onProfileIdsChange = vi.fn();
      render(
        <CreateChannelModal
          {...defaultProps({ selectedProfileIds: [], onProfileIdsChange })}
        />
      );
      fireEvent.click(screen.getByTestId('profile-option-all'));
      expect(onProfileIdsChange).toHaveBeenCalledWith(['all']);
    });

    it('selects only "none" when "No Profiles" is clicked', () => {
      const onProfileIdsChange = vi.fn();
      render(
        <CreateChannelModal
          {...defaultProps({ selectedProfileIds: [], onProfileIdsChange })}
        />
      );
      fireEvent.click(screen.getByTestId('profile-option-none'));
      expect(onProfileIdsChange).toHaveBeenCalledWith(['none']);
    });

    it('removes "all" when a specific profile is added while "all" is selected', () => {
      const onProfileIdsChange = vi.fn();
      render(
        <CreateChannelModal
          {...defaultProps({ selectedProfileIds: ['all'], onProfileIdsChange })}
        />
      );
      fireEvent.click(screen.getByTestId('profile-option-1'));
      expect(onProfileIdsChange).toHaveBeenCalledWith(['1']);
    });

    it('removes "none" when a specific profile is added while "none" is selected', () => {
      const onProfileIdsChange = vi.fn();
      render(
        <CreateChannelModal
          {...defaultProps({
            selectedProfileIds: ['none'],
            onProfileIdsChange,
          })}
        />
      );
      fireEvent.click(screen.getByTestId('profile-option-2'));
      expect(onProfileIdsChange).toHaveBeenCalledWith(['2']);
    });

    it('allows selecting multiple specific profiles', () => {
      const onProfileIdsChange = vi.fn();
      render(
        <CreateChannelModal
          {...defaultProps({ selectedProfileIds: ['1'], onProfileIdsChange })}
        />
      );
      fireEvent.click(screen.getByTestId('profile-option-2'));
      expect(onProfileIdsChange).toHaveBeenCalledWith(['1', '2']);
    });

    it('replaces existing "all" selection when "none" is clicked last', () => {
      const onProfileIdsChange = vi.fn();
      render(
        <CreateChannelModal
          {...defaultProps({ selectedProfileIds: ['all'], onProfileIdsChange })}
        />
      );
      // Mock passes ['all', 'none'] to onChange, making lastSelected = 'none'
      fireEvent.click(screen.getByTestId('profile-option-none'));
      expect(onProfileIdsChange).toHaveBeenCalledWith(['none']);
    });
  });
});
