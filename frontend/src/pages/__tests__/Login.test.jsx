import { describe, it, expect, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import Login from '../Login';
import useAuthStore from '../../store/auth';

vi.mock('../../store/auth');
vi.mock('../../components/forms/LoginForm', () => ({
  default: () => <div data-testid="login-form">LoginForm</div>,
}));
vi.mock('../../components/forms/SuperuserForm', () => ({
  default: () => <div data-testid="superuser-form">SuperuserForm</div>,
}));
vi.mock('../../assets/logo.png', () => ({ default: 'logo.png' }));
vi.mock('@mantine/core', () => ({
  Center: ({ children }) => <div>{children}</div>,
  Image: ({ src, alt }) => <img src={src} alt={alt} />,
  Loader: (props) => <div role="progressbar" {...props} />,
  Paper: ({ children }) => <div>{children}</div>,
  Stack: ({ children }) => <div>{children}</div>,
}));

describe('Login', () => {
  it('renders a loading state while setup status is unknown', () => {
    useAuthStore.mockReturnValue(null);

    render(<Login />);

    expect(
      screen.getByRole('progressbar', { name: 'Loading login' })
    ).toBeInTheDocument();
    expect(screen.getByAltText('Dispatcharr Logo')).toBeInTheDocument();
    expect(screen.queryByTestId('login-form')).not.toBeInTheDocument();
    expect(screen.queryByTestId('superuser-form')).not.toBeInTheDocument();
  });

  it('renders SuperuserForm when superuser does not exist', async () => {
    useAuthStore.mockReturnValue(false);

    render(<Login />);

    await waitFor(() => {
      expect(screen.getByTestId('superuser-form')).toBeInTheDocument();
    });
    expect(screen.queryByTestId('login-form')).not.toBeInTheDocument();
  });

  it('renders LoginForm when superuser exists', () => {
    useAuthStore.mockReturnValue(true);

    render(<Login />);

    expect(screen.getByTestId('login-form')).toBeInTheDocument();
    expect(screen.queryByTestId('superuser-form')).not.toBeInTheDocument();
  });
});
