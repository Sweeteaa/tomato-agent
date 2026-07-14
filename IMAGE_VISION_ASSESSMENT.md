# 图片识别能力评估报告

## 一、当前状态诊断

### 1.1 已有的基础设施

| 环节 | 现状 | 是否需要改动 |
|------|------|-------------|
| 前端上传 (index.html) | 已支持拖拽+点击上传，accept 已含 .jpg/.png/.gif | **无需改动** |
| API 接口 (/api/chat) | 已接收 `list[UploadFile]`，图片二进制已进入后端 | **无需改动** |
| file_service.py | `_extract_image_info()` 用 PIL 提取元数据（尺寸/格式/模式） | **需改造** |
| chat_service.py | 文件内容拼接为纯文本字符串，图片只传了元数据描述 | **需改造** |
| graph_service.py | LLM 调用全部使用 `content: "string"` 纯文本格式 | **需改造** |
| config.py | 模型为 `qwen-plus`（纯文本模型，不支持视觉理解） | **需换模型** |
| requirements.txt | openai SDK + pillow 已安装 | **无需新增** |

### 1.2 核心问题

当前图片处理链路的致命缺陷：

```
图片二进制 → PIL 提取元数据 → "图片: photo.jpg\n尺寸: 1920x1080\n格式: JPEG"
→ 拼接进 query 字符串 → 作为纯文本发给 qwen-plus → LLM 只看到"尺寸: 1920x1080"
```

**LLM 从未看到图片实际内容，只看到了一段元数据描述。**

---

## 二、两个功能模块的难度评估

### 功能 A：独立图片上传识别

**难度：低 | 改动量：50-80 行 | 涉及文件：3 个**

#### 改动点详情

**1. config.py（1 行）**
```python
# 当前
MODEL_NAME = "qwen-plus"
# 改为
MODEL_NAME = "qwen-vl-plus"          # 视觉理解模型
VL_MODEL_NAME = "qwen-vl-plus"       # 可选：图片专用，文本任务仍用 qwen-plus
```

**2. file_service.py（新增约 15 行）**
```python
import base64

IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp")
MIME_MAP = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
            ".gif": "image/gif", ".bmp": "image/bmp", ".webp": "image/webp"}

def is_image_file(filename: str) -> bool:
    return filename.lower().endswith(IMAGE_EXTENSIONS)

def encode_image_to_base64(file_content: bytes, filename: str) -> dict:
    mime = MIME_MAP.get(Path(filename).suffix.lower(), "image/jpeg")
    b64 = base64.b64encode(file_content).decode("utf-8")
    return {"mime": mime, "data": b64, "filename": filename}
```

**3. chat_service.py（修改约 20 行）**
```python
# 在 chat_with_agent_stream() 中分流图片文件
image_list = []
file_info = []
if files:
    for file in files:
        if is_image_file(file["filename"]):
            img_data = await asyncio.to_thread(encode_image_to_base64, file["content"], file["filename"])
            image_list.append(img_data)
        else:
            content = await asyncio.to_thread(extract_file_content, file["content"], file["filename"])
            file_info.append(f"【文件: {file['filename']}】\n{content}\n")

# 传递给 graph_service
async for event in run_graph_stream(query_with_context, conv_id, images=image_list):
    ...
```

**4. graph_service.py（修改约 15 行）**
```python
async def run_graph_stream(query: str, conv_id: Optional[str] = None,
                           images: Optional[list[dict]] = None):
    ...
    # 在 has_uploaded_files 分支中，构建多模态 messages
    if images:
        user_content = [{"type": "text", "text": direct_prompt}]
        for img in images:
            # 大图压缩：超过 2MB 的图片先 resize
            user_content.append({
                "type": "image_url",
                "image_url": {"url": f"data:{img['mime']};base64,{img['data']}"}
            })
        messages = [{"role": "system", "content": "你是一个专业的开发助手"},
                    {"role": "user", "content": user_content}]
    else:
        messages = [{"role": "system", "content": "你是一个专业的开发助手"},
                    {"role": "user", "content": direct_prompt}]
```

#### 注意事项
- `qwen-vl-plus` 通过 DashScope OpenAI 兼容模式调用，`content` 格式完全兼容 OpenAI 多模态标准
- 大图建议压缩到 1920x1080 以下（减少 token 消耗和延迟）
- 建议限制单次上传图片数量（如 5 张），避免 token 爆炸

---

### 功能 B：文档内图片识别（docx）

**难度：中等 | 改动量：100-150 行 | 涉及文件：2 个**

#### 核心挑战

docx 文件本质是 ZIP 压缩包，图片存储在 `word/media/` 目录。当前 `_extract_docx_content()` 只用 `python-docx` 提取了段落文本，完全忽略了内嵌图片。

#### 改动方案

**1. file_service.py — 新增 docx 图片提取函数（约 50 行）**

```python
def _extract_docx_with_images(file_content: bytes) -> tuple[str, list[dict]]:
    """提取 docx 文本和内嵌图片。
    
    返回: (文本内容, [{"mime": "image/png", "data": "base64...", "position": 3}, ...])
    """
    import zipfile
    from docx import Document
    
    doc = Document(BytesIO(file_content))
    text_parts = []
    images = []
    
    # 提取文本
    for para in doc.paragraphs:
        if para.text.strip():
            text_parts.append(para.text)
    
    # 从 ZIP 中提取内嵌图片
    zf = zipfile.ZipFile(BytesIO(file_content))
    image_files = [f for f in zf.namelist() if f.startswith("word/media/")]
    
    for img_path in image_files:
        img_data = zf.read(img_path)
        ext = Path(img_path).suffix.lower()
        mime = MIME_MAP.get(ext, "image/jpeg")
        b64 = base64.b64encode(img_data).decode("utf-8")
        images.append({"mime": mime, "data": b64, "source": img_path})
    
    zf.close()
    return "\n".join(text_parts), images
```

**2. chat_service.py — 修改文件处理流程（约 30 行）**

需要将 docx 提取出的图片也加入 `image_list`，并将图片数量信息附在文本中。

**3. graph_service.py — 与功能 A 共用多模态 messages 逻辑**

#### 额外复杂度
- **图片-文本位置关联**：python-docx 不直接暴露图片在文档中的位置。需要解析 `word/document.xml` 中 `<w:drawing>` 标签的相对位置，才能知道"第 3 段后面有一张图"
- **多图 token 控制**：一个 docx 可能有 10+ 张图片，每张 base64 约 1000-3000 tokens，需要限制提取数量或压缩
- **xlsx 内嵌图片**：Excel 也可包含图片，但更难提取（存储在 `xl/media/`），建议第一阶段不支持

---

## 三、所需外部能力

### 3.1 模型能力

| 能力 | 当前 | 需要 | 说明 |
|------|------|------|------|
| 文本理解 | qwen-plus | qwen-plus（保留） | 文本任务无需变化 |
| 图片理解 | 无 | **qwen-vl-plus** | DashScope 视觉语言模型 |
| 高精度图片理解 | 无 | qwen-vl-max（可选） | 更强但更贵，适合 OCR/图表分析 |

**关键结论：不需要额外的 API Key 或账号。** DashScope 同一 Key 下，只需改 `model` 参数即可调用 `qwen-vl-plus`。

#### 模型选择建议

```
方案 1（推荐）：双模型路由
- 图片相关请求 → qwen-vl-plus
- 纯文本请求 → qwen-plus（不变）
- 优点：不增加文本任务成本，按需使用视觉模型

方案 2：全量切换
- 所有请求 → qwen-vl-plus
- 优点：简单，一处改动
- 缺点：qwen-vl-plus 文本能力略弱于 qwen-plus，且调用成本更高
```

### 3.2 Python 依赖

| 依赖 | 状态 | 用途 |
|------|------|------|
| openai (AsyncOpenAI) | **已安装** | LLM 调用，原生支持多模态 messages |
| pillow (PIL) | **已安装** | 图片压缩/格式转换 |
| python-docx | **已安装** | docx 文本提取 |
| zipfile | **标准库** | 解压 docx 提取内嵌图片 |

**结论：无需新增任何 Python 依赖。**

### 3.3 网络与配额

- DashScope API 调用方式不变（同样的 base_url、api_key）
- `qwen-vl-plus` 的计费方式与 `qwen-plus` 类似，按 token 计费
- 图片 token 计算：每张图约 1000-3000 tokens（取决于分辨率），需注意配额消耗

---

## 四、风险评估

| 风险 | 影响 | 概率 | 缓解措施 |
|------|------|------|----------|
| 大图导致 token 爆炸 | API 超时/费用高 | 高 | 上传前用 PIL 压缩到 1920x1080 |
| qwen-vl-plus 文本能力下降 | Agent 规划质量降低 | 中 | 双模型路由，文本任务仍用 qwen-plus |
| docx 图片位置丢失 | LLM 无法关联图文 | 中 | 简化处理：先提取所有图片+文本，让 LLM 自行关联 |
| 多图 SSE 延迟增大 | 用户体验下降 | 中 | 限制单次图片数量（3-5 张） |
| has_uploaded_files 检测失效 | 图片请求走了错误分支 | 低 | 新增图片检测标记，不依赖文本匹配 |

---

## 五、实施建议

### 推荐分两阶段实施

**第一阶段（1-2 小时）：独立图片识别**
1. config.py 新增 `VL_MODEL_NAME`
2. file_service.py 新增 `is_image_file()` + `encode_image_to_base64()`
3. chat_service.py 分流图片文件
4. graph_service.py 多模态 messages 支持
5. 测试：上传一张截图，验证 LLM 能描述图片内容

**第二阶段（2-3 小时）：文档内图片识别**
1. file_service.py 新增 `_extract_docx_with_images()`
2. chat_service.py 对接 docx 图片提取
3. 图片压缩 + 数量限制逻辑
4. 测试：上传含图片的 docx，验证图片内容被识别

### 整体评估

- **技术可行性**：高。所有基础设施已就绪，改动集中且明确
- **实现难度**：功能 A 低，功能 B 中等
- **外部依赖**：仅需切换 DashScope 模型名称，无新增服务/SDK
- **推荐优先实施功能 A**：投入产出比最高，80% 的用户场景（截图/照片）可覆盖
