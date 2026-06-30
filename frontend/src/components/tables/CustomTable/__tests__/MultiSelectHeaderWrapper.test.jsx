import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';

// ── Mantine core mock ──────────────────────────────────────────────────────────
// We need MultiSelect to be identifiable by reference (element.type === MultiSelect),
// so we export it from the mock so the component under test can compare against it.
vi.mock('@mantine/core', async () => {
  const MockMultiSelect = ({
    value = [],
    data = [],
    onChange,
    label
  }) => (
    <div data-testid="multiselect" data-value={JSON.stringify(value)}>
      {label && <label>{label}</label>}
      <input
        data-testid="multiselect-input"
        onChange={(e) => onChange?.(e.target.value ? [e.target.value] : [])}
      />
      {(data || []).map((opt) => (
        <option key={opt.value} value={opt.value}>
          {opt.label}
        </option>
      ))}
    </div>
  );
  MockMultiSelect.displayName = 'MultiSelect';

  return {
    MultiSelect: MockMultiSelect,
    Box: ({ children, style, ...props }) => (
      <div data-testid="box" style={style} {...props}>
        {children}
      </div>
    ),
    Flex: ({ children, style }) => (
      <div data-testid="flex" style={style}>
        {children}
      </div>
    ),
    Pill: ({
      children,
      onRemove,
      onClick,
      withRemoveButton,
      removeButtonProps,
    }) => (
      <span data-testid="pill" onClick={onClick}>
        {children}
        {withRemoveButton && (
          <button
            data-testid="pill-remove"
            onClick={removeButtonProps?.onClick ?? onRemove}
          >
            ×
          </button>
        )}
      </span>
    ),
    Tooltip: ({ children, label }) => (
      <div
        data-testid="tooltip"
        data-label={typeof label === 'string' ? label : 'jsx'}
      >
        {label}
        {children}
      </div>
    ),
  };
});

// ── Imports after mocks ────────────────────────────────────────────────────────
import { MultiSelect } from '@mantine/core';
import MultiSelectHeaderWrapper from '../MultiSelectHeaderWrapper';

// ── Helpers ────────────────────────────────────────────────────────────────────
const makeData = (n = 3) =>
  Array.from({ length: n }, (_, i) => ({
    value: `val-${i}`,
    label: `Label ${i}`,
  }));

describe('MultiSelectHeaderWrapper', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // ── Non-MultiSelect passthrough ────────────────────────────────────────────

  describe('non-MultiSelect children', () => {
    it('renders a plain div child unchanged', () => {
      render(
        <MultiSelectHeaderWrapper>
          <div data-testid="plain-child">Hello</div>
        </MultiSelectHeaderWrapper>
      );
      expect(screen.getByTestId('plain-child')).toBeInTheDocument();
      expect(screen.getByText('Hello')).toBeInTheDocument();
    });

    it('renders a plain text node unchanged', () => {
      render(
        <MultiSelectHeaderWrapper>{'just text'}</MultiSelectHeaderWrapper>
      );
      expect(screen.getByText('just text')).toBeInTheDocument();
    });

    it('recursively passes through nested non-MultiSelect elements', () => {
      render(
        <MultiSelectHeaderWrapper>
          <div>
            <span data-testid="nested">Nested</span>
          </div>
        </MultiSelectHeaderWrapper>
      );
      expect(screen.getByTestId('nested')).toBeInTheDocument();
    });
  });

  // ── MultiSelect with no selections ────────────────────────────────────────

  describe('MultiSelect with no selections', () => {
    it('renders the MultiSelect directly when value is empty', () => {
      render(
        <MultiSelectHeaderWrapper>
          <MultiSelect value={[]} data={makeData()} onChange={vi.fn()} />
        </MultiSelectHeaderWrapper>
      );
      expect(screen.getByTestId('multiselect')).toBeInTheDocument();
    });

    it('does not render pills when value is empty', () => {
      render(
        <MultiSelectHeaderWrapper>
          <MultiSelect value={[]} data={makeData()} onChange={vi.fn()} />
        </MultiSelectHeaderWrapper>
      );
      expect(screen.queryByTestId('pill')).not.toBeInTheDocument();
    });

    it('does not render a tooltip when value is empty', () => {
      render(
        <MultiSelectHeaderWrapper>
          <MultiSelect value={[]} data={makeData()} onChange={vi.fn()} />
        </MultiSelectHeaderWrapper>
      );
      expect(screen.queryByTestId('tooltip')).not.toBeInTheDocument();
    });

    it('handles undefined value as no selections', () => {
      render(
        <MultiSelectHeaderWrapper>
          <MultiSelect data={makeData()} onChange={vi.fn()} />
        </MultiSelectHeaderWrapper>
      );
      expect(screen.queryByTestId('pill')).not.toBeInTheDocument();
    });
  });

  // ── MultiSelect with one selection ────────────────────────────────────────

  describe('MultiSelect with one selection', () => {
    const data = makeData(3);
    const value = ['val-0'];

    it('renders a pill showing the first selected label', () => {
      render(
        <MultiSelectHeaderWrapper>
          <MultiSelect value={value} data={data} onChange={vi.fn()} />
        </MultiSelectHeaderWrapper>
      );
      const pill = screen.getByTestId('pill');
      expect(pill).toBeInTheDocument();
      expect(pill).toHaveTextContent('Label 0');
    });

    it('renders exactly one pill for a single selection', () => {
      render(
        <MultiSelectHeaderWrapper>
          <MultiSelect value={value} data={data} onChange={vi.fn()} />
        </MultiSelectHeaderWrapper>
      );
      expect(screen.getAllByTestId('pill')).toHaveLength(1);
    });

    it('renders a tooltip wrapping the pill area', () => {
      render(
        <MultiSelectHeaderWrapper>
          <MultiSelect value={value} data={data} onChange={vi.fn()} />
        </MultiSelectHeaderWrapper>
      );
      expect(screen.getByTestId('tooltip')).toBeInTheDocument();
    });

    it('still renders the underlying MultiSelect', () => {
      render(
        <MultiSelectHeaderWrapper>
          <MultiSelect value={value} data={data} onChange={vi.fn()} />
        </MultiSelectHeaderWrapper>
      );
      expect(screen.getByTestId('multiselect')).toBeInTheDocument();
    });

    it('falls back to the raw value when label is not found in data', () => {
      render(
        <MultiSelectHeaderWrapper>
          <MultiSelect value={['unknown-val']} data={[]} onChange={vi.fn()} />
        </MultiSelectHeaderWrapper>
      );
      const pill = screen.getByTestId('pill');
      expect(pill).toBeInTheDocument();
      expect(pill).toHaveTextContent('unknown-val');
    });

    it('calls onChange with remaining values when the remove button is clicked', () => {
      const onChange = vi.fn();
      render(
        <MultiSelectHeaderWrapper>
          <MultiSelect value={['val-0']} data={data} onChange={onChange} />
        </MultiSelectHeaderWrapper>
      );
      fireEvent.click(screen.getByTestId('pill-remove'));
      expect(onChange).toHaveBeenCalledWith([]);
    });
  });

  // ── MultiSelect with multiple selections ──────────────────────────────────

  describe('MultiSelect with multiple selections', () => {
    const data = makeData(5);
    const value = ['val-0', 'val-1', 'val-2'];

    it('renders two pills: first label and overflow count', () => {
      render(
        <MultiSelectHeaderWrapper>
          <MultiSelect value={value} data={data} onChange={vi.fn()} />
        </MultiSelectHeaderWrapper>
      );
      expect(screen.getAllByTestId('pill')).toHaveLength(2);
    });

    it('shows the first label in the first pill', () => {
      render(
        <MultiSelectHeaderWrapper>
          <MultiSelect value={value} data={data} onChange={vi.fn()} />
        </MultiSelectHeaderWrapper>
      );
      const pills = screen.getAllByTestId('pill');
      expect(pills[0]).toHaveTextContent('Label 0');
    });

    it('shows "+N" overflow count in the second pill', () => {
      render(
        <MultiSelectHeaderWrapper>
          <MultiSelect value={value} data={data} onChange={vi.fn()} />
        </MultiSelectHeaderWrapper>
      );
      // 3 selections → "+2"
      expect(screen.getByText('+2')).toBeInTheDocument();
    });

    it('calls onChange with slice(1) when first pill remove is clicked', () => {
      const onChange = vi.fn();
      render(
        <MultiSelectHeaderWrapper>
          <MultiSelect value={value} data={data} onChange={onChange} />
        </MultiSelectHeaderWrapper>
      );
      const removeButtons = screen.getAllByTestId('pill-remove');
      fireEvent.click(removeButtons[0]);
      expect(onChange).toHaveBeenCalledWith(['val-1', 'val-2']);
    });

    it('calls onChange with [] when overflow pill remove is clicked', () => {
      const onChange = vi.fn();
      render(
        <MultiSelectHeaderWrapper>
          <MultiSelect value={value} data={data} onChange={onChange} />
        </MultiSelectHeaderWrapper>
      );
      const removeButtons = screen.getAllByTestId('pill-remove');
      fireEvent.click(removeButtons[1]);
      expect(onChange).toHaveBeenCalledWith([]);
    });
  });

  // ── Tooltip with more than 10 selections ──────────────────────────────────

  describe('tooltip overflow for > 10 selections', () => {
    it('shows "+N more" text in tooltip area when more than 10 values are selected', () => {
      const data = makeData(15);
      const value = data.map((d) => d.value);

      render(
        <MultiSelectHeaderWrapper>
          <MultiSelect value={value} data={data} onChange={vi.fn()} />
        </MultiSelectHeaderWrapper>
      );
      expect(screen.getByText('+5 more')).toBeInTheDocument();
    });

    it('does not show "+N more" when selections are 10 or fewer', () => {
      const data = makeData(10);
      const value = data.map((d) => d.value);

      render(
        <MultiSelectHeaderWrapper>
          <MultiSelect value={value} data={data} onChange={vi.fn()} />
        </MultiSelectHeaderWrapper>
      );
      expect(screen.queryByText(/more$/)).not.toBeInTheDocument();
    });
  });

  // ── Recursive enhancement ──────────────────────────────────────────────────

  describe('recursive MultiSelect enhancement', () => {
    it('enhances a MultiSelect nested inside a wrapper div', () => {
      render(
        <MultiSelectHeaderWrapper>
          <div>
            <MultiSelect
              value={['val-0']}
              data={makeData()}
              onChange={vi.fn()}
            />
          </div>
        </MultiSelectHeaderWrapper>
      );
      expect(screen.getByTestId('pill')).toBeInTheDocument();
      expect(screen.getByTestId('pill')).toHaveTextContent('Label 0');
    });
  });

  // ── onChange absence ──────────────────────────────────────────────────────

  describe('onChange not provided', () => {
    it('does not throw when onChange is undefined and remove is clicked', () => {
      render(
        <MultiSelectHeaderWrapper>
          <MultiSelect value={['val-0']} data={makeData()} />
        </MultiSelectHeaderWrapper>
      );
      expect(() =>
        fireEvent.click(screen.getByTestId('pill-remove'))
      ).not.toThrow();
    });

    it('does not throw when clearAll is triggered without onChange', () => {
      render(
        <MultiSelectHeaderWrapper>
          <MultiSelect value={['val-0', 'val-1']} data={makeData()} />
        </MultiSelectHeaderWrapper>
      );
      const removeButtons = screen.getAllByTestId('pill-remove');
      expect(() => fireEvent.click(removeButtons[1])).not.toThrow();
    });
  });
});
