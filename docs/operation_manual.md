# 局地気象シミュレーション 操作マニュアル

## 1. 基本操作

すべての操作はターミナルでプロジェクトへ移動してから行います。

```bash
cd /Users/oiso/programs/wether_sim
```

各シミュレーションは `output/case_開始日時_終了日時/` というケースフォルダにまとまります。本書の例では次を使用します。

```text
output/case_20260904T1200_20260904T2000
```

パスは実際に処理したケースへ置き換えてください。

## 2. 実際にシミュレーションする

開始・終了時刻はJSTとして指定されます。MSM、GFS、アメダス、地形データを対象日時に合わせて準備し、WPS、WRF、動画生成まで実行します。

```bash
./scripts/run_weather_case.sh \
  "2026-09-04 12:00" \
  "2026-09-04 20:00" \
  --spinup-hours 6 \
  --processes 4
```

主な結果は次の場所に作成されます。

- WRF局地出力: `output/case_.../wrf_run/wrfout_d03_...`
- 動画・図: `output/case_.../analysis/`
- ケース設定: `output/case_.../case.json`
- 取得済みアメダス: `output/case_.../observations/amedas_fuchu.csv`

動画を後で作る場合は `--no-animation` を付けます。

## 3. 共通観測形式を作る

### 推奨する自動変換

学校の生ログを `data/observations/school/` に置き、次を実行します。

```bash
./scripts/prepare_observations.sh \
  output/case_20260904T1200_20260904T2000
```

このコマンドは次を行います。

1. `case.json` から解析開始・終了時刻と学校座標を読む。
2. `data/observations/school/*.csv` のCP932形式WSNログを読む。
3. ケース内にアメダスCSVがなければ、同じ日付の府中アメダスを取得する。
4. 解析期間内の観測だけを1観測1行のlong形式へ統合する。
5. `output/case_.../observations/observations.csv` に保存する。

学校の標高が分かる場合は指定できます。

```bash
./scripts/prepare_observations.sh \
  output/case_20260904T1200_20260904T2000 \
  --school-elevation-m 80
```

アメダスを取得せず、学校データだけを変換する場合は `--no-download-amedas` を付けます。対象期間の実観測が1行もない場合は、空のCSVを作らずエラーで停止します。

### 共通CSVの列

```text
timestamp,station_id,latitude,longitude,elevation_m,variable,value,unit,quality,source
```

各列の意味は次の通りです。

| 列 | 内容 | 例 |
|---|---|---|
| `timestamp` | 観測日時。タイムゾーン付きISO 8601を推奨 | `2026-09-04T03:00:00+00:00` |
| `station_id` | 観測地点ID | `school`, `amedas_fuchu` |
| `latitude` / `longitude` | 観測地点の緯度・経度 | `35.692479...`, `139.412968...` |
| `elevation_m` | 標高m。不明なら空欄可 | `80` |
| `variable` | 変数名 | `temperature`, `wind_speed` |
| `value` | 観測値 | `30.2` |
| `unit` | 単位 | `degC`, `%`, `m/s`, `hPa`, `mm/h` |
| `quality` | 品質 | `valid`, `missing`, `invalid` |
| `source` | データ出所 | `school_wsn`, `jma_amedas` |

学校WSNからは気温、相対湿度、風向、風速、気圧、降水強度、積算降水量を変換します。元の観測ファイルは変更しません。

## 4. 未作成の動画を作る

```bash
./scripts/animate_weather_case.sh \
  output/case_20260904T1200_20260904T2000
```

`analysis/` に存在しない動画だけを作成し、既存の正常な動画は上書きしません。対象は気温、風向・風速、湿度、降水、地表気圧、地表面温度です。WRF出力に変数がない動画は作成されません。地図は国土地理院標準地図、表示ラベルは日本語、時刻はJSTです。

既存動画も作り直す場合だけ `--force` を付けます。

```bash
./scripts/animate_weather_case.sh \
  output/case_20260904T1200_20260904T2000 \
  --force
```

## 5. 実観測データで評価する

先に共通観測CSVを作り、その後評価します。

```bash
./scripts/prepare_observations.sh \
  output/case_20260904T1200_20260904T2000

./scripts/evaluate_weather_case.sh \
  output/case_20260904T1200_20260904T2000
```

評価期間は `case.json` の解析期間を自動使用し、spin-up期間は含めません。既定ではWRF出力間隔の半分以内で最も近い観測を対応させます。

結果は `output/case_.../analysis/verification/` に保存されます。

- `verification_summary.csv` / `.json`: Bias、MAE、RMSE、有効件数N、格子距離、標高
- `pairs/`: WRF値、観測値、誤差、対応時刻
- `plots/`: 日本語ラベル・JSTの時系列比較図

別の共通観測CSVを使う場合は次のように指定します。

```bash
./scripts/evaluate_weather_case.sh \
  output/case_20260904T1200_20260904T2000 \
  --observations /絶対パス/observations.csv
```

## 6. 不要データを安全に削除する

削除コマンドは、既定では候補と容量を表示するだけのdry-runです。最初は必ず `--execute` なしで確認してください。

### 再シミュレーションは不要だが、再評価・動画再生成は残す

```bash
./scripts/cleanup_weather_case.sh \
  output/case_20260904T1200_20260904T2000 \
  --discard-resimulation
```

表示内容が正しければ、実際に削除します。

```bash
./scripts/cleanup_weather_case.sh \
  output/case_20260904T1200_20260904T2000 \
  --discard-resimulation \
  --execute
```

この段階では、ケース内の `ungrib_msm/`、`ungrib_gfs/`、`wps/`、`wrfinput*`、`wrfbdy*`、再生成可能な巨大lookupファイル等を削除します。d03の `wrfout`、共通観測CSV、評価結果、動画は残るため、再評価と動画再生成は可能です。

### 再評価も動画再生成も不要で、完成結果だけ残す

まず候補を表示します。

```bash
./scripts/cleanup_weather_case.sh \
  output/case_20260904T1200_20260904T2000 \
  --discard-resimulation \
  --discard-reevaluation
```

問題なければ `--execute` を追加します。この操作ではd03の巨大な `wrfout` も削除します。少なくとも動画または評価結果が存在しない限り、安全のため削除を拒否します。

### 削除判断表

| 今後行いたいこと | 指定してよいオプション |
|---|---|
| WRFを同じ中間データから再実行したい | どちらも指定しない |
| 評価または動画を作り直したい | `--discard-resimulation` のみ |
| 動画・評価結果を見るだけでよい | 両方を指定可能 |

このコマンドは共有データである `data/meteorological/`、`data/geographic/WPS_GEOG/`、学校の元観測、WRF/WPS本体を削除しません。これらは別ケースでも再利用するため、ケース整理と同時に消さない設計です。

## 7. コマンド一覧を確認する

```bash
uv run weather-sim --help
uv run weather-sim animate-case --help
uv run weather-sim prepare-observations --help
uv run weather-sim evaluate-case --help
uv run weather-sim cleanup-case --help
```
# 2026-09-05追加：改善実験の再計算

通常の日時指定だけではFDDAは有効になりません。改善実験にはテンプレートを明示してください。既存の `wrf_run` があるケースは上書きせずエラーになるので、新しいケース名を指定します。

```bash
./scripts/run_weather_case.sh "2026-09-04 12:00" "2026-09-04 20:00" \
  --template config/case_20260904_fdda_efficient.yaml \
  --case-name case_20260904T1200_20260904T2000_fdda_efficient \
  --spinup-hours 6 --processes 4 --no-animation
```

開始時の `grid_nudging=True` 表示と、ケース内 `case.json` の `configuration.wrf.grid_nudging` で設定を確認できます。親領域の出力間隔は `analysis.parent_output_interval_minutes` で指定し、省略すると従来どおり全領域同じ間隔です。積分は解析終了まで、境界入力の準備はその後の3時間境界まで行います。

完走後は従来の `prepare_observations.sh` と `evaluate_weather_case.sh` に新しいケースフォルダを渡してください。既存の同じ日時の観測CSVを使う場合は `weather-sim evaluate-case CASE --observations CSV` でも評価できます。評価・原因分析の詳細は `docs/evaluation_20260905.md` にあります。
