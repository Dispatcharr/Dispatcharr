import { MantineProvider } from '@mantine/core';
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { Field } from '../Field';
import { PluginTableField } from '../PluginTableField';

const options = Array.from({ length: 11 }, (_, i) => ({
  value: String(i),
  label: `Option ${i}`,
}));

describe('plugin select search', () => {
  it('filters a large select and reports the selected value', () => {
    const onChange = vi.fn();
    render(
      <MantineProvider>
        <Field field={{ id: 'choice', type: 'select', label: 'Choice', options }} onChange={onChange} />
      </MantineProvider>
    );
    const input = screen.getByRole('textbox', { name: 'Choice' });
    fireEvent.change(input, { target: { value: 'Option 10' } });
    expect(screen.getByRole('option', { name: 'Option 10' })).toBeInTheDocument();
    expect(screen.queryByRole('option', { name: 'Option 1' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('option', { name: 'Option 10' }));
    expect(onChange).toHaveBeenCalledWith('choice', '10');
  });

  it.each([0, 10, 11])('applies the threshold to table selects with %i options', (count) => {
    const onChange = vi.fn();
    const field = { id: 'table', columns: [{ id: 'choice', type: 'select', options: options.slice(0, count) }] };
    render(
      <MantineProvider>
        <PluginTableField field={field} value={[{ choice: '0' }]} onChange={onChange} />
      </MantineProvider>
    );
    const input = screen.getByRole('textbox');
    if (count > 10) expect(input).not.toHaveAttribute('readonly');
    else expect(input).toHaveAttribute('readonly');
    if (count === 11) {
      fireEvent.change(input, { target: { value: 'Option 10' } });
      fireEvent.click(screen.getByRole('option', { name: 'Option 10' }));
      expect(onChange).toHaveBeenCalledWith('table', [{ choice: '10' }]);
    }
  });
});
