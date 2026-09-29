# Contributing to SmartRath

Thanks for helping HexaBytes improve SmartRath for SIH26124.

## Before opening a pull request

1. Check existing issues and pull requests to avoid duplicate work.
2. Keep changes focused, and explain any user-visible behavior changes.
3. Never commit credentials, WhatsApp session data, local databases, real
   camera footage, or personally identifiable information.
4. Run the relevant checks from the repository root:

   ```powershell
   python -m unittest test_dedup -v
   npm --prefix frontend ci
   npm --prefix frontend run lint
   npm --prefix frontend run build
   ```

5. Include or update tests for changed behavior and update the README when
   launch steps or configuration change.

## Pull requests

Use a clear title and include:

- The problem being addressed and the approach taken.
- How the change was tested.
- Any known limitations or required setup.

Do not include bus footage, license plate samples, credentials, WhatsApp
account data, or production municipal records in issues, pull requests, or
test fixtures.
