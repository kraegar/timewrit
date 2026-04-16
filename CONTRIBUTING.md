# Contributing to TimeWrit

First off, thank you for considering contributing to TimeWrit! It's people like you that make open source such a great community.

## How Can I Contribute?

### 1. Reporting Bugs & Suggesting Enhancements
This section guides you through submitting a bug report or enhancement request.
*   Ensure the bug/idea hasn't already been reported by searching the issue tracker.
*   Use a clear and descriptive title.
*   Provide a step-by-step description of how to reproduce the bug or how the enhancement would work.
*   If suggesting a UI change, mockups or sketches are highly appreciated.

### 2. Contributing Code
If you want to contribute code to fix a bug or add a new feature:
*   **Fork the repo:** Fork the repository on GitHub and create your branch from `main`.
*   **Follow the existing style:** Write clean Vanilla JS and stick to tailwind classes in the frontend. Ensure Django python code follows PEP8 guidelines.
*   **Test your code:** Run the existing unit tests (`python manage.py test`) and ensure you haven't broken anything. If adding a large feature, try to include a basic test case.
*   **Submit a Pull Request:** Make sure your PR description clearly explains what you've done and any visual changes.

### 3. Running the Test Suite
Before submitting any PR, please run:
```bash
python manage.py test
```
All tests must pass for a PR to be merged.

### 4. Code Review Process
The core maintainers will review your pull request. We might suggest some changes or improvements before merging. We use a positive, constructive feedback loop—don't be discouraged if we ask for a few tweaks!

Welcome to the team!
