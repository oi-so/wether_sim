# Local Weather Simulation

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
- [ ] データ取得から解析までの自動化
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

WRF/WPS本体、大容量地理データ、初期値・境界値データはこのリポジトリには含めません。MSMの正式な取得・WPS変換方法と学校観測装置の元形式は未確定なので、現段階では既に前処理された `met_em*` / `wrfout*` と共通観測CSVを入力にします。

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

---

## 現在の状態

現在は**仕様策定段階**です。

次の作業は、Mac上でWRF/WPSを動かすための環境構築と、Version 1で利用する初期値・境界値データの具体的な取得方法を確定することです。
