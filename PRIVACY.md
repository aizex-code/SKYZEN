# Privacy and local data

## Project intent

Skyzen is intended to work locally and does not intentionally collect or transmit
users' project content, source media, personal files, or usage analytics through its
Python application code in this snapshot.

## Local storage

Depending on usage, Skyzen may write:
- project metadata and editor state under `project_manager/projects/`;
- settings in `project_manager/settings.json`;
- deleted projects in `project_manager/trash/`;
- a local crash log named `skyzen-crash.log`;
- caches, thumbnails, and media proxies used by the editor.

Project media is generally referenced by file path; it is not necessarily copied into
the project directory. These paths may reveal usernames or folder names, so inspect
project files and logs before sharing them publicly.

## Network and third-party software

The application includes links that open creator YouTube pages when clicked. That
action opens an external website in the user's browser. Python, Qt, FFmpeg, codecs,
operating-system services, and any third-party components may have their own behavior
and privacy policies. This project does not make a blanket guarantee about those
components or network activity outside its own code.

## How to verify

Contributors should review changes for telemetry, analytics, remote upload, or network
requests before merging them. Any future feature that intentionally sends user data
should be documented clearly and should require informed user choice.
