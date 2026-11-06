#!/bin/sh
set -e

UPSTREAM_URL=https://kssinet.ghe.com/KyoshinSystemService/template.git

if git remote get-url upstream >/dev/null 2>&1; then
  MERGE_OPTS=""

  if [ "`git remote get-url upstream`" != "$UPSTREAM_URL" ]; then
    git remote set-url upstream "$UPSTREAM_URL"
    # push 先を無効な値にして、upstream への誤 push を防ぐ
    git remote set-url --push upstream DISABLE
    git remote -v
  fi
else
  MERGE_OPTS="--allow-unrelated-histories"

  CURRENT=`gh repo view -q ".owner.login + \"/\" + .name" --json name,owner`

  git remote add upstream "$UPSTREAM_URL"
  # push 先を無効な値にして、upstream への誤 push を防ぐ
  git remote set-url --push upstream DISABLE
  git remote -v

  gh repo set-default "$CURRENT"
  gh repo set-default --view
fi

git checkout -B chore/sync-upstream-template
git fetch upstream
git merge upstream/main $MERGE_OPTS
