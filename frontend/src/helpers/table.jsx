// frontend/src/helpers/table.js

export default {
  defaultProperties: {
    enableBottomToolbar: false,
    enableDensityToggle: false,
    enableFullScreenToggle: false,
    positionToolbarAlertBanner: 'none',
    enableRowNumbers: false,
    positionActionsColumn: 'last',
    enableColumnActions: false,
    enableColumnFilters: false,
    enableGlobalFilter: false,
    initialState: {
      density: 'compact',
    },
    mantineTableProps: {
      striped: true,
    },
    mantinePaperProps: {
      style: {
        '--mrt-selected-row-background-color': '#163632',
        '--mrt-base-background-color': '#27272A',
        '--mrt-striped-row-background-color': '#18181B',
      },
    },
    mantineSelectAllCheckboxProps: {
      size: 'xs',
    },
    mantineSelectCheckboxProps: {
      size: 'xs',
    },
    mantineTableBodyRowProps: ({ isDetailPanel, row }) => {
      return {
        style: {
          ...(isDetailPanel && {
            border: 'none',
          }),
          ...(isDetailPanel &&
            row.getIsSelected() && {
              backgroundColor: '#163632',
            }),
        },
      };
    },
    mantineTableBodyCellProps: {
      style: {
        // py: 0,
        paddingLeft: 10,
        paddingRight: 10,
        borderColor: '#444',
        // color: '#E0E0E0',
        fontSize: '0.85rem',
      },
    },
    mantineTableHeadCellProps: {
      style: {
        paddingLeft: 10,
        paddingRight: 10,
        paddingTop: 2,
        paddingBottom: 2,
        fontWeight: 'normal',
        // color: '#CFCFCF',
        backgroundColor: '#3F3F46',
        borderColor: '#444',
        // fontWeight: 600,
        // fontSize: '0.8rem',
      },
    },
  },
};
