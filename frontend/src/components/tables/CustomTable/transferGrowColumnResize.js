/**
 * When a column with transferResizeToNeighbor is resized, apply the pixel delta
 * to the next fixed column instead. That keeps total width to the right of a
 * grow column stable so the dragged divider moves with the pointer.
 *
 * Used for grow columns (CSS ignores their size) and for fixed columns that sit
 * after a grow column (otherwise they expand left into the grow column).
 *
 * Pass dragStart when applying deltas from a live TanStack drag so each event is
 * absolute from mousedown (avoids double-applying after clamps).
 */
export const transferGrowColumnResize = ({
  previousSizing,
  nextSizing,
  growColumnId,
  neighborId,
  defaults = {},
  neighborMin = 0,
  neighborMax = Number.POSITIVE_INFINITY,
  dragStart = null,
}) => {
  if (!neighborId) {
    return nextSizing;
  }

  const previousSource =
    previousSizing[growColumnId] ?? defaults[growColumnId] ?? 0;
  const requestedSource = nextSizing[growColumnId] ?? previousSource;

  const startSource = dragStart?.sourceSize ?? previousSource;
  const previousNeighbor =
    previousSizing[neighborId] ?? defaults[neighborId] ?? 0;
  const startNeighbor = dragStart?.neighborSize ?? previousNeighbor;

  if (requestedSource === startSource && !dragStart) {
    return nextSizing;
  }

  const requestedDelta = requestedSource - startSource;
  const nextNeighbor = Math.min(
    neighborMax,
    Math.max(neighborMin, startNeighbor - requestedDelta)
  );
  const appliedDelta = startNeighbor - nextNeighbor;

  return {
    ...previousSizing,
    ...nextSizing,
    [growColumnId]: startSource + appliedDelta,
    [neighborId]: nextNeighbor,
  };
};

export const getColumnId = (column) => column.id ?? column.accessorKey;

/**
 * Find the next visible, non-grow column after `columnId`.
 * That neighbor receives the pixel transfer when the source column is resized.
 */
export const findGrowResizeNeighbor = (
  columns,
  columnId,
  columnVisibility = {}
) => {
  const columnIndex = columns.findIndex(
    (column) => getColumnId(column) === columnId
  );
  if (columnIndex === -1) {
    return null;
  }

  return (
    columns.slice(columnIndex + 1).find((column) => {
      const id = getColumnId(column);
      // Grow columns absorb leftover space and must not be transfer targets.
      // Non-resizable columns (e.g. the final Group column) can still receive
      // transferred pixels so the dragged divider moves correctly.
      if (!id || column.grow) {
        return false;
      }
      return columnVisibility[id] !== false;
    }) ?? null
  );
};

/** Neutral size for grow-column drag accounting (layout ignores this value). */
export const GROW_COLUMN_ACCOUNTING_SIZE = 1000;
