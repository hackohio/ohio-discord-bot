# Contributing to the OHI/O Discord Bot

Thank you for contributing. This guide covers setting up a local development copy and submitting changes.

## Before you start

You will need:

- A GitHub account. To create one, click **Sign up** in the top-right corner of any GitHub page.
- [Git](https://git-scm.com/downloads) installed on your computer.
- [Python](https://www.python.org/downloads/) 3.12.
- [uv](https://docs.astral.sh/uv/getting-started/installation/) installed.
- Basic command-line knowledge. Ask another tech committee member if you need help getting started.

## 1. Fork the repository

Use the **Fork** button near the top-right of this repository’s GitHub page and follow the prompts. A fork is a copy under your own account, so you can work without changing the production repository directly.

## 2. Clone your fork

Get your fork’s URL from its green **Code** button, then clone it into a convenient local directory:

```bash
git clone <URL>
```

Replace `<URL>` with the copied URL.

Alternatively, install [GitHub Desktop](https://github.com/apps/desktop), choose **File → Clone Repository…**, open the **URL** tab, paste your fork’s URL, choose a local directory, and click **Clone**.

For more cloning options, see [GitHub’s cloning documentation](https://docs.github.com/en/repositories/creating-and-managing-repositories/cloning-a-repository).

## 3. Get `config.ini`

Download `config.ini` from the tech committee’s SharedFolder in Google Drive and place it in the root of your local repository. If you do not have access, use the request link in the `#tech-general` channel description in the OHI/O Discord server.

> **Important:** `config.ini` contains sensitive information. Do not share it outside the organization or commit it to Git.

## 4. Install dependencies

From the repository root:

```bash
uv sync
```

This creates a project virtual environment and installs the exact dependency
versions recorded in `uv.lock`. To check that the lock file is current without
updating it, use:

```bash
uv sync --locked
```

## 5. Run the bot

Start the bot and webhook server:

```bash
uv run python start.py
```

After the bot logs in, try its slash commands in the test Discord server. Press `Ctrl+C` to stop it.

## Submit a change

Make and test your changes, commit them to your fork, push the branch, then open a pull request against this repository.

## Further reading

- [An Intro to Git and GitHub for Beginners](https://product.hubspot.com/blog/git-and-github-tutorial-for-beginners)
- [git — the simple guide](https://rogerdudler.github.io/git-guide/)
- [GitHub Docs](https://docs.github.com/en)
- [Pro Git](https://git-scm.com/book/en/v2)
- [Python documentation](https://docs.python.org/3/)
- [discord.py documentation](https://discordpy.readthedocs.io/en/stable/)
