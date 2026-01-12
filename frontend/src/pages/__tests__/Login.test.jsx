import { describe, it, expect, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import Login from '../Login';
import useAuthStore from '../../store/auth';

vi.mock('../../store/auth');
vi.mock('../../components/forms/LoginForm', () => ({
  default: () => <div data-testid="login-form">LoginForm</div>
}));
vi.mock('../../components/forms/SuperuserForm', () => ({
  default: () => <div data-testid="superuser-form">SuperuserForm</div>
}));
vi.mock('@mantine/core', () => ({
  Text: ({ children }) => <div>{children}</div>,
}));

describe('Login', () => {
  it('renders SuperuserForm when superuser does not exist', async () => {
    useAuthStore.mockReturnValue(false);

    render(<Login/>);

    await waitFor(() => {
      expect(screen.getByTestId('superuser-form')).toBeInTheDocument();
    });
    expect(screen.queryByTestId('login-form')).not.toBeInTheDocument();
  });

  it('renders LoginForm when superuser exists', () => {
    useAuthStore.mockReturnValue(true);

    render(<Login/>);

    expect(screen.getByTestId('login-form')).toBeInTheDocument();
    expect(screen.queryByTestId('superuser-form')).not.toBeInTheDocument();
  });
});
