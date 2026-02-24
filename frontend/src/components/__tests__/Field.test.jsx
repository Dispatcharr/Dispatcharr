import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { Field } from '../Field';

// Mock Mantine components
vi.mock('@mantine/core', async () => {
  return {
    TextInput: ({ label, description, value, onChange }) => (
      <div>
        <label htmlFor="text-input">{label}</label>
        <input
          id="text-input"
          type="text"
          value={value}
          onChange={onChange}
          aria-describedby={description}
        />
        {description && <div>{description}</div>}
      </div>
    ),
    NumberInput: ({ label, description, value, onChange }) => (
      <div>
        <label htmlFor="number-input">{label}</label>
        <input
          id="number-input"
          type="number"
          value={value}
          onChange={(e) => onChange(Number(e.target.value))}
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
    Select: ({ label, description, value, data, onChange }) => (
      <div>
        <label htmlFor="select-input">{label}</label>
        <select
          id="select-input"
          value={value}
          onChange={(e) => onChange(e.target.value)}
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
