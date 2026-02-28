import { useEffect } from "react";
import { useNavigate } from "react-router";
import type { Route } from "./+types/login";
import useAuthStore from "~/store/auth";
import { checkAuth } from "~/lib/auth-helpers";
import LoginForm from "./login/LoginForm";
import SuperUserForm from "./login/SuperUserForm";

export function meta({}: Route.MetaArgs) {
  return [
    { title: "Login - Dispatcharr" },
    { name: "description", content: "Login to Dispatcharr" },
  ];
}

export default function Login() {
  const navigate = useNavigate();
  const superuserExists = useAuthStore((s) => s.superuserExists);

  useEffect(() => {
    // Check if already authenticated and redirect to home
    checkAuth().then((authenticated) => {
      if (authenticated) {
        navigate("/", { replace: true });
      }
    });
  }, [navigate]);

  return (
    <div className="flex min-h-screen items-center justify-center bg-background px-4">
      <div className="w-full max-w-md space-y-8">
        {superuserExists ? <LoginForm /> : <SuperUserForm />}
      </div>
    </div>
  );
}
