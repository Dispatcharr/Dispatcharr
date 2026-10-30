import { render, screen } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import M3UFilters from '../M3UFilters.jsx';

vi.mock('@mantine/core', () => ({
  useModalStackContext: () => null,
  Modal: ({ opened, children, title }) =>
    opened ? (
      <div>
        {title}
        {children}
      </div>
    ) : null,
}));
vi.mock('../M3URulesEditor.jsx', () => ({
  default: ({ accountId, accountType, streamFilters }) => (
    <div
      data-testid="rules-editor"
      data-account={accountId}
      data-account-type={accountType}
      data-stream-filters={String(streamFilters)}
    />
  ),
}));
vi.mock('../../ConfirmationDialog.jsx', () => ({ default: () => null }));

describe('M3UFilters', () => {
  it.each(['STD', 'XC'])(
    'passes the %s source type to presentation-only labels',
    (accountType) => {
      render(
        <M3UFilters
          isOpen
          playlist={{ id: 7, account_type: accountType }}
          onClose={vi.fn()}
        />
      );
      expect(screen.getByTestId('rules-editor')).toHaveAttribute(
        'data-account-type',
        accountType
      );
    }
  );
  it('uses the ordered-rule editor for the selected account', () => {
    render(<M3UFilters isOpen playlist={{ id: 7 }} onClose={vi.fn()} />);
    expect(screen.getByText('Stream filters')).toBeInTheDocument();
    expect(screen.getByTestId('rules-editor')).toHaveAttribute(
      'data-account',
      '7'
    );
    expect(screen.getByTestId('rules-editor')).toHaveAttribute(
      'data-stream-filters',
      'true'
    );
  });
  it('does not load filters while closed', () => {
    render(
      <M3UFilters isOpen={false} playlist={{ id: 7 }} onClose={vi.fn()} />
    );
    expect(screen.queryByTestId('rules-editor')).not.toBeInTheDocument();
  });
  it('does not load filters before the account is created', () => {
    render(<M3UFilters isOpen playlist={{}} onClose={vi.fn()} />);
    expect(screen.queryByTestId('rules-editor')).not.toBeInTheDocument();
  });
});
