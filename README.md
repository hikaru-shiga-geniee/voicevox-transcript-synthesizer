# VOICEVOX Transcript Synthesizer

## 概要

このプロジェクトは、VOICEVOX Engine API を使用して、CSVファイルに記述された台本（発話者とテキスト）から音声を合成し、一つのWAVファイルに結合するPythonスクリプトです。

各発話セグメントの間には、話者が同じ場合と異なる場合で指定された長さの無音を挿入することができます。

## 機能

* **CSVからの台本読み込み:** `speaker`（話者名）と `text`（セリフ）列を含むCSVファイルを読み込みます。
* **VOICEVOX連携:** 指定されたVOICEVOX Engineに接続し、テキストと話者IDに基づいて音声を合成します。
* **話者マッピング:** CSVファイル内の話者名を、VOICEVOXの話者IDにマッピングする機能を提供します。
* **音声結合:** 合成された複数の音声セグメントを一つのWAVファイルに結合します。
* **無音挿入:**
    * 同じ話者が連続する場合の無音時間を指定できます。
    * 話者が変わる場合の無音時間を指定できます。
* **柔軟な設定:** VOICEVOX EngineのURL、APIタイムアウト、出力ファイルパス、無音時間などをコマンドライン引数で設定可能です。
* **エラーハンドリング:** APIリクエストの失敗やファイル読み込みエラーなどを適切に処理し、ログに出力します。

## 前提条件

* **Python:** 3.11 以上 (`pyproject.toml` に記載)
* **uv:** 
    * インストールされていない場合は、[uv 公式ドキュメント](https://astral.sh/docs/uv#installation) を参照してインストールしてください。(例: `pip install uv` または `curl -LsSf https://astral.sh/uv/install.sh | sh`)
* **VOICEVOX Engine:** スクリプトがアクセス可能な場所でVOICEVOX Engineが起動している必要があります。デフォルトでは `http://localhost:50021` に接続します。
    * [VOICEVOX 公式サイト](https://voicevox.hiroshiba.jp/)
* **VOICEVOXの話者ID:** 使用したい話者のVOICEVOXにおける話者IDを事前に確認しておく必要があります。VOICEVOX Engineの `/speakers` エンドポイントなどで確認できます。

## インストール (uv を使用)

1.  **リポジトリをクローン（またはファイルをダウンロード）します。**
    ```bash
    git clone <repository_url>
    cd <repository_directory>
    ```
2.  **仮想環境を作成して有効化します (推奨)。**
    `uv` を使用して仮想環境を作成し、アクティベートします。

    ```bash
    # 仮想環境を作成 (.venvディレクトリが作成される)
    uv venv
    # Windows (PowerShell)
    .\.venv\Scripts\Activate.ps1
    # Windows (cmd.exe)
    .\.venv\Scripts\activate.bat
    # macOS / Linux (bash/zsh)
    source .venv/bin/activate
    ```
    *(仮想環境から抜ける場合は `deactivate` コマンドを実行します)*

3.  **依存関係をインストールします。**
    `uv` を使って `pyproject.toml` に定義された依存関係をインストールします。

    ```bash
    uv sync
    ```


## 使い方

スクリプトはコマンドラインから実行します。仮想環境が有効化されていることを確認してください。

```bash
uv run main.py <csv_filepath_input> "<speaker_map_arg>" [オプション]
```

### 引数

* **`csv_filepath_input` (必須):**
    入力するCSVファイルのパス。
* **`speaker_map_arg` (必須):**
    CSV内の話者名とVOICEVOX話者IDのマッピング。
    * 形式: `"CSV話者名1:ID1 CSV話者名2:ID2 ..."` (全体をダブルクォートで囲むことを推奨)
    * 例: `"SPEAKER_00:3 SPEAKER_01:8"`
    * CSVファイルに登場する全ての話者名をマッピングする必要があります。IDは整数である必要があります。

### オプション

* **`--voicevox_url URL`:**
    VOICEVOX Engine API エンドポイントURL。
    (デフォルト: `http://localhost:50021`)
* **`--output_wav_path PATH`:**
    出力するWAVファイルのパス。指定しない場合、入力CSVファイルと同じディレクトリに `<入力CSV名>.wav` という名前で保存されます。
    (デフォルト: `None`)
* **`--timeout_query SECONDS`:**
    `audio_query` リクエストのタイムアウト時間 (秒)。
    (デフォルト: `10`)
* **`--timeout_synthesis SECONDS`:**
    `synthesis` リクエストのタイムアウト時間 (秒)。
    (デフォルト: `60`)
* **`--silence_duration_same_speaker SECONDS`:**
    話者が変わらない場合のセグメント間に挿入する無音時間 (秒)。
    (デフォルト: `0.125`)
* **`--silence_duration_diff_speaker SECONDS`:**
    話者が変わる場合のセグメント間に挿入する無音時間 (秒)。
    (デフォルト: `0.25`)

### 実行例

```bash
# test.csv を読み込み、話者マッピングを指定して output.wav に出力
uv run main.py test.csv "SPEAKER_00:3 SPEAKER_01:8" --output_wav_path output.wav

# VOICEVOX Engineが別のURLで動作している場合
uv run main.py dialogue.csv "キャラA:1 キャラB:14" --voicevox_url [http://192.168.1.100:50021](http://192.168.1.100:50021)

# 無音時間を調整する場合
uv run main.py script.csv "ずんだもん:3 四国めたん:2" --silence_duration_same_speaker 0.1 --silence_duration_diff_speaker 0.5
```

## 入力CSVフォーマット

入力するCSVファイルには、少なくとも `speaker` と `text` という名前の列が必要です。

* **`speaker`:** その行のセリフを話す話者の名前（`speaker_map_arg` で指定する名前と一致させる）。
* **`text`:** 合成するセリフのテキスト。

ファイルは `UTF-8` (BOMあり/なし両対応) エンコーディングである必要があります。

### 例 (`test.csv`)

```csv
"start","end","speaker","text"
"00:00:48","00:00:52","SPEAKER_00","そうですねそれぞれがつながってるんですよね"
"00:00:52","00:01:00","SPEAKER_01","ですよねこれらをつなぎ合わせて今のビジネス環境で特に大事なポイントっていうのを今日は深振りしていきたいなと"
"00:01:00","00:01:05","SPEAKER_00","まさに、特にやっぱり避けられないのが、その労働力不足っていう大きな課題。"
"00:01:05","00:01:15","SPEAKER_00","これに対して企業がどうやって戦略的にリソースを配分してテクノロジーを使って成長していくかそのあたりのヒントを探っていきましょう"
"00:01:15","00:01:16","SPEAKER_01","はい。"
"00:01:16","00:01:20","SPEAKER_00","きっとあなたの日々の業務とか将来の計画に役立つ何か発見があると思いますよ"
"00:01:20","00:01:34","SPEAKER_01","マズラのパーソルさんの労働市場の未来推計2035これ結構インパクトありましたね2035年に労働時間が1日あたり1775万時間不足する"
```

**注意:** このサンプルCSVの `start` と `end` 列は、現在のスクリプト (`main.py`) では使用されません。


