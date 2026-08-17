#!/usr/bin/env bash
set -eu

target="$(pwd)"
mode=""
apply=0

usage() {
  cat <<'EOF'
Usage: uninstall.sh [--target PATH] [--mode 1|2] [--apply]

The default is interactive and dry-run. Mode 1 keeps .vibesocial data.
Mode 2 removes .vibesocial only after an explicit DELETE confirmation.
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --target) [ "$#" -ge 2 ] || { echo "--target requires a path" >&2; exit 2; }; target="$2"; shift 2 ;;
    --mode) [ "$#" -ge 2 ] || { echo "--mode requires 1 or 2" >&2; exit 2; }; mode="$2"; shift 2 ;;
    --apply) apply=1; shift ;;
    --help|-h) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

target="$(CDPATH= cd -- "$target" && pwd -P)"
[ -d "$target" ] || { echo "Target project root does not exist" >&2; exit 1; }

if [ -z "$mode" ]; then
  echo "[1] Remove both installed Skills and keep .vibesocial data"
  echo "[2] Remove both Skills and .vibesocial data (requires a second confirmation)"
  echo "[3] Cancel"
  printf "Choose 1, 2, or 3: "
  read -r mode
fi
[ "$mode" = "1" ] || [ "$mode" = "2" ] || { echo "Cancelled."; exit 0; }

skills_root="$target/.agents/skills"
case "$skills_root" in "$target"/*) ;; *) echo "Skill directory escaped target root" >&2; exit 1 ;; esac
for parent in "$target/.agents" "$skills_root"; do
  if [ -L "$parent" ]; then echo "Refusing to operate through a symlink Skill parent" >&2; exit 1; fi
done
targets=("$skills_root/vibe-social" "$skills_root/weibo-publish")
if [ "$mode" = "2" ]; then
  printf "Type DELETE to include .vibesocial data: "
  read -r confirm
  [ "$confirm" = "DELETE" ] || { echo "Cancelled."; exit 0; }
  targets+=("$target/.vibesocial")
fi

for path in "${targets[@]}"; do
  case "$path" in "$target"/*) ;; *) echo "Refusing target outside project root" >&2; exit 1 ;; esac
  if [ -L "$path" ]; then echo "Refusing to remove a symlink target" >&2; exit 1; fi
done

if [ "$mode" = "2" ]; then
  echo "这是完整删除模式。"
  echo ".vibesocial/ 中的个人数据将永久删除，包括可能存在的："
  echo "- 草稿"
  echo "- Writing Memory"
  echo "- 审核/状态记录"
  echo "- 系列状态"
  echo "- 发布记录"
  echo "删除后不会自动恢复。"
fi

if [ "$apply" -ne 1 ]; then
  echo "准备卸载 Vibe Social。"
  echo "将删除："
  echo "- .agents/skills/vibe-social/"
  echo "- .agents/skills/weibo-publish/"
  if [ "$mode" = "2" ]; then
    echo "- .vibesocial/"
  fi
  if [ "$mode" = "1" ]; then
    echo "将保留："
    echo "- .vibesocial/"
  fi
  echo "不会删除："
  echo "- .agents/"
  echo "- .agents/skills/"
  echo "- 其他 Skill"
  echo "- 项目源码"
  echo "- Git 历史"
  echo "DRY RUN：未修改任何文件。"
  echo "请使用 --apply 执行卸载。"
  exit 0
fi

echo "正在卸载 Vibe Social。"
for path in "${targets[@]}"; do
  if [ -e "$path" ]; then rm -rf -- "$path"; fi
done
echo "已删除："
echo "- .agents/skills/vibe-social/"
echo "- .agents/skills/weibo-publish/"
if [ "$mode" = "1" ]; then
  echo "已保留："
  echo "- .vibesocial/"
else
  echo "已删除："
  echo "- .vibesocial/"
fi
echo "卸载完成。"
