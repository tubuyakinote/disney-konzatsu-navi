# ディズニー混雑点数ナビ（Streamlit）

## ローカル起動（開発者向け）
```bat
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
streamlit run streamlit_app.py
```

## ログイン（必須）
このアプリは **Secrets（合言葉のハッシュ）** が無いとログインできません。

### ローカル（Windows）
プロジェクト直下に `.streamlit\secrets.toml` を作成して、以下の形式で保存します：

```toml
APP_PASSPHRASE_HASH="（合言葉をsha256した16進文字列）"
```

### Streamlit Cloud
Deploy後、**App settings → Secrets** に同じ形式で貼り付けます。

## 点数表
`attractions_master.csv` を編集/差し替え可能です。
アプリ内の「点数表CSVの読み込み/書き出し」からダウンロード/アップロードできます。
