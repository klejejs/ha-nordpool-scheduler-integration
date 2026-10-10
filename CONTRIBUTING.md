# Contribution guidelines

Contributing to this project should be as easy and transparent as possible, whether it's:

- Reporting a bug
- Discussing the current state of the code
- Submitting a fix
- Proposing new features

## GitHub is used for everything

GitHub is used to host code, to track issues and feature requests, as well as accept pull requests.

Pull requests are the best way to propose changes to the codebase.

1. Fork the repo and create your branch from `main`.
2. If you've changed something, update the documentation. A user-facing change also updates the info dialog in the card's [`src/info.ts`](https://github.com/klejejs/ha-nordpool-scheduler-card/blob/main/src/info.ts), which explains every feature.
3. Make sure your code lints (using `scripts/lint`).
4. Test your contribution (using `scripts/test`).
5. Issue that pull request!

## Any contributions you make will be under the MIT Software License

In short, when you submit code changes, your submissions are understood to be under the same [MIT License](http://choosealicense.com/licenses/mit/) that covers the project. Feel free to contact the maintainers if that's a concern.

## Report bugs using GitHub's [issues](../../issues)

GitHub issues are used to track public bugs.
Report a bug by [opening a new issue](../../issues/new/choose); it's that easy!

## Write bug reports with detail, background, and sample code

**Great Bug Reports** tend to have:

- A quick summary and/or background
- Steps to reproduce
  - Be specific!
  - Give sample code if you can.
- What you expected would happen
- What actually happens
- Notes (possibly including why you think this might be happening, or stuff you tried that didn't work)

People *love* thorough bug reports. I'm not even kidding.

## Use a Consistent Coding Style

Use [Ruff](https://docs.astral.sh/ruff/) to format and lint the code. `scripts/lint` runs both.

## Test your code modification

Run `scripts/test` to lint and run the test suite.

The repository comes with a development container, easy to launch if you use Visual Studio Code. Inside it, `scripts/develop` starts a standalone Home Assistant instance on port 8123, configured with the included [`configuration.yaml`](./config/configuration.yaml) file.

## License

By contributing, you agree that your contributions will be licensed under its MIT License.
