# VS Code Launch & Build Templates

Visual Studio Code **launch and build templates** for developing **Dispatcharr** using Docker and Remote SSH.

These templates are intended for contributors who want a fast, repeatable, and debugger-friendly workflow using **VS Code**, **Docker**, and **Linux/WSL**.

---

## Table of Contents

- Purpose
- Supported Environments
- Getting Started
- Debugging Workflow
- Celery Worker
- Notes & Tips
- Contributing

---

## Purpose

This directory provides **preconfigured VS Code launch configurations**, including a **full-stack compound debug setup**.

The full-stack debug configuration starts:
- Python backend
- Node.js services
- Chrome for frontend debugging

The Celery worker is **not** started automatically and must be launched separately.

---

## Supported Environments

- Linux (Debian-based recommended)
- Windows Subsystem for Linux (WSL)
- Remote development over SSH

Typical workflow:
1. Fork the repository
2. Clone your fork onto a Linux or WSL host
3. Develop using VS Code Remote-SSH
4. Submit changes via Pull Requests

---

## Getting Started

### Prerequisites (Host Machine)

- Docker installed and running
- Git with repository access
- SSH access (key-based recommended)
- SSH server enabled

---

## VS Code Remote Setup

1. Clone the repository on the host:
   git clone <your-fork-url>

2. Copy the VS Code templates:
   cp -r .vscode_templates .vscode

3. Open Visual Studio Code

4. Connect using:
   Remote-SSH: Connect to Host

5. Ensure debugpy extension is installed on in VSCode after connecting to the remote host

---

## Debugging Workflow

1. Open the repository root folder in VS Code
2. Open the Run and Debug panel
3. Start Docker using one of the following (Note: first time takes a while to install dependencies):

Command line:
docker compose -f docker-compose.dev.vscode.yml up

OR via VS Code Task:
Tasks: Run Task -> Docker Compose Up

4. Select a debug configuration and click Run

---

## Celery Worker

- Starts internally in the docker container

---

## Notes & Tips

- Debugging runs on the remote host
- .vscode is excluded from version control
- SSH key authentication is recommended

---

## Contributing

1. Fork the repository
2. Create a feature branch
3. Commit your changes
4. Open a Pull Request
