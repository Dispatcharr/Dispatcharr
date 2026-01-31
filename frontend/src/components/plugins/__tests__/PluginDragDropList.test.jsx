import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import PluginDragDropList from '../PluginDragDropList';
import { usePluginContext } from '../PluginRenderer';
import API from '../../../api';

// Mock the API
vi.mock('../../../api', () => ({
  default: {
    getPluginData: vi.fn(),
  },
}));

// Mock the plugin context
vi.mock('../PluginRenderer', () => ({
  usePluginContext: vi.fn(),
}));

// Mock @mantine/core
vi.mock('@mantine/core', async () => {
  return {
    Stack: ({ children, gap }) => (
      <div data-testid="stack" data-gap={gap}>
        {children}
      </div>
    ),
    Group: ({ children, justify, wrap }) => (
      <div data-testid="group" data-justify={justify} data-wrap={wrap}>
        {children}
      </div>
    ),
    Text: ({ children, c, fw, size, truncate }) => (
      <span data-testid="text" data-color={c} data-fw={fw} data-size={size}>
        {children}
      </span>
    ),
    Card: ({ children, padding, withBorder, shadow, style }) => (
      <div
        data-testid="card"
        data-padding={padding}
        data-with-border={withBorder}
        data-shadow={shadow}
        style={style}
      >
        {children}
      </div>
    ),
    ActionIcon: ({ children, onClick, variant, color, style, ...rest }) => (
      <button
        data-testid="action-icon"
        onClick={onClick}
        data-variant={variant}
        data-color={color}
        style={style}
        {...rest}
      >
        {children}
      </button>
    ),
    Menu: ({ children }) => <div data-testid="menu">{children}</div>,
    Loader: ({ size }) => <div data-testid="loader" data-size={size}>Loading...</div>,
    Center: ({ children, py }) => (
      <div data-testid="center" data-py={py}>
        {children}
      </div>
    ),
    Badge: ({ children, size, variant }) => (
      <span data-testid="badge" data-size={size} data-variant={variant}>
        {children}
      </span>
    ),
  };
});

// Simplified mocks for Menu subcomponents
vi.mock('@mantine/core', async (importOriginal) => {
  const actual = await importOriginal();
  return {
    ...actual,
    Menu: Object.assign(
      ({ children }) => <div data-testid="menu">{children}</div>,
      {
        Target: ({ children }) => <div data-testid="menu-target">{children}</div>,
        Dropdown: ({ children }) => <div data-testid="menu-dropdown">{children}</div>,
        Item: ({ children, onClick, color, leftSection }) => (
          <button
            data-testid="menu-item"
            onClick={onClick}
            data-color={color}
          >
            {leftSection}
            {children}
          </button>
        ),
      }
    ),
    Stack: ({ children, gap }) => (
      <div data-testid="stack" data-gap={gap}>
        {children}
      </div>
    ),
    Group: ({ children, justify, wrap }) => (
      <div data-testid="group" data-justify={justify} data-wrap={wrap}>
        {children}
      </div>
    ),
    Text: ({ children, c, fw, size, truncate }) => (
      <span data-testid="text" data-color={c} data-fw={fw} data-size={size}>
        {children}
      </span>
    ),
    Card: ({ children, padding, withBorder, shadow, style, ref }) => (
      <div
        data-testid="card"
        data-padding={padding}
        data-with-border={withBorder}
        data-shadow={shadow}
        style={style}
      >
        {children}
      </div>
    ),
    ActionIcon: ({ children, onClick, variant, color, style, ...rest }) => (
      <button
        data-testid="action-icon"
        onClick={onClick}
        data-variant={variant}
        data-color={color}
        style={style}
        {...rest}
      >
        {children}
      </button>
    ),
    Loader: ({ size }) => <div data-testid="loader" data-size={size}>Loading...</div>,
    Center: ({ children, py }) => (
      <div data-testid="center" data-py={py}>
        {children}
      </div>
    ),
    Badge: ({ children, size, variant }) => (
      <span data-testid="badge" data-size={size} data-variant={variant}>
        {children}
      </span>
    ),
  };
});

// Mock @dnd-kit
vi.mock('@dnd-kit/core', () => ({
  DndContext: ({ children, onDragEnd }) => (
    <div data-testid="dnd-context">{children}</div>
  ),
  closestCenter: vi.fn(),
  KeyboardSensor: vi.fn(),
  PointerSensor: vi.fn(),
  useSensor: vi.fn(() => ({})),
  useSensors: vi.fn(() => []),
}));

vi.mock('@dnd-kit/sortable', () => ({
  arrayMove: vi.fn((arr, from, to) => {
    const result = [...arr];
    const [removed] = result.splice(from, 1);
    result.splice(to, 0, removed);
    return result;
  }),
  SortableContext: ({ children }) => (
    <div data-testid="sortable-context">{children}</div>
  ),
  sortableKeyboardCoordinates: vi.fn(),
  useSortable: vi.fn(() => ({
    attributes: {},
    listeners: {},
    setNodeRef: vi.fn(),
    transform: null,
    transition: null,
    isDragging: false,
  })),
  verticalListSortingStrategy: {},
}));

vi.mock('@dnd-kit/utilities', () => ({
  CSS: {
    Transform: {
      toString: vi.fn(() => null),
    },
  },
}));

vi.mock('@dnd-kit/modifiers', () => ({
  restrictToVerticalAxis: {},
}));

// Mock lucide-react icons
vi.mock('lucide-react', () => ({
  MoreVertical: () => <span data-testid="icon-more-vertical">MoreVertical</span>,
  Edit: () => <span data-testid="icon-edit">Edit</span>,
  Trash: () => <span data-testid="icon-trash">Trash</span>,
  RefreshCw: () => <span data-testid="icon-refresh">RefreshCw</span>,
  Eye: () => <span data-testid="icon-eye">Eye</span>,
  GripVertical: () => <span data-testid="icon-grip">GripVertical</span>,
}));

describe('PluginDragDropList', () => {
  const mockContextValue = {
    pluginKey: 'test-plugin',
    dataRefreshKey: 0,
    runAction: vi.fn(),
  };

  const mockData = [
    { _id: '1', name: 'Item 1', description: 'Description 1', order: 0 },
    { _id: '2', name: 'Item 2', description: 'Description 2', order: 1 },
    { _id: '3', name: 'Item 3', description: 'Description 3', order: 2 },
  ];

  beforeEach(() => {
    vi.clearAllMocks();
    usePluginContext.mockReturnValue(mockContextValue);
    API.getPluginData.mockResolvedValue(mockData);
  });

  describe('Loading State', () => {
    it('shows loader while fetching data', () => {
      API.getPluginData.mockImplementation(() => new Promise(() => {})); // Never resolves

      render(
        <PluginDragDropList
          data_source="items"
          item_template={{ title: '{{name}}' }}
        />
      );

      expect(screen.getByTestId('loader')).toBeInTheDocument();
    });
  });

  describe('Empty State', () => {
    it('shows empty message when no data', async () => {
      API.getPluginData.mockResolvedValue([]);

      render(
        <PluginDragDropList
          data_source="items"
          item_template={{ title: '{{name}}' }}
          empty_message="No items found"
        />
      );

      await waitFor(() => {
        expect(screen.getByText('No items found')).toBeInTheDocument();
      });
    });

    it('uses default empty message', async () => {
      API.getPluginData.mockResolvedValue([]);

      render(
        <PluginDragDropList
          data_source="items"
          item_template={{ title: '{{name}}' }}
        />
      );

      await waitFor(() => {
        expect(screen.getByText('No items')).toBeInTheDocument();
      });
    });
  });

  describe('Data Display', () => {
    it('fetches data from the correct collection', async () => {
      render(
        <PluginDragDropList
          data_source="calendars"
          item_template={{ title: '{{name}}' }}
        />
      );

      await waitFor(() => {
        expect(API.getPluginData).toHaveBeenCalledWith('test-plugin', 'calendars');
      });
    });

    it('renders items with title template', async () => {
      render(
        <PluginDragDropList
          data_source="items"
          item_template={{ title: '{{name}}' }}
        />
      );

      await waitFor(() => {
        expect(screen.getByText('Item 1')).toBeInTheDocument();
        expect(screen.getByText('Item 2')).toBeInTheDocument();
        expect(screen.getByText('Item 3')).toBeInTheDocument();
      });
    });

    it('renders items with subtitle template', async () => {
      render(
        <PluginDragDropList
          data_source="items"
          item_template={{
            title: '{{name}}',
            subtitle: '{{description}}',
          }}
        />
      );

      await waitFor(() => {
        expect(screen.getByText('Description 1')).toBeInTheDocument();
        expect(screen.getByText('Description 2')).toBeInTheDocument();
      });
    });

    it('renders items with badge template', async () => {
      const dataWithStatus = [
        { _id: '1', name: 'Item 1', status: 'Active', order: 0 },
      ];
      API.getPluginData.mockResolvedValue(dataWithStatus);

      render(
        <PluginDragDropList
          data_source="items"
          item_template={{
            title: '{{name}}',
            badge: '{{status}}',
          }}
        />
      );

      await waitFor(() => {
        expect(screen.getByText('Active')).toBeInTheDocument();
      });
    });

    it('sorts items by order field', async () => {
      const unsortedData = [
        { _id: '2', name: 'Item 2', order: 1 },
        { _id: '1', name: 'Item 1', order: 0 },
        { _id: '3', name: 'Item 3', order: 2 },
      ];
      API.getPluginData.mockResolvedValue(unsortedData);

      render(
        <PluginDragDropList
          data_source="items"
          item_template={{ title: '{{name}}' }}
        />
      );

      await waitFor(() => {
        const items = screen.getAllByText(/Item \d/);
        expect(items[0]).toHaveTextContent('Item 1');
        expect(items[1]).toHaveTextContent('Item 2');
        expect(items[2]).toHaveTextContent('Item 3');
      });
    });
  });

  describe('Drag Handle', () => {
    it('renders drag handles for each item', async () => {
      render(
        <PluginDragDropList
          data_source="items"
          item_template={{ title: '{{name}}' }}
        />
      );

      await waitFor(() => {
        const gripIcons = screen.getAllByTestId('icon-grip');
        expect(gripIcons).toHaveLength(3);
      });
    });
  });

  describe('DnD Context', () => {
    it('wraps items in DndContext', async () => {
      render(
        <PluginDragDropList
          data_source="items"
          item_template={{ title: '{{name}}' }}
        />
      );

      await waitFor(() => {
        expect(screen.getByTestId('dnd-context')).toBeInTheDocument();
      });
    });

    it('wraps items in SortableContext', async () => {
      render(
        <PluginDragDropList
          data_source="items"
          item_template={{ title: '{{name}}' }}
        />
      );

      await waitFor(() => {
        expect(screen.getByTestId('sortable-context')).toBeInTheDocument();
      });
    });
  });

  describe('Actions', () => {
    it('renders action menu when actions are provided', async () => {
      render(
        <PluginDragDropList
          data_source="items"
          item_template={{ title: '{{name}}' }}
          actions={[
            { id: 'edit', label: 'Edit', icon: 'edit', action: 'edit_item' },
            { id: 'delete', label: 'Delete', icon: 'trash', action: 'delete_item', color: 'red' },
          ]}
        />
      );

      await waitFor(() => {
        const menus = screen.getAllByTestId('menu');
        expect(menus.length).toBeGreaterThan(0);
      });
    });

    it('does not render action menu when no actions', async () => {
      render(
        <PluginDragDropList
          data_source="items"
          item_template={{ title: '{{name}}' }}
          actions={[]}
        />
      );

      await waitFor(() => {
        expect(screen.queryByTestId('menu')).not.toBeInTheDocument();
      });
    });
  });

  describe('Data Refresh', () => {
    it('refetches data when dataRefreshKey changes', async () => {
      const { rerender } = render(
        <PluginDragDropList
          data_source="items"
          item_template={{ title: '{{name}}' }}
        />
      );

      await waitFor(() => {
        expect(API.getPluginData).toHaveBeenCalledTimes(1);
      });

      // Simulate context change
      usePluginContext.mockReturnValue({
        ...mockContextValue,
        dataRefreshKey: 1,
      });

      rerender(
        <PluginDragDropList
          data_source="items"
          item_template={{ title: '{{name}}' }}
        />
      );

      await waitFor(() => {
        expect(API.getPluginData).toHaveBeenCalledTimes(2);
      });
    });
  });

  describe('Template Interpolation', () => {
    it('handles missing template variables gracefully', async () => {
      const dataWithMissingField = [
        { _id: '1', name: 'Item 1', order: 0 },
      ];
      API.getPluginData.mockResolvedValue(dataWithMissingField);

      render(
        <PluginDragDropList
          data_source="items"
          item_template={{
            title: '{{name}}',
            subtitle: '{{missing_field}}',
          }}
        />
      );

      await waitFor(() => {
        expect(screen.getByText('Item 1')).toBeInTheDocument();
        // Should not crash, missing field renders as empty
      });
    });

    it('handles null values in templates', async () => {
      const dataWithNull = [
        { _id: '1', name: 'Item 1', description: null, order: 0 },
      ];
      API.getPluginData.mockResolvedValue(dataWithNull);

      render(
        <PluginDragDropList
          data_source="items"
          item_template={{
            title: '{{name}}',
            subtitle: '{{description}}',
          }}
        />
      );

      await waitFor(() => {
        expect(screen.getByText('Item 1')).toBeInTheDocument();
      });
    });
  });
});
