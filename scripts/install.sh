#!/usr/bin/env bash
set -eu

target="$(pwd)"
apply=0
update=0

usage() {
  cat <<'EOF'
Usage: install.sh [--target PATH] [--apply] [--update]

The default is a dry run. --apply copies only the two Skill directories.
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --target)
      [ "$#" -ge 2 ] || { echo "--target requires a path" >&2; exit 2; }
      target="$2"
      shift 2
      ;;
    --apply) apply=1; shift ;;
    --update) update=1; shift ;;
    --help|-h) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

script_dir="${0%/*}"
[ "$script_dir" = "$0" ] && script_dir="."
script_dir="$(CDPATH= cd -- "$script_dir" && pwd -P)"
repo_root="$(CDPATH= cd -- "$script_dir/.." && pwd -P)"
[ -d "$repo_root/.agents/skills/vibe-social" ] || { echo "Missing vibe-social source Skill" >&2; exit 1; }
[ -d "$repo_root/.agents/skills/weibo-publish" ] || { echo "Missing weibo-publish source Skill" >&2; exit 1; }
[ -d "$target" ] || { echo "Target project root does not exist: target omitted from output" >&2; exit 1; }
target="$(CDPATH= cd -- "$target" && pwd -P)"

skills_root="$target/.agents/skills"
case "$skills_root" in
  "$target"/*) ;;
  *) echo "Skill destination escaped the target root" >&2; exit 1 ;;
esac
for parent in "$target/.agents" "$skills_root"; do
  if [ -L "$parent" ]; then
    echo "Refusing to operate through a symlink Skill parent" >&2
    exit 1
  fi
done

mode="install"
[ "$update" -eq 1 ] && mode="safe update"
echo "Vibe Social Agent $mode"
echo "Target: project root (personal paths are not persisted by this script)"
echo "The following Skill directories will be copied: vibe-social, weibo-publish"
echo "Preserved: .vibesocial, source files, Git history, and unrelated Skills"
if [ "$apply" -ne 1 ]; then
  echo "DRY RUN: no files changed. Re-run with --apply to continue."
  exit 0
fi

mkdir -p "$skills_root"
for skill_name in vibe-social weibo-publish; do
  destination="$skills_root/$skill_name"
  if [ -L "$destination" ]; then
    echo "Refusing to replace a symlink Skill destination" >&2
    exit 1
  fi
  case "$destination" in "$target"/*) ;; *) echo "Skill destination escaped target root" >&2; exit 1 ;; esac
  if [ -e "$destination" ]; then rm -rf -- "$destination"; fi
  mkdir -p "$destination"
done

copy_skill_without_python_cache() {
  source="$1"
  destination="$2"
  while IFS= read -r -d '' relative; do
    relative="${relative#./}"
    destination_file="$destination/$relative"
    mkdir -p "$(dirname "$destination_file")"
    cp -p "$source/$relative" "$destination_file"
  done < <(
    cd "$source"
    find . -type d -name '__pycache__' -prune -o \
      -type f ! -name '*.pyc' ! -name '*.pyo' -print0
  )
}

copy_skill_without_python_cache "$repo_root/.agents/skills/vibe-social" "$skills_root/vibe-social"
copy_skill_without_python_cache "$repo_root/.agents/skills/weibo-publish" "$skills_root/weibo-publish"
echo "Installed/updated both Skills. Existing .vibesocial data was not touched."
