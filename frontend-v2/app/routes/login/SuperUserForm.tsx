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
import API from '~/lib/api';

export default function SuperUserForm() {
  const navigate = useNavigate();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [email, setEmail] = useState("");
  const [isLoading, setIsLoading] = useState(false);

  const setSuperuserExists = useAuthStore((s) => s.setSuperuserExists);
  const fetchVersion = useSettingsStore((s) => s.fetchVersion);
  const storedVersion = useSettingsStore((s) => s.version);

  useEffect(() => {
    // Fetch version info using the settings store (will skip if already loaded)
    fetchVersion();
  }, [fetchVersion]);

   const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true)
    try {
      const response = await API.createSuperUser({
        username,
        password,
        email,
      });
      if (response.superuser_exists) {
        setSuperuserExists(true);
      }
    } catch (err) {
      console.log(err);
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
          Welcome! Create your Super User Account to get started.
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

        <div className="space-y-2">
          <Label htmlFor="email">Email (optional)</Label>
          <Input
            id="email"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            autoFocus
          />
        </div>

        {/* Submit Button */}
        <Button type="submit" className="w-full" disabled={isLoading}>
          {isLoading ? <Spinner /> : "Create Account"}
        </Button>
      </form>
    </div>
  );
}
