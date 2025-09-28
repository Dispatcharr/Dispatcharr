# 🎬 Dispatcharr — Your Ultimate IPTV & Stream Management Companion
<p align="center">
  <img src="https://raw.githubusercontent.com/Dispatcharr/Dispatcharr/refs/heads/main/frontend/src/images/logo.png" height="200" alt="Dispatcharr Logo" />
</p>

---

## 📖 What is Dispatcharr?

Dispatcharr is an **open-source powerhouse** for managing IPTV streams and EPG data with elegance and control.\
Born from necessity and built with passion, it started as a personal project by **[OkinawaBoss](https://github.com/OkinawaBoss)** and evolved with contributions from legends like **[dekzter](https://github.com/dekzter)**, **[SergeantPanda](https://github.com/SergeantPanda)** and **Bucatini**.

> Think of Dispatcharr as the \*arr family’s IPTV cousin — simple, smart, and designed for streamers who want reliability and flexibility.

---

## 🧪 What’s New in Beta

Dispatcharr has officially entered **BETA**, bringing powerful new features and improvements across the board:

✨ **Proxy Streaming Engine** — Optimize bandwidth, reduce provider connections, and increase stream reliability\
📊 **Real-Time Stats Dashboard** — Live insights into stream health and client activity\
🧠 **EPG Auto-Match** — Match program data to channels automatically\
⚙️ **Streamlink + FFmpeg Support** — Flexible backend options for streaming and recording\
🎬 **VOD Management** — Full Video on Demand support with movies and TV series\
🛡️ **Automated Backups** — Schedule configuration snapshots and restore with confidence\
🧼 **UI & UX Enhancements** — Smoother, faster, more responsive interface\
🛁 **Output Compatibility** — HDHomeRun, M3U, and XMLTV EPG support for Plex, Jellyfin, and more

---

## ✨ Why You'll Love Dispatcharr

✅ **Full IPTV Control** — Import, organize, proxy, and monitor IPTV streams on your own terms\
✅ **Smart Playlist Handling** — M3U import, filtering, grouping, and failover support\
✅ **VOD Content Management** — Organize movies and TV series with metadata and streaming\
✅ **Reliable EPG Integration** — Match and manage TV guide data with ease\
✅ **Clean & Responsive Interface** — Modern design that gets out of your way\
✅ **Fully Self-Hosted** — Total control, zero reliance on third-party services

---


# Screenshots

![image](https://github.com/user-attachments/assets/bf7bc40a-d0e6-4f9f-8029-65b27d4205f9)

![image](https://github.com/user-attachments/assets/0835fd92-f7dc-4773-bdb7-7f88fd2f882d)

![image](https://github.com/user-attachments/assets/710f2bc4-250f-4161-a6ed-44d5082a30c4)

![image](https://github.com/user-attachments/assets/68a38d78-8f61-4c27-88f8-c52ba93d460d)

![image](https://github.com/user-attachments/assets/63686b9a-6faf-43a3-ae7a-c9e10a216b5b)




# 🚀 Get Started in Minutes

### 🐳 Quick Start with Docker (Recommended)

```bash
docker pull ghcr.io/dispatcharr/dispatcharr:latest
docker run -d \
  -p 9191:9191 \
  --name dispatcharr \
  -v dispatcharr_data:/data \
  ghcr.io/dispatcharr/dispatcharr:latest
```

> Customize ports and volumes to fit your setup.

---

### 🐳 Docker Compose Options

| Use Case                    | File                                                    | Description                                                                                            |
| --------------------------- | ------------------------------------------------------- | ------------------------------------------------------------------------------------------------------ |
| **All-in-One Deployment**   | [docker-compose.aio.yml](docker/docker-compose.aio.yml) | ⭐ Recommended! A simple, all-in-one solution — everything runs in a single container for quick setup.  |
| **Modular Deployment**      | [docker-compose.yml](docker/docker-compose.yml)         | Separate containers for Dispatcharr, Celery, and Postgres — perfect if you want more granular control. |
| **Development Environment** | [docker-compose.dev.yml](docker/docker-compose.dev.yml) | Developer-friendly setup with pre-configured ports and settings for contributing and testing.          |

---

### ⚒️ Building from Source (For the Adventurous)

> ⚠️ **Warning**: Not officially supported — but if you're here, you know what you're doing!

If you are running a Debian based operating system you can install using the `debian_install.sh` script. If you are on another operating system and come up with a script let us know! We would love to add it here!

---

## 🤝 Want to Contribute?

We welcome **PRs, issues, ideas, and suggestions**!\
Here’s how you can join the party:

- Follow our coding style and best practices.
- Be respectful, helpful, and open-minded.
- Respect the **CC BY-NC-SA license**.

> Whether it’s writing docs, squashing bugs, or building new features, your contribution matters! 🙌

---

## 📚 Roadmap & Documentation

- 📚  **Roadmap:** Coming soon!
- 📖 **Documentation:** [Dispatcharr Docs](https://dispatcharr.github.io/Dispatcharr-Docs/)

---

## ❤️ Shoutouts

A huge thank you to all the incredible open-source projects and libraries that power Dispatcharr. We stand on the shoulders of giants!

---

## ⚖️ License

> Dispatcharr is licensed under **CC BY-NC-SA 4.0**:

- **BY**: Give credit where credit’s due.
- **NC**: No commercial use.
- **SA**: Share alike if you remix.

For full license details, see [LICENSE](https://creativecommons.org/licenses/by-nc-sa/4.0/).

---

## ✉️ Connect With Us

Have a question? Want to suggest a feature? Just want to say hi?\
➡️ **[Open an issue](https://github.com/Dispatcharr/Dispatcharr/issues)** or reach out on [Discord]( https://discord.gg/Sp45V5BcxU).

---

### 🚀 *Happy Streaming! The Dispatcharr Team*
