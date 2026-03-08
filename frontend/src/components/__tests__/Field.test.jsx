import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { Field } from '../Field';

// Mock Mantine components
vi.mock('@mantine/core', async () => {
  return {
    TextInput: ({ label, description, value, onChange, type, placeholder }) => (
      <div>
        <label htmlFor="text-input">{label}</label>
        <input
          id="text-input"
          type={type || 'text'}
          value={value}
          onChange={onChange}
          placeholder={placeholder}
          aria-describedby={description}
        />
        {description && <div>{description}</div>}
      </div>
    ),
    NumberInput: ({ label, description, value, onChange, placeholder }) => (
      <div>
        <label htmlFor="number-input">{label}</label>
        <input
          id="number-input"
          type="number"
          value={value}
          onChange={(e) => onChange(Number(e.target.value))}
          placeholder={placeholder}
          aria-describedby={description}
        />
        {description && <div>{description}</div>}
      </div>
    ),
    Textarea: ({ label, description, value, onChange, placeholder }) => (
      <div>
        <label htmlFor="textarea-input">{label}</label>
        <textarea
          id="textarea-input"
          value={value}
          onChange={onChange}
          placeholder={placeholder}
          aria-describedby={description}
        />
        {description && <div>{description}</div>}
      </div>
    ),
    Switch: ({ label, description, checked, onChange }) => (
      <div>
        <label htmlFor="switch-input">{label}</label>
        <input
          id="switch-input"
          type="checkbox"
          checked={checked}
          onChange={onChange}
          aria-describedby={description}
        />
        {description && <div>{description}</div>}
      </div>
    ),
    Select: ({ label, description, value, data, onChange, placeholder }) => (
      <div>
        <label htmlFor="select-input">{label}</label>
        <select
          id="select-input"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          aria-describedby={description}
        >
          {data.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
        {description && <div>{description}</div>}
      </div>
    ),
    Text: ({ children, fw, size, c }) => (
      <div data-fw={fw} data-size={size} data-color={c}>
        {children}
      </div>
    ),
  };
});

describe('Field', () => {
  const mockOnChange = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('TextInput (string type)', () => {
    it('should render TextInput for string type', () => {
      const field = {
        id: 'name',
        type: 'string',
        label: 'Name',
        help_text: 'Enter your name',
        default: '',
      };

      render(<Field field={field} value="" onChange={mockOnChange} />);

      expect(screen.getByLabelText('Name')).toBeInTheDocument();
      expect(screen.getByText('Enter your name')).toBeInTheDocument();
    });

    it('should use provided value', () => {
      const field = {
        id: 'name',
        type: 'string',
        label: 'Name',
        default: '',
      };

      render(<Field field={field} value="John" onChange={mockOnChange} />);

      expect(screen.getByLabelText('Name')).toHaveValue('John');
    });

    it('should use default value when value is null', () => {
      const field = {
        id: 'name',
        type: 'string',
        label: 'Name',
        default: 'Default Name',
      };

      render(<Field field={field} value={null} onChange={mockOnChange} />);

      expect(screen.getByLabelText('Name')).toHaveValue('Default Name');
    });

    it('should call onChange with field id and value', () => {
      const field = {
        id: 'name',
        type: 'string',
        label: 'Name',
        default: '',
      };

      render(<Field field={field} value="" onChange={mockOnChange} />);

      fireEvent.change(screen.getByLabelText('Name'), {
        target: { value: 'New Value' },
      });

      expect(mockOnChange).toHaveBeenCalledWith('name', 'New Value');
    });
  });

  describe('NumberInput (number type)', () => {
    it('should render NumberInput for number type', () => {
      const field = {
        id: 'age',
        type: 'number',
        label: 'Age',
        help_text: 'Enter your age',
        default: 0,
      };

      render(<Field field={field} value={null} onChange={mockOnChange} />);

      expect(screen.getByLabelText('Age')).toBeInTheDocument();
      expect(screen.getByText('Enter your age')).toBeInTheDocument();
    });

    it('should use provided value', () => {
      const field = {
        id: 'age',
        type: 'number',
        label: 'Age',
        default: 0,
      };

      render(<Field field={field} value={25} onChange={mockOnChange} />);

      expect(screen.getByLabelText('Age')).toHaveValue(25);
    });

    it('should default to 0 when value and default are null', () => {
      const field = {
        id: 'age',
        type: 'number',
        label: 'Age',
        default: null,
      };

      render(<Field field={field} value={null} onChange={mockOnChange} />);

      expect(screen.getByLabelText('Age')).toHaveValue(0);
    });

    it('should call onChange with field id and numeric value', () => {
      const field = {
        id: 'age',
        type: 'number',
        label: 'Age',
        default: 0,
      };

      render(<Field field={field} value={0} onChange={mockOnChange} />);

      fireEvent.change(screen.getByLabelText('Age'), {
        target: { value: '30' },
      });

      expect(mockOnChange).toHaveBeenCalledWith('age', 30);
    });
  });

  describe('Switch (boolean type)', () => {
    it('should render Switch for boolean type', () => {
      const field = {
        id: 'active',
        type: 'boolean',
        label: 'Active',
        help_text: 'Toggle active state',
        default: false,
      };

      render(<Field field={field} value={null} onChange={mockOnChange} />);

      expect(screen.getByLabelText('Active')).toBeInTheDocument();
      expect(screen.getByText('Toggle active state')).toBeInTheDocument();
    });

    it('should be checked when value is true', () => {
      const field = {
        id: 'active',
        type: 'boolean',
        label: 'Active',
        default: false,
      };

      render(<Field field={field} value={true} onChange={mockOnChange} />);

      expect(screen.getByLabelText('Active')).toBeChecked();
    });

    it('should be unchecked when value is false', () => {
      const field = {
        id: 'active',
        type: 'boolean',
        label: 'Active',
        default: false,
      };

      render(<Field field={field} value={false} onChange={mockOnChange} />);

      expect(screen.getByLabelText('Active')).not.toBeChecked();
    });

    it('should use default value when value is null', () => {
      const field = {
        id: 'active',
        type: 'boolean',
        label: 'Active',
        default: true,
      };

      render(<Field field={field} value={null} onChange={mockOnChange} />);

      expect(screen.getByLabelText('Active')).toBeChecked();
    });

    it('should call onChange with field id and checked state', () => {
      const field = {
        id: 'active',
        type: 'boolean',
        label: 'Active',
        default: false,
      };

      render(<Field field={field} value={false} onChange={mockOnChange} />);

      fireEvent.click(screen.getByLabelText('Active'));

      expect(mockOnChange).toHaveBeenCalledWith('active', true);
    });
  });

  describe('Select (select type)', () => {
    it('should render Select for select type', () => {
      const field = {
        id: 'country',
        type: 'select',
        label: 'Country',
        help_text: 'Select your country',
        default: '',
        options: [
          { value: 'us', label: 'United States' },
          { value: 'ca', label: 'Canada' },
        ],
      };

      render(<Field field={field} value={null} onChange={mockOnChange} />);

      expect(screen.getByLabelText('Country')).toBeInTheDocument();
      expect(screen.getByText('Select your country')).toBeInTheDocument();
    });

    it('should render options correctly', () => {
      const field = {
        id: 'country',
        type: 'select',
        label: 'Country',
        default: '',
        options: [
          { value: 'us', label: 'United States' },
          { value: 'ca', label: 'Canada' },
        ],
      };

      render(<Field field={field} value={null} onChange={mockOnChange} />);

      expect(screen.getByText('United States')).toBeInTheDocument();
      expect(screen.getByText('Canada')).toBeInTheDocument();
    });

    it('should use provided value', () => {
      const field = {
        id: 'country',
        type: 'select',
        label: 'Country',
        default: '',
        options: [
          { value: 'us', label: 'United States' },
          { value: 'ca', label: 'Canada' },
        ],
      };

      render(<Field field={field} value="ca" onChange={mockOnChange} />);

      expect(screen.getByLabelText('Country')).toHaveValue('ca');
    });

    it('should convert value to string', () => {
      const field = {
        id: 'status',
        type: 'select',
        label: 'Status',
        default: 1,
        options: [
          { value: 1, label: 'Active' },
          { value: 2, label: 'Inactive' },
        ],
      };

      render(<Field field={field} value={null} onChange={mockOnChange} />);

      expect(screen.getByLabelText('Status')).toHaveValue('1');
    });

    it('should handle empty options array', () => {
      const field = {
        id: 'country',
        type: 'select',
        label: 'Country',
        default: '',
        options: null,
      };

      render(<Field field={field} value="" onChange={mockOnChange} />);

      expect(screen.getByLabelText('Country')).toBeInTheDocument();
    });

    it('should call onChange with field id and selected value', () => {
      const field = {
        id: 'country',
        type: 'select',
        label: 'Country',
        default: '',
        options: [
          { value: 'us', label: 'United States' },
          { value: 'ca', label: 'Canada' },
        ],
      };

      render(<Field field={field} value="us" onChange={mockOnChange} />);

      fireEvent.change(screen.getByLabelText('Country'), {
        target: { value: 'ca' },
      });

      expect(mockOnChange).toHaveBeenCalledWith('country', 'ca');
    });
  });

  describe('Textarea (text type)', () => {
    it('should render Textarea for text type', () => {
      const field = {
        id: 'bio',
        type: 'text',
        label: 'Biography',
        help_text: 'Enter your biography',
        default: '',
      };

      render(<Field field={field} value="" onChange={mockOnChange} />);

      expect(screen.getByLabelText('Biography')).toBeInTheDocument();
      expect(screen.getByText('Enter your biography')).toBeInTheDocument();
    });

    it('should use provided value', () => {
      const field = {
        id: 'bio',
        type: 'text',
        label: 'Biography',
        default: '',
      };

      render(<Field field={field} value="My bio" onChange={mockOnChange} />);

      expect(screen.getByLabelText('Biography')).toHaveValue('My bio');
    });

    it('should use default value when value is null', () => {
      const field = {
        id: 'bio',
        type: 'text',
        label: 'Biography',
        default: 'Default bio',
      };

      render(<Field field={field} value={null} onChange={mockOnChange} />);

      expect(screen.getByLabelText('Biography')).toHaveValue('Default bio');
    });

    it('should call onChange with field id and value', () => {
      const field = {
        id: 'bio',
        type: 'text',
        label: 'Biography',
        default: '',
      };

      render(<Field field={field} value="" onChange={mockOnChange} />);

      fireEvent.change(screen.getByLabelText('Biography'), {
        target: { value: 'New bio text' },
      });

      expect(mockOnChange).toHaveBeenCalledWith('bio', 'New bio text');
    });

    it('should render with placeholder', () => {
      const field = {
        id: 'bio',
        type: 'text',
        label: 'Biography',
        placeholder: 'Enter your bio here...',
        default: '',
      };

      render(<Field field={field} value="" onChange={mockOnChange} />);

      expect(screen.getByLabelText('Biography')).toHaveAttribute(
        'placeholder',
        'Enter your bio here...'
      );
    });
  });

  describe('Info type', () => {
    it('should render info with label and description', () => {
      const field = {
        id: 'info1',
        type: 'info',
        label: 'Important Information',
        description: 'This is important info',
      };

      render(<Field field={field} value={null} onChange={mockOnChange} />);

      expect(screen.getByText('Important Information')).toBeInTheDocument();
      expect(screen.getByText('This is important info')).toBeInTheDocument();
    });

    it('should render info with only description', () => {
      const field = {
        id: 'info2',
        type: 'info',
        description: 'Just a description',
      };

      render(<Field field={field} value={null} onChange={mockOnChange} />);

      expect(screen.getByText('Just a description')).toBeInTheDocument();
    });

    it('should render info with only label', () => {
      const field = {
        id: 'info3',
        type: 'info',
        label: 'Just a label',
      };

      render(<Field field={field} value={null} onChange={mockOnChange} />);

      expect(screen.getByText('Just a label')).toBeInTheDocument();
    });

    it('should prioritize help_text over description', () => {
      const field = {
        id: 'info4',
        type: 'info',
        label: 'Title',
        help_text: 'Help text takes priority',
        description: 'This should not appear',
      };

      render(<Field field={field} value={null} onChange={mockOnChange} />);

      expect(screen.getByText('Help text takes priority')).toBeInTheDocument();
      expect(screen.queryByText('This should not appear')).not.toBeInTheDocument();
    });

    it('should use field.value if no help_text or description', () => {
      const field = {
        id: 'info5',
        type: 'info',
        label: 'Title',
        value: 'Value text',
      };

      render(<Field field={field} value={null} onChange={mockOnChange} />);

      expect(screen.getByText('Value text')).toBeInTheDocument();
    });

    it('should not call onChange for info type', () => {
      const field = {
        id: 'info6',
        type: 'info',
        label: 'Read-only Info',
        description: 'Cannot be changed',
      };

      render(<Field field={field} value={null} onChange={mockOnChange} />);

      expect(mockOnChange).not.toHaveBeenCalled();
    });
  });

  describe('Password input type', () => {
    it('should render password input when input_type is password', () => {
      const field = {
        id: 'password',
        type: 'string',
        label: 'Password',
        input_type: 'password',
        default: '',
      };

      render(<Field field={field} value="" onChange={mockOnChange} />);

      expect(screen.getByLabelText('Password')).toHaveAttribute('type', 'password');
    });

    it('should render text input when input_type is not password', () => {
      const field = {
        id: 'username',
        type: 'string',
        label: 'Username',
        input_type: 'text',
        default: '',
      };

      render(<Field field={field} value="" onChange={mockOnChange} />);

      expect(screen.getByLabelText('Username')).toHaveAttribute('type', 'text');
    });

    it('should default to text input when input_type is undefined', () => {
      const field = {
        id: 'email',
        type: 'string',
        label: 'Email',
        default: '',
      };

      render(<Field field={field} value="" onChange={mockOnChange} />);

      expect(screen.getByLabelText('Email')).toHaveAttribute('type', 'text');
    });
  });

  describe('Description priority', () => {
    it('should prioritize help_text over description', () => {
      const field = {
        id: 'test',
        type: 'string',
        label: 'Test',
        help_text: 'Help text',
        description: 'Description text',
        default: '',
      };

      render(<Field field={field} value="" onChange={mockOnChange} />);

      expect(screen.getByText('Help text')).toBeInTheDocument();
      expect(screen.queryByText('Description text')).not.toBeInTheDocument();
    });

    it('should use description when help_text is not provided', () => {
      const field = {
        id: 'test',
        type: 'string',
        label: 'Test',
        description: 'Description text',
        default: '',
      };

      render(<Field field={field} value="" onChange={mockOnChange} />);

      expect(screen.getByText('Description text')).toBeInTheDocument();
    });

    it('should use field.value when neither help_text nor description provided', () => {
      const field = {
        id: 'test',
        type: 'string',
        label: 'Test',
        value: 'Value text',
        default: '',
      };

      render(<Field field={field} value="" onChange={mockOnChange} />);

      expect(screen.getByText('Value text')).toBeInTheDocument();
    });

    it('should not show description when all are undefined', () => {
      const field = {
        id: 'test',
        type: 'string',
        label: 'Test',
        default: '',
      };

      render(<Field field={field} value="" onChange={mockOnChange} />);

      expect(screen.getByLabelText('Test')).toBeInTheDocument();
      // No description should be present
    });
  });

  describe('Placeholder handling', () => {
    it('should render placeholder for TextInput', () => {
      const field = {
        id: 'name',
        type: 'string',
        label: 'Name',
        placeholder: 'Enter your name',
        default: '',
      };

      render(<Field field={field} value="" onChange={mockOnChange} />);

      expect(screen.getByLabelText('Name')).toHaveAttribute(
        'placeholder',
        'Enter your name'
      );
    });

    it('should render placeholder for NumberInput', () => {
      const field = {
        id: 'age',
        type: 'number',
        label: 'Age',
        placeholder: 'Enter your age',
        default: 0,
      };

      render(<Field field={field} value={null} onChange={mockOnChange} />);

      expect(screen.getByLabelText('Age')).toHaveAttribute(
        'placeholder',
        'Enter your age'
      );
    });

    it('should render placeholder for Select', () => {
      const field = {
        id: 'country',
        type: 'select',
        label: 'Country',
        placeholder: 'Select a country',
        default: '',
        options: [
          { value: 'us', label: 'United States' },
          { value: 'ca', label: 'Canada' },
        ],
      };

      render(<Field field={field} value="" onChange={mockOnChange} />);

      expect(screen.getByLabelText('Country')).toHaveAttribute(
        'placeholder',
        'Select a country'
      );
    });

    it('should render placeholder for Textarea', () => {
      const field = {
        id: 'bio',
        type: 'text',
        label: 'Biography',
        placeholder: 'Tell us about yourself',
        default: '',
      };

      render(<Field field={field} value="" onChange={mockOnChange} />);

      expect(screen.getByLabelText('Biography')).toHaveAttribute(
        'placeholder',
        'Tell us about yourself'
      );
    });
  });

  describe('Edge cases', () => {
    it('should handle empty string default value', () => {
      const field = {
        id: 'test',
        type: 'string',
        label: 'Test',
        default: '',
      };

      render(<Field field={field} value={null} onChange={mockOnChange} />);

      expect(screen.getByLabelText('Test')).toHaveValue('');
    });

    it('should handle 0 as valid number value', () => {
      const field = {
        id: 'count',
        type: 'number',
        label: 'Count',
        default: 10,
      };

      render(<Field field={field} value={0} onChange={mockOnChange} />);

      expect(screen.getByLabelText('Count')).toHaveValue(0);
    });

    it('should handle false as valid boolean value', () => {
      const field = {
        id: 'enabled',
        type: 'boolean',
        label: 'Enabled',
        default: true,
      };

      render(<Field field={field} value={false} onChange={mockOnChange} />);

      expect(screen.getByLabelText('Enabled')).not.toBeChecked();
    });

    it('should handle empty string as valid select value', () => {
      const field = {
        id: 'status',
        type: 'select',
        label: 'Status',
        default: 'active',
        options: [
          { value: '', label: 'None' },
          { value: 'active', label: 'Active' },
        ],
      };

      render(<Field field={field} value="" onChange={mockOnChange} />);

      expect(screen.getByLabelText('Status')).toHaveValue('');
    });
  });

  describe('Default fallback', () => {
    it('should render TextInput for unknown type', () => {
      const field = {
        id: 'custom',
        type: 'unknown',
        label: 'Custom Field',
        default: '',
      };

      render(<Field field={field} value="" onChange={mockOnChange} />);

      expect(screen.getByLabelText('Custom Field')).toBeInTheDocument();
    });
  });
});
