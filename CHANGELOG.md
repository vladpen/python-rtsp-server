## [Unreleased] - 2022-04-08:

Storage:
* Fixed critical error
* Improved files rotation

## [Unreleased] - 2022-01-08:

Default "storage_command" in global config.

### Removed
- "storage_connect_to_camera" flag in "cameras" section in the [configuration file](https://github.com/vladpen/python-rtsp-server/blob/main/config-exapmle.py).

### Added
- "storage_command" in "storage" section in the configuration file.

### Attention!
- You must have at least one of "storage_command" filled in "storage" or "cameras" section if "storage_enable" flag is on.
- "storage_command" format was changed to f-string like syntax. The default value now is "ffmpeg -i {url} -c copy {filename}.mkv".
Please change your private configuration file "_config.py".

## [Unreleased] - 2021-12-22

Initial commit.
