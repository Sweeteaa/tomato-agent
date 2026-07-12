from pathlib import Path
from io import BytesIO
from app.config import WORKSPACE


def _extract_docx_content(file_content: bytes) -> str:
    try:
        from docx import Document
        doc = Document(BytesIO(file_content))
        return "\n".join([paragraph.text for paragraph in doc.paragraphs if paragraph.text.strip()])
    except Exception as e:
        return f"无法读取Word文档: {str(e)}"


def _extract_xlsx_content(file_content: bytes) -> str:
    try:
        from openpyxl import load_workbook
        wb = load_workbook(BytesIO(file_content), read_only=True)
        content = []
        for sheet_name in wb.sheetnames:
            sheet = wb[sheet_name]
            rows = []
            for row in sheet.iter_rows(values_only=True):
                row_str = "\t".join([str(cell) if cell else "" for cell in row])
                if row_str.strip():
                    rows.append(row_str)
            if rows:
                content.append(f"=== Sheet: {sheet_name} ===")
                content.extend(rows)
        wb.close()
        return "\n".join(content)
    except Exception as e:
        return f"无法读取Excel文档: {str(e)}"


def _extract_image_info(file_content: bytes, filename: str) -> str:
    try:
        from PIL import Image
        img = Image.open(BytesIO(file_content))
        info = f"图片: {filename}\n尺寸: {img.size}\n格式: {img.format}\n模式: {img.mode}"
        img.close()
        return info
    except Exception as e:
        return f"无法读取图片: {str(e)}"


def extract_file_content(file_content: bytes, filename: str) -> str:
    lower_name = filename.lower()
    if lower_name.endswith(".docx"):
        return _extract_docx_content(file_content)
    elif lower_name.endswith(".xlsx"):
        return _extract_xlsx_content(file_content)
    elif lower_name.endswith((".jpg", ".jpeg", ".png", ".gif", ".bmp")):
        return _extract_image_info(file_content, filename)
    elif lower_name.endswith(".txt"):
        return file_content.decode("utf-8", errors="ignore")
    elif lower_name.endswith(".md"):
        return file_content.decode("utf-8", errors="ignore")
    else:
        return f"无法解析文件类型: {filename}"


def upload_file(file_content: bytes, filename: str):
    upload_dir = WORKSPACE / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    file_path = upload_dir / filename
    file_path.write_bytes(file_content)
    
    content = extract_file_content(file_content, filename)
    
    return {
        "status": "uploaded",
        "file": filename,
        "size": len(file_content),
        "content": content
    }


def search_workspace(query: str):
    results = []
    target_dirs = ["memory", "projects", "tasks"]
    for dir_name in target_dirs:
        dir_path = WORKSPACE / dir_name
        if not dir_path.exists():
            continue
        for f in dir_path.rglob("*.md"):
            content = f.read_text(encoding="utf-8", errors="ignore")
            if query.lower() in content.lower():
                results.append({
                    "path": str(f.relative_to(WORKSPACE)),
                    "type": dir_name,
                    "match": query
                })
    return {"query": query, "results": results}


def build_context(query: str) -> str:
    results = []
    target_dirs = ["memory", "projects", "tasks", "skill"]
    for dir_name in target_dirs:
        dir_path = WORKSPACE / dir_name
        if not dir_path.exists():
            continue
        for f in dir_path.rglob("*.md"):
            content = f.read_text(encoding="utf-8", errors="ignore")
            if query.lower() in content.lower():
                content_preview = content[:500] + "..." if len(content) > 500 else content
                results.append(f"【{dir_name}/{f.name}】\n{content_preview}\n")
    return "\n".join(results)