name: ニュースを更新

on:
  schedule:
    - cron: "0 21 * * *"   # 毎日 日本時間の朝6:00(UTC 21:00)
  workflow_dispatch:        # 手動実行ボタン用

permissions:
  contents: write

jobs:
  update:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: python fetch_news.py
      - name: 変更があればコミット
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add docs/index.html
          git diff --cached --quiet || git commit -m "ニュースを更新"
          git push
