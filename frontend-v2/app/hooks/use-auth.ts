import { useEffect } from "react";
import { useNavigate } from "react-router";
import { auth } from "~/lib/api";

/**
 * Hook to protect routes - redirects to login if not authenticated
 */
export function useAuth() {
  const navigate = useNavigate();

  useEffect(() => {
    if (!auth.isAuthenticated()) {
      navigate("/login", { replace: true });
    }
  }, [navigate]);

  return {
    isAuthenticated: auth.isAuthenticated(),
    token: auth.getToken(),
  };
}

/**
 * Hook to handle logout
 */
export function useLogout() {
  const navigate = useNavigate();

  const logout = () => {
    auth.removeToken();
    navigate("/login", { replace: true });
  };

  return logout;
}
