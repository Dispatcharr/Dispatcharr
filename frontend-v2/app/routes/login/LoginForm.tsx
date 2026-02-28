import { useState, useEffect } from "react";
import { Link, useNavigate } from "react-router";
import { Button } from "~/components/ui/button";
import { Input } from "~/components/ui/input";
import { Spinner } from "~/components/ui/spinner";
import useAuthStore from "~/store/auth";
import useSettingsStore from "~/store/settings";
import { Label } from "~/components/ui/label";
import { Checkbox } from "~/components/ui/checkbox";
import toast from "~/lib/toast";

export default function LoginForm() {
  const navigate = useNavigate();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [rememberMe, setRememberMe] = useState(false);
  const [savePassword, setSavePassword] = useState(false);
  const [isLoading, setIsLoading] = useState(false);

  const login = useAuthStore((s) => s.login);
  const logout = useAuthStore((s) => s.logout);
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const initData = useAuthStore((s) => s.initData);
  const user = useAuthStore((s) => s.user);
  const fetchVersion = useSettingsStore((s) => s.fetchVersion);
  const storedVersion = useSettingsStore((s) => s.version);

  useEffect(() => {
    if (isAuthenticated) {
      navigate("/");
    }
  }, [isAuthenticated, user, navigate]);

  useEffect(() => {
    // Load saved username if it exists
    const savedUsername = localStorage.getItem(
      "dispatcharr_remembered_username",
    );
    const savedPassword = localStorage.getItem("dispatcharr_saved_password");

    if (savedUsername) {
      setUsername(savedUsername);
      setRememberMe(true);

      if (savedPassword) {
        try {
          const decrypted = decodePassword(savedPassword);
          if (decrypted) {
            setPassword(decrypted);
            setSavePassword(true);
          }
        } catch {
          // If decoding fails, just skip
        }
      }
    }
  }, []);

  useEffect(() => {
    // Fetch version info using the settings store (will skip if already loaded)
    fetchVersion();
  }, [fetchVersion]);

  // Simple base64 encoding/decoding for localStorage
  // Note: This is obfuscation, not encryption. Use browser's password manager for real security.
  const encodePassword = (password: string) => {
    try {
      return btoa(password);
    } catch (error) {
      console.error("Encoding error:", error);
      return null;
    }
  };

  const decodePassword = (encoded) => {
    try {
      return atob(encoded);
    } catch (error) {
      console.error("Decoding error:", error);
      return "";
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);

    try {
      await login({ username, password });

      // Save username if remember me is checked
      if (rememberMe) {
        localStorage.setItem("dispatcharr_remembered_username", username);

        // Save password if save password is checked
        if (savePassword) {
          const encoded = encodePassword(password);
          if (encoded) {
            localStorage.setItem("dispatcharr_saved_password", encoded);
          }
        } else {
          localStorage.removeItem("dispatcharr_saved_password");
        }
      } else {
        localStorage.removeItem("dispatcharr_remembered_username");
        localStorage.removeItem("dispatcharr_saved_password");
      }

      await initData();
      // Navigation will happen automatically via the useEffect or route protection
    } catch (e: any) {
      console.log(`Failed to login: ${e}`);
      if (e?.message === "Unauthorized") {
        toast.show({
          title: "Web UI Access Denied",
          message:
            "This account is a Streamer account and cannot log into the web UI. " +
            "Your M3U and stream URLs still work. Contact an admin to upgrade your account level.",
          color: "red",
          autoClose: 10000,
        });
      }
      await logout();
      setIsLoading(false);
    }
  };

  return (
    <div className="rounded-lg border border-border bg-card p-8 shadow-sm">
      <div className="text-center pb-4">
        <img
          src="/logo.png"
          alt="Dispatcharr"
          className="mx-auto h-16 w-16 mb-4"
        />
        <h1 className="text-3xl font-bold tracking-tight">Dispatcharr</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          Welcome back! Please log in to continue
        </p>
      </div>

      <form onSubmit={handleSubmit} className="space-y-6">
        <div className="space-y-2">
          <Label htmlFor="username">Username</Label>
          <Input
            id="username"
            type="text"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            required
            autoFocus
          />
        </div>

        <div className="space-y-2">
          <Label htmlFor="password">Password</Label>
          <Input
            id="password"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            autoFocus
          />
        </div>

        {/* Remember Me & Remember Password */}
        <div className="space-y-3">
          <div className="flex justify-between items-center">
            <Label htmlFor="remember-me">
              <Checkbox
                id="remember-me"
                checked={rememberMe}
                onCheckedChange={setRememberMe}
              />
              Remember me
            </Label>

            {rememberMe && (
              <div>
                <Label htmlFor="save-password">
                  <Checkbox
                    id="save-password"
                    checked={savePassword}
                    onCheckedChange={setSavePassword}
                  />
                  Save password
                </Label>
              </div>
            )}

            <div className="text-right">
              <Link
                to="/forgot-password"
                className="text-sm text-primary hover:underline"
              >
                Forgot password?
              </Link>
            </div>
          </div>
        </div>

        {/* Submit Button */}
        <Button type="submit" className="w-full" disabled={isLoading}>
          {isLoading ? <Spinner /> : "Login"}
        </Button>
      </form>
    </div>
  );
}
