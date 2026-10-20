#!/usr/bin/env bash
# 扫描全仓库已跟踪文件里残留的 git 合并冲突标记（#217）。
# 起因：#214 分支的合并提交把 <<<<<<< HEAD / ======= / >>>>>>> origin/main
# 留在了 CHANGELOG.md，CI 却是绿的。CI 的 node job 调用本脚本，本地也可直接跑：
#   bash scripts/check-conflict-markers.sh
#
# 匹配规则（只看行首）：
#   <<<<<<< / >>>>>>> / |||||||（diff3 的 base 段）：正好 7 个，后面是空格或行尾；
#   =======：正好 7 个、后面直接是行尾（允许 \r），不吃 "======= 标题" 这类内容。
# git grep 只扫已跟踪文件（不碰 node_modules、未跟踪文件），-I 跳过二进制。
# 排除项：目前没有。确有合法命中时，只用 ':(exclude)具体文件' 排除，并在下面注明原因。
set -eu

cd "$(git rev-parse --show-toplevel)"

cr=$(printf '\r')
pattern="^(<{7}|>{7}|\|{7})( |\$)|^={7}${cr}?\$"

# 合法命中的排除项（每项写明原因），例如：
#   ':(exclude)tests/fixtures/some-merge-sample.txt'  # 测试数据，故意带标记
excludes=()

set +e
hits=$(git -c core.quotePath=false grep -nIE -e "$pattern" -- . "${excludes[@]+"${excludes[@]}"}")
rc=$?
set -e

if [ "$rc" -eq 1 ]; then
  echo "No merge conflict markers found."
  exit 0
fi
if [ "$rc" -ne 0 ]; then
  echo "git grep failed (exit $rc)" >&2
  exit 2
fi

count=0
while IFS= read -r hit; do
  file=${hit%%:*}
  rest=${hit#*:}
  line=${rest%%:*}
  text=${rest#*:}
  text=${text%"$cr"}
  echo "${file}:${line}: ${text}"
  if [ -n "${GITHUB_ACTIONS:-}" ]; then
    echo "::error file=${file},line=${line}::Leftover merge conflict marker: ${text}"
  fi
  count=$((count + 1))
done <<HITS
$hits
HITS

echo "Found ${count} leftover merge conflict marker line(s)." >&2
exit 1
