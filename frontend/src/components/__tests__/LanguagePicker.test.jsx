import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

vi.mock('@mantine/core', () => ({
  Button: ({ children, onClick, disabled, 'aria-label': ariaLabel }) => (
    <button aria-label={ariaLabel} disabled={disabled} onClick={onClick}>
      {children}
    </button>
  ),
  Group: ({ children }) => <div>{children}</div>,
  Checkbox: ({ label, checked, onChange }) => (
    <label>
      <input type="checkbox" checked={checked} onChange={onChange} />
      {label}
    </label>
  ),
  Modal: ({ opened, children, title }) =>
    opened ? (
      <div>
        <h2>{title}</h2>
        {children}
      </div>
    ) : null,
  ScrollArea: ({ children }) => <div>{children}</div>,
  Select: ({ data = [], value, onChange, 'aria-label': ariaLabel }) => (
    <select
      aria-label={ariaLabel}
      value={value || ''}
      onChange={(event) => onChange(event.target.value || null)}
    >
      <option value="" />
      {data.map((option) => (
        <option key={option.value} value={option.value}>
          {option.label}
        </option>
      ))}
    </select>
  ),
  Stack: ({ children }) => <div>{children}</div>,
  Text: ({ children }) => <span>{children}</span>,
  TextInput: ({ value, onChange, 'aria-label': ariaLabel }) => (
    <input aria-label={ariaLabel} value={value} onChange={onChange} />
  ),
}));

import LanguagePicker from '../LanguagePicker.jsx';

describe('LanguagePicker', () => {
  it('opens a fixed language chooser and applies the selection', () => {
    const onChange = vi.fn();
    render(<LanguagePicker label="DUB" value={['ger']} onChange={onChange} />);

    fireEvent.click(screen.getByLabelText('Add DUB language'));
    fireEvent.click(screen.getByLabelText('ENG — English'));
    fireEvent.click(screen.getByRole('button', { name: 'Apply' }));

    expect(onChange).toHaveBeenCalledWith(['ger', 'eng']);
  });

  it('removes an existing language explicitly', () => {
    const onChange = vi.fn();
    render(
      <LanguagePicker label="SUB" value={['ger', 'eng']} onChange={onChange} />
    );

    fireEvent.click(screen.getByLabelText('Remove ger'));

    expect(onChange).toHaveBeenCalledWith(['eng']);
  });
});
