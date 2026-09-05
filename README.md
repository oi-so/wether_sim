# Local Weather Simulation

地形付き3Dアニメーションと雲の2D動画6種類を追加しました。既存結果へ `./scripts/animate_weather_case.sh output/old` を実行すると不足分だけ生成します。操作と気象量の定義は [3D・雲動画マニュアル](docs/animation_3d.md) を参照してください。

2026-09-05更新：`run-case` の既定設定は `config/msm_guided.yaml`（MSMナッジング、親領域60分出力）です。精度は検証中です。従来条件との比較は `--template config/case_20260901.yaml` を指定できます。完走結果と速度の確認は [追加評価](docs/evaluation_20260905_followup.md) を参照してください。

指定した地点周辺の局地気象を、WRF（Weather Research and Forecasting Model）を用いて高解像度で再現・予測するためのプロジェクトです。

主な解析対象は、指定地点を中心とした**半径約20 km**です。対象範囲だけを単独で計算するのではなく、外側の大気の影響を取り込むため、複数の計算領域をネスティングします。

## 目標

Version 1では、次の一連の処理を完成させることを目標とします。

1. 過去を含む任意の日時・地点を指定する
2. 気象データからWRFの初期値・境界値を作成する
3. 9 km → 3 km → 1 kmの3段ネストで計算する
4. 中心半径約20 kmの結果を解析する
5. アメダス観測値と比較する
6. 本校の観測装置による実測値と比較する
7. MAE・Bias・RMSEなどで精度を評価する
8. 気温・風などを地図上に可視化する
9. 時間変化をアニメーションとして出力する

最初は**過去の1事例を正常に再現し、観測値との比較とアニメーション生成まで完走すること**を優先します。

---

## 計算領域

Version 1では以下を基本構成とします。

| Domain | 水平解像度 | 範囲の目安 | 役割 |
|---|---:|---:|---|
| d01 | 9 km | 約900 × 900 km | 大規模な気圧配置・風 |
| d02 | 3 km | 約300 × 300 km | 地方規模の気象 |
| d03 | 1 km | 約100 × 100 km | 局地気象 |

d03の中心から半径約20 kmを主解析範囲とします。

将来的には必要に応じて約333 mのd04を追加します。

---

## 入力データ

### 大気初期値・境界値

WRFには上空を含む3次元の大気状態が必要なため、アメダスだけではシミュレーションを初期化できません。

Version 1では、MSM等の数値予報・解析データを大気初期値・境界値として利用する方針です。

### アメダス

アメダスは主に、

- シミュレーション結果の検証
- MSM等との比較
- 将来的な観測データ同化

に利用します。

### 本校観測装置

本校で取得している観測値も独立した検証データとして利用します。

特に、

\[
\Delta T_{obs}
=
T_{school}
-
T_{AMeDAS}
\]

と、WRFから得られる同地点間の気温差を比較し、本校と周辺アメダスの気温差をモデルが再現できるか調べます。

---

## 日時指定

過去を含む任意日時を指定できる設計とします。

過去事例では、実際のアメダス・本校観測値が存在するため、シミュレーション結果を定量的に評価できます。

Version 1では過去再現（hindcast）を優先し、将来的に最新データを用いた将来予測へ拡張します。

時刻はタイムゾーンを明示し、基本表示を `Asia/Tokyo`、内部処理を必要に応じてUTCとします。

---

## 主な出力

Version 1では主に以下を扱います。

- 2 m気温
- 2 m相対湿度
- 10 m風
- 風向・風速
- 地表面気圧
- 降水量
- 地表面温度

必要に応じて、雲量、顕熱・潜熱フラックス、境界層高度、放射関連量なども解析します。

---

## 精度評価

観測値を \(O_i\)、予測値を \(P_i\) として、最低限以下を計算します。

### Bias

\[
Bias = \frac{1}{N}\sum_{i=1}^{N}(P_i-O_i)
\]

### MAE

\[
MAE = \frac{1}{N}\sum_{i=1}^{N}|P_i-O_i|
\]

### RMSE

\[
RMSE =
\sqrt{
\frac{1}{N}
\sum_{i=1}^{N}
(P_i-O_i)^2
}
\]

---

## 可視化

数値だけでなく、以下の形式で結果を可視化します。

- 気温分布図
- 湿度分布図
- 風速分布図
- 風ベクトル
- 降水分布
- 観測値とWRFの時系列グラフ
- 時間変化アニメーション

アニメーションでは、

- 再生・一時停止
- フレーム移動
- 時刻表示
- カラーバー
- 再生速度変更

などを扱える構成を目指します。

MP4またはGIFへの書き出しにも対応します。

---

## 想定環境

主な開発・実行環境：

- macOS
- Apple Silicon
- MacBook Air M3
- 16 GB RAM
- Python
- uv
- WRF
- WPS

Python側では主に以下の利用を想定しています。

- NumPy
- xarray
- pandas
- matplotlib
- SciPy
- netCDF4
- PyYAML
- ffmpeg

実際の依存関係は実装時に `pyproject.toml` で管理します。

## 日付と時刻を指定して実行する

実行場所は、このREADMEがあるプロジェクト直下です。

```bash
cd /Users/oiso/programs/wether_sim
./scripts/run_weather_case.sh "2026-09-01 15:00" "2026-09-01 21:00"
```

開始・終了はJSTとして解釈されます。ISO 8601のUTCオフセットを明示することもできます。

```bash
./scripts/run_weather_case.sh \
  "2026-09-01T15:00:00+09:00" \
  "2026-09-01T21:00:00+09:00"
```

このコマンドは、指定期間とspin-upを覆う入力時刻を計算し、次を自動実行します。

1. 京大RISHからMSM気圧面・地表面GRIB2を取得
2. NOAA GFSからNoah LSM用の地表面・4層土壌場を必要レコードだけ取得
3. 過去期間では府中アメダス10分値を気象庁から取得
4. WPS地理データがなければ公式高解像度必須データを取得
5. `geogrid`、MSM/GFSの`ungrib`、`metgrid`
6. `real.exe`、9 km → 3 km → 1 kmの`wrf.exe`
7. 指定した解析期間の気温分布図とMP4/GIF

macOS上のPythonが配布サーバーの証明書チェーンを検証できない場合は、証明書検証を無効化せず、システム信頼ストアを使用するmacOS標準の `curl` へ自動的に切り替えます。

MSMとGFSの初期時刻は別々に選択します。MSMは3時間間隔、GFSは00・06・12・18 UTCの6時間間隔です。たとえば計算開始が21 UTCなら、MSMは21 UTCサイクル、GFSは直前の18 UTCサイクルの3時間予報を自動使用します。

MSM入力は3時間間隔なので、内部の計算期間は指定期間の外側の3時間境界まで自動的に広げられます。解析・アニメーションは指定した開始・終了時刻だけを使用します。

既定ではspin-up 6時間、4 MPIプロセスです。変更する場合は次のように指定します。

```bash
./scripts/run_weather_case.sh \
  "2026-09-01 15:00" "2026-09-01 21:00" \
  --spinup-hours 9 \
  --processes 2
```

データだけを先に取得する場合は `--download-only` を付けます。

```bash
./scripts/run_weather_case.sh \
  "2026-09-01 15:00" "2026-09-01 21:00" \
  --download-only
```

学校・予測地点は（35.69247912845154, 139.41296806119965）、計算領域は9 km → 3 km → 1 kmの3段ネストです。入力データはローカルにキャッシュされ、同じ日時を再実行した場合は再ダウンロードしません。

GFSの土壌場は、空間切り出し後のGRIB2ではなく、NOAA全球ファイルから必要な12レコードをHTTP Rangeでそのまま取得します。土壌場の欠測ビットマップを保ったままWPSへ渡すためです。また、MSMの地上1.5 m気温・相対湿度は、WPSが受け取れる2 m地表場としてGRIBメタデータを正規化します。`metgrid` 完了後には、最内側領域の陸上地中温度、地表気温、地表相対湿度を自動検査し、0 Kや欠測などの壊れた初期値なら長時間のWRF計算を始めず停止します。通信が一時的に切れた場合は、GFSレコード単位で最大4回再試行します。

完了後の成果物は、開始・終了日時から生成される `output/case_YYYYMMDDTHHMM_YYYYMMDDTHHMM/` に出力されます。

- `analysis/temperature_animation.mp4`: d03の2 m気温
- `analysis/wind_animation.mp4`: 10 m風速と風ベクトル
- `analysis/humidity_animation.mp4`: 2 m相対湿度
- `analysis/precipitation_animation.mp4`: 出力間隔ごとの降水量
- `analysis/pressure_animation.mp4`: 地表気圧
- `analysis/skin_temperature_animation.mp4`: 地表面温度
- `analysis/temperature_map.png`: 気温分布図
- `observations/amedas_fuchu.csv`: 過去期間で取得できた府中アメダス10分値

過去日時ならhindcast、配信済みの予報時刻ならforecastとして実行できます。ただし、指定時刻のMSM/GFSが配信元に存在しない場合は、曖昧な代替データを使用せずエラーで停止します。本校観測・アメダスとの定量比較は、対応する観測CSVがあるケースに対して従来の `weather-sim analyze` を使用します。

---

## ディレクトリ構成案

```text
weather-simulation/
├── AGENTS.md
├── README.md
├── MEMORY_PROJECT.md
├── docs/
│   └── local_weather_simulation_spec.md
├── pyproject.toml
├── config/
│   └── default.yaml
├── data/
│   ├── meteorological/
│   │   └── msm/
│   ├── geographic/
│   └── observations/
│       ├── amedas/
│       └── school/
├── src/
│   └── weather_sim/
│       ├── config/
│       ├── data/
│       ├── observations/
│       ├── preprocess/
│       ├── simulation/
│       ├── analysis/
│       └── visualization/
├── scripts/
├── output/
└── tests/
```

---

## 開発ロードマップ

- [ ] WRF/WPSをMac上で実行できるようにする
- [ ] 過去1事例を9 km単独で再現する
- [ ] 3 kmネストを追加する
- [ ] 1 kmネストを追加する
- [x] Pythonからwrfoutを読み込む
- [x] 気温・風を可視化する
- [x] アニメーションを生成する
- [x] 共通形式へ変換したアメダスデータを読み込む
- [x] アメダスとWRFを比較する
- [x] 共通形式へ変換した本校観測データを読み込む
- [x] 本校観測値とWRFを比較する
- [x] MAE・Bias・RMSEを自動計算する
- [ ] 複数の過去事例で評価する

### 将来

- [ ] OBSGRID / observational nudging / WRFDA等による観測データ同化
- [ ] 約333 mへの高解像度化
- [ ] リアルタイム・将来予測
- [x] 日時指定、入力データ取得、WPS/WRF、アニメーションの自動化
- [ ] GUI / Web UI

---

## ドキュメント

- `docs/local_weather_simulation_spec.md`  
  詳細な仕様書。

- `AGENTS.md`  
  AIエージェント向けの開発ルール・設計方針。

- `MEMORY_PROJECT.md`  
  現在の進捗、確定した設計判断、実験結果、既知の問題を引き継ぐためのプロジェクトメモ。

---

## 現在利用できる実装

Python側のVersion 1基盤として、次を実装済みです。

- YAML設定の型付き読み込み・検証、JST/UTC変換、spin-up開始時刻の計算
- 9 km → 3 km → 1 km領域の `namelist.wps` / `namelist.input` 生成
- 共通形式のアメダス・学校観測CSV読み込み、品質・欠測値処理、温度単位変換
- `wrfout` の2 m気温・10 m風・積算/時間降水量の読み込み
- 観測地点に対する最近傍WRF格子の抽出
- Bias・MAE・RMSE・有効サンプル数Nの計算
- 気温分布＋風ベクトル、観測/WRF時系列、MP4/GIFアニメーションの出力
- 上記をまとめて実行するCLI
- 任意日時からMSM・GFS・アメダス・WPS地理データを準備し、WRFとアニメーションまで実行する `run-case` CLI
- ケース単位で不足動画の生成、共通観測CSV作成、実観測評価、安全な段階別削除を行うCLI

実行方法、共通観測形式、容量整理の判断基準は [操作マニュアル](docs/operation_manual.md) を参照してください。

WRF/WPS本体、大容量地理データ、初期値・境界値データはGit管理しません。大気場には京都大学生存圏研究所のMSM、MSMに含まれないNoah LSM用の土壌温度・土壌水分4層にはNOAA GFSを使用します。取得済みファイルは `data/` 以下へキャッシュします。

## セットアップ

Python 3.12以上と `uv` を使用します。MP4を出力する場合は `ffmpeg` も必要です。

```bash
uv sync --extra dev
uv run weather-sim validate-config config/default.yaml
uv run pytest
```

既定設定の領域幅は、WRFの3:1ネスト制約 `(e_we - 1) % 3 == 0` を満たすため、それぞれ約891 km、297 km、99 kmです。

## WPS / WRF namelist生成

```bash
uv run weather-sim generate-namelists config/default.yaml \
  --output-dir output/example/namelists \
  --geog-data-path /absolute/path/to/WPS_GEOG
```

生成する物理スキームは、実行開始用の暫定値です。対象事例、WRFバージョン、入力データが確定した時点で妥当性を再評価してください。特にMSMの `interval_seconds` とVtableは、入力データの実際の時間間隔・配信形式に合わせる必要があります。

## 観測CSV形式

入力は1観測1行のlong形式です。例は `tests/data/observations_example.csv` にあります。

必須列：

```text
timestamp,station_id,latitude,longitude,elevation_m,variable,value,unit
```

任意列は `quality`（`valid` / `missing` / `invalid`）と `source` です。タイムゾーンのない時刻は設定の `time.timezone` として解釈し、内部でUTCに変換します。気温の `unit` は `degC`、`°C`、`C`、`celsius`、`K`、`kelvin` に対応します。元データは変更せず、別ファイルとしてこの形式へ変換してください。

## 既存wrfoutの解析

```bash
uv run weather-sim analyze config/default.yaml \
  --wrfout /absolute/path/to/wrfout_d03_... \
  --observations tests/data/observations_example.csv \
  --station-id school \
  --reference-station-id amedas_example \
  --output-dir output/example/analysis \
  --animation
```

出力は `metrics.json`、`comparison.csv`、`temperature_timeseries.png`、`temperature_map.png` と、指定した場合の `temperature_animation.mp4` または `.gif` です。`--reference-station-id` を指定すると、学校－基準観測点の気温差についても比較CSV、指標JSON、時系列図を出力します。spin-up期間は設定の解析開始時刻より前として比較から除外します。

現段階の地点対応は最近傍格子です。WRF格子と観測点の標高差・土地利用差は自動補正しないため、結果解釈時に必ず確認してください。

## 実観測データによる多変数評価

学校と府中アメダスの実観測について、気温・相対湿度・風速・地表気圧・降水を一括評価できます。

```bash
uv run weather-sim evaluate-observations \
  config/case_20260901.yaml \
  --wrfout "output/case_20260901/wrf_run/wrfout_d03_2026-09-01_00:00:00" \
  --observations data/observations/case_20260901.csv \
  --output-dir output/case_20260901/analysis/verification
```

WRFの各出力時刻に最も近い実観測を1件対応させ、Bias・MAE・RMSE・有効件数Nを計算します。結果は `verification_summary.csv` / `.json`、対応値は `pairs/`、JST時系列グラフは `plots/` に出力します。観測点標高とWRF格子標高も集計表へ残します。

## 地図付きアニメーション

`--animation` で生成する全動画には、国土地理院の標準地図、学校地点、日本語ラベル、JST時刻を表示します。地理院タイルは `data/geographic/gsi_tiles/` にキャッシュされ、動画内に「背景地図：国土地理院」と出典を表示します。

---

## 2026-09-01実データ事例

- 予測地点・学校: `35.69247912845154, 139.41296806119965`
- 解析期間: 2026-09-01 15:00–21:00 JST
- spin-up: 6時間（初回実行確認用）
- 検証アメダス: 府中（block 1133、地点コード44116）
- d03の学校最近傍格子: `(y=49, x=49)`、地形標高約81.1 m
- WRF v4.8.0 / WPS v4.7.0: Apple Silicon arm64でビルド・起動確認済み
- `geogrid`、MSM/GFSの `ungrib`、両者を併合した `metgrid`: 完了
- `real.exe`: 3領域の `wrfinput` と `wrfbdy_d01` の生成成功を確認済み

本校のCP932・1分値WSNログと、気象庁の府中10分値は `scripts/prepare_case_20260901.py` で共通long形式へ変換できます。任意日時の自動ワークフローは追加済みですが、ユーザー指定によりこの変更時点では新ワークフロー自体のテスト実行は行っていません。
