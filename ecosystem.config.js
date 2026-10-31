module.exports = {
  apps: [
    {
      name: "aversa-ai",
      script: "venv/bin/uvicorn",
      args: "main:app --host 127.0.0.1 --port 8000 --workers 2",
      cwd: "/home/ubuntu/apps/AversA-ai",
      interpreter: "none",
      env: {
        ENVIRONMENT: "production",
      },
    },
  ],
};

