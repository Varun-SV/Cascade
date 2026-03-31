# Tool Reference

## Discovery

- `list_directory`
- `find_files`
- `glob_files`
- `grep_search`
- `semantic_code_search`
- `read_file`
- `read_files`

## Editing

- `write_file`
- `edit_file`
- `search_replace`
- `apply_patch`
- `diff_preview`
- `move_path`
- `delete_path`

## Shell and Process

- `run_command`
- `start_process`
- `read_process_output`
- `write_process_input`
- `stop_process`

## Git

- `git_status`
- `git_diff`
- `git_log`
- `git_show`
- `git_add`
- `git_commit`
- `git_checkout`

## Safety Notes

- Mutating tools support dry-run previews for the approval flow.
- The tool registry caches idempotent reads and invalidates the cache after mutating actions.
- File mutations are snapshotted for rollback when a task artifact directory is available.
