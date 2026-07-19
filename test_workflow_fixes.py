"""测试工作流工具函数 — 验证项目知识加载、项目解析、意图检测等核心修改"""

import json
import os
import sys
import tempfile
import shutil
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

# ─── 测试 fixtures ───

@pytest.fixture
def temp_workspace(tmp_path):
    """创建临时 workspace 目录结构"""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "memory").mkdir()
    (workspace / "memory" / "episodic").mkdir()
    (workspace / "memory" / "semantic").mkdir()
    (workspace / "projects").mkdir()
    (workspace / "conversation_memory").mkdir()
    return workspace


@pytest.fixture
def sample_project_in_memory(temp_workspace):
    """在 workspace/memory/ 下创建示例项目知识"""
    proj_dir = temp_workspace / "memory" / "test_project"
    proj_dir.mkdir()
    project_data = {
        "project_name": "test_project",
        "project_path": "/fake/path/test_project",
        "framework": "Vue",
        "pages": [{"name": "Home"}, {"name": "About"}],
        "components": [{"name": "Header"}],
        "api_modules": [{"name": "user_api"}],
        "summary": "测试项目总结",
    }
    (proj_dir / "project.json").write_text(
        json.dumps(project_data, ensure_ascii=False), encoding="utf-8"
    )
    return temp_workspace


@pytest.fixture
def sample_project_in_projects(temp_workspace):
    """在 workspace/projects/ 下创建旧格式项目知识"""
    proj_dir = temp_workspace / "projects" / "old_project"
    proj_dir.mkdir()
    knowledge_data = {
        "framework": "React",
        "pages": [{"name": "Dashboard"}],
        "components": [],
        "api_modules": [],
    }
    (proj_dir / "knowledge.json").write_text(
        json.dumps(knowledge_data, ensure_ascii=False), encoding="utf-8"
    )
    return temp_workspace


@pytest.fixture
def multi_project_workspace(temp_workspace):
    """创建多个项目的 workspace"""
    # memory 下的项目 A（最新）
    proj_a = temp_workspace / "memory" / "project_a"
    proj_a.mkdir()
    (proj_a / "project.json").write_text(json.dumps({
        "project_name": "project_a",
        "project_path": "/path/a",
        "framework": "Vue",
        "pages": [],
    }, ensure_ascii=False), encoding="utf-8")

    # memory 下的项目 B（较旧）
    proj_b = temp_workspace / "memory" / "project_b"
    proj_b.mkdir()
    (proj_b / "project.json").write_text(json.dumps({
        "project_name": "project_b",
        "project_path": "/path/b",
        "framework": "React",
        "pages": [],
    }, ensure_ascii=False), encoding="utf-8")

    # projects 下的项目 C（旧格式）
    proj_c = temp_workspace / "projects" / "project_c"
    proj_c.mkdir()
    (proj_c / "knowledge.json").write_text(json.dumps({
        "framework": "Angular",
        "pages": [],
    }, ensure_ascii=False), encoding="utf-8")

    # 让 project_a 的修改时间最新
    import time
    old_time = time.time() - 3600
    os.utime(proj_b / "project.json", (old_time, old_time))

    return temp_workspace


# ─── 1. load_project_knowledge 测试 ───

class TestLoadProjectKnowledge:
    """测试项目知识加载路径修复"""

    def test_load_from_memory_dir(self, sample_project_in_memory):
        """从 workspace/memory/{name}/project.json 加载（主路径）"""
        ws = sample_project_in_memory
        with patch("app.workflows.utils.MEMORY_DIR", ws / "memory"), \
             patch("app.workflows.utils.PROJECTS_DIR", ws / "projects"):
            from app.workflows.utils import load_project_knowledge
            result = load_project_knowledge("test_project")
            assert result is not None
            assert result["project_name"] == "test_project"
            assert result["framework"] == "Vue"
            assert len(result["pages"]) == 2

    def test_load_from_projects_dir_fallback(self, sample_project_in_projects):
        """从 workspace/projects/{name}/knowledge.json 加载（旧格式回退）"""
        ws = sample_project_in_projects
        with patch("app.workflows.utils.MEMORY_DIR", ws / "memory"), \
             patch("app.workflows.utils.PROJECTS_DIR", ws / "projects"):
            from app.workflows.utils import load_project_knowledge
            result = load_project_knowledge("old_project")
            assert result is not None
            assert result["framework"] == "React"

    def test_memory_priority_over_projects(self, temp_workspace):
        """memory/ 路径优先级高于 projects/ 路径"""
        ws = temp_workspace
        # 在 memory/ 放 Vue 版本
        mem_dir = ws / "memory" / "dual_project"
        mem_dir.mkdir()
        (mem_dir / "project.json").write_text(json.dumps({
            "framework": "Vue", "pages": [],
        }), encoding="utf-8")
        # 在 projects/ 放 React 版本
        proj_dir = ws / "projects" / "dual_project"
        proj_dir.mkdir()
        (proj_dir / "knowledge.json").write_text(json.dumps({
            "framework": "React", "pages": [],
        }), encoding="utf-8")

        with patch("app.workflows.utils.MEMORY_DIR", ws / "memory"), \
             patch("app.workflows.utils.PROJECTS_DIR", ws / "projects"):
            from app.workflows.utils import load_project_knowledge
            result = load_project_knowledge("dual_project")
            assert result["framework"] == "Vue"  # 应优先返回 memory/ 的

    def test_load_nonexistent_project(self, temp_workspace):
        """加载不存在的项目返回 None"""
        ws = temp_workspace
        with patch("app.workflows.utils.MEMORY_DIR", ws / "memory"), \
             patch("app.workflows.utils.PROJECTS_DIR", ws / "projects"):
            from app.workflows.utils import load_project_knowledge
            result = load_project_knowledge("nonexistent")
            assert result is None

    def test_load_corrupted_json(self, temp_workspace):
        """损坏的 JSON 文件不崩溃，返回 None"""
        ws = temp_workspace
        proj_dir = ws / "memory" / "bad_project"
        proj_dir.mkdir()
        (proj_dir / "project.json").write_text("{invalid json!!", encoding="utf-8")

        with patch("app.workflows.utils.MEMORY_DIR", ws / "memory"), \
             patch("app.workflows.utils.PROJECTS_DIR", ws / "projects"):
            from app.workflows.utils import load_project_knowledge
            result = load_project_knowledge("bad_project")
            assert result is None


# ─── 2. list_existing_projects 测试 ───

class TestListExistingProjects:

    def test_list_merges_both_dirs(self, multi_project_workspace):
        """合并 memory/ 和 projects/ 两个目录的项目"""
        ws = multi_project_workspace
        with patch("app.workflows.utils.MEMORY_DIR", ws / "memory"), \
             patch("app.workflows.utils.PROJECTS_DIR", ws / "projects"):
            from app.workflows.utils import list_existing_projects
            projects = list_existing_projects()
            names = {p["name"] for p in projects}
            assert "project_a" in names
            assert "project_b" in names
            assert "project_c" in names

    def test_memory_projects_not_duplicated(self, temp_workspace):
        """同名项目不重复（memory 优先）"""
        ws = temp_workspace
        # memory 和 projects 都有 same_name
        (ws / "memory" / "same_name").mkdir()
        (ws / "memory" / "same_name" / "project.json").write_text(
            json.dumps({"framework": "Vue", "pages": []}), encoding="utf-8"
        )
        (ws / "projects" / "same_name").mkdir()
        (ws / "projects" / "same_name" / "knowledge.json").write_text(
            json.dumps({"framework": "React", "pages": []}), encoding="utf-8"
        )

        with patch("app.workflows.utils.MEMORY_DIR", ws / "memory"), \
             patch("app.workflows.utils.PROJECTS_DIR", ws / "projects"):
            from app.workflows.utils import list_existing_projects
            projects = list_existing_projects()
            same_projects = [p for p in projects if p["name"] == "same_name"]
            assert len(same_projects) == 1
            assert same_projects[0]["framework"] == "Vue"

    def test_excludes_episodic_semantic(self, temp_workspace):
        """排除 episodic/ 和 semantic/ 子目录"""
        ws = temp_workspace
        # episodic/ 和 semantic/ 已存在，不应出现在项目列表中
        with patch("app.workflows.utils.MEMORY_DIR", ws / "memory"), \
             patch("app.workflows.utils.PROJECTS_DIR", ws / "projects"):
            from app.workflows.utils import list_existing_projects
            projects = list_existing_projects()
            names = {p["name"] for p in projects}
            assert "episodic" not in names
            assert "semantic" not in names


# ─── 3. get_last_scanned_project 测试 ───

class TestGetLastScannedProject:

    def test_returns_most_recent(self, multi_project_workspace):
        """返回最近扫描的项目"""
        ws = multi_project_workspace
        with patch("app.workflows.utils.MEMORY_DIR", ws / "memory"), \
             patch("app.workflows.utils.PROJECTS_DIR", ws / "projects"):
            from app.workflows.utils import get_last_scanned_project
            name, path = get_last_scanned_project()
            assert name == "project_a"  # project_a 的 mtime 最新
            assert path == "/path/a"

    def test_returns_none_when_empty(self, temp_workspace):
        """空 workspace 返回 (None, None)"""
        ws = temp_workspace
        with patch("app.workflows.utils.MEMORY_DIR", ws / "memory"), \
             patch("app.workflows.utils.PROJECTS_DIR", ws / "projects"):
            from app.workflows.utils import get_last_scanned_project
            name, path = get_last_scanned_project()
            assert name is None
            assert path is None


# ─── 4. resolve_project_for_document 测试 ───

class TestResolveProjectForDocument:

    def test_resolve_from_query_path(self, temp_workspace):
        """从 query 中提取项目路径"""
        ws = temp_workspace
        with patch("app.workflows.utils.MEMORY_DIR", ws / "memory"), \
             patch("app.workflows.utils.PROJECTS_DIR", ws / "projects"):
            from app.workflows.utils import resolve_project_for_document
            name, path, knowledge = resolve_project_for_document(
                "分析 /Users/test/my_project 的需求"
            )
            assert name == "my_project"
            assert "/Users/test/my_project" in path

    def test_resolve_from_query_prefix(self, temp_workspace):
        """从 '项目路径:' 前缀提取"""
        ws = temp_workspace
        with patch("app.workflows.utils.MEMORY_DIR", ws / "memory"), \
             patch("app.workflows.utils.PROJECTS_DIR", ws / "projects"):
            from app.workflows.utils import resolve_project_for_document
            name, path, knowledge = resolve_project_for_document(
                "项目路径: /Users/test/some_project\n分析需求"
            )
            assert name == "some_project"

    def test_resolve_fallback_to_last_scanned(self, sample_project_in_memory):
        """空 query 回退到最近扫描的项目"""
        ws = sample_project_in_memory
        with patch("app.workflows.utils.MEMORY_DIR", ws / "memory"), \
             patch("app.workflows.utils.PROJECTS_DIR", ws / "projects"):
            from app.workflows.utils import resolve_project_for_document
            name, path, knowledge = resolve_project_for_document("")
            assert name == "test_project"
            assert knowledge is not None
            assert knowledge["framework"] == "Vue"

    def test_resolve_with_conv_id(self, sample_project_in_memory):
        """通过 conv_id 关联项目"""
        ws = sample_project_in_memory
        conv_mem_dir = ws / "conversation_memory"
        conv_mem_dir.mkdir(exist_ok=True)
        conv_data = {
            "conv_id": "test-conv-001",
            "current_project": "test_project",
            "project_path": "/fake/path/test_project",
            "updated_at": "2026-07-19 10:00:00",
        }
        (conv_mem_dir / "test-conv-001.json").write_text(
            json.dumps(conv_data, ensure_ascii=False), encoding="utf-8"
        )

        with patch("app.workflows.utils.MEMORY_DIR", ws / "memory"), \
             patch("app.workflows.utils.PROJECTS_DIR", ws / "projects"), \
             patch("app.services.conversation_project_memory.CONVERSATION_MEMORY_DIR", conv_mem_dir):
            from app.workflows.utils import resolve_project_for_document
            name, path, knowledge = resolve_project_for_document(
                "", conv_id="test-conv-001"
            )
            assert name == "test_project"
            assert knowledge is not None

    def test_resolve_priority_order(self, multi_project_workspace):
        """优先级：query路径 > conv_id > 文本匹配 > 最近扫描"""
        ws = multi_project_workspace
        with patch("app.workflows.utils.MEMORY_DIR", ws / "memory"), \
             patch("app.workflows.utils.PROJECTS_DIR", ws / "projects"):
            from app.workflows.utils import resolve_project_for_document
            # 空 query 无 conv_id → 回退到最近扫描
            name, _, _ = resolve_project_for_document("")
            assert name == "project_a"  # 最近扫描的


# ─── 5. _detect_intent 测试 ───

class TestDetectIntent:

    def test_document_only(self):
        """纯文件上传 → document"""
        from app.services.graph_service import _detect_intent
        assert _detect_intent("", has_uploaded_files=True) == "document"

    def test_project_only(self):
        """纯项目路径 → project"""
        from app.services.graph_service import _detect_intent
        assert _detect_intent("项目路径: /Users/test/proj", has_uploaded_files=False) == "project"

    def test_project_keyword(self):
        """项目关键词 → project"""
        from app.services.graph_service import _detect_intent
        assert _detect_intent("帮我扫描项目结构", has_uploaded_files=False) == "project"

    def test_document_plus_project(self):
        """文件上传 + 项目路径 → document+project"""
        from app.services.graph_service import _detect_intent
        result = _detect_intent(
            "项目路径: /Users/test/proj 分析需求", has_uploaded_files=True
        )
        assert result == "document+project"

    def test_document_plus_project_keyword(self):
        """文件上传 + 项目关键词 → document+project"""
        from app.services.graph_service import _detect_intent
        result = _detect_intent("扫描项目并分析文档", has_uploaded_files=True)
        assert result == "document+project"

    def test_chat_only(self):
        """普通问题 → chat"""
        from app.services.graph_service import _detect_intent
        assert _detect_intent("你好", has_uploaded_files=False) == "chat"

    def test_windows_path(self):
        """Windows 路径 → project"""
        from app.services.graph_service import _detect_intent
        assert _detect_intent("D:/projects/myapp", has_uploaded_files=False) == "project"


# ─── 6. 端到端流程模拟测试 ───

class TestEndToEndFlow:
    """模拟用户操作流程"""

    def test_flow_scan_then_document(self, sample_project_in_memory):
        """流程：先扫描项目 → 再上传文档分析（空query）"""
        ws = sample_project_in_memory
        with patch("app.workflows.utils.MEMORY_DIR", ws / "memory"), \
             patch("app.workflows.utils.PROJECTS_DIR", ws / "projects"):
            from app.workflows.utils import resolve_project_for_document

            # 模拟第二步：上传文档，空 query
            name, path, knowledge = resolve_project_for_document(
                query="",
                conv_id=None,
                project_name=None,
            )
            assert name == "test_project", "应回退到最近扫描的项目"
            assert knowledge is not None, "应加载到项目知识"
            assert knowledge["framework"] == "Vue"

    def test_flow_document_with_explicit_path(self, temp_workspace):
        """流程：上传文档 + 显式指定项目路径（项目无知识）"""
        ws = temp_workspace
        with patch("app.workflows.utils.MEMORY_DIR", ws / "memory"), \
             patch("app.workflows.utils.PROJECTS_DIR", ws / "projects"):
            from app.workflows.utils import resolve_project_for_document

            name, path, knowledge = resolve_project_for_document(
                query="项目路径: /Users/test/new_project\n分析需求文档",
            )
            assert name == "new_project"
            assert path == "/Users/test/new_project"
            assert knowledge is None  # 没有知识，document_workflow 会触发扫描

    def test_flow_both_uploaded(self, sample_project_in_memory):
        """流程：同时上传文档+项目 → 复合意图"""
        from app.services.graph_service import _detect_intent

        # 验证意图检测
        intent = _detect_intent(
            "项目路径: /Users/test/test_project 分析需求",
            has_uploaded_files=True,
        )
        assert intent == "document+project"

        # 验证项目知识可加载
        ws = sample_project_in_memory
        with patch("app.workflows.utils.MEMORY_DIR", ws / "memory"), \
             patch("app.workflows.utils.PROJECTS_DIR", ws / "projects"):
            from app.workflows.utils import resolve_project_for_document
            name, _, knowledge = resolve_project_for_document(
                "项目路径: /fake/path/test_project 分析需求"
            )
            assert name == "test_project"
            assert knowledge is not None



# ─── 7. 文档持久化测试 ───

class TestDocumentPersistence:
    """测试上传文档持久化到 workspace/docs/"""

    def test_persist_text_document(self, tmp_path):
        """上传文本文件保存到 workspace/docs/"""
        ws = tmp_path / "workspace"
        ws.mkdir()
        with patch("app.services.chat_service.WORKSPACE", ws):
            from app.services.chat_service import _persist_uploaded_documents
            files = [{"type": "text", "filename": "需求文档.xlsx", "content": "Sheet1: 数据看板..."}]
            saved = _persist_uploaded_documents(files, conv_id="test-001")
            assert len(saved) == 1
            # 验证文件已写入
            docs_dir = ws / "docs"
            assert docs_dir.exists()
            md_files = list(docs_dir.glob("*.md"))
            assert len(md_files) == 1
            content = md_files[0].read_text(encoding="utf-8")
            assert "需求文档.xlsx" in content  # 元信息包含原始文件名
            assert "数据看板" in content  # 内容已保存

    def test_persist_multiple_documents(self, tmp_path):
        """多个文件同时保存"""
        ws = tmp_path / "workspace"
        ws.mkdir()
        with patch("app.services.chat_service.WORKSPACE", ws):
            from app.services.chat_service import _persist_uploaded_documents
            files = [
                {"type": "text", "filename": "doc1.txt", "content": "内容1"},
                {"type": "text", "filename": "doc2.txt", "content": "内容2"},
            ]
            saved = _persist_uploaded_documents(files)
            assert len(saved) == 2

    def test_persist_skips_empty_content(self, tmp_path):
        """空内容文件不保存"""
        ws = tmp_path / "workspace"
        ws.mkdir()
        with patch("app.services.chat_service.WORKSPACE", ws):
            from app.services.chat_service import _persist_uploaded_documents
            files = [{"type": "text", "filename": "empty.txt", "content": ""}]
            saved = _persist_uploaded_documents(files)
            assert len(saved) == 0


# ─── 8. 文档引用加载测试 ───

class TestDocumentReferenceLoading:
    """测试 '结合文档' query 能加载最近文档"""

    def test_mentions_documents_detection(self):
        """检测 query 是否提及文档"""
        from app.services.graph_service import _mentions_documents
        assert _mentions_documents("结合文档分析需要修改的功能") is True
        assert _mentions_documents("需求文档中有哪些功能") is True
        assert _mentions_documents("刚刚上传的文档内容") is True
        assert _mentions_documents("你好") is False
        assert _mentions_documents("扫描项目结构") is False

    def test_load_recent_documents(self, tmp_path):
        """从 workspace/docs/ 加载最近文档"""
        ws = tmp_path / "workspace"
        docs_dir = ws / "docs"
        docs_dir.mkdir(parents=True)
        # 写入模拟文档
        doc_content = "---\nfilename: 需求规格.xlsx\nuploaded_at: 2026-07-19T15:00:00\n---\n\n## 功能需求\n1. 数据看板"
        (docs_dir / "20260719_150000_需求规格xlsx.md").write_text(doc_content, encoding="utf-8")

        with patch("app.services.graph_service.WORKSPACE", ws):
            from app.services.graph_service import _load_recent_documents
            result = _load_recent_documents()
            assert "需求规格" in result
            assert "数据看板" in result

    def test_load_recent_documents_empty(self, tmp_path):
        """无文档时返回空字符串"""
        ws = tmp_path / "workspace"
        ws.mkdir()
        with patch("app.services.graph_service.WORKSPACE", ws):
            from app.services.graph_service import _load_recent_documents
            result = _load_recent_documents()
            assert result == ""


# ─── 9. 意图检测增强测试 ───

class TestDetectIntentEnhanced:
    """测试修复后的意图检测"""

    def test_users_path_detected_as_project(self):
        """/Users/... 路径正确识别为 project"""
        from app.services.graph_service import _detect_intent
        result = _detect_intent(
            "结合项目分析：/Users/jpang/Documents/agent/gt-agent/workspace/projects/天津三院HCC专病库",
            has_uploaded_files=False,
        )
        assert result == "project"

    def test_home_path_detected_as_project(self):
        """/home/... 路径正确识别为 project"""
        from app.services.graph_service import _detect_intent
        result = _detect_intent("分析 /home/user/my_project 的结构", has_uploaded_files=False)
        assert result == "project"

    def test_combine_project_keyword(self):
        """'结合项目' 关键词识别为 project"""
        from app.services.graph_service import _detect_intent
        result = _detect_intent("结合项目分析功能修改", has_uploaded_files=False)
        assert result == "project"

    def test_combine_code_keyword(self):
        """'结合代码' 关键词识别为 project"""
        from app.services.graph_service import _detect_intent
        result = _detect_intent("结合代码分析需求", has_uploaded_files=False)
        assert result == "project"


# ─── 10. Session 上下文增强测试 ───

class TestSessionEnhanced:
    """测试 session 历史 token 预算增大"""

    def test_max_history_tokens_increased(self):
        """token 预算已增大到 16000"""
        from agent.session import _MAX_HISTORY_TOKENS
        assert _MAX_HISTORY_TOKENS == 16000

    def test_max_tool_result_chars_increased(self):
        """工具结果字符限制已增大到 15000"""
        from agent.session import _MAX_TOOL_RESULT_CHARS
        assert _MAX_TOOL_RESULT_CHARS == 15000


# ─── 11. ContextBuilder 文档提示测试 ───

class TestContextBuilderDocsHint:
    """测试 system prompt 包含已上传文档提示"""

    def test_docs_hint_in_system_prompt(self, tmp_path):
        """有文档时 system prompt 包含文档列表"""
        ws = tmp_path
        docs_dir = ws / "docs"
        docs_dir.mkdir()
        (docs_dir / "20260719_test.md").write_text(
            "---\nfilename: 测试文档.xlsx\n---\n\n文档内容",
            encoding="utf-8",
        )

        from agent.context_builder import ContextBuilder, BuildContext
        builder = ContextBuilder(ws)
        ctx = BuildContext()
        prompt = builder.build_system_prompt(ctx)
        assert "测试文档.xlsx" in prompt
        assert "已上传文档" in prompt

    def test_no_docs_hint_when_empty(self, tmp_path):
        """无文档时 system prompt 不包含文档段落"""
        ws = tmp_path
        # 不创建 docs/ 目录

        from agent.context_builder import ContextBuilder, BuildContext
        builder = ContextBuilder(ws)
        ctx = BuildContext()
        prompt = builder.build_system_prompt(ctx)
        assert "已上传文档" not in prompt


# ─── 12. 端到端流程测试 ───

class TestEndToEndDocumentFlow:
    """端到端：上传文档 → 后续引用"""

    def test_upload_then_reference(self, tmp_path):
        """上传文档后，后续 query 引用文档能加载"""
        ws = tmp_path / "workspace"
        docs_dir = ws / "docs"
        docs_dir.mkdir(parents=True)

        # 模拟第一步：上传文档
        with patch("app.services.chat_service.WORKSPACE", ws):
            from app.services.chat_service import _persist_uploaded_documents
            files = [{"type": "text", "filename": "PRD.xlsx", "content": "## 需求\n1. 数据看板功能"}]
            saved = _persist_uploaded_documents(files, conv_id="conv-001")
            assert len(saved) == 1

        # 模拟第二步：引用文档
        with patch("app.services.graph_service.WORKSPACE", ws):
            from app.services.graph_service import _mentions_documents, _load_recent_documents
            assert _mentions_documents("结合需求文档分析需要修改的功能") is True
            doc_content = _load_recent_documents()
            assert "数据看板" in doc_content
            assert "PRD" in doc_content


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
