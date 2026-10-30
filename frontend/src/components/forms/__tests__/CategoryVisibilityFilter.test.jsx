import { useState } from 'react';
import { MantineProvider } from '@mantine/core';
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import CategoryVisibilityFilter from '../CategoryVisibilityFilter.jsx';
import { DEFAULT_CATEGORY_VISIBILITY } from '../../../utils/categoryVisibility.js';

const categories = [
  { enabled: true },
  { enabled: false },
  { enabled: false, ignored: true },
];

const renderFilter = (value, rows = categories) =>
  render(
    <MantineProvider env="test">
      <CategoryVisibilityFilter
        value={value}
        categories={rows}
        onChange={vi.fn()}
      />
    </MantineProvider>
  );

describe('Category visibility indicator', () => {
  it.each([
    { enabled: true, disabled: false, ignored: true },
    { enabled: false, disabled: true, ignored: true },
    { enabled: false, disabled: false, ignored: false },
    DEFAULT_CATEGORY_VISIBILITY,
  ])('marks a restricted status selection (%j)', (value) => {
    const { container } = renderFilter(value);
    const trigger = screen.getByRole('button', {
      name: 'Filter category status',
    });
    expect(trigger).toHaveAttribute('data-filter-active', 'true');
    expect(trigger).toHaveAccessibleDescription(
      'Category status filter active'
    );
    const indicator = container.querySelector('.mantine-Indicator-indicator');
    expect(indicator).toBeInTheDocument();
    expect(indicator).toHaveAttribute('data-with-border');
    expect(
      indicator.parentElement.style.getPropertyValue('--indicator-color')
    ).toBe('var(--mantine-color-red-filled)');
    expect(
      indicator.parentElement.style.getPropertyValue('--indicator-size')
    ).toBe('calc(0.625rem * var(--mantine-scale))');
  });

  it('does not mark the default selection when no ignored categories are hidden', () => {
    const { container } = renderFilter(
      DEFAULT_CATEGORY_VISIBILITY,
      categories.slice(0, 2)
    );
    expect(
      container.querySelector('.mantine-Indicator-indicator')
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: 'Filter category status' })
    ).not.toHaveAttribute('aria-description');
  });

  it.each([
    [{ enabled: true, disabled: false, ignored: true }, 1],
    [{ enabled: false, disabled: true, ignored: true }, 1],
    [{ enabled: false, disabled: false, ignored: false }, 3],
    [DEFAULT_CATEGORY_VISIBILITY, 1],
  ])(
    'counts every status hidden by %j, not search results',
    async (value, count) => {
      renderFilter(value);
      const button = screen.getByRole('button', {
        name: 'Filter category status',
      });
      expect(button).toHaveAttribute('data-hidden-count', String(count));
      expect(
        screen.queryByText(/categories? filtered/)
      ).not.toBeInTheDocument();
      fireEvent.mouseEnter(button);
      expect(await screen.findByRole('tooltip')).toHaveTextContent(
        `${count} ${count === 1 ? 'category' : 'categories'} filtered`
      );
      fireEvent.click(button);
      expect(
        await screen.findByText(
          `${count} ${count === 1 ? 'category' : 'categories'} filtered`,
          { selector: 'p' }
        )
      ).toBeVisible();
    }
  );

  it('does not mark a selection that shows every status', () => {
    const { container } = renderFilter({
      enabled: true,
      disabled: true,
      ignored: true,
    });
    expect(
      container.querySelector('.mantine-Indicator-indicator')
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: 'Filter category status' })
    ).not.toHaveAttribute('data-filter-active');
  });

  it('updates the indicator when filters change or reset without modifying categories', () => {
    const onChange = vi.fn();
    const rows = categories.slice(0, 2);
    const original = JSON.stringify(rows);
    function FilterHarness() {
      const [value, setValue] = useState(DEFAULT_CATEGORY_VISIBILITY);
      return (
        <CategoryVisibilityFilter
          value={value}
          categories={rows}
          onChange={(next) => {
            onChange(next);
            setValue(next);
          }}
        />
      );
    }
    const { container } = render(
      <MantineProvider env="test">
        <FilterHarness />
      </MantineProvider>
    );
    fireEvent.click(
      screen.getByRole('button', { name: 'Filter category status' })
    );
    fireEvent.click(
      screen.getByRole('checkbox', { name: 'Disabled', exact: true })
    );
    expect(
      container.querySelector('.mantine-Indicator-indicator')
    ).toBeInTheDocument();
    expect(onChange).toHaveBeenLastCalledWith({
      enabled: true,
      disabled: false,
      ignored: false,
    });
    fireEvent.click(screen.getByRole('button', { name: 'Reset filters' }));
    expect(
      container.querySelector('.mantine-Indicator-indicator')
    ).not.toBeInTheDocument();
    expect(onChange).toHaveBeenLastCalledWith(DEFAULT_CATEGORY_VISIBILITY);
    expect(JSON.stringify(rows)).toBe(original);
  });

  it('removes the indicator when the last hidden ignored category is revealed', () => {
    const { container, rerender } = renderFilter(DEFAULT_CATEGORY_VISIBILITY);
    expect(
      container.querySelector('.mantine-Indicator-indicator')
    ).toBeInTheDocument();
    rerender(
      <MantineProvider env="test">
        <CategoryVisibilityFilter
          value={{ ...DEFAULT_CATEGORY_VISIBILITY, ignored: true }}
          categories={categories}
          onChange={vi.fn()}
        />
      </MantineProvider>
    );
    expect(
      container.querySelector('.mantine-Indicator-indicator')
    ).not.toBeInTheDocument();
  });
});
