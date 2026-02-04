# AI 索引板块大改更新计划：CLAP 升级至 larger_clap_general

## 一、目标与范围

- **模型**：从 `clap-htsat-unfused` 切换为 `larger_clap_general`（Xenova ONNX，Hugging Face 镜像）。
- **模型结构**：由「单 model.onnx + dummy 另一路」改为 **audio_model.onnx + text_model.onnx + model.onnx** 三文件，全精度。
- **配套文件**：所有 tokenizer/预处理器/配置的 .json 与 .txt 均使用 larger_clap_general 仓库版本。
- **下载方式**：继续在软件内在线下载，源为 HF 镜像。

**涉及模块**：模型下载、CLAP 加载与推理、AI 检索页（索引/搜索/打标）、设置页模型路径与下载入口。

---

## 二、模型与文件来源

- **仓库根目录**（`tree/main`）：  
  https://hf-mirror.com/Xenova/larger_clap_general/tree/main  
  用于下载：config.json、merges.txt、preprocessor_config.json、quantize_config.json、special_tokens_map.json、tokenizer.json、tokenizer_config.json、vocab.json 等。

- **ONNX 子目录**（`tree/main/onnx`）：  
  https://hf-mirror.com/Xenova/larger_clap_general/tree/main/onnx  
  用于下载：**全精度** ONNX（不选 fp16/quantized）  
  - `audio_model.onnx`（约 282 MB）  
  - `text_model.onnx`（约 502 MB）  
  - ~~`model.onnx`~~ **不下载**（推理只需 audio_model + text_model，见 Xenova README）。

用户要求：**仅下载 audio_model.onnx、text_model.onnx 全精度**；不下载 model.onnx。

---

## 三、更新计划（分步）

### 1. 模型下载（ModelDownloadWorker + 配置）

| 项目 | 当前 | 变更后 |
|------|------|--------|
| 仓库/Base URL | `hf-mirror.com/Xenova/clap-htsat-unfused/resolve/main` | `hf-mirror.com/Xenova/larger_clap_general/resolve/main` |
| 本地目录 | `data_dir/models/clap-htsat-unfused` | `data_dir/models/larger-clap-general`（或保持语义一致命名） |
| ONNX 文件 | 仅 `onnx/model.onnx` | `onnx/audio_model.onnx`、`onnx/text_model.onnx`、`onnx/model.onnx`（全精度） |
| 根目录文件 | tokenizer.json, vocab.json, config.json, preprocessor_config.json, special_tokens_map.json | 与 larger_clap_general 根目录一致：config.json, merges.txt, preprocessor_config.json, quantize_config.json, special_tokens_map.json, tokenizer.json, tokenizer_config.json, vocab.json（按需决定是否下载 README/.gitattributes） |

**实现要点**：

- 在 `ui/utils/workers.py` 的 `ModelDownloadWorker` 中：
  - 将 `BASE_URL` 改为 `https://hf-mirror.com/Xenova/larger_clap_general/resolve/main`。
  - `FILES_TO_DOWNLOAD` 改为两段：
    - 根目录：`config.json`, `merges.txt`, `preprocessor_config.json`, `special_tokens_map.json`, `tokenizer.json`, `tokenizer_config.json`, `vocab.json`（若需量化配置再加 `quantize_config.json`）。
    - ONNX：`onnx/audio_model.onnx`, `onnx/text_model.onnx`, `onnx/model.onnx`。
  - 下载逻辑保持「按列表顺序、逐文件请求」；大文件（三个 onnx）可保留或增强进度展示（如按文件名区分「模型主体 / 音频编码器 / 文本编码器」）。
- 设置页 / 运行时用于「CLAP 模型目录」的路径，统一改为新目录（例如 `get_data_dir() / "models" / "larger-clap-general"`），与下载目标目录一致。

---

### 2. CLAP 服务加载与推理（clap_service.py）

| 项目 | 当前 | 变更后 |
|------|------|--------|
| 加载 | 单 session：`model_dir/onnx/model.onnx` | 三个 session：`session_audio`（audio_model.onnx）、`session_text`（text_model.onnx）；`model.onnx` 是否加载、用于何处在确认 ONNX 结构后再定（若为融合/兼容用则保留加载与调用策略） |
| 文本 embedding | 同一 session + dummy 音频 input_features | **仅** `session_text`：input_ids、attention_mask（及 tokenizer 产出），无 dummy 音频 |
| 音频 embedding | 同一 session + dummy 文本 input_ids/attention_mask | **仅** `session_audio`：input_features（mel 等），无 dummy 文本 |
| 预处理 | 当前 mel 参数（48k, 10s, n_fft=1024, hop=480, n_mels=64） | 需与 larger_clap_general 的 preprocessor_config.json / 文档对齐（采样率、长度、mel 参数等），必要时调整 `_preprocess_audio` 与静态预处理函数 |
| 输入/输出名 | 按当前 model.onnx 的 input/output 名 | 按 audio_model.onnx、text_model.onnx 的实际 input/output 名（如 audio_embeds、text_embeds）做兼容 |

**实现要点**：

- `initialize()`：
  - 加载 `onnx/audio_model.onnx` → `self.session_audio`。
  - 加载 `onnx/text_model.onnx` → `self.session_text`。
  - 若后续确认 `model.onnx` 必须参与（例如联合头或兼容接口），再增加 `self.session` 及调用处。
- `get_text_embedding(text)`：
  - 仅用 `session_text` + tokenizer；构建输入时只传文本相关 tensor，不再传 `input_features`。
  - 输出从 `session_text` 的 output 中取 text embedding（维度与现有一致或更新为 512 等，以 ONNX 为准）。
- `get_audio_embedding(audio_path)` / `_run_audio_inference(input_features)`：
  - 仅用 `session_audio`；只传音频相关 input（如 input_features），不再传 input_ids/attention_mask。
  - 输出从 `session_audio` 的 output 中取 audio embedding。
- 若 larger_clap_general 的音频前端与当前不同（例如采样率、窗长、mel 数），需同步改：
  - `clap_service.py` 内 `SAMPLE_RATE`、`N_FFT`、`HOP_LENGTH`、`N_MELS`、`MAX_LENGTH_SECONDS` 等；
  - 多进程/静态预处理 `_preprocess_audio_static` 的默认参数，与 preprocessor_config 一致。
- Tokenizer：继续使用下载的 `tokenizer.json`（及 vocab 等）；若 larger 使用 `tokenizer_config.json` 或 merges，按新格式加载，保证与 text_model.onnx 输入一致。

---

### 3. AI 检索页（ai_search_page_qt.py）

| 项目 | 当前 | 变更后 |
|------|------|--------|
| 模型目录 | `data_dir/models/clap-htsat-unfused` | `data_dir/models/larger-clap-general`（与下载、clap_service 一致） |
| 引擎初始化 | `CLAPInferenceService(model_dir)`，内部单 model.onnx | 无 API 变更；内部已改为双/三 session，对外仍为「按路径初始化」 |
| 索引/搜索/打标 | 调用 `engine.get_audio_embedding` / `engine.get_text_embedding` | 调用方式不变；实现改为走 session_audio / session_text |

**实现要点**：

- 将「CLAP 模型目录」的默认路径改为新目录（例如 `get_data_dir() / "models" / "larger-clap-general"`）。
- 索引建立、语义搜索、打标流程仍通过现有 `engine` 接口；只要 `CLAPInferenceService` 在新目录下正确加载 audio/text 两个 session 并实现上述 get_* 方法即可，页面逻辑可不变。
- 若新模型 embedding 维度或归一化方式变化，且影响索引存储格式，需在索引构建/加载处做版本或维度兼容（见下「索引兼容」）。

---

### 4. 设置页（settings_page_qt.py）

| 项目 | 当前 | 变更后 |
|------|------|--------|
| CLAP 模型目录显示/校验 | `clap-htsat-unfused`、检查 `onnx/model.onnx` 等 | 改为 `larger-clap-general`，检查 `onnx/audio_model.onnx`、`onnx/text_model.onnx`、`onnx/model.onnx` 及必要 .json/.txt 是否存在 |
| 下载按钮/逻辑 | 调用 `ModelDownloadWorker(save_dir)`，save_dir 为旧目录 | save_dir 改为新目录；下载内容为上述新文件列表 |
| 删除/清空模型 | 删除旧目录 | 删除新目录 |

**实现要点**：

- 所有「CLAP 模型路径」「模型是否存在」的判断，改为基于新目录和新文件列表（三个 onnx + 必要 json/txt）。
- 下载进度与完成提示可保留，仅更新「正在下载：xxx」中的文件名（如区分三个 onnx）。

---

### 5. 索引兼容与重建

| 项目 | 说明 |
|------|------|
| 旧索引 | 当前索引是 clap-htsat-unfused 的 audio embedding 向量；与 larger_clap_general 的向量空间不一致，**不能混用**。 |
| 新索引 | 使用 larger_clap_general 的 session_audio 产出；维度以新 ONNX 为准（如 512）。 |
| 策略 | 升级后**必须全量重建索引**；可选：在版本或元数据中标记「clap 版本」或「embed 维度」，便于以后再次换模型时提示用户重建。 |

建议：在索引元数据（如 manifest 或现有 meta）中增加一项「clap_model」或「embed_version」，值为 `larger_clap_general`；加载时若与当前模型不一致则提示「索引由旧模型生成，请重新建立索引」。

---

### 6. 测试与回归要点

- **下载**：从 HF 镜像能完整拉取三个 onnx + 所有 .json/.txt；目录结构与 clap_service 预期一致。
- **加载**：`CLAPInferenceService(model_dir).initialize()` 成功，无单 model 回退逻辑。
- **文本**：`get_text_embedding("Footsteps")` 等返回形状与维度符合 text_model.onnx 输出。
- **音频**：`get_audio_embedding(audio_path)` 与 `_run_audio_inference(mel)` 返回形状与维度符合 audio_model.onnx 输出。
- **检索**：建立索引 → 语义搜索（文本/相似音频）结果合理。
- **打标**：打标流程中文本 embedding 与音频 embedding 的相似度计算与阈值行为正常。
- **设置页**：新目录下「已安装」状态正确；下载/删除流程正常。

---

## 四、文件与代码修改清单（汇总）

| 文件/模块 | 修改内容摘要 |
|-----------|--------------|
| `ui/utils/workers.py` | `ModelDownloadWorker`：BASE_URL 改为 larger_clap_general；FILES_TO_DOWNLOAD 改为根目录 json/txt + onnx 下 audio_model.onnx、text_model.onnx、model.onnx；进度提示可区分三个 onnx。 |
| `application/ai/clap_service.py` | 加载 audio_model.onnx → session_audio、text_model.onnx → session_text；get_text_embedding 仅用 session_text；get_audio_embedding / _run_audio_inference 仅用 session_audio；预处理与 preprocessor_config 对齐；输入/输出名按新 ONNX 适配。 |
| `ui/pages/ai_search_page_qt.py` | 模型目录改为 larger-clap-general；其余调用保持不变。 |
| `ui/pages/settings_page_qt.py` | CLAP 模型目录与「是否存在」检查改为新目录 + 三个 onnx 及必要 json/txt；下载/删除目标为新目录。 |
| `runtime/bootstrap.py` 或 其他配置 | 若有硬编码 `clap-htsat-unfused` 路径，改为 `larger-clap-general`。 |
| 索引元数据（可选） | 增加 clap_model/embed_version，便于以后兼容与提示重建。 |

---

## 五、实施顺序建议

1. **下载与目录**：先改 `ModelDownloadWorker` 与设置页路径/检查逻辑，保证能下载并校验新模型与新文件。
2. **CLAP 推理**：再改 `clap_service.py`（双 session、输入输出、预处理），单元或脚本验证 get_audio_embedding / get_text_embedding。
3. **AI 检索页**：改模型目录并做集成测试（索引 + 搜索 + 打标）。
4. **索引与提示**：确定索引格式/元数据，必要时加「索引与当前模型不匹配请重建」的提示逻辑。

按上述顺序推进，可先完成「下载 + 加载 + 双路推理」，再统一改界面与索引逻辑，降低风险。
