# How to contribute to LeKiwi Diagnostics + Teleoperation

This repository is a community fork of Hugging Face LeRobot. LeKiwi dashboard,
teleoperation, iOS, deployment, and documentation changes belong here. General
LeRobot fixes should normally be proposed upstream at
https://github.com/huggingface/lerobot first.

Everyone is welcome to contribute, and we value everybody's contribution. Code is not the only way to help the community. Answering questions, helping others, reaching out, and improving the documentation are immensely valuable.

Whichever way you choose to contribute, please be mindful to respect our [code of conduct](https://github.com/huggingface/lerobot/blob/main/CODE_OF_CONDUCT.md) and our [AI policy](https://github.com/huggingface/lerobot/blob/main/AI_POLICY.md).

## Ways to Contribute

You can contribute in many ways:

- **Fixing issues:** Resolve bugs or improve existing code.
- **New features:** Develop new features.
- **Extend:** Implement new models/policies, robots, or simulation environments and upload datasets to the Hugging Face Hub.
- **Documentation:** Improve examples, guides, and docstrings.
- **Feedback:** Submit tickets related to bugs or desired new features.

For questions specific to this fork, open a GitHub discussion or issue. The
upstream [LeRobot Discord](https://discord.gg/q8Dzzpym3f) remains useful for
general hardware and framework questions.

## Development Setup

To contribute code, you need to set up a development environment.

### 1. Fork and Clone

Fork the repository on GitHub, then clone your fork:

```bash
git clone https://github.com/<your-handle>/lekiwi-lerobot.git
cd lekiwi-lerobot
git remote add upstream https://github.com/huggingface/lerobot.git
```

### 2. Environment Installation

Install with `uv sync --locked --extra test --extra dev --extra lekiwi`. The
upstream [installation guide](https://huggingface.co/docs/lerobot/installation)
contains platform-specific prerequisites.

## Running Tests & Quality Checks

### Code Style (Pre-commit)

Install `pre-commit` hooks to run checks automatically before you commit:

```bash
pre-commit install
```

To run checks manually on all files:

```bash
pre-commit run --all-files
```

### Running Tests

We use `pytest`. First, ensure you have test artifacts by installing **git-lfs**:

```bash
git lfs install
git lfs pull
```

Run the full suite (this may require extras installed):

```bash
uv run pytest -sv ./tests
```

Or run a specific test file during development:

```bash
uv run pytest -q tests/robots/test_lekiwi_diagnostics.py tests/robots/test_lekiwi_live_diagnostics.py
```

## Submitting Issues & Pull Requests

Use the templates for required fields and examples.

- **Issues:** Follow this repository's bug template and include whether the robot was lifted, the leader/follower topology, motor IDs, voltage source, and a redacted state snapshot.
- **Pull requests:** Branch from this repository's `main`, keep upstream attribution, run focused tests and pre-commit, and describe any physical validation separately from simulated tests.

Never include calibration files, Access tokens, tunnel credentials, Wi-Fi
details, private hostnames, or USB serial numbers from someone else's robot.
Tests that can move hardware must be opt-in and clearly labeled.

Maintainers review changes on a best-effort basis. No response-time commitment is implied.

Thank you for contributing to LeRobot!
