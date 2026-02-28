import { redirect } from 'react-router';
import useAuthStore from '~/store/auth';
import storage from '~/lib/safe-storage';
import API from '~/lib/api';

/**
 * Check authentication status by validating stored token
 * @returns true if authenticated, false otherwise
 */
export async function checkAuth(): Promise<boolean> {
  // SSR safety check
  if (!storage.isBrowser()) {
    return false;
  }

  const authStore = useAuthStore.getState();
  const refreshToken = storage.getItem('refreshToken');

  // If no refresh token, not authenticated
  if (!refreshToken) {
    // Check if superuser exists for first-time setup
    try {
      const response = await API.fetchSuperUser();
      if (response && response.superuser_exists === false) {
        authStore.setSuperuserExists(false);
      }
    } catch (error) {
      console.error('Error checking superuser status:', error);
    }
    return false;
  }

  // Try to refresh/validate the token
  try {
    const loggedIn = await authStore.getRefreshToken();
    if (loggedIn) {
      // Initialize app data after successful auth
      authStore.initData();
      return true;
    }
  } catch (error) {
    console.error('Token validation failed:', error);
  }

  // Token invalid, clean up
  await authStore.logout();
  return false;
}

/**
 * Loader helper for protected routes
 * Redirects to /login if not authenticated
 */
export async function requireAuth() {
  const isAuthenticated = await checkAuth();

  if (!isAuthenticated) {
    throw redirect('/login');
  }

  return null;
}

/**
 * Loader helper for login route
 * Redirects to / if already authenticated
 */
export async function redirectIfAuthenticated() {
  const isAuthenticated = await checkAuth();

  if (isAuthenticated) {
    throw redirect('/');
  }

  return null;
}
