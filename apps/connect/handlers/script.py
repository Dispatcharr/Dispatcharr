# connect/handlers/script.py
import os
import subprocess
from .base import IntegrationHandler

class ScriptHandler(IntegrationHandler):
    def execute(self):
        script_path = self.integration.config.get("path")

        # Build environment variables from payload (prefixed for clarity)
        env = os.environ.copy()
        for key, value in (self.payload or {}).items():
            # Convert keys to upper snake case and prefix
            env_key = f"DISPATCHARR_{str(key).upper()}"
            env[env_key] = str(value) if value is not None else ""

        result = subprocess.run(
            [script_path],
            capture_output=True,
            text=True,
            env=env,
        )
        return {
            "exit_code": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "success": result.returncode == 0,
        }
